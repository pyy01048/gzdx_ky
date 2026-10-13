import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { taxonomyApi, reviewApi, quizApi, qualityApi } from '../api/client'
import { toast, Empty } from '../components/UI'
import {
  RefreshCw, CheckCircle, ChevronRight, ChevronDown,
  Book, Brain, AlertCircle, Map as MapIcon,
} from '../components/Icon'

/* 题型码 → 中文标签（与后端 ALLOWED_QUESTION_TYPES 对齐）。
   后端落库为 single/judge/fill/essay/calc/draw，展示层统一翻成中文。 */
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

/* 掌握度三态（与后端口径一致，见 backend services/kp_mastery.py）：
   未学（无任何学习记录）= 灰 / 薄弱（有记录但 <70）= 黄 / 已掌握（≥70）= 绿。
   未学知识点不计入薄弱统计 —— 它们"还没开始"，不是"薄弱"。 */
const STATE_TONE = {
  unlearned: { cls: 'new', label: '未学' },
  weak: { cls: 'mid', label: '薄弱' },
  mastered: { cls: 'ok', label: '已掌握' },
}
/* 知识点三态：优先用后端下发的 state；旧接口没有时按 (mastery, review_count) 兜底 */
function kpState(kp) {
  if (kp && STATE_TONE[kp.state]) return kp.state
  const m = Number(kp && kp.mastery) || 0
  if (m >= 70) return 'mastered'
  return kp && kp.review_count > 0 ? 'weak' : 'unlearned'
}
function stateTone(state) {
  return STATE_TONE[state] || STATE_TONE.unlearned
}
/* 纯数值 → 三态 tone（均分等只有数值的场景；<70 即薄弱=黄） */
function masteryTone(m) {
  const v = Number(m) || 0
  return v >= 70 ? STATE_TONE.mastered : STATE_TONE.weak
}
/* 科目/章节聚合节点：全部未学 → 灰；否则按已学平均掌握度取黄/绿 */
function nodeTone(node) {
  const total = (node && (node.knowledge_point_count ?? node.total)) || 0
  const unlearned = (node && node.unlearned_count) || 0
  if (total > 0 && unlearned >= total) return STATE_TONE.unlearned
  return masteryTone((node && (node.learned_avg_mastery ?? node.avg_mastery)) || 0)
}
/* 聚合节点展示用均分：优先已学平均（未学不拉低均值） */
function nodeAvg(node) {
  return (node && (node.learned_avg_mastery ?? node.avg_mastery)) ?? 0
}

/* 复习结果三态按钮 */
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

