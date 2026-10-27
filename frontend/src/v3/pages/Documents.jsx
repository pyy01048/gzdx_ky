import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { documentsApi, getBackendState, subscribeBackendState } from '../../api/client'
import { fmtDateCN } from '../../utils/date'
import { fmtBytes } from '../../utils/format'
import {
  Alert, AnimatedNumber, Badge, Button, Card, Chip, Dialog, Empty, Field, IconButton, Input,
  Menu, MenuItem, PageHeader, Progress, Segmented, Skeleton, Switch, Tile, toast, toastErr, toastOk,
  useConfirm, cx,
} from '../ui'
import {
  AlertCircle, AlertTriangle, Brain, CheckCircle2, Download, Edit, Eye, FileText, FolderOpen,
  Layers, ListChecks, MoreHorizontal, RefreshCw, Search, Settings, Share2, Sparkles, Star, Trash,
  Type, Upload, X,
} from '../icons'
import { useFavorite, useFavoriteProbe } from '../../hooks/useFavorites'
import { useAuth } from '../../auth/AuthContext'
import DocumentsDetail from './DocumentsDetail'
import {
  KbImportDialog, KnowledgeView, QuestionReviewDialog, RagSearchPanel, RawFilePreviewDialog,
  SubjectMgrDialog,
} from './documentsV3Panels'
import {
  ACCEPT, docStateOf, fileMetaOf, governanceApi, isEmptyBody, listItems, normalizeDoc, sigOf,
} from './documentsV3Shared'
import '../styles/documents-v3.css'

/* ==========================================================================
   文档知识库（Aurora v3）
   上传讲义 / 真题 / 笔记 → 解析入库 → 知识点 / 分块 / 题目预览
   功能面与 legacy Documents.jsx 对齐：
     · 科目分布筛选 + 文档搜索 + 总览统计
     · 批量上传（dropzone + 指纹去重队列 + FormData + 自动解析）
     · 单篇/批量解析、智能分析、出题、归档、改科目、删除
     · 批量选择（归档 / 改科目 / 标记删除 / 物理删除，后者仍走 delete_guard 闸门）
     · 详情抽屉（Markdown 快照 / 导出 md·txt·pdf / 知识点 / 分块 / 题目预览 / 下载原文件）
     · 扫描 knowledge_base 根目录，dry-run 预览与执行归档（执行前全库备份）
   所有数据来自接口；离线 / 空库 / 失败都是显式状态，不用演示数据冒充。
   ========================================================================== */

const DOC_ISSUE_PREFIXES = ['/documents', '/kb', '/kb-import']

