import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import useStore from '../../store/useStore'
import { errorsApi, quizApi, taxonomyApi, fetchAllPages } from '../../api/client'
import { ukey, readMigrated } from '../../utils/userKeys'
import { fmtDateTime } from '../../utils/date'
import MathText from '../../components/MathText'
import {
  Alert, AnimatedNumber, Badge, Button, Card, CardHead, Chip, Empty, Field,
  Menu, PageHeader, Select, Skeleton, Spinner, Tile, cx, toast,
} from '../ui'
import {
  Activity, AlertCircle, BarChart3, Brain, CalendarClock, Check, CheckCircle,
  ChevronDown, ChevronRight, CircleHelp, Download, FileText, FilterX, Folder, Map,
  RefreshCw, SlidersHorizontal, Target, Wand,
} from '../icons'
import '../styles/review-pages.css'
import '../styles/study-glass.css'

const PAGE_SIZE = 20
const MASTERY_STATES = ['unlearned', 'weak', 'mastered']
const MASTERY_FALLBACK_LABEL = { unlearned: '未学', weak: '薄弱', mastered: '已掌握' }
const MASTERY_BADGE = { unlearned: 'outline', weak: 'warning', mastered: 'success' }

const LINK_SOURCE_LABEL = {
  question_link: '题目关联',
  manual: '手动指定',
  name_match: '自动·名称命中',
  name_match_cross: '自动·跨科目兜底',
  keyword_match: '自动·关键词命中',
  chapter_match: '自动·同章检索',
  search_match: '自动·检索命中',
  subject_fallback: '自动·同科目兜底',
}

const emptyText = (v) => (v === null || v === undefined || v === '' ? '—' : String(v))
const fmtPercent = (v) => {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : '—'
}
const fmtTime = (v) => fmtDateTime(v) || '—'
const statusText = (v) => (v === 'graduated' ? '已毕业' : v === 'archived' ? '已归档' : '在练')

const DETAIL_FIELDS = [
  { key: 'id', label: '记录 ID', default: false },
  { key: 'subject', label: '学科', default: true },
  { key: 'question_id', label: '关联题目 ID', default: false },
  { key: 'error_reason', label: '错因', default: true },
  { key: 'my_answer', label: '我的答案', default: true },
  { key: 'correct_answer', label: '正确答案', default: true },
  { key: 'accuracy', label: '正确率', default: true, fmt: fmtPercent },
  { key: 'mastery_label', label: '掌握度', default: true },
  { key: 'review_count', label: '复习次数', default: true },
  { key: 'last_review', label: '上次复习', default: true, fmt: fmtTime },
  { key: 'next_review', label: '下次复习', default: true, fmt: fmtTime },
  { key: 'status', label: '状态', default: true, fmt: statusText },
  { key: 'analysis', label: 'AI 分析', default: true },
  { key: 'created_at', label: '录入时间', default: false, fmt: fmtTime },
  { key: 'updated_at', label: '更新时间', default: false, fmt: fmtTime },
]
const DEFAULT_VISIBLE = DETAIL_FIELDS.filter((f) => f.default).map((f) => f.key)
const FIELD_VISIBILITY_KEY = 'er_field_visibility'

function normalizeList(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.items)) return data.items
  if (data && Array.isArray(data.errors)) return data.errors
  return []
}

function parseTags(t) {
  if (Array.isArray(t)) return t.filter(Boolean).map(String)
  if (typeof t === 'string') {
    try {
      const p = JSON.parse(t || '[]')
      return Array.isArray(p) ? p.filter(Boolean).map(String) : []
    } catch {
      return []
    }
  }
  return []
}

function ErStatTile({ label, value, tone, icon }) {
  return (
    <Tile span={2} className={cx('v3-er-stat', tone && `v3-er-stat--${tone}`)}>
      <span className="v3-tile__label">{icon}{label}</span>
      <span className="v3-tile__value">
        {value == null ? '—' : <AnimatedNumber value={value} />}
      </span>
    </Tile>
  )
}

