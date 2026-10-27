import React, { useCallback, useEffect, useRef, useState } from 'react'
import { netdiskApi } from '../../api/client'
import {
  getTokenStatus, fetchRemoteFiles, getAuthUrl, exchangeToken, logoutPan, getQuarkView,
} from '../../utils/pan'
import { fmtFileSize, fmtDateCN } from '../../utils/date'
import {
  Alert, Badge, Button, Card, Dialog, Empty, Field, IconButton, Input, LoadingState,
  PageHeader, SectionHead, focusAndScroll, toast, toastErr, toastOk,
} from '../ui'
import {
  AlertCircle, ArrowUpRight, ChevronLeft, ChevronRight, Cloud, Download,
  FileText, Folder, FolderOpen, HardDrive, Image, KeyRound, Music, RefreshCw,
  Video, X,
} from '../icons'
import { useAuth } from '../../auth/AuthContext'
import '../styles/aux-v3.css'

/* ============================================================
 * 网盘联动 · Aurora v3
 *
 * 状态机 view: select → baidu / quark
 *   ① select  只认后端 token-status，未授权时不渲染任何目录；
 *   ② baidu   OAuth（oob 手动授权码）→ 后端换 token → 文件浏览器；
 *   ③ 文件浏览器逐级进入，右侧预览/下载/入库；
 *   ④ quark   无官方 API，配置化 Web 视图嵌入。
 * 所有取流都走后端代理，百度 dlink 浏览器直连必 403。
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

const KIND_META = {
  video: { label: '视频', Icon: Video },
  audio: { label: '音频', Icon: Music },
  image: { label: '图片', Icon: Image },
  pdf: { label: 'PDF', Icon: FileText },
  text: { label: '文本', Icon: FileText },
  docx: { label: 'Word 文档', Icon: FileText },
  other: { label: '文件', Icon: FileText },
}

/** 面包屑：根目录 / 各级目录名，可点击回跳。 */
function Breadcrumb({ dir, onNavigate }) {
  const segs = String(dir || '/').split('/').filter(Boolean)
  return (
    <nav className="pan-crumb v3-pan-crumb" aria-label="目录导航">
      <button type="button" className="pan-crumb-item" onClick={() => onNavigate('/')}>根目录</button>
      {segs.map((s, i) => {
        const p = `/${segs.slice(0, i + 1).join('/')}`
        const last = i === segs.length - 1
        return (
          <React.Fragment key={p}>
            <ChevronRight size={13} className="pan-crumb-sep" />
            {last
              ? <span className="pan-crumb-item current" title={s}>{s}</span>
              : <button type="button" className="pan-crumb-item" onClick={() => onNavigate(p)} title={s}>{s}</button>}
          </React.Fragment>
        )
      })}
    </nav>
  )
}

