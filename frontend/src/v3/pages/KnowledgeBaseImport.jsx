import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { kbApi, documentsApi, quizApi, kbImportApi } from '../../api/client'
import { fmtBytes } from '../../utils/format'
import {
  Alert, Badge, Button, Card, CardHead, Dialog, Empty, PageHeader, Progress, Skeleton,
  Spinner, toastErr, toastOk, toastWarn, cx,
} from '../ui'
import {
  AlertTriangle, BookOpen, CheckCircle2, ChevronDown, ChevronUp, Database, FileText,
  FolderOpen, HardDrive, InfoCircle, Layers, RefreshCw, Sparkles, Tag, Upload,
} from '../icons'
import '../styles/admin-ops-v3.css'

/* ============================================================================
   知识库批量导入（Aurora v3）
   两条真实链路：
   1) /documents/upload → /documents/{id}/parse（解析、分块、向量化）
   2) /kb-import/scan（只读）→ 页内勾选 → /kb-import/confirm
   统计全部来自接口；任何接口失败都不拿演示数字冒充。
   ========================================================================== */

const ACCEPT = '.pdf,.docx,.doc,.txt,.md'
const sigOf = (name, size) => `${String(name || '').trim().toLowerCase()}::${size || 0}`

const TYPE_META = {
  pdf: { label: 'PDF 文档', desc: '教材、真题卷、讲义等' },
  docx: { label: 'Word 文档', desc: '笔记、习题集、解析' },
  doc: { label: '旧版 Word', desc: '.doc 兼容格式' },
  txt: { label: '纯文本', desc: '简单文本、导出数据' },
  md: { label: 'Markdown', desc: '技术文档、知识点总结' },
  pptx: { label: 'PPT', desc: '课件讲义' },
  ppt: { label: '旧版 PPT', desc: '.ppt 兼容格式' },
  xlsx: { label: 'Excel', desc: '表格类资料' },
  image: { label: '图片', desc: '扫描件、截图' },
  html: { label: 'HTML', desc: '网页存档' },
  json: { label: 'JSON', desc: '结构化数据' },
  jpg: { label: 'JPG 图片', desc: '扫描件、截图' },
  png: { label: 'PNG 图片', desc: '扫描件、截图' },
  other: { label: '其他格式', desc: '未识别的扩展名' },
}

const typeMeta = (type) => TYPE_META[type] || { label: String(type || '其他').toUpperCase(), desc: '其他格式' }

const UPLOAD_META = {
  pending: { tone: 'outline', text: '待上传' },
  dup: { tone: 'warning', text: '重复跳过' },
  uploading: { tone: 'soft', text: '上传中' },
  parsing: { tone: 'primary', text: '解析中' },
  done: { tone: 'success', text: '已完成' },
  warn: { tone: 'warning', text: '已上传' },
  error: { tone: 'danger', text: '失败' },
}

const INDEX_META = {
  indexed: { label: '已索引', tone: 'success' },
  ready: { label: '已索引', tone: 'success' },
  parsed: { label: '已解析', tone: 'primary' },
  parsing: { label: '解析中', tone: 'warning' },
  pending: { label: '待处理', tone: 'outline' },
  uploaded: { label: '已上传', tone: 'soft' },
  failed: { label: '失败', tone: 'danger' },
  error: { label: '失败', tone: 'danger' },
}

const ISSUE_META = {
  error: { label: '错误', tone: 'danger' },
  warn: { label: '警告', tone: 'warning' },
  info: { label: '提示', tone: 'soft' },
}

const fmtCount = (v) => {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN') : '—'
}

const fmtDateTime = (v) => (v ? String(v).slice(0, 16).replace('T', ' ') : '—')

const extOf = (name) => {
  const parts = String(name || '').split('.')
  return (parts.length > 1 ? parts.pop() : '?').slice(0, 4).toUpperCase()
}

/* ---------------- kb-import 契约容错规范化（与后端实测形态对齐） ---------------- */
const candStem = (c) => String(c.content || c.question || c.text || c.stem || c.title || c['题干'] || '（无题干）')
const candType = (c) => String(c.question_type || c.type || c.qtype || c['题型'] || '')
const candExisting = (c) => !!(c.already_exists || c.is_existing || c.exists || c.dup || c.is_dup || c.in_quiz)

function kbNormalize(resp) {
  const rawItems = resp?.items || resp?.candidates || resp?.docs || []
  const items = (Array.isArray(rawItems) ? rawItems : []).map((it) => {
    const docId = it.doc_id ?? it.id ?? ''
    const candidates = Array.isArray(it.candidates)
      ? it.candidates
      : (Array.isArray(it.items) ? it.items : [])
    return {
      doc_id: docId,
      doc_title: it.doc_title ?? it.title ?? it.file_name ?? it.filename ?? '未命名文档',
      subject: it.subject || '未分类',
      truncated: !!it.truncated,
      candidates: candidates.map((c, index) => {
        const candIndex = typeof c.index === 'number' ? c.index : index
        return {
          _key: `${docId}::${candIndex}`,
          docId,
          candIndex,
          stem: candStem(c),
          type: candType(c),
          existing: candExisting(c),
          raw: c,
        }
      }),
    }
  }).filter((doc) => doc.candidates.length > 0)

  const scannedDocs = resp?.scanned_docs ?? resp?.scannedDocs ?? items.length
  return {
    totalDocs: resp?.total_docs ?? resp?.totalDocs ?? items.length,
    scannedDocs,
    scopeDocs: resp?.file_type ? scannedDocs : null,
    totalCandidates: resp?.total_candidates ?? resp?.totalCandidates
      ?? items.reduce((sum, doc) => sum + doc.candidates.length, 0),
    dupSkipped: resp?.dup_skipped ?? resp?.dupSkipped ?? resp?.duplicates_skipped ?? 0,
    elapsed: Number(resp?.elapsed_seconds ?? resp?.elapsed_ms ?? 0) || 0,
    items,
  }
}

