import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast, CountUp } from '../components/UI'
import { Card } from '../components/Card'
import { documentsApi, getBackendState, subscribeBackendState } from '../api/client'
import KbHealthPanel from '../components/KbHealthPanel'
import { governanceApi, VIEWS, sigOf, kpItems } from './docShared'
import DocumentsUpload from './DocumentsUpload'
import DocumentsList from './DocumentsList'
import DocumentsSearch from './DocumentsSearch'
import DocumentsKnowledge from './DocumentsKnowledge'
import DocTextPreviewModal from './DocTextPreviewModal'
import DocFilePreviewModal from './DocFilePreviewModal'
import { Book, CheckCircle, FileText, Layers, Type, Warning } from '../components/Icon'
import DocQuestionPreviewModal from './DocQuestionPreviewModal'
import DocKbImportModal from './DocKbImportModal'
import DocDetailModal from './DocDetailModal'
import DocSubjectMgrModal from './DocSubjectMgrModal'

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

   V10 工程拆分（结构重构，行为不变）：
     Documents.jsx          容器：核心列表数据 + 页面骨架 + 各文档动作
     DocumentsUpload.jsx    批量上传 dropzone + 去重队列
     DocumentsList.jsx      文档卡片网格 + 批量操作栏
     DocumentsSearch.jsx    知识库检索（RAG）
     DocumentsKnowledge.jsx 知识点图谱 / 分块
     DocTextPreviewModal.jsx    原文预览
     DocFilePreviewModal.jsx    原文件（字节流）预览
     DocQuestionPreviewModal.jsx 题目预览与人工审核
     DocKbImportModal.jsx      知识库题目识别 / 确认入库
     DocDetailModal.jsx        文档详情抽屉
     DocSubjectMgrModal.jsx    内联科目维护
     docShared.js           治理 API 与共享纯函数（原模块级定义原样拆出）
   ============================================================ */

/* ------------------------------------------------------------------
 * 页面级「接口异常」聚合（P2-4）
 * 文档库同时依赖 documents / kb / kb-import 三域接口，任意几个 503 散落成
 * 多行红字会让人以为整页不可用。这里按「接口路径」聚合成一条提示，
 * 口径与顶栏三态一致（5xx / 网络 / 超时才算异常，4xx 不算）。
 * ------------------------------------------------------------------ */
const DOC_ISSUE_PREFIXES = ['/documents', '/kb', '/kb-import']

