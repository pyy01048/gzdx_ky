import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { taxonomyApi, reviewApi, quizApi, qualityApi } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { chatCompletion, defaultProvider, recordUsage } from '../../utils/api'
import {
  Alert, AnimatedNumber, Badge, Button, Card, CardHead, Chip, Empty, IconButton, Input,
  PageHeader, Progress, Ring, Skeleton, Spinner, Tile, cx, toastErr, toastOk,
} from '../ui'
import {
  AlertCircle, ArrowRight, BookOpen, Brain, CheckCircle2, ChevronRight, Clock, Database,
  Eye, Map as MapIcon, Play, RefreshCw, Search, Sparkles, Target, X,
} from '../icons'
import '../styles/kb-v3.css'

/* ==========================================================================
   知识地图 · Aurora v3
   沿章节推进的复习动线：章节 → 知识点 → 例题 / 方法。
   数据全部来自 /taxonomy + /review + /quality，访客只跳过登录态接口。
   ========================================================================== */

const TYPE_LABEL = {
  single: '单选',
  judge: '判断',
  fill: '填空',
  essay: '简答',
  calc: '计算',
  draw: '作图',
}

function typeLabel(t) {
  return TYPE_LABEL[t] || t || ''
}

/* 掌握度三态，与后端 services/kp_mastery.py 口径一致 */
const STATE_TONE = {
  unlearned: { cls: 'new', label: '未学', badge: undefined },
  weak: { cls: 'mid', label: '薄弱', badge: 'warning' },
  mastered: { cls: 'ok', label: '已掌握', badge: 'success' },
}

function stateTone(state) {
  return STATE_TONE[state] || STATE_TONE.unlearned
}

/* 优先使用后端下发的 state；老接口缺字段时按 (mastery, review_count) 兜底 */
function kpState(kp) {
  if (kp && STATE_TONE[kp.state]) return kp.state
  const m = Number(kp && kp.mastery) || 0
  if (m >= 70) return 'mastered'
  return kp && kp.review_count > 0 ? 'weak' : 'unlearned'
}

/* 只有数值的场景（均分）：≥70 已掌握，否则薄弱 */
function masteryTone(m) {
  return (Number(m) || 0) >= 70 ? STATE_TONE.mastered : STATE_TONE.weak
}

/* 聚合节点：全部未学 → 灰；否则按已学平均掌握度取黄 / 绿 */
function nodeTone(node) {
  const total = (node && (node.knowledge_point_count ?? node.total)) || 0
  const unlearned = (node && node.unlearned_count) || 0
  if (total > 0 && unlearned >= total) return STATE_TONE.unlearned
  return masteryTone((node && (node.learned_avg_mastery ?? node.avg_mastery)) || 0)
}

function nodeAvg(node) {
  return (node && (node.learned_avg_mastery ?? node.avg_mastery)) ?? 0
}

const REVIEW_ACTIONS = [
  { result: 'mastered', label: '会', cls: 'ok' },
  { result: 'fuzzy', label: '模糊', cls: 'warn' },
  { result: 'forgotten', label: '不会', cls: 'danger' },
]

/* 兼容 /taxonomy/subjects 的两种返回：数组或 {subjects:[...]} */
function normalizeSubjects(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.subjects)) return data.subjects
  if (data && Array.isArray(data.items)) return data.items
  return []
}

const isNum = (v) => v != null && Number.isFinite(Number(v))

function MetricValue({ value, suffix }) {
  if (!isNum(value)) return <span className="v3-kb-stat__empty">—</span>
  return (
    <>
      <AnimatedNumber value={Number(value)} />
      {suffix ? <em>{suffix}</em> : null}
    </>
  )
}

function StateDot({ tone, title }) {
  return <span className={cx('v3-kb-dot', `is-${tone}`)} title={title} aria-hidden="true" />
}

function Meter({ value, tone, height = 6 }) {
  return (
    <Progress
      value={Math.min(100, Math.max(0, Number(value) || 0))}
      height={height}
      className={cx('v3-kb-meter', `is-${tone}`)}
    />
  )
}

function Highlighted({ text = '', query = '' }) {
  const q = query.trim()
  if (!q) return <>{text}</>
  const idx = text.toLowerCase().indexOf(q.toLowerCase())
  if (idx < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <mark className="v3-kb-mark">{text.slice(idx, idx + q.length)}</mark>
      {text.slice(idx + q.length)}
    </>
  )
}