function docIssuesOf(failures) {
  if (!Array.isArray(failures)) return []
  return failures.filter((f) => {
    const path = f && f.path ? String(f.path) : ''
    return DOC_ISSUE_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`))
  })
}

const QUEUE_META = {
  pending: { label: '待上传', tone: 'outline' },
  uploading: { label: '上传中', tone: 'primary' },
  parsing: { label: '解析中', tone: 'primary' },
  done: { label: '已完成', tone: 'success' },
  dup: { label: '重复跳过', tone: 'warning' },
  error: { label: '失败', tone: 'danger' },
}

const extOf = (name) => {
  const parts = String(name || '').split('.')
  return (parts.length > 1 ? parts.pop() : '?').slice(0, 3).toUpperCase()
}

const PAGE_SIZE = 30

const VIEW_OPTIONS = [
  { value: 'list', label: '文档列表', icon: <FileText size={14} /> },
  { value: 'search', label: 'RAG 检索', icon: <Search size={14} /> },
  { value: 'knowledge', label: '知识图谱', icon: <Share2 size={14} /> },
]

/* 收藏星标：走 /favorites 弱引用接口（与 legacy 同一契约），失败回滚并提示 */
function DocFavorite({ doc }) {
  const { favorited, known, toggle } = useFavorite('document', doc.id)
  const [busy, setBusy] = useState(false)

  const onClick = async () => {
    if (busy || !known) return
    setBusy(true)
    try {
      const now = await toggle({
        title: doc.filename,
        snippet: doc.summary || '',
        meta: { subject: doc.subject || '' },
      })
      if (now) toastOk('已收藏')
      else toast('已取消收藏')
    } catch (e) {
      toastErr(`收藏失败：${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <IconButton
      label={!known ? '收藏状态加载中' : favorited ? '取消收藏' : '收藏'}
      size="sm"
      icon={<Star size={16} />}
      className={cx('dv3-fav', favorited && 'is-on')}
      aria-pressed={favorited}
      aria-busy={busy}
      disabled={busy || !known}
      onClick={onClick}
    />
  )
}

/* -------------------------------------------------------------------------- */
/* 文档卡片                                                                   */
/* -------------------------------------------------------------------------- */
function DocCard({
  d, selected, parsingId, analyzingId, onToggle, onOpen, onParse,
  onAnalyze, onGenerateQuiz, onChangeSubject, onArchive, onRemove, onDownload,
  onReviewQuestions, onKbImport, onPreviewFile, canManage,
}) {
  const meta = fileMetaOf(d)
  const st = docStateOf(d)
  const menuAnchor = useRef(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const chunks = Number(d.chunk_count) || 0
  const chars = Number(d.content_length) || 0
  const busyParse = parsingId === d.id
  const busyAnalyze = analyzingId === d.id

  const runMenu = (fn) => () => {
    setMenuOpen(false)
    fn()
  }

  return (
    <Card className={cx('dv3-doc', selected && 'is-selected')}>
      <div className="dv3-doc__head">
        {canManage ? (
          <label className="dv3-check" title="选择该文档">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggle(d.id)}
              aria-label={`选择文档：${d.filename}`}
            />
            <span className="dv3-check__box" aria-hidden="true" />
          </label>
        ) : null}
        <span className={cx('dv3-file', `is-${meta.cls}`)} aria-hidden="true">{meta.label}</span>
        <div className="dv3-doc__id">
          <button
            type="button"
            className="dv3-doc__name"
            title={d.filename}
            onClick={() => onOpen(d, 'overview')}
          >
            {d.filename}
          </button>
          <span className="dv3-doc__meta">
            {fmtDateCN(d.uploaded_at)} · {fmtBytes(d.size)}
          </span>
        </div>
        <DocFavorite doc={d} />
        {canManage || d.has_local_file ? (
          <span className="dv3-doc__more" ref={menuAnchor}>
            <IconButton
              label="更多操作"
              size="sm"
              icon={<MoreHorizontal size={18} />}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
            />
          </span>
        ) : null}
      </div>

      <div className="dv3-doc__body">
        <div className="dv3-doc__tags">
          <Chip as="span" className="dv3-subject">{d.subject}</Chip>
          <Badge tone={st.tone}>{st.label}</Badge>
          <span className="dv3-doc__stat">{chars.toLocaleString('zh-CN')} 字</span>
          <span className="dv3-doc__stat">{chunks > 0 ? `${chunks} 分块` : '无分块'}</span>
        </div>
        <p className={cx('dv3-doc__summary', !d.summary && 'is-placeholder')}>
          {d.summary || '暂无摘要，解析后自动生成'}
        </p>
        {st.empty ? (
          <span className="dv3-doc__warn">
            <AlertCircle size={12} />
            正文缺失，建议重新解析
          </span>
        ) : null}
        {!d.has_local_file ? (
          <span className="dv3-doc__warn is-muted" title={d.local_file_note || '本地没有原文件'}>
            <FolderOpen size={12} />
            {d.local_file_note || '本地无原文，无法下载 / 归档'}
          </span>
        ) : null}
      </div>

      <div className="dv3-doc__foot">
        <Button variant="tonal" size="sm" onClick={() => onOpen(d, 'overview')}>详情</Button>
        {canManage ? (
          st.empty ? (
            <Button variant="filled" size="sm" loading={busyParse} onClick={() => onParse(d.id)}>
              {busyParse ? '解析中…' : '重新解析'}
            </Button>
          ) : d.status === 'parsed' ? (
            <>
              <Button variant="text" size="sm" icon={<Sparkles size={14} />} onClick={() => onOpen(d, 'points')}>
                知识点
              </Button>
              {chunks > 0 ? (
                <Button variant="text" size="sm" icon={<Layers size={14} />} onClick={() => onOpen(d, 'chunks')}>
                  分块
                </Button>
              ) : null}
              <Button variant="text" size="sm" icon={<ListChecks size={14} />} onClick={() => onGenerateQuiz(d)}>
                出题
              </Button>
            </>
          ) : (
            <Button variant="filled" size="sm" loading={busyParse} onClick={() => onParse(d.id)}>
              {busyParse ? '解析中…' : '开始解析'}
            </Button>
          )
        ) : d.status === 'parsed' ? (
          <>
            <Button variant="text" size="sm" icon={<Sparkles size={14} />} onClick={() => onOpen(d, 'points')}>
              知识点
            </Button>
            {chunks > 0 ? (
              <Button variant="text" size="sm" icon={<Layers size={14} />} onClick={() => onOpen(d, 'chunks')}>
                分块
              </Button>
            ) : null}
          </>
        ) : null}
      </div>

      {canManage || d.has_local_file ? (
        <Menu open={menuOpen} anchorRef={menuAnchor} onClose={() => setMenuOpen(false)} width={196}>
          {canManage ? (
            <>
              <MenuItem
                icon={<Brain size={15} />}
                disabled={busyAnalyze}
                onClick={runMenu(() => onAnalyze(d))}
              >
                {busyAnalyze ? '分析中…' : '智能分析'}
              </MenuItem>
              <MenuItem icon={<ListChecks size={15} />} onClick={runMenu(() => onOpen(d, 'questions'))}>
                预览题目
              </MenuItem>
              <MenuItem icon={<CheckCircle2 size={15} />} onClick={runMenu(() => onReviewQuestions(d))}>
                审核入库
              </MenuItem>
              <MenuItem icon={<Sparkles size={15} />} onClick={runMenu(() => onKbImport(d))}>
                识别题目
              </MenuItem>
              <MenuItem icon={<Edit size={15} />} onClick={runMenu(() => onChangeSubject(d))}>
                改科目
              </MenuItem>
              <div className="v3-menu__sep" />
            </>
          ) : null}
          <MenuItem
            icon={<Eye size={15} />}
            disabled={!d.has_local_file}
            onClick={runMenu(() => onPreviewFile(d))}
          >
            预览原文件
          </MenuItem>
          <MenuItem
            icon={<Download size={15} />}
            disabled={!d.has_local_file}
            onClick={runMenu(() => onDownload(d))}
          >
            下载原文件
          </MenuItem>
          {canManage ? (
            <>
              <MenuItem
                icon={<FolderOpen size={15} />}
                disabled={!d.has_local_file}
                onClick={runMenu(() => onArchive(d))}
              >
                归档源文件
              </MenuItem>
              <MenuItem icon={<Trash size={15} />} danger onClick={runMenu(() => onRemove(d))}>
                删除
              </MenuItem>
            </>
          ) : null}
        </Menu>
      ) : null}
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* 页面                                                                       */
/* -------------------------------------------------------------------------- */
export default function Documents() {
  const { isAdmin } = useAuth()
  const [confirm, confirmDialog] = useConfirm()

  const [backendOk, setBackendOk] = useState(false)
  const [backend, setBackend] = useState(() => {
    try {
      const s = getBackendState()
      if (s && s.state) return s
    } catch { /* 读不到状态按未知处理 */ }
    return { state: 'unknown', failures: [], checkedAt: 0 }
  })
  const [apiIssues, setApiIssues] = useState(() => docIssuesOf(backend.failures))

  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [subject, setSubject] = useState('all')
  const [subjectStats, setSubjectStats] = useState(null)
  const [q, setQ] = useState('')

  const [uploading, setUploading] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [queue, setQueue] = useState([])
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef(null)

  const [parsingId, setParsingId] = useState(null)
  const [parsingAll, setParsingAll] = useState(false)
  const [analyzingId, setAnalyzingId] = useState(null)

  const [selected, setSelected] = useState(() => new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [detail, setDetail] = useState(null) // { id, doc, tab }
  const [view, setView] = useState('list') // list | search | knowledge
  const [limit, setLimit] = useState(PAGE_SIZE)

  const [reviewDoc, setReviewDoc] = useState(null)
  const [fileDoc, setFileDoc] = useState(null)
  const [kbImport, setKbImport] = useState(null) // { defaultScope }
  const [subjMgrOpen, setSubjMgrOpen] = useState(false)

  const [subjectDlg, setSubjectDlg] = useState(null) // { ids, count, current }
  const [subjectValue, setSubjectValue] = useState('')
  const [savingSubject, setSavingSubject] = useState(false)

  const [scanOpen, setScanOpen] = useState(false)
  const [scanDry, setScanDry] = useState(true)
  const [scanResult, setScanResult] = useState(null)
  const [scanningRoot, setScanningRoot] = useState(false)
  const [scanBacking, setScanBacking] = useState(false)

  const listSeq = useRef(0)

  /* 收藏态：批量探测只对未命中项发请求，避免 N 次 /favorites/check */
  const probeItems = useMemo(
    () => docs.map((d) => ({ item_type: 'document', item_id: Number(d.id) })),
    [docs],
  )
  const { probe } = useFavoriteProbe(probeItems)
  useEffect(() => { probe() }, [probe])

  /* ---------------- 科目统计 ---------------- */
  const refreshSubjects = useCallback(async () => {
    try {
      const s = await documentsApi.subjects()
      setSubjectStats(s)
    } catch { /* 后端离线时静默，科目分布整块隐藏 */ }
  }, [])

  /* ---------------- 文档列表 ---------------- */
  const refresh = useCallback(async () => {
    const seq = ++listSeq.current
    setLoading(true)
    try {
      const d = await documentsApi.list({ subject: subject === 'all' ? undefined : subject })
      if (seq !== listSeq.current) return
      const list = listItems(d)
      if (!list) throw new Error('文档列表响应格式无法识别')
      setDocs(list.map(normalizeDoc))
      setBackendOk(true)
      setLoadErr('')
    } catch (e) {
      if (seq !== listSeq.current) return
      setDocs([])
      setBackendOk(false)
      setLoadErr(e?.message || '文档列表加载失败')
    } finally {
      if (seq === listSeq.current) setLoading(false)
    }
  }, [subject])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { refreshSubjects() }, [refreshSubjects])

  /* 订阅后端三态：失败登记会触发复判，这里只取回快照 */
  useEffect(() => {
    let alive = true
    const onStatus = (s) => {
      if (!alive || !s || !s.state) return
      setBackend(s)
      setApiIssues(docIssuesOf(s.failures))
    }
    let unsub = () => {}
    try {
      const ret = subscribeBackendState(onStatus)
      if (typeof ret === 'function') unsub = ret
    } catch { /* 忽略订阅异常 */ }
    return () => { alive = false; unsub() }
  }, [])

  const filtered = useMemo(() => {
    let arr = docs
    if (subject !== 'all') arr = arr.filter((d) => d.subject === subject)
    const kw = q.trim().toLowerCase()
    if (kw) arr = arr.filter((d) => (d.filename + (d.summary || '')).toLowerCase().includes(kw))
    return arr
  }, [docs, subject, q])

  /* 客户端窗口化：接口仍取回全部文档，只控制渲染量 */
  const visibleDocs = useMemo(() => filtered.slice(0, limit), [filtered, limit])

  useEffect(() => {
    setLimit(PAGE_SIZE)
  }, [q, subject, docs.length])

  const subjectOptions = useMemo(() => {
    const set = new Set()
    ;(subjectStats?.subjects || []).forEach((s) => { if (s?.name) set.add(s.name) })
    docs.forEach((d) => { if (d.subject) set.add(d.subject) })
    return Array.from(set)
  }, [subjectStats, docs])

  const existSigs = useMemo(() => new Set(docs.map((d) => sigOf(d.filename, d.size))), [docs])

  const overview = useMemo(() => {
    const parsed = docs.filter((d) => d.status === 'parsed').length
    const chunks = docs.reduce((s, d) => s + (d.chunk_count || 0), 0)
    const chars = docs.reduce((s, d) => s + (d.content_length || 0), 0)
    return { total: docs.length, parsed, pending: docs.length - parsed, chunks, chars }
  }, [docs])

  const emptyCount = useMemo(() => docs.filter(isEmptyBody).length, [docs])
  const coverage = overview.total ? Math.round((overview.parsed / overview.total) * 100) : 0
  const selectedDocs = useMemo(() => docs.filter((d) => selected.has(d.id)), [docs, selected])

  /* 文档刷新后剔除已不存在的选择 */
  useEffect(() => {
    setSelected((prev) => {
      const ids = new Set(docs.map((d) => d.id))
      const next = new Set([...prev].filter((id) => ids.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [docs])

  const detailDoc = detail ? (docs.find((d) => d.id === detail.id) || detail.doc) : null

  /* ---------------- 批量上传 ---------------- */
  const queueStat = useMemo(() => {
    const total = queue.length
    const pending = queue.filter((i) => i.status === 'pending').length
    const dup = queue.filter((i) => i.status === 'dup').length
    const done = queue.filter((i) => i.status === 'done').length
    const error = queue.filter((i) => i.status === 'error').length
    const finished = queue.filter((i) => ['done', 'error'].includes(i.status)).length
    return { total, pending, dup, done, error, finished, pct: total ? Math.round((finished / total) * 100) : 0 }
  }, [queue])

  const enqueue = (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    if (!backendOk) { toastErr('需先连接后端（8000）才能上传解析'); return }
    if (uploading) { toast('上传进行中，请等待完成'); return }
    const seen = new Set(queue.map((it) => it.key))
    const items = []
    let dup = 0
    files.forEach((f) => {
      const key = sigOf(f.name, f.size)
      if (seen.has(key)) { dup += 1; return }
      seen.add(key)
      const isDup = existSigs.has(key)
      if (isDup) dup += 1
      items.push({
        key,
        name: f.name,
        size: f.size,
        file: f,
        status: isDup ? 'dup' : 'pending',
        msg: isDup ? '库中已存在同名同大小文档' : '',
      })
    })
    if (!items.length) { toast(`已忽略 ${dup} 个重复文件`); return }
    setQueue((prev) => [...prev, ...items])
    setUploadOpen(true)
    if (dup) toast(`加入 ${items.filter((i) => i.status === 'pending').length} 个文件，检出 ${dup} 个重复`)
    else toast(`已加入 ${items.length} 个文件，点「开始上传」`)
  }

  const runQueue = async (force = false) => {
    const targets = queue.filter(
      (it) => it.status === 'pending' || it.status === 'error' || (force && it.status === 'dup'),
    )
    if (!targets.length) return toast('没有待上传文件')
    if (!backendOk) return toastErr('需先连接后端（8000）才能上传解析')
    setUploading(true)
    let ok = 0
    let fail = 0
    for (const it of targets) {
      setQueue((prev) => prev.map((o) => (o.key === it.key ? { ...o, status: 'uploading', msg: '上传中…' } : o)))
      try {
        const fd = new FormData()
        fd.append('file', it.file)
        const r = await documentsApi.upload(fd)
        let msg = r?.message || '上传成功'
        if (r?.id) {
          setQueue((prev) => prev.map((o) => (o.key === it.key ? { ...o, status: 'parsing', msg: '已上传，正在解析…' } : o)))
          try {
            await documentsApi.parse(Number(r.id))
            msg = r.message ? `${r.message}（已解析）` : '上传并解析完成'
          } catch (e) {
            msg = `已上传；解析未完成：${e?.message || e}`
          }
        }
        ok += 1
        setQueue((prev) => prev.map((o) => (o.key === it.key ? { ...o, status: 'done', msg } : o)))
      } catch (e) {
        fail += 1
        setQueue((prev) => prev.map((o) => (o.key === it.key ? { ...o, status: 'error', msg: e?.message || String(e) } : o)))
      }
    }
    setUploading(false)
    if (fileRef.current) fileRef.current.value = ''
    await refresh()
    refreshSubjects()
    if (fail) toastErr(`批量上传完成：成功 ${ok} 个，失败 ${fail} 个`)
    else toastOk(`批量上传完成：成功 ${ok} 个`)
  }

  const clearQueue = () => { if (!uploading) setQueue([]) }

  const closeUpload = () => {
    if (uploading) { toast('上传进行中，请等待完成'); return }
    setUploadOpen(false)
  }

  /* ---------------- 单篇动作 ---------------- */
  const parseDoc = async (id) => {
    setParsingId(id)
    try {
      const r = await documentsApi.parse(Number(id))
      toastOk(r?.message || '解析完成，已提取知识点')
      await refresh()
    } catch (e) {
      // 422 = 质量闸门拒绝，detail 已是完整原因，不再叠加「解析失败」
      toastErr(e?.status === 422 ? e.message : `解析失败：${e?.message || e}`)
    } finally {
      setParsingId(null)
    }
  }

  const parseAllDocs = async () => {
    if (!backendOk) return toastErr('需连接后端批量解析')
    setParsingAll(true)
    try {
      const r = await documentsApi.parseAll()
      toastOk(r?.message || `批量解析完成：成功 ${r?.parsed || 0}/${r?.total || 0} 篇${r?.rejected ? `，质量闸门拒绝 ${r.rejected} 篇` : ''}`)
      await refresh()
    } catch (e) {
      toastErr(`批量解析失败：${e?.message || e}`)
    } finally {
      setParsingAll(false)
    }
  }

  const generateQuiz = async (d) => {
    if (!backendOk) return toastErr('需连接后端生成题目')
    try {
      const r = await documentsApi.generateQuiz(Number(d.id), { count: 5 })
      toastOk(`已生成 ${r?.questions_created || 5} 道题目，可在刷题中心查看`)
    } catch (e) {
      toastErr(`生成失败：${e?.message || e}`)
    }
  }

  const analyzeDoc = async (d) => {
    if (!backendOk) return toastErr('需连接后端智能分析')
    const ok = await confirm({
      title: '智能分析',
      message: '智能分析将AI识别文档中的知识点和题目（真题/模拟题自动分类），可能需要1-3分钟，确定开始？',
      confirmText: '开始分析',
    })
    if (!ok) return
    setAnalyzingId(d.id)
    try {
      const r = await documentsApi.analyze(Number(d.id), { extract_kp: true, extract_questions: true })
      toastOk(`分析完成：${r?.knowledge_points || 0}个知识点，${r?.questions || 0}道题目（真题已自动分类）`)
      await refresh()
      refreshSubjects()
    } catch (e) {
      toastErr(`分析失败：${e?.message || e}`)
    } finally {
      setAnalyzingId(null)
    }
  }

  const archiveDoc = async (d) => {
    if (!backendOk) return toastErr('需连接后端归档')
    const ok = await confirm({
      title: '归档源文件',
      message: `把《${d.filename}》的源文件归档到 knowledge_base/_archive/？（不会删除数据）`,
      confirmText: '归档',
    })
    if (!ok) return
    try {
      const r = await governanceApi.archive(Number(d.id))
      toastOk(r?.message || (r?.archived ? '已归档' : '未归档'))
      await refresh()
    } catch (e) {
      toastErr(`归档失败：${e?.message || e}`)
    }
  }

  const removeDoc = async (d) => {
    if (!backendOk) {
      setDocs((prev) => prev.filter((x) => x.id !== d.id))
      toast('已从列表移除')
      return
    }
    const ok = await confirm({
      title: '删除文档',
      message: '确定删除该文档？关联的知识分块和知识点也会被删除。',
      danger: true,
      confirmText: '删除',
    })
    if (!ok) return
    try {
      await documentsApi.remove(Number(d.id))
      setDocs((prev) => prev.filter((x) => x.id !== d.id))
      toastOk('文档已删除')
      refreshSubjects()
    } catch (e) {
      toastErr(`删除失败：${e?.message || e}`)
    }
  }

  const downloadOriginal = (d) => {
    const a = document.createElement('a')
    a.href = documentsApi.downloadUrl(d.id)
    a.download = d.filename || ''
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  const openDetail = (d, tab = 'overview') => {
    if (!backendOk) return toastErr('需连接后端查看文档详情')
    setDetail({ id: d.id, doc: d, tab })
  }

  const openDocById = (id, meta = null) => {
    const d = docs.find((x) => String(x.id) === String(id))
    if (d) { openDetail(d, 'overview'); return }
    // 命中可能来自未通过科目筛选的文档：用检索返回的真实元信息打开，
    // 详情正文 / 知识点仍按 id 从接口加载，不伪造统计字段。
    if (meta) {
      openDetail({
        id: Number(id),
        filename: meta.doc_name || meta.title || `文档 #${id}`,
        subject: meta.subject || '',
        file_type: meta.source_type || '',
        has_local_file: false,
        local_file_note: '该文档不在当前筛选列表，原文件状态需回到列表确认',
      }, 'overview')
      return
    }
    toastErr('该文档不在当前列表（可能被科目筛选过滤），请先在文档列表定位')
  }

  const openReview = (d) => {
    if (!backendOk) return toastErr('需连接后端预览题目')
    setReviewDoc(d)
  }

  const openKbImport = (arg, doc = null) => {
    if (!backendOk) return toastErr('需先连接后端才能识别题目')
    const defaultScope = arg === 'all' ? 'all' : arg === 'list' ? 'list' : 'single'
    setKbImport({ defaultScope, docId: doc?.id || '' })
  }

  const openFilePreview = (d) => {
    if (!backendOk) return toastErr('需连接后端预览原文件')
    if (!d?.has_local_file) return toastErr(d?.local_file_note || '本地没有原文件，无法预览')
    setFileDoc(d)
  }

  const openSubjectMgr = () => {
    if (!backendOk) return toastErr('需连接后端维护科目')
    setSubjMgrOpen(true)
  }

  /* ---------------- 选择与批量操作 ---------------- */
  const toggleSelect = (id) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const toggleAll = (check) => setSelected((prev) => {
    const next = new Set(prev)
    filtered.forEach((d) => {
      if (check) next.add(d.id)
      else next.delete(d.id)
    })
    return next
  })

  const clearSelection = () => setSelected(new Set())

  const bulkAction = async (action) => {
    if (!backendOk) return toastErr('需连接后端执行批量操作')
    const ids = selectedDocs.map((d) => Number(d.id))
    if (!ids.length) return toast('请先勾选文档')
    if (action === 'set_subject') { openSubjectDialog(selectedDocs); return }

    let ok = false
    if (action === 'archive') {
      ok = await confirm({
        title: '批量归档',
        message: `归档 ${ids.length} 篇文档的源文件到 _archive/？（不会删除数据）`,
        confirmText: '归档',
      })
    } else if (action === 'mark_delete') {
      ok = await confirm({
        title: '批量标记删除',
        message: `标记删除 ${ids.length} 篇文档的源文件（移动到 _trash/，记录保留）？`,
        confirmText: '标记删除',
      })
    } else if (action === 'purge') {
      ok = await confirm({
        title: '批量物理删除',
        message: `物理删除 ${ids.length} 篇文档及其分块/知识点？此操作不可逆，需已开启物理删除开关。`,
        danger: true,
        confirmText: '物理删除',
      })
    }
    if (!ok) return

    setBulkBusy(true)
    try {
      const r = await governanceApi.bulk({ action, doc_ids: ids })
      toastOk(r?.message || '批量操作完成')
      clearSelection()
      await refresh()
      refreshSubjects()
    } catch (e) {
      toastErr(`批量操作失败：${e?.message || e}`)
    } finally {
      setBulkBusy(false)
    }
  }

  /* ---------------- 改科目 ---------------- */
  const openSubjectDialog = (list) => {
    if (!backendOk) return toastErr('需连接后端')
    if (!list.length) return toast('请先勾选文档')
    setSubjectDlg({ ids: list.map((d) => Number(d.id)), count: list.length, current: list[0]?.subject || '' })
    setSubjectValue(list[0]?.subject || '')
  }

  const saveSubject = async () => {
    if (!subjectDlg) return
    const name = subjectValue.trim()
    if (!name) return toastErr('请填写科目名称')
    setSavingSubject(true)
    try {
      const r = await governanceApi.bulk({ action: 'set_subject', doc_ids: subjectDlg.ids, subject: name })
      toastOk(r?.message || '科目已更新')
      setSubjectDlg(null)
      await refresh()
      refreshSubjects()
    } catch (e) {
      toastErr(`改科目失败：${e?.message || e}`)
    } finally {
      setSavingSubject(false)
    }
  }

  /* ---------------- 扫描根目录归档 ---------------- */
  const openScan = (dry = true) => {
    if (!backendOk) return toastErr('需连接后端扫描')
    setScanDry(dry)
    setScanResult(null)
    setScanOpen(true)
  }

  const runScan = async () => {
    if (!backendOk) return toastErr('需连接后端扫描')
    if (!scanDry) {
      const ok = await confirm({
        title: '扫描并归档根目录',
        message: '扫描 knowledge_base 根目录并按科目归档？',
        content: (
          <div className="dv3-confirm-text">
            <p>文件会被移动到「科目/」目录，DB 路径同步更新（断链记录只统计不动）。</p>
            <p>注意：归档前会先做一次全库备份，耗时取决于库大小；备份期间请勿关闭页面。</p>
          </div>
        ),
        confirmText: '开始归档',
      })
      if (!ok) return
    }
    setScanningRoot(true)
    setScanBacking(!scanDry)
    try {
      const r = await governanceApi.scanRoot(scanDry)
      setScanResult({
        dryRun: scanDry,
        moved: r?.moved ?? 0,
        skipped: r?.skipped ?? 0,
        broken: r?.broken ?? 0,
        errors: r?.errors ?? 0,
        message: r?.message || '',
      })
      toastOk(r?.message || `${scanDry ? '预览' : '归档'}完成：移动 ${r?.moved ?? 0}，跳过 ${r?.skipped ?? 0}，断链 ${r?.broken ?? 0}，失败 ${r?.errors ?? 0}`)
      if (!scanDry) {
        await refresh()
        refreshSubjects()
      }
    } catch (e) {
      toastErr(`扫描失败：${e?.message || e}`)
    } finally {
      setScanningRoot(false)
      setScanBacking(false)
    }
  }

  const closeScan = () => {
    if (scanningRoot) { toast('扫描进行中，请等待完成'); return }
    setScanOpen(false)
  }

  /* ---------------- 页面头部 ---------------- */
  const connecting = loading && docs.length === 0 && !loadErr
  const offline = backend.state === 'offline' || !backendOk
  const degraded = backend.state === 'degraded'
  const backendTone = connecting ? 'outline' : offline ? 'danger' : degraded ? 'warning' : 'success'
  const backendText = connecting ? '连接中…' : offline ? '后端离线' : degraded ? '部分接口异常' : '后端已连接'

  return (
    <div className="v3-stack dv3-page">
      <PageHeader
        eyebrow="KNOWLEDGE BASE"
        title="文档知识库"
        sub={isAdmin
          ? '上传讲义 / 真题 / 笔记 · AI 自动解析提取知识点与分块'
          : '浏览、检索与阅读共享资料 · 上传与整理由管理员维护'}
        icon={<FileText size={22} />}
        actions={(
          <>
            <Badge tone={backendTone}>{backendText}</Badge>
            <IconButton
              label="刷新文档列表"
              icon={<RefreshCw size={17} />}
              onClick={refresh}
              disabled={loading}
            />
            {isAdmin ? (
              <>
                <Button
                  variant="tonal"
                  icon={<Sparkles size={15} />}
                  disabled={!backendOk}
                  onClick={() => openKbImport('list')}
                >
                  题目识别
                </Button>
                <Button
                  variant="filled"
                  icon={<Upload size={15} />}
                  loading={uploading}
                  onClick={() => setUploadOpen(true)}
                >
                  {uploading ? '上传中…' : '批量上传'}
                </Button>
              </>
            ) : null}
          </>
        )}
      />

      <div className="dv3-viewbar">
        <Segmented ariaLabel="文档视图" options={VIEW_OPTIONS} value={view} onChange={setView} />
        <div className="dv3-viewbar__right">
          {view === 'list' ? (
            <>
              <span className="dv3-viewbar__count">匹配 {filtered.length} / {docs.length} 篇</span>
              {isAdmin ? (
                <Button
                  variant="tonal"
                  size="sm"
                  icon={<Sparkles size={14} />}
                  disabled={!backendOk || filtered.length === 0}
                  onClick={() => openKbImport('list')}
                >
                  识别当前列表（{filtered.length}）
                </Button>
              ) : null}
            </>
          ) : null}
        </div>
      </div>

      {!isAdmin ? (
        <Alert tone="info">
          共享文档库为只读：浏览、RAG 检索、知识点、分块、原文预览与收藏可用；上传、解析、整理与入库由管理员操作。
        </Alert>
      ) : null}

      {apiIssues.length > 0 && backend.state !== 'offline' ? (
        <Alert tone="warning" icon={<AlertTriangle size={18} />}>
          <div className="dv3-issues">
            <div><b>{apiIssues.length} 项接口异常</b>，不影响浏览：已入库的文档、知识点与分块照常查看。</div>
            <details>
              <summary>查看详情</summary>
              <ul>
                {apiIssues.map((it) => (
                  <li key={it.path}>
                    <code>{it.path}</code>
                    <span>{it.status ? `HTTP ${it.status}` : '网络不可达'}</span>
                  </li>
                ))}
              </ul>
            </details>
          </div>
        </Alert>
      ) : null}

      {view === 'list' ? (
        <>
      {/* 总览 */}
      <div className="v3-bento dv3-stats">
        <Tile span={3} variant="gradient" className="dv3-stat dv3-stat--hero">
          <span className="v3-tile__label"><FileText size={15} />文档总数</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={overview.total} />
            <em>篇</em>
          </span>
          <span className="v3-tile__hint">已解析 {overview.parsed} · 待解析 {overview.pending}</span>
        </Tile>
        <Tile span={3} className="dv3-stat">
          <span className="dv3-stat__orb" aria-hidden="true"><CheckCircle2 size={18} /></span>
          <span className="v3-tile__label">已解析入库</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={overview.parsed} />
            <em>篇</em>
          </span>
          <Progress value={coverage} gradient height={4} />
          <span className="v3-tile__hint">{overview.pending ? `${overview.pending} 篇待解析 · 覆盖率 ${coverage}%` : `全部已解析 · 覆盖率 ${coverage}%`}</span>
        </Tile>
        <Tile span={3} className="dv3-stat">
          <span className="dv3-stat__orb" aria-hidden="true"><Layers size={18} /></span>
          <span className="v3-tile__label">知识分块</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={overview.chunks} />
            <em>块</em>
          </span>
          <span className="v3-tile__hint">按文档 chunk_count 汇总</span>
        </Tile>
        <Tile span={3} className="dv3-stat">
          <span className="dv3-stat__orb" aria-hidden="true"><Type size={18} /></span>
          <span className="v3-tile__label">入库总字数</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={overview.chars / 10000} format={(n) => n.toFixed(1)} />
            <em>万</em>
          </span>
          <span className="v3-tile__hint">按 documents.content_length 汇总</span>
        </Tile>
      </div>

      {/* 科目分布 + 操作 */}
      <Card className="dv3-filter">
        <div className="dv3-filter__top">
          <span className="dv3-filter__label"><FolderOpen size={15} />科目分布</span>
          {subjectStats && (subjectStats.subjects || []).length > 0 ? (
            <div className="dv3-chips" role="group" aria-label="按科目筛选">
              <Chip active={subject === 'all'} onClick={() => setSubject('all')}>
                全部科目
                <span className="dv3-chip-n">{subjectStats.total_documents ?? docs.length}</span>
              </Chip>
              {(subjectStats.subjects || []).map((s) => {
                const n = s.merged_document_count ?? s.document_count
                return (
                  <Chip
                    key={s.name}
                    active={subject === s.name}
                    onClick={() => setSubject(subject === s.name ? 'all' : s.name)}
                  >
                    {s.name}
                    <span className="dv3-chip-n">{n}</span>
                  </Chip>
                )
              })}
            </div>
          ) : (
            <span className="dv3-filter__hint">暂无科目统计</span>
          )}
          {isAdmin ? (
            <Button
              variant="text"
              size="sm"
              icon={<Settings size={14} />}
              className="dv3-subjmgr-open"
              disabled={!backendOk}
              onClick={openSubjectMgr}
            >
              科目维护
            </Button>
          ) : null}
        </div>

        <div className="dv3-filter__actions">
          <div className="dv3-search">
            <Input
              icon={<Search size={15} />}
              placeholder="搜索文档 / 摘要"
              aria-label="搜索文档 / 摘要"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          {isAdmin ? (
            <div className="dv3-filter__tools">
              <Button
                variant="text"
                size="sm"
                icon={<RefreshCw size={14} />}
                loading={parsingAll}
                disabled={!backendOk || !overview.pending}
                onClick={parseAllDocs}
              >
                批量解析未入库{overview.pending ? `（${overview.pending}）` : ''}
              </Button>
              <Button
                variant="text"
                size="sm"
                icon={<FolderOpen size={14} />}
                disabled={!backendOk || scanningRoot}
                onClick={() => openScan(false)}
              >
                {scanBacking ? '备份中，请勿关闭…' : scanningRoot ? '扫描中…' : '扫描归档根目录'}
              </Button>
            </div>
          ) : null}
        </div>
      </Card>

      {/* 批量操作栏 */}
      {isAdmin && !loadErr && docs.length > 0 ? (
        <div className="dv3-bulk" role="region" aria-label="批量操作">
          <label className="dv3-check dv3-bulk__all">
            <input
              type="checkbox"
              checked={filtered.length > 0 && filtered.every((d) => selected.has(d.id))}
              onChange={(e) => toggleAll(e.target.checked)}
            />
            <span className="dv3-check__box" aria-hidden="true" />
            <span>全选当前 {filtered.length} 篇</span>
          </label>

          {selected.size > 0 ? (
            <div className="dv3-bulk__actions">
              <Badge tone="primary">已选 {selected.size}</Badge>
              <Button variant="text" size="sm" disabled={bulkBusy} onClick={() => bulkAction('archive')}>归档源文件</Button>
              <Button variant="text" size="sm" disabled={bulkBusy} onClick={() => bulkAction('set_subject')}>批量改科目</Button>
              <Button variant="text" size="sm" disabled={bulkBusy} onClick={() => bulkAction('mark_delete')}>标记删除</Button>
              <Button
                variant="text"
                size="sm"
                disabled={bulkBusy}
                title="物理删除需开启 KAOYAN_ALLOW_PHYSICAL_DELETE=1"
                onClick={() => bulkAction('purge')}
              >
                物理删除
              </Button>
              <Button variant="text" size="sm" disabled={bulkBusy} onClick={clearSelection}>清除选择</Button>
            </div>
          ) : null}

          <div className="dv3-bulk__right">
            <Badge tone={emptyCount ? 'warning' : 'outline'}>{emptyCount} 篇正文缺失</Badge>
            <Button
              variant="text"
              size="sm"
              icon={<FolderOpen size={14} />}
              disabled={!backendOk || scanningRoot}
              onClick={() => openScan(true)}
            >
              预览扫描归档
            </Button>
          </div>
        </div>
      ) : null}

      {/* 列表三态 */}
      {loading && docs.length === 0 ? (
        <div className="dv3-grid" aria-busy="true" aria-label="正在加载文档">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card className="dv3-doc dv3-doc--skeleton" key={i}>
              <Skeleton height={16} width="38%" />
              <Skeleton height={20} width="72%" />
              <Skeleton height={12} width="54%" />
              <Skeleton height={12} width="88%" />
              <Skeleton height={30} width="100%" />
            </Card>
          ))}
        </div>
      ) : loadErr ? (
        <Card>
          <Empty
            icon={<AlertCircle size={26} />}
            title="文档列表加载失败"
            text={loadErr}
            action={(
              <Button variant="tonal" icon={<RefreshCw size={15} />} loading={loading} onClick={refresh}>
                重新加载
              </Button>
            )}
          />
        </Card>
      ) : filtered.length === 0 ? (
        <Card>
          <Empty
            icon={<FolderOpen size={26} />}
            title={docs.length ? '没有匹配的文档' : isAdmin ? '知识库还是空的' : '知识库里还没有资料'}
            text={docs.length
              ? '换个关键词或清除科目筛选试试'
              : isAdmin
                ? '上传一份讲义或真题，让 AI 帮你解析知识点'
                : '共享资料由管理员统一导入，导入后即可在此浏览、检索与收藏'}
            action={(
              <div className="dv3-empty-actions">
                {docs.length > 0 ? (
                  <Button
                    variant="tonal"
                    onClick={() => { setQ(''); setSubject('all') }}
                  >
                    清除筛选
                  </Button>
                ) : isAdmin ? (
                  <Button variant="gradient" icon={<Upload size={15} />} onClick={() => setUploadOpen(true)}>
                    选择文件上传
                  </Button>
                ) : (
                  <Button variant="tonal" icon={<RefreshCw size={15} />} loading={loading} onClick={refresh}>
                    重新加载
                  </Button>
                )}
              </div>
            )}
          />
        </Card>
      ) : (
        <div className="dv3-grid">
          {visibleDocs.map((d) => (
            <DocCard
              key={d.id}
              d={d}
              selected={selected.has(d.id)}
              parsingId={parsingId}
              analyzingId={analyzingId}
              onToggle={toggleSelect}
              onOpen={openDetail}
              onParse={parseDoc}
              onAnalyze={analyzeDoc}
              onGenerateQuiz={generateQuiz}
              onChangeSubject={(doc) => openSubjectDialog([doc])}
              onArchive={archiveDoc}
              onRemove={removeDoc}
              onDownload={downloadOriginal}
              onReviewQuestions={openReview}
              onKbImport={(doc) => openKbImport('single', doc)}
              onPreviewFile={openFilePreview}
              canManage={isAdmin}
            />
          ))}
        </div>
      )}

      {!loadErr && filtered.length > 0 ? (
        <div className="dv3-loadmore">
          <span className="v3-caption">
            已显示 {Math.min(limit, filtered.length)} / {filtered.length} 篇
            {filtered.length > limit ? ` · 还有 ${filtered.length - limit} 篇未渲染` : ' · 已全部显示'}
          </span>
          {filtered.length > limit ? (
            <div className="dv3-loadmore__actions">
              <Button variant="tonal" size="sm" onClick={() => setLimit((n) => n + PAGE_SIZE)}>
                加载更多（{Math.min(PAGE_SIZE, filtered.length - limit)} 篇）
              </Button>
              <Button variant="text" size="sm" onClick={() => setLimit(PAGE_SIZE)}>回到首屏</Button>
            </div>
          ) : null}
        </div>
      ) : null}
        </>
      ) : null}

      {view === 'search' ? (
        <RagSearchPanel
          backendOk={backendOk}
          subjectOptions={subjectOptions}
          onOpenDoc={openDocById}
        />
      ) : null}

      {view === 'knowledge' ? (
        <KnowledgeView
          backendOk={backendOk}
          docs={docs}
          onOpenDoc={(doc) => openDetail(doc, 'overview')}
        />
      ) : null}

      {/* 隐藏文件选择器：dropzone 与上传按钮共用 */}
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={ACCEPT}
        aria-label="选择要上传到知识库的文件"
        style={{ display: 'none' }}
        onChange={(e) => {
          enqueue(e.target.files)
          e.target.value = ''
        }}
      />

      {/* 批量上传 */}
      <Dialog
        open={uploadOpen}
        wide
        title="批量上传"
        sub="支持多选 · 同名同大小自动跳过 · 上传后自动解析"
        onClose={closeUpload}
        footer={(
          <>
            <Button variant="text" size="sm" onClick={clearQueue} disabled={uploading || queue.length === 0}>
              清空队列
            </Button>
            <Button variant="text" size="sm" onClick={closeUpload} disabled={uploading}>
              关闭
            </Button>
            {queueStat.dup > 0 ? (
              <Button variant="tonal" size="sm" onClick={() => runQueue(true)} disabled={uploading || !backendOk}>
                连重复一起上传
              </Button>
            ) : null}
            <Button
              variant="filled"
              size="sm"
              loading={uploading}
              disabled={!queueStat.pending || !backendOk}
              onClick={() => runQueue(false)}
            >
              {uploading ? '上传中…' : `开始上传${queueStat.pending ? `（${queueStat.pending}）` : ''}`}
            </Button>
          </>
        )}
      >
        <div className="dv3-upload">
          {!backendOk ? (
            <Alert tone="danger">
              后端未连接（8000），上传与解析暂不可用。连接后可在此拖入文件。
            </Alert>
          ) : null}
          <div
            className={cx('dv3-drop', dragging && 'is-dragging', uploading && 'is-disabled')}
            role="button"
            tabIndex={0}
            aria-disabled={uploading}
            onClick={() => { if (!uploading) fileRef.current?.click() }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                if (!uploading) fileRef.current?.click()
              }
            }}
            onDragOver={(e) => { e.preventDefault(); if (!uploading) setDragging(true) }}
            onDragEnter={(e) => { e.preventDefault(); if (!uploading) setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              if (!uploading) enqueue(e.dataTransfer?.files)
            }}
          >
            <span className="dv3-drop__orb" aria-hidden="true"><Upload size={24} /></span>
            <b>{uploading ? '上传队列执行中…' : '把 PDF / Word / TXT / Markdown 拖到这里，或点击选择'}</b>
            <p>{ACCEPT.replaceAll('.', '').toUpperCase()} · 支持多选 · 上传前按「文件名 + 字节数」比对去重</p>
            <Button
              variant="tonal"
              size="sm"
              icon={<FolderOpen size={14} />}
              disabled={uploading}
              onClick={(e) => { e.stopPropagation(); if (!uploading) fileRef.current?.click() }}
            >
              选择文件
            </Button>
          </div>

          {queue.length === 0 ? (
            <p className="dv3-upload__hint">还没有加入文件。选择或拖入文件后，将在上传前自动比对库内文档。</p>
          ) : (
            <div className="dv3-queue">
              <div className="dv3-queue__head">
                <div>
                  <b>上传队列</b>
                  <span>{queueStat.finished} / {queueStat.total} 已处理</span>
                </div>
                <Badge tone={uploading ? 'primary' : queueStat.error ? 'warning' : 'success'}>
                  {uploading ? '进行中' : queueStat.error ? '部分失败' : '已完成'}
                </Badge>
              </div>
              <Progress value={queueStat.pct} gradient={!queueStat.error} height={6} />
              <div className="dv3-queue__summary">
                <Badge tone="outline">待上传 {queueStat.pending}</Badge>
                <Badge tone="warning">重复 {queueStat.dup}</Badge>
                <Badge tone="success">完成 {queueStat.done}</Badge>
                {queueStat.error > 0 ? <Badge tone="danger">失败 {queueStat.error}</Badge> : null}
              </div>
              <div className="dv3-queue__list">
                {queue.map((it) => {
                  const meta = QUEUE_META[it.status] || QUEUE_META.pending
                  const locked = uploading && ['uploading', 'parsing'].includes(it.status)
                  return (
                    <div className={cx('dv3-qrow', it.status === 'error' && 'is-error')} key={it.key}>
                      <span className="dv3-qrow__ext">{extOf(it.name)}</span>
                      <div className="dv3-qrow__main">
                        <div className="dv3-qrow__name" title={it.name}>{it.name}</div>
                        <div className="dv3-qrow__meta">
                          {fmtBytes(it.size)}{it.msg ? ` · ${it.msg}` : ''}
                        </div>
                      </div>
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                      <IconButton
                        label={`移除 ${it.name}`}
                        size="sm"
                        icon={<X size={15} />}
                        disabled={uploading || locked}
                        onClick={() => setQueue((prev) => prev.filter((o) => o.key !== it.key))}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </Dialog>

      {/* 扫描根目录归档 */}
      <Dialog
        open={scanOpen}
        title="扫描归档根目录"
        sub="扫描 knowledge_base 根目录，按科目归档到「科目/」并同步 DB 路径"
        onClose={closeScan}
        footer={(
          <>
            <Button variant="text" size="sm" onClick={closeScan} disabled={scanningRoot}>取消</Button>
            <Button
              variant={scanDry ? 'filled' : 'danger'}
              size="sm"
              loading={scanningRoot}
              onClick={runScan}
              disabled={!backendOk}
            >
              {scanningRoot ? (scanBacking ? '备份中…' : '扫描中…') : scanDry ? '开始预览' : '执行归档'}
            </Button>
          </>
        )}
      >
        <div className="dv3-scan">
          <ul className="dv3-scan__tips">
            <li>扫描根目录中尚未归档的文件，按科目移动到「科目/」目录。</li>
            <li>数据库内的路径同步更新；断链记录只统计，不改动文件。</li>
            <li>执行归档前会先做一次全库备份，备份期间请勿关闭或刷新页面。</li>
          </ul>

          <div className="dv3-switchrow">
            <div>
              <b>预览模式（dry run）</b>
              <p>只统计将移动、跳过、断链与失败的数量，不移动任何文件。</p>
            </div>
            <Switch
              checked={scanDry}
              onChange={setScanDry}
              label="预览模式（dry run）"
              disabled={scanningRoot}
            />
          </div>

          {!scanDry ? (
            <Alert tone="warning" icon={<AlertTriangle size={17} />}>
              归档会移动源文件并先做全库备份（耗时取决于库大小），期间请勿关闭页面。
            </Alert>
          ) : null}

          {scanBacking ? (
            <div className="dv3-scan__backing" role="status">
              <span className="dv3-spin" aria-hidden="true" />
              正在备份数据库（库越大越久），完成后自动按科目归档。<b>请勿关闭或刷新页面。</b>
            </div>
          ) : null}

          {scanResult ? (
            <div className="dv3-scan__result">
              <div className="dv3-panel-head">
                <b>{scanResult.dryRun ? '预览结果' : '归档结果'}</b>
                <Badge tone={scanResult.dryRun ? 'outline' : 'success'}>
                  {scanResult.dryRun ? '未移动文件' : '已执行'}
                </Badge>
              </div>
              <div className="dv3-scan__metrics">
                <div className="dv3-scan__metric"><b>{scanResult.moved}</b><span>移动</span></div>
                <div className="dv3-scan__metric"><b>{scanResult.skipped}</b><span>跳过</span></div>
                <div className="dv3-scan__metric"><b>{scanResult.broken}</b><span>断链</span></div>
                <div className="dv3-scan__metric"><b>{scanResult.errors}</b><span>失败</span></div>
              </div>
              {scanResult.message ? <p className="dv3-scan__msg">{scanResult.message}</p> : null}
            </div>
          ) : null}
        </div>
      </Dialog>

      {/* 改科目 */}
      <Dialog
        open={!!subjectDlg}
        title={subjectDlg?.count > 1 ? `批量改科目（${subjectDlg.count} 篇）` : '修改文档科目'}
        sub="保存后立即更新文档科目，并刷新列表与科目统计。"
        onClose={() => { if (!savingSubject) setSubjectDlg(null) }}
        footer={(
          <>
            <Button variant="text" size="sm" onClick={() => setSubjectDlg(null)} disabled={savingSubject}>取消</Button>
            <Button variant="filled" size="sm" loading={savingSubject} onClick={saveSubject}>保存</Button>
          </>
        )}
      >
        <Field label="科目名称" hint="填写科目名，保存后列表与科目统计会刷新。">
          <Input
            value={subjectValue}
            onChange={(e) => setSubjectValue(e.target.value)}
            placeholder="如：数字电子技术"
            aria-label="科目名称"
            onKeyDown={(e) => { if (e.key === 'Enter') saveSubject() }}
          />
        </Field>
        {subjectStats && (subjectStats.subjects || []).length > 0 ? (
          <div className="dv3-subj-suggest">
            <span className="dv3-subj-suggest__label">已有科目</span>
            <div className="dv3-chips">
              {(subjectStats.subjects || []).slice(0, 12).map((s) => (
                <Chip
                  key={s.name}
                  active={subjectValue.trim() === s.name}
                  onClick={() => setSubjectValue(s.name)}
                >
                  {s.name}
                </Chip>
              ))}
            </div>
          </div>
        ) : null}
      </Dialog>

      {/* 知识库题目识别 / 确认入库 */}
      <KbImportDialog
        open={!!kbImport}
        docs={docs}
        listIds={filtered.map((d) => Number(d.id))}
        defaultScope={kbImport?.defaultScope || 'list'}
        initialDocId={kbImport?.docId || ''}
        onClose={() => setKbImport(null)}
        onImported={() => { refresh(); refreshSubjects() }}
      />

      {/* 题目预览与人工审核 */}
      <QuestionReviewDialog
        open={!!reviewDoc}
        doc={reviewDoc}
        onClose={() => setReviewDoc(null)}
        onImported={refresh}
      />

      {/* 科目维护 */}
      <SubjectMgrDialog
        open={subjMgrOpen}
        onClose={() => setSubjMgrOpen(false)}
        onSubjectsChanged={refreshSubjects}
      />

      {/* 原文件预览 */}
      <RawFilePreviewDialog doc={fileDoc} onClose={() => setFileDoc(null)} />

      {/* 文档详情抽屉 */}
      <DocumentsDetail
        open={!!detail}
        doc={detailDoc}
        tab={detail?.tab || 'overview'}
        onTab={(tab) => setDetail((prev) => (prev ? { ...prev, tab } : prev))}
        onClose={() => setDetail(null)}
        backendOk={backendOk}
        parsingId={parsingId}
        analyzingId={analyzingId}
        onParse={parseDoc}
        onAnalyze={analyzeDoc}
        onGenerateQuiz={generateQuiz}
        onArchive={archiveDoc}
      />

      {confirmDialog}
    </div>
  )
}
