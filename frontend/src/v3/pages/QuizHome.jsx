import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  CardHead,
  Chip,
  Empty,
  Input,
  LoadingState,
  PageHeader,
  Progress,
  Segmented,
  Skeleton,
  toast,
} from '../ui'
import {
  BookOpen,
  Brain,
  Calendar,
  ChevronDown,
  ChevronRight,
  FileText,
  ListChecks,
  Play,
  RefreshCw,
  Search,
  Target,
  Wand,
} from '../icons'
import { quizApi, taxonomyApi, goalsApi, errorsApi, fetchAllPages } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { SOURCE_KINDS, SOURCE_KIND_LABEL, loadFavs, normQ } from './quizShared'
import QuizYear from './QuizYear'
import QuizWrongReview from './QuizWrongReview'
import Engineering08Practice from './Engineering08Practice'
import '../styles/quiz-v3.css'
import '../styles/study-glass.css'

/* =====================================================================
 * 刷题中心 · 首页（v3）
 * 统计带 / 来源 Tab（真题·教材题·全部）/ 三入口 Tab（知识点·年份·错题收藏）/
 * 练习-背题切换 / 自定义练习设置 / 智能组卷 / 按知识点（科目+章节树）。
 * 首页常驻挂载于容器（visible=false 时渲染 null），
 * 以便「返回题库」时保留 Tab、选中科目与分组缓存——与拆分前行为一致。
 * ===================================================================== */

/**
 * 刷题中心 · 首页（v3）
 * 统计带 / 来源 Tab（真题·教材题·全部）/ 三入口 Tab（知识点·年份·错题收藏）/
 * 练习-背题切换 / 自定义练习设置 / 智能组卷 / 按知识点（科目+章节树）。
 * 首页常驻挂载于容器（visible=false 时渲染 null），
 * 以便「返回题库」时保留 Tab、选中科目与分组缓存——与拆分前行为一致。
 * @param {Object} props
 * @param {boolean} props.visible - 是否可见（首页常驻挂载，不可见时返回 null）
 * @param {string} props.mode - practice | memorize
 * @param {(m: string) => void} props.setMode
 * @param {string} props.sourceKind - exam | textbook | all
 * @param {(s: string) => void} props.setSourceKind
 * @param {Object|null} props.kpFilter - 知识点筛选 {id,name} | null
 * @param {Object|null} props.kpEmpty - 知识点无题空态 {name} | null
 * @param {Object} props.favs - 收藏快照 {id: {content,subject,chapter,type}}
 * @param {boolean} props.submitting - 提交中（禁用整科练习按钮）
 * @param {Function} props.onBeginSession - 开始会话
 * @param {Function} props.onStartWithFilter - 按筛选开始
 * @param {Function} props.onClearKp - 清除知识点筛选
 * @param {Function} props.onContinueSession - 继续上次会话
 */
