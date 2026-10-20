import React, { useCallback, useEffect, useRef, useState } from 'react'
import { LoadingState } from '../components/States'
import { Modal, Empty, toast, toastOk, toastErr, focusAndScroll } from '../components/UI'
import { netdiskApi } from '../api/client'
import {
  getTokenStatus, fetchRemoteFiles, getAuthUrl, exchangeToken, logoutPan, getQuarkView,
} from '../utils/pan'
import { fmtFileSize, fmtDateCN } from '../utils/date'
import { Cloud, Folder, RefreshCw, Download, ChevronRight, X } from '../components/Icon'

/* ============================================================
 * 网盘联动（#netdisk-refactor 重构）
 *
 * 交互流程（状态机 view: select → baidu / quark）：
 *   ① select  未授权：只渲染平台选择卡（百度网盘 / 夸克网盘）+ 授权按钮，
 *               **禁止出现任何目录/文件** —— 旧版拿 localStorage 残留 token
 *               当门禁、又把本地同步缓存混进列表，"没连接也显示目录"的 bug
 *               就是这么来的；现在门禁只认后端 /netdisk/token-status。
 *   ② 百度网盘：OAuth（oob 手动授权码）→ 后端换 token → 进入文件浏览器。
 *   ③ 文件浏览器：逐级进入文件夹 + 面包屑导航，数据只取百度真实列表。
 *   ④ 文件点击 → 右侧预览面板：图片 <img> / PDF <iframe> / 视频 <video>
 *      / 音频 <audio> / 文本 <pre> / docx（mammoth 转 HTML）。
 *   ⑤ 下载与预览都走后端代理 /api/netdisk/content（百度 dlink 强制 UA，
 *      浏览器直连必 403）。
 *   夸克网盘：无官方开放 API，采用配置化 Web 视图嵌入（见 getQuarkView）。
 * ============================================================ */

const VIDEO_EXT = /\.(mp4|mkv|webm|mov|avi|flv|wmv|m4v)$/i
const AUDIO_EXT = /\.(mp3|wav|m4a|flac|aac|ogg)$/i
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|svg)$/i
const PDF_EXT = /\.pdf$/i
const TEXT_EXT = /\.(txt|md|markdown|csv|log|json)$/i
const DOCX_EXT = /\.docx$/i

function fileKind(name) {
  const n = name || ''
  if (VIDEO_EXT.test(n)) return 'video'
  if (AUDIO_EXT.test(n)) return 'audio'
  if (IMAGE_EXT.test(n)) return 'image'
  if (PDF_EXT.test(n)) return 'pdf'
  if (TEXT_EXT.test(n)) return 'text'
  if (DOCX_EXT.test(n)) return 'docx'
  return 'other'
}

const KIND_ICON = { video: '视频', audio: '音频', image: '图片', pdf: '教材', text: '文档', docx: '教材', other: '文档' }
const KIND_LABEL = { video: '视频', audio: '音频', image: '图片', pdf: 'PDF', text: '文本', docx: 'Word 文档', other: '文件' }

/** 面包屑：根目录 / 各级目录名，可点击回跳。 */
function Breadcrumb({ dir, onNavigate }) {
  const segs = String(dir || '/').split('/').filter(Boolean)
  return (
    <nav className="pan-crumb" aria-label="目录导航">
      <button className="pan-crumb-item" onClick={() => onNavigate('/')}>根目录</button>
      {segs.map((s, i) => {
        const p = `/${segs.slice(0, i + 1).join('/')}`
        const last = i === segs.length - 1
        return (
          <React.Fragment key={p}>
            <ChevronRight size={13} className="pan-crumb-sep" />
            {last
              ? <span className="pan-crumb-item current" title={s}>{s}</span>
              : <button className="pan-crumb-item" onClick={() => onNavigate(p)} title={s}>{s}</button>}
          </React.Fragment>
        )
      })}
    </nav>
  )
}

