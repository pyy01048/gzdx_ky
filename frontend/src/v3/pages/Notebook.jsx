import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import useStore from '../../store/useStore'
import { errorsApi, flashcardsApi, taxonomyApi, fetchAllPages } from '../../api/client'
import { fmtDateCN, todayStr, addDays } from '../../utils/date'
import { isNumericId, toApiId } from '../../utils/id'
import { fileToCompressedDataUrl, dataUrlToFile } from '../../utils/image'
import { chatCompletion, defaultProvider, recordUsage } from '../../utils/api'
import MathText from '../../components/MathText'
import {
  Alert, AnimatedNumber, Badge, Button, Chip, Dialog, Field, IconButton, Input,
  Kbd, Menu, MenuItem, PageHeader, Progress, Segmented, Select, Skeleton, Spinner,
  Tabs, Textarea, Tile, cx, toast, toastErr, toastOk, toastWarn, useConfirm,
} from '../ui'
import {
  AlertCircle, Camera, CheckCircle, ChevronLeft, ChevronRight, Download, Edit,
  FileText, Flame, GraduationCap, Hash, Image, Layers, LayoutGrid, List,
  MoreVertical, NotebookPen, PlayCircle, Plus, RefreshCw, Search, Send, Tag,
  Trash, Upload, Wand,
} from '../icons'
import '../styles/review-pages.css'
import '../styles/study-glass.css'

/* 今日到期判定：active 且已排期且 next_review ≤ 今天（与后端 due 口径一致）。 */
function isDueToday(n, today) {
  if (n.status !== 'active') return false
  const nr = n.nextReview || n.next_review
  if (!nr) return false
  return String(nr).slice(0, 10) <= today
}

/* 四档评分 → 下次复习间隔（天）：忘记=今天重学 / 模糊=1 天 / 记得=3 天 / 简单=7 天。 */
const GRADE_INTERVAL_DAYS = { 1: 0, 2: 1, 3: 3, 4: 7 }

const SUBJECT_CODE_MAP = { math: '数学', english: '英语', politics: '政治', major: '专业课' }
const subjectName = (s) => SUBJECT_CODE_MAP[s] || s || '未分类'

const MASTERY_FALLBACK_LABEL = { unlearned: '未学', weak: '薄弱', mastered: '已掌握' }
const MASTERY_TONE = { unlearned: 'outline', weak: 'warning', mastered: 'success' }

const EMPTY_FORM = { question: '', answer: '', analysis: '', reason: '', subject: '', tags: '' }

function parseTags(t) {
  if (Array.isArray(t)) return t.filter(Boolean).map(String)
  if (typeof t === 'string') {
    try {
      const parsed = JSON.parse(t || '[]')
      return Array.isArray(parsed) ? parsed.filter(Boolean).map(String) : []
    } catch {
      return []
    }
  }
  return []
}

function mapError(e) {
  return {
    id: String(e.id),
    subject: e.subject || '',
    question: e.content || '',
    answer: e.correct_answer || '',
    myAnswer: e.my_answer || '',
    analysis: e.analysis || '',
    reason: e.error_reason || '',
    status: e.status || 'active',
    masteryState: e.mastery_state || 'unlearned',
    masteryLabel: e.mastery_label || MASTERY_FALLBACK_LABEL[e.mastery_state] || '未学',
    accuracy: Number(e.accuracy) || 0,
    tags: parseTags(e.tags),
    reviewCount: e.review_count || 0,
    lastReview: e.last_review,
    nextReview: e.next_review,
    createdAt: e.created_at,
  }
}

/* 后端字段 → 页面视图字段（离线/本地条目同样可用）。 */
const UI_PATCH_MAP = {
  content: 'question',
  correct_answer: 'answer',
  my_answer: 'myAnswer',
  error_reason: 'reason',
  analysis: 'analysis',
  subject: 'subject',
  review_count: 'reviewCount',
  last_review: 'lastReview',
  next_review: 'nextReview',
  status: 'status',
  tags: 'tags',
}

function toUiPatch(patch) {
  const out = {}
  Object.entries(patch || {}).forEach(([k, v]) => {
    const key = UI_PATCH_MAP[k] || k
    out[key] = key === 'tags' ? parseTags(v) : v
  })
  return out
}

/* 后端没有返回相似题时，用当前错题生成「复盘思路提示」（明确标注本地生成，不冒充题库数据）。 */
function genSimilar(n) {
  const q = (n.question || '').slice(0, 18)
  return [
    { title: `变式训练：${q}…（同考点不同条件）`, kind: '同考点' },
    { title: `思路复述：请口述 ${q}… 的解题步骤`, kind: '思路' },
    { title: `拓展迁移：将本题结论推广到一般情形并证明`, kind: '拓展' },
  ]
}

function MasteryBadge({ state, label }) {
  const s = state || 'unlearned'
  return (
    <Badge tone={MASTERY_TONE[s] || 'outline'}>
      {label || MASTERY_FALLBACK_LABEL[s] || '未学'}
    </Badge>
  )
}

function StatusBadge({ item, today }) {
  if (item.status === 'graduated') return <Badge tone="success">已毕业</Badge>
  if (item.status === 'archived') return <Badge tone="outline">已归档</Badge>
  if (isDueToday(item, today)) return <Badge tone="warning">待复习</Badge>
  return <Badge tone="primary">复习中</Badge>
}

/* 卡片上的更多操作（菜单挂在按钮上方，避免卡片内嵌套可点击区域）。 */
function CardMenu({ n, aiBusy, aiBusyId, onAi, onCard, onGraduate, onEdit, onRemove }) {
  const [open, setOpen] = useState(false)
  const anchorRef = useRef(null)
  const run = (fn) => () => {
    setOpen(false)
    fn()
  }
  const itemStyle = { minHeight: 'var(--v3-touch)' }
  return (
    <>
      <span ref={anchorRef} className="v3-nb-card__more">
        <IconButton
          label="更多操作"
          icon={<MoreVertical size={18} />}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        />
      </span>
      <Menu open={open} anchorRef={anchorRef} onClose={() => setOpen(false)} width={196}>
        <MenuItem icon={<Edit size={16} />} style={itemStyle} onClick={run(onEdit)}>编辑错题</MenuItem>
        <MenuItem
          icon={aiBusy && aiBusyId === n.id ? <Spinner size={16} /> : <Wand size={16} />}
          style={itemStyle}
          disabled={aiBusy}
          onClick={run(onAi)}
        >
          {aiBusy && aiBusyId === n.id ? 'AI 分析中…' : 'AI 深度分析'}
        </MenuItem>
        <MenuItem icon={<Layers size={16} />} style={itemStyle} onClick={run(onCard)}>转记忆卡片</MenuItem>
        <MenuItem icon={<GraduationCap size={16} />} style={itemStyle} onClick={run(onGraduate)}>标记毕业</MenuItem>
        <MenuItem
          icon={<Trash size={16} />}
          style={{ ...itemStyle, color: 'var(--v3-danger)' }}
          onClick={run(onRemove)}
        >
          删除错题
        </MenuItem>
      </Menu>
    </>
  )
}

