import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { errorsApi, quizApi, taxonomyApi } from '../api/client'
import { toast, Empty } from '../components/UI'
import { LoadingState, ErrorState } from '../components/States'
import {
  RefreshCw, AlertCircle, ChevronDown, ChevronRight, Brain, Map, FileText, Activity, Target
} from '../components/Icon'
import './ErrorReview.css'

/* ==========================================================================
   错题复盘（ErrorReview）
   --------------------------------------------------------------------------
   与「电子错题本」（/notebook）分工：Notebook 负责"录入 + 日常复习"，
   本页负责"复盘分析"——把错题摊开成数据，看错误原因分布、薄弱知识点，
   对单题做 AI 归因与知识点挂接。

   数据来源（全部为后端真实接口，无 mock）：
     - GET  /api/errors?subject=&error_reason=&mastery_state=&page=&page_size=
                                              错题列表（分页 + 三态筛选）
     - GET  /api/errors/stats                  错题统计（与仪表盘同一聚合函数）
     - GET  /api/quiz/wrong-reasons            错因分布（错因筛选项 + 计数）
     - GET  /api/taxonomy/subjects             学科筛选（唯一科目源，只保留有错题的科目）
     - GET  /api/taxonomy/knowledge-points     知识点挂接候选（真实知识点，非硬编码）
     - GET  /api/errors/{id}/knowledge-points  该错题的真实关联（题目链路 + 启发式链路）
     - POST /api/errors/{id}/ai-analyze        AI 归因分析
     - POST /api/errors/{id}/link-knowledge    挂接知识点 {knowledge_point_id}
     - DELETE /api/errors/links/{link_id}      解除启发式挂接
   任一接口失败都在页面上如实呈现错误态，不用假数据兜底。
   ========================================================================== */

const PAGE_SIZE = 20

/* 掌握度**三态**筛选项（口径唯一源：后端 services/kp_mastery.py，
   标签也由后端 /api/errors/stats 下发；这里只声明可选值，不写死档位）。 */
const MASTERY_STATES = ['unlearned', 'weak', 'mastered']
const MASTERY_FALLBACK_LABEL = { unlearned: '未学', weak: '薄弱', mastered: '已掌握' }
const MASTERY_TONE = { unlearned: 'muted', weak: 'warn', mastered: 'ok' }

/* 知识点来源 → 中文说明（用于「这题考什么」的可信度标注） */
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

/* 错题详情可显示字段定义（后端 ErrorRecordResponse 全量字段，可显隐自定义）。
 * key 对应后端字段；default 控制默认是否显示，用户可在页面顶部切换。 */
const DETAIL_FIELDS = [
  { key: 'id', label: 'ID', default: false },
  { key: 'subject', label: '学科', default: true },
  { key: 'question_id', label: '关联题目 ID', default: false },
  { key: 'error_reason', label: '错因', default: true },
  { key: 'my_answer', label: '我的答案', default: true },
  { key: 'correct_answer', label: '正确答案', default: true },
  { key: 'accuracy', label: '正确率', default: true, fmt: (v) => `${Math.round((Number(v) || 0) * 100)}%` },
  { key: 'mastery_label', label: '掌握度', default: true },
  { key: 'review_count', label: '复习次数', default: true },
  { key: 'last_review', label: '上次复习', default: true, fmt: (v) => v ? new Date(v).toLocaleString('zh-CN') : '—' },
  { key: 'next_review', label: '下次复习', default: true, fmt: (v) => v ? new Date(v).toLocaleString('zh-CN') : '—' },
  { key: 'status', label: '状态', default: true, fmt: (v) => v === 'graduated' ? '已毕业' : v === 'archived' ? '已归档' : '在练' },
  { key: 'analysis', label: 'AI 分析', default: true },
  { key: 'created_at', label: '录入时间', default: false, fmt: (v) => v ? new Date(v).toLocaleString('zh-CN') : '—' },
  { key: 'updated_at', label: '更新时间', default: false, fmt: (v) => v ? new Date(v).toLocaleString('zh-CN') : '—' },
]
const DEFAULT_VISIBLE = DETAIL_FIELDS.filter((f) => f.default).map((f) => f.key)
const FIELD_VISIBILITY_KEY = 'er_field_visibility'