/** 右侧文件预览面板：图片/PDF/视频/音频/文本/docx，其余仅提供下载。 */
function FilePreview({ file, onClose }) {
  const kind = fileKind(file.name)
  const inlineUrl = netdiskApi.contentUrlByFsid(file.fs_id)
  const dlUrl = netdiskApi.contentUrlByFsid(file.fs_id, 'attachment')
  const [text, setText] = useState('')
  const [docxHtml, setDocxHtml] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [ingesting, setIngesting] = useState(false)

  useEffect(() => {
    /* 卸载后不得再 setState：docx 分支要动态 import mammoth（几百 KB），
       用户在加载期间关闭预览面板就会触发
       "ReferenceError: window is not defined / setState on unmounted"，
       在测试里表现为 unhandled rejection（实测）。 */
    let alive = true
    setText(''); setDocxHtml(''); setError('')
    if (kind === 'text') {
      setLoading(true)
      fetch(inlineUrl)
        .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((v) => { if (alive) setText(v) })
        .catch((e) => { if (alive) setError(String(e?.message || e)) })
        .finally(() => { if (alive) setLoading(false) })
    } else if (kind === 'docx') {
      setLoading(true)
      ;(async () => {
        try {
          const resp = await fetch(inlineUrl)
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
          const arrayBuffer = await resp.arrayBuffer()
          // mammoth 只在需要预览 docx 时才加载，不进首屏包体。
          // 注意入参键名是 buffer：该版本 openZip 只认 path/buffer/file，
          // 传 arrayBuffer 会被当成"没给文件"而 reject。
          const mod = await import('mammoth')
          const mammoth = mod.default?.convertToHtml ? mod.default : mod
          const r = await mammoth.convertToHtml({ buffer: arrayBuffer })
          if (alive) setDocxHtml(r.value || '')
        } catch (e) {
          if (alive) setError(String(e?.message || e))
        } finally {
          if (alive) setLoading(false)
        }
      })()
    }
    return () => { alive = false }
  }, [file.fs_id, kind, inlineUrl]) // eslint-disable-line react-hooks/exhaustive-deps

  const ingest = async () => {
    setIngesting(true)
    try {
      const r = await netdiskApi.ingest(file.fs_id)
      toast(r?.message || '已入库到知识库')
    } catch (e) {
      toast(`入库失败：${e?.message || '未知错误'}`)
    } finally {
      setIngesting(false)
    }
  }

  return (
    <div className="panel pan2-preview">
      <div className="panel-head">
        <h3 className="panel-title">文件预览</h3>
        <button className="modal-close" onClick={onClose} aria-label="关闭预览"><X size={14} /></button>
      </div>
      <div className="pv-name" title={file.path}>{file.name}</div>
      <div className="pv-meta">
        <span>{KIND_LABEL[kind]}</span>
        <span>{fmtFileSize(file.size_kb)}</span>
        {file.date ? <span>{fmtDateCN(file.date)}</span> : null}
      </div>
      <div className="pv-stage">
        {kind === 'image' && <img className="pv-img" src={inlineUrl} alt={file.name} />}
        {kind === 'pdf' && <iframe className="pv-frame" src={inlineUrl} title={file.name} />}
        {kind === 'video' && (
          <video className="pv-video" src={inlineUrl} controls preload="metadata" playsInline />
        )}
        {kind === 'audio' && <audio className="pv-audio" src={inlineUrl} controls preload="metadata" />}
        {kind === 'text' && (
          loading ? <LoadingState text="读取中…" rows={2} />
            : error ? <p className="pan-error">读取失败：{error}</p>
              : <pre className="pv-pre">{text}</pre>
        )}
        {kind === 'docx' && (
          loading ? <p className="pan-hint">正在转换文档…</p>
            : error ? <p className="pan-error">文档预览失败：{error}（可下载后查看）</p>
              // mammoth 输出为受控 HTML 映射，本地可信文档场景可用
              : <div className="pv-doc" dangerouslySetInnerHTML={{ __html: docxHtml }} />
        )}
        {kind === 'other' && <p className="pan-hint">该类型暂不支持在线预览，请下载后查看</p>}
      </div>
      <div className="pv-actions">
        <button className="btn primary" onClick={() => window.open(dlUrl, '_blank')}>
          <Download size={14} /> 下载
        </button>
        <button className="btn ghost" onClick={ingest} disabled={ingesting}>
          {ingesting ? '入库中…' : '入库到知识库'}
        </button>
      </div>
    </div>
  )
}