export default function Notebook() {
  const notebook = useStore((s) => s.notebook)
  const packs = useStore((s) => s.packs)

  const [backendOk, setBackendOk] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [stats, setStats] = useState(null)
  const [statsErr, setStatsErr] = useState('')
  const [subjectOptions, setSubjectOptions] = useState([])

  const [filter, setFilter] = useState('all')
  const [subject, setSubject] = useState('all')
  const [q, setQ] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [viewMode, setViewMode] = useState('grid')

  const [selectedIds, setSelectedIds] = useState([])
  const [confirm, confirmDialog] = useConfirm()

  const [showAdd, setShowAdd] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formTab, setFormTab] = useState('edit')
  const [submitting, setSubmitting] = useState(false)
  const [ocrBusy, setOcrBusy] = useState(false)

  const [showOcrBatch, setShowOcrBatch] = useState(false)
  const [ocrBatchBusy, setOcrBatchBusy] = useState(false)
  const [ocrProgress, setOcrProgress] = useState(0)

  const [showDetail, setShowDetail] = useState(null)
  const [detailShowAnswer, setDetailShowAnswer] = useState(false)
  const [similarMap, setSimilarMap] = useState({})
  const [aiMetaMap, setAiMetaMap] = useState({})
  const [aiBusy, setAiBusy] = useState(false)
  const [aiBusyId, setAiBusyId] = useState(null)
  const [aiFollowup, setAiFollowup] = useState({ input: '', busy: false, history: [] })

  const [reviewMode, setReviewMode] = useState(false)
  const [reviewQueue, setReviewQueue] = useState([])
  const [reviewIdx, setReviewIdx] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [reviewStats, setReviewStats] = useState({ again: 0, hard: 0, good: 0, easy: 0, startTime: null })
  const [reviewSummary, setReviewSummary] = useState(null)
  const [grading, setGrading] = useState(false)

  const ocrRef = useRef(null)
  const captureRef = useRef(null)
  const ocrBatchRef = useRef(null)
  const today = todayStr()

  const refresh = useCallback(async () => {
    setLoading(true)
    let listErrMsg = ''
    try {
      const list = await fetchAllPages((p) => errorsApi.list(p), { keys: ['errors'] })
      useStore.setState({ notebook: list.map(mapError) })
      setBackendOk(true)
      setLoadErr('')
    } catch (e) {
      setBackendOk(false)
      listErrMsg = e?.message || '错题列表接口不可用'
      setLoadErr(listErrMsg)
    }
    try {
      const d = await errorsApi.stats()
      setStats(d && typeof d === 'object' ? d : null)
      setStatsErr(d ? '' : '统计接口返回空数据')
    } catch (e) {
      setStats(null)
      setStatsErr(e?.message || '统计接口不可用')
    }
    setLoading(false)
    return !listErrMsg
  }, [])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const r = await taxonomyApi.subjects()
        const items = Array.isArray(r) ? r : (r && (r.subjects || r.items)) || []
        const withErrors = items
          .filter((x) => Number(x.error_count || 0) > 0)
          .map((x) => x.subject)
          .filter(Boolean)
        if (alive) setSubjectOptions(withErrors)
      } catch {
        if (alive) setSubjectOptions([])
      }
    })()
    return () => { alive = false }
  }, [])

  const allSubjects = useMemo(() => {
    const set = new Set(subjectOptions)
    notebook.forEach((n) => { if (n.subject) set.add(n.subject) })
    return Array.from(set)
  }, [subjectOptions, notebook])

  const tagCounts = useMemo(() => {
    const map = new Map()
    notebook.forEach((n) => {
      (n.tags || []).forEach((t) => map.set(t, (map.get(t) || 0) + 1))
    })
    return Array.from(map.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-Hans-CN'))
  }, [notebook])

  useEffect(() => {
    if (tagFilter && !tagCounts.some((t) => t.name === tagFilter)) setTagFilter('')
  }, [tagCounts, tagFilter])

  const list = useMemo(() => {
    let arr = notebook
    if (filter === 'active') arr = arr.filter((n) => n.status !== 'graduated')
    if (filter === 'graduated') arr = arr.filter((n) => n.status === 'graduated')
    if (subject !== 'all') arr = arr.filter((n) => n.subject === subject)
    if (tagFilter) arr = arr.filter((n) => (n.tags || []).includes(tagFilter))
    const needle = q.trim().toLowerCase()
    if (needle) {
      arr = arr.filter((n) => `${n.question}\n${n.answer}\n${(n.tags || []).join(',')}`.toLowerCase().includes(needle))
    }
    return arr
  }, [notebook, filter, subject, tagFilter, q])

  const counts = useMemo(() => {
    if (stats) {
      const active = Number(stats.active_errors || 0)
      const due = Number(stats.due_errors || 0)
      const graduated = Number(stats.graduated_errors || 0)
      const total = Number(stats.total || 0)
      return { total, due, reviewing: Math.max(0, active - due), mastered: graduated }
    }
    return {
      total: notebook.length,
      due: notebook.filter((n) => isDueToday(n, today)).length,
      reviewing: notebook.filter((n) => n.status === 'active' && (n.reviewCount || 0) > 0).length,
      mastered: notebook.filter((n) => n.status === 'graduated').length,
    }
  }, [stats, notebook, today])

  const weekNew = useMemo(() => {
    const since = addDays(today, -6)
    return notebook.filter((n) => {
      const day = String(n.createdAt || '').slice(0, 10)
      return /^\d{4}-\d{2}-\d{2}$/.test(day) && day >= since && day <= today
    }).length
  }, [notebook, today])

  const todayReviews = stats && stats.today_reviews != null ? Number(stats.today_reviews) : null
  const initialLoading = loading && notebook.length === 0
  const hasFilters = filter !== 'all' || subject !== 'all' || Boolean(q.trim()) || Boolean(tagFilter)
  const activeReview = reviewMode && reviewQueue.length > 0 ? reviewQueue[reviewIdx] : null

  const liveDetail = showDetail
    ? (notebook.find((n) => String(n.id) === String(showDetail.id)) || showDetail)
    : null

  const resetFilters = () => {
    setFilter('all')
    setSubject('all')
    setQ('')
    setTagFilter('')
  }

  const toggleSelect = (id) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  /* 统一本地改写的字段映射；云端同步失败时仍更新本地视图（并在显式操作时提示）。 */
  const patchError = async (id, patch, { notify = false } = {}) => {
    let syncErr = null
    if (backendOk && isNumericId(id)) {
      try {
        await errorsApi.update(Number(id), patch)
      } catch (e) {
        syncErr = e
      }
    }
    const uiPatch = toUiPatch(patch)
    useStore.setState({
      notebook: useStore.getState().notebook.map((n) => (String(n.id) === String(id) ? { ...n, ...uiPatch } : n)),
    })
    setShowDetail((prev) => (prev && String(prev.id) === String(id) ? { ...prev, ...uiPatch } : prev))
    if (syncErr && notify) toastErr(`云端同步失败：${syncErr.message || '未知错误'}`)
    return !syncErr
  }

  const openAdd = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormTab('edit')
    setShowAdd(true)
  }

  const beginEdit = (n) => {
    setShowDetail(null)
    setAiFollowup({ input: '', busy: false, history: [] })
    setEditingId(n.id)
    setForm({
      question: n.question || '',
      answer: n.answer || '',
      analysis: n.analysis || '',
      reason: n.reason || '',
      subject: n.subject || '',
      tags: (n.tags || []).join(', '),
    })
    setFormTab('edit')
    setShowAdd(true)
  }

  const submit = async () => {
    if (submitting) return
    if (!form.question.trim() || !form.answer.trim()) return toastWarn('请填写题干与答案')
    if (!form.subject.trim()) return toastWarn('请填写科目')
    const tags = form.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
    const body = {
      content: form.question.trim(),
      correct_answer: form.answer.trim(),
      analysis: form.analysis.trim() || null,
      error_reason: form.reason.trim() || null,
      subject: form.subject.trim(),
      tags,
    }
    setSubmitting(true)
    try {
      if (!backendOk) {
        if (editingId != null) {
          useStore.setState({
            notebook: useStore.getState().notebook.map((n) => (
              String(n.id) === String(editingId)
                ? { ...n, ...toUiPatch(body) }
                : n
            )),
          })
          setShowDetail((prev) => (prev && String(prev.id) === String(editingId) ? { ...prev, ...toUiPatch(body) } : prev))
          toastOk('错题已更新（本地模式）')
        } else {
          const local = {
            id: `n${Date.now()}`,
            question: body.content,
            answer: body.correct_answer,
            myAnswer: '',
            analysis: body.analysis || '',
            reason: body.error_reason || '',
            subject: body.subject,
            tags,
            status: 'active',
            reviewCount: 0,
            accuracy: 0,
            lastReview: null,
            nextReview: addDays(today, 1),
            createdAt: today,
          }
          useStore.setState({ notebook: [local, ...useStore.getState().notebook] })
          toastOk('错题已收录（本地模式）')
        }
      } else if (editingId != null && isNumericId(editingId)) {
        await errorsApi.update(Number(editingId), body)
        await refresh()
        toastOk('错题已更新')
      } else if (editingId != null) {
        useStore.setState({
          notebook: useStore.getState().notebook.map((n) => (
            String(n.id) === String(editingId) ? { ...n, ...toUiPatch(body) } : n
          )),
        })
        toastOk('错题已更新（本地条目）')
      } else {
        await errorsApi.create(body)
        await refresh()
        toastOk('错题已收录，按艾宾浩斯排入复习')
      }
      setShowAdd(false)
      setEditingId(null)
      setForm(EMPTY_FORM)
    } catch (e) {
      toastErr(`保存失败：${e?.message || '未知错误'}`)
    } finally {
      setSubmitting(false)
    }
  }

  const reviewFlow = async (id, correct) => {
    const current = notebook.find((n) => String(n.id) === String(id))
    if (!current) return
    const patch = correct
      ? {
        status: 'graduated',
        review_count: (current.reviewCount || 0) + 1,
        last_review: today,
      }
      : {
        status: 'active',
        review_count: current.reviewCount || 0,
        last_review: today,
        next_review: addDays(today, 1),
      }
    await patchError(id, patch, { notify: true })
    if (backendOk) await refresh()
    toastOk(correct ? '已标记答对，错题毕业' : '已记录答错，明天再复习')
  }

  const startReview = () => {
    const dueList = notebook.filter((n) => isDueToday(n, today))
    if (dueList.length === 0) return toastWarn('今日没有待复习的错题')
    setReviewQueue(dueList)
    setReviewIdx(0)
    setShowAnswer(false)
    setReviewSummary(null)
    setReviewStats({ again: 0, hard: 0, good: 0, easy: 0, startTime: Date.now() })
    setReviewMode(true)
    setFilter('active')
  }

  const exitReview = () => {
    setReviewMode(false)
    setReviewQueue([])
    setReviewIdx(0)
    setShowAnswer(false)
    setGrading(false)
  }

  const reviewWithGrade = async (grade) => {
    if (grading) return
    const current = reviewQueue[reviewIdx]
    if (!current || GRADE_INTERVAL_DAYS[grade] === undefined) return
    const gradeKey = grade === 1 ? 'again' : grade === 2 ? 'hard' : grade === 3 ? 'good' : 'easy'
    const nextStats = { ...reviewStats, [gradeKey]: (reviewStats[gradeKey] || 0) + 1 }
    setGrading(true)
    setReviewStats(nextStats)
    const newReviewCount = (current.reviewCount || 0) + (grade >= 3 ? 1 : 0)
    const newStatus = grade === 4 && newReviewCount >= 4 ? 'graduated' : 'active'
    const nextReview = addDays(today, GRADE_INTERVAL_DAYS[grade])
    await patchError(current.id, {
      review_count: newReviewCount,
      status: newStatus,
      last_review: today,
      next_review: nextReview,
    })
    setShowAnswer(false)
    if (reviewIdx + 1 < reviewQueue.length) {
      setReviewIdx(reviewIdx + 1)
      setGrading(false)
    } else {
      setReviewMode(false)
      setReviewSummary({ ...nextStats, total: reviewQueue.length })
      setGrading(false)
      toastOk(`复习完成！共 ${reviewQueue.length} 道题`)
      refresh()
    }
  }

  useEffect(() => {
    if (!reviewMode || !showAnswer) return undefined
    const onKey = (e) => {
      const tag = (e.target?.tagName || '').toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target?.isContentEditable) return
      if (!['1', '2', '3', '4'].includes(e.key)) return
      e.preventDefault()
      reviewWithGrade(Number(e.key))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [reviewMode, showAnswer, reviewIdx, reviewQueue, reviewStats, grading])

  const graduate = async (id) => {
    if (backendOk && isNumericId(id)) {
      try {
        await errorsApi.update(Number(id), { status: 'graduated' })
        await refresh()
        toastOk('已标记毕业')
      } catch (e) {
        toastErr(`操作失败：${e?.message || '未知错误'}`)
      }
    } else {
      await patchError(id, { status: 'graduated' })
      toastOk('已标记毕业')
    }
  }

  const remove = async (id) => {
    const target = notebook.find((n) => String(n.id) === String(id))
    const ok = await confirm({
      title: '删除错题',
      message: `将删除「${(target?.question || '这道错题').slice(0, 40)}${(target?.question || '').length > 40 ? '…' : ''}」，此操作不可恢复。`,
      danger: true,
    })
    if (!ok) return
    if (backendOk && isNumericId(id)) {
      try {
        await errorsApi.remove(Number(id))
        await refresh()
        toastOk('已删除')
      } catch (e) {
        toastErr(`删除失败：${e?.message || '未知错误'}`)
        return
      }
    } else {
      useStore.setState({ notebook: useStore.getState().notebook.filter((n) => String(n.id) !== String(id)) })
      toastOk('已删除')
    }
    setSelectedIds((prev) => prev.filter((x) => String(x) !== String(id)))
    setShowDetail((prev) => (prev && String(prev.id) === String(id) ? null : prev))
  }

  const batchRemove = async () => {
    if (selectedIds.length === 0) return
    const ok = await confirm({
      title: '批量删除错题',
      message: `将删除选中的 ${selectedIds.length} 道错题，此操作不可恢复。`,
      danger: true,
    })
    if (!ok) return
    const localIds = selectedIds.filter((x) => !isNumericId(x))
    const backendIds = selectedIds.filter((x) => isNumericId(x)).map(Number)
    if (backendIds.length && !backendOk) {
      toastErr('后端未连接，无法删除云端错题')
      return
    }
    if (backendIds.length) {
      try {
        await errorsApi.batchDelete(backendIds)
        toastOk(`已删除 ${backendIds.length} 道错题`)
      } catch (e) {
        toastErr(`删除失败：${e?.message || '未知错误'}`)
        return
      }
    }
    if (localIds.length) {
      useStore.setState({
        notebook: useStore.getState().notebook.filter((n) => !localIds.includes(n.id)),
      })
    }
    setSelectedIds([])
    setShowDetail(null)
    if (backendOk) await refresh()
  }

  const exportCsv = async () => {
    const numericIds = selectedIds.filter((x) => isNumericId(x)).map(Number)
    if (selectedIds.length > 0 && numericIds.length === 0) {
      return toastErr('选中的错题尚未同步到云端，无法导出')
    }
    try {
      await errorsApi.exportCsv({
        ids: numericIds.length ? numericIds : undefined,
        subject: subject !== 'all' ? subject : undefined,
        status: filter !== 'all' ? filter : undefined,
      })
      toastOk(numericIds.length ? `已导出 ${numericIds.length} 道错题` : '已按当前筛选导出')
    } catch (e) {
      toastErr(`导出失败：${e?.message || '未知错误'}`)
    }
  }

  const aiAnalyze = async (n) => {
    if (!n) return
    if (!backendOk) {
      toastWarn('AI 分析需连接后端；已展示本地复盘思路')
      return
    }
    if (!isNumericId(n.id)) {
      toastWarn('该错题尚未同步到云端，暂不能做 AI 分析')
      return
    }
    setAiBusy(true)
    setAiBusyId(n.id)
    try {
      const r = await errorsApi.aiAnalyze(toApiId(n.id))
      const analysis = typeof r === 'string' ? r : (r?.analysis || '')
      if (analysis) {
        useStore.setState({
          notebook: useStore.getState().notebook.map((x) => (
            String(x.id) === String(n.id) ? { ...x, analysis } : x
          )),
        })
        setShowDetail((prev) => (prev && String(prev.id) === String(n.id) ? { ...prev, analysis } : prev))
      }
      const practice = Array.isArray(r?.practice_questions) ? r.practice_questions : []
      setSimilarMap((m) => ({ ...m, [n.id]: practice }))
      setAiMetaMap((m) => ({
        ...m,
        [n.id]: {
          category: r?.category || '',
          knowledgePoint: r?.knowledge_point || '',
          suggestion: r?.suggestion || '',
        },
      }))
      toastOk('AI 分析完成')
    } catch (e) {
      toastErr(`AI 分析失败：${e?.message || '未知错误'}`)
    } finally {
      setAiBusy(false)
      setAiBusyId(null)
    }
  }

  const runFollowup = async (n) => {
    const text = aiFollowup.input.trim()
    if (!n || !text || aiFollowup.busy) return
    const provider = defaultProvider()
    if (!provider) return toastWarn('请先在设置中配置 AI 服务')
    setAiFollowup((s) => ({ ...s, busy: true }))
    const context = [
      `错题题干：${n.question}`,
      n.answer ? `正确答案：${n.answer}` : '',
      n.analysis ? `已有解析：${n.analysis}` : '',
      n.reason ? `失分原因：${n.reason}` : '',
    ].filter(Boolean).join('\n')
    const messages = [
      { role: 'system', content: '你是考研辅导老师，针对学生的错题进行追问答疑，简洁、分点。' },
      ...aiFollowup.history
        .flatMap((h) => [{ role: 'user', content: h.q }, { role: 'assistant', content: h.a }]),
      { role: 'user', content: `${context}\n\n学生追问：${text}` },
    ]
    setAiFollowup((s) => ({ ...s, input: '', history: [...s.history, { q: text, a: '' }] }))
    try {
      const r = await chatCompletion(provider, messages)
      recordUsage(r.usage, provider.id)
      setAiFollowup((s) => {
        const h = [...s.history]
        h[h.length - 1] = { q: text, a: r.text || '（AI 未返回内容）' }
        return { ...s, busy: false, history: h }
      })
    } catch (e) {
      setAiFollowup((s) => {
        const h = [...s.history]
        h[h.length - 1] = { q: text, a: `追问失败：${e?.message || '未知错误'}` }
        return { ...s, busy: false, history: h }
      })
    }
  }

  const toCard = async (n) => {
    if (!n) return
    const body = {
      front: n.question,
      back: n.answer,
      hint: n.analysis || n.reason || '',
      subject: n.subject,
      knowledge_point_id: null,
    }
    if (backendOk) {
      try {
        await flashcardsApi.create(body)
        toastOk('已生成记忆卡片')
      } catch (e) {
        toastErr(`转卡失败：${e?.message || '未知错误'}`)
      }
    } else {
      if (!packs.length) return toastWarn('请先在「记忆卡片」页创建卡包')
      useStore.getState().addCard({ ...body, packId: packs[0].id })
      toastOk('已生成记忆卡片')
    }
  }

  const ocrUpload = async (file) => {
    if (!file) return
    if (!backendOk) {
      if (captureRef.current) captureRef.current.value = ''
      if (ocrRef.current) ocrRef.current.value = ''
      return toastWarn('需先连接后端才能使用 OCR')
    }
    setOcrBusy(true)
    try {
      let upload = file
      try {
        const { dataUrl } = await fileToCompressedDataUrl(file, { maxSide: 1800, quality: 0.85 })
        upload = dataUrlToFile(dataUrl, (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg')
      } catch (e) {
        toastErr(e.message)
        return
      }
      const fd = new FormData()
      fd.append('file', upload)
      const r = await errorsApi.ocr(fd)
      if (r.raw_text) {
        setEditingId(null)
        setForm((f) => ({ ...f, question: r.raw_text.slice(0, 800) }))
        setFormTab('edit')
        setShowAdd(true)
        toastOk(`OCR 识别成功（识别到 ${r.count || 0} 道题），请核对收录`)
      } else {
        toastWarn('OCR 未识别到内容')
      }
    } catch (e) {
      toastErr(`OCR 失败：${e?.message || '未知错误'}`)
    } finally {
      setOcrBusy(false)
      if (captureRef.current) captureRef.current.value = ''
      if (ocrRef.current) ocrRef.current.value = ''
    }
  }

  const applyOcrBatch = async (files) => {
    if (!backendOk) return toastWarn('需先连接后端才能使用批量 OCR')
    if (!files || !files.length) return
    const targets = [...selectedIds]
    setOcrBatchBusy(true)
    setOcrProgress(0)
    try {
      for (let i = 0; i < files.length && i < targets.length; i += 1) {
        const fd = new FormData()
        fd.append('file', files[i])
        const r = await errorsApi.ocr(fd)
        const text = (r.raw_text || '').slice(0, 800)
        setOcrProgress(i + 1)
        const id = targets[i]
        if (id != null && text) {
          const item = useStore.getState().notebook.find((x) => String(x.id) === String(id))
          if (item) {
            const merged = (item.question ? `${item.question}\n` : '') + text
            await patchError(id, { content: merged })
          }
        }
      }
      toastOk(`批量识别完成（${Math.min(files.length, targets.length)} 张图片）`)
    } catch (e) {
      toastErr(`批量 OCR 失败：${e?.message || '未知错误'}`)
    } finally {
      setOcrBatchBusy(false)
      setSelectedIds([])
      setShowOcrBatch(false)
      if (backendOk) refresh()
    }
  }

  const openDetail = (n) => {
    setShowDetail(n)
    setDetailShowAnswer(false)
    setAiFollowup({ input: '', busy: false, history: [] })
  }

  const goDetail = (delta) => {
    if (!liveDetail) return
    const idx = list.findIndex((n) => String(n.id) === String(liveDetail.id))
    if (idx < 0) return
    const next = list[idx + delta]
    if (!next) return
    setShowDetail(next)
    setDetailShowAnswer(false)
    setAiFollowup({ input: '', busy: false, history: [] })
  }

  const detailIdx = liveDetail ? list.findIndex((n) => String(n.id) === String(liveDetail.id)) : -1

  const resetSummary = () => {
    setReviewSummary(null)
    setReviewQueue([])
    setReviewIdx(0)
    setShowAnswer(false)
  }

  return (
    <div className="v3-stack v3-nb v3-glasspage">
      <PageHeader
        eyebrow="错题本 · 收录与艾宾浩斯复习"
        title={(
          <span className="v3-nb-title">
            <NotebookPen size={26} />
            错题本
          </span>
        )}
        sub={(
          <span className="v3-nb-sub">
            {backendOk ? '云端已连接' : '本地模式'} · 今日 {counts.due} 道到期 · 共 {counts.total} 道错题
          </span>
        )}
        actions={(
          <>
            <Button
              variant="filled"
              icon={<Camera size={16} />}
              loading={ocrBusy}
              disabled={ocrBusy}
              onClick={() => captureRef.current?.click()}
            >
              {ocrBusy ? '识别中…' : '拍照收录'}
            </Button>
            <Button
              variant="outline"
              icon={<Upload size={16} />}
              disabled={ocrBusy}
              onClick={() => ocrRef.current?.click()}
            >
              相册上传
            </Button>
            <Button variant="tonal" icon={<Plus size={16} />} onClick={openAdd}>手动录入</Button>
            <Button variant="ghost" icon={<Download size={16} />} onClick={exportCsv}>导出</Button>
            <IconButton
              label="刷新错题本"
              icon={<RefreshCw size={17} />}
              onClick={refresh}
              disabled={loading}
            />
            <input
              ref={captureRef}
              type="file"
              accept="image/*"
              capture="environment"
              aria-label="拍照上传错题图片"
              className="v3-nb-file"
              onChange={(e) => ocrUpload(e.target.files?.[0])}
            />
            <input
              ref={ocrRef}
              type="file"
              accept="image/*"
              aria-label="从相册选择错题图片"
              className="v3-nb-file"
              onChange={(e) => ocrUpload(e.target.files?.[0])}
            />
          </>
        )}
      />

      <nav className="v3-rp-domain" aria-label="错题域导航">
        <Link to="/error-review" className="v3-rp-domain__link">错题分析</Link>
        <Link to="/notebook" className="v3-rp-domain__link is-active" aria-current="page">错题本</Link>
        <Link to="/quiz?tab=review" className="v3-rp-domain__link">快速重练</Link>
      </nav>

      {!loading && !backendOk && (
        <Alert tone="warning" className="v3-rp-alert">
          <div className="v3-rp-alert__body">
            <span>
              未连接后端{loadErr ? `：${loadErr}` : ''}。当前展示本机缓存的错题，新增与编辑会先保存在本机。
            </span>
            <Button variant="text" size="sm" onClick={refresh}>重试连接</Button>
          </div>
        </Alert>
      )}

      {initialLoading ? (
        <>
          <Tile span={12} className="v3-nb-hero v3-nb-hero--loading">
            <Skeleton width={140} height={14} />
            <Skeleton width={180} height={54} />
            <Skeleton width="70%" height={12} />
          </Tile>
          <div className="v3-bento v3-nb-stats">
            {[0, 1, 2, 3].map((i) => (
              <Tile key={i} span={3} className="v3-nb-stat">
                <Skeleton width="55%" height={12} />
                <Skeleton width="45%" height={34} />
              </Tile>
            ))}
          </div>
          <div className="v3-nb-grid" aria-label="正在读取错题">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="v3-card v3-nb-card">
                <Skeleton width="42%" height={12} />
                <Skeleton width="100%" height={48} />
                <Skeleton width="68%" height={12} />
              </div>
            ))}
          </div>
        </>
      ) : (
        <>
          <Tile span={12} variant="hero" className="v3-nb-hero">
            <div className="v3-nb-hero__main">
              <span className="v3-nb-hero__flame" aria-hidden="true"><Flame size={30} /></span>
              <div className="v3-nb-hero__copy">
                <div className="v3-eyebrow">今日复习</div>
                <div className="v3-nb-hero__due">
                  <AnimatedNumber value={counts.due} />
                  <em>道</em>
                </div>
                <div className="v3-caption">按艾宾浩斯曲线自动排入；四档评分会决定下次复习日期。</div>
              </div>
            </div>
            <div className="v3-nb-hero__actions">
              <Button variant="filled" icon={<PlayCircle size={17} />} onClick={startReview}>
                开始今日复习
              </Button>
              <Button variant="tonal" icon={<Plus size={16} />} onClick={openAdd}>收录新错题</Button>
            </div>
            <div className="v3-nb-hero__metrics">
              <div>
                <span>全部错题</span>
                <b>{counts.total}</b>
              </div>
              <div>
                <span>本周新增</span>
                <b>{weekNew}</b>
              </div>
              <div>
                <span>今日已复习</span>
                <b>{todayReviews == null ? '—' : todayReviews}</b>
              </div>
            </div>
          </Tile>

          {statsErr && (
            <Alert tone="warning" className="v3-rp-alert">
              <div className="v3-rp-alert__body">
                <span>统计接口不可用，当前使用本地可见数据统计：{statsErr}</span>
                <Button variant="text" size="sm" onClick={refresh}>重试</Button>
              </div>
            </Alert>
          )}

          <div className="v3-bento v3-nb-stats">
            <Tile span={3} className="v3-nb-stat">
              <span className="v3-tile__label"><FileText size={15} /> 全部错题</span>
              <span className="v3-tile__value"><AnimatedNumber value={counts.total} /></span>
              <span className="v3-tile__hint">错题本总量</span>
            </Tile>
            <Tile span={3} className="v3-nb-stat v3-nb-stat--due">
              <span className="v3-tile__label"><AlertCircle size={15} /> 待复习</span>
              <span className="v3-tile__value"><AnimatedNumber value={counts.due} /></span>
              <span className="v3-tile__hint">今日到期</span>
            </Tile>
            <Tile span={3} className="v3-nb-stat v3-nb-stat--reviewing">
              <span className="v3-tile__label"><RefreshCw size={15} /> 七刷中</span>
              <span className="v3-tile__value"><AnimatedNumber value={counts.reviewing} /></span>
              <span className="v3-tile__hint">活跃但未到期</span>
            </Tile>
            <Tile span={3} className="v3-nb-stat v3-nb-stat--done">
              <span className="v3-tile__label"><CheckCircle size={15} /> 已毕业</span>
              <span className="v3-tile__value"><AnimatedNumber value={counts.mastered} /></span>
              <span className="v3-tile__hint">已移出复习</span>
            </Tile>
          </div>

          {reviewSummary && !reviewMode && (
            <Tile span={12} className="v3-nb-summary">
              <div className="v3-nb-summary__head">
                <span className="v3-nb-summary__icon"><CheckCircle size={30} /></span>
                <div>
                  <div className="v3-h3">本轮复习完成</div>
                  <div className="v3-caption">共复习 {reviewSummary.total || reviewQueue.length} 道错题</div>
                </div>
              </div>
              <div className="v3-nb-summary__grid">
                <div><span>忘记</span><b>{reviewSummary.again}</b></div>
                <div><span>模糊</span><b>{reviewSummary.hard}</b></div>
                <div><span>记得</span><b>{reviewSummary.good}</b></div>
                <div><span>简单</span><b>{reviewSummary.easy}</b></div>
              </div>
              <div className="v3-nb-summary__actions">
                <Button variant="filled" onClick={startReview}>再来一轮</Button>
                <Button variant="outline" onClick={resetSummary}>返回列表</Button>
              </div>
            </Tile>
          )}

          {reviewMode && activeReview && (
            <Tile span={12} className="v3-nb-review">
              <div className="v3-nb-review__head">
                <div className="v3-row">
                  <MasteryBadge state={activeReview.masteryState} label={activeReview.masteryLabel} />
                  <Badge tone="primary">复习模式</Badge>
                  <Badge tone="outline">{subjectName(activeReview.subject)}</Badge>
                </div>
                <div className="v3-row">
                  <span className="v3-caption">{reviewIdx + 1} / {reviewQueue.length}</span>
                  <Button variant="ghost" size="sm" onClick={exitReview}>退出复习</Button>
                </div>
              </div>
              <Progress value={((reviewIdx + 1) / reviewQueue.length) * 100} gradient />
              <div className="v3-nb-review__block">
                <div className="v3-caption">题干</div>
                <MathText className="v3-rp-prose v3-nb-review__question" text={activeReview.question} />
              </div>
              {showAnswer && (
                <>
                  <div className="v3-nb-review__answer">
                    <div className="v3-caption">答案</div>
                    <MathText className="v3-rp-prose" text={activeReview.answer} />
                  </div>
                  {activeReview.analysis && (
                    <div className="v3-nb-review__analysis">
                      <div className="v3-caption">解析</div>
                      <MathText className="v3-rp-prose" text={activeReview.analysis} />
                    </div>
                  )}
                </>
              )}
              {!showAnswer ? (
                <Button variant="filled" block onClick={() => setShowAnswer(true)}>显示答案</Button>
              ) : (
                <>
                  <div className="v3-nb-grades" role="group" aria-label="选择掌握程度">
                    <button type="button" className="v3-nb-grade v3-nb-grade--again" onClick={() => reviewWithGrade(1)} disabled={grading}>
                      <b>忘记</b><small>重新学习</small>
                    </button>
                    <button type="button" className="v3-nb-grade v3-nb-grade--hard" onClick={() => reviewWithGrade(2)} disabled={grading}>
                      <b>模糊</b><small>1 天后复习</small>
                    </button>
                    <button type="button" className="v3-nb-grade v3-nb-grade--good" onClick={() => reviewWithGrade(3)} disabled={grading}>
                      <b>记得</b><small>3 天后复习</small>
                    </button>
                    <button type="button" className="v3-nb-grade v3-nb-grade--easy" onClick={() => reviewWithGrade(4)} disabled={grading}>
                      <b>简单</b><small>7 天后复习</small>
                    </button>
                  </div>
                  <div className="v3-nb-review__keys">
                    快捷键：<Kbd>1</Kbd> 忘记 <Kbd>2</Kbd> 模糊 <Kbd>3</Kbd> 记得 <Kbd>4</Kbd> 简单
                  </div>
                </>
              )}
            </Tile>
          )}

          <div className="v3-toolbar v3-nb-toolbar">
            <Segmented
              ariaLabel="毕业状态筛选"
              options={[
                { label: '全部', value: 'all' },
                { label: '未毕业', value: 'active' },
                { label: '已毕业', value: 'graduated' },
              ]}
              value={filter}
              onChange={setFilter}
            />
            <Select
              className="v3-nb-subject"
              aria-label="按科目过滤"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            >
              <option value="all">全部科目</option>
              {allSubjects.map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
            <Input
              className="v3-nb-search"
              icon={<Search size={16} />}
              aria-label="搜索题干、答案或标签"
              placeholder="搜索题干 / 答案 / 标签"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <span className="v3-toolbar__spacer" />
            <span className="v3-caption">当前 {list.length} 道</span>
            <Segmented
              ariaLabel="切换列表视图"
              options={[
                { label: '列表', value: 'list', icon: <List size={15} /> },
                { label: '卡片', value: 'grid', icon: <LayoutGrid size={15} /> },
              ]}
              value={viewMode}
              onChange={setViewMode}
            />
          </div>

          {tagCounts.length > 0 && (
            <div className="v3-nb-tags" role="group" aria-label="按标签筛选">
              <Chip active={!tagFilter} onClick={() => setTagFilter('')} icon={<Tag size={14} />} aria-pressed={!tagFilter}>
                全部标签
              </Chip>
              {tagCounts.map((t) => (
                <Chip
                  key={t.name}
                  active={tagFilter === t.name}
                  onClick={() => setTagFilter(tagFilter === t.name ? '' : t.name)}
                  aria-pressed={tagFilter === t.name}
                >
                  <Hash size={12} />
                  {t.name}
                  <span className="v3-rp-count">{t.count}</span>
                </Chip>
              ))}
            </div>
          )}

          {selectedIds.length > 0 && (
            <div className="v3-rp-selection">
              <span className="v3-rp-selection__text">已选择 {selectedIds.length} 道错题</span>
              <div className="v3-rp-selection__actions">
                <Button variant="tonal" size="sm" disabled={!backendOk} onClick={() => setShowOcrBatch(true)}>批量识别</Button>
                <Button variant="danger" size="sm" onClick={batchRemove}>批量删除</Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedIds(list.map((n) => n.id))}
                  disabled={list.length === 0}
                >
                  全选当前 {list.length} 项
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setSelectedIds([])}>取消选择</Button>
              </div>
            </div>
          )}

          {list.length === 0 ? (
            <Tile span={12} className="v3-nb-empty">
              {!backendOk && notebook.length === 0 ? (
                <EmptyState
                  icon={<AlertCircle size={26} />}
                  title="无法连接错题库"
                  text={loadErr ? `后端返回：${loadErr}` : '请确认后端服务已启动，然后重试。'}
                  action={(
                    <div className="v3-rp-empty-actions">
                      <Button variant="filled" icon={<RefreshCw size={16} />} onClick={refresh}>重试加载</Button>
                      <Button variant="outline" icon={<Plus size={16} />} onClick={openAdd}>离线手动录入</Button>
                    </div>
                  )}
                />
              ) : notebook.length === 0 ? (
                <EmptyState
                  icon={<NotebookPen size={26} />}
                  title="这本错题本还是空的"
                  text="拍一张错题照片自动识别入库，或手动录入题干与解析；之后会按艾宾浩斯曲线自动排复习。"
                  action={(
                    <div className="v3-rp-empty-actions">
                      <Button variant="filled" icon={<Camera size={16} />} onClick={() => captureRef.current?.click()} disabled={ocrBusy}>拍照收录</Button>
                      <Button variant="tonal" icon={<Plus size={16} />} onClick={openAdd}>手动录入</Button>
                      <Link className="v3-btn v3-btn--text" to="/quiz">去刷题</Link>
                    </div>
                  )}
                />
              ) : (
                <EmptyState
                  icon={<Search size={26} />}
                  title="没有符合条件的错题"
                  text="换个科目、标签或关键词试试，也可以清除筛选查看全部错题。"
                  action={(
                    <div className="v3-rp-empty-actions">
                      <Button variant="tonal" onClick={resetFilters}>清除筛选</Button>
                      <Button variant="ghost" icon={<Plus size={16} />} onClick={openAdd}>手动录入</Button>
                    </div>
                  )}
                />
              )}
            </Tile>
          ) : viewMode === 'grid' ? (
            <div className="v3-nb-grid">
              {list.map((n) => (
                <article key={n.id} className="v3-card v3-nb-card">
                  <div className="v3-nb-card__head">
                    <div className="v3-nb-card__badges">
                      <label className="v3-rp-check">
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(n.id)}
                          onChange={() => toggleSelect(n.id)}
                          aria-label={`选择错题：${n.question.slice(0, 30)}`}
                        />
                      </label>
                      <MasteryBadge state={n.masteryState} label={n.masteryLabel} />
                      <StatusBadge item={n} today={today} />
                    </div>
                    <CardMenu
                      n={n}
                      aiBusy={aiBusy}
                      aiBusyId={aiBusyId}
                      onAi={() => aiAnalyze(n)}
                      onCard={() => toCard(n)}
                      onGraduate={() => graduate(n.id)}
                      onEdit={() => beginEdit(n)}
                      onRemove={() => remove(n.id)}
                    />
                  </div>
                  <button type="button" className="v3-nb-card__body" onClick={() => openDetail(n)}>
                    <MathText className="v3-rp-prose v3-nb-card__question v3-clamp-3" text={n.question} />
                  </button>
                  <div className="v3-nb-card__meta">
                    <span>{subjectName(n.subject)}</span>
                    <span>复习 {n.reviewCount || 0} 次</span>
                    <span>{n.nextReview ? `下次 ${fmtDateCN(String(n.nextReview).slice(0, 10))}` : '未排期'}</span>
                  </div>
                  <div className="v3-nb-card__actions">
                    <Button variant="ghost" size="sm" onClick={() => reviewFlow(n.id, true)}>答对</Button>
                    <Button variant="ghost" size="sm" onClick={() => reviewFlow(n.id, false)}>答错</Button>
                    <Button variant="outline" size="sm" onClick={() => openDetail(n)}>详情</Button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="v3-nb-list">
              {list.map((n) => (
                <div key={n.id} className="v3-nb-row">
                  <label className="v3-rp-check">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(n.id)}
                      onChange={() => toggleSelect(n.id)}
                      aria-label={`选择错题：${n.question.slice(0, 30)}`}
                    />
                  </label>
                  <div
                    className="v3-nb-row__main"
                    role="button"
                    tabIndex={0}
                    aria-label={`查看错题详情：${n.question.slice(0, 40)}`}
                    onClick={() => openDetail(n)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        openDetail(n)
                      }
                    }}
                  >
                    <div className="v3-nb-row__badges">
                      <MasteryBadge state={n.masteryState} label={n.masteryLabel} />
                      <StatusBadge item={n} today={today} />
                      <Badge tone="outline">{subjectName(n.subject)}</Badge>
                    </div>
                    <MathText className="v3-rp-prose v3-nb-row__question v3-clamp-2" text={n.question} />
                    <div className="v3-caption">
                      复习 {n.reviewCount || 0} 次 · {n.lastReview ? `上次 ${fmtDateCN(String(n.lastReview).slice(0, 10))}` : '尚未复习'}
                    </div>
                  </div>
                  <div className="v3-nb-row__actions">
                    <Button
                      variant="outline"
                      size="sm"
                      loading={aiBusy && aiBusyId === n.id}
                      disabled={aiBusy}
                      onClick={() => aiAnalyze(n)}
                    >
                       AI 精讲
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => toCard(n)}>转卡</Button>
                    <Button variant="ghost" size="sm" onClick={() => graduate(n.id)}>毕业</Button>
                    <Button variant="danger" size="sm" onClick={() => remove(n.id)}>删除</Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      <Dialog
        open={showAdd}
        title={editingId != null ? '编辑错题' : '收录错题'}
        sub={editingId != null ? '修改会同步到错题记录' : '支持 LaTeX 公式，例如 $x^2$'}
        onClose={() => { if (!submitting) setShowAdd(false) }}
        className="v3-nb-dialog"
        wide
        footer={(
          <div className="v3-rp-foot">
            <Button variant="text" onClick={() => setShowAdd(false)} disabled={submitting}>取消</Button>
            <Button variant="filled" onClick={submit} loading={submitting}>
              {editingId != null ? '保存修改' : '收录错题'}
            </Button>
          </div>
        )}
      >
        <Tabs
          ariaLabel="编辑与预览"
          value={formTab}
          onChange={setFormTab}
          options={[{ value: 'edit', label: '编辑' }, { value: 'preview', label: '预览' }]}
        />
        {formTab === 'edit' ? (
          <div className="v3-nb-form">
            <Field label="科目">
              <Input
                list="v3-nb-subject-options"
                value={form.subject}
                onChange={(e) => setForm({ ...form, subject: e.target.value })}
                placeholder="填写或选择科目"
              />
              <datalist id="v3-nb-subject-options">
                {allSubjects.map((s) => <option key={s} value={s} />)}
              </datalist>
            </Field>
            <Field label="题目 / 题干">
              <Textarea
                rows={4}
                value={form.question}
                onChange={(e) => setForm({ ...form, question: e.target.value })}
                placeholder="原题或题干，可用 $...$ 写公式"
              />
            </Field>
            <Field label="正确答案">
              <Textarea
                rows={3}
                value={form.answer}
                onChange={(e) => setForm({ ...form, answer: e.target.value })}
                placeholder="完整答案"
              />
            </Field>
            <Field label="解析（可选）">
              <Textarea
                rows={3}
                value={form.analysis}
                onChange={(e) => setForm({ ...form, analysis: e.target.value })}
                placeholder="考点、易错点分析"
              />
            </Field>
            <Field label="失分原因（可选）">
              <Input
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                placeholder="如：概念混淆"
              />
            </Field>
            <Field label="标签（可选）" hint="多个标签用逗号分隔">
              <Input
                value={form.tags}
                onChange={(e) => setForm({ ...form, tags: e.target.value })}
                placeholder="极限, 等价无穷小"
              />
            </Field>
          </div>
        ) : (
          <div className="v3-nb-preview">
            <div>
              <div className="v3-caption">题干</div>
              <MathText className="v3-rp-prose" text={form.question || '尚未填写题干'} />
            </div>
            <div>
              <div className="v3-caption">正确答案</div>
              <MathText className="v3-rp-prose" text={form.answer || '尚未填写答案'} />
            </div>
            {form.analysis && (
              <div>
                <div className="v3-caption">解析</div>
                <MathText className="v3-rp-prose" text={form.analysis} />
              </div>
            )}
            {form.reason && (
              <div>
                <div className="v3-caption">失分原因</div>
                <div className="v3-rp-prose">{form.reason}</div>
              </div>
            )}
            {form.tags.trim() && (
              <div className="v3-rp-tags">
                {form.tags.split(/[,，]/).map((t) => t.trim()).filter(Boolean).map((t) => (
                  <span className="v3-rp-tag" key={t}><Tag size={12} />{t}</span>
                ))}
              </div>
            )}
          </div>
        )}
      </Dialog>

      <Dialog
        open={showOcrBatch}
        title="批量识别（OCR）"
        sub={`已选择 ${selectedIds.length} 道错题`}
        onClose={() => { if (!ocrBatchBusy) setShowOcrBatch(false) }}
        className="v3-nb-dialog"
        footer={<div className="v3-rp-foot"><Button variant="text" onClick={() => setShowOcrBatch(false)} disabled={ocrBatchBusy}>关闭</Button></div>}
      >
        <div className="v3-stack">
          <p className="v3-body">
            为选中的错题上传图片，系统会按选择顺序逐张识别，并把文字追加到对应错题的题干。
          </p>
          <div
            className="v3-rp-drop"
            role="button"
            tabIndex={0}
            aria-label="选择要识别的图片，可多选，按顺序对应选中错题"
            onClick={() => { if (!ocrBatchBusy) ocrBatchRef.current?.click() }}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && !ocrBatchBusy) {
                e.preventDefault()
                ocrBatchRef.current?.click()
              }
            }}
          >
            <Image size={28} />
            <b>点击选择多张图片</b>
            <span className="v3-caption">按顺序对应选中的错题；建议按题目顺序选择</span>
            <input
              ref={ocrBatchRef}
              type="file"
              accept="image/*"
              multiple
              aria-label="批量选择要识别的图片"
              className="v3-nb-file"
              onChange={(e) => applyOcrBatch(Array.from(e.target.files || []))}
            />
          </div>
          {ocrBatchBusy && (
            <div className="v3-stack" style={{ gap: 8 }}>
              <div className="v3-caption">识别中… {ocrProgress} / {selectedIds.length}</div>
              <Progress value={selectedIds.length ? (ocrProgress / selectedIds.length) * 100 : 0} gradient />
            </div>
          )}
        </div>
      </Dialog>

      <Dialog
        open={Boolean(liveDetail)}
        title="错题详情"
        sub={liveDetail ? `${subjectName(liveDetail.subject)} · 复习 ${liveDetail.reviewCount || 0} 次` : ''}
        onClose={() => setShowDetail(null)}
        className="v3-nb-dialog v3-nb-detail-dialog"
        full
        footer={liveDetail ? (
          <div className="v3-rp-foot">
            <Button variant="text" onClick={() => setShowDetail(null)}>关闭</Button>
            <Button variant="outline" icon={<Edit size={15} />} onClick={() => beginEdit(liveDetail)}>编辑</Button>
            <Button variant="danger" icon={<Trash size={15} />} onClick={() => remove(liveDetail.id)}>删除</Button>
          </div>
        ) : null}
      >
        {liveDetail && (
          <div className="v3-nb-detail v3-stack">
            <div className="v3-nb-detail__nav">
              <Button
                variant="ghost"
                size="sm"
                icon={<ChevronLeft size={16} />}
                disabled={detailIdx <= 0}
                onClick={() => goDetail(-1)}
              >
                上一题
              </Button>
              <span className="v3-caption">
                {detailIdx >= 0 ? `第 ${detailIdx + 1} / ${list.length} 题` : '当前筛选外'}
              </span>
              <Button
                variant="ghost"
                size="sm"
                trailingIcon={<ChevronRight size={16} />}
                disabled={detailIdx < 0 || detailIdx >= list.length - 1}
                onClick={() => goDetail(1)}
              >
                下一题
              </Button>
            </div>

            <div className="v3-nb-detail__badges">
              <MasteryBadge state={liveDetail.masteryState} label={liveDetail.masteryLabel} />
              <StatusBadge item={liveDetail} today={today} />
              <Badge tone="outline">{subjectName(liveDetail.subject)}</Badge>
              {liveDetail.tags.map((t) => (
                <span className="v3-rp-tag" key={t}><Tag size={12} />{t}</span>
              ))}
            </div>

            <div>
              <div className="v3-caption">题干</div>
              <MathText className="v3-rp-prose v3-nb-detail__question" text={liveDetail.question || '（题干为空）'} />
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={() => setDetailShowAnswer((v) => !v)}
              trailingIcon={<ChevronDownToggle open={detailShowAnswer} />}
            >
              {detailShowAnswer ? '收起答案 / 解析' : '显示答案 / 解析'}
            </Button>

            {detailShowAnswer && (
              <div className="v3-nb-detail__answers">
                <div className="v3-nb-answer">
                  <span className="v3-caption">我的答案</span>
                  <MathText className="v3-rp-prose" text={liveDetail.myAnswer || '—'} />
                </div>
                <div className="v3-nb-answer v3-nb-answer--right">
                  <span className="v3-caption">正确答案</span>
                  <MathText className="v3-rp-prose" text={liveDetail.answer || '—'} />
                </div>
                {liveDetail.analysis && (
                  <div className="v3-nb-answer v3-nb-answer--analysis">
                    <span className="v3-caption">解析</span>
                    <MathText className="v3-rp-prose" text={liveDetail.analysis} />
                  </div>
                )}
              </div>
            )}

            {liveDetail.reason && (
              <div>
                <div className="v3-caption">失分原因</div>
                <div className="v3-rp-prose v3-nb-detail__reason">{liveDetail.reason}</div>
              </div>
            )}

            {aiMetaMap[liveDetail.id] && (
              <div className="v3-nb-ai-meta">
                {aiMetaMap[liveDetail.id].category && (
                  <Badge tone="warning">错因 {aiMetaMap[liveDetail.id].category}</Badge>
                )}
                {aiMetaMap[liveDetail.id].knowledgePoint && (
                  <Badge tone="primary">考点 {aiMetaMap[liveDetail.id].knowledgePoint}</Badge>
                )}
                {aiMetaMap[liveDetail.id].suggestion && (
                  <div className="v3-rp-prose v3-nb-ai-suggestion">
                    <span className="v3-caption">纠正建议</span>
                    <MathText text={aiMetaMap[liveDetail.id].suggestion} />
                  </div>
                )}
              </div>
            )}

            <div className="v3-divider" />

            <div className="v3-rp-section-head">
              <div>
                <div className="v3-h3">AI 追问</div>
                <div className="v3-caption">围绕当前错题的题干、答案与解析继续提问</div>
              </div>
              {aiFollowup.history.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setAiFollowup({ input: '', busy: false, history: [] })}
                >
                  清空对话
                </Button>
              )}
            </div>

            {aiFollowup.history.map((h, i) => (
              <div className="v3-nb-chat" key={`${h.q}-${i}`}>
                <div className="v3-nb-chat__q">问：{h.q}</div>
                <div className="v3-nb-chat__a">
                  {h.a ? <MathText className="v3-rp-prose" text={h.a} /> : <span className="v3-caption">正在思考…</span>}
                </div>
              </div>
            ))}
            {aiFollowup.busy && (
              <div className="v3-row"><Spinner size={16} /><span className="v3-caption">AI 正在回答…</span></div>
            )}

            <div className="v3-nb-followup">
              <Input
                aria-label="向 AI 追问这道题"
                placeholder="比如：这道题还有别的解法吗？"
                value={aiFollowup.input}
                onChange={(e) => setAiFollowup((s) => ({ ...s, input: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    runFollowup(liveDetail)
                  }
                }}
                disabled={aiFollowup.busy}
              />
              <Button
                variant="filled"
                icon={<Send size={16} />}
                loading={aiFollowup.busy}
                disabled={aiFollowup.busy || !aiFollowup.input.trim()}
                onClick={() => runFollowup(liveDetail)}
              >
                发送
              </Button>
            </div>

            <div className="v3-divider" />

            <div className="v3-rp-section-head">
              <div>
                <div className="v3-h3">复练与拓展</div>
                <div className="v3-caption">AI 分析会从题库匹配同考点练习题</div>
              </div>
              <Button
                variant="tonal"
                size="sm"
                icon={<Wand size={15} />}
                loading={aiBusy && aiBusyId === liveDetail.id}
                disabled={aiBusy}
                onClick={() => aiAnalyze(liveDetail)}
              >
                {Array.isArray(similarMap[liveDetail.id]) ? '刷新推荐' : 'AI 分析'}
              </Button>
            </div>

            {Array.isArray(similarMap[liveDetail.id]) && similarMap[liveDetail.id].length > 0 ? (
              <div className="v3-nb-practices">
                {similarMap[liveDetail.id].map((p, i) => (
                  <details className="v3-nb-practice" key={p.question_id ?? i}>
                    <summary>
                      <span className="v3-badge v3-badge--primary">练习 {i + 1}</span>
                      <MathText className="v3-rp-prose" text={p.content || '（题目内容为空）'} />
                    </summary>
                    <div className="v3-nb-practice__body">
                      {p.options && <div className="v3-caption">选项：{p.options}</div>}
                      <div className="v3-caption">答案</div>
                      <MathText className="v3-rp-prose" text={p.answer || '—'} />
                      {p.analysis && (
                        <>
                          <div className="v3-caption">解析</div>
                          <MathText className="v3-rp-prose" text={p.analysis} />
                        </>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            ) : (
              <div className="v3-nb-local-hints">
                <div className="v3-caption v3-row">
                  <Badge tone="outline">本地提示</Badge>
                  {Array.isArray(similarMap[liveDetail.id]) ? 'AI 未返回配套练习题，先按下面的思路复盘' : '运行 AI 分析后可获得题库配套练习'}
                </div>
                {genSimilar(liveDetail).map((s, i) => (
                  <div className="v3-nb-local-hint" key={i}>
                    <Layers size={15} />
                    <div>
                      <div>{s.title}</div>
                      <div className="v3-caption">{s.kind}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="v3-nb-detail__actions">
              <Button variant="ghost" size="sm" icon={<CheckCircle size={15} />} onClick={() => reviewFlow(liveDetail.id, true)}>答对 +1</Button>
              <Button variant="outline" size="sm" icon={<Layers size={15} />} onClick={() => toCard(liveDetail)}>转记忆卡片</Button>
              <Button variant="ghost" size="sm" icon={<GraduationCap size={15} />} onClick={() => graduate(liveDetail.id)}>毕业</Button>
            </div>
          </div>
        )}
      </Dialog>

      {confirmDialog}
    </div>
  )
}

function EmptyState({ icon, title, text, action }) {
  return (
    <div className="v3-empty">
      <div className="v3-empty__orb">{icon}</div>
      <div className="v3-empty__title">{title}</div>
      {text ? <div className="v3-empty__text">{text}</div> : null}
      {action}
    </div>
  )
}

function ChevronDownToggle({ open }) {
  return (
    <span className={cx('v3-nb-chevron', open && 'is-open')}>
      <ChevronRight size={15} />
    </span>
  )
}