function docIssuesOf(failures) {
  if (!Array.isArray(failures)) return []
  return failures.filter((f) => {
    const path = f && f.path ? String(f.path) : ''
    return DOC_ISSUE_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`))
  })
}

export default function Documents() {
  const [backendOk, setBackendOk] = useState(false)
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  /* 三态 + 本页相关的失败接口：用于把散落的 503 收敛成一条页面级提示 */
  const [backend, setBackend] = useState(() => {
    try {
      const s = getBackendState()
      if (s && s.state) return s
      if (s && typeof s.catch === 'function') s.catch(() => {})
    } catch { /* 兜底：读不到状态时按「未知」处理 */ }
    return { state: 'unknown', failures: [], checkedAt: 0 }
  })
  const [apiIssues, setApiIssues] = useState(() => docIssuesOf(backend.failures))
  const [subject, setSubject] = useState('all')
  const [subjectStats, setSubjectStats] = useState(null)
  const [subjectOptions, setSubjectOptions] = useState([])
  const [q, setQ] = useState('')
  const [uploading, setUploading] = useState(false)
  const [parsingId, setParsingId] = useState(null)
  const [analyzingId, setAnalyzingId] = useState(null)
  const [previewingId, setPreviewingId] = useState(null)
  const fileRef = useRef(null)
  const [view, setView] = useState('list') // list / knowledge / search
  /* 知识点图谱 / 分块（由容器加载后传入 DocumentsKnowledge） */
  const [kpDoc, setKpDoc] = useState(null)
  const [kpList, setKpList] = useState([])
  const [chunkDoc, setChunkDoc] = useState(null)
  const [chunkList, setChunkList] = useState([])
  const [kpSubject, setKpSubject] = useState('all')
  const [activeKp, setActiveKp] = useState(null)
  // V3 治理：扫描归档
  const [scanningRoot, setScanningRoot] = useState(false)
  // apply 模式会**同步**触发一次全库备份（耗时随库大小增长），期间请求阻塞。
  // 用独立标志驱动"正在备份，请勿关闭"提示，避免用户以为卡死而刷新（dry-run 不备份，不提示）。
  const [scanBacking, setScanBacking] = useState(false)
  const [subjMgrOpen, setSubjMgrOpen] = useState(false)
  /* 各弹窗的打开态与数据（弹窗内部状态自理） */
  const [previewDoc, setPreviewDoc] = useState(null)
  const [fileDoc, setFileDoc] = useState(null)
  const [showPreview, setShowPreview] = useState(false)
  const [previewQuestions, setPreviewQuestions] = useState([])
  const [previewOwner, setPreviewOwner] = useState(null)
  const [kbOpen, setKbOpen] = useState(false)
  const [kbDocIds, setKbDocIds] = useState(null) // null=全库；number[]=分批范围
  const [kbScopeLabel, setKbScopeLabel] = useState('全库') // Modal 标题展示用
  const [detailDoc, setDetailDoc] = useState(null)

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

  /* 订阅三态：失败登记（client 内）会触发一次 health 复判，这里只负责取回快照。
     订阅失败（测试桩/异常环境）不影响页面本身。 */
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
      else if (ret && typeof ret.catch === 'function') ret.catch(() => {})
    } catch { /* 忽略订阅异常 */ }
    return () => { alive = false; unsub() }
  }, [])

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
      /* 契约以 GET /documents/{doc_id}/knowledge-points 为准（routers/documents.py
         的 get_knowledge_points）：返回**裸数组**，不是 {knowledge_points:[…]}。
         之前这里读 r.knowledge_points || r.points，两个键后端都不存在，
         于是知识点视图永远空 —— 页面看起来是「这篇文档没抽取出知识点」，
         实际是接口回来了 20 条却被丢掉了。 */
      const r = await documentsApi.knowledgePoints(Number(d.id))
      setKpList(kpItems(r))
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

  /* ---------------- V8 阶段3：知识库 → 题目识别预览 / 确认入库 ---------------- */
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

  /* 扫描 knowledge_base 根目录 → 按科目归档（dryRun 预览） */
  const runScanRoot = async (dryRun) => {
    if (!backendOk) return toast('需连接后端扫描')
    if (!dryRun && !confirm('扫描 knowledge_base 根目录并按科目归档？文件会被移动到 {科目}/ 目录，DB 路径同步更新（断链记录只统计不动）。\n\n注意：归档前会先做一次全库备份，耗时取决于库大小；备份期间请勿关闭页面。')) return
    setScanningRoot(true)
    setScanBacking(!dryRun)
    try {
      const r = await governanceApi.scanRoot(dryRun)
      const msg = r.message || `移动 ${r.moved}，跳过 ${r.skipped}，断链 ${r.broken}，失败 ${r.errors}`
      toast(msg)
      if (!dryRun) { await refresh(); refreshSubjects() }
    } catch (e) {
      toast(`扫描失败：${e.message}`)
    } finally {
      setScanningRoot(false)
      setScanBacking(false)
    }
  }

  /* 详情抽屉：仅做打开（快照拉取在 DocDetailModal 内） */
  const openDetail = (d) => {
    if (!backendOk) return toast('需连接后端查看文档详情')
    setDetailDoc(d)
  }
  /* 原文预览：仅做打开（正文拉取在 DocTextPreviewModal 内） */
  const onShowText = (d) => {
    if (!backendOk) return toast('需连接后端预览文档')
    setPreviewDoc(d)
  }
  /* 知识点视图返回列表：清空选中并回列表（与拆分前「← 返回列表」一致） */
  const onBackToList = () => { setKpDoc(null); setChunkDoc(null); setActiveKp(null); setView('list') }

  return (
    <div>
      <style>{`
        .doc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
        /* V3 治理：批量操作栏 / 选择框 / 详情抽屉 / 内联科目维护 */
        .doc-bulkbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 10px 14px; margin-bottom: 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); }
        /* 归档前的备份等待提示：同步全库备份，耗时看库大小，别让用户误判成卡死 */
        .doc-scanhint { display: flex; align-items: center; gap: 10px; padding: 11px 15px; margin-bottom: 14px; background: var(--accent-soft, var(--surface-2)); border: 1px solid var(--accent); border-radius: var(--radius-md); color: var(--fg); font-size: 12.8px; line-height: 1.6; }
        .doc-scanhint i { flex: none; width: 15px; height: 15px; border-radius: 50%; border: 2px solid var(--accent); border-top-color: transparent; animation: doc-spin 0.8s linear infinite; }
        @keyframes doc-spin { to { transform: rotate(360deg); } }
        /* 页面级接口异常提示条：与顶栏 degraded 同口径，提示但不阻断浏览 */
        .doc-apiwarn { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 8px 16px; padding: 10px 14px; margin-bottom: 14px; background: var(--warn-soft); border: 1px solid var(--warn); border-radius: var(--radius-md); color: var(--warn-ink); font-size: 12.8px; line-height: 1.6; }
        .doc-apiwarn-main { display: flex; align-items: flex-start; gap: 8px; }
        .doc-apiwarn-main svg { flex: none; margin-top: 3px; }
        .doc-apiwarn-detail summary { cursor: pointer; font-weight: 600; }
        .doc-apiwarn-detail ul { margin: 6px 0 0; padding-left: 18px; color: var(--fg-2); font-size: 12px; }
        .doc-apiwarn-detail li { display: flex; gap: 8px; }
        .doc-apiwarn-detail code { font-family: var(--font-mono); }
        .doc-check-inline { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--fg-2); cursor: pointer; }
        .doc-check { width: 16px; height: 16px; cursor: pointer; accent-color: var(--accent); flex: none; }
        .doc-card-checked { border-color: var(--accent) !important; box-shadow: 0 0 0 1px var(--accent) inset; }
        .doc-detail { display: flex; flex-direction: column; gap: 10px; }
        .doc-detail-meta { display: flex; flex-wrap: wrap; gap: 6px; }
        .doc-detail-mdhead { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap; font-size: 12.5px; font-weight: 700; color: var(--fg-2); }
        .doc-detail-path { font-weight: 400; color: var(--muted); font-size: 11.5px; max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .doc-subjmgr { max-height: 52vh; overflow-y: auto; }
        .kp-cloud { display: flex; flex-wrap: wrap; gap: 8px; }
        .kp-chip-lg { font-size: 13px; padding: 7px 13px; }
        .doc-pre { font-size: 12.8px; line-height: 1.9; white-space: pre-wrap; word-break: break-word; color: var(--fg); background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; max-height: 46vh; overflow-y: auto; }
        /* #26 原文件字节流预览：PDF/图片交给浏览器渲染，后端已支持 Range，翻页不会整读 908MB */
        .file-frame { display: block; width: 100%; height: 68vh; border: 1px solid var(--border); border-radius: var(--radius-md); background: #fff; }
        /* V8 阶段3：kb-import 识别预览（新增 class，颜色全部走 var(--*)） */
        .kbimp-sum { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
        .kbimp-sum .ks-cell { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 12px; }
        .kbimp-sum .ks-num { font-size: 22px; font-weight: 800; color: var(--fg); font-family: var(--font-sans); line-height: 1.1; }
        .kbimp-sum .ks-of { font-size: 13px; font-weight: 600; color: var(--muted); }
        .kbimp-sum .ks-lab { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
        .kbimp-subj { display: flex; flex-wrap: wrap; gap: 6px; }
        .kbimp-list { display: flex; flex-direction: column; gap: 10px; }
        .kbimp-doc { border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
        .kbimp-doc-head { display: flex; align-items: center; gap: 8px; padding: 9px 12px; background: var(--surface-2); }
        .kbimp-doc-title { flex: 1; min-width: 0; font-size: 13px; font-weight: 700; color: var(--fg); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .kbimp-qrow { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border-top: 1px solid var(--border); }
        .kbimp-qrow.existing { background: var(--surface-2); opacity: 0.72; }
        .kbimp-check { position: relative; flex: none; width: 18px; height: 18px; margin-top: 2px; }
        .kbimp-check input { position: absolute; inset: 0; opacity: 0; margin: 0; cursor: pointer; }
        .kbimp-check .box { width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid var(--border-strong); background: var(--surface); display: grid; place-items: center; color: #fff; font-size: 12px; line-height: 1; transition: background var(--motion-fast), border-color var(--motion-fast); }
        .kbimp-check input:checked + .box { background: var(--accent); border-color: var(--accent); }
        .kbimp-check input:checked + .box::after { content: '已完成'; }
        .kbimp-check input:disabled + .box { background: var(--surface-2); border-color: var(--border); cursor: not-allowed; }
        .kbimp-qmain { flex: 1; min-width: 0; }
        .kbimp-stem { font-size: 12.8px; line-height: 1.7; color: var(--fg); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
        .kbimp-qmeta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
        .kbimp-more { width: 100%; padding: 8px; border: none; border-top: 1px solid var(--border); background: var(--surface-2); color: var(--accent); font-size: 12px; font-weight: 600; cursor: pointer; }
        .kbimp-err { background: var(--danger-soft); border: 1px solid rgba(224, 82, 74, 0.25); color: var(--danger); border-radius: var(--radius-sm); padding: 14px; display: flex; flex-direction: column; gap: 8px; }
        .kbimp-err-title { font-size: 13.5px; font-weight: 700; }
        .kbimp-err-msg { font-size: 12.5px; line-height: 1.6; }
        .kbimp-result { display: flex; flex-direction: column; gap: 14px; }
        .kbimp-note { font-size: 12.5px; color: var(--muted); line-height: 1.7; margin: 0; }
      `}</style>

      <div className="page-head">
        <div>
          <h1 className="page-title">文档知识库</h1>
          <p className="page-sub">上传讲义 / 真题 / 笔记 · AI 自动解析提取知识点与分块</p>
        </div>
        <div className="page-actions">
          {/* 状态徽标与页面级提示同源：有接口异常时不再笼统写「后端已连接」，
              否则会和下方 503 详情互相打脸 */}
          {backend.state === 'offline' || !backendOk
            ? <span className="badge warning">后端离线</span>
            : backend.state === 'degraded'
              ? <span className="badge warning">部分接口异常</span>
              : <span className="badge success">后端已连接</span>}
          <span className="badge info">{overview.total} 篇 · {overview.chunks} 分块</span>
          <button className="btn ghost" onClick={parseAll} disabled={!backendOk || !overview.pending}>批量解析未入库</button>
          <button className="btn ghost" onClick={() => runScanRoot(false)} disabled={!backendOk || scanningRoot}
            title="扫描 knowledge_base 根目录，按科目归档到 {科目}/ 并同步 DB 路径（断链只统计；归档前先做一次全库备份）">
            {scanBacking ? '备份中，请勿关闭…' : (scanningRoot ? '扫描中…' : '扫描归档根目录')}
          </button>
          <button className="btn ghost" onClick={() => setSubjMgrOpen(true)} disabled={!backendOk} title="内联维护科目（增删改）">
            科目维护
          </button>
          <button className="btn outline" onClick={() => openKbImport(null)} disabled={!backendOk} title="扫描全部文档识别题目（约5分钟，建议分批）">
            搜索 全库识别
          </button>
          <button className="btn primary" disabled={uploading} onClick={() => fileRef.current?.click()}>
            {uploading ? '上传中…' : '↑ 批量上传'}
          </button>
        </div>
      </div>

      {/* 页面级接口异常聚合（P2-4）：一个提示条替代散落的 503 报错，
          明确「不影响浏览」，细节收进可展开区域。
          整站离线（health 不可达）时不说「不影响浏览」，交给上方的离线徽标。 */}
      {apiIssues.length > 0 && backend.state !== 'offline' && (
        <div className="doc-apiwarn" role="status" aria-live="polite">
          <div className="doc-apiwarn-main">
            <Warning size={15} />
            <span><b>{apiIssues.length} 项接口异常</b>，不影响浏览：已入库的文档、知识点与分块照常查看。</span>
          </div>
          <details className="doc-apiwarn-detail">
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
      )}

      {/* 归档前同步全库备份：明确告知用户别关页面。
          耗时取决于库大小，不写死具体 MB / 秒数——空库和新导入的库差别很大，写死了就是骗人。 */}
      {scanBacking && (
        <div className="doc-scanhint" role="status">
          <i />
          正在备份数据库（库越大越久），完成后自动按科目归档。<b>请勿关闭或刷新页面。</b>
        </div>
      )}

      {/* 知识库健康：缺口体检 + 一键修复 */}
      <KbHealthPanel />

      {/* 总览 stat-tile */}
      <div className="stat-grid" style={{ marginBottom: 'var(--space-4)' }}>
        <div className="stat-tile">
          <div className="st-ico blue"><FileText size={16} /></div>
          <div className="st-val"><CountUp value={overview.total} /></div>
          <div className="st-label">文档总数</div>
        </div>
        <div className="stat-tile">
          <div className="st-ico green"><CheckCircle size={16} /></div>
          <div className="st-val"><CountUp value={overview.parsed} /></div>
          <div className="st-label">已解析入库</div>
          {overview.pending > 0 && <div className="st-delta down">{overview.pending} 篇待解析</div>}
        </div>
        <div className="stat-tile">
          <div className="st-ico violet"><Layers size={16} /></div>
          <div className="st-val"><CountUp value={overview.chunks} /></div>
          <div className="st-label">知识分块</div>
        </div>
        <div className="stat-tile">
          <div className="st-ico amber"><Type size={16} /></div>
          <div className="st-val">{(overview.chars / 10000).toFixed(1)}<span style={{ fontSize: 'var(--text-base)', fontWeight: 700 }}> 万</span></div>
          <div className="st-label">入库总字数</div>
        </div>
      </div>

      {/* 科目统计 stat-tile（后端 /documents/subjects） */}
      {subjectStats && (subjectStats.subjects || []).length > 0 && (
        <Card
          title="科目分布"
          extra={<span className="badge">共 {subjectStats.total_documents} 篇 · {subjectStats.total_chunks} 分块</span>}
          style={{ marginBottom: 'var(--space-4)' }}
        >
            <div className="grid-4">
              {(subjectStats.subjects || []).map((s) => (
                <div key={s.name} className="stat-tile" style={{ cursor: 'pointer', borderColor: subject === s.name ? 'var(--accent)' : undefined }}
                  onClick={() => setSubject(subject === s.name ? 'all' : s.name)}>
                  <div className="row spread">
                    <div className="st-ico sm neutral"><Book size={14} /></div>
                    {subject === s.name && <span className="badge accent">筛选中</span>}
                  </div>
                  <div className="st-val" style={{ fontSize: 'var(--text-xl)' }}>{s.merged_document_count ?? s.document_count}</div>
                  <div className="st-label">
                    {s.name}{s.chunk_count != null ? ` · ${s.chunk_count} 分块` : ''}
                    {(s.aliases || []).length > 0 && `（含 ${s.aliases.join('、')}）`}
                  </div>
                </div>
              ))}
            </div>
        </Card>
      )}

      {/* 视图切换 + 筛选 */}
      <div className="toolbar" style={{ marginBottom: 'var(--space-4)' }}>
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
              搜索 识别当前列表（{filtered.length}）
            </button>
          )}
        </div>
        <div className="right">
          {view !== 'search' && (
            <select className="select" style={{ width: 180 }} aria-label="按科目筛选文档" value={subject} onChange={(e) => setSubject(e.target.value)}>
              <option value="all">全部科目</option>
              {subjectOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
          {view !== 'search' && <input className="input search" style={{ width: 220 }} placeholder="搜索文档 / 摘要" aria-label="搜索文档 / 摘要" value={q} onChange={(e) => setQ(e.target.value)} />}
        </div>
      </div>

      {/* 批量上传 dropzone + 去重队列（隐藏 file input 常驻，page-head 上传按钮经同一 fileRef 触发） */}
      <DocumentsUpload
        visible={view === 'list'}
        backendOk={backendOk}
        uploading={uploading}
        setUploading={setUploading}
        existSigs={existSigs}
        fileRef={fileRef}
        onUploadFile={upload}
        onRefresh={refresh}
        onRefreshSubjects={refreshSubjects}
      />

      <DocumentsSearch visible={view === 'search'} backendOk={backendOk} subjectOptions={subjectOptions} />

      <DocumentsList
        visible={view === 'list'}
        docs={docs}
        filtered={filtered}
        loading={loading}
        loadErr={loadErr}
        backendOk={backendOk}
        parsingId={parsingId}
        analyzingId={analyzingId}
        previewingId={previewingId}
        scanningRoot={scanningRoot}
        onRefresh={refresh}
        onRefreshSubjects={refreshSubjects}
        onUploadClick={() => fileRef.current?.click()}
        onClearFilters={() => { setQ(''); setSubject('all') }}
        onOpenDetail={openDetail}
        onParse={parse}
        onShowKnowledge={showKnowledge}
        onShowChunks={showChunks}
        onShowText={onShowText}
        onShowFile={(d) => setFileDoc(d)}
        onAnalyze={analyze}
        onPreviewQuestions={handlePreviewQuestions}
        onKbImportDoc={openKbImport}
        onGenerateQuiz={generateQuiz}
        onChangeSubject={changeDocSubject}
        onArchiveDoc={archiveDoc}
        onRemove={remove}
        onScanRootDry={runScanRoot}
      />

      <DocumentsKnowledge
        visible={view === 'knowledge'}
        kpDoc={kpDoc}
        kpList={kpList}
        chunkDoc={chunkDoc}
        chunkList={chunkList}
        kpSubject={kpSubject}
        setKpSubject={setKpSubject}
        activeKp={activeKp}
        setActiveKp={setActiveKp}
        onBackToList={onBackToList}
      />

      {/* 原文预览 Modal */}
      <DocTextPreviewModal doc={previewDoc} onClose={() => setPreviewDoc(null)} />

      {/* 原文件（磁盘上那份）预览 Modal：字节流走 /documents/{id}/raw，后端支持 Range */}
      <DocFilePreviewModal doc={fileDoc} onClose={() => setFileDoc(null)} />

      {/* 题目预览 / 人工审核 Modal */}
      <DocQuestionPreviewModal
        open={showPreview}
        questions={previewQuestions}
        owner={previewOwner}
        onClose={() => { setShowPreview(false); setPreviewQuestions([]); setPreviewOwner(null) }}
        onQuestionsChange={setPreviewQuestions}
        onImported={refresh}
      />

      {/* V8 阶段3：知识库题目识别预览 / 确认入库 Modal */}
      <DocKbImportModal
        open={kbOpen}
        docIds={kbDocIds}
        scopeLabel={kbScopeLabel}
        onClose={() => setKbOpen(false)}
        onImported={() => { refresh(); refreshSubjects() }}
      />

      {/* V3 治理：文档详情抽屉（Markdown 快照 + 导出 + 归档） */}
      <DocDetailModal
        doc={detailDoc}
        onClose={() => setDetailDoc(null)}
        onArchive={archiveDoc}
        onParse={parse}
        parsingId={parsingId}
      />

      {/* V3 治理：内联科目维护（增删改，走科目 API） */}
      <DocSubjectMgrModal
        open={subjMgrOpen}
        onClose={() => setSubjMgrOpen(false)}
        onSubjectsChanged={refreshSubjects}
      />
    </div>
  )
}
