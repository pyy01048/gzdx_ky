import React, { useMemo, useState, useCallback, useEffect, useRef } from 'react'
import useStore from '../store/useStore'
import { fmtDateCN } from '../utils/date'
// 体积口径全站一份：0 字节显示「—」，不再被 Math.max(1,...) 报成「1 KB」
import { fmtBytes } from '../utils/format'
import { SubTag, Modal, toast, CountUp } from '../components/UI'
import { LoadingState, ErrorState, EmptyState } from '../components/States'
import { documentsApi, aiApi, kbImportApi, taxonomyApi, request, fileUrl } from '../api/client'
import KbHealthPanel from '../components/KbHealthPanel'

/* ============================================================
   文档知识库（V2 冷蓝）
   · 上传讲义 / 真题 / 笔记 → 解析入库 → 知识点 / 分块 / RAG 检索
   V2 新增：
   ① 批量上传 + 去重：dropzone 拖拽多文件，按「文件名 + 字节数」指纹与库内文档比对，重复自动跳过
   ② 知识点图谱预览：知识点以 chip 标签云呈现，按科目 / 频率筛选，点击查看详情并可一键转记忆卡片
   V3 治理（学习文库 / 文档知识库深度重构）：
   ③ 三态（loading/empty/error）齐全，接入统一 States.jsx 组件
   ④ 详情抽屉：Markdown 快照预览 + 导出 md/txt/pdf + 归档源文件 + 原始文件下载
   ⑤ 批量选择：批量归档 / 标记删除 / 改科目（物理删除仍走 delete_guard 闸门）
   ⑥ 内联科目维护入口（增删改科目，走科目 API，不硬编码）
   ⑦ 空正文文档显著标记「正文缺失/待重新解析」并提供重新解析入口
   ⑧ 扫描 knowledge_base 根目录 → 按科目自动归档（含断链跳过报告）
   ============================================================ */

/* 文档治理：新端点未进 documentsApi（避免与并行改动冲突），此处就地封装 */
const governanceApi = {
  snapshot: (id) => request(`/documents/${id}/snapshot`),
  exportUrl: (id, fmt) => fileUrl(`/documents/${id}/export`, { fmt: fmt || 'md' }),
  archive: (id) => request(`/documents/${id}/archive`, { method: 'POST', body: {} }),
  bulk: (body) => request('/documents/bulk', { method: 'POST', body }),
  scanRoot: (dryRun) => request('/documents/scan-root', { method: 'POST', body: { dry_run: !!dryRun } }),
}

const EMPTY_CT = { subject: '', doc_type: '', stage: '', content_type: '', subject_source: '' }

const VIEWS = [
  { label: '文档列表', value: 'list' },
  { label: '知识点图谱', value: 'knowledge' },
  { label: '知识库检索', value: 'search' }
]

/* 浏览器自己能渲染的类型才塞进 iframe；docx/ppt 塞进去只会变成一张下载提示。 */
const INLINE_EXT = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg',
  'txt', 'md', 'markdown', 'csv', 'html']
const canInlinePreview = (d) => {
  const ext = String(d?.file_name || '').toLowerCase().split('.').pop()
  return INLINE_EXT.includes(ext) || INLINE_EXT.includes(String(d?.file_type || '').toLowerCase())
}

const ACCEPT = '.pdf,.docx,.doc,.txt,.md'

/* 正文缺失判定：content_length 为 0（后端 documents.content 为空）。
   实测约 150 篇此类文档，列表里要能一眼看出、并能就地重新解析。 */
const isEmptyBody = (d) => (Number(d?.content_length) || 0) === 0

/* 文件指纹：名称 + 字节数（同名同大小视为重复） */
const sigOf = (name, size) => `${(name || '').trim().toLowerCase()}::${size || 0}`

const TYPE_ICO = { pdf: { text: 'PDF', cls: 'red' }, docx: { text: 'DOC', cls: 'blue' }, doc: { text: 'DOC', cls: 'blue' }, md: { text: 'MD', cls: 'violet' }, txt: { text: 'TXT', cls: 'neutral' } }

/* ---------------- V8 阶段3：kb-import 契约容错规范化 ----------------
   后端实测形态：items[].candidates[] = {content, options, answer, analysis,
   question_type, subject, chapter, knowledge_point, difficulty, content_hash,
   already_exists, index}。题干字段是 content，去重标记是 already_exists。 */
const kbCandStem = (c) => c.content || c.question || c.text || c.stem || c.title || c.题干 || '（无题干）'
const kbCandType = (c) => c.question_type || c.type || c.qtype || c.题型 || ''
const kbCandExisting = (c) => !!(c.already_exists || c.is_existing || c.exists || c.dup || c.is_dup || c.in_quiz)

// 把后端 scan 响应规整为统一结构；任何非数组都降级为空，绝不抛错
function kbNormalize(resp) {
  const rawItems = resp?.items || resp?.candidates || resp?.docs || []
  const items = (Array.isArray(rawItems) ? rawItems : []).map((it) => {
    const docId = it.doc_id ?? it.id ?? ''
    const cands = Array.isArray(it.candidates) ? it.candidates : (Array.isArray(it.items) ? it.items : [])
    return {
      doc_id: docId,
      doc_title: it.doc_title ?? it.title ?? it.file_name ?? it.filename ?? '未命名文档',
      subject: it.subject || '未分类',
      truncated: !!it.truncated,
      candidates: (Array.isArray(cands) ? cands : []).map((c, i) => {
        const stem = kbCandStem(c)
        // index 由后端下发（文档内去重后的稳定下标），confirm 原样回传；缺省用数组位置兜底
        const candIndex = typeof c.index === 'number' ? c.index : i
        return {
          _key: `${docId}::${candIndex}`,
          docId,
          candIndex,
          stem,
          type: kbCandType(c),
          existing: kbCandExisting(c),
          raw: c
        }
      })
    }
  }).filter((d) => d.candidates.length > 0)
  return {
    totalDocs: resp?.total_docs ?? resp?.totalDocs ?? items.length,
    scannedDocs: resp?.scanned_docs ?? resp?.scannedDocs ?? items.length,
    totalCandidates: resp?.total_candidates ?? resp?.totalCandidates ?? items.reduce((s, d) => s + d.candidates.length, 0),
    dupSkipped: resp?.dup_skipped ?? resp?.dupSkipped ?? resp?.duplicates_skipped ?? 0,
    elapsed: resp?.elapsed_seconds ?? resp?.elapsed_ms ?? 0,
    items
  }
}