export default function QuizHome({
  visible,
  mode,
  setMode,
  sourceKind,
  setSourceKind,
  kpFilter,
  kpEmpty,
  favs,
  submitting,
  onBeginSession,
  onStartWithFilter,
  onClearKp,
  onContinueSession,
}) {
  const { user } = useAuth()
  /* URL ?subject= 初选科目（与拆分前 Quiz.jsx 的 selSubject 初值一致） */
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const isExamRoute = location.pathname.startsWith('/exam')
  const urlSubject = searchParams.get('subject') || ''

  /* ---------- 首页数据 ---------- */
  /* 支持 /quiz?tab=review 深链：顶部导航「错题库」直接落到错题与收藏页，
     用户不再需要在刷题中心里找入口。 */
  const urlTab = searchParams.get('tab')
  const [tab, setTab] = useState(
    isExamRoute ? 'year' : ['knowledge', 'year', 'review', 'engineering08'].includes(urlTab) ? urlTab : 'knowledge',
  ) // knowledge | year | review
  const [stats, setStats] = useState(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsErr, setStatsErr] = useState(false)
  const [latestSession, setLatestSession] = useState(null)

  const [subjects, setSubjects] = useState([])
  const [subjLoading, setSubjLoading] = useState(true)

  /* 按知识点：左选科目 + 右知识点树 */
  const [selSubject, setSelSubject] = useState(urlSubject || '')
  const selSubjectRef = useRef(false)
  /* 全局学科选择器联动：URL ?subject= 变化时同步本地选中科目（2026-10-24） */
  useEffect(() => {
    setSelSubject(urlSubject)
  }, [urlSubject])
  /* 未配置备考科目时不默认落到 taxonomy 的第一个科目（曾实测落到「中医综合」）。
     用户可显式选择「浏览全部科目」再进入。 */
  const [browseAll, setBrowseAll] = useState(false)
  const [tree, setTree] = useState(null)
  const [treeLoading, setTreeLoading] = useState(false)
  const [treeErr, setTreeErr] = useState(false)

  /* 用户配置的考试/支撑科目顺序（goals/subjects），用于科目列表排序与默认选中 */
  const [cfgOrder, setCfgOrder] = useState([])
  const cfgLoadedRef = useRef(false)

  /* ---------- 自定义练习设置（题量 / 科目多选 / 只练错题 / 只练收藏） ---------- */
  const [practiceCount, setPracticeCount] = useState('10') // '5' | '10' | '20' | 'custom'
  const [customCount, setCustomCount] = useState('15') // 自定义题量
  const [practiceSubs, setPracticeSubs] = useState([]) // 选中的科目名；空数组 = 全部科目
  const [onlyWrong, setOnlyWrong] = useState(false)
  const [onlyFav, setOnlyFav] = useState(false)
  const [customLoading, setCustomLoading] = useState(false)

  /* V11 智能组卷 loading：null | 'weak' | 'error_prone' | 'random' */
  const [smartLoading, setSmartLoading] = useState(null)

  /* 来源大类切换时重置「按年份」的分组懒加载缓存（与原实现同点击 handler 内清零等价） */
  const [groupResetKey, setGroupResetKey] = useState(0)

  /* ================= 数据加载 ================= */
  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    setStatsErr(false)
    try {
      setStats(await quizApi.stats())
    } catch {
      setStatsErr(true)
    } finally {
      setStatsLoading(false)
    }
  }, [])

  const loadCfgOrder = useCallback(async () => {
    if (cfgLoadedRef.current) return
    cfgLoadedRef.current = true
    try {
      const d = await goalsApi.subjects()
      setCfgOrder([...(d?.exam_subjects || []), ...(d?.support_subjects || [])])
    } catch {
      setCfgOrder([])
    }
  }, [])

  const loadSubjects = useCallback(async () => {
    setSubjLoading(true)
    try {
      const d = await taxonomyApi.subjects()
      /* 兼容两种返回：{subjects:[{subject,...}]} 或 {core,extension:[{name,...}]} */
      let items = d?.subjects
      if (!Array.isArray(items) || !items.length) {
        items = [...(d?.core || []), ...(d?.extension || [])].map((s) => ({
          subject: s.subject || s.name,
          chapters: s.chapters || [],
          question_count: s.question_count ?? 0,
          error_count: s.error_count ?? 0,
          is_custom: s.is_custom ?? false,
        }))
      }
      const list = Array.isArray(items) ? items.filter((s) => s && (s.subject || s.name)) : []
      /* 合并「可作答」题数：taxonomy 科目接口不带该字段，单独取 /quiz/subjects
         （后端已按 is_available 口径统计），把可作答题数与题量分别展示，避免
         「显示 2000 题、点进去 0 题可判分」的口径错位。 */
      let answerableMap = {}
      let visibleMap = {}
      try {
        const qs = await quizApi.subjects()
        const its = Array.isArray(qs?.items) ? qs.items : Array.isArray(qs) ? qs : []
        answerableMap = Object.fromEntries(its.map((x) => [x.subject, x.answerable_count ?? 0]))
        visibleMap = Object.fromEntries(its.map((x) => [x.subject, x.visible_count ?? x.question_count ?? 0]))
      } catch {
        answerableMap = {}
        visibleMap = {}
      }
      for (const s of list) {
        const name = s.subject || s.name
        if (answerableMap[name] != null) s.answerable_count = answerableMap[name]
        if (visibleMap[name] != null) s.visible_count = visibleMap[name]
      }
      /* 排序：用户配置科目在前（按配置顺序），其余按有题优先、最后 0 题 */
      const cfgIdx = (name) => {
        const i = cfgOrder.indexOf(name)
        return i < 0 ? 9999 : i
      }
      const sorted = [...list].sort((a, b) => {
        const ca = cfgIdx(a.subject || a.name),
          cb = cfgIdx(b.subject || b.name)
        if (ca !== cb) return ca - cb
        const qa = (a.question_count || 0) > 0 ? 0 : 1
        const qb = (b.question_count || 0) > 0 ? 0 : 1
        if (qa !== qb) return qa - qb
        return 0
      })
      setSubjects(sorted)
      /* 默认选中：只从「用户配置的备考科目」里选（优先有题的）。
         未配置时不回退到 sorted[0]——那会把无关科目当成用户的目标。 */
      if (!selSubjectRef.current) {
        /* 未配置备考科目：只有「题库里仅一个科目」时才自动选它（此时不存在
           “替用户假设方向”的问题）；多科目必须让用户先配置或主动浏览。 */
        if (!cfgOrder.length) {
          if (sorted.length === 1) setSelSubject(sorted[0].subject || sorted[0].name)
          return
        }
        const preferred = cfgOrder.map((n) => sorted.find((s) => (s.subject || s.name) === n)).filter(Boolean)
        const target = preferred.find((s) => (s.question_count || 0) > 0) || preferred[0]
        if (target) setSelSubject(target.subject || target.name)
      }
    } catch {
      setSubjects([])
    } finally {
      setSubjLoading(false)
    }
  }, [cfgOrder])

  const loadTree = useCallback(async (subj) => {
    if (!subj) {
      setTree(null)
      return
    }
    setTreeLoading(true)
    setTreeErr(false)
    try {
      const d = await taxonomyApi.tree(subj, false)
      setTree(Array.isArray(d?.tree) ? d.tree[0] || null : null)
    } catch {
      setTreeErr(true)
      setTree(null)
    } finally {
      setTreeLoading(false)
    }
  }, [])

  useEffect(() => {
    loadStats()
  }, [loadStats])
  const loadLatestSession = useCallback(async () => {
    if (!visible || !user) return
    const data = await quizApi.latestSession?.()
    setLatestSession(data?.session_id && data.status === 'in_progress' ? data : null)
  }, [visible, user])

  useEffect(() => {
    let alive = true
    Promise.resolve(quizApi.latestSession?.()).then((data) => {
      if (alive) setLatestSession(data?.session_id && data.status === 'in_progress' ? data : null)
    }).catch(() => { if (alive) setLatestSession(null) })
    return () => { alive = false }
  }, [visible, user])
  useEffect(() => {
    loadCfgOrder()
  }, [loadCfgOrder])
  /* P0-6：真题库为空时不要默认停在「历年真题」让用户看到 0 题。
     实测题库 386 道全是教材题（source_kind=exam 返回 total 0），默认落在真题
     的用户一进刷题中心就是空的，点「开始练习」只会拿到「当前设置下没有可用题目」。

     首次进入 /quiz 同时探测**两侧**题量：默认落到有题的一侧；若当前侧 0 题而
     另一侧有题，下方空态再给出「去教材题」直达按钮（不只是"暂无数据"文案）。
     用户在 URL 显式指定 source_kind 或进入 /exam 真题中心时不自动干预。 */
  const [sourceCounts, setSourceCounts] = useState({ exam: null, textbook: null })
  useEffect(() => {
    // 深链直达（?chapter= / ?kp_id=）会立刻开一场练习，此时来源 Tab 不由探测决定，
    // 也不需要占用 quizApi.questions 的调用序列（回归测试按首次调用断言深链参数）。
    if (searchParams.get('chapter') || searchParams.get('kp_id')) return
    let alive = true
    const probe = (sk) =>
      quizApi
        .questions({ source_kind: sk, page: 1, page_size: 1 })
        .then((d) => d?.total_count ?? d?.total ?? 0)
        .catch(() => null) // 探测失败不干预默认值
    Promise.all([probe('exam'), probe('textbook')]).then(([exam, textbook]) => {
      if (!alive) return
      setSourceCounts({ exam, textbook })
      if (isExamRoute || searchParams.get('source_kind')) return
      if (exam === 0 && (textbook || 0) > 0) setSourceKind('textbook')
    })
    return () => {
      alive = false
    }
    // 仅在首次挂载时探测一次；后续用户主动切换不再覆盖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  /* URL 与 Tab 双向同步：
     - 顶部导航点「错题库」→ ?tab=review
     - 错题库空态点「去刷题」→ /quiz 无参数，回到按知识点，不能停留在错题库 */
  useEffect(() => {
    if (isExamRoute) {
      setTab('year')
      return
    }
    setTab(['knowledge', 'year', 'review', 'engineering08'].includes(urlTab) ? urlTab : 'knowledge')
  }, [urlTab, isExamRoute])
  /* 等配置科目顺序就绪后再加载科目列表，保证排序/默认选中正确 */
  useEffect(() => {
    if (cfgLoadedRef.current || cfgOrder.length) loadSubjects()
  }, [cfgOrder, loadSubjects])
  /* 科目加载后：仅在「已配置备考科目」或用户主动浏览全部时，才默认选中第一个 */
  useEffect(() => {
    if (selSubject || !subjects.length) return
    if (!cfgOrder.length && !browseAll && subjects.length > 1) return
    const target = subjects.find((s) => (s.question_count || 0) > 0) || subjects[0]
    if (target) setSelSubject(target.subject)
  }, [subjects, selSubject, cfgOrder.length, browseAll])
  useEffect(() => {
    loadTree(selSubject)
  }, [selSubject, loadTree])

  /* ================= 自定义练习 =================
      题量：5 / 10 / 20 / 自定义；科目：多选（来自已加载的 subjects 列表，
      空选 = 全部科目）；来源：只练错题 / 只练收藏（二选一，均进入浏览模式——
      错题与收藏快照不携带选项，无法自动判分）。
      数据来源：错题 = errorsApi.list({status:'active'})；收藏 = 本地
      quiz_favorites_v9；普通出题 = quizApi.questions（多科目逐个请求后合并）。 */
  /** 启动自定义练习：按题量/科目/错题/收藏组合出题并进入会话 */
  const startCustomPractice = useCallback(async () => {
    const n = practiceCount === 'custom' ? parseInt(customCount, 10) : parseInt(practiceCount, 10)
    const size = Number.isFinite(n) && n > 0 ? Math.min(n, 200) : 10
    if (onlyWrong && onlyFav) {
      toast('「只练错题」与「只练收藏」请二选一')
      return
    }
    setCustomLoading(true)
    try {
      let qs = []
      let errorBasis = null
      if (onlyWrong) {
        const rows = await fetchAllPages((p) => errorsApi.list({ ...p, status: 'active' }), {
          keys: ['errors'],
        })
        for (let i = rows.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1))
          ;[rows[i], rows[j]] = [rows[j], rows[i]]
        }
        const selected = rows.slice(0, size)
        const loaded = await Promise.all(selected.map(async (error) => {
          if (!Number(error.question_id)) throw new Error('部分错题没有关联原题，请先前往错题本补录题目')
          const detail = await quizApi.questionDetail(error.question_id)
          const question = { ...normQ(detail), id: String(detail.id), error_id: Number(error.id) }
          if (!question.content) throw new Error('原题内容为空，无法重练')
          return question
        }))
        qs = loaded
        errorBasis = {
          kind: 'error_review',
          title: `自定义错题重练（${loaded.length} 题）`,
          error_ids: selected.map((error) => Number(error.id)),
          question_error_ids: Object.fromEntries(loaded.map((question) => [question.id, question.error_id])),
          loaded: loaded.length,
          answerableCount: loaded.length,
          totalCount: loaded.length,
        }
      } else if (onlyFav) {
        const favMap = loadFavs()
        qs = Object.entries(favMap).map(([id, f]) => ({
          id,
          content: f.content || '',
          options: [],
          answer: '',
          analysis: '',
          subject: f.subject || '',
          chapter: f.chapter || '',
          difficulty: 1,
          question_type: f.type || '',
        }))
      } else {
        const targetSubs = practiceSubs.length ? practiceSubs : subjects.map((s) => s.subject).filter(Boolean)
        const results = await Promise.all(
          (targetSubs.length ? targetSubs : ['']).map((sub) =>
            quizApi
              .questions({
                subject: sub || undefined,
                source_kind: sourceKind !== 'all' ? sourceKind : undefined,
                answerable: true,
                page: 1,
                page_size: size,
                // 随机抽题：默认是顺序模式，只拿第一页等于每次都练同一批题。
                mode: 'random',
              })
              .catch(() => ({ questions: [] })),
          ),
        )
        qs = results.flatMap((d) => (d?.questions || d?.items || []).map(normQ))
      }
      /* 科目一致性过滤 + 去重 */
      if (practiceSubs.length && !onlyWrong && !onlyFav) {
        qs = qs.filter((q) => practiceSubs.includes(q.subject))
      }
      const seen = new Set()
      qs = qs.filter((q) => (seen.has(q.id) ? false : (seen.add(q.id), true)))
      /* 打乱后截取题量 */
      for (let i = qs.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1))
        ;[qs[i], qs[j]] = [qs[j], qs[i]]
      }
      qs = qs.slice(0, size)
      if (!qs.length) {
        toast('当前设置下没有可用题目，请调整科目或开关')
        return
      }
      const browse = onlyFav
      const parts = [
        onlyWrong ? '错题' : onlyFav ? '收藏' : practiceSubs.length ? practiceSubs.join('+') : '全部科目',
      ]
      const title = `自定义练习 · ${parts.join(' · ')}（${qs.length} 题）`
      const sessionBasis = errorBasis || {
        title,
        subject: practiceSubs[0] || null,
        chapter: null,
        kpName: null,
        sourceKind,
        sourceKindLabel: SOURCE_KIND_LABEL[sourceKind] || '全部来源',
        noAnswer: browse,
        loaded: qs.length,
        answerableCount: browse ? null : qs.length,
        totalCount: qs.length,
        dropped: 0,
      }
      await onBeginSession(title, qs, mode, 0, browse, sessionBasis)
      if (onlyFav) toast('收藏快照不携带选项，已进入浏览模式（不判分、不进错题本）')
    } catch (e) {
      toast(onlyWrong ? `错题重练失败：${e?.message || '无法读取原题'}` : '自定义练习拉题失败，请确认后端已启动')
    } finally {
      setCustomLoading(false)
      try { await loadLatestSession() } catch { /* 首页继续上次入口保持原状态 */ }
    }
  }, [practiceCount, customCount, onlyWrong, onlyFav, practiceSubs, subjects, sourceKind, mode, onBeginSession, loadLatestSession])

  /** V11 智能组卷：调 /api/insight/smart-paper 成卷后直接进入练习
   *  @param {string} m - weak | error_prone | random */
  const runSmartPaper = useCallback(async (m) => {
    setSmartLoading(m)
    try {
      const { insightApi } = await import('../../api/client')
      const size = Math.min(
        Math.max(parseInt(practiceCount === 'custom' ? customCount : practiceCount, 10) || 20, 1),
        200,
      )
      const r = await insightApi.smartPaper({ mode: m, size, subject: selSubject || undefined })
      await onBeginSession(
        `智能组卷 · ${m === 'weak' ? '薄弱优先' : m === 'error_prone' ? '易错重练' : '随机'}（${r.size}题）`,
        r.questions,
        'practice',
      )
      toast(`已生成 ${r.size} 题：${r.basis?.slice(0, 40) || '就绪'}`)
    } catch (e) {
      toast(e?.message || '智能组卷失败')
    } finally {
      setSmartLoading(null)
      try { await loadLatestSession() } catch { /* 首页继续上次入口保持原状态 */ }
    }
  }, [practiceCount, customCount, selSubject, onBeginSession, loadLatestSession])

  /* 非首页视图时不渲染（组件保持挂载，首页状态因此跨练习保留） */
  if (!visible) return null

  const active =
    subjects.find((s) => s.subject === selSubject) ||
    (browseAll ? subjects.find((s) => (s.question_count || 0) > 0) || subjects[0] : null)

  /* ---------- 按知识点 ---------- */
  const renderKnowledge = () => {
    if (subjLoading)
      return (
        <Card>
          <LoadingState text="正在加载科目列表…" />
        </Card>
      )
    if (!subjects.length) {
      return (
        <Card>
          <Empty
            icon={<BookOpen size={26} />}
            title="暂无科目"
            text="科目从后端动态加载，请稍后重试"
            action={
              <Button variant="filled" onClick={loadSubjects}>
                重试
              </Button>
            }
          />
        </Card>
      )
    }
    /* 未配置备考科目：不默认选 taxonomy 的第一项（可能是中医综合等无关科目） */
    if (!selSubject && !cfgOrder.length && !browseAll && subjects.length > 1) {
      return (
        <Card>
          <Empty
            icon={<Target size={30} />}
            title="先配置你的备考科目"
            text="刷题默认科目会跟随「设置 → 目标与概览 → 备考科目」。未配置时系统不会替你假设专业方向；也可以先浏览全部科目。"
            action={
              <div className="v3-quiz-inline" style={{ justifyContent: 'center' }}>
                <a className="v3-btn v3-btn--filled" href="#/settings">
                  配置备考科目
                </a>
                <Button variant="ghost" onClick={() => setBrowseAll(true)}>
                  浏览全部 {subjects.length} 个科目
                </Button>
              </div>
            }
          />
        </Card>
      )
    }
    /* 默认选中第一个有题的科目（避免落在 0 题科目上，点「开始练习」无反应） */
    if (!active) return null
    const activeAnswerable = active?.answerable_count
    const chapters = tree?.chapters || []
    /* 学习路径推荐（对标粉笔「智能推荐下一步」）：在「有题的章节」里，
       优先推已开练但掌握度 <70% 的（薄弱巩固），其次推还没开始的（按大纲顺序）。
       依据都写在按钮文案里，不凭空造"进度"。 */
    const scored = chapters.filter((c) => (c.knowledge_point_count || 0) > 0)
    const nextStep = scored.length
      ? scored.find((c) => (c.avg_mastery || 0) > 0 && (c.avg_mastery || 0) < 0.7) ||
        scored.find((c) => !(c.avg_mastery > 0)) ||
        scored[0]
      : null
    const nextStepPct = nextStep ? Math.round((nextStep.avg_mastery || 0) * 100) : 0
    const nextStepWhy = nextStep
      ? nextStepPct > 0
        ? `已学过但掌握度 ${nextStepPct}%，先巩固这一章`
        : '尚未开始，按大纲顺序推进到这里'
      : ''
    return (
      <div className="v3-quiz-know v3-glasspage">
        <nav className="v3-quiz-subj-nav" aria-label="科目">
          {subjects.map((s) => {
            const on = s.subject === (active?.subject || '')
            const empty = (s.question_count || 0) === 0
            return (
              <button
                key={s.subject}
                type="button"
                className={`v3-quiz-subj ${on ? 'is-active' : ''} ${empty ? 'is-empty' : ''}`}
                title={empty ? `「${s.subject}」暂无题目，可先在题库管理导入` : undefined}
                onClick={() => {
                  if (empty) return toast(`「${s.subject}」暂无题目，可先在题库管理导入`)
                  setSelSubject(s.subject)
                }}
              >
                <span className="v3-quiz-subj__top">
                  <span className="v3-quiz-subj__name">{s.subject}</span>
                  <span className="v3-quiz-subj__count">
                    {s.question_count || 0}题
                    {empty ? <em className="v3-quiz-subj__empty">暂无题目</em> : null}
                  </span>
                </span>
                <span
                  className="v3-quiz-subj__meta"
                  title="可作答 = 有答案可判分；可见 = 排除 OCR 碎片后的该科目题量"
                >
                  <span className={s.answerable_count === 0 ? 'is-error' : ''}>
                    可作答 {s.answerable_count ?? '—'} / 可见 {s.visible_count ?? s.question_count ?? '—'}
                  </span>
                  {(s.error_count || 0) > 0 && <span className="is-error">错题 {s.error_count}</span>}
                  {s.is_custom && <span>自定义</span>}
                </span>
              </button>
            )
          })}
        </nav>

        <Card className="v3-quiz-know__main">
          <div className="v3-quiz-know__head">
            <div>
              <h2>{active?.subject || ''} · 学习路径</h2>
              <p className="v3-quiz-note">
                按章节推进练习；掌握度来自复习调度（/api/taxonomy/tree · avg_mastery）
              </p>
            </div>
            <Button
              variant="filled"
              disabled={!active || submitting}
              loading={submitting}
              onClick={() => {
                if ((active?.question_count || 0) === 0)
                  return toast('该科目暂无题目，可先在科目管理中维护或导入题目')
                onStartWithFilter({ subject: active.subject, title: `${active.subject} · 整科练习` })
              }}
            >
              {activeAnswerable === 0
                ? `浏览全部（${active?.question_count || 0}，不可判分）`
                : `整科练习（可作答 ${activeAnswerable ?? '—'}）`}
            </Button>
          </div>

          {nextStep && !treeLoading && !treeErr && (
            <button
              type="button"
              className="v3-quiz-pathnext"
              onClick={() =>
                onStartWithFilter({
                  subject: active.subject,
                  chapter: nextStep.title,
                  title: `${active.subject} · ${nextStep.title}`,
                })
              }
            >
              <span className="v3-quiz-pathnext__tag">建议下一步</span>
              <span className="v3-quiz-pathnext__body">
                <strong>{nextStep.title}</strong>
                <em>
                  {nextStepWhy} · {nextStep.knowledge_point_count || 0} 个知识点
                </em>
              </span>
              <ChevronRight size={16} className="v3-quiz-pathnext__go" />
            </button>
          )}

          {/* 依据明示：当前科目题量 vs 可作答题量，让用户清楚「能判分多少」 */}
          {active && (
            <Alert tone="info">
              当前依据：科目 <strong>{active.subject}</strong> · 可见题{' '}
              {active.visible_count ?? active.question_count ?? 0} 题 · 可作答 {activeAnswerable ?? '未知'} 题
              {activeAnswerable === 0 && '（该科目尚无标准答案，将进入「浏览模式」：不判分、不进错题本）'}
            </Alert>
          )}

          {treeLoading && <LoadingState text="正在加载知识点树…" />}
          {treeErr && (
            <Alert tone="danger">
              <div className="v3-quiz-inline">
                <span>
                  <strong>知识点树加载失败：</strong>网络或服务暂不可用，请重试。
                </span>
                <Button size="sm" variant="text" onClick={() => loadTree(active?.subject)}>
                  重试
                </Button>
              </div>
            </Alert>
          )}
          {!treeLoading && !treeErr && !chapters.length && (
            <Empty
              icon={<ChevronRight size={24} />}
              title="该科目暂无章节"
              text="可先在科目管理中维护考纲章节"
            />
          )}

          {!treeLoading && !treeErr && !!chapters.length && (
            <div className="v3-quiz-chapter-list">
              {chapters.map((c, i) => {
                const mastery = Math.round((c.avg_mastery || 0) * 100)
                return (
                  <button
                    key={c.title}
                    type="button"
                    className="v3-quiz-chapter"
                    onClick={() =>
                      onStartWithFilter({
                        subject: active.subject,
                        chapter: c.title,
                        title: `${active.subject} · ${c.title}`,
                      })
                    }
                  >
                    <span className="v3-quiz-chapter__idx">{String(i + 1).padStart(2, '0')}</span>
                    <span className="v3-quiz-chapter__main">
                      <span className="v3-quiz-chapter__name">{c.title}</span>
                      <span className="v3-quiz-chapter__meta">
                        <span>{c.knowledge_point_count || 0} 个知识点</span>
                        <span className="v3-quiz-chapter__bar">
                          <Progress value={mastery} />
                        </span>
                        <span>掌握度 {mastery}%</span>
                      </span>
                    </span>
                    <span className="v3-quiz-chapter__go">
                      开始练习 <ChevronRight size={14} />
                    </span>
                  </button>
                )
              })}
            </div>
          )}
          {!treeLoading && !treeErr && !!chapters.length && (
            <p className="v3-quiz-note">
              口径说明：章节题数按后端科目统计；掌握度来自 /api/taxonomy/tree 的 avg_mastery（复习调度口径）。
            </p>
          )}
        </Card>
      </div>
    )
  }

  return (
    <div className="v3-quiz">
      <PageHeader
        eyebrow={isExamRoute ? 'REAL EXAM · 真题中心' : 'QUIZ CENTER · 刷题中心'}
        title={isExamRoute ? '真题中心' : '刷题中心'}
        sub="覆盖考纲知识点与历年真题，点选即判、即时显示答案与解析；答错自动收入错题本，薄弱点一目了然。支持练习 / 背题双模式与键盘快捷作答。"
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              icon={<RefreshCw size={15} />}
              onClick={loadStats}
              disabled={statsLoading}
            >
              刷新统计
            </Button>
            {/* 沉浸式全屏刷题入口：进入 /studio/quiz 二级全屏页（壳外路由，无侧边栏） */}
            <Link
              to={urlSubject ? `/studio/quiz?subject=${encodeURIComponent(urlSubject)}` : '/studio/quiz'}
              style={{ textDecoration: 'none' }}
              title="进入沉浸式全屏刷题页"
            >
              <Button variant="primary" size="sm" icon={<Play size={15} />}>
                全屏刷题
              </Button>
            </Link>
          </>
        }
      />

      {/* 访客引导：未登录也能浏览科目/题量，但开始答题需登录 */}
      {!user && (
        <Alert tone="info" icon={<BookOpen size={16} />} className="v3-quiz-login-hint">
          <div
            className="v3-quiz-inline"
            style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}
          >
            <span>
              <strong>登录后开始刷题：</strong>答题判分、错题归集、记忆卡片与学习统计都跟着账号走。
            </span>
            <Link
              to="/login"
              state={{ from: { pathname: '/quiz' } }}
              className="v3-btn v3-btn--filled v3-btn--sm"
            >
              登录 / 注册
            </Link>
          </div>
        </Alert>
      )}

      {latestSession && onContinueSession && (
        <Card className="v3-quiz-continue">
          <div className="v3-quiz-inline" style={{ justifyContent: 'space-between', gap: 12 }}>
            <div>
              <strong>继续上次</strong>
              <div className="v3-quiz-keyhint">
                {latestSession.title} · 已作答 {latestSession.answered_count || 0}/{latestSession.total_questions || 0} 题
              </div>
            </div>
            <Button variant="filled" icon={<Play size={15} />} onClick={() => onContinueSession(latestSession)}>
              继续作答
            </Button>
          </div>
        </Card>
      )}

      {/* 统计带（W4 精简）：题库口径两数常显；答题行为数**有数据才出现**——
          「已完成作答 0 次 / 正确率 0% / 待攻克 0 题」不是信息，是噪音
          （对标粉笔/考研帮：首页只给当前有用的下一步，不做零值陈列柜）。 */}
      {tab !== 'engineering08' && (
      <div className="v3-quiz-statsline" aria-label="题库与作答概况">
        {statsLoading ? (
          <>
            <Skeleton width={72} height={20} radius={8} />
            <Skeleton width={72} height={20} radius={8} />
          </>
        ) : statsErr ? (
          <span className="v3-quiz-statsline__item is-muted">
            统计加载失败
            <button type="button" className="v3-quiz-statsline__link" onClick={loadStats}>
              重试
            </button>
          </span>
        ) : (
          <>
            <span className="v3-quiz-statsline__item" title="已排除 OCR 碎片题后的题库总量">
              题库 <b>{stats?.visible_total ?? stats?.total_questions ?? 0}</b> 题
            </span>
            <span className="v3-quiz-statsline__sep" aria-hidden="true" />
            <span className="v3-quiz-statsline__item" title="有标准答案、可自动判分的题">
              可作答 <b>{stats?.answerable_total ?? 0}</b>
            </span>
            {(stats?.total_attempts || 0) > 0 && (
              <>
                <span className="v3-quiz-statsline__sep" aria-hidden="true" />
                <span className="v3-quiz-statsline__item" title="你累计判分作答的次数">
                  已作答 <b>{stats?.total_attempts}</b> 次 · 正确率{' '}
                  <b>{Math.round(stats?.accuracy_rate || 0)}%</b>
                </span>
              </>
            )}
            {(stats?.total_attempts || 0) === 0 && !statsLoading && !statsErr && (
              <>
                <span className="v3-quiz-statsline__sep" aria-hidden="true" />
                <span className="v3-quiz-statsline__item is-muted">
                  还没有作答记录，正确率将在你答完第一批题后出现（样本不足）
                </span>
              </>
            )}
            {(stats?.active_errors || 0) > 0 && (
              <>
                <span className="v3-quiz-statsline__sep" aria-hidden="true" />
                <button
                  type="button"
                  className="v3-quiz-statsline__item is-danger v3-quiz-statsline__link"
                  title="活跃错题会进入复习闭环；点直达错题库"
                  onClick={() => setTab('review')}
                >
                  待攻克错题 <b>{stats?.active_errors}</b> 题 →
                </button>
              </>
            )}
          </>
        )}
      </div>
      )}

      {/* 知识点级筛选标识：仅在 URL 带 kp_id 时出现，让用户明确当前按知识点刷题 */}
      {tab !== 'engineering08' && kpFilter && (
        <Alert tone="info">
          <div className="v3-quiz-inline">
            <span>
              当前筛选：知识点 <strong>{kpFilter.name}</strong>
            </span>
            <Button size="sm" variant="text" onClick={onClearKp}>
              清除筛选
            </Button>
          </div>
        </Alert>
      )}

      {/* 知识点筛选命中 0 题：显式空态兜底，不白屏 */}
      {tab !== 'engineering08' && kpEmpty && (
        <Card>
          <Empty
            icon={<Search size={26} />}
            title={`知识点「${kpEmpty.name}」暂无关联题目`}
            text="该知识点尚未关联题目，可先返回知识点全景页选择其它知识点，或按科目/章节刷题。"
            action={
              <Button variant="filled" onClick={onClearKp}>
                返回题库首页
              </Button>
            }
          />
        </Card>
      )}

      {tab !== 'engineering08' && statsErr && (
        <Alert tone="danger">
          <div className="v3-quiz-inline">
            <span>
              <strong>统计数据加载失败</strong>：请确认后端服务已启动后重试。
            </span>
            <Button size="sm" variant="text" onClick={loadStats}>
              重试
            </Button>
          </div>
        </Alert>
      )}

      {/* 来源分离（M0）+ 三入口 Tab + 练习/背题切换 */}
      <Card variant="tonal" className="v3-quiz-controls">
        {tab !== 'engineering08' && (
        <div className="v3-quiz-bar">
          <Segmented
            ariaLabel="题目来源"
            value={sourceKind}
            onChange={(v) => {
              setSourceKind(v)
              setGroupResetKey((k) => k + 1)
            }}
            options={SOURCE_KINDS.map((s) => ({
              value: s.id,
              label: s.label,
              icon:
                s.id === 'exam' ? (
                  <FileText size={14} />
                ) : s.id === 'textbook' ? (
                  <BookOpen size={14} />
                ) : (
                  <ListChecks size={14} />
                ),
            }))}
          />
          <span className="v3-quiz-bar__label">
            当前依据：<strong>{SOURCE_KIND_LABEL[sourceKind] || '全部来源'}</strong>
            {sourceKind === 'exam' ? '（真题与教材题已分离，不混排）' : ''}
          </span>
        </div>
        )}
        <div className="v3-quiz-bar">
          <Segmented
            ariaLabel="刷题入口"
            value={tab}
            onChange={(nextTab) => {
              setTab(nextTab)
              setSearchParams((prev) => {
                const params = new URLSearchParams(prev)
                if (nextTab === 'knowledge') params.delete('tab')
                else params.set('tab', nextTab)
                return params
              }, { replace: true })
            }}
            options={[
              { value: 'knowledge', label: '按知识点', icon: <Brain size={14} /> },
              { value: 'year', label: '按年份', icon: <Calendar size={14} /> },
              { value: 'review', label: '错题库', icon: <Search size={14} /> },
              { value: 'engineering08', label: '工科08', icon: <Target size={14} /> },
            ]}
          />
          <Segmented
            ariaLabel="练习模式"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'practice', label: '练习模式', icon: <Play size={14} /> },
              { value: 'memorize', label: '背题模式', icon: <BookOpen size={14} /> },
            ]}
          />
        </div>
      </Card>

      {/* P0-6：当前来源 0 题、而另一侧有题时，给一个「去教材题」直达按钮。 */}
      {tab !== 'engineering08' && sourceKind === 'exam' && sourceCounts?.exam === 0 && (sourceCounts?.textbook || 0) > 0 && (
        <Card>
          <Empty
            icon={<Search size={26} />}
            title="「历年真题」当前没有题目"
            text={`题库里暂无真题（0 道），但教材题有 ${sourceCounts.textbook} 道。点击下方按钮直接切到教材题开始刷题。`}
            action={
              <Button
                variant="filled"
                onClick={() => {
                  setSourceKind('textbook')
                  setGroupResetKey((k) => k + 1)
                  toast(`已切换到「教材题」（${sourceCounts.textbook} 道），可直接开始练习`)
                }}
              >
                去教材题（{sourceCounts.textbook} 道）
              </Button>
            }
          />
        </Card>
      )}

      {/* 自定义练习：题量 / 科目多选 / 只练错题 / 只练收藏 */}
      {tab !== 'engineering08' && (
      <Card>
        <CardHead
          title="自定义练习"
          sub={
            onlyWrong
              ? '候选池为全部活跃错题，回取完整原题后判分'
              : onlyFav
                ? '候选池为本地收藏快照（浏览模式）'
                : '题量、科目范围与随机抽题'
          }
          actions={
            <Button
              variant="filled"
              icon={<Play size={15} />}
              disabled={customLoading}
              onClick={startCustomPractice}
            >
              {customLoading ? '出题中…' : '开始练习'}
            </Button>
          }
        />
        <div className="v3-quiz-custom">
          <div className="v3-quiz-custom__row">
            <strong>题量</strong>
            <Segmented
              ariaLabel="练习题量"
              value={practiceCount}
              onChange={setPracticeCount}
              options={['5', '10', '20', 'custom'].map((c) => ({
                value: c,
                label: c === 'custom' ? '自定义' : `${c} 题`,
              }))}
            />
            {practiceCount === 'custom' && (
              <Input
                className="v3-quiz-count"
                type="number"
                min="1"
                max="200"
                value={customCount}
                onChange={(e) => setCustomCount(e.target.value)}
                placeholder="题量"
                aria-label="自定义题量"
              />
            )}
            <Chip
              active={onlyWrong}
              onClick={() => {
                setOnlyWrong((v) => !v)
                if (!onlyWrong) setOnlyFav(false)
              }}
            >
              只练错题
            </Chip>
            <Chip
              active={onlyFav}
              onClick={() => {
                setOnlyFav((v) => !v)
                if (!onlyFav) setOnlyWrong(false)
              }}
            >
              只练收藏
            </Chip>
          </div>

          {/* 科目多选：默认收起，避免科目一多就把设置挤出可视区 */}
          {!onlyWrong && !onlyFav && subjects.length > 0 && (
            <details className="v3-quiz-picker">
              <summary>
                <span>科目范围</span>
                <b>{practiceSubs.length ? `已选 ${practiceSubs.length} 个` : '全部科目'}</b>
                {practiceSubs.length > 0 && (
                  <span className="v3-quiz-note" style={{ margin: 0 }}>
                    {practiceSubs.slice(0, 3).join('、')}
                    {practiceSubs.length > 3 ? ' 等' : ''}
                  </span>
                )}
                <ChevronDown size={14} className="v3-quiz-picker__caret" />
              </summary>
              <div className="v3-quiz-picker__panel">
                <div className="v3-quiz-picker__chips">
                  {subjects.map((s) => {
                    const name = s.subject || s.name
                    const on = practiceSubs.includes(name)
                    return (
                      <Chip
                        key={name}
                        active={on}
                        title={`${name} · 题量 ${s.question_count || 0}`}
                        onClick={() =>
                          setPracticeSubs((prev) => (on ? prev.filter((x) => x !== name) : [...prev, name]))
                        }
                      >
                        {name}
                        <small style={{ marginLeft: 4, opacity: 0.7 }}>{s.question_count || 0}</small>
                      </Chip>
                    )
                  })}
                </div>
                <div className="v3-quiz-picker__foot">
                  <span>不选 = 全部科目；可多选组合出题。</span>
                  {practiceSubs.length > 0 && (
                    <Button size="sm" variant="ghost" onClick={() => setPracticeSubs([])}>
                      清空选择
                    </Button>
                  )}
                </div>
              </div>
            </details>
          )}
        </div>
      </Card>
      )}

      {tab === 'knowledge' && (
        <>
          {/* V11 智能组卷（薄弱优先/易错重练/随机）：数据已齐，一键成卷 */}
          <Card className="v3-quiz-smart">
            <span className="v3-quiz-smart__label">
              <Wand size={15} />
              智能组卷
            </span>
            {[
              { m: 'weak', label: '薄弱优先', tip: '按薄弱考点自动抽题' },
              { m: 'error_prone', label: '易错重练', tip: '从你的错题规律抽同类题' },
              { m: 'random', label: '随机', tip: '随机抽题练手感' },
            ].map((x) => (
              <Chip key={x.m} disabled={!!smartLoading} title={x.tip} onClick={() => runSmartPaper(x.m)}>
                {smartLoading === x.m ? '组卷中…' : x.label}
              </Chip>
            ))}
            <span className="v3-quiz-note" style={{ marginLeft: 'auto' }}>
              按当前科目与题量生成
            </span>
          </Card>
          {renderKnowledge()}
        </>
      )}
      <QuizYear
        visible={visible && tab === 'year'}
        tab={tab}
        groupResetKey={groupResetKey}
        sourceKind={sourceKind}
        mode={mode}
        onBeginSession={onBeginSession}
      />
      <QuizWrongReview
        visible={visible && tab === 'review'}
        tab={tab}
        favs={favs}
        mode={mode}
        onBeginSession={onBeginSession}
      />
      <Engineering08Practice
        visible={visible && tab === 'engineering08'}
        mode={mode}
        onBeginSession={onBeginSession}
      />
    </div>
  )
}