/** 兼容 /api/errors 的多种返回形态：数组 / {items:[]} / {errors:[]} */
function normalizeList(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.items)) return data.items
  if (data && Array.isArray(data.errors)) return data.errors
  return []
}

/** 标签：后端可能是 JSON 字符串或数组 */
function parseTags(t) {
  if (Array.isArray(t)) return t
  if (typeof t === 'string') {
    try { const p = JSON.parse(t || '[]'); return Array.isArray(p) ? p : [] } catch { return [] }
  }
  return []
}

export default function ErrorReview() {
  const [searchParams] = useSearchParams()
  const urlErrorId = searchParams.get('error_id')   // 深链：知识地图「去复盘」跳转目标
  const [subject, setSubject] = useState(() => searchParams.get('subject') || '')
  const [errorReason, setErrorReason] = useState('')
  const [masteryState, setMasteryState] = useState('')
  const [page, setPage] = useState(1)

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [listState, setListState] = useState('loading') // loading | ok | error
  const [listErr, setListErr] = useState('')
  const [loading, setLoading] = useState(false)

  /* 学科筛选（唯一科目源：/api/taxonomy/subjects，只保留有错题的科目） */
  const [subjectOptions, setSubjectOptions] = useState([])
  const [subjectErr, setSubjectErr] = useState('')

  /* 统计（错题统计唯一口径：/api/errors/stats，与仪表盘同一聚合函数） */
  const [stats, setStats] = useState(null)
  const [statsErr, setStatsErr] = useState('')

  /* 错因分布（筛选项计数） */
  const [reasons, setReasons] = useState([])

  /* 知识点挂接候选（真实知识点，来自 /api/taxonomy/knowledge-points） */
  const [kpChoices, setKpChoices] = useState([])
  const [kpChoicesErr, setKpChoicesErr] = useState('')

  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState({ state: 'idle', kps: [], kpErr: '' })
  const [ai, setAi] = useState({ state: 'idle', text: '', err: '' })
  const [linkKp, setLinkKp] = useState('')
  const [linking, setLinking] = useState(false)

  /* 字段显隐：默认展示常用字段，可在页头「字段」里自定义看哪些（存 localStorage） */
  const [visibleFields, setVisibleFields] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem(FIELD_VISIBILITY_KEY)) || DEFAULT_VISIBLE) }
    catch { return new Set(DEFAULT_VISIBLE) }
  })
  const [showFieldPicker, setShowFieldPicker] = useState(false)
  const toggleField = (key) => {
    setVisibleFields((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      localStorage.setItem(FIELD_VISIBILITY_KEY, JSON.stringify([...next]))
      return next
    })
  }

  const listSeq = useRef(0)
  const detailSeq = useRef(0)

  /* ---------------- 错题列表（三态筛选走后端） ---------------- */
  const loadList = useCallback(async () => {
    const seq = ++listSeq.current
    setLoading(true)
    try {
      const data = await errorsApi.list({
        subject: subject || undefined,
        error_reason: errorReason || undefined,
        mastery_state: masteryState || undefined,
        page,
        page_size: PAGE_SIZE
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
  }, [subject, errorReason, masteryState, page])

  useEffect(() => { loadList() }, [loadList])

  /* ---------------- 错题统计（与仪表盘同一聚合函数） ---------------- */
  const loadStats = useCallback(() => {
    errorsApi
      .stats(subject ? { subject } : undefined)
      .then((d) => { setStats(d || null); setStatsErr(d ? '' : '统计接口返回空数据') })
      .catch((e) => { setStats(null); setStatsErr(e?.message || '统计接口不可用') })
  }, [subject])
  useEffect(() => { loadStats() }, [loadStats])

  /* ---------------- 学科筛选：只列"有错题"的科目（错误数 > 0） ---------------- */
  useEffect(() => {
    let alive = true
    taxonomyApi
      .subjects()
      .then((r) => {
        if (!alive) return
        // 兼容 {subjects:[...]} 与直接数组两种形态
        const list = Array.isArray(r) ? r : (r && (r.subjects || r.items)) || []
        const withErrors = list
          .filter((s) => Number(s.error_count || 0) > 0)
          .map((s) => ({ subject: s.subject, count: Number(s.error_count || 0) }))
        setSubjectOptions(withErrors)
        setSubjectErr('')
      })
      .catch((e) => { if (alive) { setSubjectOptions([]); setSubjectErr(e?.message || '科目接口不可用') } })
    return () => { alive = false }
  }, [])

  /* ---------------- 错因分布（供筛选 chip 显示计数） ---------------- */
  useEffect(() => {
    let alive = true
    quizApi
      .wrongReasons()
      .then((d) => { if (alive) setReasons(Array.isArray(d?.items) ? d.items : []) })
      .catch(() => { if (alive) setReasons([]) }) // 筛选项拉不到就不显示计数，不阻断主列表
    return () => { alive = false }
  }, [])

  /* ---------------- 知识点挂接候选：真实知识点（随学科筛选收窄） ---------------- */
  useEffect(() => {
    let alive = true
    taxonomyApi
      .knowledgePoints({ subject: subject || undefined, page_size: 500 })
      .then((d) => {
        if (!alive) return
        const list = Array.isArray(d?.items) ? d.items : []
        setKpChoices(list.map((k) => ({
          id: k.id,
          label: `${k.name}（${k.subject || '未分类'}${k.chapter ? ' · ' + k.chapter : ''}）`,
        })))
        setKpChoicesErr('')
      })
      .catch((e) => { if (alive) { setKpChoices([]); setKpChoicesErr(e?.message || '知识点接口不可用') } })
    return () => { alive = false }
  }, [subject])

  /* 切换筛选回到第一页 */
  const pickSubject = (v) => { setSubject(v); setPage(1) }
  const pickReason = (v) => { setErrorReason(v); setPage(1) }
  const pickMastery = (v) => { setMasteryState(v); setPage(1) }

  /* ---------------- 选中一条错题：拉真实关联的知识点 ---------------- */
  const selectError = async (err) => {
    setSelectedId(err.id)
    setAi({ state: 'idle', text: '', err: '' })
    setLinkKp('')
    const seq = ++detailSeq.current
    setDetail({ state: 'loading', kps: [], kpErr: '' })
    try {
      const d = await errorsApi.knowledgePoints(err.id)
      if (seq !== detailSeq.current) return
      const list = Array.isArray(d?.items) ? d.items : Array.isArray(d) ? d : []
      setDetail({ state: 'ok', kps: list, kpErr: '' })
    } catch (e) {
      if (seq !== detailSeq.current) return
      setDetail({ state: 'error', kps: [], kpErr: e?.message || '知识点关联接口不可用' })
    }
  }

  /* 列表刷新后，若当前选中项已不在本页，自动选第一条，保证详情区不悬空 */
  useEffect(() => {
    if (listState !== 'ok' || items.length === 0) { if (selectedId != null && items.length === 0) setSelectedId(null); return }
    if (selectedId == null || !items.some((e) => e.id === selectedId)) selectError(items[0])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, listState])

  /* 深链：/error-review?error_id=X&subject=Y —— 列表就绪后自动选中该错题 */
  useEffect(() => {
    if (!urlErrorId || listState !== 'ok') return
    const target = items.find((e) => String(e.id) === String(urlErrorId))
    if (target) selectError(target)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, listState, urlErrorId])

  const selected = useMemo(
    () => items.find((e) => e.id === selectedId) || null,
    [items, selectedId]
  )

  /* ---------------- AI 归因分析 ---------------- */
  const runAiAnalyze = async () => {
    if (selectedId == null) return
    setAi({ state: 'loading', text: '', err: '' })
    try {
      const d = await errorsApi.aiAnalyze(selectedId)
      const text =
        typeof d === 'string' ? d
          : d?.analysis || d?.result || d?.message || ''
      setAi({ state: 'ok', text: text || '接口已返回，但没有可展示的分析文本。', err: '' })
      loadList() // 分析结果会写回 analysis 字段，顺手刷新列表
    } catch (e) {
      setAi({ state: 'error', text: '', err: e?.message || 'AI 分析接口调用失败' })
    }
  }

  /* ---------------- 挂接 / 解除知识点 ---------------- */
  const reloadDetail = async () => {
    const d = await errorsApi.knowledgePoints(selectedId)
    const list = Array.isArray(d?.items) ? d.items : Array.isArray(d) ? d : []
    setDetail({ state: 'ok', kps: list, kpErr: '' })
  }

  const doLink = async () => {
    if (selectedId == null || !linkKp) return
    setLinking(true)
    try {
      await errorsApi.linkKnowledge(selectedId, { knowledge_point_id: Number(linkKp) })
      await reloadDetail()
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
      await reloadDetail()
      toast('已解除关联')
    } catch (e) {
      toast(`解除失败：${e?.message || '未知错误'}`)
    }
  }

  /* ---------------- 首屏加载骨架（复用统一三态组件） ---------------- */
  if (listState === 'loading') {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1 className="page-title">错题复盘</h1>
            <div className="page-sub">错因分布 · 薄弱知识点 · 单题 AI 归因</div>
          </div>
        </div>
        <div className="card er-card">
          <div className="card-head">
            <div>
              <div className="card-title">错题清单</div>
              <div className="card-sub">正在读取 /api/errors…</div>
            </div>
          </div>
          <div className="card-body">
            <LoadingState text="正在读取 /api/errors…" rows={6} />
          </div>
        </div>
      </div>
    )
  }

  /* ---------------- 列表接口失败：统一错误态 + 重试 ---------------- */
  if (listState === 'error') {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1 className="page-title">错题复盘</h1>
            <div className="page-sub">错因分布 · 薄弱知识点 · 单题 AI 归因</div>
          </div>
        </div>
        <div className="card er-card">
          <ErrorState
            title="错题列表加载失败"
            message={listErr}
            onRetry={loadList}
            retryText="重新加载"
          />
        </div>
      </div>
    )
  }

  /* 三态计数（来自 /api/errors/stats，标签同后端 kp_mastery.STATE_LABELS） */
  const stateCount = (s) => (stats ? stats[s] : null)

  return (
    <div className="page">
      {/* 页头 */}
      <div className="page-head">
        <div>
          <h1 className="page-title">错题复盘</h1>
          <div className="page-sub">错因分布 · 薄弱知识点 · 单题 AI 归因与知识点挂接</div>
        </div>
        <div className="page-actions" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ position: 'relative' }}>
            <button className="btn ghost" onClick={() => setShowFieldPicker((v) => !v)}>
              <FileText size={15} /> 字段 {showFieldPicker ? '▴' : '▾'}
            </button>
            {showFieldPicker && (
              <div className="panel" style={{ position: 'absolute', right: 0, top: '110%', zIndex: 20, minWidth: 200, padding: 10, boxShadow: '0 8px 24px rgba(0,0,0,.15)' }}>
                <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 8 }}>勾选要在详情里显示的字段</div>
                {DETAIL_FIELDS.map((f) => (
                  <label key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, padding: '4px 0', cursor: 'pointer' }}>
                    <input type="checkbox" checked={visibleFields.has(f.key)} onChange={() => toggleField(f.key)} />
                    {f.label}
                  </label>
                ))}
                <button className="btn ghost" style={{ marginTop: 6, fontSize: 12, padding: '4px 8px' }}
                  onClick={() => { setVisibleFields(new Set(DEFAULT_VISIBLE)); localStorage.setItem(FIELD_VISIBILITY_KEY, JSON.stringify(DEFAULT_VISIBLE)) }}>
                  恢复默认
                </button>
              </div>
            )}
          </div>
          <button className="btn ghost" onClick={() => { loadList(); loadStats() }} disabled={loading}>
            <RefreshCw size={15} /> 刷新
          </button>
        </div>
      </div>

      {/* 复盘总览：GET /api/errors/stats（与仪表盘同一聚合函数） */}
      <div className="er-stat-row">
        {statsErr ? (
          <div className="card er-card er-inline-error">
            <AlertCircle size={14} />
            <span>错题统计不可用：{statsErr}</span>
          </div>
        ) : (
          <>
            <StatTile label="活跃错题" value={stats?.active_errors} />
            <StatTile label="今日待复盘" value={stats?.due_errors} tone="warn" />
            <StatTile label="未学" value={stateCount('unlearned')} tone="muted" />
            <StatTile label="薄弱" value={stateCount('weak')} tone="warn" />
            <StatTile label="已掌握" value={stateCount('mastered')} tone="ok" />
          </>
        )}
      </div>

      {/* 筛选：掌握度（三态）/ 错因 / 学科（均来自 API） */}
      <div className="er-filterbar">
        <Target size={15} className="er-filterbar-icon" />
        <span className="er-filter-label">掌握度</span>
        <div className="kb-chips" role="group" aria-label="掌握度筛选">
          <button
            className={`kb-chip ${masteryState === '' ? 'active' : ''}`}
            onClick={() => pickMastery('')}
          >
            全部
            {stats && <small>{stats.total}</small>}
          </button>
          {MASTERY_STATES.map((s) => {
            const label = (stats?.labels && stats.labels[s]) || MASTERY_FALLBACK_LABEL[s]
            const count = stateCount(s)
            return (
              <button
                key={s}
                className={`kb-chip ${masteryState === s ? 'active' : ''}`}
                onClick={() => pickMastery(s)}
              >
                {label}
                {count != null && <small>{count}</small>}
              </button>
            )
          })}
        </div>
      </div>

      <div className="er-filterbar">
        <FileText size={15} className="er-filterbar-icon" />
        <span className="er-filter-label">错因</span>
        <div className="kb-chips" role="group" aria-label="错因筛选">
          <button
            className={`kb-chip ${errorReason === '' ? 'active' : ''}`}
            onClick={() => pickReason('')}
          >
            全部
          </button>
          {reasons.map((r) => (
            <button
              key={r.reason}
              className={`kb-chip ${errorReason === r.reason ? 'active' : ''}`}
              onClick={() => pickReason(r.reason)}
            >
              {r.reason}
              {r.count > 0 && <small>{r.count}</small>}
            </button>
          ))}
        </div>
      </div>

      <div className="er-filterbar">
        <Activity size={15} className="er-filterbar-icon" />
        <span className="er-filter-label">学科</span>
        <div className="kb-chips" role="group" aria-label="学科筛选">
          <button
            className={`kb-chip ${subject === '' ? 'active' : ''}`}
            onClick={() => pickSubject('')}
          >
            全部
          </button>
          {subjectOptions.map((s) => (
            <button
              key={s.subject}
              className={`kb-chip ${subject === s.subject ? 'active' : ''}`}
              onClick={() => pickSubject(s.subject)}
            >
              {s.subject}
              {s.count > 0 && <small>{s.count}</small>}
            </button>
          ))}
        </div>
      </div>
      {subjectErr && (
        <div className="er-inline-error"><AlertCircle size={14} /><span>学科接口失败：{subjectErr}</span></div>
      )}

      <div className="er-layout">
        {/* 左：错题列表 */}
        <div className="card er-card">
          <div className="card-head">
            <div>
              <div className="card-title">错题清单</div>
              <div className="card-sub">
                共 <b>{total}</b> 条 · 第 {page} / {Math.max(totalPages, 1)} 页
                {loading && ' · 加载中…'}
              </div>
            </div>
          </div>
          <div className="card-body">
            {items.length === 0 ? (
              <Empty
                icon={<FileText size={44} />}
                title="当前筛选条件下没有错题"
                desc="换个掌握度 / 错因 / 学科，或先去「电子错题本」录入错题。"
              />
            ) : (
              <div className="er-list">
                {items.map((e) => {
                  const open = selectedId === e.id
                  const state = e.mastery_state || 'unlearned'
                  return (
                    <button
                      key={e.id}
                      className={`er-row ${open ? 'active' : ''}`}
                      onClick={() => selectError(e)}
                    >
                      <div className="er-row-top">
                        <span className={`er-status ${MASTERY_TONE[state] || 'muted'}`}>
                          {e.mastery_label || MASTERY_FALLBACK_LABEL[state] || state}
                        </span>
                        <span className="er-subj">{e.subject || '未分类'}</span>
                        <span className="er-reason">{e.error_reason || '未标注错因'}</span>
                        <span className="er-meta">
                          复习 {e.review_count || 0} 次 · 正确率 {Math.round((Number(e.accuracy) || 0) * 100)}%
                        </span>
                      </div>
                      <div className="er-row-q">
                        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        <span>{e.content || '（题干为空）'}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}

            {totalPages > 1 && (
              <div className="er-pager">
                <button className="btn ghost" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
                  上一页
                </button>
                <span className="er-pager-txt">{page} / {totalPages}</span>
                <button className="btn ghost" disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)}>
                  下一页
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 右：详情 + 知识点关联 + AI 分析 */}
        <div className="er-side">
          <div className="card er-card">
            <div className="card-head">
              <div>
                <div className="card-title">错题详情</div>
                <div className="card-sub">
                  {selected ? `#${selected.id} · ${selected.subject || '未分类'} · ${selected.mastery_label || ''}` : '请从左侧选择一条错题'}
                </div>
              </div>
              {selected && (
                <button className="btn primary er-ai-btn" onClick={runAiAnalyze} disabled={ai.state === 'loading'}>
                  <Brain size={14} />
                  {ai.state === 'loading' ? '分析中…' : 'AI 归因分析'}
                </button>
              )}
            </div>
            <div className="card-body">
              {!selected ? (
                <Empty icon={<Brain size={40} />} title="尚未选择错题" desc="点击左侧任意一条错题查看详情、知识点与 AI 分析。" />
              ) : (
                <>
                  <div className="er-q">{selected.content || '（题干为空）'}</div>
                  <div className="er-answers">
                    <div className="er-ans wrong">
                      <span className="er-ans-label">我的答案</span>
                      <span>{selected.my_answer || '—'}</span>
                    </div>
                    <div className="er-ans right">
                      <span className="er-ans-label">正确答案</span>
                      <span>{selected.correct_answer || '—'}</span>
                    </div>
                  </div>
                  <div className="er-kv">
                    {DETAIL_FIELDS.filter((f) => visibleFields.has(f.key)).map((f) => (
                      <React.Fragment key={f.key}>
                        <span>{f.label}</span>
                        <b>{f.fmt ? f.fmt(selected[f.key]) : (selected[f.key] ?? '—') || '—'}</b>
                      </React.Fragment>
                    ))}
                    {visibleFields.has('tags') && parseTags(selected.tags).length > 0 && (
                      <span>标签</span>
                    )}
                    {visibleFields.has('tags') && parseTags(selected.tags).length > 0 && (
                      <b className="er-tags" style={{ gridColumn: '2' }}>
                        {parseTags(selected.tags).map((t) => <span className="er-tag" key={t}>{t}</span>)}
                      </b>
                    )}
                  </div>
                  {parseTags(selected.tags).length > 0 && !visibleFields.has('tags') && (
                    <div className="er-tags">
                      {parseTags(selected.tags).map((t) => <span className="er-tag" key={t}>{t}</span>)}
                    </div>
                  )}

                  {/* AI 分析结果 */}
                  {ai.state === 'error' && (
                    <div className="er-ai er-ai-error">
                      <AlertCircle size={15} />
                      <div>
                        <div className="er-ai-title">AI 分析失败</div>
                        <div className="er-ai-err">{ai.err}</div>
                      </div>
                    </div>
                  )}
                  {ai.state === 'ok' && (
                    <div className="er-ai er-ai-ok">
                      <Brain size={15} />
                      <div>
                        <div className="er-ai-title">AI 归因分析</div>
                        <div className="er-ai-body">{ai.text}</div>
                      </div>
                    </div>
                  )}
                  {ai.state === 'idle' && selected.analysis && (
                    <div className="er-ai er-ai-ok">
                      <Brain size={15} />
                      <div>
                        <div className="er-ai-title">已有分析</div>
                        <div className="er-ai-body">{selected.analysis}</div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* 知识点关联（按实际链路展示） */}
          <div className="card er-card">
            <div className="card-head">
              <div>
                <div className="card-title">知识点关联</div>
                <div className="card-sub">
                  「题目关联」来自题目的人工校验链路，最可信；「自动」为启发式挂接，仅供参考
                </div>
              </div>
            </div>
            <div className="card-body">
              {!selected ? (
                <div className="er-muted">选择一条错题后可查看 / 挂接知识点。</div>
              ) : (
                <>
                  {detail.state === 'loading' && <div className="loading-inline">知识点加载中…</div>}
                  {detail.state === 'error' && (
                    <div className="er-inline-error">
                      <AlertCircle size={14} />
                      <span>知识点关联读取失败：{detail.kpErr}</span>
                    </div>
                  )}
                  {detail.state === 'ok' && detail.kps.length === 0 && (
                    <div className="er-muted">该错题尚未关联任何知识点（题目侧也未校验）。</div>
                  )}
                  {detail.state === 'ok' && detail.kps.length > 0 && (
                    <div className="er-kp-list">
                      {detail.kps.map((k) => (
                        <div className="er-kp" key={k.link_id ?? `q-${k.knowledge_point_id}`}>
                          <Map size={14} />
                          <div className="er-kp-main">
                            <div className="er-kp-name">
                              {k.name || k.kp_name || `知识点 #${k.knowledge_point_id}`}
                              {k.verified && <span className="er-tag" style={{ marginLeft: 6 }}>已校验</span>}
                            </div>
                            <div className="er-kp-sub">
                              {[k.subject, k.chapter].filter(Boolean).join(' · ') || '—'}
                              {k.state_label && (
                                <>
                                  {' · '}
                                  <span className={`er-status ${MASTERY_TONE[k.state] || 'muted'}`}>{k.state_label}</span>
                                </>
                              )}
                              {' · '}
                              {LINK_SOURCE_LABEL[k.source] || k.source || '未知来源'}
                              {k.relevance != null && ` · 关联度 ${Math.round(Number(k.relevance) * 100)}%`}
                            </div>
                          </div>
                          {k.link_id != null ? (
                            <button
                              className="btn mini ghost"
                              onClick={() => doUnlink(k.link_id)}
                              title="解除这条自动/手动挂接"
                            >
                              解除
                            </button>
                          ) : (
                            <span className="er-muted" style={{ fontSize: 12, flexShrink: 0 }} title="来自题目的人工校验关联，需在题库侧调整">题目侧</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 挂接：候选来自 /api/taxonomy/knowledge-points（真实知识点） */}
                  <div className="er-link-row">
                    <select
                      className="form-input er-select"
                      value={linkKp}
                      onChange={(e) => setLinkKp(e.target.value)}
                    >
                      <option value="">
                        {kpChoices.length ? '选择知识点…' : '知识点接口不可用，暂无候选'}
                      </option>
                      {kpChoices.map((c) => (
                        <option key={c.id} value={c.id}>{c.label}</option>
                      ))}
                    </select>
                    <button className="btn primary" onClick={doLink} disabled={!linkKp || linking}>
                      {linking ? '关联中…' : '关联'}
                    </button>
                  </div>
                  {kpChoicesErr && <div className="er-inline-error"><AlertCircle size={14} /><span>知识点接口失败：{kpChoicesErr}</span></div>}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* 总览小卡（数值来自 /api/errors/stats，与仪表盘同一聚合函数） */
function StatTile({ label, value, tone }) {
  return (
    <div className={`card er-stat ${tone ? `er-stat-${tone}` : ''}`}>
      <div className="er-stat-num">{value == null ? '—' : value}</div>
      <div className="er-stat-label">{label}</div>
    </div>
  )
}