/* ============================================================================
   题目识别 / 确认入库弹窗（等价迁移自 legacy DocKbImportModal）
   ========================================================================== */
function KbScanDialog({ docIds, fileType, scopeLabel, onClose, onImported }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [checked, setChecked] = useState(() => new Set())
  const [expanded, setExpanded] = useState(() => new Set())
  const [askConfirm, setAskConfirm] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState('')
  const [done, setDone] = useState(null)

  const mountedRef = useRef(true)
  const startedRef = useRef(false)
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const runScan = useCallback(async () => {
    setLoading(true)
    setError('')
    setDone(null)
    setAskConfirm(false)
    setConfirmError('')
    try {
      // scan 入参：{doc_ids?, file_type?}；都缺省 = 全库
      const body = {}
      if (Array.isArray(docIds) && docIds.length) body.doc_ids = docIds
      if (fileType) body.file_type = fileType
      const resp = await kbImportApi.scan(body)
      if (!mountedRef.current) return
      const normalized = kbNormalize(resp)
      setResult(normalized)
      const next = new Set()
      normalized.items.forEach((doc) => doc.candidates.forEach((cand) => {
        if (!cand.existing) next.add(cand._key)
      }))
      setChecked(next)
      setExpanded(new Set())
    } catch (e) {
      if (!mountedRef.current) return
      setResult(null)
      setError(e?.message || '扫描失败，请稍后重试')
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [docIds, fileType])

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    runScan()
  }, [runScan])

  const subjDist = useMemo(() => {
    if (!result) return []
    const map = new Map()
    result.items.forEach((doc) => doc.candidates.forEach(() => {
      map.set(doc.subject, (map.get(doc.subject) || 0) + 1)
    }))
    return Array.from(map.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
  }, [result])

  const selectable = useMemo(() => {
    if (!result) return { total: 0, checked: 0 }
    let total = 0
    result.items.forEach((doc) => doc.candidates.forEach((cand) => {
      if (!cand.existing) total += 1
    }))
    return { total, checked: checked.size }
  }, [result, checked])

  const toggleKb = (cand) => {
    if (cand.existing) return
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(cand._key)) next.delete(cand._key)
      else next.add(cand._key)
      return next
    })
  }

  const toggleAllKb = (check) => {
    if (!result) return
    if (!check) {
      setChecked(new Set())
      return
    }
    const next = new Set()
    result.items.forEach((doc) => doc.candidates.forEach((cand) => {
      if (!cand.existing) next.add(cand._key)
    }))
    setChecked(next)
  }

  const toggleDoc = (docId) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(docId)) next.delete(docId)
      else next.add(docId)
      return next
    })
  }

  const doConfirm = async () => {
    if (!result || !checked.size) {
      toastWarn('请先勾选要入库的题目')
      return
    }
    setConfirming(true)
    setConfirmError('')
    try {
      // 后端契约：{selected:[{doc_id,index}]}，index 取 scan 下发的稳定下标
      const selected = []
      result.items.forEach((doc) => doc.candidates.forEach((cand) => {
        if (checked.has(cand._key)) selected.push({ doc_id: cand.docId, index: cand.candIndex })
      }))
      const resp = await kbImportApi.confirm({ selected })
      if (!mountedRef.current) return
      const payload = {
        inserted: resp?.inserted ?? 0,
        skipped: resp?.skipped_existing ?? resp?.skipped ?? 0,
        outOfRange: resp?.out_of_range ?? 0,
        bySubject: resp?.by_subject || {},
      }
      setDone(payload)
      setAskConfirm(false)
      toastOk(`已入库 ${payload.inserted} 题 / 跳过已存在 ${payload.skipped} 题`)
      onImported?.()
    } catch (e) {
      if (!mountedRef.current) return
      setConfirmError(e?.message || '入库失败，请稍后重试')
      toastErr(`入库失败：${e?.message || e}`)
    } finally {
      if (mountedRef.current) setConfirming(false)
    }
  }

  const footer = done ? (
    <Button variant="filled" onClick={onClose}>完成</Button>
  ) : loading ? (
    <Button variant="text" onClick={onClose}>取消</Button>
  ) : error ? (
    <Button variant="text" onClick={onClose}>关闭</Button>
  ) : (
    <>
      <Button variant="text" onClick={onClose}>取消</Button>
      {askConfirm ? (
        <>
          <Button variant="text" onClick={() => setAskConfirm(false)} disabled={confirming}>返回检查</Button>
          <Button variant="filled" loading={confirming} onClick={doConfirm}>
            确认写入 {checked.size} 题
          </Button>
        </>
      ) : (
        <Button
          variant="filled"
          disabled={!checked.size || !result?.items.length}
          onClick={() => setAskConfirm(true)}
        >
          确认入库（{checked.size}）
        </Button>
      )}
    </>
  )

  return (
    <Dialog
      open
      wide
      title={done ? '入库完成' : `知识库题目识别预览 · ${scopeLabel || '全库'}`}
      sub="扫描操作只读；只有确认入库才会写入题库，来源标记为「知识库:文档名」。"
      onClose={() => { if (!confirming) onClose() }}
      footer={footer}
    >
      {askConfirm && (
        <Alert tone="warning" icon={<AlertTriangle size={17} />} className="v3-kbi-ask">
          确认将选中的 {checked.size} 道题目写入题库？写入后可在刷题中心查看，来源标记为「知识库:文档名」。
        </Alert>
      )}
      {confirmError && <Alert tone="danger" className="v3-kbi-ask">入库失败：{confirmError}</Alert>}

      {loading ? (
        <div className="v3-kbi-scan-loading">
          <Spinner size={30} />
          <b>正在扫描知识库文档并识别候选题目…</b>
          <p>
            {docIds || fileType
              ? '按范围识别通常数秒到数分钟，请耐心等待。'
              : '全库扫描逐篇打分，实测约 5 分钟，请耐心等待。'}
          </p>
          <div className="v3-kbi-scan-loading__bars">
            <Skeleton height={54} radius={12} />
            <Skeleton height={120} radius={12} />
          </div>
        </div>
      ) : done ? (
        <div className="v3-kbi-done">
          <div className="v3-kbi-scan-stats">
            <div><b>{fmtCount(done.inserted)}</b><span>实际入库（题）</span></div>
            <div><b>{fmtCount(done.skipped)}</b><span>跳过已存在（题）</span></div>
            <div><b>{fmtCount(done.outOfRange)}</b><span>下标越界（题）</span></div>
          </div>
          {Object.keys(done.bySubject || {}).length > 0 && (
            <div className="v3-kbi-scan-subjects">
              {Object.entries(done.bySubject).map(([subject, count]) => (
                <Badge key={subject} tone="soft">{subject} · {count}</Badge>
              ))}
            </div>
          )}
          <Alert tone="success" icon={<CheckCircle2 size={17} />}>
            入库流程已完成。可在「刷题中心」查看新入库的题目，来源标记为「知识库:文档名」。
          </Alert>
        </div>
      ) : error ? (
        <div className="v3-kbi-scan-error">
          <Alert tone="danger" icon={<AlertTriangle size={17} />}>
            <b>扫描失败</b>
            <div className="v3-kbi-scan-error__msg">{error}</div>
          </Alert>
          <Button variant="filled" size="sm" onClick={runScan}>重新扫描</Button>
        </div>
      ) : !result || result.items.length === 0 ? (
        <Empty
          icon={<Sparkles size={26} />}
          title={result && result.totalDocs === 0 ? '知识库还没有文档' : '未识别到候选题'}
          text={result && result.totalDocs === 0
            ? '请先上传并解析文档，再回来识别题目。'
            : result
              ? `已扫描 ${result.scannedDocs} 篇文档，未发现可入库的候选题目（可能是文档没有题号 / 选项结构，或题目都已入库）。`
              : '已扫描所选文档，但未发现新的候选题目（可能都已入库）。'}
          action={<Button variant="filled" size="sm" onClick={runScan}>重新扫描</Button>}
        />
      ) : (
        <div className="v3-kbi-scan">
          <div className="v3-kbi-scan-stats">
            <div><b>{fmtCount(result.totalCandidates)}</b><span>候选题目总数</span></div>
            <div><b>{fmtCount(result.dupSkipped)}</b><span>已去重跳过</span></div>
            <div>
              <b>{fmtCount(result.scannedDocs)}<em> / {fmtCount(result.scopeDocs ?? result.totalDocs)}</em></b>
              <span>扫描文档{result.elapsed ? ` · 耗时 ${result.elapsed.toFixed(1)}s` : ''}</span>
            </div>
          </div>

          {subjDist.length > 0 && (
            <div className="v3-kbi-scan-subjects">
              {subjDist.map((subject) => (
                <Badge key={subject.name} tone="soft">{subject.name} · {subject.count}</Badge>
              ))}
            </div>
          )}

          <div className="v3-kbi-scan-toolbar">
            <Badge tone="success">已勾选 {selectable.checked} / {selectable.total} 新题</Badge>
            <div className="v3-row">
              <Button size="sm" variant="ghost" onClick={() => toggleAllKb(true)}>全选新题</Button>
              <Button size="sm" variant="ghost" onClick={() => toggleAllKb(false)}>清空</Button>
            </div>
          </div>

          <div className="v3-kbi-doc-list">
            {result.items.map((doc, docIdx) => {
              const open = expanded.has(doc.doc_id)
              const shown = open ? doc.candidates : doc.candidates.slice(0, 5)
              const newCount = doc.candidates.filter((cand) => !cand.existing).length
              return (
                <div className="v3-kbi-scan-doc" key={`${doc.doc_id}-${docIdx}`}>
                  <div className="v3-kbi-scan-doc__head">
                    <span className="v3-kbi-scan-doc__title" title={doc.doc_title}>{doc.doc_title}</span>
                    <Badge tone="soft">{doc.subject}</Badge>
                    <Badge tone="primary">{newCount} 新 / {doc.candidates.length} 总</Badge>
                    {doc.truncated && <Badge tone="warning">候选过多已截断</Badge>}
                  </div>
                  <div className="v3-kbi-cand-list">
                    {shown.map((cand) => (
                      <label
                        className={cx('v3-kbi-cand', cand.existing && 'is-existing', checked.has(cand._key) && 'is-checked')}
                        key={cand._key}
                      >
                        <input
                          type="checkbox"
                          className="v3-ops-check"
                          checked={checked.has(cand._key)}
                          disabled={cand.existing}
                          onChange={() => toggleKb(cand)}
                          aria-label={`选择题目：${cand.stem.slice(0, 40)}`}
                        />
                        <span className="v3-kbi-cand__body">
                          <span className="v3-kbi-cand__stem">{cand.stem}</span>
                          <span className="v3-kbi-cand__meta">
                            {cand.type && <Badge tone="outline">{cand.type}</Badge>}
                            {cand.existing
                              ? <Badge tone="warning">已存在</Badge>
                              : <Badge tone="success">新题</Badge>}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                  {doc.candidates.length > 5 && (
                    <button type="button" className="v3-kbi-scan-more" onClick={() => toggleDoc(doc.doc_id)}>
                      {open ? '收起' : `展开全部 ${doc.candidates.length} 题`}
                      {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </Dialog>
  )
}

/* ============================================================================
   页面主体
   ========================================================================== */
export default function KnowledgeBaseImport() {
  const [stats, setStats] = useState(null)
  const [health, setHealth] = useState(null)
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [statsError, setStatsError] = useState('')
  const [sectionErrors, setSectionErrors] = useState({})
  const [lastSync, setLastSync] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadRows, setUploadRows] = useState([])
  const [dragging, setDragging] = useState(false)
  const [scan, setScan] = useState(null)

  const fileRef = useRef(null)
  const seqRef = useRef(0)
  const scanSeqRef = useRef(0)
  const mountedRef = useRef(true)
  const docsRef = useRef([])
  const healthRef = useRef(null)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  /* ---------------- 统计与文档列表 ---------------- */
  const loadStats = useCallback(async ({ quiet = false } = {}) => {
    const seq = ++seqRef.current
    if (quiet) setRefreshing(true)
    else setLoading(true)

    const [kbR, docsR, quizR] = await Promise.allSettled([
      kbApi.health(),
      documentsApi.list(),
      quizApi.stats(),
    ])
    if (!mountedRef.current || seq !== seqRef.current) {
      return { stale: true, ok: false }
    }

    if (kbR.status === 'rejected' && docsR.status === 'rejected') {
      setStats(null)
      setDocs([])
      docsRef.current = []
      setHealth(null)
      healthRef.current = null
      setStatsError(kbR.reason?.message || docsR.reason?.message || '统计接口不可用')
      setSectionErrors({})
      setLoading(false)
      setRefreshing(false)
      return { ok: false, fatal: true }
    }

    setStatsError('')
    const kb = kbR.status === 'fulfilled' ? (kbR.value || null) : healthRef.current
    const docsRaw = docsR.status === 'fulfilled' ? docsR.value : docsRef.current
    const quiz = quizR.status === 'fulfilled' ? (quizR.value || null) : null
    const items = Array.isArray(docsRaw) ? docsRaw : (docsRaw?.items || [])
    const safeDocs = Array.isArray(items) ? items : []
    setHealth(kb)
    healthRef.current = kb
    setDocs(safeDocs)
    docsRef.current = safeDocs

    const byType = {}
    const bySubject = {}
    let lastImport = null
    for (const doc of safeDocs) {
      const ext = String(doc.file_type || doc.doc_type || 'other').toLowerCase()
      byType[ext] = (byType[ext] || 0) + 1
      const subject = doc.subject || '未分类'
      bySubject[subject] = (bySubject[subject] || 0) + 1
      const t = doc.created_at || doc.uploaded_at || doc.updated_at
      if (t && (!lastImport || String(t) > String(lastImport))) lastImport = t
    }

    setStats({
      totalDocs: Number(kb?.documents?.total ?? safeDocs.length) || 0,
      chunks: kb?.chunks?.total ?? null,
      missingEmbedding: kb?.chunks?.missing_embedding ?? null,
      emptyContent: kb?.documents?.empty_content ?? null,
      issues: Array.isArray(kb?.issues) ? kb.issues.length : null,
      healthy: kb?.healthy,
      byType,
      bySubject,
      lastImport: lastImport ? String(lastImport).slice(0, 16).replace('T', ' ') : '从未',
      importedQuestions: quiz
        ? (Number(quiz.total_questions ?? quiz.visible_total ?? 0) || 0)
        : null,
    })

    const nextErrors = {}
    if (kbR.status === 'rejected') nextErrors.health = kbR.reason?.message || '知识库体检接口不可用'
    if (docsR.status === 'rejected') nextErrors.docs = docsR.reason?.message || '文档列表接口不可用'
    if (quizR.status === 'rejected') nextErrors.quiz = quizR.reason?.message || '题库统计接口不可用'
    setSectionErrors(nextErrors)

    setLoading(false)
    setRefreshing(false)
    if (kbR.status === 'fulfilled' || docsR.status === 'fulfilled' || quizR.status === 'fulfilled') {
      setLastSync(new Date())
    }
    return { ok: Object.keys(nextErrors).length === 0, errors: nextErrors }
  }, [])

  useEffect(() => { loadStats() }, [loadStats])

  const manualRefresh = async () => {
    const result = await loadStats({ quiet: true })
    if (result.stale) return
    if (result.fatal) toastErr('知识库统计接口不可用')
    else if (result.ok) toastOk('知识库统计已刷新')
    else toastWarn('部分统计接口不可用，缺失区块以「—」展示')
  }

  const existSigs = useMemo(
    () => new Set(docs.map((doc) => sigOf(doc.file_name, doc.size))),
    [docs],
  )

  const typeRows = useMemo(() => (
    Object.entries(stats?.byType || {})
      .map(([type, count]) => ({ type, count, ...typeMeta(type) }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
  ), [stats])

  const subjectRows = useMemo(() => (
    Object.entries(stats?.bySubject || {})
      .map(([subject, count]) => ({ subject, count }))
      .sort((a, b) => b.count - a.count || a.subject.localeCompare(b.subject))
  ), [stats])

  const recentDocs = useMemo(() => (
    [...docs]
      .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
      .slice(0, 10)
  ), [docs])

  const issues = useMemo(() => (Array.isArray(health?.issues) ? health.issues : []), [health])

  /* ---------------- 上传队列 ---------------- */
  const updateRow = (key, patch) => {
    setUploadRows((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  const openFilePicker = () => {
    if (uploading) {
      toastWarn('已有上传任务在进行，请等待完成')
      return
    }
    fileRef.current?.click()
  }

  const uploadFiles = async (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    if (uploading) {
      toastWarn('已有上传任务在进行，请等待完成')
      return
    }

    const rows = files.map((file, i) => ({
      key: `${Date.now()}-${i}-${file.name}`,
      name: file.name,
      size: file.size,
      status: 'pending',
      msg: '等待上传',
    }))
    setUploadRows(rows)
    setUploading(true)

    const seenSigs = new Set(existSigs)
    let ok = 0
    let dup = 0
    let fail = 0

    try {
      for (let i = 0; i < files.length; i += 1) {
        const file = files[i]
        const key = rows[i].key
        const sig = sigOf(file.name, file.size)
        if (seenSigs.has(sig)) {
          dup += 1
          updateRow(key, { status: 'dup', msg: '库中已有同名同大小文档，已跳过' })
          continue
        }
        seenSigs.add(sig)
        updateRow(key, { status: 'uploading', msg: '上传中…' })
        try {
          const formData = new FormData()
          formData.append('file', file)
          const result = await documentsApi.upload(formData)
          if (!result?.id) throw new Error('后端未返回文档 id')
          updateRow(key, { status: 'parsing', msg: '已上传，解析中…' })
          try {
            await documentsApi.parse(Number(result.id))
            updateRow(key, { status: 'done', msg: '上传并解析完成' })
          } catch (e) {
            updateRow(key, { status: 'warn', msg: `已上传；解析失败：${e?.message || e}` })
          }
          ok += 1
        } catch (e) {
          fail += 1
          updateRow(key, { status: 'error', msg: e?.message || String(e) })
        }
      }
    } finally {
      if (mountedRef.current) {
        setUploading(false)
        await loadStats({ quiet: true })
        const summary = `上传完成：成功 ${ok} 篇${dup ? `，跳过重复 ${dup} 篇` : ''}${fail ? `，失败 ${fail} 篇` : ''}`
        if (fail) toastWarn(summary, 4200)
        else toastOk(summary, 3200)
      }
    }
  }

  const uploadSummary = useMemo(() => {
    const total = uploadRows.length
    const finished = uploadRows.filter((row) => ['done', 'warn', 'dup', 'error'].includes(row.status)).length
    const ok = uploadRows.filter((row) => row.status === 'done' || row.status === 'warn').length
    const dup = uploadRows.filter((row) => row.status === 'dup').length
    const fail = uploadRows.filter((row) => row.status === 'error').length
    return { total, finished, ok, dup, fail, pct: total ? Math.round(finished / total * 100) : 0 }
  }, [uploadRows])

  const openScan = (docIds, fileType, scopeLabel) => {
    scanSeqRef.current += 1
    setScan({ key: scanSeqRef.current, docIds, fileType, scopeLabel })
  }

  const hasDocs = Number(stats?.totalDocs) > 0

  /* ---------------- 首屏骨架 ---------------- */
  if (loading && !stats && !statsError) {
    return (
      <div className="v3-ops v3-kbi">
        <PageHeader
          eyebrow="数据管理 / 知识库"
          title="知识库批量导入"
          sub="正在读取知识库统计、体检报告与文档列表…"
          actions={(
            <>
              <Button variant="ghost" icon={<RefreshCw size={15} />} disabled>刷新</Button>
              <Button variant="filled" icon={<Upload size={15} />} disabled>上传文档</Button>
            </>
          )}
        />
        <div className="v3-ops-stats">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} height={122} radius={22} />)}
        </div>
        <div className="v3-ops-grid-2 v3-kbi-top">
          <Skeleton height={360} radius={22} />
          <Skeleton height={360} radius={22} />
        </div>
      </div>
    )
  }

  return (
    <div className="v3-ops v3-kbi">
      <PageHeader
        eyebrow="数据管理 / 知识库"
        title="知识库批量导入"
        sub={`上传资料入知识库 · 按文件类型识别题目并确认入库 · 当前共 ${fmtCount(stats?.totalDocs)} 篇文档`}
        actions={(
          <>
            <Button
              variant="ghost"
              icon={<RefreshCw size={15} />}
              loading={refreshing}
              onClick={manualRefresh}
            >
              刷新
            </Button>
            <Button
              variant="ghost"
              icon={<Sparkles size={15} />}
              disabled={!hasDocs || uploading}
              title="扫描全部文档识别题目（约 5 分钟，建议先按类型分批）"
              onClick={() => openScan(null, null, '全库')}
            >
              全库扫描
            </Button>
            <Button
              variant="filled"
              icon={<Upload size={15} />}
              disabled={uploading}
              onClick={openFilePicker}
            >
              {uploading ? '上传中…' : '上传文档'}
            </Button>
          </>
        )}
      />

      <input
        ref={fileRef}
        type="file"
        multiple
        accept={ACCEPT}
        aria-label="选择要上传到知识库的文件"
        style={{ display: 'none' }}
        onChange={(e) => {
          uploadFiles(e.target.files)
          e.target.value = ''
        }}
      />

      {statsError && (
        <Alert tone="danger">
          <div className="v3-ops-inline">
            <span>知识库统计读取失败：{statsError}</span>
            <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
          </div>
        </Alert>
      )}
      {!statsError && (sectionErrors.health || sectionErrors.docs || sectionErrors.quiz) && (
        <Alert tone="warning">
          <div className="v3-ops-inline">
            <span>
              部分接口不可用：
              {[sectionErrors.health && '知识库体检', sectionErrors.docs && '文档列表', sectionErrors.quiz && '题库统计']
                .filter(Boolean).join('、')}
              。缺失值以「—」展示，未用 0 冒充。
            </span>
            <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
          </div>
        </Alert>
      )}

      {/* 知识库概览 */}
      <div className="v3-ops-stats">
        <div className="v3-ops-stat is-primary">
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><BookOpen size={14} />文档总数</span>
            <span className="v3-ops-stat__tag">篇</span>
          </div>
          <div className="v3-ops-stat__value">{fmtCount(stats?.totalDocs)}</div>
          <div className="v3-ops-stat__hint">最后导入：{stats?.lastImport || '从未'}</div>
        </div>
        <div className="v3-ops-stat is-info">
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><Layers size={14} />知识分块</span>
            <span className="v3-ops-stat__tag">块</span>
          </div>
          <div className="v3-ops-stat__value">{fmtCount(stats?.chunks)}</div>
          <div className="v3-ops-stat__hint">
            缺向量分块：{stats?.missingEmbedding == null ? '—' : fmtCount(stats.missingEmbedding)} 个
          </div>
        </div>
        <div className={cx('v3-ops-stat', stats?.issues == null ? 'is-muted' : (stats.issues > 0 ? 'is-warning' : 'is-success'))}>
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><AlertTriangle size={14} />待修问题</span>
            {health && <Badge tone={health.healthy ? 'success' : 'warning'}>{health.healthy ? '健康' : '需处理'}</Badge>}
          </div>
          <div className="v3-ops-stat__value">{fmtCount(stats?.issues)}</div>
          <div className="v3-ops-stat__hint">
            正文为空：{stats?.emptyContent == null ? '—' : fmtCount(stats.emptyContent)} 篇
          </div>
        </div>
        <div className="v3-ops-stat is-muted">
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><Database size={14} />题库总题数</span>
          </div>
          <div className="v3-ops-stat__value">{fmtCount(stats?.importedQuestions)}</div>
          <div className="v3-ops-stat__hint">
            {lastSync ? `统计同步于 ${lastSync.toLocaleTimeString('zh-CN', { hour12: false })}` : '来自 /quiz/stats'}
          </div>
        </div>
      </div>

      <div className="v3-ops-grid-2 v3-kbi-top">
        {/* 上传资料 */}
        <Card>
          <CardHead
            icon={<Upload size={17} />}
            title="上传资料"
            sub="PDF / Word / TXT / Markdown · 上传后自动解析、分块并向量化"
            actions={<Badge tone="outline">{ACCEPT.replaceAll('.', '').toUpperCase()}</Badge>}
          />
          <div
            className={cx('v3-kbi-dropzone', dragging && 'is-dragging', uploading && 'is-disabled')}
            role="button"
            tabIndex={0}
            aria-disabled={uploading}
            onClick={openFilePicker}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                openFilePicker()
              }
            }}
            onDragOver={(e) => { e.preventDefault(); if (!uploading) setDragging(true) }}
            onDragEnter={(e) => { e.preventDefault(); if (!uploading) setDragging(true) }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false)
            }}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              if (!uploading) uploadFiles(e.dataTransfer?.files)
            }}
          >
            <span className="v3-kbi-dropzone__orb"><Upload size={24} /></span>
            <b>{uploading ? '上传队列执行中…' : '把资料拖到这里，或点击选择'}</b>
            <p>支持多选 · 同名同大小的文件自动跳过 · 上传完成后即可按类型识别题目</p>
            <Button
              variant="tonal"
              size="sm"
              icon={<FolderOpen size={14} />}
              disabled={uploading}
              onClick={(e) => { e.stopPropagation(); openFilePicker() }}
            >
              选择文件
            </Button>
          </div>

          {uploadRows.length > 0 && (
            <div className="v3-kbi-upload">
              <div className="v3-kbi-upload__head">
                <div>
                  <b>上传队列</b>
                  <span>{uploadSummary.finished} / {uploadSummary.total} 已处理</span>
                </div>
                <Badge tone={uploading ? 'primary' : uploadSummary.fail ? 'warning' : 'success'}>
                  {uploading ? '进行中' : uploadSummary.fail ? '部分失败' : '已完成'}
                </Badge>
              </div>
              <Progress value={uploadSummary.pct} gradient={!uploadSummary.fail} height={6} />
              <div className="v3-kbi-upload__summary">
                <Badge tone="success">成功 {uploadSummary.ok}</Badge>
                <Badge tone="warning">重复 {uploadSummary.dup}</Badge>
                <Badge tone="danger">失败 {uploadSummary.fail}</Badge>
              </div>
              <div className="v3-kbi-upload__list">
                {uploadRows.map((row) => {
                  const meta = UPLOAD_META[row.status] || UPLOAD_META.pending
                  return (
                    <div className={cx('v3-kbi-file', row.status === 'error' && 'is-error')} key={row.key}>
                      <span className="v3-kbi-file__ext">{extOf(row.name)}</span>
                      <div className="v3-kbi-file__main">
                        <div className="v3-kbi-file__name" title={row.name}>{row.name}</div>
                        <div className="v3-kbi-file__meta">{fmtBytes(row.size)}{row.msg ? ` · ${row.msg}` : ''}</div>
                      </div>
                      <Badge tone={meta.tone}>{meta.text}</Badge>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </Card>

        {/* 体检 */}
        <Card>
          <CardHead
            icon={<HardDrive size={17} />}
            title="知识库体检"
            sub={health?.checked_at ? `最近体检 ${fmtDateTime(health.checked_at)}` : '来自 /api/kb/health'}
            actions={health ? (
              <Badge tone={health.healthy ? 'success' : 'warning'}>
                {health.healthy ? '通过' : `${issues.length} 项问题`}
              </Badge>
            ) : null}
          />
          {health ? (
            <>
              <div className="v3-kbi-health-meta">
                <div>
                  <span>缺向量分块</span>
                  <b>{health?.chunks?.missing_embedding == null ? '—' : fmtCount(health.chunks.missing_embedding)}</b>
                </div>
                <div>
                  <span>正文为空</span>
                  <b>{fmtCount(health?.documents?.empty_content)}</b>
                </div>
                <div>
                  <span>OCR 文档</span>
                  <b>{fmtCount(health?.documents?.ocr_used)}</b>
                </div>
              </div>
              {issues.length ? (
                <div className="v3-kbi-issues">
                  {issues.map((issue, idx) => {
                    const meta = ISSUE_META[issue.level] || ISSUE_META.info
                    return (
                      <div className={cx('v3-kbi-issue', `is-${issue.level || 'info'}`)} key={issue.key || idx}>
                        <span className="v3-kbi-issue__dot" aria-hidden="true" />
                        <div className="v3-kbi-issue__main">
                          <b>{issue.title}</b>
                          {issue.impact && <p>{issue.impact}</p>}
                          {issue.fix && <p>建议：{issue.fix}</p>}
                          <span className="v3-ops-caption">{issue.auto ? '可在后台自愈' : '需手动处理'}</span>
                        </div>
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <Alert tone="success" icon={<CheckCircle2 size={17} />}>
                  知识库体检未发现需要处理的问题。
                </Alert>
              )}
            </>
          ) : sectionErrors.health ? (
            <Alert tone="warning">
              <div className="v3-ops-inline">
                <span>体检数据不可用：{sectionErrors.health}</span>
                <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
              </div>
            </Alert>
          ) : (
            <Empty
              icon={<InfoCircle size={24} />}
              title="暂无体检数据"
              text="知识库体检接口未返回可展示的报告。"
            />
          )}
        </Card>
      </div>

      <div className="v3-ops-grid-2 v3-kbi-mid">
        {/* 按文件类型导入 */}
        <Card>
          <CardHead
            icon={<Layers size={17} />}
            title="按文件类型导入"
            sub="先按格式缩小扫描范围；扫描只读，勾选确认后才写题库"
            actions={<Badge tone="outline">{typeRows.length} 种格式</Badge>}
          />
          {sectionErrors.docs && !typeRows.length ? (
            <Alert tone="warning">
              <div className="v3-ops-inline">
                <span>文档列表不可用：{sectionErrors.docs}</span>
                <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
              </div>
            </Alert>
          ) : typeRows.length === 0 ? (
            <Empty
              icon={<FileText size={24} />}
              title="暂无文档"
              text="先上传 PDF / Word / 文本，解析完成后这里会按格式汇总。"
              action={<Button size="sm" variant="outline" onClick={openFilePicker}>上传文档</Button>}
            />
          ) : (
            <div className="v3-table-wrap">
              <table className="v3-table v3-kbi-type-table">
                <thead>
                  <tr>
                    <th>格式</th>
                    <th className="v3-kbi-hide-sm">说明</th>
                    <th>文档数</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {typeRows.map((row) => (
                    <tr key={row.type}>
                      <td>
                        <div className="v3-kbi-type-name">
                          <span>{extOf(`x.${row.type}`)}</span>
                          <b>{row.label}</b>
                        </div>
                      </td>
                      <td className="v3-kbi-hide-sm v3-ops-muted">{row.desc}</td>
                      <td className="v3-ops-mono">{fmtCount(row.count)}</td>
                      <td>
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Sparkles size={14} />}
                          disabled={!row.count || uploading}
                          onClick={() => openScan(null, row.type, row.label)}
                        >
                          扫描识别
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* 学科分布 */}
        <Card>
          <CardHead
            icon={<Tag size={17} />}
            title="按学科分布"
            sub="按文档 subject 字段真实汇总"
            actions={<Badge tone="outline">{subjectRows.length} 个学科</Badge>}
          />
          {subjectRows.length ? (
            <div className="v3-kbi-subject-bars">
              {subjectRows.map((row) => {
                const max = subjectRows[0]?.count || 1
                return (
                  <div className="v3-kbi-subject-bar" key={row.subject}>
                    <div className="v3-kbi-subject-bar__top">
                      <span title={row.subject}>{row.subject}</span>
                      <b>{fmtCount(row.count)}</b>
                    </div>
                    <div className="v3-kbi-subject-bar__track">
                      <span style={{ width: `${Math.max(3, Math.round(row.count / max * 100))}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <Empty
              icon={<BookOpen size={24} />}
              title="暂无学科分类"
              text="导入文档后，系统会按文档所属学科自动汇总到这里。"
            />
          )}
        </Card>
      </div>

      {/* 最近文档：真实文档列表，兼作导入历史 */}
      <Card>
        <CardHead
          icon={<FileText size={17} />}
          title="最近文档"
          sub={`按创建时间倒序展示最近 ${recentDocs.length} 篇 · 文档总数 ${fmtCount(stats?.totalDocs)}`}
          actions={(
            <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} loading={refreshing} onClick={manualRefresh}>
              刷新
            </Button>
          )}
        />
        {sectionErrors.docs && !docs.length ? (
          <Alert tone="warning">
            <div className="v3-ops-inline">
              <span>文档列表不可用：{sectionErrors.docs}</span>
              <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
            </div>
          </Alert>
        ) : recentDocs.length === 0 ? (
          <Empty
            icon={<FolderOpen size={26} />}
            title="知识库还没有文档"
            text="上传资料并等待解析完成后，最近文档会显示在这里。"
            action={<Button size="sm" variant="filled" icon={<Upload size={14} />} onClick={openFilePicker}>上传第一篇文档</Button>}
          />
        ) : (
          <div className="v3-table-wrap">
            <table className="v3-table v3-kbi-doc-table">
              <thead>
                <tr>
                  <th>文件</th>
                  <th className="v3-kbi-hide-sm">学科</th>
                  <th>状态</th>
                  <th className="v3-kbi-hide-sm">大小</th>
                  <th className="v3-kbi-hide-md">导入时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {recentDocs.map((doc) => {
                  const idx = INDEX_META[doc.index_status] || {
                    label: doc.index_status || '未知', tone: 'outline',
                  }
                  return (
                    <tr key={doc.id}>
                      <td>
                        <div className="v3-kbi-doc-name">
                          <span className="v3-kbi-file__ext">{extOf(doc.file_name)}</span>
                          <div>
                            <b title={doc.file_name}>{doc.file_name}</b>
                            <span>{typeMeta(doc.file_type || doc.doc_type).label}</span>
                          </div>
                        </div>
                      </td>
                      <td className="v3-kbi-hide-sm">{doc.subject || '未分类'}</td>
                      <td><Badge tone={idx.tone}>{idx.label}</Badge></td>
                      <td className="v3-kbi-hide-sm v3-ops-mono">{fmtBytes(doc.size)}</td>
                      <td className="v3-kbi-hide-md v3-ops-mono">{fmtDateTime(doc.created_at)}</td>
                      <td>
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Sparkles size={14} />}
                          disabled={uploading}
                          onClick={() => openScan([doc.id], null, doc.file_name)}
                        >
                          识别题目
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {sectionErrors.docs && docs.length > 0 && (
          <div className="v3-ops-caption v3-kbi-doc-warn">
            本次刷新文档列表失败：{sectionErrors.docs}。上表为上一次成功读取的数据。
          </div>
        )}
      </Card>

      {/* 导入流程 */}
      <Card>
        <CardHead icon={<InfoCircle size={17} />} title="导入流程与操作边界" />
        <div className="v3-kbi-flow">
          <div>
            <span>01</span>
            <b>上传并解析</b>
            <p>上传资料后，后端自动解析正文、分块并建立向量索引；解析状态逐条回传。</p>
          </div>
          <div>
            <span>02</span>
            <b>只读扫描</b>
            <p>在「按文件类型导入」或最近文档中触发扫描，页面直接弹出候选题目；已存在的题自动置灰。</p>
          </div>
          <div>
            <span>03</span>
            <b>确认入库</b>
            <p>勾选新题并确认后，才写入题库，来源标记为「知识库:文档名」；全库扫描较慢，建议按类型分批。</p>
          </div>
        </div>
        <Alert tone="info" icon={<InfoCircle size={17} />} className="v3-kbi-flow__note">
          注意：扫描操作只读不写；只有确认入库才会写入题库。上传时同名同大小的文件会自动跳过，避免重复导入。
        </Alert>
      </Card>

      {scan && (
        <KbScanDialog
          key={scan.key}
          docIds={scan.docIds}
          fileType={scan.fileType}
          scopeLabel={scan.scopeLabel}
          onClose={() => setScan(null)}
          onImported={() => loadStats({ quiet: true })}
        />
      )}
    </div>
  )
}