export default function KbMap() {
  const [subjects, setSubjects] = useState([])      // 动态科目列表（taxonomyApi.subjects）
  const [tree, setTree] = useState([])              // 结构树（taxonomyApi.tree）
  const [progress, setProgress] = useState(null)    // 全局掌握度总览
  const [due, setDue] = useState([])                // 今日复习队列
  const [coverage, setCoverage] = useState(null)    // 结构化覆盖体检
  const [quality, setQuality] = useState(null)      // 语料质量层（qualityApi.treeOverlay）
  const [status, setStatus] = useState('loading')  // loading | ok | error
  const [treeLoading, setTreeLoading] = useState(false)
  const [activeSubject, setActiveSubject] = useState('')
  const [openChapters, setOpenChapters] = useState({})
  const [reviewing, setReviewing] = useState(null)
  const [errMsg, setErrMsg] = useState('')

  const navigate = useNavigate()
  /* 知识点详情抽屉：详情来自 /api/taxonomy/knowledge-points/{id}；
     关联题量来自 /api/quiz/questions?kp_id=（tree 不返回题量，故单独查真实值）。 */
  const [detail, setDetail] = useState({ open: false, loading: false, error: '', data: null })
  const [kpQCount, setKpQCount] = useState(null)
  const [detailReviewing, setDetailReviewing] = useState(false)
  const detailSeq = useRef(0)

  /* 首次加载：科目列表 + 全局总览 + 全量结构树 并行拉取 */
  const loadAll = useCallback(async () => {
    setStatus('loading')
    setErrMsg('')
    try {
      const [sj, t, p, d, c, q] = await Promise.all([
        taxonomyApi.subjects(),
        taxonomyApi.tree(),
        reviewApi.progress(),
        reviewApi.due({ limit: 30 }),
        taxonomyApi.coverage(),
        qualityApi.treeOverlay().catch(() => null),   // 质量层失败不影响地图主体
      ])
      setSubjects(normalizeSubjects(sj))
      const tNodes = t?.tree || []
      setTree(tNodes)
      setProgress(p)
      setDue(d?.items || [])
      setCoverage(c)
      setQuality(q)
      setActiveSubject('')
      // 默认展开第一个有知识点的科目首个有知识点的章节
      const first = tNodes.find((s) => s.knowledge_point_count > 0)
      const firstCh = first?.chapters?.find((ch) => ch.knowledge_point_count > 0)
      setOpenChapters(
        first && firstCh ? { [`${first.subject}|${firstCh.title}`]: true } : {}
      )
      setStatus('ok')
    } catch (e) {
      setErrMsg(e?.message || '未知错误')
      setStatus('error')
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  /* 切换科目：仅重拉该科结构树，保留全局总览与队列 */
  const selectSubject = useCallback(async (name) => {
    if (name === activeSubject) return
    setActiveSubject(name)
    setTreeLoading(true)
    setOpenChapters({})
    try {
      const t = await taxonomyApi.tree(name || undefined)
      const tNodes = t?.tree || []
      setTree(tNodes)
      const first = tNodes.find((s) => s.knowledge_point_count > 0)
      const firstCh = first?.chapters?.find((ch) => ch.knowledge_point_count > 0)
      if (first && firstCh) {
        setOpenChapters({ [`${first.subject}|${firstCh.title}`]: true })
      }
    } catch (e) {
      toast('加载知识结构失败：' + (e?.message || ''))
    } finally {
      setTreeLoading(false)
    }
  }, [activeSubject])

  const toggleChapter = (key) =>
    setOpenChapters((s) => ({ ...s, [key]: !s[key] }))

  /* 提交一次复习结果（艾宾浩斯回写掌握度） */
  const submitReview = async (kpId, result) => {
    setReviewing(kpId)
    try {
      const r = await reviewApi.submit({ item_type: 'knowledge', item_id: kpId, result })
      toast(`已记录：掌握度 ${r.mastery_before} → ${r.mastery_after}，${r.interval} 天后复习`)
      await loadAll()
    } catch (e) {
      toast('记录失败：' + (e?.message || ''))
    } finally {
      setReviewing(null)
    }
  }

  /* 打开知识点详情抽屉：并行拉取详情 + 关联题量（各自容错，防竞态） */
  const openDetail = useCallback(async (kp) => {
    const id = kp?.id
    if (id == null) return
    const seq = ++detailSeq.current
    setDetail({ open: true, loading: true, error: '', data: null })
    setKpQCount(null)
    const [detRes, qRes] = await Promise.allSettled([
      taxonomyApi.knowledgePoint(id),
      quizApi.questions({ kp_id: id, page_size: 1 }),
    ])
    if (seq !== detailSeq.current) return
    if (detRes.status === 'fulfilled' && detRes.value) {
      setDetail({ open: true, loading: false, error: '', data: detRes.value })
    } else {
      setDetail({
        open: true,
        loading: false,
        error: detRes.reason?.message || '知识点详情加载失败',
        data: null,
      })
    }
    // 题量查询失败时置 null（界面显示 '—'），绝不伪造 0
    setKpQCount(
      qRes.status === 'fulfilled' && qRes.value && typeof qRes.value.total === 'number'
        ? qRes.value.total
        : null
    )
  }, [])

  const closeDetail = useCallback(() => {
    detailSeq.current++
    setDetail({ open: false, loading: false, error: '', data: null })
    setKpQCount(null)
  }, [])

  /* 抽屉内复习打卡：复用 reviewApi.submit，成功后刷新抽屉与页面数据 */
  const submitDetailReview = async (result) => {
    const id = detail.data?.id
    if (id == null) return
    setDetailReviewing(true)
    try {
      const r = await reviewApi.submit({ item_type: 'knowledge', item_id: id, result })
      toast(`已记录：掌握度 ${r.mastery_before} → ${r.mastery_after}，${r.interval} 天后复习`)
      await Promise.all([openDetail({ id }), loadAll()])
    } catch (e) {
      toast('记录失败：' + (e?.message || ''))
    } finally {
      setDetailReviewing(false)
    }
  }

  /* Esc 关闭抽屉 */
  useEffect(() => {
    if (!detail.open) return
    const onKey = (e) => { if (e.key === 'Escape') closeDetail() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [detail.open, closeDetail])

  /* 科目维度汇总（用于概览分布条）：三态 —— 未学/薄弱/已掌握 */
  const dist = useMemo(() => {
    if (!progress) return null
    const total = progress.total_knowledge_points || 0
    const mastered = progress.mastered_count || 0
    const weak = progress.weak_count || 0
    // 旧后端没有 unlearned_count 时用总数倒扣，保证分布条不出现负值
    const unlearned = progress.unlearned_count ?? Math.max(0, total - mastered - weak)
    return { total, mastered, weak, unlearned }
  }, [progress])

  /* 科目选择 chips：优先用 /taxonomy/subjects（阶段1 契约 {subjects:[...]}）；
     若该表为空（旧库未播种 SubjectConfig），回退用结构树里已存在的科目，
     避免有大量知识点却误报「暂未配置科目」。 */
  const chipSubjects = useMemo(() => {
    if (subjects.length > 0) return subjects
    return tree
      .filter((s) => s.knowledge_point_count > 0)
      .map((s) => ({ subject: s.subject, question_count: s.knowledge_point_count }))
  }, [subjects, tree])

  /* 语料质量层：学科 → 可检索块数 / 平均打标置信 / 弃权率（/api/quality/tree-overlay）。
     小节级用 chunk 的 l2_chapter（原文小节名），与大纲章节名对不上就不显示——不猜对应关系。 */
  const qualityBySubject = useMemo(() => {
    const m = new Map()
    for (const s of (quality && quality.subjects) || []) {
      m.set(s.subject, s)
      const k = String(s.subject || '').replace(/\s+/g, '')
      if (!m.has(k)) m.set(k, s)
    }
    return m
  }, [quality])

  /* 只对得上名字，不做模糊归一：对不上时显示"未匹配"而不是"无语料"，
     因为很可能只是学科叫法不同（如 408 前后缀差异）。 */
  const pickQuality = useCallback((name) => {
    if (!name) return null
    return qualityBySubject.get(name) || qualityBySubject.get(String(name).replace(/\s+/g, '')) || null
  }, [qualityBySubject])

  const chapterQuality = useCallback((subjectName, title) => {
    const row = pickQuality(subjectName)
    if (!row || !row.chapters || !row.chapters.length) return null
    const t = String(title || '').replace(/\s+/g, '')
    if (!t) return null
    return row.chapters.find((c) => String(c.chapter || '').replace(/\s+/g, '') === t) || null
  }, [pickQuality])

  /* 置信分档：0.40 是后端 CONF_THRESHOLD，低于它标签视为不可信 */
  const corpusTone = (conf) => (conf != null && conf >= 0.40 ? 'ok' : 'low')

  /* ---------------- 三态：加载中 ---------------- */
  if (status === 'loading') {
    return (
      <div className="page">
        <div className="card">
          <div className="loading-inline">知识结构加载中…</div>
        </div>
      </div>
    )
  }

  /* ---------------- 三态：失败（toast + 就地提示 + 重试） ---------------- */
  if (status === 'error') {
    return (
      <div className="page">
        <div className="card kb-error-card">
          <div className="kb-error-icon"><AlertCircle size={28} /></div>
          <div className="kb-error-body">
            <div className="kb-error-title">知识地图加载失败</div>
            <div className="kb-error-desc">{errMsg || '请确认后端服务已启动后重试。'}</div>
            <button className="btn ghost" onClick={loadAll}>
              <RefreshCw size={14} /> 重新加载
            </button>
          </div>
        </div>
      </div>
    )
  }

  const coreSubjects = tree.filter((s) => s.is_core)
  const extSubjects = tree.filter((s) => !s.is_core)
  const hasAnyKp = tree.some((s) => s.knowledge_point_count > 0)
  // 总览大数字：全部未学时置灰，否则按已学平均掌握度取黄/绿
  const overviewTone = dist && dist.total > 0 && dist.unlearned >= dist.total
    ? STATE_TONE.unlearned
    : masteryTone(progress ? (progress.learned_avg_mastery ?? progress.avg_mastery) : 0)
  // 详情抽屉里的掌握度三态
  const dTone = stateTone(detail.data ? kpState(detail.data) : 'unlearned')

  return (
    <div className="page">
      {/* 页头 */}
      <div className="page-head">
        <div>
          <h1 className="page-title">知识地图</h1>
          <div className="page-sub">章节 → 知识点 → 题型 三级结构 · 掌握度可视化追踪</div>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={loadAll}>
            <RefreshCw size={15} /> 刷新
          </button>
        </div>
      </div>

      {/* 掌握度总览卡 */}
      {progress && dist && (
        <div className="kb-overview">
          <div className="kb-overview-main">
            <div className="kb-overview-figure">
              <span className={`kb-overview-num tone-${overviewTone.cls}`}>
                {progress.learned_avg_mastery ?? progress.avg_mastery}
              </span>
              <span className="kb-overview-unit">%</span>
            </div>
            <div className="kb-overview-meta">
              <div className="kb-overview-label">
                {overviewTone.cls === 'new' ? '掌握度（尚未开始学习）' : '已学平均掌握度'}
              </div>
              <div className="kb-overview-hint">
                共 {dist.total} 个知识点 · 已掌握 {dist.mastered} · 薄弱 {dist.weak} · 未学 {dist.unlearned}
              </div>
            </div>
          </div>
          <div className="kb-overview-dist">
            <div className="kb-dist-bar" role="img" aria-label="掌握度三态分布">
              <span className="seg new" style={{ width: dist.total ? `${(dist.unlearned / dist.total) * 100}%` : '0%' }} />
              <span className="seg mid" style={{ width: dist.total ? `${(dist.weak / dist.total) * 100}%` : '0%' }} />
              <span className="seg ok" style={{ width: dist.total ? `${(dist.mastered / dist.total) * 100}%` : '0%' }} />
            </div>
            <div className="kb-legend">
              <span className="kb-legend-item"><i className="dot new" />未学（无学习记录）</span>
              <span className="kb-legend-item"><i className="dot mid" />薄弱 &lt;70（已学）</span>
              <span className="kb-legend-item"><i className="dot ok" />已掌握 ≥70</span>
            </div>
          </div>
        </div>
      )}

      {/* 全局统计小卡 */}
      {progress && dist && (
        <div className="kb-stats">
          <div className="kb-stat">
            <span className="kb-stat-num">{progress.total_knowledge_points}</span>
            <span className="kb-stat-label">知识点总数</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num">{progress.reviewed_count}</span>
            <span className="kb-stat-label">已复习</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num new">{dist.unlearned}</span>
            <span className="kb-stat-label">未学</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num ok">{progress.mastered_count}</span>
            <span className="kb-stat-label">已掌握</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num warn">{progress.weak_count}</span>
            <span className="kb-stat-label">薄弱</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num">{progress.due_count ?? 0}</span>
            <span className="kb-stat-label">待复习</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num">{progress.reviews_last_7_days}</span>
            <span className="kb-stat-label">近 7 天复习</span>
          </div>
        </div>
      )}

      {/* 科目选择（动态，来自 taxonomyApi.subjects） */}
      <div className="kb-subjectbar">
        <MapIcon size={15} className="kb-subjectbar-icon" />
        <div className="kb-chips">
          <button
            className={`kb-chip ${!activeSubject ? 'active' : ''}`}
            onClick={() => selectSubject('')}
          >
            全部
          </button>
          {chipSubjects.map((s) => (
            <button
              key={s.subject}
              className={`kb-chip ${activeSubject === s.subject ? 'active' : ''}`}
              onClick={() => selectSubject(s.subject)}
            >
              {s.subject}
              {typeof s.question_count === 'number' && <small>{s.question_count}</small>}
            </button>
          ))}
        </div>
      </div>

      {quality && (
        <div className="kb-quality-hint">
          「语料」徽标＝知识库该学科可检索块数与自动打标置信（置信 &lt;0.40 标红，与后端 CONF_THRESHOLD 一致）；
          弃权＝被判为垃圾/无学科而不参与检索的块。小节级语料统计依赖原文小节名回填，未回填时只显示学科级。
        </div>
      )}

      {chipSubjects.length === 0 && !treeLoading ? (
        <Empty
          icon={<Book size={44} />}
          title="暂未配置科目"
          desc="请先在「科目管理」中添加考试科目与大纲章节，知识地图会自动生成三级结构。"
        />
      ) : (
        <div className="kb-layout">
          {/* 左：三级结构树 */}
          <div className="kb-tree-col">
            {treeLoading ? (
              <div className="card"><div className="loading-inline">结构加载中…</div></div>
            ) : !hasAnyKp ? (
              <Empty
                icon={<Brain size={44} />}
                title={activeSubject ? `「${activeSubject}」暂无知识点` : '暂无知识结构数据'}
                desc="上传资料并解析后，这里会按章节展开知识点与掌握度。"
              />
            ) : (
              [...coreSubjects, ...extSubjects].map((subject) => (
                <div className="card kb-subject-card" key={subject.subject}>
                  <div className="kb-subject-head">
                    <div className="kb-subject-titles">
                      <div className="kb-subject-name">
                        {subject.subject}
                        {!subject.is_core && <span className="kb-tag-ext">拓展</span>}
                      </div>
                      <div className="kb-subject-meta">
                        知识点 {subject.knowledge_point_count} · {subject.outline_chapter_count} 章节
                        {(() => {
                          const ql = pickQuality(subject.subject)
                          if (ql) {
                            const ab = ql.chunks ? Math.round((ql.abstained_chunks / ql.chunks) * 100) : 0
                            return (
                              <span className={`kb-corpus tone-${corpusTone(ql.avg_confidence)}`}
                                title={`知识库该学科可检索块数 ${ql.chunks}，平均打标置信 ${ql.avg_confidence == null ? '—' : ql.avg_confidence}，弃权（判为垃圾/无学科）${ql.abstained_chunks} 块`}>
                                语料 {ql.chunks} 块 · 置信 {ql.avg_confidence == null ? '—' : ql.avg_confidence} · 弃权 {ab}%
                              </span>
                            )
                          }
                          return quality
                            ? <span className="kb-corpus" title="按学科名精确匹配没匹配上；可能只是叫法不同，不代表库里真没有">语料名未匹配</span>
                            : null
                        })()}
                      </div>
                    </div>
                    <div className="kb-subject-mastery">
                      <span className={`kb-pill tone-${nodeTone(subject).cls}`}>
                        {nodeTone(subject).cls === 'new' ? '未学' : `平均 ${nodeAvg(subject)}%`}
                      </span>
                    </div>
                  </div>
                  {/* 科目维度掌握度条 */}
                  <div className={`kb-bar tone-${nodeTone(subject).cls}`}>
                    <i style={{ width: `${Math.min(100, nodeAvg(subject))}%` }} />
                  </div>

                  <div className="kb-chapters">
                    {subject.chapters.map((ch) => {
                      const key = `${subject.subject}|${ch.title}`
                      const open = !!openChapters[key]
                      const hasData = ch.knowledge_point_count > 0
                      const tone = nodeTone(ch)
                      return (
                        <div className={`kb-chapter ${hasData ? '' : 'is-empty'}`} key={key}>
                          <button className="kb-chapter-head" onClick={() => toggleChapter(key)}>
                            {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                            <span className="kb-chapter-title">{ch.title}</span>
                            <span className="kb-chapter-meta">
                              {hasData ? `${ch.knowledge_point_count} 个知识点` : '暂无资料'}
                              {(() => {
                                const cq = chapterQuality(subject.subject, ch.title)
                                return cq ? (
                                  <span className="kb-corpus sm"
                                    title={`原文小节「${cq.chapter}」语料 ${cq.chunks} 块 · 平均置信 ${cq.avg_confidence == null ? '—' : cq.avg_confidence}`}>
                                    原文语料 {cq.chunks} 块
                                  </span>
                                ) : null
                              })()}
                              {hasData && (
                                <span className={`kb-bar sm tone-${tone.cls}`}>
                                  <i style={{ width: `${Math.min(100, nodeAvg(ch))}%` }} />
                                </span>
                              )}
                            </span>
                          </button>

                          {open && hasData && (
                            <div className="kb-kp-list">
                              <div className="kb-qtypes">
                                <span className="kb-qtypes-label">题型</span>
                                {ch.question_types.slice(0, 8).map((t) => (
                                  <span className="kb-qtype" key={t}>{typeLabel(t)}</span>
                                ))}
                              </div>
                              {ch.knowledge_points.map((kp) => {
                                const kt = stateTone(kpState(kp))
                                return (
                                  <div
                                    className="kb-kp kb-kp-clickable"
                                    key={kp.id}
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => openDetail(kp)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault()
                                        openDetail(kp)
                                      }
                                    }}
                                    title={`查看「${kp.name}」知识点详情`}
                                  >
                                    <span className={`kb-dot tone-${kt.cls}`} title={`掌握度 ${kp.mastery}（${kt.label}）`} />                                    <div className="kb-kp-main">
                                      <div className="kb-kp-row1">
                                        <span className="kb-kp-name">{kp.name}</span>
                                        <span className="kb-kp-tags">
                                          {(kp.question_types || []).slice(0, 3).map((t) => (
                                            <span className="kb-qtype sm" key={t}>{typeLabel(t)}</span>
                                          ))}
                                        </span>
                                      </div>
                                      <div className="kb-kp-row2">
                                        <span className={`kb-bar tone-${kt.cls}`}>
                                          <i style={{ width: `${Math.min(100, kp.mastery)}%` }} />
                                        </span>
                                        <span className={`kb-kp-pct tone-${kt.cls}`}>
                                          {kt.cls === 'new' ? '未学' : `${kp.mastery}%`}
                                        </span>
                                        <span className="kb-kp-freq">
                                          {kp.review_count ? `已复习 ${kp.review_count} 次` : '未复习'}
                                        </span>
                                      </div>
                                    </div>
                                    <span className="kb-kp-actions">
                                      {REVIEW_ACTIONS.map((r) => (
                                        <button
                                          key={r.result}
                                          className={`kb-mini-btn ${r.cls}`}
                                          disabled={reviewing === kp.id}
                                          onClick={(e) => { e.stopPropagation(); submitReview(kp.id, r.result) }}
                                          title={`标记为${r.label}`}
                                        >
                                          {r.label}
                                        </button>
                                      ))}
                                    </span>
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 右：复习队列 + 薄弱考点 + 覆盖率 */}
          <div className="kb-side-col">
            <div className="card">
              <div className="card-head">
                <div>
                  <div className="card-title">今日复习队列</div>
                  <div className="card-sub">{due.length} 个知识点待复习</div>
                </div>
              </div>
              <div className="card-body">
                {due.length === 0 ? (
                  <div className="kb-due-empty">
                    <CheckCircle size={18} /> 今天没有待复习的知识点
                  </div>
                ) : (
                  <div className="kb-due-list">
                    {due.slice(0, 12).map((it) => (
                      <div className="kb-due-item" key={it.id}>
                        <div className="kb-due-main">
                          <div className="kb-due-name">{it.name}</div>
                          <div className="kb-due-sub">
                            {it.subject} · {it.chapter || '未归章'}
                            {it.is_new && <span className="kb-tag-new">新</span>}
                          </div>
                        </div>
                        <div className="kb-due-actions">
                          <button className="kb-mini-btn ok" disabled={reviewing === it.id}
                            onClick={() => submitReview(it.id, 'mastered')}>会</button>
                          <button className="kb-mini-btn warn" disabled={reviewing === it.id}
                            onClick={() => submitReview(it.id, 'fuzzy')}>模糊</button>
                          <button className="kb-mini-btn danger" disabled={reviewing === it.id}
                            onClick={() => submitReview(it.id, 'forgotten')}>不会</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {progress?.weak_points?.length > 0 && (
              <div className="card">
                <div className="card-head">
                  <div>
                    <div className="card-title">薄弱知识点</div>
                    <div className="card-sub">按掌握度升序，优先攻克</div>
                  </div>
                </div>
                <div className="card-body">
                  <div className="kb-weak-list">
                    {progress.weak_points.slice(0, 10).map((k) => (
                      <div className="kb-weak-item" key={k.id}>
                        <span className="kb-weak-name">{k.name}</span>
                        <span className="kb-weak-ch">{k.chapter || '未归章'}</span>
                        <span className={`kb-pill tone-${stateTone(k.state ?? (Number(k.mastery) >= 70 ? 'mastered' : 'weak')).cls}`}>
                          {k.mastery}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {coverage && (
              <div className="card">
                <div className="card-head">
                  <div>
                    <div className="card-title">结构化覆盖体检</div>
                    <div className="card-sub">
                      {coverage.totals?.documents ?? 0} 篇资料 · {coverage.totals?.chunks ?? 0} 分块 ·{' '}
                      {coverage.totals?.ocr_documents ?? 0} 篇扫描件
                    </div>
                  </div>
                </div>
                <div className="card-body">
                  <table className="kb-cov-table">
                    <thead>
                      <tr><th>科目</th><th>分块</th><th>知识点</th><th>章节覆盖</th></tr>
                    </thead>
                    <tbody>
                      {coverage.subjects.filter((s) => s.documents > 0).map((s) => (
                        <tr key={s.subject} className={s.is_core ? '' : 'ext'}>
                          <td>
                            {s.subject}
                            {!s.is_core && <span className="kb-tag-ext">拓展</span>}
                          </td>
                          <td>{s.chunks}</td>
                          <td>{s.knowledge_points}</td>
                          <td>
                            {s.outline_chapters ? `${s.covered_chapters}/${s.outline_chapters}` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 知识点详情抽屉（点击知识点行打开） */}
      {detail.open && (
        <div className="kb-drawer-mask" onClick={closeDetail}>
          <aside
            className="kb-drawer"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="知识点详情"
          >
            <div className="kb-drawer-head">
              <div className="kb-drawer-titles">
                <div className="kb-drawer-name">{detail.data?.name || '知识点详情'}</div>
                <div className="kb-drawer-path">
                  {detail.data
                    ? `${detail.data.subject || ''}${detail.data.chapter ? ' · ' + detail.data.chapter : ''}`
                    : '加载中…'}
                </div>
              </div>
              <button className="kb-drawer-close" onClick={closeDetail} aria-label="关闭">✕</button>
            </div>
            <div className="kb-drawer-body">
              {detail.loading ? (
                <div className="loading-inline">详情加载中…</div>
              ) : detail.error ? (
                <div className="kb-drawer-err">
                  <AlertCircle size={16} /> {detail.error}
                  <div style={{ marginTop: 10 }}>
                    <button className="btn ghost" onClick={() => openDetail({ id: detail.data?.id })}>重试</button>
                  </div>
                </div>
              ) : detail.data ? (
                <>
                  <div className="kb-drawer-meta">
                    <div className="kb-drawer-cell">
                      <span className="kb-drawer-cell-label">掌握度</span>
                      <span className={`kb-drawer-cell-val tone-${dTone.cls}`} title={`状态：${dTone.label}`}>
                        {dTone.cls === 'new' ? '未学' : `${detail.data.mastery ?? 0}%`}
                      </span>
                    </div>
                    <div className="kb-drawer-cell">
                      <span className="kb-drawer-cell-label">考频</span>
                      <span className="kb-drawer-cell-val">{detail.data.exam_frequency ?? '—'}</span>
                    </div>
                    <div className="kb-drawer-cell">
                      <span className="kb-drawer-cell-label">难度</span>
                      <span className="kb-drawer-cell-val">{detail.data.difficulty ?? '—'}</span>
                    </div>
                    <div className="kb-drawer-cell">
                      <span className="kb-drawer-cell-label">关联题量</span>
                      <span className="kb-drawer-cell-val">{kpQCount == null ? '—' : `${kpQCount} 题`}</span>
                    </div>
                  </div>

                  {(detail.data.question_types || []).length > 0 && (
                    <div className="kb-drawer-section">
                      <div className="kb-drawer-section-title">题型</div>
                      <div className="kb-qtypes">
                        {detail.data.question_types.map((t) => (
                          <span className="kb-qtype" key={t}>{typeLabel(t)}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {detail.data.description && (
                    <div className="kb-drawer-section">
                      <div className="kb-drawer-section-title">描述</div>
                      <p className="kb-drawer-desc">{detail.data.description}</p>
                    </div>
                  )}

                  <div className="kb-drawer-section">
                    <div className="kb-drawer-section-title">
                      原文摘录
                      <span className="kb-drawer-count">{(detail.data.related_chunks || []).length}</span>
                    </div>
                    {(detail.data.related_chunks || []).length === 0 ? (
                      <div className="kb-drawer-empty">该知识点暂无关联原文</div>
                    ) : (
                      <div className="kb-drawer-chunks">
                        {detail.data.related_chunks.map((c) => (
                          <div className="kb-drawer-chunk" key={c.chunk_id}>
                            {c.doc_name && <div className="kb-drawer-chunk-src">{c.doc_name}</div>}
                            <div className="kb-drawer-chunk-text">{c.text || '（无文本）'}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="kb-drawer-section">
                    <div className="kb-drawer-section-title">
                      关联错题
                      <span className="kb-drawer-count">{(detail.data.related_errors || []).length}</span>
                    </div>
                    {(detail.data.related_errors || []).length === 0 ? (
                      <div className="kb-drawer-empty">暂无关联错题</div>
                    ) : (
                      <div className="kb-drawer-errs">
                        {detail.data.related_errors.map((e) => (
                          <div className="kb-drawer-err-item" key={e.id}>
                            <div className="kb-drawer-err-content">{e.content || '（无题干）'}</div>
                            <div className="kb-drawer-err-meta">
                              <span>我的答案：{e.my_answer || '—'}</span>
                              <span>正确答案：{e.correct_answer || '—'}</span>
                              {e.error_reason && <span>错因：{e.error_reason}</span>}
                            </div>
                            <button
                              className="kb-mini-btn"
                              onClick={() => navigate(
                                '/error-review?error_id=' + e.id +
                                '&subject=' + encodeURIComponent(e.subject || detail.data.subject || '')
                              )}
                            >
                              去复盘
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="kb-drawer-section">
                    <div className="kb-drawer-section-title">复习打卡</div>
                    <div className="kb-drawer-review-actions">
                      {REVIEW_ACTIONS.map((r) => (
                        <button
                          key={r.result}
                          className={`kb-mini-btn ${r.cls}`}
                          disabled={detailReviewing}
                          onClick={() => submitDetailReview(r.result)}
                        >
                          {r.label}
                        </button>
                      ))}
                    </div>
                    {detail.data.review_count > 0 && (
                      <div className="kb-drawer-review-hint">
                        已复习 {detail.data.review_count} 次 · 下次复习{' '}
                        {detail.data.next_review ? String(detail.data.next_review).slice(0, 10) : '—'}
                      </div>
                    )}
                  </div>
                </>
              ) : null}
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
