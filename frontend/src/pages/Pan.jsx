import React, { useEffect, useMemo, useState } from 'react'
import useStore from '../store/useStore'
import { fmtFileSize, fmtDateCN } from '../utils/date'
import { Modal, Empty, toast } from '../components/UI'
import {
  getStoredPan, clearPan, getStatus, getAuthUrl, exchangeToken,
  refreshPanToken, listPanFiles, getFileMetas
} from '../utils/pan'
import { Cloud, Search, Plus, Folder, RefreshCw, X } from '../components/Icon'

const CATS = ['全部', '真题', '数学', '英语', '政治', '专业课']
const ICON = { pdf: '📕', video: '🎬', doc: '📄', audio: '🎧', zip: '🗜', other: '📁' }

function fileIcon(name) {
  const n = (name || '').toLowerCase()
  if (n.endsWith('.pdf')) return 'pdf'
  if (/\.(mp4|mkv|avi|mov|flv|wmv)$/.test(n)) return 'video'
  if (/\.(docx?|xlsx?|pptx?|txt|md)$/.test(n)) return 'doc'
  if (/\.(mp3|wav|m4a|flac)$/.test(n)) return 'audio'
  if (/\.(zip|rar|7z|tar|gz)$/.test(n)) return 'zip'
  return 'other'
}

function guessCat(name) {
  const n = (name || '').toLowerCase()
  if (/真题|押题|模考|试卷/.test(n)) return '真题'
  if (/数学|高数|线代|概率|1800|660|汤|张宇/.test(n)) return '数学'
  if (/英语|恋恋|单词|词汇|阅读|作文|真题精讲/.test(n)) return '英语'
  if (/政治|马原|毛概|史纲|肖|腿|徐涛/.test(n)) return '政治'
  return '专业课'
}