/** 右侧文件预览面板：图片/PDF/视频/音频/文本/docx，其余仅下载。 */
function FilePreview({ file, onClose }) {
  const { isAdmin } = useAuth()
  const kind = fileKind(file.name)
  const inlineUrl = netdiskApi.contentUrlByFsid(file.fs_id)
  const dlUrl = netdiskApi.contentUrlByFsid(file.fs_id, 'attachment')
  const [text, setText] = useState('')
  const [docxHtml, setDocxHtml] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [ingesting, setIngesting] = useState(false)

  useEffect(() => {
    /* 卸载后不得再 setState：docx 分支动态 import mammoth（几百 KB），
       用户在加载期间关闭面板也必须安全退出。 */
    let alive = true
    setText('')
    setDocxHtml('')
    setError('')
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
          // mammoth 只在需要预览 docx 时加载；入参键名必须是 buffer。
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

  const meta = KIND_META[kind]
  return (
    <div className="panel pan2-preview v3-pan-preview">
      <div className="v3-pan-preview__head">
        <div className="v3-pan-preview__title">
          <span className="v3-pan-preview__title-icon"><FileText size={17} /></span>
          文件预览
        </div>
        <IconButton label="关闭预览" size="sm" icon={<X size={17} />} onClick={onClose} />
      </div>

      <div className="pv-name v3-pan-preview__name" title={file.path}>{file.name}</div>
      <div className="pv-meta v3-pan-preview__meta">
        <span>{meta.label}</span>
        <span>{fmtFileSize(file.size_kb)}</span>
        {file.date ? <span>{fmtDateCN(file.date)}</span> : null}
      </div>

      <div className="pv-stage v3-pan-preview__stage">
        {kind === 'image' && <img className="pv-img" src={inlineUrl} alt={file.name} />}
        {kind === 'pdf' && <iframe className="pv-frame" src={inlineUrl} title={file.name} />}
        {kind === 'video' && (
          <video className="pv-video" src={inlineUrl} controls preload="metadata" playsInline />
        )}
        {kind === 'audio' && <audio className="pv-audio" src={inlineUrl} controls preload="metadata" />}
        {kind === 'text' && (
          loading ? <LoadingState text="读取中…" />
            : error ? <p className="pan-error v3-pan-error">读取失败：{error}</p>
              : <pre className="pv-pre">{text}</pre>
        )}
        {kind === 'docx' && (
          loading ? <LoadingState text="正在转换文档…" />
            : error ? <p className="pan-error v3-pan-error">文档预览失败：{error}（可下载后查看）</p>
              : <div className="pv-doc" dangerouslySetInnerHTML={{ __html: docxHtml }} />
        )}
        {kind === 'other' && <p className="pan-hint v3-pan-hint">该类型暂不支持在线预览，请下载后查看</p>}
      </div>

      <div className="pv-actions v3-pan-preview__actions">
        <Button
          variant="gradient"
          size="sm"
          icon={<Download size={15} />}
          onClick={() => window.open(dlUrl, '_blank')}
        >
          下载
        </Button>
        {isAdmin ? (
          <Button variant="tonal" size="sm" loading={ingesting} onClick={ingest}>
            {ingesting ? '入库中…' : '入库到知识库'}
          </Button>
        ) : (
          <span className="v3-caption">入库由管理员操作</span>
        )}
      </div>
    </div>
  )
}

export default function Pan() {
  const { isAdmin } = useAuth()
  /* ---- 视图状态机：select 平台选择 / baidu 文件浏览器 / quark Web 视图 ---- */
  const [view, setView] = useState('select')
  /* ---- 授权状态：唯一事实来源是后端 token-status，不信 localStorage ---- */
  const [tokenStatus, setTokenStatus] = useState(null)
  const [statusLoading, setStatusLoading] = useState(true)

  /* ---- 平台配置 ---- */
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
        // 后端 2026-10-18 起返回 409 + action=reauthorize，401 兼容旧版本。
        setTokenStatus((s) => ({ ...(s || {}), authorized: false, expired: true }))
        setEntries([])
        setSelected(null)
        setView('select')
        toastErr('百度网盘授权已失效，请重新授权')
        return 'auth'
      }
      setBrowseError(e?.message || '目录读取失败')
      return false
    } finally {
      setBrowseLoading(false)
    }
  }, [])

  useEffect(() => { if (view === 'baidu') loadDir('/') }, [view, loadDir]) // eslint-disable-line

  /* 手动刷新目录：成功绿色 / 失败红色，授权失效分支已单独提示 */
  const refreshDir = async (path) => {
    const r = await loadDir(path)
    if (r === true) toastOk('目录已刷新')
    else if (r === false) toastErr('目录读取失败，请稍后重试')
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
    setEntries([])
    setSelected(null)
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
    // 密钥是只写字段：GET 拿不到原值，表单一律留空，留空提交 = 保持原值。
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

  const parentDir = dir === '/' ? '/' : (dir.slice(0, dir.lastIndexOf('/')) || '/')

  return (
    <div className="v3-aux-page v3-pan">
      <PageHeader
        eyebrow="NETDISK · 云端资料"
        title="网盘联动"
        sub={isAdmin
          ? '选择网盘平台并授权，即可浏览云端学习资料 · 支持逐级目录、文件预览与视频播放'
          : '浏览与下载管理员已授权的云端学习资料 · 支持逐级目录、文件预览与视频播放'}
        actions={!statusLoading && view !== 'select' ? (
          <Button
            variant="ghost"
            icon={<ChevronLeft size={16} />}
            onClick={() => { setView('select'); setSelected(null) }}
          >
            切换平台
          </Button>
        ) : null}
      />

      {!isAdmin ? (
        <Alert tone="info">
          网盘凭据由管理员维护：可浏览、预览与下载已授权网盘中的资料；授权、API 配置与入库由管理员操作。
        </Alert>
      ) : null}

      {statusLoading ? (
        <Card className="v3-pan-status">
          <LoadingState text="正在读取网盘授权状态…" />
        </Card>
      ) : (
        <>
          {/* ===== ① 平台选择（未授权：只有平台卡 + 授权按钮） ===== */}
          {view === 'select' && (
            <section className="v3-pan-select">
              <SectionHead
                title="选择网盘平台"
                sub="授权状态由后端实时校验，未连接时不会展示任何目录"
              />
              <div className="v3-pan-providers">
                <Card className={`v3-pan-provider ${baiduAuthorized ? 'is-connected' : ''}`}>
                  <span className="v3-pan-provider__glow" aria-hidden="true" />
                  <div className="v3-pan-provider__top">
                    <div className="v3-pan-provider__identity">
                      <span className="v3-pan-provider__logo is-baidu"><Cloud size={26} /></span>
                      <div>
                        <h2>百度网盘</h2>
                        <p>官方 OAuth 授权 · 授权后可浏览目录、预览与下载文件</p>
                      </div>
                    </div>
                    <Badge tone={baiduAuthorized ? 'success' : 'outline'} className="v3-pan-pill">
                      {baiduAuthorized ? '已连接' : '未连接'}
                    </Badge>
                  </div>

                  <div className="v3-pan-provider__facts">
                    <div><span>接入方式</span><strong>OAuth 2.0</strong></div>
                    <div><span>文件能力</span><strong>浏览 · 预览 · 下载</strong></div>
                    <div><span>知识库</span><strong>一键入库</strong></div>
                  </div>

                  <div className="v3-pan-provider__actions">
                    {isAdmin ? (
                      <Button variant="tonal" size="sm" icon={<KeyRound size={15} />} onClick={openCfg}>
                        API 配置
                      </Button>
                    ) : null}
                    {baiduAuthorized ? (
                      <>
                        <Button variant="gradient" size="sm" onClick={() => setView('baidu')}>进入网盘</Button>
                        {isAdmin ? (
                          <Button variant="ghost" size="sm" onClick={doLogout}>退出授权</Button>
                        ) : null}
                      </>
                    ) : isAdmin ? (
                      <Button
                        variant="gradient"
                        size="sm"
                        onClick={startAuth}
                        disabled={!baiduReady}
                        title={baiduReady ? '' : '请先配置百度网盘 AppKey / SecretKey'}
                      >
                        去授权
                      </Button>
                    ) : (
                      <span className="v3-caption">网盘授权由管理员维护</span>
                    )}
                  </div>

                  {!baiduReady && (
                    <div className="v3-pan-provider__hint is-warn">
                      {isAdmin
                        ? '尚未配置 API 密钥：点击「API 配置」填写百度开放平台申请的 AppKey / SecretKey 后即可授权。'
                        : '管理员尚未完成百度网盘 API 配置，暂时无法浏览云端资料。'}
                    </div>
                  )}
                  {tokenStatus?.expired && baiduAuthorized === false && tokenStatus?.authorized && (
                    <div className="v3-pan-provider__hint is-warn">
                      {isAdmin ? '授权已过期，请重新「去授权」。' : '授权已过期，请联系管理员重新授权。'}
                    </div>
                  )}
                </Card>

                <Card className="v3-pan-provider is-quark">
                  <span className="v3-pan-provider__glow" aria-hidden="true" />
                  <div className="v3-pan-provider__top">
                    <div className="v3-pan-provider__identity">
                      <span className="v3-pan-provider__logo is-quark"><HardDrive size={26} /></span>
                      <div>
                        <h2>夸克网盘</h2>
                        <p>Web 视图嵌入 · 夸克未开放官方 API，登录态由浏览器维护</p>
                      </div>
                    </div>
                    <Badge tone="outline" className="v3-pan-pill">Web 视图</Badge>
                  </div>

                  <div className="v3-pan-provider__facts">
                    <div><span>接入方式</span><strong>Web 嵌入</strong></div>
                    <div><span>登录态</span><strong>浏览器 Cookie</strong></div>
                    <div><span>官方 API</span><strong>暂未开放</strong></div>
                  </div>

                  <div className="v3-pan-provider__actions">
                    {isAdmin ? (
                      <Button variant="tonal" size="sm" icon={<KeyRound size={15} />} onClick={openQuarkCfg}>配置</Button>
                    ) : null}
                    <Button variant="gradient" size="sm" loading={quarkLoading} onClick={enterQuark}>
                      {quarkLoading ? '读取配置…' : '进入网盘'}
                    </Button>
                  </div>

                  <div className="v3-pan-provider__hint">
                    {isAdmin
                      ? '夸克网盘暂无官方文件 API，本方案将网页版以内嵌视图呈现；地址可在「配置」中修改。'
                      : '夸克网盘暂无官方文件 API，以内嵌网页视图呈现；嵌入地址由管理员维护。'}
                  </div>
                </Card>
              </div>
            </section>
          )}

          {/* ===== ②③④ 百度网盘文件浏览器（授权后才出现） ===== */}
          {view === 'baidu' && (
            <div className="v3-pan-body">
              <Card className="v3-pan-browser">
                <div className="v3-pan-panel__head">
                  <div className="v3-pan-panel__identity">
                    <span className="v3-pan-panel__icon"><Folder size={19} /></span>
                    <div>
                      <h2>百度网盘文件</h2>
                      <div className="v3-pan-panel__sub">
                        {browseLoading ? '正在同步云端目录…' : `当前目录 ${entries.length} 项`}
                      </div>
                    </div>
                  </div>
                  <div className="v3-pan-panel__actions">
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<RefreshCw size={15} />}
                      onClick={() => refreshDir(dir)}
                      disabled={browseLoading}
                    >
                      刷新
                    </Button>
                    {isAdmin ? (
                      <Button variant="ghost" size="sm" onClick={doLogout}>退出授权</Button>
                    ) : null}
                  </div>
                </div>

                <div className="pan-crumb-bar v3-pan-crumb-bar">
                  <button
                    type="button"
                    className="v3-btn v3-btn--tonal v3-btn--sm pan-up"
                    onClick={() => loadDir(parentDir)}
                    disabled={dir === '/' || browseLoading}
                  >
                    ⬆ 上级
                  </button>
                  <Breadcrumb dir={dir} onNavigate={(p) => loadDir(p)} />
                </div>

                {browseLoading ? (
                  <div className="v3-pan-state">
                    <LoadingState text="正在读取百度网盘…" />
                  </div>
                ) : browseError ? (
                  <div className="v3-pan-state">
                    <Empty
                      icon={<AlertCircle size={26} />}
                      title="目录读取失败"
                      text={browseError}
                      action={<Button variant="tonal" size="sm" onClick={() => refreshDir(dir)}>重新读取</Button>}
                    />
                  </div>
                ) : entries.length === 0 ? (
                  <div className="v3-pan-state">
                    <Empty
                      icon={<FolderOpen size={26} />}
                      title="当前目录暂无文件"
                      text="点击「上级」或面包屑返回其他目录"
                      action={<Button variant="outline" size="sm" onClick={() => refreshDir('/')}>回到根目录</Button>}
                    />
                  </div>
                ) : (
                  <div className="pan-file-list v3-pan-file-list">
                    {entries.map((f) => {
                      const kind = f.isdir ? 'folder' : fileKind(f.name)
                      const Icon = f.isdir ? Folder : KIND_META[kind].Icon
                      return (
                        <div
                          key={f.fs_id || f.path}
                          className={`pan-file-row v3-pan-file-row ${selected && selected.fs_id === f.fs_id ? 'active' : ''}`}
                          role="button"
                          tabIndex={0}
                          aria-label={f.isdir ? `进入文件夹 ${f.name}` : `预览 ${f.name}`}
                          onClick={() => (f.isdir ? loadDir(f.path) : setSelected(f))}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              if (f.isdir) loadDir(f.path)
                              else setSelected(f)
                            }
                          }}
                        >
                          <span className={`pan-file-ico v3-pan-file-ico is-${kind}`}><Icon size={19} /></span>
                          <div className="pan-file-main">
                            <div className="pan-file-name" title={f.path}>{f.name}</div>
                            <div className="pan-file-meta">
                              {f.isdir ? '文件夹' : `${fmtFileSize(f.size_kb)}${f.date ? ` · ${fmtDateCN(f.date)}` : ''}`}
                            </div>
                          </div>
                          {!f.isdir && (
                            <span className="pan-file-go">预览 <ChevronRight size={14} /></span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </Card>

              {selected ? (
                <FilePreview file={selected} onClose={() => setSelected(null)} />
              ) : (
                <Card className="v3-pan-side-empty">
                  <Empty
                    icon={<FileText size={26} />}
                    title="点击文件即可预览"
                    text="图片 / PDF / 视频 / 文档均支持在线查看"
                  />
                </Card>
              )}
            </div>
          )}

          {/* ===== 夸克网盘 Web 视图 ===== */}
          {view === 'quark' && (
            <Card className="v3-pan-quark">
              <div className="v3-pan-panel__head">
                <div className="v3-pan-panel__identity">
                  <span className="v3-pan-panel__icon is-quark"><HardDrive size={19} /></span>
                  <div>
                    <h2>夸克网盘（Web 视图）</h2>
                    <div className="v3-pan-panel__sub">登录状态由浏览器 Cookie 维护</div>
                  </div>
                </div>
                <div className="v3-pan-panel__actions">
                  {isAdmin ? (
                    <Button variant="ghost" size="sm" icon={<KeyRound size={15} />} onClick={openQuarkCfg}>配置地址</Button>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<ArrowUpRight size={15} />}
                    onClick={() => window.open(quark?.url || 'https://pan.quark.cn/', '_blank', 'noopener')}
                  >
                    新窗口打开
                  </Button>
                </div>
              </div>

              <p className="v3-pan-note">
                夸克网盘未开放官方 API（无 OAuth、无文件列表接口），本方案为配置化 Web 视图嵌入：下方内嵌网页的登录状态由浏览器 Cookie 维护；
                若站点禁止被 iframe 嵌入导致白屏，请点击右上角「新窗口打开」。
                {isAdmin ? '嵌入地址可在「配置地址」中修改（仅支持 http/https）。' : '嵌入地址由管理员维护。'}
              </p>
              {quark?.defaulted && (
                <p className="v3-pan-note is-accent">
                  当前使用默认地址 {quark.url}，你可以在「配置地址」中改成自己的分享页/目录页。
                </p>
              )}
              <iframe
                className="pan-quark-frame"
                src={quark?.url || 'https://pan.quark.cn/'}
                title="夸克网盘"
                referrerPolicy="no-referrer"
              />
            </Card>
          )}
        </>
      )}

      {/* ===== 授权弹窗（oob 手动授权码） ===== */}
      <Dialog
        open={showAuth}
        title="授权百度网盘"
        sub="OAuth 2.0 · 授权码模式"
        onClose={() => setShowAuth(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowAuth(false)}>取消</Button>
            <Button variant="gradient" onClick={submitAuthCode} loading={authBusy}>
              {authBusy ? '正在换取…' : '完成授权'}
            </Button>
          </>
        )}
      >
        <p className="v3-pan-dialog-note">
          点击下方按钮跳转百度网盘授权页，登录并同意授权后，<strong>复制页面显示的授权码（code）</strong>粘贴到下方输入框。
          授权成功后自动进入文件浏览器。
        </p>
        <a href={authUrl} target="_blank" rel="noreferrer" className="v3-pan-auth-link">
          <Cloud size={16} />
          前往百度网盘授权
          <ArrowUpRight size={15} />
        </a>
        <Field label="授权码（code）" htmlFor="v3-pan-auth-code">
          <Input
            id="v3-pan-auth-code"
            ref={authCodeRef}
            icon={<KeyRound size={16} />}
            value={authCode}
            onChange={(e) => setAuthCode(e.target.value)}
            placeholder="粘贴授权码"
            autoComplete="off"
          />
        </Field>
      </Dialog>

      {/* ===== 百度 API 配置弹窗 ===== */}
      <Dialog
        open={showCfg}
        title="百度网盘 API 配置"
        sub="密钥只写不回显，全部由后端加密保存"
        onClose={() => setShowCfg(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowCfg(false)}>取消</Button>
            <Button variant="gradient" onClick={saveCfg} loading={cfgSaving}>
              {cfgSaving ? '保存中…' : '保存'}
            </Button>
          </>
        )}
      >
        <p className="v3-pan-dialog-note">
          填入你在百度开放平台（pan.baidu.com/union）申请的 AppKey / SecretKey。
          密钥是只写字段：保存后由后端加密落库，任何接口都不会再回显原值，
          <b>留空提交表示保持原值不变</b>。当前：{baiduReady ? '已配置' : '未配置'}。
        </p>
        <div className="v3-pan-form">
          <Field label="App Key（client_id）" htmlFor="v3-pan-app-key">
            <Input
              id="v3-pan-app-key"
              value={cfgForm.app_key}
              onChange={(e) => setCfgForm((f) => ({ ...f, app_key: e.target.value }))}
              placeholder={baiduReady ? '已配置，留空则不修改' : '如：xxxxxxxxxxxxxxxx'}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
          <Field label="Secret Key（client_secret）" htmlFor="v3-pan-secret-key">
            <Input
              id="v3-pan-secret-key"
              type="password"
              value={cfgForm.secret_key}
              onChange={(e) => setCfgForm((f) => ({ ...f, secret_key: e.target.value }))}
              placeholder={baiduReady ? '已配置，留空则不修改' : '如：xxxxxxxxxxxxxxxx'}
              autoComplete="new-password"
              spellCheck={false}
            />
          </Field>
          <Field label="回调地址（redirect_uri）" htmlFor="v3-pan-redirect-uri">
            <Input
              id="v3-pan-redirect-uri"
              value={cfgForm.redirect_uri}
              onChange={(e) => setCfgForm((f) => ({ ...f, redirect_uri: e.target.value }))}
              placeholder="oob（默认，表示授权后手动复制授权码）"
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
        </div>
      </Dialog>

      {/* ===== 夸克 Web 视图配置弹窗 ===== */}
      <Dialog
        open={showQuarkCfg}
        title="夸克网盘 Web 视图配置"
        sub="仅支持 http/https 地址"
        onClose={() => setShowQuarkCfg(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowQuarkCfg(false)}>取消</Button>
            <Button variant="gradient" onClick={saveQuarkCfg} loading={quarkSaving}>
              {quarkSaving ? '保存中…' : '保存'}
            </Button>
          </>
        )}
      >
        <p className="v3-pan-dialog-note">
          夸克网盘未开放官方 API，此处配置要嵌入的网页地址（默认 pan.quark.cn 首页，也可填具体分享页）。
          仅支持 http/https 地址；登录状态由浏览器 Cookie 维护。
        </p>
        <Field label="Web 视图地址" htmlFor="v3-pan-quark-url">
          <Input
            id="v3-pan-quark-url"
            value={quarkForm.web_view_url}
            onChange={(e) => setQuarkForm({ web_view_url: e.target.value })}
            placeholder="https://pan.quark.cn/"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
      </Dialog>
    </div>
  )
}