export default function Documents() {
  const addCard = useStore((s) => s.addCard)
  const [backendOk, setBackendOk] = useState(false)
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [subject, setSubject] = useState('all')
  const [subjectStats, setSubjectStats] = useState(null)
  const [subjectOptions, setSubjectOptions] = useState([])
  const [q, setQ] = useState('')
  const [uploading, setUploading] = useState(false)
  const [parsingId, setParsingId] = useState(null)
  const [analyzingId, setAnalyzingId] = useState(null)
  const [previewingId, setPreviewingId] = useState(null)
  const [showPreview, setShowPreview] = useState(false)
  const [previewQuestions, setPreviewQuestions] = useState([])
  const [previewOwner, setPreviewOwner] = useState(null)
  const [editingQuestionIdx, setEditingQuestionIdx] = useState(null)
  const fileRef = useRef(null)
  const [view, setView] = useState('list') // list / knowledge / search
  const [kpDoc, setKpDoc] = useState(null)
  const [kpList, setKpList] = useState([])
  const [chunkDoc, setChunkDoc] = useState(null)
  const [chunkList, setChunkList] = useState([])
  // RAG 检索
  const [ragQ, setRagQ] = useState('')
  const [ragSubject, setRagSubject] = useState('')
  const [ragLoading, setRagLoading] = useState(false)
  const [ragHits, setRagHits] = useState([])
  // 新增① 批量上传队列
  const [queue, setQueue] = useState([]) // { key, name, size, status: pending|uploading|done|dup|error, msg }
  const [dragging, setDragging] = useState(false)
  const [showQueue, setShowQueue] = useState(false)
  // 新增② 知识点图谱
  const [kpSubject, setKpSubject] = useState('all')
  const [activeKp, setActiveKp] = useState(null)
  // V8 阶段3：知识库 → 刷题库 批量识别预览与确认入库
  const [kbOpen, setKbOpen] = useState(false)
  const [kbLoading, setKbLoading] = useState(false)
  const [kbError, setKbError] = useState('')
  const [kbResult, setKbResult] = useState(null) // { summary, items:[{doc_id,doc_title,subject,candidates:[{_key,docId,candIndex,stem,type,existing,raw}]}] }
  const [kbChecked, setKbChecked] = useState(() => new Set())
  const [kbExpanded, setKbExpanded] = useState(() => new Set())
  const [kbConfirming, setKbConfirming] = useState(false)
  const [kbDone, setKbDone] = useState(null) // 确认入库结果 {inserted, skipped, outOfRange, bySubject}
  const [kbDocIds, setKbDocIds] = useState(null) // null=全库；number[]=分批范围
  const [kbScopeLabel, setKbScopeLabel] = useState('全库') // Modal 标题展示用

  // V3 治理：批量选择 / 详情抽屉 / 内联科目维护 / 扫描归档
  const [selected, setSelected] = useState(() => new Set())
  const [detailDoc, setDetailDoc] = useState(null)
  const [snapshot, setSnapshot] = useState({ state: 'idle', md: '', path: '', exists: false })
  const [bulkBusy, setBulkBusy] = useState(false)
  const [scanningRoot, setScanningRoot] = useState(false)
  const [subjMgrOpen, setSubjMgrOpen] = useState(false)
  const [subjList, setSubjList] = useState([])
  const [subjBusy, setSubjBusy] = useState(false)
  const [subjEditor, setSubjEditor] = useState({ open: false, mode: 'create', original: '', name: '' })

  const refreshSubjects = useCallback(async () => {
    try {
      const s = await documentsApi.subjects()
      setSubjectStats(s)
      // 篇数必须是「点这一科实际能拿到的篇数」：后端会把「公共课-数学」这类
      // 别名写法折叠进「数学」，所以优先用 merged_document_count，用原值就少报。
      const opts = (s.subjects || []).map((x) => {
        const n = x.merged_document_count ?? x.document_count
        return { label: `${x.name}（${n} 篇）${(x.aliases || []).length ? ' 含别名写法' : ''}`, value: x.name }
      })
      setSubjectOptions(opts)
    } catch { /* 后端离线时静默 */ }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const d = await documentsApi.list({ subject: subject === 'all' ? undefined : subject })
      const list = Array.isArray(d) ? d : (d.documents || d.items || [])
      if (Array.isArray(list)) {
        setDocs(list.map((x) => ({
          id: String(x.id),
          filename: x.file_name || x.filename || x.name || '未命名文档',
          file_name: x.file_name || x.filename || x.name || '未命名文档',
          doc_type: x.file_type || x.doc_type || 'txt',
          file_type: x.file_type || '',
          size: x.size || 0,
          subject: x.subject || '未分类',
          status: x.index_status === 'indexed' ? 'parsed' : (x.index_status || 'uploaded'),
          // 后端没给日期就是「未知」，不能拿当前时间冒充上传时间 —— 页面会把它
          // 排在「最新上传」最前面，等于伪造排序依据。
          uploaded_at: x.created_at || '',
          summary: (x.summary || '').slice(0, 120),
          content_length: x.content_length || 0,
          chunk_count: x.chunk_count || 0,
          // V3 治理字段：原文可读性 / 阶段 / 来源，供详情抽屉与空正文标记使用
          has_local_file: !!x.has_local_file,
          local_file_note: x.local_file_note || '',
          chunk_count_raw: x.chunk_count || 0,
          stage: x.stage || '',
          content_type: x.content_type || '',
          subject_source: x.subject_source || '',
          folder_path: x.folder_path || '',
          index_status: x.index_status || '',
        })))
        setBackendOk(true)
        setLoadErr('')
      }
    } catch (e) {
      setDocs([])
      setBackendOk(false)
      setLoadErr(e?.message || '文档列表加载失败')
    } finally {
      setLoading(false)
    }
  }, [subject])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { refreshSubjects() }, [])

  const filtered = useMemo(() => {
    let arr = docs
    if (subject !== 'all') arr = arr.filter((d) => d.subject === subject)
    if (q.trim()) arr = arr.filter((d) => (d.filename + (d.summary || '')).toLowerCase().includes(q.toLowerCase()))
    return arr
  }, [docs, subject, q])

  /* 库内已有文档指纹集合（用于上传去重） */
  const existSigs = useMemo(() => new Set(docs.map((d) => sigOf(d.filename, d.size))), [docs])

  const overview = useMemo(() => {
    const parsed = docs.filter((d) => d.status === 'parsed').length
    const chunks = docs.reduce((s, d) => s + (d.chunk_count || 0), 0)
    const chars = docs.reduce((s, d) => s + (d.content_length || 0), 0)
    return { total: docs.length, parsed, pending: docs.length - parsed, chunks, chars }
  }, [docs])

  /* ---------------- 单文件上传（保留原逻辑） ---------------- */
  const upload = async (file) => {
    if (!file) return
    if (!backendOk) return toast('需先连接后端（8000）才能上传解析')
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await documentsApi.upload(fd)
      toast(r.message || '上传成功')
      await refresh()
      if (r.id) { setParsingId(String(r.id)); parse(String(r.id)) }
    } catch (e) {
      toast(`上传失败：${e.message}`)
    }
    setUploading(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  /* ---------------- 新增① 批量上传 + 去重 ---------------- */
  const enqueue = (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    if (!backendOk) { toast('需先连接后端（8000）才能上传解析'); return }
    const seen = new Set(queue.map((it) => it.key))
    const items = []
    let dup = 0
    files.forEach((f) => {
      const key = sigOf(f.name, f.size)
      if (seen.has(key)) { dup++; return } // 队列内重复
      seen.add(key)
      const isDup = existSigs.has(key)
      if (isDup) dup++
      items.push({ key, name: f.name, size: f.size, file: f, status: isDup ? 'dup' : 'pending', msg: isDup ? '库中已存在同名同大小文档' : '' })
    })
    if (!items.length) { toast(`已忽略 ${dup} 个重复文件`); return }
    setQueue((x) => [...x, ...items])
    setShowQueue(true)
    if (dup) toast(`加入 ${items.filter((i) => i.status === 'pending').length} 个文件，检出 ${dup} 个重复`)
    else toast(`已加入 ${items.length} 个文件，点「开始上传」`)
  }

  const runQueue = async (force = false) => {
    const targets = queue.filter((it) => it.status === 'pending' || (force && it.status === 'dup') || it.status === 'error')
    if (!targets.length) return toast('没有待上传文件')
    setUploading(true)
    let ok = 0
    let fail = 0
    for (const it of targets) {
      setQueue((x) => x.map((o) => (o.key === it.key ? { ...o, status: 'uploading', msg: '上传中…' } : o)))
      try {
        const fd = new FormData()
        fd.append('file', it.file)
        const r = await documentsApi.upload(fd)
        ok++
        setQueue((x) => x.map((o) => (o.key === it.key ? { ...o, status: 'done', msg: r.message || '上传成功，正在解析' } : o)))
        if (r.id) {
          try { await documentsApi.parse(Number(r.id)) } catch { /* 解析失败不阻塞队列 */ }
        }
      } catch (e) {
        fail++
        setQueue((x) => x.map((o) => (o.key === it.key ? { ...o, status: 'error', msg: e.message } : o)))
      }
    }
    setUploading(false)
    await refresh()
    refreshSubjects()
    toast(`批量上传完成：成功 ${ok} 个${fail ? `，失败 ${fail} 个` : ''}`)
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    enqueue(e.dataTransfer?.files)
  }

  const queueStat = useMemo(() => ({
    pending: queue.filter((i) => i.status === 'pending').length,
    dup: queue.filter((i) => i.status === 'dup').length,
    done: queue.filter((i) => i.status === 'done').length,
    error: queue.filter((i) => i.status === 'error').length
  }), [queue])

  const parse = async (id) => {
    setParsingId(id)
    try {
      const r = await documentsApi.parse(Number(id))
      toast(r.message || '解析完成，已提取知识点')
      await refresh()
    } catch (e) {
      // 422 = 质量闸门拒绝，detail 已经是完整原因，不能再加上「解析失败」把
      // 「被规则拦下」和「代码报错」混成同一句话。
      toast(e.status === 422 ? e.message : `解析失败：${e.message}`)
    }
    setParsingId(null)
  }

  const showKnowledge = async (d) => {
    if (!backendOk) return toast('需连接后端查看知识点')
    try {
      const r = await documentsApi.knowledgePoints(Number(d.id))
      setKpList(r.knowledge_points || r.points || [])
      setKpDoc(d)
      setChunkDoc(null)
      setKpSubject('all')
      setActiveKp(null)
      setView('knowledge')
    } catch (e) {
      toast(`获取知识点失败：${e.message}`)
    }
  }

  const showChunks = async (d) => {
    if (!backendOk) return toast('需连接后端查看知识分块')
    try {
      const r = await documentsApi.chunks(Number(d.id))
      setChunkList(r.chunks || [])
      setChunkDoc(d)
      setView('knowledge')
      setKpDoc(null)
    } catch (e) {
      toast(`获取分块失败：${e.message}`)
    }
  }

  const doRagSearch = async () => {
    const query = ragQ.trim()
    if (!query) return toast('请输入检索内容')
    if (!backendOk) return toast('需连接后端进行知识库检索')
    setRagLoading(true)
    try {
      const r = await aiApi.ragSearch({ query, subject: ragSubject || undefined, limit: 10 })
      setRagHits(r.hits || [])
      if ((r.hits || []).length === 0) toast('未检索到相关知识，可换个关键词试试')
    } catch (e) {
      setRagHits([])
      toast(`检索失败：${e.message}`)
    }
    setRagLoading(false)
  }

  const generateQuiz = async (d) => {
    if (!backendOk) return toast('需连接后端生成题目')
    try {
      const r = await documentsApi.generateQuiz(Number(d.id), { count: 5 })
      toast(`已生成 ${r.questions_created || 5} 道题目，可在刷题中心查看`)
    } catch (e) {
      toast(`生成失败：${e.message}`)
    }
  }

  // V2.0 智能分析：长文本识别 + 自动分类知识点/题目/真题
  const analyze = async (d) => {
    if (!backendOk) return toast('需连接后端智能分析')
    if (!confirm('智能分析将AI识别文档中的知识点和题目（真题/模拟题自动分类），可能需要1-3分钟，确定开始？')) return
    setAnalyzingId(d.id)
    try {
      const r = await documentsApi.analyze(Number(d.id), { extract_kp: true, extract_questions: true })
      toast(`分析完成：${r.knowledge_points || 0}个知识点，${r.questions || 0}道题目（真题已自动分类）`)
      await refresh()
      refreshSubjects()
    } catch (e) {
      toast(`分析失败：${e.message}`)
    } finally {
      setAnalyzingId(null)
    }
  }

  // V3.0 题目预览与人工编辑
  const handlePreviewQuestions = async (d) => {
    if (!backendOk) return toast('需连接后端预览题目')
    setPreviewingId(d.id)
    try {
      const result = await documentsApi.previewQuestions(Number(d.id))
      setPreviewQuestions(result.questions || [])
      setPreviewOwner(d)
      setShowPreview(true)
      toast(`预览到 ${result.total ?? (result.questions || []).length} 道题目，请人工审核`)
    } catch (e) {
      toast(`预览失败: ${e.message}`)
    } finally {
      setPreviewingId(null)
    }
  }

  // 更新预览中的题目
  const updatePreviewQuestion = (idx, field, value) => {
    const updated = [...previewQuestions]
    updated[idx] = { ...updated[idx], [field]: value }
    setPreviewQuestions(updated)
  }

  // 更新选项
  const updatePreviewOption = (qIdx, optIdx, value) => {
    const updated = [...previewQuestions]
    const options = [...(updated[qIdx].options || [])]
    options[optIdx] = value
    updated[qIdx] = { ...updated[qIdx], options }
    setPreviewQuestions(updated)
  }

  // 删除预览中的题目
  const removePreviewQuestion = (idx) => {
    const updated = previewQuestions.filter((_, i) => i !== idx)
    setPreviewQuestions(updated)
    if (editingQuestionIdx === idx) setEditingQuestionIdx(null)
    toast('已移除该题目')
  }

  // 确认入库
  const confirmImportQuestions = async (d) => {
    const target = d || previewOwner
    if (!target) return toast('缺少来源文档')
    const selected = previewQuestions.filter((x) => x.selected !== false)
    if (selected.length === 0) return toast('没有选中的题目')
    if (!confirm(`确认入库 ${selected.length} 道题目？`)) return
    try {
      const result = await documentsApi.confirmQuestions(Number(target.id), { questions: previewQuestions })
      toast(`入库完成：成功 ${result.imported} 道，跳过 ${result.skipped} 道`)
      setShowPreview(false)
      setPreviewQuestions([])
      setPreviewOwner(null)
      refresh()
    } catch (e) {
      toast(`入库失败: ${e.message}`)
    }
  }

  /* ---------------- V8 阶段3：知识库 → 题目识别预览 / 确认入库 ---------------- */
  // 按科目分布小计（仅统计候选题总数，含已存在）
  const kbSubjDist = useMemo(() => {
    if (!kbResult) return []
    const m = new Map()
    kbResult.items.forEach((d) => d.candidates.forEach((c) => m.set(d.subject, (m.get(d.subject) || 0) + 1)))
    return Array.from(m.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count)
  }, [kbResult])

  // 可勾选（新题）数量与已勾选数量
  const kbSelectable = useMemo(() => {
    if (!kbResult) return { total: 0, checked: 0 }
    let total = 0
    kbResult.items.forEach((d) => d.candidates.forEach((c) => { if (!c.existing) total++ }))
    return { total, checked: kbChecked.size }
  }, [kbResult, kbChecked])

  const runKbScan = useCallback(async (docIds) => {
    setKbLoading(true)
    setKbError('')
    setKbDone(null)
    try {
      // scan 入参：{doc_ids?}；缺省=全库
      const body = {}
      if (Array.isArray(docIds) && docIds.length) body.doc_ids = docIds
      const resp = await kbImportApi.scan(body)
      const norm = kbNormalize(resp)
      setKbResult(norm)
      // 默认勾选全部新题；已存在题置灰不可选
      const checked = new Set()
      norm.items.forEach((d) => d.candidates.forEach((c) => { if (!c.existing) checked.add(c._key) }))
      setKbChecked(checked)
      setKbExpanded(new Set())
    } catch (e) {
      setKbResult(null)
      setKbError(e?.message || '扫描失败，请稍后重试')
    } finally {
      setKbLoading(false)
    }
  }, [])

  // 打开识别预览。docIds 缺省=全库（带 5 分钟耗时警告）；传数组=分批（单文档/当前列表）。
  const openKbImport = (docIds) => {
    if (!backendOk) return toast('需先连接后端才能识别题目')
    const ids = (Array.isArray(docIds) && docIds.length) ? docIds : null
    if (!ids) {
      if (!confirm('全库识别需逐篇打分，实测约 5 分钟。建议先用「识别当前列表」或单文档「识别」分批处理。是否仍要全库扫描？')) return
      setKbScopeLabel('全库')
    } else {
      setKbScopeLabel(ids.length === 1 ? '单文档' : `当前列表（${ids.length} 篇）`)
    }
    setKbDocIds(ids)
    setKbOpen(true)
    runKbScan(ids)
  }

  const toggleKb = (key) => {
    setKbChecked((prev) => {
      const n = new Set(prev)
      if (n.has(key)) n.delete(key); else n.add(key)
      return n
    })
  }

  const toggleAllKb = (check) => {
    if (!kbResult) return
    if (check) {
      const all = new Set()
      kbResult.items.forEach((d) => d.candidates.forEach((c) => { if (!c.existing) all.add(c._key) }))
      setKbChecked(all)
    } else {
      setKbChecked(new Set())
    }
  }

  const toggleKbDoc = (docKey) => {
    setKbExpanded((prev) => {
      const n = new Set(prev)
      if (n.has(docKey)) n.delete(docKey); else n.add(docKey)
      return n
    })
  }

  const doKbConfirm = async () => {
    if (!kbResult || kbChecked.size === 0) return toast('请先勾选要入库的题目')
    if (!confirm(`确认将选中的 ${kbChecked.size} 道题目写入题库？（来源标记为「知识库:文档名」）`)) return
    setKbConfirming(true)
    try {
      // 后端契约：{selected:[{doc_id, index}]}，index 取后端 scan 下发的稳定下标
      const selected = []
      kbResult.items.forEach((d) => d.candidates.forEach((c) => {
        if (kbChecked.has(c._key)) selected.push({ doc_id: c.docId, index: c.candIndex })
      }))
      const r = await kbImportApi.confirm({ selected })
      const inserted = r?.inserted ?? 0
      const skipped = r?.skipped_existing ?? r?.skipped ?? 0
      const outOfRange = r?.out_of_range ?? 0
      const bySubject = r?.by_subject || {}
      setKbDone({ inserted, skipped, outOfRange, bySubject })
      toast(`已入库 ${inserted} 题 / 跳过已存在 ${skipped} 题`)
      refresh()
      refreshSubjects()
    } catch (e) {
      toast(`入库失败：${e?.message || e}`)
    } finally {
      setKbConfirming(false)
    }
  }

  const remove = async (id) => {
    if (!backendOk) { setDocs(docs.filter((d) => d.id !== id)); toast('已从列表移除'); return }
    if (!confirm('确定删除该文档？关联的知识分块和知识点也会被删除。')) return
    try { await documentsApi.remove(Number(id)); setDocs(docs.filter((d) => d.id !== id)); toast('文档已删除'); refreshSubjects() }
    catch (e) { toast(`删除失败：${e.message}`) }
  }

  const parseAll = async () => {
    if (!backendOk) return toast('需连接后端批量解析')
    try { const r = await documentsApi.parseAll(); toast(r.message || `批量解析完成：成功 ${r.parsed || 0}/${r.total || 0} 篇${r.rejected ? `，质量闸门拒绝 ${r.rejected} 篇` : ''}`); await refresh() }
    catch (e) { toast(`批量解析失败：${e.message}`) }
  }

  /* ---------------- V3 治理：批量选择 ---------------- */
  const toggleSelect = (id) => setSelected((prev) => {
    const n = new Set(prev)
    if (n.has(id)) n.delete(id); else n.add(id)
    return n
  })
  const toggleAllVisible = (list, check) => setSelected((prev) => {
    const n = new Set(prev)
    list.forEach((d) => { if (check) n.add(d.id); else n.delete(d.id) })
    return n
  })
  const clearSelection = () => setSelected(new Set())
  const selectedDocs = useMemo(() => docs.filter((d) => selected.has(d.id)), [docs, selected])

  /* ---------------- V3 治理：详情抽屉 + Markdown 快照 ---------------- */
  const openDetail = async (d) => {
    if (!backendOk) return toast('需连接后端查看文档详情')
    setDetailDoc(d)
    setSnapshot({ state: 'loading', md: '', path: '', exists: false })
    try {
      const r = await governanceApi.snapshot(Number(d.id))
      setSnapshot({ state: 'ok', md: r.markdown || '', path: r.snapshot_path || '', exists: !!r.snapshot_exists })
    } catch (e) {
      setSnapshot({ state: 'error', md: '', path: '', exists: false })
      toast(`读取快照失败：${e.message}`)
    }
  }

  /* 导出统一快照（md/txt/pdf）。pdf 依赖缺失后端会降级为 md，这里据响应头明确提示。 */
  const exportDoc = async (d, fmt) => {
    if (!backendOk) return toast('需连接后端导出文档')
    try {
      const resp = await fetch(fileUrl(`/documents/${Number(d.id)}/export`, { fmt }))
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const degraded = resp.headers.get('X-Export-Degraded') === '1'
      if (degraded) toast('PDF 渲染依赖缺失，已降级导出 Markdown（内容一致）')
      const blob = await resp.blob()
      // 从 Content-Disposition 里取回后端给的文件名（中文按 RFC 5987 编码）
      const cd = resp.headers.get('content-disposition') || ''
      const m = /filename\*=UTF-8''([^;]+)/i.exec(cd)
      const fname = m ? decodeURIComponent(m[1]) : `${(d.filename || 'document').replace(/\.[^.]+$/, '')}.${fmt}`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = fname
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 4000)
      if (!degraded) toast(`已导出 ${fname}`)
    } catch (e) {
      toast(`导出失败：${e.message}`)
    }
  }

  /* 归档源文件到 knowledge_base/_archive/（默认归档而非删除） */
  const archiveDoc = async (d) => {
    if (!backendOk) return toast('需连接后端归档')
    if (!confirm(`把《${d.filename}》的源文件归档到 knowledge_base/_archive/？（不会删除数据）`)) return
    try {
      const r = await governanceApi.archive(Number(d.id))
      toast(r.message || (r.archived ? '已归档' : '未归档'))
      await refresh()
    } catch (e) {
      toast(`归档失败：${e.message}`)
    }
  }

  /* 单篇改科目（内联入口） */
  const changeDocSubject = async (d) => {
    if (!backendOk) return toast('需连接后端')
    const s = window.prompt(`把《${d.filename}》改到哪个科目？（填科目名）`, d.subject || '')
    if (!s || !s.trim()) return
    try {
      const r = await governanceApi.bulk({ action: 'set_subject', doc_ids: [Number(d.id)], subject: s.trim() })
      toast(r.message || '科目已更新')
      await refresh()
      refreshSubjects()
    } catch (e) {
      toast(`改科目失败：${e.message}`)
    }
  }

  /* 批量操作：archive / mark_delete / set_subject / purge（purge 走 delete_guard 闸门） */
  const bulkAction = async (action) => {
    if (!backendOk) return toast('需连接后端执行批量操作')
    const ids = selectedDocs.map((d) => Number(d.id))
    if (!ids.length) return toast('请先勾选文档')
    let body = { action, doc_ids: ids }
    if (action === 'set_subject') {
      const subj = window.prompt(`把选中的 ${ids.length} 篇文档改到哪个科目？（填科目名）`, selectedDocs[0]?.subject || '')
      if (!subj || !subj.trim()) return
      body.subject = subj.trim()
    }
    if (action === 'mark_delete' && !confirm(`标记删除 ${ids.length} 篇文档的源文件（移动到 _trash/，记录保留）？`)) return
    if (action === 'purge' && !confirm(`物理删除 ${ids.length} 篇文档及其分块/知识点？此操作不可逆，需已开启物理删除开关。`)) return
    if (action === 'archive' && !confirm(`归档 ${ids.length} 篇文档的源文件到 _archive/？（不会删除数据）`)) return
    setBulkBusy(true)
    try {
      const r = await governanceApi.bulk(body)
      toast(r.message || '批量操作完成')
      if (action !== 'set_subject') clearSelection()
      await refresh()
      refreshSubjects()
    } catch (e) {
      toast(`批量操作失败：${e.message}`)
    } finally {
      setBulkBusy(false)
    }
  }

  /* 扫描 knowledge_base 根目录 → 按科目归档（dryRun 预览） */
  const runScanRoot = async (dryRun) => {
    if (!backendOk) return toast('需连接后端扫描')
    if (!dryRun && !confirm('扫描 knowledge_base 根目录并按科目归档？文件会被移动到 {科目}/ 目录，DB 路径同步更新（断链记录只统计不动）。')) return
    setScanningRoot(true)
    try {
      const r = await governanceApi.scanRoot(dryRun)
      const msg = r.message || `移动 ${r.moved}，跳过 ${r.skipped}，断链 ${r.broken}，失败 ${r.errors}`
      toast(msg)
      if (!dryRun) { await refresh(); refreshSubjects() }
    } catch (e) {
      toast(`扫描失败：${e.message}`)
    } finally {
      setScanningRoot(false)
    }
  }

  /* ---------------- V3 治理：内联科目维护（走科目 API，不硬编码） ---------------- */
  const loadSubjects = useCallback(async () => {
    setSubjBusy(true)
    try {
      const d = await taxonomyApi.subjects()
      const list = Array.isArray(d) ? d : (d?.subjects || d?.items || [])
      setSubjList(Array.isArray(list) ? list : [])
    } catch (e) {
      toast(`加载科目失败：${e.message}`)
    } finally {
      setSubjBusy(false)
    }
  }, [])

  const openSubjectMgr = () => { setSubjMgrOpen(true); loadSubjects() }

  const submitSubjectForm = async () => {
    const name = (subjEditor.name || '').trim()
    if (!name) return toast('请填写科目名称')
    setSubjBusy(true)
    try {
      if (subjEditor.mode === 'create') {
        await taxonomyApi.createSubject({ subject: name })
        toast('科目已添加')
      } else {
        await taxonomyApi.updateSubject(subjEditor.original, { subject: name })
        toast('科目已更新')
      }
      setSubjEditor({ open: false, mode: 'create', original: '', name: '' })
      await loadSubjects()
      refreshSubjects()
    } catch (e) {
      toast(`保存失败：${e.message}`)
    } finally {
      setSubjBusy(false)
    }
  }

  const removeSubject = async (item) => {
    const n = item?.question_count || 0
    const tip = n > 0
      ? `科目「${item.subject}」下已有 ${n} 道题目，删除后这些题目将失去科目归属，确定删除吗？`
      : `确定删除科目「${item.subject}」吗？`
    if (!window.confirm(tip)) return
    try {
      await taxonomyApi.removeSubject(item.subject)
      toast('科目已删除')
      await loadSubjects()
      refreshSubjects()
    } catch (e) {
      toast(`删除失败：${e.message}`)
    }
  }

  const [previewDoc, setPreviewDoc] = useState(null)
  const [previewContent, setPreviewContent] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  /* #26 原文件（字节流）预览：与"解析文本"预览是两码事，前者是磁盘上的那份 PDF */
  const [fileDoc, setFileDoc] = useState(null)
  const handleShowPreview = async (d) => {
    if (!backendOk) return toast('需连接后端预览文档')
    setPreviewDoc(d); setPreviewLoading(true); setPreviewContent('')
    try { const r = await documentsApi.getContent(Number(d.id), 8000); setPreviewContent(r.content || '') }
    catch (e) { toast(`预览失败：${e.message}`) }
    setPreviewLoading(false)
  }

  /* ---------------- 新增② 知识点图谱：科目分面 + 标签云 ---------------- */
  const kpSubjects = useMemo(() => {
    const map = new Map()
    kpList.forEach((k) => {
      const s = k.subject || kpDoc?.subject || '未分类'
      map.set(s, (map.get(s) || 0) + 1)
    })
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count)
  }, [kpList, kpDoc])

  const kpFiltered = useMemo(() => {
    if (kpSubject === 'all') return kpList
    return kpList.filter((k) => (k.subject || kpDoc?.subject || '未分类') === kpSubject)
  }, [kpList, kpSubject, kpDoc])

  const kpFreqLevel = (k) => {
    const f = k.exam_frequency
    if (f == null || f === '') return 0
    if (typeof f === 'number') return f >= 5 ? 2 : f >= 2 ? 1 : 0
    const s = String(f)
    if (/高|frequent|high/i.test(s)) return 2
    if (/中|medium/i.test(s)) return 1
    const n = parseInt(s, 10)
    if (!Number.isNaN(n)) return n >= 5 ? 2 : n >= 2 ? 1 : 0
    return 0
  }

  const kpName = (k) => k.name || k.point || k.title || '未命名知识点'

  const kpToCard = (k) => {
    const front = kpName(k)
    const back = (k.description || k.summary || '').trim() || '（该知识点暂无描述，请补充）'
    addCard({ front, back })
    toast(`已把「${front.slice(0, 14)}」加入记忆卡片`)
  }

  return (
    <div>
      <style>{`
        .doc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
        /* V3 治理：批量操作栏 / 选择框 / 详情抽屉 / 内联科目维护 */
        .doc-bulkbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 10px 14px; margin-bottom: 14px; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-md); }
        .doc-check-inline { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--ink-2); cursor: pointer; }
        .doc-check { width: 16px; height: 16px; cursor: pointer; accent-color: var(--accent); flex: none; }
        .doc-card-checked { border-color: var(--accent) !important; box-shadow: 0 0 0 1px var(--accent) inset; }
        .doc-detail { display: flex; flex-direction: column; gap: 10px; }
        .doc-detail-meta { display: flex; flex-wrap: wrap; gap: 6px; }
        .doc-detail-mdhead { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap; font-size: 12.5px; font-weight: 700; color: var(--ink-2); }
        .doc-detail-path { font-weight: 400; color: var(--ink-3); font-size: 11.5px; max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .doc-subjmgr { max-height: 52vh; overflow-y: auto; }
        .kp-cloud { display: flex; flex-wrap: wrap; gap: 8px; }
        .kp-chip-lg { font-size: 13px; padding: 7px 13px; }
        .doc-pre { font-size: 12.8px; line-height: 1.9; white-space: pre-wrap; word-break: break-word; color: var(--ink); background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-md); padding: 12px; max-height: 46vh; overflow-y: auto; }
        /* #26 原文件字节流预览：PDF/图片交给浏览器渲染，后端已支持 Range，翻页不会整读 908MB */
        .file-frame { display: block; width: 100%; height: 68vh; border: 1px solid var(--line); border-radius: var(--r-md); background: #fff; }
        /* V8 阶段3：kb-import 识别预览（新增 class，颜色全部走 var(--*)） */
        .kbimp-sum { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .kbimp-sum .ks-cell { background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 10px 12px; }
        .kbimp-sum .ks-num { font-size: 22px; font-weight: 800; color: var(--ink); font-family: var(--font-sans); line-height: 1.1; }
        .kbimp-sum .ks-of { font-size: 13px; font-weight: 600; color: var(--ink-3); }
        .kbimp-sum .ks-lab { font-size: 11.5px; color: var(--ink-3); margin-top: 3px; }
        .kbimp-subj { display: flex; flex-wrap: wrap; gap: 6px; }
        .kbimp-list { display: flex; flex-direction: column; gap: 10px; }
        .kbimp-doc { border: 1px solid var(--line); border-radius: var(--r-sm); overflow: hidden; }
        .kbimp-doc-head { display: flex; align-items: center; gap: 8px; padding: 9px 12px; background: var(--surface-2); }
        .kbimp-doc-title { flex: 1; min-width: 0; font-size: 13px; font-weight: 700; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .kbimp-qrow { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border-top: 1px solid var(--line); }
        .kbimp-qrow.existing { background: var(--surface-2); opacity: 0.72; }
        .kbimp-check { position: relative; flex: none; width: 18px; height: 18px; margin-top: 2px; }
        .kbimp-check input { position: absolute; inset: 0; opacity: 0; margin: 0; cursor: pointer; }
        .kbimp-check .box { width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid var(--line-strong); background: var(--surface); display: grid; place-items: center; color: #fff; font-size: 12px; line-height: 1; transition: background var(--dur-fast), border-color var(--dur-fast); }
        .kbimp-check input:checked + .box { background: var(--accent); border-color: var(--accent); }
        .kbimp-check input:checked + .box::after { content: '✓'; }
        .kbimp-check input:disabled + .box { background: var(--surface-2); border-color: var(--line); cursor: not-allowed; }
        .kbimp-qmain { flex: 1; min-width: 0; }
        .kbimp-stem { font-size: 12.8px; line-height: 1.7; color: var(--ink); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
        .kbimp-qmeta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
        .kbimp-more { width: 100%; padding: 8px; border: none; border-top: 1px solid var(--line); background: var(--surface-2); color: var(--accent); font-size: 12px; font-weight: 600; cursor: pointer; }
        .kbimp-err { background: var(--red-soft); border: 1px solid rgba(224, 82, 74, 0.25); color: var(--red); border-radius: var(--r-sm); padding: 14px; display: flex; flex-direction: column; gap: 8px; }
        .kbimp-err-title { font-size: 13.5px; font-weight: 700; }
        .kbimp-err-msg { font-size: 12.5px; line-height: 1.6; }
        .kbimp-result { display: flex; flex-direction: column; gap: 14px; }
        .kbimp-note { font-size: 12.5px; color: var(--ink-3); line-height: 1.7; margin: 0; }
      `}</style>

      <div className="page-head">
        <div>
          <h1 className="page-title">文档知识库</h1>
          <p className="page-sub">上传讲义 / 真题 / 笔记 · AI 自动解析提取知识点与分块</p>
        </div>
        <div className="page-actions">
          {backendOk ? <span className="badge success">后端已连接</span> : <span className="badge warning">后端离线</span>}
          <span className="badge info">{overview.total} 篇 · {overview.chunks} 分块</span>
          <button className="btn ghost" onClick={parseAll} disabled={!backendOk || !overview.pending}>批量解析未入库</button>
          <button className="btn ghost" onClick={() => runScanRoot(false)} disabled={!backendOk || scanningRoot}
            title="扫描 knowledge_base 根目录，按科目归档到 {科目}/ 并同步 DB 路径（断链只统计）">
            {scanningRoot ? '扫描中…' : '🗂 扫描归档根目录'}
          </button>
          <button className="btn ghost" onClick={openSubjectMgr} disabled={!backendOk} title="内联维护科目（增删改）">
            科目维护
          </button>
          <button className="btn outline" onClick={() => openKbImport(null)} disabled={!backendOk} title="扫描全部文档识别题目（约5分钟，建议分批）">
            🔍 全库识别
          </button>
          <button className="btn primary" disabled={uploading} onClick={() => fileRef.current?.click()}>
            {uploading ? '上传中…' : '↑ 批量上传'}
          </button>
          <input ref={fileRef} type="file" multiple accept={ACCEPT} style={{ display: 'none' }}
            onChange={(e) => { const fs = e.target.files; if (fs && fs.length > 1) enqueue(fs); else upload(fs && fs[0]) }} />
        </div>
      </div>

      {/* 知识库健康：缺口体检 + 一键修复 */}
      <KbHealthPanel />

      {/* 总览 stat-tile */}
      <div className="grid-4" style={{ marginBottom: 14 }}>
        <div className="stat-tile">
          <div className="st-ico ico blue">📚</div>
          <div className="st-val"><CountUp value={overview.total} /></div>
          <div className="st-label">文档总数</div>
        </div>
        <div className="stat-tile">
          <div className="st-ico ico green">✓</div>
          <div className="st-val"><CountUp value={overview.parsed} /></div>
          <div className="st-label">已解析入库</div>
          {overview.pending > 0 && <div className="st-delta down">{overview.pending} 篇待解析</div>}
        </div>
        <div className="stat-tile">
          <div className="st-ico ico violet">≡</div>
          <div className="st-val"><CountUp value={overview.chunks} /></div>
          <div className="st-label">知识分块</div>
        </div>
        <div className="stat-tile">
          <div className="st-ico ico amber">字</div>
          <div className="st-val">{(overview.chars / 10000).toFixed(1)}<span style={{ fontSize: 14, fontWeight: 700 }}> 万</span></div>
          <div className="st-label">入库总字数</div>
        </div>
      </div>

      {/* 科目统计 stat-tile（后端 /documents/subjects） */}
      {subjectStats && (subjectStats.subjects || []).length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-head">
            <div className="card-title">科目分布</div>
            <span className="badge">共 {subjectStats.total_documents} 篇 · {subjectStats.total_chunks} 分块</span>
          </div>
          <div className="card-body">
            <div className="grid-4">
              {(subjectStats.subjects || []).map((s) => (
                <div key={s.name} className="stat-tile" style={{ cursor: 'pointer', borderColor: subject === s.name ? 'var(--accent)' : undefined }}
                  onClick={() => setSubject(subject === s.name ? 'all' : s.name)}>
                  <div className="row spread">
                    <div className="st-ico ico sm neutral">科</div>
                    {subject === s.name && <span className="badge accent">筛选中</span>}
                  </div>
                  <div className="st-val" style={{ fontSize: 22 }}>{s.merged_document_count ?? s.document_count}</div>
                  <div className="st-label">
                    {s.name}{s.chunk_count != null ? ` · ${s.chunk_count} 分块` : ''}
                    {(s.aliases || []).length > 0 && `（含 ${s.aliases.join('、')}）`}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 视图切换 + 筛选 */}
      <div className="toolbar" style={{ marginBottom: 14 }}>
        <div className="left">
          <div className="segmented">
            {VIEWS.map((v) => (
              <button key={v.value} className={`seg ${view === v.value ? 'active' : ''}`} onClick={() => setView(v.value)}>{v.label}</button>
            ))}
          </div>
          {view === 'list' && (
            <button className="btn outline sm" disabled={!backendOk || filtered.length === 0}
              onClick={() => openKbImport(filtered.map((d) => Number(d.id)))}
              title="仅扫描当前筛选出的文档（秒级），识别候选题">
              🔍 识别当前列表（{filtered.length}）
            </button>
          )}
        </div>
        <div className="right">
          {view !== 'search' && (
            <select className="select" style={{ width: 180 }} value={subject} onChange={(e) => setSubject(e.target.value)}>
              <option value="all">全部科目</option>
              {subjectOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
          {view !== 'search' && <input className="input search" style={{ width: 220 }} placeholder="搜索文档 / 摘要" value={q} onChange={(e) => setQ(e.target.value)} />}
        </div>
      </div>

      {/* ============ 新增① 批量上传 dropzone + 去重队列 ============ */}
      {view === 'list' && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-head">
            <div className="card-title">批量上传</div>
            <div className="row" style={{ gap: 8 }}>
              {queueStat.dup > 0 && <span className="badge warning">{queueStat.dup} 个重复</span>}
              {queueStat.pending > 0 && <span className="badge info">{queueStat.pending} 个待上传</span>}
              {queue.length > 0 && <button className="btn ghost" onClick={() => setShowQueue((v) => !v)}>{showQueue ? '收起队列' : `查看队列(${queue.length})`}</button>}
            </div>
          </div>
          <div className="card-body">
            <div
              className={`dropzone ${dragging ? 'drag' : ''}`}
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <div style={{ fontSize: 26, marginBottom: 6 }}>⇪</div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--ink-2)' }}>把 PDF / Word / TXT / Markdown 拖到这里，或点击选择（支持多选）</div>
              <div style={{ fontSize: 12, marginTop: 6 }}>上传前自动按「文件名 + 字节数」比对去重，重复文件默认跳过</div>
            </div>

            {showQueue && queue.length > 0 && (
              <>
                <div className="hr" />
                <div className="toolbar" style={{ marginBottom: 10 }}>
                  <div className="left">
                    <span className="badge">待上传 {queueStat.pending}</span>
                    <span className="badge warning">重复 {queueStat.dup}</span>
                    <span className="badge success">完成 {queueStat.done}</span>
                    {queueStat.error > 0 && <span className="badge danger">失败 {queueStat.error}</span>}
                  </div>
                  <div className="right">
                    <button className="btn ghost" onClick={() => setQueue([])} disabled={uploading}>清空队列</button>
                    {queueStat.dup > 0 && <button className="btn ghost" onClick={() => runQueue(true)} disabled={uploading}>连重复一起上传</button>}
                    <button className="btn primary" onClick={() => runQueue(false)} disabled={uploading || !queueStat.pending}>{uploading ? '上传中…' : '开始上传'}</button>
                  </div>
                </div>
                {(queueStat.done + queueStat.error) > 0 && (
                  <div className="progress thin" style={{ marginBottom: 10 }}>
                    <i style={{ width: `${Math.round(((queueStat.done + queueStat.error) / queue.length) * 100)}%` }} />
                  </div>
                )}
                <div className="list">
                  {queue.map((it) => (
                    <div key={it.key} className="list-row">
                      <div className="lr-ico ico sm neutral">{(it.name.split('.').pop() || '?').slice(0, 3).toUpperCase()}</div>
                      <div className="lr-main">
                        <div className="lr-title">{it.name}</div>
                        <div className="lr-meta">{fmtBytes(it.size)}{it.msg ? ` · ${it.msg}` : ''}</div>
                      </div>
                      <div className="lr-actions">
                        {it.status === 'pending' && <span className="badge">待上传</span>}
                        {it.status === 'uploading' && <span className="badge info">上传中</span>}
                        {it.status === 'done' && <span className="badge success">已上传</span>}
                        {it.status === 'dup' && <span className="badge warning">重复跳过</span>}
                        {it.status === 'error' && <span className="badge danger">失败</span>}
                        <button className="btn ghost" disabled={uploading} onClick={() => setQueue((x) => x.filter((o) => o.key !== it.key))}>移除</button>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ============ 知识库检索 ============ */}
      {view === 'search' && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">知识库检索（RAG）</div>
            <span className="badge info">FTS5 + 向量混合检索</span>
          </div>
          <div className="card-body">
            <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
              <input className="input search" style={{ flex: 1, minWidth: 260 }} placeholder="输入问题，如：什么是香农公式 / MOSFET 工作原理" value={ragQ}
                onChange={(e) => setRagQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && doRagSearch()} />
              <select className="select" style={{ width: 170 }} value={ragSubject} onChange={(e) => setRagSubject(e.target.value)}>
                <option value="">全部学科</option>
                {subjectOptions.map((o) => <option key={o.value} value={o.value}>{o.value}</option>)}
              </select>
              <button className="btn primary" onClick={doRagSearch} disabled={ragLoading}>{ragLoading ? '检索中…' : '检索知识库'}</button>
            </div>
            <p style={{ fontSize: 12, color: 'var(--ink-3)', margin: '10px 0 0' }}>命中结果会作为 AI 回答依据，并在「AI 助手」中标注引用来源。</p>
            <div className="hr" />
            {ragLoading ? (
              <div className="loading-inline"><i />正在检索知识分块…</div>
            ) : ragHits.length === 0 ? (
              <div className="empty">
                <div className="e-ico">⌕</div>
                <div className="e-title">知识库检索</div>
                <div className="e-text">输入问题后回车，从已入库的分块中检索相关知识</div>
              </div>
            ) : (
              <div className="stack" style={{ gap: 10 }}>
                {ragHits.map((h, i) => (
                  <div key={i} className="card" style={{ boxShadow: 'none' }}>
                    <div className="card-head" style={{ padding: '12px 14px' }}>
                      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                        <span className="badge accent">#{i + 1}</span>
                        <b style={{ fontSize: 13.5 }}>{h.title || '未命名片段'}</b>
                      </div>
                      <div className="row" style={{ gap: 6 }}>
                        {h.score != null && <span className="badge success">相关度 {Number(h.score).toFixed(2)}</span>}
                        <span className="badge">{h.source || '知识分块'} · {h.subject || '未分类'}</span>
                      </div>
                    </div>
                    <div className="card-body" style={{ paddingTop: 0 }}>
                      <div style={{ fontSize: 12.8, lineHeight: 1.9, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>{h.content || h.text || ''}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ============ 文档列表 ============ */}
      {view === 'list' && (
        <>
          {loading && docs.length === 0 ? (
            <div className="card"><div className="card-body"><LoadingState text="正在加载文档…" rows={4} /></div></div>
          ) : loadErr ? (
            <div className="card"><div className="card-body">
              <ErrorState message={loadErr} onRetry={refresh} />
            </div></div>
          ) : (
            <>
              {/* 批量操作栏：勾选后批量归档 / 标记删除 / 改科目（物理删除走闸门） */}
              <div className="doc-bulkbar">
                <label className="doc-check-inline">
                  <input type="checkbox"
                    checked={filtered.length > 0 && filtered.every((d) => selected.has(d.id))}
                    onChange={(e) => toggleAllVisible(filtered, e.target.checked)} />
                  <span>全选当前 {filtered.length} 篇</span>
                </label>
                {selected.size > 0 && (
                  <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                    <span className="badge accent">已选 {selected.size}</span>
                    <button className="btn ghost sm" disabled={bulkBusy} onClick={() => bulkAction('archive')}>归档源文件</button>
                    <button className="btn ghost sm" disabled={bulkBusy} onClick={() => bulkAction('set_subject')}>批量改科目</button>
                    <button className="btn ghost sm" disabled={bulkBusy} onClick={() => bulkAction('mark_delete')}>标记删除</button>
                    <button className="btn danger sm" disabled={bulkBusy} title="物理删除需开启 KAOYAN_ALLOW_PHYSICAL_DELETE=1"
                      onClick={() => bulkAction('purge')}>物理删除</button>
                    <button className="btn ghost sm" disabled={bulkBusy} onClick={clearSelection}>清除选择</button>
                  </div>
                )}
                <div className="row" style={{ gap: 8, marginLeft: 'auto' }}>
                  <span className="badge warning">{docs.filter(isEmptyBody).length} 篇正文缺失</span>
                  <button className="btn ghost sm" disabled={scanningRoot} onClick={() => runScanRoot(true)}>预览扫描归档</button>
                </div>
              </div>

              {filtered.length === 0 ? (
                <div className="card"><div className="card-body">
                  <EmptyState
                    icon="📁"
                    title={docs.length ? '没有匹配的文档' : '知识库还是空的'}
                    desc={docs.length ? '换个关键词或清除科目筛选试试' : '上传一份讲义或真题，让 AI 帮你解析知识点'}
                    action={(
                      <>
                        <button className="btn primary" onClick={() => fileRef.current?.click()}>↑ 选择文件上传</button>
                        {docs.length > 0 && <button className="btn ghost" onClick={() => { setQ(''); setSubject('all') }}>清除筛选</button>}
                      </>
                    )}
                  />
                </div></div>
              ) : (
                <div className="doc-grid">
                  {filtered.map((d) => {
                    const t = TYPE_ICO[(d.doc_type || 'txt').toLowerCase()] || TYPE_ICO.txt
                    const empty = isEmptyBody(d)
                    const checked = selected.has(d.id)
                    return (
                      <div key={d.id} className={`card ${checked ? 'doc-card-checked' : ''}`}>
                        <div className="card-head">
                          <div className="row" style={{ gap: 10, minWidth: 0 }}>
                            <input type="checkbox" className="doc-check" checked={checked}
                              onChange={() => toggleSelect(d.id)} title="选择该文档" />
                            <div className={`ico sm ${t.cls}`} style={{ fontSize: 11, fontWeight: 800 }}>{t.text}</div>
                            <div style={{ minWidth: 0 }}>
                              <div className="card-title" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 190 }} title={d.filename}>{d.filename}</div>
                              <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 2 }}>{fmtDateCN(d.uploaded_at)} · {fmtBytes(d.size)}</div>
                            </div>
                          </div>
                          {empty ? <span className="badge danger" title="正文缺失：documents.content 为空，建议重新解析">正文缺失</span>
                            : d.status === 'parsed' ? <span className="badge success">已入库</span>
                              : d.status === 'failed' ? <span className="badge danger">入库失败</span>
                                : <span className="badge warning">未解析</span>}
                        </div>
                        <div className="card-body">
                          <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                            <SubTag subject={d.subject} />
                            <span className={`badge ${empty ? 'danger' : ''}`}>{empty ? '待重新解析' : `${(d.content_length || 0).toLocaleString()} 字`}</span>
                            {d.chunk_count > 0 ? <span className="badge info">{d.chunk_count} 分块</span> : <span className="badge">无分块</span>}
                          </div>
                          {d.summary
                            ? <p style={{ fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.8, margin: 0 }}>{d.summary}</p>
                            : <p style={{ fontSize: 12.5, color: 'var(--ink-3)', margin: 0 }}>暂无摘要，解析后自动生成</p>}
                        </div>
                        <div className="card-foot" style={{ flexWrap: 'wrap', gap: 8 }}>
                          <button className="btn ghost" onClick={() => openDetail(d)}>详情</button>
                          {empty && (
                            <button className="btn primary" disabled={parsingId === d.id} onClick={() => parse(d.id)}>
                              {parsingId === d.id ? '解析中…' : '重新解析'}
                            </button>
                          )}
                          {d.status === 'parsed' && !empty ? (
                            <>
                              <button className="btn ghost" onClick={() => showKnowledge(d)}>知识点</button>
                              {d.chunk_count > 0 && <button className="btn ghost" onClick={() => showChunks(d)}>≡ 分块</button>}
                              <button className="btn ghost" onClick={() => handleShowPreview(d)}>原文</button>
                              {/* #26：本地原文预览/下载。754 篇本地没有原文（439 未登记路径 + 238 IMA 媒体号 + 77 已失效），
                                  按钮按 has_local_file 置灰并把原因写在 title，而不是点了才报错 */}
                              <button className="btn ghost" disabled={!d.has_local_file}
                                title={d.has_local_file ? '在浏览器里打开原文件' : (d.local_file_note || '本地没有原文件')}
                                onClick={() => setFileDoc(d)}>📄 原文件</button>
                              <button className="btn ghost" disabled={analyzingId === d.id} onClick={() => analyze(d)}>{analyzingId === d.id ? '分析中…' : '✨ 智能分析'}</button>
                              <button className="btn ghost" disabled={previewingId === d.id} onClick={() => handlePreviewQuestions(d)}>{previewingId === d.id ? '预览中…' : '👁 预览题目'}</button>
                              <button className="btn ghost" onClick={() => openKbImport([Number(d.id)])}>🔍 识别</button>
                              <button className="btn ghost" onClick={() => generateQuiz(d)}>出题</button>
                            </>
                          ) : (d.status !== 'parsed' && !empty) ? (
                            <button className="btn primary" disabled={parsingId === d.id} onClick={() => parse(d.id)}>{parsingId === d.id ? '解析中…' : '开始解析'}</button>
                          ) : null}
                          <button className="btn ghost" onClick={() => changeDocSubject(d)} title="把该文档改到其他科目">改科目</button>
                          <button className="btn ghost" disabled={!d.has_local_file} onClick={() => archiveDoc(d)} title={d.has_local_file ? '归档源文件到 _archive/' : '本地无原文，无法归档'}>归档</button>
                          <button className="btn danger" onClick={() => remove(d.id)}>删除</button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* ============ 知识点图谱 / 分块 ============ */}
      {view === 'knowledge' && (
        kpDoc === null && chunkDoc === null ? (
          <div className="card"><div className="card-body">
            <div className="empty">
              <div className="e-ico">🧠</div>
              <div className="e-title">知识点图谱</div>
              <div className="e-text">先在「文档列表」里点某份文档的「知识点」或「分块」，这里会展示标签云与详情</div>
              <div className="e-actions"><button className="btn primary" onClick={() => setView('list')}>去选择文档</button></div>
            </div>
          </div></div>
        ) : (
          <div className="stack">
            <div className="card">
              <div className="card-head">
                <div className="card-title">《{(kpDoc || chunkDoc).filename}》· {chunkDoc ? '知识分块' : '知识点图谱'}</div>
                <div className="row" style={{ gap: 8 }}>
                  {!chunkDoc && <span className="badge info">{kpList.length} 个知识点</span>}
                  {chunkDoc && <span className="badge info">{chunkList.length} 个分块</span>}
                  <button className="btn ghost" onClick={() => { setKpDoc(null); setChunkDoc(null); setActiveKp(null); setView('list') }}>← 返回列表</button>
                </div>
              </div>

              {/* 新增② 标签云筛选 */}
              {!chunkDoc && kpList.length > 0 && (
                <div className="card-body">
                  <div className="sec-title" style={{ margin: '0 0 10px' }}>
                    <h3 style={{ fontSize: 13.5 }}>按科目筛选</h3>
                    <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>点击标签查看知识点详情，高频考点用蓝色高亮</span>
                  </div>
                  <div className="kp-cloud" style={{ marginBottom: 12 }}>
                    <button className={`chip ${kpSubject === 'all' ? 'active' : ''}`} onClick={() => { setKpSubject('all'); setActiveKp(null) }}>全部 {kpList.length}</button>
                    {kpSubjects.map((s) => (
                      <button key={s.name} className={`chip ${kpSubject === s.name ? 'active' : ''}`} onClick={() => { setKpSubject(s.name); setActiveKp(null) }}>{s.name} {s.count}</button>
                    ))}
                  </div>
                  <div className="hr" />
                  <div className="kp-cloud">
                    {kpFiltered.map((k, i) => {
                      const lvl = kpFreqLevel(k)
                      const on = activeKp && kpName(activeKp) === kpName(k)
                      return (
                        <button
                          key={`${kpName(k)}-${i}`}
                          className={`chip kp-chip-lg ${on || lvl === 2 ? 'active' : ''}`}
                          style={lvl === 2 ? { fontWeight: 800 } : lvl === 1 ? { fontWeight: 700 } : undefined}
                          onClick={() => setActiveKp(on ? null : k)}
                          title={k.description || ''}
                        >
                          {kpName(k)}{lvl === 2 ? ' ★' : lvl === 1 ? ' ·' : ''}
                        </button>
                      )
                    })}
                  </div>
                  {kpFiltered.length === 0 && (
                    <div className="empty">
                      <div className="e-ico">📄</div>
                      <div className="e-title">该科目下暂无知识点</div>
                      <div className="e-text">换个科目标签，或对文档执行「智能分析」重新提取</div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 选中知识点详情 */}
            {!chunkDoc && activeKp && (
              <div className="card">
                <div className="card-head">
                  <div className="card-title">{kpName(activeKp)}</div>
                  <div className="row" style={{ gap: 8 }}>
                    <SubTag subject={activeKp.subject || kpDoc?.subject} />
                    {activeKp.exam_frequency ? <span className="badge warning">出题频率 {String(activeKp.exam_frequency)}</span> : null}
                  </div>
                </div>
                <div className="card-body">
                  <div style={{ fontSize: 13, lineHeight: 1.9, color: 'var(--ink)', whiteSpace: 'pre-wrap' }}>
                    {activeKp.description || activeKp.summary || '（该知识点暂无描述，可对文档执行「智能分析」补全）'}
                  </div>
                </div>
                <div className="card-foot">
                  <button className="btn ghost" onClick={() => setActiveKp(null)}>收起</button>
                  <button className="btn primary" onClick={() => kpToCard(activeKp)}>加入记忆卡片</button>
                </div>
              </div>
            )}

            {/* 分块列表 */}
            {chunkDoc && (
              <div className="card">
                <div className="card-head"><div className="card-title">分块内容</div></div>
                <div className="card-body">
                  {chunkList.length === 0 ? (
                    <div className="empty">
                      <div className="e-ico">≡</div>
                      <div className="e-title">该文档暂无分块</div>
                      <div className="e-text">可能为扫描件或正文过短，可尝试重新解析</div>
                    </div>
                  ) : (
                    <div className="stack" style={{ gap: 10 }}>
                      {chunkList.map((c, i) => (
                        <div key={i} className="list-row" style={{ alignItems: 'flex-start' }}>
                          <div className="lr-ico ico sm neutral">{i + 1}</div>
                          <div className="lr-main">
                            <div className="lr-meta" style={{ marginBottom: 4 }}>#{c.chunk_id || c.id || i + 1} · {(c.text || c.content || '').length} 字</div>
                            <div style={{ fontSize: 12.8, lineHeight: 1.9, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>{c.text || c.content || ''}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      )}

      {/* 原文预览 Modal */}
      <Modal
        open={!!previewDoc}
        title={previewDoc ? `原文预览 · ${previewDoc.filename}` : ''}
        onClose={() => { setPreviewDoc(null); setPreviewContent('') }}
        footer={<button className="btn primary" onClick={() => { setPreviewDoc(null); setPreviewContent('') }}>关闭</button>}
      >
        {previewLoading
          ? <div className="loading-inline"><i />正在读取正文…</div>
          : <div className="doc-pre">{previewContent || '（未取到正文内容，可能尚未解析）'}</div>}
      </Modal>

      {/* 原文件（磁盘上那份）预览 Modal：字节流走 /documents/{id}/raw，后端支持 Range */}
      <Modal
        open={!!fileDoc}
        title={fileDoc ? `原文件 · ${fileDoc.file_name}` : ''}
        onClose={() => setFileDoc(null)}
        footer={(
          <div style={{ display: 'flex', gap: 8 }}>
            {fileDoc && canInlinePreview(fileDoc) && (
              <a className="btn ghost" href={documentsApi.rawUrl(fileDoc.id)} target="_blank" rel="noreferrer">新窗口打开</a>
            )}
            {/* footer 这一整块 JSX 在**每次渲染**时都会求值（Modal 的 open 只影响
                是否挂载内容，不影响 props 的构造），所以这里每一次 `fileDoc.xxx`
                都必须带判空 —— 漏一个就是整页白屏（fileDoc 初始就是 null）。 */}
            {fileDoc && (
              <a className="btn primary" href={documentsApi.downloadUrl(fileDoc.id)} download>下载原文件</a>
            )}
            <button className="btn ghost" onClick={() => setFileDoc(null)}>关闭</button>
          </div>
        )}
      >
        {fileDoc && (canInlinePreview(fileDoc)
          ? <iframe className="file-frame" title="原文件预览" src={documentsApi.rawUrl(fileDoc.id)} />
          : <div className="doc-pre">
            {`该文件的类型（${fileDoc.file_type || '未知'}）浏览器不能直接渲染，请点下方「下载原文件」后用本地应用打开。`}
            {fileDoc.size ? `\n大小 ${(fileDoc.size / 1048576).toFixed(1)} MB` : ''}
          </div>)}
      </Modal>

      {/* 题目预览 / 人工审核 Modal */}
      <Modal
        open={showPreview}
        title={`题目预览与审核${previewOwner ? ` · ${previewOwner.filename}` : ''}`}
        onClose={() => { setShowPreview(false); setEditingQuestionIdx(null) }}
        footer={
          <>
            <button className="btn ghost" onClick={() => { setShowPreview(false); setEditingQuestionIdx(null) }}>取消</button>
            <button className="btn primary" onClick={() => confirmImportQuestions(previewOwner)} disabled={previewQuestions.length === 0}>
              确认入库（{previewQuestions.filter((x) => x.selected !== false).length}）
            </button>
          </>
        }
      >
        {previewQuestions.length === 0 ? (
          <div className="empty">
            <div className="e-ico">📝</div>
            <div className="e-title">未提取到题目</div>
            <div className="e-text">可先执行「智能分析」，或该文档不含可识别题目</div>
          </div>
        ) : (
          <div className="stack" style={{ gap: 10, maxHeight: '52vh', overflowY: 'auto' }}>
            {previewQuestions.map((qq, idx) => (
              <div key={idx} className="card" style={{ boxShadow: 'none' }}>
                <div className="card-head" style={{ padding: '10px 12px' }}>
                  <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                    <span className="badge accent">#{idx + 1}</span>
                    {qq.question_type && <span className="badge">{qq.question_type}</span>}
                    {qq.is_real && <span className="badge warning">真题</span>}
                    {qq.selected === false && <span className="badge danger">已取消选中</span>}
                  </div>
                  <div className="row" style={{ gap: 6 }}>
                    <button className="btn ghost" onClick={() => updatePreviewQuestion(idx, 'selected', qq.selected === false)}>
                      {qq.selected === false ? '选中' : '不入库'}
                    </button>
                    <button className="btn ghost" onClick={() => setEditingQuestionIdx(editingQuestionIdx === idx ? null : idx)}>
                      {editingQuestionIdx === idx ? '完成' : '编辑'}
                    </button>
                    <button className="btn danger" onClick={() => removePreviewQuestion(idx)}>移除</button>
                  </div>
                </div>
                <div className="card-body" style={{ paddingTop: 0 }}>
                  {editingQuestionIdx === idx ? (
                    <div className="stack" style={{ gap: 8 }}>
                      <div className="field">
                        <label>题干</label>
                        <textarea className="textarea" rows={3} value={qq.question || qq.content || ''} onChange={(e) => updatePreviewQuestion(idx, 'question', e.target.value)} />
                      </div>
                      {(qq.options || []).map((op, oi) => (
                        <div key={oi} className="field">
                          <label>选项 {String.fromCharCode(65 + oi)}</label>
                          <input className="input" value={op} onChange={(e) => updatePreviewOption(idx, oi, e.target.value)} />
                        </div>
                      ))}
                      <div className="grid-2">
                        <div className="field">
                          <label>答案</label>
                          <input className="input" value={qq.answer || ''} onChange={(e) => updatePreviewQuestion(idx, 'answer', e.target.value)} />
                        </div>
                        <div className="field">
                          <label>科目</label>
                          <input className="input" value={qq.subject || ''} onChange={(e) => updatePreviewQuestion(idx, 'subject', e.target.value)} />
                        </div>
                      </div>
                      <div className="field">
                        <label>解析</label>
                        <textarea className="textarea" rows={2} value={qq.analysis || ''} onChange={(e) => updatePreviewQuestion(idx, 'analysis', e.target.value)} />
                      </div>
                    </div>
                  ) : (
                    <>
                      <div style={{ fontSize: 13, lineHeight: 1.85, color: 'var(--ink)', whiteSpace: 'pre-wrap' }}>{qq.question || qq.content || '（无题干）'}</div>
                      {(qq.options || []).length > 0 && (
                        <div className="stack" style={{ gap: 4, marginTop: 8 }}>
                          {(qq.options || []).map((op, oi) => (
                            <div key={oi} style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>{String.fromCharCode(65 + oi)}. {op}</div>
                          ))}
                        </div>
                      )}
                      <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                        {qq.answer && <span className="badge success">答案 {qq.answer}</span>}
                        {qq.subject && <span className="badge">{qq.subject}</span>}
                      </div>
                      {qq.analysis && <p style={{ fontSize: 12.5, color: 'var(--ink-3)', lineHeight: 1.8, margin: '8px 0 0' }}>解析：{qq.analysis}</p>}
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* ============ V8 阶段3：知识库题目识别预览 / 确认入库 Modal ============ */}
      <Modal
        open={kbOpen}
        title={kbDone ? '入库完成' : `知识库题目识别预览 · ${kbScopeLabel}`}
        onClose={() => { setKbOpen(false); setKbDone(null) }}
        footer={
          kbDone ? (
            <button className="btn primary" onClick={() => { setKbOpen(false); setKbDone(null) }}>完成</button>
          ) : (
            <>
              <button className="btn ghost" onClick={() => { setKbOpen(false); setKbDone(null) }}>取消</button>
              <button className="btn primary" onClick={doKbConfirm} disabled={kbChecked.size === 0 || kbConfirming || kbLoading}>
                {kbConfirming ? '入库中…' : `确认入库（${kbChecked.size}）`}
              </button>
            </>
          )
        }
      >
        {kbLoading ? (
          <div className="loading-inline"><i />正在扫描知识库文档并识别候选题目…{kbDocIds ? '分批识别通常数秒内完成。' : '全库扫描逐篇打分，实测约 5 分钟，请耐心等待。'}</div>
        ) : kbDone ? (
          <div className="kbimp-result">
            <div className="kbimp-sum">
              <div className="ks-cell"><div className="ks-num">{kbDone.inserted}</div><div className="ks-lab">实际入库（题）</div></div>
              <div className="ks-cell"><div className="ks-num">{kbDone.skipped}</div><div className="ks-lab">跳过已存在（题）</div></div>
              <div className="ks-cell"><div className="ks-num">{kbDone.outOfRange || 0}</div><div className="ks-lab">下标越界（题）</div></div>
            </div>
            {Object.keys(kbDone.bySubject || {}).length > 0 && (
              <>
                <div className="sec-title"><h3>按科目分布</h3></div>
                <div className="kbimp-subj">
                  {Object.entries(kbDone.bySubject).map(([s, n]) => (
                    <span key={s} className="chip active">{s} · {n}</span>
                  ))}
                </div>
              </>
            )}
            <p className="kbimp-note">可在「刷题中心」查看新入库的题目，来源标记为「知识库:文档名」。</p>
          </div>
        ) : kbError ? (
          <div className="kbimp-err">
            <div className="kbimp-err-title">扫描失败</div>
            <div className="kbimp-err-msg">{kbError}</div>
            <button className="btn primary sm" onClick={() => runKbScan(kbDocIds)}>重新扫描</button>
          </div>
        ) : !kbResult || kbResult.items.length === 0 ? (
          <div className="empty">
            <div className="e-ico">📭</div>
            <div className="e-title">{kbResult && kbResult.totalDocs === 0 ? '知识库还没有文档' : '未识别到候选题'}</div>
            <div className="e-text">{kbResult && kbResult.totalDocs === 0 ? '请先上传并解析文档，再回来识别题目' : '已扫描所选文档，但未发现新的候选题目（可能都已入库）'}</div>
            <div className="e-actions"><button className="btn primary" onClick={() => runKbScan(kbDocIds)}>重新扫描</button></div>
          </div>
        ) : (
          <>
            <div className="kbimp-sum">
              <div className="ks-cell"><div className="ks-num">{kbResult.totalCandidates}</div><div className="ks-lab">候选题目总数</div></div>
              <div className="ks-cell"><div className="ks-num">{kbResult.dupSkipped}</div><div className="ks-lab">已去重跳过</div></div>
              <div className="ks-cell"><div className="ks-num">{kbResult.scannedDocs}<span className="ks-of"> / {kbResult.totalDocs}</span></div><div className="ks-lab">扫描文档{kbResult.elapsed ? ` · 耗时 ${kbResult.elapsed.toFixed(1)}s` : ''}</div></div>
            </div>

            {kbSubjDist.length > 0 && (
              <div className="kbimp-subj">
                {kbSubjDist.map((s) => <span key={s.name} className="badge info">{s.name} · {s.count}</span>)}
              </div>
            )}

            <div className="toolbar">
              <div className="left">
                <span className="badge success">已勾选 {kbChecked.size} / {kbSelectable.total} 新题</span>
              </div>
              <div className="right">
                <button className="btn ghost sm" onClick={() => toggleAllKb(true)}>全选新题</button>
                <button className="btn ghost sm" onClick={() => toggleAllKb(false)}>清空</button>
              </div>
            </div>

            <div className="kbimp-list">
              {kbResult.items.map((doc) => {
                const expanded = kbExpanded.has(doc.doc_id)
                const shown = expanded ? doc.candidates : doc.candidates.slice(0, 5)
                const newCount = doc.candidates.filter((c) => !c.existing).length
                return (
                  <div key={doc.doc_id} className="kbimp-doc">
                    <div className="kbimp-doc-head">
                      <span className="kbimp-doc-title" title={doc.doc_title}>{doc.doc_title}</span>
                      <span className="badge">{doc.subject}</span>
                      <span className="badge info">{newCount} 新 / {doc.candidates.length} 总</span>
                      {doc.truncated && <span className="badge warning">候选过多已截断</span>}
                    </div>
                    {shown.map((c) => (
                      <div key={c._key} className={`kbimp-qrow ${c.existing ? 'existing' : ''}`}>
                        <label className="kbimp-check">
                          <input type="checkbox" checked={kbChecked.has(c._key)} disabled={c.existing} onChange={() => toggleKb(c._key)} />
                          <span className="box" />
                        </label>
                        <div className="kbimp-qmain">
                          <div className="kbimp-stem">{c.stem}</div>
                          <div className="kbimp-qmeta">
                            {c.type && <span className="badge">{c.type}</span>}
                            {c.existing
                              ? <span className="badge warning">已存在</span>
                              : <span className="badge success">新题</span>}
                          </div>
                        </div>
                      </div>
                    ))}
                    {doc.candidates.length > 5 && (
                      <button className="kbimp-more" onClick={() => toggleKbDoc(doc.doc_id)}>
                        {expanded ? '收起' : `展开全部 ${doc.candidates.length} 题 ▾`}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          </>
        )}
      </Modal>

      {/* ============ V3 治理：文档详情抽屉（Markdown 快照 + 导出 + 归档） ============ */}
      <Modal
        open={!!detailDoc}
        title={detailDoc ? `文档详情 · ${detailDoc.filename}` : ''}
        onClose={() => { setDetailDoc(null); setSnapshot({ state: 'idle', md: '', path: '', exists: false }) }}
        footer={detailDoc ? (
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn ghost" onClick={() => exportDoc(detailDoc, 'md')}>导出 MD</button>
            <button className="btn ghost" onClick={() => exportDoc(detailDoc, 'txt')}>导出 TXT</button>
            <button className="btn ghost" onClick={() => exportDoc(detailDoc, 'pdf')} title="PDF 依赖不可用时后端会降级为 Markdown 并提示">导出 PDF</button>
            {detailDoc.has_local_file && (
              <>
                <a className="btn ghost" href={documentsApi.downloadUrl(detailDoc.id)} download>下载原文件</a>
                <button className="btn ghost" onClick={() => archiveDoc(detailDoc)}>归档源文件</button>
              </>
            )}
            {isEmptyBody(detailDoc) && (
              <button className="btn primary" disabled={parsingId === detailDoc.id} onClick={() => parse(detailDoc.id)}>
                {parsingId === detailDoc.id ? '解析中…' : '重新解析'}
              </button>
            )}
            <button className="btn ghost" onClick={() => { setDetailDoc(null) }}>关闭</button>
          </div>
        ) : null}
      >
        {detailDoc && (
          <div className="doc-detail">
            <div className="doc-detail-meta">
              <span className="badge">{detailDoc.file_type || detailDoc.doc_type || '未知类型'}</span>
              <SubTag subject={detailDoc.subject} />
              <span className="badge">{fmtBytes(detailDoc.size)}</span>
              <span className={`badge ${isEmptyBody(detailDoc) ? 'danger' : 'info'}`}>{detailDoc.content_length || 0} 字</span>
              {isEmptyBody(detailDoc) && <span className="badge danger">正文缺失，建议重新解析</span>}
              {!detailDoc.has_local_file && <span className="badge warning" title={detailDoc.local_file_note}>{detailDoc.local_file_note || '本地无原文'}</span>}
            </div>
            <div className="doc-detail-mdhead">
              <span>Markdown 快照预览</span>
              {snapshot.path && <span className="doc-detail-path" title={snapshot.path}>{snapshot.exists ? '已落盘' : '未落盘'}：{snapshot.path}</span>}
            </div>
            {snapshot.state === 'loading' ? (
              <div className="loading-inline"><i />正在生成快照…</div>
            ) : snapshot.state === 'error' ? (
              <div className="doc-pre">快照生成失败，可稍后重试</div>
            ) : (
              <div className="doc-pre">{snapshot.md || '（该文档暂无正文，快照为空）'}</div>
            )}
          </div>
        )}
      </Modal>

      {/* ============ V3 治理：内联科目维护（增删改，走科目 API） ============ */}
      <Modal
        open={subjMgrOpen}
        title="科目维护（文档页内联入口）"
        onClose={() => setSubjMgrOpen(false)}
        footer={<button className="btn primary" onClick={() => setSubjMgrOpen(false)}>关闭</button>}
      >
        <div className="doc-subjmgr">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <span className="badge info">共 {subjList.length} 个科目</span>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn ghost sm" disabled={subjBusy} onClick={loadSubjects}>刷新</button>
              <button className="btn primary sm" onClick={() => setSubjEditor({ open: true, mode: 'create', original: '', name: '' })}>+ 添加科目</button>
            </div>
          </div>
          {subjBusy && subjList.length === 0 ? (
            <div className="loading-inline"><i />加载科目…</div>
          ) : subjList.length === 0 ? (
            <EmptyState icon="📚" title="暂无科目" desc="点击「添加科目」创建第一个科目" />
          ) : (
            <div className="list">
              {subjList.map((s) => (
                <div key={s.subject} className="list-row">
                  <div className="lr-main">
                    <div className="lr-title">{s.subject}</div>
                    <div className="lr-meta">
                      {s.unregistered ? '未登记' : s.is_custom ? '自定义' : '内置'}
                      {s.question_count != null ? ` · ${s.question_count} 题` : ''}
                      {s.document_count != null ? ` · ${s.document_count} 篇资料` : ''}
                    </div>
                  </div>
                  <div className="lr-actions">
                    <button className="btn ghost sm" onClick={() => setSubjEditor({ open: true, mode: 'edit', original: s.subject, name: s.subject })}>编辑</button>
                    <button className="btn danger sm" onClick={() => removeSubject(s)}>删除</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 添加 / 编辑子弹窗 */}
        <Modal
          open={subjEditor.open}
          title={subjEditor.mode === 'create' ? '添加科目' : '编辑科目'}
          onClose={() => setSubjEditor({ open: false, mode: 'create', original: '', name: '' })}
          footer={(
            <>
              <button className="btn ghost" onClick={() => setSubjEditor({ open: false, mode: 'create', original: '', name: '' })}>取消</button>
              <button className="btn primary" disabled={subjBusy} onClick={submitSubjectForm}>{subjBusy ? '保存中…' : '保存'}</button>
            </>
          )}
        >
          <div className="field">
            <label>科目名称</label>
            <input className="input" value={subjEditor.name} autoFocus
              onChange={(e) => setSubjEditor((s) => ({ ...s, name: e.target.value }))}
              placeholder="如：数字电子技术" />
          </div>
        </Modal>
      </Modal>
    </div>
  )
}
