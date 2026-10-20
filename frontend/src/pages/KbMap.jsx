import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { taxonomyApi, reviewApi, quizApi, qualityApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { chatCompletion, defaultProvider, recordUsage } from '../utils/api'
import { toast, Empty } from '../components/UI'
import { LoadingState } from '../components/States'
import {
  RefreshCw, CheckCircle, ChevronRight,
  Book, Brain, AlertCircle, Map as MapIcon, Play, Target,
} from '../components/Icon'

/* =====================================================================
 * 知识地图（KbMap）：章节 → 知识点 → 例题/方法 三栏复习入口
 *   信息架构对标 gitgraduate.com/academy/pages/math-limits：
 *     左「章节」列表 → 中「知识点」卡片 → 右「例题/方法」详情 + 顶部居中置顶导航。
 *   与「知识点全景」（/panorama，图谱总览）分工：本页是沿着章节推进的复习动线，
 *   全景页是跨章节的掌握度热力总览；两页通过顶部导航与 ?subject&chapter&kp_id
 *   深链互跳，路由均保留。
 *   视觉沿用 kbmap.css 既有 .kb-* 色标与 global.css 令牌，零新依赖、零新配色。
 * ===================================================================== */

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
  const { user } = useAuth()
  const [subjects, setSubjects] = useState([])      // 动态科目列表（taxonomyApi.subjects）
  const [tree, setTree] = useState([])              // 结构树（taxonomyApi.tree）
  const [progress, setProgress] = useState(null)    // 全局掌握度总览
  const [due, setDue] = useState([])                // 今日复习队列
  const [coverage, setCoverage] = useState(null)    // 结构化覆盖体检
  const [quality, setQuality] = useState(null)      // 语料质量层（qualityApi.treeOverlay）
  const [status, setStatus] = useState('loading')   // loading | ok | error
  const [treeLoading, setTreeLoading] = useState(false)
  const [activeSubject, setActiveSubject] = useState('')
  const [reviewing, setReviewing] = useState(null)
  const [errMsg, setErrMsg] = useState('')

  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  /* 三栏选择态：左栏选中章节 → 中栏知识点 → 右栏例题/方法详情 */
  const [activeChapter, setActiveChapter] = useState(null)   // { subject, title }
  const [selectedKpId, setSelectedKpId] = useState(null)     // 中栏高亮 + 右栏数据源

  /* 知识点详情：来自 /api/taxonomy/knowledge-points/{id}；
     关联题量来自 /api/quiz/questions?kp_id=（tree 不返回题量，故单独查真实值）。 */
  const [detail, setDetail] = useState({ loading: false, error: '', data: null })
  const [kpQCount, setKpQCount] = useState(null)
  const [detailReviewing, setDetailReviewing] = useState(false)
  const detailSeq = useRef(0)

  /* 知识点 AI 精讲：调 utils/api 的 chatCompletion（与 GlobalAI 同链路，走后端 /api/ai/chat），
     结果在详情面板内嵌展示、可折叠；切换知识点时重置。 */
  const [aiExplain, setAiExplain] = useState({ open: false, loading: false, text: '', error: '' })
  const resetAiExplain = () => setAiExplain({ open: false, loading: false, text: '', error: '' })

  /* 首帧是否已完成初始化选择：URL 深链与默认选中只应用一次，
     后续刷新/复习回写不会把用户当前所在的章节与知识点冲掉。 */
  const bootstrappedRef = useRef(false)
  const selectedIdRef = useRef(null)
  /* URL 参数用 ref 透传（loadAll 无需把 searchParams 进依赖） */
  const paramsRef = useRef(searchParams)
  paramsRef.current = searchParams

  /* 打开知识点详情：并行拉取详情 + 关联题量（各自容错，防竞态） */
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
      quizApi.questions({ kp_id: id, page_size: 1 }),
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
    // 题量查询失败时置 null（界面显示 '—'），绝不伪造 0
    setKpQCount(
      qRes.status === 'fulfilled' && qRes.value && typeof qRes.value.total === 'number'
        ? qRes.value.total
        : null
    )
  }, [])

  const closeDetail = useCallback(() => {
    detailSeq.current++
    selectedIdRef.current = null
    setSelectedKpId(null)
    setDetail({ loading: false, error: '', data: null })
    setKpQCount(null)
  }, [])

  /* 首次加载：科目列表 + 全局总览 + 全量结构树 并行拉取 */
  const loadAll = useCallback(async () => {
    setStatus('loading')
    setErrMsg('')
    try {
      const [sj, t, p, d, c, q] = await Promise.all([
        taxonomyApi.subjects(),
        taxonomyApi.tree(),
        /* 访客（未登录）：复习进度/到期队列/语料质量层是登录态数据，跳过不打后端 */
        user ? reviewApi.progress() : Promise.resolve(null),
        user ? reviewApi.due({ limit: 30 }) : Promise.resolve(null),
        taxonomyApi.coverage(),
        user ? qualityApi.treeOverlay().catch(() => null) : Promise.resolve(null),
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
        /* 深链入参（来自「知识点全景」或外部链接）：subject/chapter/kp_id 优先 */
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
          // 默认展开第一个有知识点的科目首个有知识点的章节
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
        // 刷新/复习回写：保留当前选择，仅重拉右栏详情
        openDetail({ id: selectedIdRef.current })
      }
      setStatus('ok')
    } catch (e) {
      setErrMsg(e?.message || '未知错误')
      setStatus('error')
    }
    // user 入依赖：登录态就绪后重拉，访客切登录后掌握度/队列不再空白
  }, [openDetail, closeDetail, user])

  useEffect(() => { loadAll() }, [loadAll])

  /* 切换科目：仅重拉该科结构树，保留全局总览与队列 */
  const selectSubject = useCallback(async (name) => {
    if (name === activeSubject) return
    setActiveSubject(name)
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
      toast('加载知识结构失败：' + (e?.message || ''))
    } finally {
      setTreeLoading(false)
    }
  }, [activeSubject, openDetail, closeDetail])

  /* 左栏点选章节：中栏换成该章节知识点，右栏定位到第一个知识点 */
  const selectChapter = useCallback((subject, title, kpList) => {
    setActiveChapter({ subject, title })
    const kp = (kpList || [])[0]
    if (kp) openDetail(kp)
    else closeDetail()
  }, [openDetail, closeDetail])

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

  /* 右栏复习打卡：复用 reviewApi.submit，成功后刷新右栏与页面数据 */
  const submitDetailReview = async (result) => {
    const id = detail.data?.id ?? selectedKpId
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

  /* 知识点 → 刷题：知识点级精确出题 /quiz?subject=&chapter=&kp_id=&kp_name= */
  const goQuiz = useCallback((subject, chapter, kp) => {
    const params = new URLSearchParams()
    if (subject) params.set('subject', subject)
    if (chapter) params.set('chapter', chapter)
    if (kp?.id != null) params.set('kp_id', kp.id)
    if (kp?.name) params.set('kp_name', kp.name)
    navigate(`/quiz?${params.toString()}`)
  }, [navigate])

  /* AI 精讲：prompt 携带知识点名称、科目/章节、掌握度三态，走后端 /api/ai/chat 代理 */
  const runAiExplain = async () => {
    const d = detail.data
    if (!d || aiExplain.loading) return
    setAiExplain({ open: true, loading: true, text: '', error: '' })
    const tone = stateTone(kpState(d))
    const prompt = [
      `请为考研知识点「${d.name}」（科目：${d.subject || '未分类'}${d.chapter ? ' · ' + d.chapter : ''}）做一次精讲。`,
      `该知识点当前掌握度 ${d.mastery ?? 0}%（状态：${tone.label}），考频 ${d.exam_frequency ?? '未知'}，难度 ${d.difficulty ?? '未知'}。`,
      '请给出：1）核心概念与直觉解释；2）常用方法/公式；3）易错点；4）结合当前掌握状态给出 1-2 条针对性复习建议。用 markdown 列表，简洁。'
    ].join('\n')
    try {
      const r = await chatCompletion(defaultProvider(), [{ role: 'user', content: prompt }])
      recordUsage(r.usage, defaultProvider()?.id)
      setAiExplain((s) => ({ ...s, loading: false, text: r.text || '（AI 未返回内容）' }))
    } catch (e) {
      setAiExplain((s) => ({ ...s, loading: false, error: `AI 精讲失败：${e?.message || '未知错误'}` }))
    }
  }

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

  /* 科目选择 chips：/taxonomy/subjects 同时返回 knowledge_point_count 与
     question_count；知识地图并列标注两种口径，避免把题量误认为知识点数。
     兼容旧后端：缺 knowledge_point_count 时从 coverage/tree 补，仍不复用题量。 */
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
        // 后端给 0 但结构树里有 KP（科目别名/归一差异）时以结构树为准，
        // 保证 chip 数字与左栏「知识点 N」不打架。
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

  /* 「全部」chip 的合计：知识点数与题量分别累加，任一字段缺失都跳过而不是当 0，
     避免把"没这个字段"显示成"0 个知识点"。 */
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

  /* 当前科目的 chip（空态文案要用它的题量解释"为什么是 0 知识点"） */
  const activeChip = useMemo(
    () => (activeSubject ? chipSubjects.find((s) => s.subject === activeSubject) || null : null),
    [chipSubjects, activeSubject]
  )

  /* 左栏：章节分组（按科目；选科后仅该科） */
  const chapterGroups = useMemo(() => {
    const src = activeSubject ? tree.filter((s) => s.subject === activeSubject) : tree
    return src
      .map((s) => ({ subject: s.subject, is_core: s.is_core, node: s, chapters: s.chapters || [] }))
      .filter((g) => g.chapters.length > 0)
  }, [tree, activeSubject])

  /* 中栏：当前章节的知识点 */
  const activeChapterData = useMemo(() => {
    if (!activeChapter) return null
    const s = tree.find((x) => x.subject === activeChapter.subject)
    const ch = s?.chapters?.find((c) => c.title === activeChapter.title)
    return ch ? { subject: activeChapter.subject, chapter: ch } : null
  }, [tree, activeChapter])

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

  /* 只对得上名字，不做模糊归一：对不上时显示"未匹配"而不是"无语料"。 */
  const pickQuality = useCallback((name) => {
    if (!name) return null
    return qualityBySubject.get(name) || qualityBySubject.get(String(name).replace(/\s+/g, '')) || null
  }, [qualityBySubject])

  /* 置信分档：0.40 是后端 CONF_THRESHOLD，低于它标签视为不可信 */
  const corpusTone = (conf) => (conf != null && conf >= 0.40 ? 'ok' : 'low')

  /* ---------------- 三态：加载中 ---------------- */
  if (status === 'loading') {
    return <LoadingState text="知识结构加载中…" />
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

  const hasAnyKp = tree.some((s) => s.knowledge_point_count > 0)
  // 总览大数字：全部未学时置灰，否则按已学平均掌握度取黄/绿
  const overviewTone = dist && dist.total > 0 && dist.unlearned >= dist.total
    ? STATE_TONE.unlearned
    : masteryTone(progress ? (progress.learned_avg_mastery ?? progress.avg_mastery) : 0)
  // 右栏详情掌握度三态
  const dTone = stateTone(detail.data ? kpState(detail.data) : 'unlearned')

  return (
    <div className="page">
      {/* 页头 */}
      <div className="page-head">
        <div>
          <h1 className="page-title">知识地图</h1>
          <div className="page-sub">
            章节 → 知识点 → 例题 / 方法 三栏复习动线 · 点知识点直达刷题 ·
            与「知识点全景」（跨章节图谱总览）互跳
          </div>
        </div>
        {/* 模块内的「知识图谱」胶囊已移除（与面包屑/页标题重复）；
            保留 nav 地标供辅助技术与自动化用例定位当前模块。 */}
        <nav className="page-actions" aria-label="知识图谱">
          <button className="btn ghost" onClick={loadAll}>
            <RefreshCw size={15} /> 刷新
          </button>
        </nav>
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
            title="知识点数＝知识库结构化抽取的知识点；题量＝题库题目数，两者口径不同"
          >
            全部
            {chipTotals.hasKp && (
              <small>
                {chipTotals.kp} 知识点
                {chipTotals.hasQ ? ` · ${chipTotals.q} 题` : ''}
              </small>
            )}
          </button>
          {chipSubjects.map((s) => {
            const kpCount = typeof s.knowledge_point_count === 'number'
              ? s.knowledge_point_count
              : null
            const questionCount = typeof s.question_count === 'number'
              ? s.question_count
              : null
            return (
              <button
                key={s.subject}
                className={`kb-chip ${activeSubject === s.subject ? 'active' : ''}`}
                onClick={() => selectSubject(s.subject)}
                title="知识点数＝知识库结构化抽取的知识点；题量＝题库题目数，两者口径不同"
              >
                {s.subject}
                <small>
                  {kpCount == null ? '— 知识点' : `${kpCount} 知识点`}
                  {questionCount != null ? ` · ${questionCount} 题` : ''}
                </small>
              </button>
            )
          })}
        </div>
        {/* 教材↔知识地图双向打通入口：
            当前选中科目时，可直接跳到教材目录看该科指定书目
            （数据源 /api/textbooks/by-subject，26 本核心专业课教材）。
            未选科目则进入教材总目录。 */}
        <button
          type="button"
          className="kb-textbook-link"
          title={activeSubject
            ? `查看「${activeSubject}」的核心教材书目`
            : '查看电子通信考研核心专业课教材总目录'}
          onClick={() => navigate(
            activeSubject ? `/textbooks?subject=${encodeURIComponent(activeSubject)}` : '/textbooks'
          )}
        >
          <Book size={14} />
          {activeSubject ? '本科教材' : '教材总目录'}
        </button>
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
          action={(
            <button className="btn primary" onClick={() => navigate('/subjects')}>
              去科目管理
            </button>
          )}
        />
      ) : (
        <div className="kb3-layout">
          {/* 左：章节列表 */}
          <section className="kb3-col" aria-label="章节">
            <div className="kb3-col-title">章节</div>
            {treeLoading ? (
              <LoadingState text="结构加载中…" rows={0} />
            ) : !hasAnyKp ? (
              <Empty
                icon={<Brain size={44} />}
                title={activeSubject ? `「${activeSubject}」暂无知识点` : '知识点库为空'}
                desc={activeSubject
                  ? `该科目${typeof activeChip?.question_count === 'number'
                    ? `题库已有 ${activeChip.question_count} 题`
                    : '题库可能有题'}，但知识点数为 0 —— 题量 ≠ 知识点数。`
                    + '知识点来自教材/讲义的结构化抽取，题库题目不会自动生成知识结构。'
                    + '请到资料库上传该科资料并执行知识点抽取，完成后返回刷新。'
                  : '知识点数与题库题量是两个口径：这里统计的是从教材/讲义中抽取的结构化知识点。'
                    + '当前还没有任何知识点，请到资料库上传资料并执行知识点抽取，完成后返回刷新。'}
                action={(
                  <button className="btn primary" onClick={() => navigate('/documents')}>
                    去资料库导入
                  </button>
                )}
              />
            ) : (
              chapterGroups.map((g) => (
                <div className="card kb3-subgroup" key={g.subject}>
                  <div className="kb-subject-head">
                    <div className="kb-subject-titles">
                      <div className="kb-subject-name">
                        {g.subject}
                        {!g.is_core && <span className="kb-tag-ext">拓展</span>}
                      </div>
                      <div className="kb-subject-meta">
                        知识点 {g.node.knowledge_point_count ?? 0} · {g.node.outline_chapter_count ?? 0} 章节
                      </div>
                    </div>
                    <div className="kb-subject-mastery">
                      <span className={`kb-pill tone-${nodeTone(g.node).cls}`}>
                        {nodeTone(g.node).cls === 'new' ? '未学' : `平均 ${nodeAvg(g.node)}%`}
                      </span>
                    </div>
                  </div>

                  <div className="kb3-ch-list">
                    {g.chapters.map((ch) => {
                      const hasData = ch.knowledge_point_count > 0
                      const isSel = !!activeChapter
                        && activeChapter.subject === g.subject
                        && activeChapter.title === ch.title
                      const tone = nodeTone(ch)
                      return (
                        <button
                          key={ch.title}
                          type="button"
                          className={`kb3-ch ${isSel ? 'is-sel' : ''} ${hasData ? '' : 'is-empty'}`}
                          onClick={() => hasData && selectChapter(g.subject, ch.title, ch.knowledge_points)}
                          disabled={!hasData}
                          title={hasData ? `查看「${ch.title}」的知识点` : '该章节暂无资料'}
                        >
                          <ChevronRight size={14} className="kb3-ch-chevron" />
                          <span className="kb3-ch-title">{ch.title}</span>
                          <span className="kb3-ch-meta">
                            {hasData ? `${ch.knowledge_point_count} 个` : '暂无资料'}
                          </span>
                          {hasData && (
                            <span className={`kb-bar sm tone-${tone.cls}`}>
                              <i style={{ width: `${Math.min(100, nodeAvg(ch))}%` }} />
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))
            )}
          </section>

          {/* 中：知识点卡片 */}
          <section className="kb3-col" aria-label="知识点">
            <div className="kb3-col-title">
              知识点{activeChapter ? ` · ${activeChapter.title}` : ''}
            </div>
            {treeLoading ? (
              <LoadingState text="结构加载中…" rows={0} />
            ) : !activeChapterData ? (
              <Empty
                icon={<Target size={40} />}
                title="请选择章节"
                desc="从左栏选择一个章节，中间会列出该章节的全部知识点与掌握度。"
              />
            ) : (activeChapterData.chapter.knowledge_points || []).length === 0 ? (
              <Empty
                icon={<Brain size={40} />}
                title="该章节暂无知识点"
                desc="请到知识库上传对应章节资料并执行知识点抽取，完成后返回刷新。"
                action={(
                  <button className="btn primary" onClick={() => navigate('/documents')}>
                    去知识库导入
                  </button>
                )}
              />
            ) : (
              <div className="kb3-kp-cards">
                {(activeChapterData.chapter.knowledge_points || []).map((kp) => {
                  const kt = stateTone(kpState(kp))
                  const isSel = String(selectedKpId) === String(kp.id)
                  return (
                    <div
                      key={kp.id}
                      className={`kb3-kp-card ${isSel ? 'is-sel' : ''}`}
                    >
                      {/* 主区：点它 → 进入知识点阅读页（学术阅读版式，对标 gitgraduate）
                          原行为是展开右栏例题区，但「读概念」是复习主线动作，
                          阅读页承载考纲/教材原文/主动回忆/掌握度自评，比右栏更完整。 */}
                      <button
                        type="button"
                        className="kb3-kp-select"
                        onClick={() => navigate(`/knowledge/${kp.id}`)}
                        title={`阅读「${kp.name}」：考纲要求 · 教材原文 · 主动回忆`}
                      >
                        <span className="kb3-kp-head">
                          <span className={`kb-dot tone-${kt.cls}`} title={`掌握度 ${kp.mastery}（${kt.label}）`} />
                          <span className="kb3-kp-name">{kp.name}</span>
                          <span className={`kb3-kp-pct tone-${kt.cls}`}>
                            {kt.cls === 'new' ? '未学' : `${kp.mastery}%`}
                          </span>
                        </span>
                        <span className="kb3-kp-row">
                          <span className={`kb-bar tone-${kt.cls}`}>
                            <i style={{ width: `${Math.min(100, kp.mastery)}%` }} />
                          </span>
                          <span className="kb-kp-freq">
                            {kp.review_count ? `已复习 ${kp.review_count} 次` : '未复习'}
                          </span>
                        </span>
                        {(kp.question_types || []).length > 0 && (
                          <span className="kb-kp-tags">
                            {(kp.question_types || []).slice(0, 4).map((t) => (
                              <span className="kb-qtype sm" key={t}>{typeLabel(t)}</span>
                            ))}
                          </span>
                        )}
                      </button>
                      <div className="kb3-kp-foot">
                        <span className="kb3-kp-hint">点上方看例题 / 方法</span>
                        <button
                          type="button"
                          className="btn primary mini"
                          onClick={() => goQuiz(activeChapterData.subject, activeChapterData.chapter.title, kp)}
                          title="按该知识点精确出题"
                        >
                          <Play size={12} /> 开始练习
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </section>

          {/* 右：例题 / 方法 */}
          <section className="kb3-col kb3-col-detail" aria-label="例题与方法">
            <div className="kb3-col-title">例题 / 方法</div>
            <div className="card kb3-detail-card">
              <div className="card-body">
                {selectedKpId == null ? (
                  <div className="kb3-empty">
                    <Target size={18} /> 请从中间选择一个知识点
                  </div>
                ) : detail.loading ? (
                  <LoadingState text="详情加载中…" rows={0} />
                ) : detail.error ? (
                  <div className="kb-drawer-err">
                    <AlertCircle size={16} /> {detail.error}
                    <div style={{ marginTop: 'var(--space-3)' }}>
                      <button className="btn ghost" onClick={() => openDetail({ id: selectedKpId })}>重试</button>
                    </div>
                  </div>
                ) : detail.data ? (
                  <>
                    <div className="kb3-detail-head">
                      <div className="kb-drawer-name">{detail.data.name}</div>
                      <div className="kb-drawer-path">
                        {detail.data.subject || ''}{detail.data.chapter ? ' · ' + detail.data.chapter : ''}
                      </div>
                    </div>

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

                    <div className="kb3-detail-actions">
                      <button
                        className="btn primary"
                        onClick={() => goQuiz(
                          detail.data.subject,
                          detail.data.chapter,
                          { id: detail.data.id, name: detail.data.name }
                        )}
                      >
                        <Play size={14} /> 开始练习
                      </button>
                      <button className="btn outline" disabled={aiExplain.loading} onClick={runAiExplain}>
                        {aiExplain.loading ? '生成中…' : 'AI 精讲'}
                      </button>
                    </div>

                    {aiExplain.open && (
                      <div className="kb-drawer-section">
                        <div className="kb-drawer-section-title">AI 精讲</div>
                        {aiExplain.loading ? (
                          <div className="loading-inline">正在生成讲解…</div>
                        ) : aiExplain.error ? (
                          <div style={{ color: 'var(--danger)', fontSize: 'var(--text-sm)' }}>{aiExplain.error}</div>
                        ) : (
                          <p className="kb-drawer-desc" style={{ whiteSpace: 'pre-wrap' }}>{aiExplain.text}</p>
                        )}
                      </div>
                    )}

                    {(detail.data.question_types || []).length > 0 && (
                      <div className="kb-drawer-section">
                        <div className="kb-drawer-section-title">涉及题型</div>
                        <div className="kb-qtypes">
                          {detail.data.question_types.map((t) => (
                            <span className="kb-qtype" key={t}>{typeLabel(t)}</span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="kb-drawer-section">
                      <div className="kb-drawer-section-title">方法 / 要点</div>
                      {detail.data.description ? (
                        <p className="kb-drawer-desc">{detail.data.description}</p>
                      ) : (
                        <div className="kb-drawer-empty">该知识点暂无方法说明</div>
                      )}
                    </div>

                    <div className="kb-drawer-section">
                      <div className="kb-drawer-section-title">
                        例题 / 原文摘录
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
            </div>
          </section>
        </div>
      )}

      {/* 复习辅助：今日复习队列 + 薄弱知识点 + 覆盖率（复用既有卡片） */}
      {hasAnyKp && (
        <div className="kb-aux-grid">
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
                  <div className="card-title">掌握度最低的知识点</div>
                  <div className="card-sub">按掌握度升序，优先攻克</div>
                </div>
              </div>
              <div className="card-body">
                <div className="kb-weak-list">
                  {progress.weak_points.slice(0, 10).map((k) => (
                    <div className="kb-weak-item" key={k.id}>
                      <span className="kb-weak-name">{k.name}</span>
                      <span className="kb-weak-ch">{k.chapter || '未归章'}</span>
                      {/* state 由 services/kp_mastery 判定并随响应下发，前端不再自己抄一份阈值 */}
                      <span className={`kb-pill tone-${stateTone(k.state).cls}`}>
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
                <div className="table-container">
                <table className="kb-cov-table">
                  <thead>
                    <tr><th>科目</th><th>分块</th><th>知识点</th><th>章节覆盖</th></tr>
                  </thead>
                  <tbody>
                    {(coverage.subjects || []).filter((s) => s.documents > 0).map((s) => (
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
            </div>
          )}
        </div>
      )}
    </div>
  )
}