function TypeTags({ types = [], max = 4 }) {
  const list = (types || []).slice(0, max)
  if (list.length === 0) return null
  return (
    <span className="v3-kb-types">
      {list.map((t) => <span className="v3-kb-type" key={t}>{typeLabel(t)}</span>)}
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* Chapter group                                                              */
/* -------------------------------------------------------------------------- */
function SubjectGroup({ group, activeChapter, quality, onSelectChapter }) {
  const tone = nodeTone(group.node)
  const avg = nodeAvg(group.node)
  const confOk = quality && Number(quality.avg_confidence) >= 0.4
  return (
    <section className="v3-kb-subject">
      <div className="v3-kb-subject__head">
        <div className="v3-kb-subject__titles">
          <div className="v3-kb-subject__name">
            {group.subject}
            {!group.is_core ? <Badge tone="outline">拓展</Badge> : null}
          </div>
          <div className="v3-kb-subject__meta">
            <span>知识点 {group.node.knowledge_point_count ?? 0}</span>
            <span>{group.node.outline_chapter_count ?? group.chapters.length} 章节</span>
            {quality ? (
              <span
                className={cx('v3-kb-corpus', confOk ? 'is-ok' : 'is-low')}
                title={`可检索语料块 ${quality.chunks} · 平均打标置信 ${(Number(quality.avg_confidence) * 100).toFixed(1)}% · 弃权 ${quality.abstained_chunks ?? 0} 块 · 低置信 ${quality.low_conf_chunks ?? 0} 块`}
              >
                <Database size={12} />
                语料 {quality.chunks}
                <em>{(Number(quality.avg_confidence) * 100).toFixed(0)}%</em>
              </span>
            ) : null}
          </div>
        </div>
        <Badge tone={tone.badge}>
          {tone.cls === 'new' ? '未学' : `均分 ${avg}%`}
        </Badge>
      </div>

      <div className="v3-kb-chapters">
        {group.chapters.map((ch) => {
          const hasData = ch.knowledge_point_count > 0
          const isSel = !!activeChapter
            && activeChapter.subject === group.subject
            && activeChapter.title === ch.title
          const chTone = nodeTone(ch)
          return (
            <button
              key={ch.title}
              type="button"
              className={cx('v3-kb-chapter', isSel && 'is-selected', !hasData && 'is-empty')}
              onClick={() => hasData && onSelectChapter(group.subject, ch.title, ch.knowledge_points)}
              disabled={!hasData}
              aria-current={isSel ? 'true' : undefined}
              title={hasData ? `查看「${ch.title}」的知识点` : '该章节暂无资料'}
            >
              <span className="v3-kb-chapter__main">
                <ChevronRight size={13} className="v3-kb-chapter__chev" />
                <span className="v3-kb-chapter__title">{ch.title}</span>
                <span className="v3-kb-chapter__count">
                  {hasData ? `${ch.knowledge_point_count} 个` : '暂无资料'}
                </span>
              </span>
              {hasData ? <Meter value={nodeAvg(ch)} tone={chTone.cls} height={4} /> : null}
            </button>
          )
        })}
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Knowledge point card                                                       */
/* -------------------------------------------------------------------------- */
function PointCard({ kp, selected, path, query, onOpen, onPreview, onPractice }) {
  const st = stateTone(kpState(kp))
  const mastery = Math.min(100, Math.max(0, Number(kp.mastery) || 0))
  return (
    <div className={cx('v3-kb-point', selected && 'is-selected')}>
      <button
        type="button"
        className="v3-kb-point__main"
        onClick={onOpen}
        title={`阅读「${kp.name}」：考纲要求 · 教材原文 · 主动回忆`}
      >
        {path ? <span className="v3-kb-point__path">{path}</span> : null}
        <span className="v3-kb-point__title">
          <StateDot tone={st.cls} title={`掌握度 ${mastery}（${st.label}）`} />
          <span className="v3-kb-point__name"><Highlighted text={kp.name} query={query} /></span>
          <span className={cx('v3-kb-point__pct', `is-${st.cls}`)}>
            {st.cls === 'new' ? '未学' : `${mastery}%`}
          </span>
        </span>
        <Meter value={mastery} tone={st.cls} height={5} />
        <span className="v3-kb-point__meta">
          <span>{kp.review_count ? `已复习 ${kp.review_count} 次` : '未复习'}</span>
          <TypeTags types={kp.question_types} />
        </span>
      </button>
      <div className="v3-kb-point__actions">
        <IconButton
          label="在右栏查看详情"
          size="sm"
          icon={<Eye size={15} />}
          onClick={onPreview}
        />
        <Button
          size="sm"
          variant="tonal"
          icon={<Play size={13} />}
          onClick={onPractice}
          title="按该知识点精确出题"
        >
          练习
        </Button>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Detail pane                                                                */
/* -------------------------------------------------------------------------- */
function DetailPanel({
  selectedKpId, detail, kpQCount, aiExplain, detailReviewing, user,
  onRetry, onPractice, onOpenArticle, onOpenError, onRunAiExplain, onToggleAi, onReview, onLogin,
  onGoAllQuestions,
}) {
  if (selectedKpId == null) {
    return (
      <Empty
        className="v3-kb-detail-empty"
        icon={<Target size={22} />}
        title="选择一个知识点"
        text="从左侧选择章节，或在中间点选知识点 —— 这里会显示方法要点、例题原文、关联错题与复习打卡。"
      />
    )
  }

  if (detail.loading) {
    return (
      <div className="v3-kb-detail-skeleton" aria-label="详情加载中">
        <Skeleton height={28} width="62%" />
        <Skeleton height={14} width="40%" />
        <Skeleton height={86} />
        <Skeleton height={62} />
        <Skeleton height={132} />
      </div>
    )
  }

  if (detail.error) {
    return (
      <Empty
        icon={<AlertCircle size={22} />}
        title="知识点详情加载失败"
        text={detail.error}
        action={<Button size="sm" variant="tonal" onClick={onRetry}>重试</Button>}
      />
    )
  }

  if (!detail.data) return null
  const d = detail.data
  const st = stateTone(kpState(d))
  const mastery = Math.min(100, Math.max(0, Number(d.mastery) || 0))
  const chunks = d.related_chunks || []
  const errors = d.related_errors || []
  const types = d.question_types || []

  return (
    <div className="v3-kb-detail">
      <div className="v3-kb-detail__head">
        <div className="v3-kb-detail__titles">
          <div className="v3-kb-detail__name">{d.name}</div>
          <div className="v3-kb-detail__path">
            {d.subject || '未分类'}{d.chapter ? ` · ${d.chapter}` : ''}
          </div>
        </div>
        <Badge tone={st.badge}>{st.label}</Badge>
      </div>

      <div className="v3-kb-detail__meta">
        <div>
          <span>掌握度</span>
          <b className={cx('v3-kb-tone', `is-${st.cls}`)}>
            {st.cls === 'new' ? '未学' : `${mastery}%`}
          </b>
        </div>
        <div>
          <span>考频</span>
          <b>{d.exam_frequency ?? '—'}</b>
        </div>
        <div>
          <span>难度</span>
          <b>{d.difficulty ?? '—'}</b>
        </div>
        <div>
          <span>关联题量</span>
          <b>{kpQCount == null ? '—' : `${kpQCount} 题`}</b>
        </div>
      </div>

      {/* 无关联题：友好提示 + 「去全部题」兜底（跳到该科目全部题） */}
      {kpQCount === 0 ? (
        <div className="v3-kb-detail__noquiz" role="status">
          <AlertCircle size={13} />
          <span>该知识点暂无关联题目，可先去该科目题库刷全部题。</span>
        </div>
      ) : null}

      <div className="v3-kb-detail__actions">
        <Button
          variant="gradient"
          icon={<Play size={15} />}
          onClick={() => (kpQCount === 0
            ? onGoAllQuestions(d.subject)
            : onPractice(d.subject, d.chapter, { id: d.id, name: d.name }))}
        >
          开始练习
        </Button>
        <Button
          variant="tonal"
          icon={<Sparkles size={15} />}
          loading={aiExplain.loading}
          onClick={onRunAiExplain}
        >
          AI 精讲
        </Button>
        <Button variant="text" icon={<BookOpen size={15} />} onClick={() => onOpenArticle(d.id)}>
          进入精读
        </Button>
      </div>

      {aiExplain.open ? (
        <section className="v3-kb-detail__section v3-kb-ai" aria-label="AI 精讲">
          <div className="v3-kb-detail__section-head">
            <span><Sparkles size={14} /> AI 精讲</span>
            {!aiExplain.loading && !aiExplain.error ? (
              <button type="button" className="v3-kb-text-btn" onClick={onToggleAi}>
                {aiExplain.text ? '收起' : '关闭'}
              </button>
            ) : null}
          </div>
          {aiExplain.loading ? (
            <div className="v3-kb-ai__loading">
              <Spinner size={16} /> 正在生成讲解…
            </div>
          ) : aiExplain.error ? (
            <Alert tone="danger">{aiExplain.error}</Alert>
          ) : (
            <div className="v3-kb-ai__text">{aiExplain.text}</div>
          )}
        </section>
      ) : null}

      {types.length > 0 ? (
        <section className="v3-kb-detail__section">
          <div className="v3-kb-detail__section-head"><span>涉及题型</span></div>
          <div className="v3-kb-tagrow">
            {types.map((t) => <Badge key={t} tone="outline">{typeLabel(t)}</Badge>)}
          </div>
        </section>
      ) : null}

      <section className="v3-kb-detail__section">
        <div className="v3-kb-detail__section-head"><span>方法 / 要点</span></div>
        {d.description ? (
          <p className="v3-kb-detail__desc">{d.description}</p>
        ) : (
          <p className="v3-kb-note">该知识点暂无方法说明。</p>
        )}
      </section>

      <section className="v3-kb-detail__section">
        <div className="v3-kb-detail__section-head">
          <span>例题 / 原文摘录</span>
          <Badge tone="outline">{chunks.length}</Badge>
        </div>
        {chunks.length === 0 ? (
          <p className="v3-kb-note">该知识点暂无关联原文。</p>
        ) : (
          <div className="v3-kb-chunks">
            {chunks.map((c) => (
              <div className="v3-kb-chunk" key={c.chunk_id}>
                {c.doc_name ? <div className="v3-kb-chunk__src">{c.doc_name}</div> : null}
                <div className="v3-kb-chunk__text">{c.text || '（无文本）'}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="v3-kb-detail__section">
        <div className="v3-kb-detail__section-head">
          <span>关联错题</span>
          <Badge tone="outline">{errors.length}</Badge>
        </div>
        {errors.length === 0 ? (
          <p className="v3-kb-note">暂无关联错题。</p>
        ) : (
          <div className="v3-kb-errors">
            {errors.map((e) => (
              <div className="v3-kb-error" key={e.id}>
                <div className="v3-kb-error__content">{e.content || '（无题干）'}</div>
                <div className="v3-kb-error__meta">
                  <span>我的答案：{e.my_answer || '—'}</span>
                  <span>正确答案：{e.correct_answer || '—'}</span>
                  {e.error_reason ? <span>错因：{e.error_reason}</span> : null}
                </div>
                <Button
                  size="sm"
                  variant="text"
                  onClick={() => onOpenError(`/error-review?error_id=${e.id}&subject=${encodeURIComponent(e.subject || d.subject || '')}`)}
                >
                  去复盘
                </Button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="v3-kb-detail__section v3-kb-checkin">
        <div className="v3-kb-detail__section-head">
          <span>复习打卡</span>
          {d.review_count > 0 ? <Badge tone="outline">已复习 {d.review_count} 次</Badge> : null}
        </div>
        {user ? (
          <>
            <div className="v3-kb-review-actions">
              {REVIEW_ACTIONS.map((r) => (
                <button
                  key={r.result}
                  type="button"
                  className={cx('v3-kb-mini', `is-${r.cls}`)}
                  disabled={detailReviewing}
                  onClick={() => onReview(r.result)}
                >
                  {r.label}
                </button>
              ))}
            </div>
            <p className="v3-kb-note">
              {d.review_count > 0
                ? `下次复习 ${d.next_review ? String(d.next_review).slice(0, 10) : '—'} · 提交后立即重排`
                : '提交后按记忆曲线排入下一次复习。'}
            </p>
          </>
        ) : (
          <>
            <p className="v3-kb-note">访客模式不写入复习记录。登录后可记录「会 / 模糊 / 不会」，系统会按记忆曲线重排下次复习。</p>
            <Button size="sm" variant="tonal" onClick={onLogin}>登录后打卡</Button>
          </>
        )}
      </section>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */
export default function KbMap() {
  const { user, isAdmin } = useAuth()
  const [subjects, setSubjects] = useState([])
  const [tree, setTree] = useState([])
  const [progress, setProgress] = useState(null)
  const [due, setDue] = useState([])
  const [coverage, setCoverage] = useState(null)
  const [quality, setQuality] = useState(null)
  const [status, setStatus] = useState('loading')
  const [treeLoading, setTreeLoading] = useState(false)
  const [activeSubject, setActiveSubject] = useState('')
  const [reviewing, setReviewing] = useState(null)
  const [errMsg, setErrMsg] = useState('')
  const [query, setQuery] = useState('')

  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [activeChapter, setActiveChapter] = useState(null)
  const [selectedKpId, setSelectedKpId] = useState(null)
  const [detail, setDetail] = useState({ loading: false, error: '', data: null })
  const [kpQCount, setKpQCount] = useState(null)
  const [detailReviewing, setDetailReviewing] = useState(false)
  const detailSeq = useRef(0)

  const [aiExplain, setAiExplain] = useState({ open: false, loading: false, text: '', error: '' })
  const aiSeq = useRef(0)
  const resetAiExplain = useCallback(() => {
    aiSeq.current += 1
    setAiExplain({ open: false, loading: false, text: '', error: '' })
  }, [])

  const bootstrappedRef = useRef(false)
  const selectedIdRef = useRef(null)
  const paramsRef = useRef(searchParams)
  paramsRef.current = searchParams

  /* 打开详情：详情 + 关联题量并行拉取，各自容错，防竞态 */
  const openDetail = useCallback(async (kp) => {
    const id = kp?.id
    if (id == null) return
    selectedIdRef.current = id
    setSelectedKpId(id)
    resetAiExplain()
    const seq = ++detailSeq.current
    setDetail({ loading: true, error: '', data: null })
    setKpQCount(null)
    const [detRes, qRes] = await Promise.allSettled([
      taxonomyApi.knowledgePoint(id),
      // 访客不请求登录态接口，避免 401 触发全局登录引导
      user ? quizApi.questions({ kp_id: id, page_size: 1 }) : Promise.resolve(null),
    ])
    if (seq !== detailSeq.current) return
    if (detRes.status === 'fulfilled' && detRes.value) {
      setDetail({ loading: false, error: '', data: detRes.value })
    } else {
      setDetail({
        loading: false,
        error: detRes.reason?.message || '知识点详情加载失败',
        data: null,
      })
    }
    // 题量查询失败时显示 '—'，绝不伪造 0（访客访问 quiz 接口会 401）
    setKpQCount(
      qRes.status === 'fulfilled' && qRes.value && typeof qRes.value.total === 'number'
        ? qRes.value.total
        : null,
    )
  }, [resetAiExplain, user])

  const closeDetail = useCallback(() => {
    detailSeq.current += 1
    selectedIdRef.current = null
    setSelectedKpId(null)
    setDetail({ loading: false, error: '', data: null })
    setKpQCount(null)
    resetAiExplain()
  }, [resetAiExplain])

  const loadAll = useCallback(async () => {
    setStatus('loading')
    setErrMsg('')
    try {
      const [sj, t, p, d, c, q] = await Promise.all([
        taxonomyApi.subjects(),
        taxonomyApi.tree(),
        user ? reviewApi.progress() : Promise.resolve(null),
        user ? reviewApi.due({ limit: 30 }) : Promise.resolve(null),
        taxonomyApi.coverage(),
        isAdmin ? qualityApi.treeOverlay().catch(() => null) : Promise.resolve(null),
      ])
      setSubjects(normalizeSubjects(sj))
      const tNodes = t?.tree || []
      setTree(tNodes)
      setProgress(p)
      setDue(d?.items || [])
      setCoverage(c)
      setQuality(q)

      if (!bootstrappedRef.current) {
        bootstrappedRef.current = true
        const sp = paramsRef.current
        const urlSubject = (sp && sp.get('subject')) || ''
        const urlChapter = (sp && sp.get('chapter')) || ''
        const urlKpId = (sp && sp.get('kp_id')) || ''

        setActiveSubject(urlSubject)

        let chap = null
        let kp = null
        if (urlSubject && urlChapter) {
          const s = tNodes.find((x) => x.subject === urlSubject)
          const ch = s?.chapters?.find((x) => x.title === urlChapter)
          if (ch) chap = { subject: urlSubject, title: urlChapter }
        }
        if (!chap) {
          const first = tNodes.find((x) => x.knowledge_point_count > 0)
          const firstCh = first?.chapters?.find((x) => x.knowledge_point_count > 0)
          if (first && firstCh) chap = { subject: first.subject, title: firstCh.title }
        }
        setActiveChapter(chap)

        if (urlKpId) {
          kp = { id: urlKpId }
        } else if (chap) {
          const s = tNodes.find((x) => x.subject === chap.subject)
          const ch = s?.chapters?.find((x) => x.title === chap.title)
          kp = (ch?.knowledge_points || [])[0] || null
        }
        if (kp) openDetail(kp)
        else closeDetail()
      } else if (selectedIdRef.current != null) {
        openDetail({ id: selectedIdRef.current })
      }
      setStatus('ok')
    } catch (e) {
      setErrMsg(e?.message || '未知错误')
      setStatus('error')
    }
  }, [openDetail, closeDetail, user, isAdmin])

  useEffect(() => { loadAll() }, [loadAll])

  /* 切换科目：只重拉该科结构树，保留全局总览与队列 */
  const selectSubject = useCallback(async (name) => {
    if (name === activeSubject) return
    setActiveSubject(name)
    setQuery('')
    setTreeLoading(true)
    try {
      const t = await taxonomyApi.tree(name || undefined)
      const tNodes = t?.tree || []
      setTree(tNodes)
      const first = tNodes.find((s) => s.knowledge_point_count > 0)
      const firstCh = first?.chapters?.find((ch) => ch.knowledge_point_count > 0)
      if (first && firstCh) {
        setActiveChapter({ subject: first.subject, title: firstCh.title })
        const kp = (firstCh.knowledge_points || [])[0]
        if (kp) openDetail(kp)
        else closeDetail()
      } else {
        setActiveChapter(null)
        closeDetail()
      }
    } catch (e) {
      toastErr('加载知识结构失败：' + (e?.message || ''))
    } finally {
      setTreeLoading(false)
    }
  }, [activeSubject, openDetail, closeDetail])

  const selectChapter = useCallback((subject, title, kpList) => {
    setActiveChapter({ subject, title })
    const kp = (kpList || [])[0]
    if (kp) openDetail(kp)
    else closeDetail()
  }, [openDetail, closeDetail])

  const submitReview = async (kpId, result) => {
    if (!user) {
      toastErr('登录后才能记录复习结果')
      return
    }
    setReviewing(kpId)
    try {
      const r = await reviewApi.submit({ item_type: 'knowledge', item_id: kpId, result })
      toastOk(`已记录：掌握度 ${r.mastery_before} → ${r.mastery_after}，${r.interval} 天后复习`)
      await loadAll()
    } catch (e) {
      toastErr('记录失败：' + (e?.message || ''))
    } finally {
      setReviewing(null)
    }
  }

  const submitDetailReview = async (result) => {
    const id = detail.data?.id ?? selectedKpId
    if (id == null) return
    if (!user) {
      toastErr('登录后才能记录复习结果')
      return
    }
    setDetailReviewing(true)
    try {
      const r = await reviewApi.submit({ item_type: 'knowledge', item_id: id, result })
      toastOk(`已记录：掌握度 ${r.mastery_before} → ${r.mastery_after}，${r.interval} 天后复习`)
      await Promise.all([openDetail({ id }), loadAll()])
    } catch (e) {
      toastErr('记录失败：' + (e?.message || ''))
    } finally {
      setDetailReviewing(false)
    }
  }

  const goQuiz = useCallback((subject, chapter, kp) => {
    const params = new URLSearchParams()
    if (subject) params.set('subject', subject)
    if (chapter) params.set('chapter', chapter)
    if (kp?.id != null) params.set('kp_id', kp.id)
    if (kp?.name) params.set('kp_name', kp.name)
    navigate(`/quiz?${params.toString()}`)
  }, [navigate])

  const runAiExplain = async () => {
    const d = detail.data
    if (!d || aiExplain.loading) return
    const seq = ++aiSeq.current
    setAiExplain({ open: true, loading: true, text: '', error: '' })
    const tone = stateTone(kpState(d))
    const prompt = [
      `请为考研知识点「${d.name}」（科目：${d.subject || '未分类'}${d.chapter ? ' · ' + d.chapter : ''}）做一次精讲。`,
      `该知识点当前掌握度 ${d.mastery ?? 0}%（状态：${tone.label}），考频 ${d.exam_frequency ?? '未知'}，难度 ${d.difficulty ?? '未知'}。`,
      '请给出：1）核心概念与直觉解释；2）常用方法/公式；3）易错点；4）结合当前掌握状态给出 1-2 条针对性复习建议。用 markdown 列表，简洁。',
    ].join('\n')
    const provider = defaultProvider()
    try {
      const r = await chatCompletion(provider, [{ role: 'user', content: prompt }])
      if (seq !== aiSeq.current) return
      recordUsage(r.usage, provider?.id)
      setAiExplain((s) => ({ ...s, loading: false, text: r.text || '（AI 未返回内容）' }))
    } catch (e) {
      if (seq !== aiSeq.current) return
      setAiExplain((s) => ({ ...s, loading: false, error: `AI 精讲失败：${e?.message || '未知错误'}` }))
    }
  }

  /* 科目维度汇总（掌握度三态） */
  const dist = useMemo(() => {
    if (!progress) return null
    const total = progress.total_knowledge_points || 0
    const mastered = progress.mastered_count || 0
    const weak = progress.weak_count || 0
    const unlearned = progress.unlearned_count ?? Math.max(0, total - mastered - weak)
    return { total, mastered, weak, unlearned }
  }, [progress])

  /* 科目 chips：知识点数与题量并列展示，缺失字段不补 0 */
  const chipSubjects = useMemo(() => {
    const fallbackKpCounts = new Map()
    for (const s of (coverage?.subjects || [])) {
      fallbackKpCounts.set(s.subject, s.knowledge_points)
    }
    for (const s of tree) {
      fallbackKpCounts.set(s.subject, s.knowledge_point_count)
    }
    if (subjects.length > 0) {
      return subjects.map((s) => {
        const direct = typeof s.knowledge_point_count === 'number' ? s.knowledge_point_count : null
        const fallback = fallbackKpCounts.get(s.subject)
        const kp = direct == null
          ? fallback
          : (direct === 0 && typeof fallback === 'number' && fallback > 0 ? fallback : direct)
        return { ...s, knowledge_point_count: kp }
      })
    }
    return tree
      .filter((s) => s.knowledge_point_count > 0)
      .map((s) => ({ subject: s.subject, knowledge_point_count: s.knowledge_point_count }))
  }, [subjects, tree, coverage])

  const chipTotals = useMemo(() => {
    let kp = 0
    let q = 0
    let hasKp = false
    let hasQ = false
    for (const s of chipSubjects) {
      if (typeof s?.knowledge_point_count === 'number') { kp += s.knowledge_point_count; hasKp = true }
      if (typeof s?.question_count === 'number') { q += s.question_count; hasQ = true }
    }
    return { kp, q, hasKp, hasQ }
  }, [chipSubjects])

  const activeChip = useMemo(
    () => (activeSubject ? chipSubjects.find((s) => s.subject === activeSubject) || null : null),
    [chipSubjects, activeSubject],
  )

  const chapterGroups = useMemo(() => {
    const src = activeSubject ? tree.filter((s) => s.subject === activeSubject) : tree
    return src
      .map((s) => ({ subject: s.subject, is_core: s.is_core, node: s, chapters: s.chapters || [] }))
      .filter((g) => g.chapters.length > 0)
  }, [tree, activeSubject])

  const activeChapterData = useMemo(() => {
    if (!activeChapter) return null
    const s = tree.find((x) => x.subject === activeChapter.subject)
    const ch = s?.chapters?.find((c) => c.title === activeChapter.title)
    return ch ? { subject: activeChapter.subject, chapter: ch } : null
  }, [tree, activeChapter])

  /* 语料质量层：学科 → 块数 / 平均置信 / 弃权数 */
  const qualityBySubject = useMemo(() => {
    const m = new Map()
    for (const s of (quality && quality.subjects) || []) {
      m.set(s.subject, s)
      const k = String(s.subject || '').replace(/\s+/g, '')
      if (!m.has(k)) m.set(k, s)
    }
    return m
  }, [quality])

  const pickQuality = useCallback((name) => {
    if (!name) return null
    return qualityBySubject.get(name) || qualityBySubject.get(String(name).replace(/\s+/g, '')) || null
  }, [qualityBySubject])

  /* 客户端搜索：数据来自已加载的 taxonomy 树，不发请求、不造字段 */
  const searchPool = useMemo(() => {
    const out = []
    for (const s of tree) {
      for (const ch of (s.chapters || [])) {
        for (const kp of (ch.knowledge_points || [])) {
          out.push({ ...kp, subject: s.subject, chapter: ch.title })
        }
      }
    }
    return out
  }, [tree])

  const searchResults = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return searchPool
      .filter((kp) => String(kp.name || '').toLowerCase().includes(q))
      .slice(0, 60)
  }, [searchPool, query])

  const coverageTotals = useMemo(() => {
    let outline = 0
    let covered = 0
    for (const s of coverage?.subjects || []) {
      if (typeof s.outline_chapters === 'number') outline += s.outline_chapters
      if (typeof s.covered_chapters === 'number') covered += s.covered_chapters
    }
    return { outline, covered }
  }, [coverage])

  const publicKpCount = chipTotals.hasKp
    ? chipTotals.kp
    : (isNum(coverage?.totals?.knowledge_points) ? Number(coverage.totals.knowledge_points) : null)

  const searchActive = query.trim().length > 0
  const hasAnyKp = tree.some((s) => s.knowledge_point_count > 0)
  const overviewTone = dist && dist.total > 0 && dist.unlearned >= dist.total
    ? STATE_TONE.unlearned
    : masteryTone(progress ? (progress.learned_avg_mastery ?? progress.avg_mastery) : 0)
  const avgMastery = Math.min(100, Math.max(0, Number(
    progress ? (progress.learned_avg_mastery ?? progress.avg_mastery) : 0,
  ) || 0))

  const scrollToDue = () => {
    document.getElementById('kb-due')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const goTextbooks = () => navigate(
    activeSubject ? `/textbooks?subject=${encodeURIComponent(activeSubject)}` : '/textbooks',
  )

  const pageActions = (
    <>
      <IconButton
        label="刷新知识地图"
        icon={<RefreshCw size={18} />}
        onClick={loadAll}
        disabled={status === 'loading'}
      />
      <Button variant="tonal" icon={<BookOpen size={16} />} onClick={goTextbooks}>
        {activeSubject ? '本科教材' : '教材总目录'}
      </Button>
    </>
  )

  if (status === 'loading') {
    return (
      <div className="v3-stack v3-kb-page">
        <PageHeader
          eyebrow="KNOWLEDGE · 知识结构"
          title="知识地图"
          sub="正在读取科目、章节与知识点结构…"
          actions={pageActions}
        />
        <div className="v3-bento">
          {Array.from({ length: 4 }).map((_, i) => (
            <Tile span={3} className="v3-kb-stat" key={i}><Skeleton height={58} /></Tile>
          ))}
          <Tile span={12} className="v3-kb-loading-card">
            <Skeleton height={34} width="28%" />
            <Skeleton height={190} />
          </Tile>
        </div>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="v3-stack v3-kb-page">
        <PageHeader
          eyebrow="KNOWLEDGE · 知识结构"
          title="知识地图"
          sub="章节 → 知识点 → 例题 / 方法"
          actions={pageActions}
        />
        <Card className="v3-kb-error-card">
          <Empty
            icon={<AlertCircle size={26} />}
            title="知识地图加载失败"
            text={errMsg || '请确认后端服务已启动后重试。'}
            action={(
              <Button variant="tonal" icon={<RefreshCw size={16} />} onClick={loadAll}>
                重新加载
              </Button>
            )}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="v3-stack v3-kb-page">
      <PageHeader
        eyebrow="KNOWLEDGE · 知识结构"
        title="知识地图"
        sub={progress && dist
          ? `共 ${dist.total} 个知识点 · 已掌握 ${dist.mastered} · 今日队列 ${due.length} 个 · 与「知识点全景」同一数据源`
          : '章节 → 知识点 → 例题 / 方法 · 访客可浏览结构与教材原文'}
        actions={pageActions}
      />

      {!user ? (
        <Alert tone="info" className="v3-kb-guest">
          <div className="v3-kb-guest__inner">
            <span>访客模式：知识结构与教材原文可直接浏览；登录后可查看掌握度、复习队列并记录复习结果。</span>
            <Button size="sm" variant="text" onClick={() => navigate('/login')}>去登录</Button>
          </div>
        </Alert>
      ) : null}

      {progress && dist ? (
        <div className="v3-bento">
          <Tile span={8} variant="hero" className="v3-kb-hero">
            <div className="v3-kb-hero__body">
              <Ring value={avgMastery} size={148} stroke={12} gradient>
                <div className="v3-kb-ring-center">
                  <strong>{avgMastery}<em>%</em></strong>
                  <span>{overviewTone.cls === 'new' ? '尚未开始' : '已学平均掌握度'}</span>
                </div>
              </Ring>
              <div className="v3-kb-hero__copy">
                <span className="v3-eyebrow v3-kb-hero__eyebrow">
                  <Sparkles size={14} data-idle="spin" /> MASTERY
                </span>
                <h2>
                  {overviewTone.cls === 'new'
                    ? '从第一个知识点开始建立结构。'
                    : `已掌握 ${dist.mastered} 个知识点，薄弱 ${dist.weak} 个。`}
                </h2>
                <p>
                  共 {dist.total} 个知识点 · 已掌握 {dist.mastered} · 薄弱 {dist.weak} · 未学 {dist.unlearned}。
                  未学知识点不计入薄弱，也不会拉低已学平均掌握度。
                </p>
                <div className="v3-kb-dist" role="img" aria-label="掌握度三态分布">
                  <div className="v3-kb-dist__bar">
                    <span className="is-new" style={{ width: dist.total ? `${(dist.unlearned / dist.total) * 100}%` : '0%' }} />
                    <span className="is-mid" style={{ width: dist.total ? `${(dist.weak / dist.total) * 100}%` : '0%' }} />
                    <span className="is-ok" style={{ width: dist.total ? `${(dist.mastered / dist.total) * 100}%` : '0%' }} />
                  </div>
                  <div className="v3-kb-dist__legend">
                    <span className="is-new"><i />未学 {dist.unlearned}</span>
                    <span className="is-mid"><i />薄弱 {dist.weak}</span>
                    <span className="is-ok"><i />已掌握 {dist.mastered}</span>
                  </div>
                </div>
              </div>
            </div>
          </Tile>

          <Tile span={4} className="v3-kb-pace">
            <CardHead
              icon={<Target size={17} />}
              title="今日复习"
              sub={`${due.length} 个知识点在队列中`}
            />
            <div className="v3-kb-pace__value">
              {due.length}<em>个待复习</em>
            </div>
            <div className="v3-kb-pace__kv">
              <div><span>已复习</span><b>{progress.reviewed_count ?? '—'}</b></div>
              <div><span>近 7 天</span><b>{progress.reviews_last_7_days ?? '—'}</b></div>
              <div><span>完成率</span><b>{progress.completion_rate != null ? `${progress.completion_rate}%` : '—'}</b></div>
            </div>
            {due.length > 0 ? (
              <Button variant="gradient" block icon={<ArrowRight size={16} />} onClick={scrollToDue}>
                查看今日队列
              </Button>
            ) : (
              <div className="v3-kb-pace__clear">
                <CheckCircle2 size={16} /> 今日队列已清空
              </div>
            )}
          </Tile>

          <Tile span={3} className="v3-kb-stat">
            <span className="v3-tile__label"><MapIcon size={15} /> 知识点总数</span>
            <span className="v3-tile__value"><MetricValue value={dist.total} suffix="个" /></span>
            <span className="v3-tile__hint">来自教材 / 讲义的结构化抽取</span>
          </Tile>
          <Tile span={3} className="v3-kb-stat">
            <span className="v3-tile__label"><CheckCircle2 size={15} /> 已复习</span>
            <span className="v3-tile__value v3-kb-tone is-ok"><MetricValue value={progress.reviewed_count} suffix="个" /></span>
            <span className="v3-tile__hint">至少复习过一次的知识点</span>
          </Tile>
          <Tile span={3} className="v3-kb-stat">
            <span className="v3-tile__label"><Clock size={15} /> 待复习</span>
            <span className="v3-tile__value v3-kb-tone is-mid"><MetricValue value={progress.due_count} suffix="个" /></span>
            <span className="v3-tile__hint">已排期且到期（不含新知识点）</span>
          </Tile>
          <Tile span={3} className="v3-kb-stat">
            <span className="v3-tile__label"><Sparkles size={15} /> 近 7 天复习</span>
            <span className="v3-tile__value"><MetricValue value={progress.reviews_last_7_days} suffix="次" /></span>
            <span className="v3-tile__hint">按北京时间自然日统计</span>
          </Tile>
        </div>
      ) : (
        <div className="v3-bento">
          <Tile span={3} className="v3-kb-stat">
            <span className="v3-tile__label"><MapIcon size={15} /> 科目</span>
            <span className="v3-tile__value"><MetricValue value={chipSubjects.length} suffix="科" /></span>
            <span className="v3-tile__hint">来自 /taxonomy/subjects</span>
          </Tile>
          <Tile span={3} className="v3-kb-stat">
            <span className="v3-tile__label"><Brain size={15} /> 知识点</span>
            <span className="v3-tile__value"><MetricValue value={publicKpCount} suffix="个" /></span>
            <span className="v3-tile__hint">不是题库题量，两个口径分开统计</span>
          </Tile>
          <Tile span={3} className="v3-kb-stat">
            <span className="v3-tile__label"><BookOpen size={15} /> 大纲章节</span>
            <span className="v3-tile__value"><MetricValue value={coverage ? coverageTotals.outline : null} suffix="章" /></span>
            <span className="v3-tile__hint">
              {coverage ? `已覆盖 ${coverageTotals.covered} 章` : '覆盖数据加载后显示'}
            </span>
          </Tile>
          <Tile span={3} className="v3-kb-stat">
            <span className="v3-tile__label"><Database size={15} /> 资料</span>
            <span className="v3-tile__value"><MetricValue value={coverage?.totals?.documents} suffix="篇" /></span>
            <span className="v3-tile__hint">
              {isNum(coverage?.totals?.chunks) ? `${coverage.totals.chunks} 个可检索分块` : '登录后可查看复习进度'}
            </span>
          </Tile>
        </div>
      )}

      {/* 科目选择 + 搜索 */}
      <Card variant="tonal" className="v3-kb-toolbar">
        <div className="v3-kb-toolbar__row">
          <div className="v3-kb-subjects" role="group" aria-label="选择科目">
            <Chip
              active={!activeSubject}
              onClick={() => selectSubject('')}
              title="知识点数＝知识库结构化抽取的知识点；题量＝题库题目数，两者口径不同"
            >
              全部
              {chipTotals.hasKp ? (
                <span className="v3-kb-chip-count">
                  {chipTotals.kp} 知识点{chipTotals.hasQ ? ` · ${chipTotals.q} 题` : ''}
                </span>
              ) : null}
            </Chip>
            {chipSubjects.map((s) => {
              const kpCount = typeof s.knowledge_point_count === 'number' ? s.knowledge_point_count : null
              const questionCount = typeof s.question_count === 'number' ? s.question_count : null
              return (
                <Chip
                  key={s.subject}
                  active={activeSubject === s.subject}
                  onClick={() => selectSubject(s.subject)}
                  title="知识点数＝知识库结构化抽取的知识点；题量＝题库题目数，两者口径不同"
                >
                  {s.subject}
                  <span className="v3-kb-chip-count">
                    {kpCount == null ? '— 知识点' : `${kpCount} 知识点`}
                    {questionCount != null ? ` · ${questionCount} 题` : ''}
                  </span>
                </Chip>
              )
            })}
          </div>
          <div className="v3-kb-toolbar__search">
            <Input
              icon={<Search size={16} />}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索知识点名称…"
              aria-label="搜索知识点"
              className="v3-kb-search"
            />
            {query ? (
              <IconButton
                label="清空搜索"
                size="sm"
                icon={<X size={15} />}
                onClick={() => setQuery('')}
              />
            ) : null}
          </div>
        </div>
        <div className="v3-kb-toolbar__foot">
          <span className="v3-kb-hint">
            知识点数来自教材 / 讲义的结构化抽取；题量来自题库，两个口径不同。
          </span>
          {quality ? (
            <span className="v3-kb-hint">
              <Database size={12} />
              语料徽标 = 可检索块数与平均打标置信（&lt;40% 标红）；弃权块不参与检索。
            </span>
          ) : null}
        </div>
      </Card>

      {chipSubjects.length === 0 && !treeLoading ? (
        <Card className="v3-kb-empty-card">
          <Empty
            icon={<BookOpen size={26} />}
            title="暂未配置科目"
            text={isAdmin
              ? '请先在「科目管理」中添加考试科目与大纲章节，知识地图会自动生成三级结构。'
              : '科目与大纲由管理员维护，配置完成后知识地图会自动生成。'}
            action={isAdmin
              ? <Button variant="gradient" onClick={() => navigate('/subjects')}>去科目管理</Button>
              : null}
          />
        </Card>
      ) : !hasAnyKp && !treeLoading ? (
        <Card className="v3-kb-empty-card">
          <Empty
            icon={<Brain size={26} />}
            title={activeSubject ? `「${activeSubject}」暂无知识点` : '知识点库为空'}
            text={activeSubject
              ? `该科目${typeof activeChip?.question_count === 'number'
                ? `题库已有 ${activeChip.question_count} 题`
                : '题库可能有题'}，但知识点数为 0 —— 题量 ≠ 知识点数。知识点来自教材 / 讲义的结构化抽取，题库题目不会自动生成知识结构。${isAdmin ? '请到资料库上传该科资料并执行知识点抽取，完成后返回刷新。' : '资料抽取由管理员维护，完成后返回刷新即可。'}`
              : `知识点数与题库题量是两个口径：这里统计的是从教材 / 讲义中抽取的结构化知识点。当前还没有任何知识点，${isAdmin ? '请到资料库上传资料并执行知识点抽取，完成后返回刷新。' : '资料抽取由管理员维护，完成后返回刷新即可。'}`}
            action={isAdmin
              ? <Button variant="gradient" icon={<BookOpen size={16} />} onClick={() => navigate('/documents')}>去资料库导入</Button>
              : null}
          />
        </Card>
      ) : (
        <div className="v3-kb-map">
          {/* 左：章节 */}
          <Card className="v3-kb-column v3-kb-column--chapters">
            <div className="v3-kb-column__head">
              <div>
                <span className="v3-eyebrow">CHAPTERS</span>
                <h2>章节</h2>
              </div>
              <Badge tone="outline">{chapterGroups.length} 科</Badge>
            </div>
            <div className="v3-kb-column__scroll">
              {treeLoading ? (
                <div className="v3-kb-skeleton-list">
                  <Skeleton height={16} width="40%" />
                  <Skeleton height={44} />
                  <Skeleton height={44} />
                  <Skeleton height={44} />
                  <Skeleton height={44} />
                </div>
              ) : chapterGroups.length === 0 ? (
                <Empty
                  icon={<BookOpen size={22} />}
                  title="暂无章节"
                  text="该筛选条件下没有可用章节，试试切换科目。"
                />
              ) : (
                chapterGroups.map((g) => (
                  <SubjectGroup
                    key={g.subject}
                    group={g}
                    activeChapter={activeChapter}
                    quality={pickQuality(g.subject)}
                    onSelectChapter={selectChapter}
                  />
                ))
              )}
            </div>
          </Card>

          {/* 中：知识点 / 搜索结果 */}
          <Card className="v3-kb-column v3-kb-column--points">
            <div className="v3-kb-column__head">
              <div>
                <span className="v3-eyebrow">{searchActive ? 'SEARCH' : 'POINTS'}</span>
                <h2>
                  {searchActive
                    ? '搜索结果'
                    : `知识点${activeChapter ? ` · ${activeChapter.title}` : ''}`}
                </h2>
              </div>
              <Badge tone="outline">
                {searchActive
                  ? `${searchResults.length} 个匹配`
                  : `${activeChapterData?.chapter.knowledge_point_count ?? 0} 个`}
              </Badge>
            </div>
            <div className="v3-kb-column__scroll">
              {treeLoading ? (
                <div className="v3-kb-skeleton-list">
                  <Skeleton height={78} />
                  <Skeleton height={78} />
                  <Skeleton height={78} />
                </div>
              ) : searchActive ? (
                searchResults.length === 0 ? (
                  <Empty
                    icon={<Search size={22} />}
                    title="没有匹配的知识点"
                    text={`没有找到名称包含「${query.trim()}」的知识点。换个关键词，或清空搜索回到章节浏览。`}
                    action={<Button size="sm" variant="tonal" onClick={() => setQuery('')}>清空搜索</Button>}
                  />
                ) : (
                  <div className="v3-kb-points">
                    {searchResults.map((kp) => (
                      <PointCard
                        key={`${kp.subject}-${kp.id}`}
                        kp={kp}
                        selected={String(selectedKpId) === String(kp.id)}
                        path={`${kp.subject}${kp.chapter ? ` · ${kp.chapter}` : ''}`}
                        query={query}
                        onOpen={() => navigate(`/knowledge/${kp.id}`)}
                        onPreview={() => openDetail(kp)}
                        onPractice={() => goQuiz(kp.subject, kp.chapter, kp)}
                      />
                    ))}
                  </div>
                )
              ) : !activeChapterData ? (
                <Empty
                  icon={<Target size={22} />}
                  title="请选择章节"
                  text="从左栏选择一个章节，这里会列出该章节的全部知识点与掌握度。"
                />
              ) : (activeChapterData.chapter.knowledge_points || []).length === 0 ? (
                <Empty
                  icon={<Brain size={22} />}
                  title="该章节暂无知识点"
                  text={isAdmin
                    ? '请到知识库上传对应章节资料并执行知识点抽取，完成后返回刷新。'
                    : '该章节资料尚未抽取知识点，管理员完成抽取后即可查看。'}
                  action={isAdmin
                    ? <Button size="sm" variant="tonal" onClick={() => navigate('/documents')}>去知识库导入</Button>
                    : null}
                />
              ) : (
                <div className="v3-kb-points">
                  {(activeChapterData.chapter.knowledge_points || []).map((kp) => (
                    <PointCard
                      key={kp.id}
                      kp={kp}
                      selected={String(selectedKpId) === String(kp.id)}
                      query={query}
                      onOpen={() => navigate(`/knowledge/${kp.id}`)}
                      onPreview={() => openDetail(kp)}
                      onPractice={() => goQuiz(activeChapterData.subject, activeChapterData.chapter.title, kp)}
                    />
                  ))}
                </div>
              )}
            </div>
          </Card>

          {/* 右：例题 / 方法 */}
          <Card className="v3-kb-column v3-kb-column--detail">
            <div className="v3-kb-column__head">
              <div>
                <span className="v3-eyebrow">EXAMPLES</span>
                <h2>例题 / 方法</h2>
              </div>
              {selectedKpId != null ? <Badge tone="outline">#{selectedKpId}</Badge> : null}
            </div>
            <DetailPanel
              selectedKpId={selectedKpId}
              detail={detail}
              kpQCount={kpQCount}
              aiExplain={aiExplain}
              detailReviewing={detailReviewing}
              user={user}
              onRetry={() => openDetail({ id: selectedKpId })}
              onPractice={goQuiz}
              onOpenArticle={(id) => navigate(`/knowledge/${id}`)}
              onOpenError={(to) => navigate(to)}
              onRunAiExplain={runAiExplain}
              onToggleAi={() => setAiExplain((s) => ({ ...s, open: !s.open }))}
              onReview={submitDetailReview}
              onLogin={() => navigate('/login')}
              onGoAllQuestions={(subject) => navigate(`/quiz?subject=${encodeURIComponent(subject || '')}`)}
            />
          </Card>
        </div>
      )}

      {/* 复习辅助：队列 / 薄弱 / 覆盖体检 */}
      {hasAnyKp ? (
        <div className="v3-kb-aux">
          {user ? (
            <Card className={cx('v3-kb-aux-card', !(progress?.weak_points?.length > 0) && 'v3-kb-aux__wide')} id="kb-due">
              <CardHead
                icon={<Clock size={17} />}
                title="今日复习队列"
                sub={`${due.length} 个知识点待复习`}
                actions={<Badge tone={due.length ? 'warning' : 'success'}>{due.length ? '待处理' : '已清空'}</Badge>}
              />
              {due.length === 0 ? (
                <div className="v3-kb-due-empty">
                  <CheckCircle2 size={18} /> 今天没有待复习的知识点
                </div>
              ) : (
                <div className="v3-kb-due-list">
                  {due.slice(0, 12).map((it) => (
                    <div className="v3-kb-due" key={it.id}>
                      <div className="v3-kb-due__main">
                        <div className="v3-kb-due__name">
                          {it.name}
                          {it.is_new ? <Badge tone="primary">新</Badge> : null}
                        </div>
                        <div className="v3-kb-due__sub">
                          {it.subject} · {it.chapter || '未归章'}
                        </div>
                      </div>
                      <div className="v3-kb-review-actions">
                        <button
                          type="button"
                          className="v3-kb-mini is-ok"
                          disabled={reviewing === it.id}
                          onClick={() => submitReview(it.id, 'mastered')}
                        >
                          会
                        </button>
                        <button
                          type="button"
                          className="v3-kb-mini is-warn"
                          disabled={reviewing === it.id}
                          onClick={() => submitReview(it.id, 'fuzzy')}
                        >
                          模糊
                        </button>
                        <button
                          type="button"
                          className="v3-kb-mini is-danger"
                          disabled={reviewing === it.id}
                          onClick={() => submitReview(it.id, 'forgotten')}
                        >
                          不会
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {due.length > 12 ? (
                <p className="v3-kb-hint">仅展示队列前 12 个，共 {due.length} 个。逐条打卡后会自动刷新。</p>
              ) : null}
            </Card>
          ) : null}

          {user && progress?.weak_points?.length > 0 ? (
            <Card className="v3-kb-aux-card">
              <CardHead
                icon={<Target size={17} />}
                title="掌握度最低的知识点"
                sub="按掌握度升序，优先攻克"
              />
              <div className="v3-kb-weak-list">
                {progress.weak_points.slice(0, 10).map((k) => {
                  const tone = stateTone(k.state)
                  return (
                    <div className="v3-kb-weak" key={k.id}>
                      <span className="v3-kb-weak__name">{k.name}</span>
                      <span className="v3-kb-weak__ch">{k.chapter || '未归章'}</span>
                      <Badge tone={tone.badge}>{k.mastery}%</Badge>
                    </div>
                  )
                })}
              </div>
            </Card>
          ) : null}

          {coverage ? (
            <Card className="v3-kb-aux-card v3-kb-aux__wide">
              <CardHead
                icon={<Database size={17} />}
                title="结构化覆盖体检"
                sub={`${coverage.totals?.documents ?? 0} 篇资料 · ${coverage.totals?.chunks ?? 0} 分块 · ${coverage.totals?.ocr_documents ?? 0} 篇扫描件`}
                actions={<Badge tone="outline">真实统计</Badge>}
              />
              <div className="v3-kb-table-wrap">
                <table className="v3-kb-table" aria-label="结构化覆盖体检">
                  <thead>
                    <tr>
                      <th scope="col">科目</th>
                      <th scope="col">分块</th>
                      <th scope="col">知识点</th>
                      <th scope="col">章节覆盖</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(coverage.subjects || []).filter((s) => s.documents > 0).length === 0 ? (
                      <tr>
                        <td colSpan={4} className="v3-kb-table__empty">
                          {isAdmin ? '暂无已入库资料，先去资料库导入并解析。' : '暂无已入库资料，管理员导入并解析后会显示统计。'}
                        </td>
                      </tr>
                    ) : (coverage.subjects || []).filter((s) => s.documents > 0).map((s) => {
                      const hasOutline = !!s.outline_chapters
                      const rate = hasOutline
                        ? Math.min(100, Math.round((s.covered_chapters / s.outline_chapters) * 100))
                        : 0
                      return (
                        <tr key={s.subject}>
                          <td data-label="科目">
                            <span className="v3-kb-table__subject">
                              {s.subject}
                              {!s.is_core ? <Badge tone="outline">拓展</Badge> : null}
                            </span>
                          </td>
                          <td data-label="分块">{s.chunks}</td>
                          <td data-label="知识点">{s.knowledge_points}</td>
                          <td data-label="章节覆盖">
                            {hasOutline ? (
                              <span className="v3-kb-cov">
                                <span className="v3-kb-cov__num">{s.covered_chapters}/{s.outline_chapters}</span>
                                <Meter value={rate} tone={rate >= 70 ? 'ok' : rate > 0 ? 'mid' : 'new'} height={4} />
                                <em>{rate}%</em>
                              </span>
                            ) : '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p className="v3-kb-hint">
                知识点来自教材 / 讲义的结构化抽取；章节覆盖只按大纲章名精确匹配，不猜对应关系。
              </p>
            </Card>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