export default function Pan() {
  /* ---- 视图状态机：select 平台选择 / baidu 文件浏览器 / quark Web 视图 ---- */
  const [view, setView] = useState('select')
  /* ---- 授权状态：唯一事实来源是后端 token-status，不信 localStorage ---- */
  const [tokenStatus, setTokenStatus] = useState(null)
  const [statusLoading, setStatusLoading] = useState(true)

  /* ---- 平台配置（"配置入口灵活化"）：百度 app_key + 夸克 web_view_url ---- */
  const [platformCfgs, setPlatformCfgs] = useState({})
  const loadCfgs = useCallback(() => {
    netdiskApi.platformConfigs()
      .then((d) => setPlatformCfgs(d?.configs || {}))
      .catch(() => setPlatformCfgs({}))
  }, [])
  useEffect(() => { loadCfgs() }, [loadCfgs])

  /* 挂载即校验后端授权状态：已授权且未过期才直接进文件浏览器 */
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const st = await getTokenStatus()
        if (!alive) return
        setTokenStatus(st)
        if (st?.authorized && st?.expired !== true) setView('baidu')
      } catch (e) {
        toastErr(`网盘状态获取失败：${e?.message || '请检查后端服务'}`)
      } finally {
        if (alive) setStatusLoading(false)
      }
    })()
    return () => { alive = false }
  }, [])

  const baiduAuthorized = !!tokenStatus?.authorized && tokenStatus?.expired !== true

  /* ---- 百度文件浏览器 ---- */
  const [dir, setDir] = useState('/')
  const [entries, setEntries] = useState([])
  const [browseLoading, setBrowseLoading] = useState(false)
  const [browseError, setBrowseError] = useState('')
  const [selected, setSelected] = useState(null)

  const loadDir = useCallback(async (path) => {
    setBrowseLoading(true)
    setBrowseError('')
    try {
      const list = await fetchRemoteFiles(path)
      setEntries(list)
      setDir(path)
      setSelected(null)
      return true
    } catch (e) {
      if (e?.status === 401 || e?.data?.action === 'reauthorize') {
        // 授权失效：回平台选择页要求重新授权，绝不用本地缓存冒充目录。
        // 后端 2026-10-18 起返回 409（避免撞上 session 401 刷新机制被踢下线），
        // 这里以 action 语义为准，401 兼容旧版本后端。
        setTokenStatus((s) => ({ ...(s || {}), authorized: false, expired: true }))
        setEntries([]); setSelected(null)
        setView('select')
        toastErr('百度网盘授权已失效，请重新授权')
        return 'auth'
      } else {
        setBrowseError(e?.message || '目录读取失败')
        return false
      }
    } finally {
      setBrowseLoading(false)
    }
  }, [])

  useEffect(() => { if (view === 'baidu') loadDir('/') }, [view, loadDir]) // eslint-disable-line

  /* 手动刷新目录：成功绿色 / 失败红色，失败原因同时留在目录区 */
  const refreshDir = async (path) => {
    const r = await loadDir(path)
    if (r === true) toastOk('目录已刷新')
    else if (r === false) toastErr('目录读取失败，请稍后重试')
    // 'auth'：授权失效分支已单独提示，不重复弹
  }

  /* ---- OAuth 授权（oob：授权页显示授权码，手动粘回） ---- */
  const [showAuth, setShowAuth] = useState(false)
  const [authUrl, setAuthUrl] = useState('')
  const [authCode, setAuthCode] = useState('')
  const authCodeRef = useRef(null)
  const [authBusy, setAuthBusy] = useState(false)

  const startAuth = async () => {
    try {
      const url = await getAuthUrl()
      setAuthUrl(url)
      setShowAuth(true)
    } catch (e) {
      toast(e?.message || '获取授权链接失败')
    }
  }
  const submitAuthCode = async () => {
    const code = authCode.trim()
    if (!code) {
      toastErr('请输入授权码')
      focusAndScroll(authCodeRef.current)
      return
    }
    setAuthBusy(true)
    try {
      await exchangeToken(code)
      const st = await getTokenStatus()
      setTokenStatus(st)
      setShowAuth(false)
      setAuthCode('')
      if (st?.authorized && st?.expired !== true) {
        setView('baidu')
        toast('百度网盘授权成功')
      } else {
        toast('授权未生效，请重试')
      }
    } catch (e) {
      toast(e?.message || '授权失败')
    } finally {
      setAuthBusy(false)
    }
  }
  const doLogout = async () => {
    try { await logoutPan() } catch { /* 后端不可用时也放行本地退出 */ }
    setTokenStatus((s) => ({ ...(s || {}), authorized: false }))
    setEntries([]); setSelected(null)
    setView('select')
    toast('已退出百度网盘授权')
  }

  /* ---- 百度 API 配置弹窗（app_key / secret_key / redirect_uri） ---- */
  const [showCfg, setShowCfg] = useState(false)
  const [cfgForm, setCfgForm] = useState({ app_key: '', secret_key: '', redirect_uri: 'oob' })
  const [cfgSaving, setCfgSaving] = useState(false)
  const baiduCfg = platformCfgs.baidu || {}
  // P0-SEC：后端不再下发 app_key/secret_key 原值，只回 has_* 状态位
  const baiduReady = !!(baiduCfg.has_app_key && baiduCfg.has_secret_key)

  const openCfg = () => {
    // 密钥是只写字段：GET 拿不到原值，所以表单一律留空，
    // 留空提交在后端解释为「不修改」（见 PUT /netdisk/platform-config/{platform}）。
    setCfgForm({
      app_key: '',
      secret_key: '',
      redirect_uri: baiduCfg.redirect_uri || 'oob',
    })
    setShowCfg(true)
  }
  const saveCfg = async () => {
    setCfgSaving(true)
    try {
      await netdiskApi.updatePlatformConfig('baidu', {
        app_key: cfgForm.app_key.trim(),
        secret_key: cfgForm.secret_key.trim(),
        redirect_uri: cfgForm.redirect_uri.trim() || 'oob',
      })
      toastOk('百度网盘 API 配置已保存')
      setShowCfg(false)
      loadCfgs()
    } catch (e) {
      toastErr(`保存失败：${e?.message || '未知错误'}`)
    } finally {
      setCfgSaving(false)
    }
  }

  /* ---- 夸克 Web 视图（无官方 API，配置化嵌入） ---- */
  const [quark, setQuark] = useState(null)
  const [quarkLoading, setQuarkLoading] = useState(false)
  const [showQuarkCfg, setShowQuarkCfg] = useState(false)
  const [quarkForm, setQuarkForm] = useState({ web_view_url: '' })
  const [quarkSaving, setQuarkSaving] = useState(false)

  const enterQuark = async () => {
    setQuarkLoading(true)
    try {
      const v = await getQuarkView()
      setQuark(v)
      setQuarkForm({ web_view_url: v?.url || '' })
      setView('quark')
    } catch (e) {
      toast(e?.message || '夸克网盘配置读取失败')
    } finally {
      setQuarkLoading(false)
    }
  }
  const openQuarkCfg = () => {
    setQuarkForm({ web_view_url: quark?.url || platformCfgs.quark?.web_view_url || 'https://pan.quark.cn/' })
    setShowQuarkCfg(true)
  }
  const saveQuarkCfg = async () => {
    setQuarkSaving(true)
    try {
      await netdiskApi.updatePlatformConfig('quark', { web_view_url: quarkForm.web_view_url.trim() })
      toastOk('夸克网盘 Web 视图地址已保存')
      setShowQuarkCfg(false)
      loadCfgs()
      const v = await getQuarkView()
      setQuark(v)
    } catch (e) {
      toastErr(`保存失败：${e?.message || '未知错误'}`)
    } finally {
      setQuarkSaving(false)
    }
  }

  if (statusLoading) {
    return (
      <div className="pan2">
        <div className="panel"><p className="pan-hint">正在读取网盘授权状态…</p></div>
      </div>
    )
  }

  const parentDir = dir === '/' ? '/' : (dir.slice(0, dir.lastIndexOf('/')) || '/')

  return (
    <div className="pan2">
      {/* ===== 头部 ===== */}
      <div className="pan2-head">
        <div>
          <div className="pan2-title">网盘联动</div>
          <div className="pan2-sub">选择网盘平台并授权，即可浏览云端学习资料 · 支持逐级目录、文件预览与视频播放</div>
        </div>
        {view !== 'select' && (
          <button className="btn ghost" onClick={() => { setView('select'); setSelected(null) }}>← 切换平台</button>
        )}
      </div>

      {/* ===== ① 平台选择（未授权：只有平台卡 + 授权按钮，没有任何目录） ===== */}
      {view === 'select' && (
        <div className="provider-grid">
          <div className={`provider-card ${baiduAuthorized ? 'connected' : ''}`}>
            <div className="provider-ico"><Cloud size={20} /></div>
            <div className="provider-name">百度网盘</div>
            <div className="provider-desc">官方 OAuth 授权 · 授权后可浏览目录、预览与下载文件</div>
            <span className={`provider-pill ${baiduAuthorized ? 'on' : 'off'}`}>
              {baiduAuthorized ? '已连接' : '未连接'}
            </span>
            <div className="provider-btns">
              <button className="provider-btn ghost" onClick={openCfg}>API 配置</button>
              {baiduAuthorized ? (
                <>
                  <button className="provider-btn primary" onClick={() => setView('baidu')}>进入网盘</button>
                  <button className="provider-btn ghost" onClick={doLogout}>退出授权</button>
                </>
              ) : (
                <button
                  className="provider-btn primary"
                  onClick={startAuth}
                  disabled={!baiduReady}
                  title={baiduReady ? '' : '请先配置百度网盘 AppKey / SecretKey'}
                >去授权</button>
              )}
            </div>
            {!baiduReady && (
              <div className="provider-hint">
                尚未配置 API 密钥：点击「API 配置」填写百度开放平台申请的 AppKey / SecretKey 后即可授权。
              </div>
            )}
            {tokenStatus?.expired && baiduAuthorized === false && tokenStatus?.authorized && (
              <div className="provider-hint">授权已过期，请重新「去授权」。</div>
            )}
          </div>

          <div className="provider-card">
            <div className="provider-ico"><Cloud size={20} /></div>
            <div className="provider-name">夸克网盘</div>
            <div className="provider-desc">Web 视图嵌入 · 夸克未开放官方 API，登录态由浏览器维护</div>
            <span className="provider-pill off">Web 视图</span>
            <div className="provider-btns">
              <button className="provider-btn ghost" onClick={openQuarkCfg}>配置</button>
              <button className="provider-btn primary" onClick={enterQuark} disabled={quarkLoading}>
                {quarkLoading ? '读取配置…' : '进入网盘'}
              </button>
            </div>
            <div className="provider-hint">
              夸克网盘暂无官方文件 API，本方案将网页版以内嵌视图呈现；地址可在「配置」中修改。
            </div>
          </div>
        </div>
      )}

      {/* ===== ②③④ 百度网盘文件浏览器（授权后才出现） ===== */}
      {view === 'baidu' && (
        <div className="pan2-body">
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">
                <Folder size={16} style={{ verticalAlign: -3, marginRight: 'var(--space-2)' }} />百度网盘文件
              </h3>
              <div className="panel-head-btns">
                <button className="btn ghost" onClick={() => refreshDir(dir)} disabled={browseLoading}>
                  <RefreshCw size={14} /> 刷新
                </button>
                <button className="btn ghost" onClick={doLogout}>退出授权</button>
              </div>
            </div>

            <div className="pan-crumb-bar">
              <button
                className="btn ghost pan-up"
                onClick={() => loadDir(parentDir)}
                disabled={dir === '/' || browseLoading}
              >⬆ 上级</button>
              <Breadcrumb dir={dir} onNavigate={(p) => loadDir(p)} />
            </div>

            {browseLoading ? (
              <p className="pan-hint">正在读取百度网盘…</p>
            ) : browseError ? (
              <p className="pan-error">{browseError}</p>
            ) : entries.length === 0 ? (
              <Empty icon={<span style={{ fontSize: 'var(--text-2xl)' }}>目录</span>} title="当前目录暂无文件" desc="点击「上级」或面包屑返回其他目录"
                action={<button className="btn ghost" onClick={() => refreshDir('/')}>回到根目录</button>} />
            ) : (
              <div className="pan-file-list">
                {entries.map((f) => (
                  <div
                    key={f.fs_id || f.path}
                    className={`pan-file-row ${selected && selected.fs_id === f.fs_id ? 'active' : ''}`}
                    onClick={() => (f.isdir ? loadDir(f.path) : setSelected(f))}
                  >
                    <span className="pan-file-ico">{f.isdir ? '文件夹' : KIND_ICON[fileKind(f.name)]}</span>
                    <div className="pan-file-main">
                      <div className="pan-file-name" title={f.path}>{f.name}</div>
                      <div className="pan-file-meta">
                        {f.isdir ? '文件夹' : `${fmtFileSize(f.size_kb)}${f.date ? ` · ${fmtDateCN(f.date)}` : ''}`}
                      </div>
                    </div>
                    {!f.isdir && <span className="pan-file-go">预览 ›</span>}
                  </div>
                ))}
              </div>
            )}
          </div>

          {selected ? (
            <FilePreview file={selected} onClose={() => setSelected(null)} />
          ) : (
            <div className="panel pan-empty-side">
              <Empty icon={<span style={{ fontSize: 'var(--text-2xl)' }}>操作</span>} title="点击文件即可预览" desc="图片 / PDF / 视频 / 文档均支持在线查看" />
            </div>
          )}
        </div>
      )}

      {/* ===== 夸克网盘 Web 视图 ===== */}
      {view === 'quark' && (
        <div className="panel">
          <div className="panel-head">
            <h3 className="panel-title">
              <Cloud size={16} style={{ verticalAlign: -3, marginRight: 'var(--space-2)' }} />夸克网盘（Web 视图）
            </h3>
            <div className="panel-head-btns">
              <button className="btn ghost" onClick={openQuarkCfg}>配置地址</button>
              <button className="btn ghost" onClick={() => window.open(quark?.url, '_blank', 'noopener')}>新窗口打开</button>
            </div>
          </div>
          <p className="pan-note">
            夸克网盘未开放官方 API（无 OAuth、无文件列表接口），本方案为配置化 Web 视图嵌入：下方内嵌网页的登录状态由浏览器 Cookie 维护；
            若站点禁止被 iframe 嵌入导致白屏，请点击右上角「新窗口打开」。嵌入地址可在「配置地址」中修改（仅支持 http/https）。
          </p>
          {quark?.defaulted && (
            <p className="pan-note">当前使用默认地址 {quark.url}，你可以在「配置地址」中改成自己的分享页/目录页。</p>
          )}
          <iframe
            className="pan-quark-frame"
            src={quark?.url || 'https://pan.quark.cn/'}
            title="夸克网盘"
            referrerPolicy="no-referrer"
          />
        </div>
      )}

      {/* ===== 授权弹窗（oob 手动授权码） ===== */}
      <Modal open={showAuth} title="授权百度网盘" onClose={() => setShowAuth(false)}
        footer={<>
          <button className="btn ghost" onClick={() => setShowAuth(false)}>取消</button>
          <button className="btn primary" onClick={submitAuthCode} disabled={authBusy}>
            {authBusy ? '正在换取…' : '完成授权'}
          </button>
        </>}>
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--fg-2)', lineHeight: 1.8, marginBottom: 'var(--space-3)' }}>
          点击下方按钮跳转百度网盘授权页，登录并同意授权后，<strong>复制页面显示的授权码（code）</strong>粘贴到下方输入框。
          授权成功后自动进入文件浏览器。
        </p>
        <a href={authUrl} target="_blank" rel="noreferrer" className="btn primary"
          style={{ textDecoration: 'none', display: 'inline-flex', marginBottom: 'var(--space-3)' }}>前往百度网盘授权</a>
        <label style={{ display: 'block', fontSize: 'var(--text-sm)' }}>授权码（code）
          <input className="input" style={{ width: '100%', marginTop: 'var(--space-1)', padding: 'var(--space-2) var(--space-3)', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2)' }}
            value={authCode} onChange={(e) => setAuthCode(e.target.value)} placeholder="粘贴授权码" ref={authCodeRef} />
        </label>
      </Modal>

      {/* ===== 百度 API 配置弹窗 ===== */}
      <Modal open={showCfg} title="百度网盘 API 配置" onClose={() => setShowCfg(false)}
        footer={<>
          <button className="btn ghost" onClick={() => setShowCfg(false)}>取消</button>
          <button className="btn primary" onClick={saveCfg} disabled={cfgSaving}>{cfgSaving ? '保存中…' : '保存'}</button>
        </>}>
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', lineHeight: 1.7, marginBottom: 'var(--space-3)' }}>
          填入你在百度开放平台（pan.baidu.com/union）申请的 AppKey / SecretKey。
          密钥是只写字段：保存后由后端加密落库，任何接口都不会再回显原值，
          <b>留空提交表示保持原值不变</b>。当前：{baiduReady ? '已配置' : '未配置'}。
        </p>
        <label style={{ display: 'block', marginBottom: 'var(--space-3)', fontSize: 'var(--text-sm)' }}>App Key（client_id）
          <input className="input" style={{ width: '100%', marginTop: 'var(--space-1)', padding: 'var(--space-2) var(--space-3)', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2)' }}
            value={cfgForm.app_key} onChange={(e) => setCfgForm({ ...cfgForm, app_key: e.target.value })}
            placeholder={baiduReady ? '已配置，留空则不修改' : '如：xxxxxxxxxxxxxxxx'} />
        </label>
        <label style={{ display: 'block', marginBottom: 'var(--space-3)', fontSize: 'var(--text-sm)' }}>Secret Key（client_secret）
          <input className="input" type="password" style={{ width: '100%', marginTop: 'var(--space-1)', padding: 'var(--space-2) var(--space-3)', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2)' }}
            value={cfgForm.secret_key} onChange={(e) => setCfgForm({ ...cfgForm, secret_key: e.target.value })}
            placeholder={baiduReady ? '已配置，留空则不修改' : '如：xxxxxxxxxxxxxxxx'} />
        </label>
        <label style={{ display: 'block', fontSize: 'var(--text-sm)' }}>回调地址（redirect_uri）
          <input className="input" style={{ width: '100%', marginTop: 'var(--space-1)', padding: 'var(--space-2) var(--space-3)', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2)' }}
            value={cfgForm.redirect_uri} onChange={(e) => setCfgForm({ ...cfgForm, redirect_uri: e.target.value })} placeholder="oob（默认，表示授权后手动复制授权码）" />
        </label>
      </Modal>

      {/* ===== 夸克 Web 视图配置弹窗 ===== */}
      <Modal open={showQuarkCfg} title="夸克网盘 Web 视图配置" onClose={() => setShowQuarkCfg(false)}
        footer={<>
          <button className="btn ghost" onClick={() => setShowQuarkCfg(false)}>取消</button>
          <button className="btn primary" onClick={saveQuarkCfg} disabled={quarkSaving}>{quarkSaving ? '保存中…' : '保存'}</button>
        </>}>
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', lineHeight: 1.7, marginBottom: 'var(--space-3)' }}>
          夸克网盘未开放官方 API，此处配置要嵌入的网页地址（默认 pan.quark.cn 首页，也可填具体分享页）。
          仅支持 http/https 地址；登录状态由浏览器 Cookie 维护。
        </p>
        <label style={{ display: 'block', fontSize: 'var(--text-sm)' }}>Web 视图地址
          <input className="input" style={{ width: '100%', marginTop: 'var(--space-1)', padding: 'var(--space-2) var(--space-3)', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2)' }}
            value={quarkForm.web_view_url} onChange={(e) => setQuarkForm({ web_view_url: e.target.value })}
            placeholder="https://pan.quark.cn/" />
        </label>
      </Modal>
    </div>
  )
}