export default function ErrorReview() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const urlErrorId = searchParams.get('error_id')

  const [kpId, setKpId] = useState(() => searchParams.get('kp_id') || '')
  const [kpName, setKpName] = useState(() => searchParams.get('kp_name') || '')
  const [subject, setSubject] = useState(() => searchParams.get('subject') || '')
  const [errorReason, setErrorReason] = useState('')
  const [masteryState, setMasteryState] = useState('')
  const [statusFilter, setStatusFilter] = useState('active')
  const [page, setPage] = useState(1)

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [listState, setListState] = useState('loading')
  const [listErr, setListErr] = useState('')
  const [loading, setLoading] = useState(false)

  const [subjectOptions, setSubjectOptions] = useState([])
  const [subjectErr, setSubjectErr] = useState('')
  const [stats, setStats] = useState(null)
  const [statsErr, setStatsErr] = useState('')
  const [statsLoading, setStatsLoading] = useState(true)
  const [reasons, setReasons] = useState([])
  const [reasonsErr, setReasonsErr] = useState('')
  const [reasonsLoading, setReasonsLoading] = useState(true)
  const [kpChoices, setKpChoices] = useState([])
  const [kpChoicesErr, setKpChoicesErr] = useState('')
  const [kpChoicesLoading, setKpChoicesLoading] = useState(true)

  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState({ state: 'idle', kps: [], kpErr: '' })
  const [linkKp, setLinkKp] = useState('')
  const [linking, setLinking] = useState(false)
  const [ai, setAi] = useState({
    state: 'idle', text: '', err: '', category: '', knowledgePoint: '', suggestion: '', practice: [],
  })

  const [showFieldPicker, setShowFieldPicker] = useState(false)
  const [visibleFields, setVisibleFields] = useState(() => {
    try {
      const saved = readMigrated(FIELD_VISIBILITY_KEY, DEFAULT_VISIBLE)
      return new Set(Array.isArray(saved) ? saved : DEFAULT_VISIBLE)
    } catch {
      return new Set(DEFAULT_VISIBLE)
    }
  })

  const addNote = useStore((s) => s.addNote)
  const listSeq = useRef(0)
  const detailSeq = useRef(0)
  const subjectSeq = useRef(0)
  const reasonSeq = useRef(0)
  const kpSeq = useRef(0)
  const fieldBtnRef = useRef(null)
  const detailRef = useRef(null)

  const loadList = useCallback(async () => {
    const seq = ++listSeq.current
    setLoading(true)
    try {
      const data = await errorsApi.list({
        subject: subject || undefined,
        error_reason: errorReason || undefined,
        mastery_state: masteryState || undefined,
        status: statusFilter || undefined,
        knowledge_point_id: kpId || undefined,
        page,
        page_size: PAGE_SIZE,
      })
      if (seq !== listSeq.current) return
      const list = normalizeList(data)
      setItems(list)
      setTotal(Number(data?.total) || list.length)
      setTotalPages(Number(data?.total_pages) || 1)
      setListState('ok')
      setListErr('')
    } catch (e) {
      if (seq !== listSeq.current) return
      setItems([])
      setTotal(0)
      setListErr(e?.message || '未知错误')
      setListState('error')
    } finally {
      if (seq === listSeq.current) setLoading(false)
    }
  }, [subject, errorReason, masteryState, statusFilter, kpId, page])

  useEffect(() => { loadList() }, [loadList])

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const d = await errorsApi.stats(subject ? { subject } : undefined)
      setStats(d || null)
      setStatsErr(d ? '' : '统计接口返回空数据')
    } catch (e) {
      setStats(null)
      setStatsErr(e?.message || '统计接口不可用')
    } finally {
      setStatsLoading(false)
    }
  }, [subject])

  useEffect(() => { loadStats() }, [loadStats])

  const loadSubjects = useCallback(async () => {
    const seq = ++subjectSeq.current
    try {
      const r = await taxonomyApi.subjects()
      if (seq !== subjectSeq.current) return
      const list = Array.isArray(r) ? r : (r && (r.subjects || r.items)) || []
      const withErrors = list
        .filter((s) => Number(s.error_count || 0) > 0)
        .map((s) => ({ subject: s.subject, count: Number(s.error_count || 0) }))
      setSubjectOptions(withErrors)
      setSubjectErr('')
    } catch (e) {
      if (seq !== subjectSeq.current) return
      setSubjectOptions([])
      setSubjectErr(e?.message || '科目接口不可用')
    }
  }, [])

  useEffect(() => { loadSubjects() }, [loadSubjects])

  const loadReasons = useCallback(async () => {
    const seq = ++reasonSeq.current
    setReasonsLoading(true)
    try {
      const d = await quizApi.wrongReasons()
      if (seq !== reasonSeq.current) return
      setReasons(Array.isArray(d?.items) ? d.items : [])
      setReasonsErr('')
    } catch (e) {
      if (seq !== reasonSeq.current) return
      setReasons([])
      setReasonsErr(e?.message || '错因接口不可用')
    } finally {
      if (seq === reasonSeq.current) setReasonsLoading(false)
    }
  }, [])

  useEffect(() => { loadReasons() }, [loadReasons])

  const loadKpChoices = useCallback(async () => {
    const seq = ++kpSeq.current
    setKpChoicesLoading(true)
    try {
      const list = await fetchAllPages((p) => taxonomyApi.knowledgePoints({ ...p, subject: subject || undefined }))
      if (seq !== kpSeq.current) return
      setKpChoices(list.map((k) => ({
        id: k.id,
        label: `${k.name}（${k.subject || '未分类'}${k.chapter ? ' · ' + k.chapter : ''}）`,
      })))
      setKpChoicesErr('')
    } catch (e) {
      if (seq !== kpSeq.current) return
      setKpChoices([])
      setKpChoicesErr(e?.message || '知识点接口不可用')
    } finally {
      if (seq === kpSeq.current) setKpChoicesLoading(false)
    }
  }, [subject])

  useEffect(() => { loadKpChoices() }, [loadKpChoices])

  const pickSubject = (v) => { setSubject(v); setPage(1) }
  const pickReason = (v) => { setErrorReason(v); setPage(1) }
  const pickMastery = (v) => { setMasteryState(v); setPage(1) }
  const pickStatus = (v) => { setStatusFilter(v); setPage(1) }

  const clearKpFilter = () => {
    setKpId('')
    setKpName('')
    setPage(1)
    const next = new URLSearchParams(searchParams)
    next.delete('kp_id')
    next.delete('kp_name')
    setSearchParams(next, { replace: true })
  }

  const filtersDirty = Boolean(masteryState || errorReason || subject || kpId || statusFilter !== 'active')

  const resetFilters = () => {
    setMasteryState('')
    setErrorReason('')
    setSubject('')
    setStatusFilter('active')
    setKpId('')
    setKpName('')
    setPage(1)
    const next = new URLSearchParams(searchParams)
    ;['kp_id', 'kp_name', 'subject', 'error_id'].forEach((k) => next.delete(k))
    setSearchParams(next, { replace: true })
  }

  const loadKps = useCallback(async (id) => {
    const seq = ++detailSeq.current
    setDetail({ state: 'loading', kps: [], kpErr: '' })
    try {
      const d = await errorsApi.knowledgePoints(id)
      if (seq !== detailSeq.current) return
      const list = Array.isArray(d?.items) ? d.items : Array.isArray(d) ? d : []
      setDetail({ state: 'ok', kps: list, kpErr: '' })
    } catch (e) {
      if (seq !== detailSeq.current) return
      setDetail({ state: 'error', kps: [], kpErr: e?.message || '知识点关联接口不可用' })
    }
  }, [])

  const selectError = (err, { scroll = false } = {}) => {
    setSelectedId(err.id)
    setAi({
      state: 'idle', text: '', err: '', category: '', knowledgePoint: '', suggestion: '', practice: [],
    })
    setLinkKp('')
    loadKps(err.id)
    if (scroll && window.matchMedia('(max-width: 1180px)').matches) {
      window.setTimeout(() => {
        detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 80)
    }
  }

  useEffect(() => {
    if (listState !== 'ok' || items.length === 0) {
      if (items.length === 0 && selectedId != null) setSelectedId(null)
      return
    }
    if (selectedId == null || !items.some((e) => e.id === selectedId)) selectError(items[0])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, listState])

  useEffect(() => {
    if (!urlErrorId || listState !== 'ok') return
    const target = items.find((e) => String(e.id) === String(urlErrorId))
    if (target && String(selectedId) !== String(target.id)) selectError(target)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, listState, urlErrorId])

  const selected = useMemo(
    () => items.find((e) => e.id === selectedId) || null,
    [items, selectedId],
  )

  const masteryLabel = (s) => (stats?.labels && stats.labels[s]) || MASTERY_FALLBACK_LABEL[s] || s
  const stateCount = (s) => (stats ? stats[s] : null)

  const runAiAnalyze = async () => {
    if (selectedId == null) return
    setAi((prev) => ({ ...prev, state: 'loading', text: '', err: '' }))
    try {
      const d = await errorsApi.aiAnalyze(selectedId)
      const text = typeof d === 'string'
        ? d
        : d?.analysis || d?.result || d?.message || ''
      const meta = d && typeof d === 'object' ? d : {}
      setAi({
        state: 'ok',
        text: text || '接口已返回，但没有可展示的分析文本。',
        err: '',
        category: meta.category || '',
        knowledgePoint: meta.knowledge_point || '',
        suggestion: meta.suggestion || '',
        practice: Array.isArray(meta.practice_questions) ? meta.practice_questions : [],
      })
      loadList()
    } catch (e) {
      setAi({
        state: 'error',
        text: '',
        err: e?.message || 'AI 分析接口调用失败',
        category: '',
        knowledgePoint: '',
        suggestion: '',
        practice: [],
      })
    }
  }

  const doLink = async () => {
    if (selectedId == null || !linkKp) return
    setLinking(true)
    try {
      await errorsApi.linkKnowledge(selectedId, { knowledge_point_id: Number(linkKp) })
      await loadKps(selectedId)
      setLinkKp('')
      toast('知识点已关联')
    } catch (e) {
      toast(`关联失败：${e?.message || '未知错误'}`)
    } finally {
      setLinking(false)
    }
  }

  const doUnlink = async (linkId) => {
    if (linkId == null) return
    try {
      await errorsApi.unlinkKnowledge(linkId)
      await loadKps(selectedId)
      toast('已解除关联')
    } catch (e) {
      toast(`解除失败：${e?.message || '未知错误'}`)
    }
  }

  const saveAttributionToNotebook = () => {
    if (!selected) return
    addNote({
      question: selected.content || '',
      answer: selected.correct_answer || '',
      analysis: ai.text || selected.analysis || '',
      reason: ai.text ? `AI 归因：${ai.text.slice(0, 120)}` : (selected.error_reason || ''),
      subject: selected.subject || '',
      tags: ['AI归因'],
    })
    toast('已记入错题本')
  }

  const toggleField = (key) => {
    setVisibleFields((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      try { localStorage.setItem(ukey(FIELD_VISIBILITY_KEY), JSON.stringify([...next])) } catch { /* 忽略隐私模式写入失败 */ }
      return next
    })
  }

  const resetFields = () => {
    setVisibleFields(new Set(DEFAULT_VISIBLE))
    try { localStorage.setItem(ukey(FIELD_VISIBILITY_KEY), JSON.stringify(DEFAULT_VISIBLE)) } catch { /* 忽略 */ }
  }

  const refreshAll = () => {
    loadList()
    loadStats()
  }

  /* 导出 PDF（对标「不背单词」纸质导出）：按当前筛选条件导出本人错题 */
  const exportPdf = async () => {
    if (total === 0) {
      toast('当前没有可导出的错题')
      return
    }
    try {
      await errorsApi.exportPdf({
        subject: subject || undefined,
        status: statusFilter || undefined,
        mastery_state: masteryState || undefined,
      })
      toast('错题本 PDF 已导出')
    } catch (err) {
      toast(`导出失败：${err?.message || '未知错误'}`)
    }
  }

  const detailFields = selected
    ? DETAIL_FIELDS.filter((f) => (
      visibleFields.has(f.key)
      && !['subject', 'mastery_label', 'status', 'my_answer', 'correct_answer', 'analysis'].includes(f.key)
    ))
    : []

  return (
    <div className="v3-stack v3-er v3-glasspage">
      <PageHeader
        eyebrow="错题域 · 归因与薄弱点"
        title="错题复盘"
        icon={<BarChart3 size={26} />}
        sub="错因分布 · 薄弱知识点 · 单题 AI 归因与知识点挂接"
        actions={(
          <>
            <span ref={fieldBtnRef} className="v3-er-field-anchor">
              <Button
                variant="ghost"
                size="sm"
                icon={<SlidersHorizontal size={16} />}
                trailingIcon={<ChevronDown size={14} />}
                aria-haspopup="menu"
                aria-expanded={showFieldPicker}
                onClick={() => setShowFieldPicker((v) => !v)}
              >
                字段
              </Button>
            </span>
            <Button
              variant="outline"
              size="sm"
              icon={<Download size={16} />}
              onClick={exportPdf}
              disabled={total === 0}
            >
              导出 PDF
            </Button>
            <Button
              variant="outline"
              size="sm"
              icon={<RefreshCw size={16} />}
              onClick={refreshAll}
              disabled={loading}
            >
              刷新
            </Button>
          </>
        )}
      />

      <nav className="v3-rp-domain" aria-label="错题域导航">
        <Link to="/error-review" className="v3-rp-domain__link is-active" aria-current="page">错题分析</Link>
        <Link to="/notebook" className="v3-rp-domain__link">错题本</Link>
        <Link to="/quiz?tab=review" className="v3-rp-domain__link">快速重练</Link>
      </nav>

      <Menu open={showFieldPicker} anchorRef={fieldBtnRef} onClose={() => setShowFieldPicker(false)} width={252}>
        <div className="v3-er-field-menu">
          <div className="v3-caption">勾选要在详情里显示的字段</div>
          <div className="v3-er-field-list">
            {DETAIL_FIELDS.map((f) => {
              const checked = visibleFields.has(f.key)
              return (
                <button
                  key={f.key}
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={checked}
                  className="v3-er-field-item"
                  onClick={() => toggleField(f.key)}
                >
                  <span className={cx('v3-er-field-check', checked && 'is-checked')}>
                    {checked ? <Check size={13} /> : null}
                  </span>
                  <span>{f.label}</span>
                </button>
              )
            })}
          </div>
          <Button variant="ghost" size="sm" onClick={resetFields}>恢复默认</Button>
        </div>
      </Menu>

      {statsErr && !statsLoading ? (
        <Alert tone="warning" className="v3-rp-alert">
          <div className="v3-rp-alert__body">
            <span>错题统计不可用：{statsErr}</span>
            <Button variant="text" size="sm" onClick={loadStats} loading={statsLoading}>重试</Button>
          </div>
        </Alert>
      ) : statsLoading ? (
        <div className="v3-bento v3-er-stats">
          {Array.from({ length: 6 }).map((_, i) => (
            <Tile key={i} span={2} className="v3-er-stat">
              <Skeleton width="60%" height={12} />
              <Skeleton width="38%" height={30} />
            </Tile>
          ))}
        </div>
      ) : (
        <div className="v3-bento v3-er-stats">
          <ErStatTile label="活跃错题" value={stats?.active_errors} tone="primary" icon={<Activity size={14} />} />
          <ErStatTile label="今日待复盘" value={stats?.due_errors} tone="warning" icon={<CalendarClock size={14} />} />
          <ErStatTile label="未学" value={stateCount('unlearned')} tone="muted" icon={<CircleHelp size={14} />} />
          <ErStatTile label="薄弱" value={stateCount('weak')} tone="warning" icon={<Target size={14} />} />
          <ErStatTile label="已掌握" value={stateCount('mastered')} tone="success" icon={<CheckCircle size={14} />} />
          <ErStatTile label="已归档" value={stats?.archived_errors} tone="muted" icon={<Folder size={14} />} />
        </div>
      )}

      <Tile span={12} className="v3-er-filters">
        <div className="v3-er-filter-top">
          <span className="v3-caption">筛选选项全部来自后端真实接口；掌握度标签由统计接口下发。</span>
          {filtersDirty && (
            <Button variant="text" size="sm" icon={<FilterX size={15} />} onClick={resetFilters}>清除筛选</Button>
          )}
        </div>

        <div className="v3-er-filter">
          <span className="v3-er-filter__label"><Target size={15} />掌握度</span>
          <div className="v3-er-chips" role="group" aria-label="掌握度筛选">
            <Chip active={masteryState === ''} onClick={() => pickMastery('')}>
              全部
              {stats && <span className="v3-rp-count">{stats.total}</span>}
            </Chip>
            {MASTERY_STATES.map((s) => {
              const count = stateCount(s)
              return (
                <Chip key={s} active={masteryState === s} onClick={() => pickMastery(s)}>
                  {masteryLabel(s)}
                  {count != null && <span className="v3-rp-count">{count}</span>}
                </Chip>
              )
            })}
          </div>
        </div>

        <div className="v3-er-filter">
          <span className="v3-er-filter__label"><Activity size={15} />状态</span>
          <div className="v3-er-chips" role="group" aria-label="错题状态筛选">
            <Chip active={statusFilter === 'active'} onClick={() => pickStatus('active')}>在练</Chip>
            <Chip active={statusFilter === 'archived'} onClick={() => pickStatus('archived')}>已归档</Chip>
          </div>
        </div>

        <div className="v3-er-filter">
          <span className="v3-er-filter__label"><FileText size={15} />错因</span>
          <div className="v3-er-chips v3-er-chip-scroll" role="group" aria-label="错因筛选">
            <Chip active={errorReason === ''} onClick={() => pickReason('')}>全部</Chip>
            {reasons.map((r) => (
              <Chip key={r.reason} active={errorReason === r.reason} onClick={() => pickReason(r.reason)}>
                {r.reason}
                {r.count > 0 && <span className="v3-rp-count">{r.count}</span>}
              </Chip>
            ))}
            {reasonsLoading && reasons.length === 0 && <span className="v3-caption">错因加载中…</span>}
          </div>
        </div>
        {reasonsErr && (
          <div className="v3-er-api-error">
            <AlertCircle size={14} />
            <span>错因筛选加载失败：{reasonsErr}</span>
            <Button variant="text" size="sm" onClick={loadReasons}>重试</Button>
          </div>
        )}

        <div className="v3-er-filter">
          <span className="v3-er-filter__label"><Activity size={15} />学科</span>
          <div className="v3-er-chips v3-er-chip-scroll" role="group" aria-label="学科筛选">
            <Chip active={subject === ''} onClick={() => pickSubject('')}>全部</Chip>
            {subjectOptions.map((s) => (
              <Chip key={s.subject} active={subject === s.subject} onClick={() => pickSubject(s.subject)}>
                {s.subject}
                {s.count > 0 && <span className="v3-rp-count">{s.count}</span>}
              </Chip>
            ))}
          </div>
        </div>
        {subjectErr && (
          <div className="v3-er-api-error">
            <AlertCircle size={14} />
            <span>学科接口失败：{subjectErr}</span>
            <Button variant="text" size="sm" onClick={loadSubjects}>重试</Button>
          </div>
        )}

        {kpId && (
          <div className="v3-er-filter">
            <span className="v3-er-filter__label"><Target size={15} />考点</span>
            <div className="v3-er-chips">
              <b className="v3-er-kp-name">{kpName || `知识点 #${kpId}`}</b>
              <Chip active onClick={clearKpFilter}>只看这个考点 · 清除</Chip>
            </div>
          </div>
        )}
      </Tile>

      <div className="v3-bento v3-er-layout">
        <Tile span={7} className="v3-er-list-tile">
          <CardHead
            title="错题清单"
            sub={`共 ${total} 条 · 第 ${page} / ${Math.max(totalPages, 1)} 页${loading ? ' · 加载中…' : ''}`}
          />
          <div className={cx('v3-er-list-body', loading && 'is-loading')} aria-busy={loading || undefined}>
            {listState === 'loading' ? (
              <div className="v3-er-skeleton-list">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="v3-er-skeleton-row">
                    <Skeleton width="42%" height={14} />
                    <Skeleton width="90%" height={16} />
                    <Skeleton width="58%" height={11} />
                  </div>
                ))}
              </div>
            ) : listState === 'error' ? (
              <Empty
                icon={<AlertCircle size={26} />}
                title="错题列表加载失败"
                text={listErr}
                action={(
                  <div className="v3-rp-empty-actions">
                    <Button variant="filled" icon={<RefreshCw size={15} />} onClick={loadList}>重新加载</Button>
                    {filtersDirty && <Button variant="ghost" onClick={resetFilters}>清除筛选</Button>}
                  </div>
                )}
              />
            ) : items.length === 0 ? (
              <Empty
                icon={<FileText size={26} />}
                title="当前筛选条件下没有错题"
                text="换个掌握度、错因或学科；也可以去刷题（答错会自动归集），或手动录入一道错题。"
                action={(
                  <div className="v3-rp-empty-actions">
                    <Button variant="filled" onClick={() => navigate('/quiz')}>去刷题</Button>
                    <Button variant="outline" onClick={() => navigate('/notebook')}>手动录入</Button>
                    {kpId && <Button variant="ghost" onClick={clearKpFilter}>清除考点筛选</Button>}
                    {!kpId && filtersDirty && <Button variant="ghost" onClick={resetFilters}>清除筛选</Button>}
                  </div>
                )}
              />
            ) : (
              <div className="v3-er-list">
                {items.map((e) => {
                  const open = selectedId === e.id
                  const state = e.mastery_state || 'unlearned'
                  return (
                    <button
                      type="button"
                      key={e.id}
                      className={cx('v3-er-row', open && 'is-active')}
                      onClick={() => selectError(e, { scroll: true })}
                      aria-current={open ? 'true' : undefined}
                    >
                      <div className="v3-er-row__top">
                        <Badge tone={MASTERY_BADGE[state] || 'outline'}>
                          {e.mastery_label || masteryLabel(state)}
                        </Badge>
                        <span className="v3-er-row__subject">{e.subject || '未分类'}</span>
                        <span className="v3-er-row__reason">{e.error_reason || '未标注错因'}</span>
                        <span className="v3-er-row__meta">
                          复习 {e.review_count || 0} 次 · 正确率 {Math.round((Number(e.accuracy) || 0) * 100)}%
                        </span>
                      </div>
                      <div className="v3-er-row__q">
                        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                        <MathText className="v3-rp-prose v3-er-row__question v3-clamp-2" text={e.content || '（题干为空）'} />
                      </div>
                    </button>
                  )
                })}
              </div>
            )}

            {totalPages > 1 && (
              <div className="v3-er-pager">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || loading}
                >
                  上一页
                </Button>
                <span className="v3-caption">{page} / {totalPages}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages || loading}
                >
                  下一页
                </Button>
              </div>
            )}
          </div>
        </Tile>

        <div className="v3-stack v3-er-side v3-span-5" ref={detailRef}>
          <Card className="v3-er-detail">
            <CardHead
              title="错题详情"
              sub={selected ? `记录 #${selected.id}` : '请从左侧选择一条错题'}
              actions={selected ? (
                <Button
                  variant="tonal"
                  size="sm"
                  icon={<Wand size={15} />}
                  loading={ai.state === 'loading'}
                  disabled={ai.state === 'loading'}
                  onClick={runAiAnalyze}
                >
                  {ai.state === 'loading' ? '分析中…' : 'AI 归因分析'}
                </Button>
              ) : null}
            />
            <div className="v3-er-detail-body">
              {!selected ? (
                <Empty
                  icon={<FileText size={24} />}
                  title="尚未选择错题"
                  text="点击左侧任意一条错题，查看答案、错因、知识点关联与 AI 归因。"
                />
              ) : (
                <>
                  <div className="v3-er-detail-badges">
                    {visibleFields.has('subject') && <Badge tone="outline">{selected.subject || '未分类'}</Badge>}
                    {visibleFields.has('mastery_label') && (
                      <Badge tone={MASTERY_BADGE[selected.mastery_state] || 'outline'}>
                        {selected.mastery_label || masteryLabel(selected.mastery_state || 'unlearned')}
                      </Badge>
                    )}
                    {visibleFields.has('status') && (
                      <Badge tone={selected.status === 'graduated' ? 'success' : selected.status === 'archived' ? 'outline' : 'primary'}>
                        {statusText(selected.status)}
                      </Badge>
                    )}
                  </div>

                  <MathText className="v3-rp-prose v3-er-question" text={selected.content || '（题干为空）'} />

                  {(visibleFields.has('my_answer') || visibleFields.has('correct_answer')) && (
                    <div className="v3-er-answers">
                      {visibleFields.has('my_answer') && (
                        <div className="v3-er-ans v3-er-ans--wrong">
                          <span className="v3-caption">我的答案</span>
                          <MathText className="v3-rp-prose" text={emptyText(selected.my_answer)} />
                        </div>
                      )}
                      {visibleFields.has('correct_answer') && (
                        <div className="v3-er-ans v3-er-ans--right">
                          <span className="v3-caption">正确答案</span>
                          <MathText className="v3-rp-prose" text={emptyText(selected.correct_answer)} />
                        </div>
                      )}
                    </div>
                  )}

                  {detailFields.length > 0 && (
                    <div className="v3-er-kv">
                      {detailFields.map((f) => (
                        <React.Fragment key={f.key}>
                          <span>{f.label}</span>
                          <b><MathText text={f.fmt ? f.fmt(selected[f.key]) : emptyText(selected[f.key])} /></b>
                        </React.Fragment>
                      ))}
                    </div>
                  )}

                  {parseTags(selected.tags).length > 0 && (
                    <div className="v3-rp-tags">
                      {parseTags(selected.tags).map((t) => <span className="v3-rp-tag" key={t}>{t}</span>)}
                    </div>
                  )}

                  {visibleFields.has('analysis') && selected.analysis && ai.state !== 'ok' && (
                    <div className="v3-er-ai">
                      <div className="v3-er-ai__head">
                        <Brain size={17} />
                        <span>已有分析</span>
                      </div>
                      <MathText className="v3-rp-prose" text={selected.analysis} />
                    </div>
                  )}

                  {ai.state === 'loading' && (
                    <div className="v3-er-ai v3-er-ai--loading">
                      <Spinner size={18} />
                      <span className="v3-caption">AI 正在分析这道错题…</span>
                    </div>
                  )}

                  {ai.state === 'error' && (
                    <Alert tone="danger" className="v3-rp-alert">
                      <div className="v3-rp-alert__body">
                        <div>
                          <div className="v3-strong">AI 分析失败</div>
                          <div className="v3-caption">{ai.err}</div>
                        </div>
                        <Button variant="text" size="sm" onClick={runAiAnalyze}>重试</Button>
                      </div>
                    </Alert>
                  )}

                  {ai.state === 'ok' && (
                    <div className="v3-er-ai v3-er-ai--ok">
                      <div className="v3-er-ai__head">
                        <Brain size={17} />
                        <span>AI 归因分析</span>
                        {ai.category && <Badge tone="warning">错因 {ai.category}</Badge>}
                        {ai.knowledgePoint && <Badge tone="primary">考点 {ai.knowledgePoint}</Badge>}
                      </div>
                      <MathText className="v3-rp-prose" text={ai.text} />
                      {ai.suggestion && (
                        <div className="v3-er-ai__suggestion">
                          <div className="v3-caption">纠正建议</div>
                          <MathText className="v3-rp-prose" text={ai.suggestion} />
                        </div>
                      )}
                      {ai.practice.length > 0 && (
                        <div className="v3-er-practices">
                          <div className="v3-caption">AI 推荐复练（{ai.practice.length}）</div>
                          {ai.practice.map((p, i) => (
                            <details className="v3-er-practice" key={p.question_id ?? i}>
                              <summary>
                                <span className="v3-badge v3-badge--primary">练习 {i + 1}</span>
                                <MathText className="v3-rp-prose" text={p.content || '（题目内容为空）'} />
                              </summary>
                              <div className="v3-er-practice__body">
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
                      )}
                      <Button variant="outline" size="sm" onClick={saveAttributionToNotebook}>
                        记入错题本
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>
          </Card>

          <Card className="v3-er-kps">
            <CardHead
              title="知识点关联"
              sub="「题目关联」来自题目的人工校验链路；「自动」为启发式挂接，仅供参考"
            />
            <div className="v3-er-kp-body">
              {!selected ? (
                <div className="v3-caption">选择一条错题后可查看或挂接知识点。</div>
              ) : (
                <>
                  {detail.state === 'loading' && (
                    <div className="v3-stack" style={{ gap: 10 }}>
                      <Skeleton width="72%" height={14} />
                      <Skeleton width="55%" height={12} />
                    </div>
                  )}
                  {detail.state === 'error' && (
                    <div className="v3-er-api-error">
                      <AlertCircle size={14} />
                      <span>知识点关联读取失败：{detail.kpErr}</span>
                      <Button variant="text" size="sm" onClick={() => loadKps(selected.id)}>重试</Button>
                    </div>
                  )}
                  {detail.state === 'ok' && detail.kps.length === 0 && (
                    <div className="v3-caption">该错题尚未关联任何知识点（题目侧也未校验）。</div>
                  )}
                  {detail.state === 'ok' && detail.kps.length > 0 && (
                    <div className="v3-er-kp-list">
                      {detail.kps.map((k) => (
                        <div className="v3-er-kp" key={k.link_id ?? `q-${k.knowledge_point_id}`}>
                          <Map size={15} />
                          <div className="v3-er-kp__main">
                            <div className="v3-er-kp__name">
                              {k.name || k.kp_name || `知识点 #${k.knowledge_point_id}`}
                              {k.verified && <Badge tone="success">已校验</Badge>}
                            </div>
                            <div className="v3-caption">
                              {[k.subject, k.chapter].filter(Boolean).join(' · ') || '—'}
                              {k.state_label && (
                                <>
                                  {' · '}
                                  <span className={cx('v3-er-kp-state', `is-${k.state || 'unlearned'}`)}>{k.state_label}</span>
                                </>
                              )}
                              {' · '}
                              {LINK_SOURCE_LABEL[k.source] || k.source || '未知来源'}
                              {k.relevance != null && ` · 关联度 ${Math.round(Number(k.relevance) * 100)}%`}
                            </div>
                          </div>
                          {k.link_id != null ? (
                            <Button variant="ghost" size="sm" onClick={() => doUnlink(k.link_id)}>解除</Button>
                          ) : (
                            <span className="v3-caption" title="来自题目的人工校验关联，需在题库侧调整">题目侧</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="v3-er-link-row">
                    <Field label="挂接知识点">
                      <Select
                        aria-label="选择要挂接的知识点"
                        value={linkKp}
                        onChange={(e) => setLinkKp(e.target.value)}
                      >
                        <option value="">
                          {kpChoicesLoading
                            ? '知识点加载中…'
                            : kpChoices.length ? '选择知识点…' : '暂无知识点候选'}
                        </option>
                        {kpChoices.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                      </Select>
                    </Field>
                    <Button
                      variant="filled"
                      onClick={doLink}
                      loading={linking}
                      disabled={!linkKp || linking}
                    >
                      关联
                    </Button>
                  </div>
                  {kpChoicesErr && (
                    <div className="v3-er-api-error">
                      <AlertCircle size={14} />
                      <span>知识点接口失败：{kpChoicesErr}</span>
                      <Button variant="text" size="sm" onClick={loadKpChoices}>重试</Button>
                    </div>
                  )}
                </>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