export default function Pan() {
  const { pan, addPan, removePan, updatePan } = useStore()
  const [cat, setCat] = useState('全部')
  const [q, setQ] = useState('')
  const [activeId, setActiveId] = useState(null)
  const [link, setLink] = useState('')

  /* ---- 百度网盘对接状态 ---- */
  const [baidu, setBaidu] = useState({ configured: false })
  const [panToken, setPanToken] = useState(getStoredPan())
  const [remoteDir, setRemoteDir] = useState('/')
  const [remoteFiles, setRemoteFiles] = useState([])
  const [remoteLoading, setRemoteLoading] = useState(false)
  const [showAuth, setShowAuth] = useState(false)
  const [authCode, setAuthCode] = useState('')
  const [authUrl, setAuthUrl] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [curPath, setCurPath] = useState(['/'])

  /* ---- 登记资料弹窗 ---- */
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'pdf', cat: '专业课', desc: '', size: 0 })

  useEffect(() => { getStatus().then(setBaidu).catch(() => toast('网盘服务状态获取失败，请检查后端是否启动')) }, [])

  const tokenValid = panToken && panToken.access_token

  const loadRemote = async (dir = remoteDir) => {
    if (!tokenValid) return
    setRemoteLoading(true)
    try {
      const list = await listPanFiles(panToken.access_token, dir)
      setRemoteFiles(list)
      setCurPath((p) => (dir === '/' ? ['/'] : (p.includes(dir) ? p.slice(0, p.indexOf(dir) + 1) : [...p, dir])))
    } catch (e) {
      if (panToken.refresh_token) {
        try {
          const refreshed = await refreshPanToken(panToken.refresh_token)
          setPanToken(refreshed)
          setRemoteFiles(await listPanFiles(refreshed.access_token, dir))
        } catch {
          toast('授权已失效，请重新授权')
          setPanToken(null); clearPan()
        }
      } else toast(e.message)
    }
    setRemoteLoading(false)
  }

  useEffect(() => { if (tokenValid) loadRemote('/') }, [tokenValid]) // eslint-disable-line

  const openAuth = async () => {
    try { const url = await getAuthUrl(); setAuthUrl(url); setShowAuth(true) }
    catch (e) { toast(e.message) }
  }
  const submitAuthCode = async () => {
    const code = authCode.trim()
    if (!code) return toast('请输入授权码')
    setAuthBusy(true)
    try {
      const tok = await exchangeToken(code)
      setPanToken(tok); setShowAuth(false); setAuthCode('')
      toast('百度网盘授权成功')
    } catch (e) { toast(e.message) } finally { setAuthBusy(false) }
  }
  const logoutPan = () => { setPanToken(null); clearPan(); setRemoteFiles([]); toast('已退出百度网盘') }
  const openDir = (f) => { if (!f.isdir) return; setRemoteDir(f.path); loadRemote(f.path) }
  const goUp = () => {
    const parent = curPath.length > 1 ? curPath.slice(0, -1).join('/') || '/' : '/'
    setRemoteDir(parent); loadRemote(parent)
  }
  const getDlink = async (f) => {
    if (!tokenValid) return ''
    try {
      const arr = await getFileMetas(panToken.access_token, [f.fs_id])
      if (arr[0] && arr[0].dlink) return arr[0].dlink
    } catch (e) { toast(e.message) }
    return ''
  }
  const importRemote = (f) => {
    addPan({ name: f.name, type: fileIcon(f.name), cat: guessCat(f.name), desc: `来自百度网盘：${f.path}`, size: f.size, remote: true, fsId: f.fs_id })
    toast(`已登记「${f.name}」到本地资料库`)
  }

  const list = useMemo(
    () => (cat === '全部' ? pan : pan.filter((p) => p.cat === cat))
      .filter((p) => !q || (p.name || '').toLowerCase().includes(q.toLowerCase())),
    [pan, cat, q]
  )
  const active = pan.find((p) => p.id === activeId) || null
  const syncedCount = pan.filter((p) => p.synced).length
  const connectedCount = tokenValid ? 1 : 0
  const recentSync = useMemo(
    () => [...pan].sort((a, b) => (b.date || '').localeCompare(a.date || '')).slice(0, 5),
    [pan]
  )

  const submit = () => {
    if (!form.name.trim()) return toast('请填写文件名')
    addPan({ name: form.name.trim(), type: form.type, cat: form.cat, desc: form.desc.trim(), size: Number(form.size) || 0, url: '' })
    setForm({ name: '', type: 'pdf', cat: '专业课', desc: '', size: 0 })
    setShowAdd(false); toast('资料已登记')
  }
  const importLink = () => {
    const v = link.trim()
    if (!v) return toast('请粘贴分享链接')
    addPan({ name: v, type: 'other', cat: '专业课', desc: '从分享链接导入', size: 0, url: v })
    setLink(''); toast('链接已登记到资料库')
  }

  return (
    <div className="pan2">
      {/* ===== 头部 ===== */}
      <div className="pan2-head">
        <div>
          <div className="pan2-title">网盘联动</div>
          <div className="pan2-sub">集中管理你的云端学习资料，一键同步到本地 · 已同步 {syncedCount}/{pan.length} 项</div>
        </div>
        <span className="pan2-status"><span className="dot" />已连接 {connectedCount} / 4 个网盘</span>
      </div>

      {/* ===== 云盘连接卡 ===== */}
      <div className="provider-grid">
        <div className={`provider-card ${tokenValid ? 'connected' : ''}`}>
          <div className="provider-ico"><Cloud size={20} /></div>
          <div className="provider-name">百度网盘</div>
          <div className="provider-desc">{tokenValid ? 'OAuth 已授权 · 可浏览下载' : '官方 OAuth 直连'}</div>
          <span className={`provider-pill ${tokenValid ? 'on' : 'off'}`}>{tokenValid ? '已连接' : '未连接'}</span>
          {tokenValid
            ? <button className="provider-btn ghost" onClick={logoutPan}>退出授权</button>
            : <button className="provider-btn primary" onClick={openAuth} disabled={!baidu.configured}>去连接</button>}
        </div>
        {['阿里云盘', 'OneDrive', '夸克网盘'].map((name) => (
          <div key={name} className="provider-card soon">
            <div className="provider-ico"><Cloud size={20} /></div>
            <div className="provider-name">{name}</div>
            <div className="provider-desc">平台对接规划中</div>
            <span className="provider-pill off">即将支持</span>
            <button className="provider-btn ghost" disabled>敬请期待</button>
          </div>
        ))}
      </div>

      {/* ===== 百度网盘文件浏览（授权后） ===== */}
      {tokenValid && (
        <div className="panel">
          <div className="panel-head">
            <h3 className="panel-title"><Folder size={16} style={{ verticalAlign: -3, marginRight: 6 }} />百度网盘文件</h3>
            <button className="btn ghost" onClick={() => loadRemote(remoteDir)}><RefreshCw size={14} /> 刷新</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <button className="btn ghost" style={{ padding: '4px 10px' }} onClick={goUp} disabled={curPath.length <= 1}>⬆ 上级</button>
            <span style={{ fontSize: 12.5, color: 'var(--ink-2)', wordBreak: 'break-all' }}>{curPath.join(' / ') || '/'}</span>
          </div>
          {remoteLoading ? (
            <p style={{ fontSize: 13, color: 'var(--ink-3)' }}>正在读取百度网盘…</p>
          ) : remoteFiles.length === 0 ? (
            <p style={{ fontSize: 13, color: 'var(--ink-3)' }}>当前目录暂无文件</p>
          ) : (
            <div style={{ maxHeight: 260, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
              {remoteFiles.map((f) => (
                <div key={f.fs_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', background: 'var(--surface-2)', borderRadius: 10 }}>
                  <span style={{ fontSize: 18 }}>{f.isdir ? '📁' : ICON[fileIcon(f.name)] || '📄'}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{f.isdir ? '文件夹' : `${fmtFileSize(f.size)} · ${fmtDateCN(f.mtime * 1000)}`}</div>
                  </div>
                  {f.isdir ? (
                    <button className="btn ghost" style={{ padding: '4px 10px' }} onClick={() => openDir(f)}>进入</button>
                  ) : (
                    <>
                      <button className="btn ghost" style={{ padding: '4px 10px' }} onClick={() => importRemote(f)}>登记</button>
                      <button className="btn ghost" style={{ padding: '4px 10px' }} onClick={async () => { const d = await getDlink(f); d ? window.open(d, '_blank') : toast('无法获取下载链接（可能需在网盘客户端下载）') }}>下载</button>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ===== 资源列表 + 活动/预览 ===== */}
      <div className="pan2-body">
        <div className="pan2-res">
          <div className="pan2-toolbar">
            <div className="pan2-search">
              <Search size={15} />
              <input placeholder="搜索文件名、来源…" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="pan2-tabs">
              {CATS.map((c) => (
                <button key={c} className={`pan2-tab ${cat === c ? 'active' : ''}`} onClick={() => setCat(c)}>{c}</button>
              ))}
            </div>
            <button className="btn primary" onClick={() => setShowAdd(true)}><Plus size={15} /> 添加资料</button>
          </div>

          {list.length === 0 ? (
            <div className="panel">
              <Empty icon={<span style={{ fontSize: 32 }}>☁️</span>} title="该分类暂无资料" desc="点击「添加资料」或从上方百度网盘导入" />
            </div>
          ) : (
            <div className="res-list">
              {list.map((p) => (
                <div key={p.id} className={`res-item ${activeId === p.id ? 'active' : ''}`} onClick={() => setActiveId(p.id)}>
                  <div className={`res-ico ${p.type}`}>{ICON[p.type] || '📁'}</div>
                  <div className="res-info">
                    <div className="res-name">{p.name}</div>
                    <div className="res-meta">{fmtFileSize(p.size)} · {p.cat} · {fmtDateCN(p.date)}</div>
                  </div>
                  {p.remote && <span className="res-tag remote">网盘</span>}
                  {p.synced ? <span className="res-tag synced">已同步</span> : <span className="res-tag unsynced">未同步</span>}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 右侧：选中→预览，未选→活动面板 */}
        {active ? (
          <div className="panel pan2-preview">
            <div className="pv-icon">{ICON[active.type] || '📁'}</div>
            <div className="pv-title">{active.name}</div>
            <div className="pv-meta">
              <span>{fmtFileSize(active.size)}</span>
              <span>{active.cat}</span>
              <span>{active.synced ? '已同步' : '待同步'}</span>
              {active.remote && <span>来自网盘</span>}
            </div>
            <div className="pv-body">{active.desc || '暂无描述'}</div>
            <div className="pv-actions">
              <button className="btn primary" onClick={() => updatePan(active.id, { synced: !active.synced })}>
                {active.synced ? '标记为未同步' : '标记为已同步'}
              </button>
              <button className="btn ghost" onClick={() => toast('可在「百度网盘文件」区域中定位并下载该文件')}>在网盘中打开</button>
              <button className="btn danger" onClick={() => { removePan(active.id); setActiveId(null); toast('已移除该资料') }}>移除</button>
            </div>
          </div>
        ) : (
          <div className="pan2-activity">
            <div className="panel quick-import">
              <div className="panel-title" style={{ marginBottom: 10 }}>快速导入</div>
              <input className="qinput" placeholder="粘贴分享链接…" value={link} onChange={(e) => setLink(e.target.value)} />
              <button className="btn primary" onClick={importLink}>导入到本地</button>
            </div>
            <div className="panel">
              <div className="panel-title" style={{ marginBottom: 10 }}>最近同步</div>
              <div className="act-list">
                {recentSync.length === 0 && <p style={{ fontSize: 12.5, color: 'var(--ink-3)' }}>暂无同步记录</p>}
                {recentSync.map((p) => (
                  <div key={p.id} className="act-row">
                    <span className={`act-dot ${p.synced ? 'green' : 'amber'}`} />
                    <span className="act-text">{p.name}</span>
                    <span className="act-time">{fmtDateCN(p.date)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ===== 登记资料弹窗 ===== */}
      <Modal open={showAdd} title="登记网盘资料" onClose={() => setShowAdd(false)}
        footer={<><button className="btn ghost" onClick={() => setShowAdd(false)}>取消</button><button className="btn primary" onClick={submit}>保存</button></>}>
        <label style={{ display: 'block', marginBottom: 10, fontSize: 13 }}>文件名
          <input className="input" style={{ width: '100%', marginTop: 4, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如：834 真题 2026.pdf" />
        </label>
        <label style={{ display: 'block', marginBottom: 10, fontSize: 13 }}>类型
          <select className="input" style={{ width: '100%', marginTop: 4, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            <option value="pdf">PDF 文档</option>
            <option value="doc">Word 文档</option>
            <option value="video">视频</option>
            <option value="audio">音频</option>
            <option value="zip">压缩包</option>
            <option value="other">其他</option>
          </select>
        </label>
        <label style={{ display: 'block', marginBottom: 10, fontSize: 13 }}>分类
          <select className="input" style={{ width: '100%', marginTop: 4, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }} value={form.cat} onChange={(e) => setForm({ ...form, cat: e.target.value })}>
            {CATS.slice(1).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label style={{ display: 'block', fontSize: 13 }}>说明
          <input className="input" style={{ width: '100%', marginTop: 4, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }} value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} placeholder="资料用途、使用建议" />
        </label>
      </Modal>

      {/* ===== 授权弹窗 ===== */}
      <Modal open={showAuth} title="授权百度网盘" onClose={() => setShowAuth(false)}
        footer={<><button className="btn ghost" onClick={() => setShowAuth(false)}>取消</button><button className="btn primary" onClick={submitAuthCode} disabled={authBusy}>{authBusy ? '正在换取…' : '完成授权'}</button></>}>
        <p style={{ fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.8, marginBottom: 10 }}>
          点击下方按钮跳转百度网盘授权页，登录并同意授权后，<strong>复制页面显示的授权码（code）</strong>粘贴到下方输入框。
        </p>
        <a href={authUrl} target="_blank" rel="noreferrer" className="btn primary" style={{ textDecoration: 'none', display: 'inline-flex', marginBottom: 12 }}>前往百度网盘授权</a>
        <label style={{ display: 'block', fontSize: 13 }}>授权码（code）
          <input className="input" style={{ width: '100%', marginTop: 4, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }} value={authCode} onChange={(e) => setAuthCode(e.target.value)} placeholder="粘贴授权码" />
        </label>
      </Modal>
    </div>
  )
}
