import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { Empty, toast, CountUp } from '../components/UI'
import { LoadingState, ErrorState } from '../components/States'
import { quizApi, taxonomyApi, goalsApi, errorsApi, fetchAllPages } from '../api/client'
import { SOURCE_KINDS, SOURCE_KIND_LABEL, loadFavs, normQ } from './quizShared'
import { ChevronDown, Target } from '../components/Icon'
import QuizYear from './QuizYear'
import QuizReview from './QuizReview'

/* =====================================================================
 * 刷题中心 · 首页（自 Quiz.jsx 拆出）
 * Hero+统计带 / 来源 Tab（真题·教材题·全部）/ 三入口 Tab（知识点·年份·错题收藏）/
 * 练习-背题切换 / 自定义练习设置 / 智能组卷 / 按知识点（科目+章节树）。
 * 首页常驻挂载于容器（visible=false 时渲染 null），
 * 以便「返回题库」时保留 Tab、选中科目与分组缓存——与拆分前行为一致。
 * ===================================================================== */

export default function QuizHome({
  visible, mode, setMode, sourceKind, setSourceKind,
  backendOk, setBackendOk, kpFilter, kpEmpty, favs, submitting,
  onBeginSession, onStartWithFilter, onClearKp,
}) {
  /* URL ?subject= 初选科目（与拆分前 Quiz.jsx 的 selSubject 初值一致） */
  const [searchParams] = useSearchParams()
  const location = useLocation()
  const isExamRoute = location.pathname.startsWith('/exam')
  const urlSubject = searchParams.get('subject') || ''

  /* ---------- 首页数据 ---------- */
  /* 支持 /quiz?tab=review 深链：顶部导航「错题库」直接落到错题与收藏页，
     用户不再需要在刷题中心里找入口。 */
  const urlTab = searchParams.get('tab')
  const [tab, setTab] = useState(isExamRoute ? 'year' : (['knowledge', 'year', 'review'].includes(urlTab) ? urlTab : 'knowledge')) // knowledge | year | review
  const [stats, setStats] = useState(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsErr, setStatsErr] = useState(false)

  const [subjects, setSubjects] = useState([])
  const [subjLoading, setSubjLoading] = useState(true)

  /* 按知识点：左选科目 + 右知识点树 */
  const [selSubject, setSelSubject] = useState(urlSubject || '')
  const selSubjectRef = useRef(false)
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
  const [practiceCount, setPracticeCount] = useState('10')  // '5' | '10' | '20' | 'custom'
  const [customCount, setCustomCount] = useState('15')      // 自定义题量
  const [practiceSubs, setPracticeSubs] = useState([])      // 选中的科目名；空数组 = 全部科目
  const [onlyWrong, setOnlyWrong] = useState(false)
  const [onlyFav, setOnlyFav] = useState(false)
  const [customLoading, setCustomLoading] = useState(false)

  /* V11 智能组卷 loading：null | 'weak' | 'error_prone' | 'random' */
  const [smartLoading, setSmartLoading] = useState(null)

  /* 来源大类切换时重置「按年份」的分组懒加载缓存（与原实现同点击 handler 内清零等价） */
  const [groupResetKey, setGroupResetKey] = useState(0)

  /* ================= 数据加载 ================= */
  const loadStats = useCallback(async () => {
    setStatsLoading(true); setStatsErr(false)
    try {
      setStats(await quizApi.stats()); setBackendOk(true)
    } catch { setStatsErr(true); setBackendOk(false) }
    finally { setStatsLoading(false) }
  }, [setBackendOk])

  const loadCfgOrder = useCallback(async () => {
    if (cfgLoadedRef.current) return
    cfgLoadedRef.current = true
    try {
      const d = await goalsApi.subjects()
      setCfgOrder([...(d?.exam_subjects || []), ...(d?.support_subjects || [])])
    } catch { setCfgOrder([]) }
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
          is_custom: s.is_custom ?? false
        }))
      }
      const list = (Array.isArray(items) ? items.filter((s) => s && (s.subject || s.name)) : [])
      /* 合并「可作答」题数：taxonomy 科目接口不带该字段，单独取 /quiz/subjects
         （后端已按 is_available 口径统计），把可作答题数与题量分别展示，避免
         「显示 2000 题、点进去 0 题可判分」的口径错位。 */
      let answerableMap = {}
      let visibleMap = {}
      try {
        const qs = await quizApi.subjects()
        const its = Array.isArray(qs?.items) ? qs.items : (Array.isArray(qs) ? qs : [])
        answerableMap = Object.fromEntries(its.map((x) => [x.subject, x.answerable_count ?? 0]))
        visibleMap = Object.fromEntries(its.map((x) => [x.subject, x.visible_count ?? x.question_count ?? 0]))
      } catch { answerableMap = {}; visibleMap = {} }
      for (const s of list) {
        const name = s.subject || s.name
        if (answerableMap[name] != null) s.answerable_count = answerableMap[name]
        if (visibleMap[name] != null) s.visible_count = visibleMap[name]
      }
      /* 排序：用户配置科目在前（按配置顺序），其余按有题优先、最后 0 题 */
      const cfgIdx = (name) => { const i = cfgOrder.indexOf(name); return i < 0 ? 9999 : i }
      const sorted = [...list].sort((a, b) => {
        const ca = cfgIdx(a.subject || a.name), cb = cfgIdx(b.subject || b.name)
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
        const preferred = cfgOrder
          .map((n) => sorted.find((s) => (s.subject || s.name) === n))
          .filter(Boolean)
        const target = preferred.find((s) => (s.question_count || 0) > 0) || preferred[0]
        if (target) setSelSubject(target.subject || target.name)
      }
    } catch { setSubjects([]) }
    finally { setSubjLoading(false) }
  }, [cfgOrder])

  const loadTree = useCallback(async (subj) => {
    if (!subj) { setTree(null); return }
    setTreeLoading(true); setTreeErr(false)
    try {
      const d = await taxonomyApi.tree(subj, false)
      setTree(Array.isArray(d?.tree) ? d.tree[0] || null : null)
    } catch { setTreeErr(true); setTree(null) }
    finally { setTreeLoading(false) }
  }, [])

  useEffect(() => { loadStats() }, [loadStats])
  useEffect(() => { loadCfgOrder() }, [loadCfgOrder])
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
    const probe = (sk) => quizApi.questions({ source_kind: sk, page: 1, page_size: 1 })
      .then((d) => d?.total_count ?? d?.total ?? 0)
      .catch(() => null) // 探测失败不干预默认值
    Promise.all([probe('exam'), probe('textbook')]).then(([exam, textbook]) => {
      if (!alive) return
      setSourceCounts({ exam, textbook })
      if (isExamRoute || searchParams.get('source_kind')) return
      if (exam === 0 && (textbook || 0) > 0) setSourceKind('textbook')
    })
    return () => { alive = false }
    // 仅在首次挂载时探测一次；后续用户主动切换不再覆盖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  /* URL 与 Tab 双向同步：
     - 顶部导航点「错题库」→ ?tab=review
     - 错题库空态点「去刷题」→ /quiz 无参数，回到按知识点，不能停留在错题库 */
  useEffect(() => {
    if (isExamRoute) { setTab('year'); return }
    setTab(['knowledge', 'year', 'review'].includes(urlTab) ? urlTab : 'knowledge')
  }, [urlTab, isExamRoute])
  /* 等配置科目顺序就绪后再加载科目列表，保证排序/默认选中正确 */
  useEffect(() => { if (cfgLoadedRef.current || cfgOrder.length) loadSubjects() }, [cfgOrder, loadSubjects])
  /* 科目加载后：仅在「已配置备考科目」或用户主动浏览全部时，才默认选中第一个 */
  useEffect(() => {
    if (selSubject || !subjects.length) return
    if (!cfgOrder.length && !browseAll && subjects.length > 1) return
    const target = subjects.find((s) => (s.question_count || 0) > 0) || subjects[0]
    if (target) setSelSubject(target.subject)
  }, [subjects, selSubject, cfgOrder.length, browseAll])
  useEffect(() => { loadTree(selSubject) }, [selSubject, loadTree])

  /* ================= 自定义练习 =================
     题量：5 / 10 / 20 / 自定义；科目：多选（来自已加载的 subjects 列表，
     空选 = 全部科目）；来源：只练错题 / 只练收藏（二选一，均进入浏览模式——
     错题与收藏快照不携带选项，无法自动判分）。
     数据来源：错题 = errorsApi.list({status:'active'})；收藏 = 本地
     quiz_favorites_v9；普通出题 = quizApi.questions（多科目逐个请求后合并）。 */
  const startCustomPractice = async () => {
    const n = practiceCount === 'custom' ? parseInt(customCount, 10) : parseInt(practiceCount, 10)
    const size = Number.isFinite(n) && n > 0 ? Math.min(n, 200) : 10
    if (onlyWrong && onlyFav) { toast('「只练错题」与「只练收藏」请二选一'); return }
    setCustomLoading(true)
    try {
      let qs = []
      if (onlyWrong) {
        // 「只练错题」的候选池必须是全部活跃错题：此前只取第一页 200 条，
        // 第 201 条以后的错题在自定义练习里永远抽不到。
        const rows = await fetchAllPages((p) => errorsApi.list({ ...p, status: 'active' }), { keys: ['errors'] })
        qs = rows.map((e) => ({
          id: String(e.question_id || e.id), content: e.content || '', options: [],
          answer: e.correct_answer || '', analysis: e.analysis || '',
          subject: e.subject || '', chapter: '错题', difficulty: 1, question_type: '',
        }))
      } else if (onlyFav) {
        const favMap = loadFavs()
        qs = Object.entries(favMap).map(([id, f]) => ({
          id, content: f.content || '', options: [], answer: '', analysis: '',
          subject: f.subject || '', chapter: f.chapter || '', difficulty: 1, question_type: f.type || '',
        }))
      } else {
        const targetSubs = practiceSubs.length ? practiceSubs
          : subjects.map((s) => s.subject).filter(Boolean)
        const results = await Promise.all((targetSubs.length ? targetSubs : ['']).map((sub) =>
          quizApi.questions({
            subject: sub || undefined,
            source_kind: sourceKind !== 'all' ? sourceKind : undefined,
            answerable: true, page: 1, page_size: size,
            // 随机抽题：默认是顺序模式，只拿第一页等于每次都练同一批题。
            mode: 'random',
          }).catch(() => ({ questions: [] }))
        ))
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
      if (!qs.length) { toast('当前设置下没有可用题目，请调整科目或开关'); return }
      const browse = onlyWrong || onlyFav
      const parts = [onlyWrong ? '错题' : onlyFav ? '收藏' : (practiceSubs.length ? practiceSubs.join('+') : '全部科目')]
      const title = `自定义练习 · ${parts.join(' · ')}（${qs.length} 题）`
      onBeginSession(title, qs, mode, 0, browse, {
        title, subject: practiceSubs[0] || null, chapter: null, kpName: null,
        sourceKind, sourceKindLabel: SOURCE_KIND_LABEL[sourceKind] || '全部来源',
        noAnswer: browse, loaded: qs.length,
        answerableCount: browse ? null : qs.length, totalCount: qs.length, dropped: 0,
      })
      if (browse) toast('错题/收藏题不携带选项，已进入浏览模式（不判分、不进错题本）')
    } catch {
      toast('自定义练习拉题失败，请确认后端已启动')
    } finally { setCustomLoading(false) }
  }

  /* V11 智能组卷：调 /api/insight/smart-paper 成卷后直接进入练习 */
  const runSmartPaper = async (m) => {
    setSmartLoading(m)
    try {
      const { insightApi } = await import('../api/client')
      const size = Math.min(Math.max(parseInt(practiceCount === 'custom' ? customCount : practiceCount, 10) || 20, 1), 200)
      const r = await insightApi.smartPaper({ mode: m, size, subject: selSubject || undefined })
      onBeginSession(`智能组卷 · ${m === 'weak' ? '薄弱优先' : m === 'error_prone' ? '易错重练' : '随机'}（${r.size}题）`, r.questions, 'practice')
      toast(`已生成 ${r.size} 题：${r.basis?.slice(0, 40) || '就绪'}`)
    } catch (e) {
      toast(e?.message || '智能组卷失败')
    } finally {
      setSmartLoading(null)
    }
  }

  /* 非首页视图时不渲染（组件保持挂载，首页状态因此跨练习保留） */
  if (!visible) return null

  /* ---------- 按知识点 ---------- */
  const renderKnowledge = () => {
    if (subjLoading) return <div className="card"><LoadingState text="正在加载科目列表…" rows={4} /></div>
    if (!subjects.length) {
      return <Empty icon="资料" title="暂无科目" desc="科目从后端动态加载，请稍后重试"
        action={<button className="btn primary" onClick={loadSubjects}>重试</button>} />
    }
    /* 未配置备考科目：不默认选 taxonomy 的第一项（可能是中医综合等无关科目） */
    if (!selSubject && !cfgOrder.length && !browseAll && subjects.length > 1) {
      return (
        <div className="card" style={{ padding: 'var(--space-8) var(--space-5)' }}>
          <Empty
            icon={<Target size={40} />}
            title="先配置你的备考科目"
            desc="刷题默认科目会跟随「设置 → 目标与概览 → 备考科目」。未配置时系统不会替你假设专业方向；也可以先浏览全部科目。"
            action={(
              <div className="row">
                <a className="btn primary" href="#/settings">配置备考科目</a>
                <button className="btn ghost" onClick={() => setBrowseAll(true)}>
                  浏览全部 {subjects.length} 个科目
                </button>
              </div>
            )}
          />
        </div>
      )
    }
    /* 默认选中第一个有题的科目（避免落在 0 题科目上，点「开始练习」无反应） */
    const active = subjects.find((s) => s.subject === selSubject)
      || (browseAll ? (subjects.find((s) => (s.question_count || 0) > 0) || subjects[0]) : null)
    if (!active) return null
    const activeAnswerable = active?.answerable_count
    const chapters = tree?.chapters || []
    return (
      <div className="qknow-layout">
        <nav className="qknow-nav" aria-label="科目">
          {subjects.map((s) => {
            const on = s.subject === (active?.subject || '')
            return (
              <button key={s.subject} className={`qknow-subj ${on ? 'active' : ''}`}
                onClick={() => setSelSubject(s.subject)}>
                <span className="qknow-subj-top">
                  <span className="qknow-subj-name">{s.subject}</span>
                  <span className="qknow-subj-cnt">{s.question_count || 0}题</span>
                </span>
                <span className="qknow-subj-meta" title="可作答 = 有答案可判分；可见 = 排除 OCR 碎片后的该科目题量">
                  <span className={s.answerable_count === 0 ? 'err' : ''}>
                    可作答 {s.answerable_count ?? '—'} / 可见 {s.visible_count ?? s.question_count ?? '—'}
                  </span>
                  <span className="err">错题 {s.error_count || 0}</span>
                  {s.is_custom && <span>自定义</span>}
                </span>
              </button>
            )
          })}
        </nav>

        <section>
          <div className="qknow-head">
            <div className="qknow-title">{active?.subject || ''} · 章节知识点</div>
            <button className="btn primary" disabled={!active || submitting}
              onClick={() => {
                if ((active?.question_count || 0) === 0) return toast('该科目暂无题目，可先在科目管理中维护或导入题目')
                onStartWithFilter({ subject: active.subject, title: `${active.subject} · 整科练习` })
              }}>
              {(activeAnswerable === 0)
                ? `浏览全部（${active?.question_count || 0}，不可判分）`
                : `整科练习（可作答 ${activeAnswerable ?? '—'}）`}
            </button>
          </div>

          {/* 依据明示：当前科目题量 vs 可作答题量，让用户清楚「能判分多少」 */}
          {active && (
            <p className="qnote flush" style={{ marginTop: 0 }}>
              当前依据：科目 <strong>{active.subject}</strong> · 可见题 {active.visible_count ?? active.question_count ?? 0} 题 ·
              可作答 {activeAnswerable ?? '未知'} 题
              {activeAnswerable === 0 && '（该科目尚无标准答案，将进入「浏览模式」：不判分、不进错题本）'}
            </p>
          )}

          {treeLoading && <div className="card"><LoadingState text="正在加载知识点树…" rows={3} /></div>}
          {treeErr && (
            <div className="card">
              <ErrorState title="知识点树加载失败" message="无法读取 /api/taxonomy/tree。" onRetry={() => loadTree(active?.subject)} />
            </div>
          )}
          {!treeLoading && !treeErr && !chapters.length && (
            <Empty icon="目录" title="该科目暂无章节" desc="可先在科目管理中维护考纲章节" />
          )}

          {!treeLoading && !treeErr && !!chapters.length && (
            <div className="qknow-list">
              {chapters.map((c, i) => {
                const mastery = Math.round((c.avg_mastery || 0) * 100)
                return (
                  <button key={c.title} className="qknow-row"
                    onClick={() => onStartWithFilter({ subject: active.subject, chapter: c.title, title: `${active.subject} · ${c.title}` })}>
                    <span className="qknow-idx">{String(i + 1).padStart(2, '0')}</span>
                    <span className="qknow-main">
                      <span className="qknow-name">{c.title}</span>
                      <span className="qknow-meta">
                        <span>{c.knowledge_point_count || 0} 个知识点</span>
                        <span className="qknow-bar progress thin"><i style={{ width: `${mastery}%` }} /></span>
                        <span>掌握度 {mastery}%</span>
                      </span>
                    </span>
                    <span className="qknow-action">开始练习 ›</span>
                  </button>
                )
              })}
            </div>
          )}
          {!treeLoading && !treeErr && !!chapters.length && (
            <p className="qnote">
              口径说明：章节题数按后端科目统计；掌握度来自 /api/taxonomy/tree 的 avg_mastery（复习调度口径）。
            </p>
          )}
        </section>
      </div>
    )
  }

  return (
    <div className="container stack">
      {/* Hero + 统计带 */}
      <section className="qh-hero">
        <div className="qh-hero-top">
          <div>
            <div className="qh-hero-eyebrow">{isExamRoute ? 'REAL EXAM · 真题中心' : 'QUIZ CENTER · 刷题中心'}</div>
            <h1 className="qh-hero-title">{isExamRoute ? '历年真题，按年份整卷精练' : '历年真题，按知识点、按年份精准刷'}</h1>
            <p className="qh-hero-desc">
              覆盖考纲知识点与历年真题，点选即判、即时显示答案与解析；答错自动收入错题本，
              薄弱点一目了然。支持练习 / 背题双模式与键盘快捷作答。
            </p>
          </div>
          <dl className="qh-hero-stats">
            <div className="qh-hstat" title="可见题：已排除 OCR 碎片题后的题库总量">
              <dt>可见题</dt>
              <dd>{statsLoading ? '…' : <CountUp value={stats?.visible_total ?? stats?.total_questions ?? 0} />}<small>题</small></dd>
            </div>
            <div className="qh-hstat" title="可作答：有答案、可用于自动判分的题">
              <dt>可作答</dt>
              <dd>{statsLoading ? '…' : <CountUp value={stats?.answerable_total ?? 0} />}<small>题</small></dd>
            </div>
            <div className="qh-hstat">
              <dt>已完成作答</dt>
              <dd>{statsLoading ? '…' : <CountUp value={stats?.total_attempts || 0} />}<small>次</small></dd>
            </div>
            <div className="qh-hstat">
              <dt>正确率</dt>
              <dd>{statsLoading ? '…' : Math.round(stats?.accuracy_rate || 0)}<small>%</small></dd>
            </div>
            <div className="qh-hstat">
              <dt>待攻克错题</dt>
              <dd>{statsLoading ? '…' : <CountUp value={stats?.active_errors || 0} />}<small>题</small></dd>
            </div>
          </dl>
        </div>
        <div className="qh-hero-note">
          <span>可见题已排除 OCR 碎片题</span>
          <span>·「可作答」= 有答案、可自动判分</span>
          {backendOk
            ? <span className="live-dot">· 已连接真实题库</span>
            : <span className="offline-dot">· 统计加载失败，显示为 0，可重试</span>}
        </div>
      </section>

      {/* 知识点级筛选标识：仅在 URL 带 kp_id 时出现，让用户明确当前按知识点刷题 */}
      {kpFilter && (
        <div className="qkp-filter card">
          <span className="qkp-filter-tag">收藏 当前筛选：知识点 {kpFilter.name}</span>
          <button className="btn mini ghost" onClick={onClearKp}>
            清除筛选
          </button>
        </div>
      )}

      {/* 知识点筛选命中 0 题：显式空态兜底，不白屏 */}
      {kpEmpty && (
        <Empty icon="搜索" title={`知识点「${kpEmpty.name}」暂无关联题目`}
          desc="该知识点尚未关联题目，可先返回知识点全景页选择其它知识点，或按科目/章节刷题。"
          action={<button className="btn primary" onClick={onClearKp}>
            返回题库首页
          </button>} />
      )}

      {statsErr && (
        <div className="card">
          <ErrorState title="统计数据加载失败" message="无法读取 /api/quiz/stats，请确认后端已启动。" onRetry={loadStats} retryText="重试" />
        </div>
      )}

      {/* 来源分离（M0）：真题 / 教材题 / 全部来源。
          默认「历年真题」——真题与教材题不再混在同一个列表里；
          本 Tab 同时决定「按知识点 / 按年份 / 错题收藏」三个视图的取题范围。 */}
      <div className="qbar">
        <div className="qtab-bar" role="tablist" aria-label="题目来源">
          {SOURCE_KINDS.map((s) => (
            <button key={s.id} role="tab" aria-selected={sourceKind === s.id}
              className={`qtab-btn ${sourceKind === s.id ? 'active' : ''}`}
              title={s.id === 'all' ? '混合展示全部来源（真题+教材题）' : `只展示${s.label}`}
              onClick={() => { setSourceKind(s.id); setGroupResetKey((k) => k + 1) }}>
              {s.label}
            </button>
          ))}
        </div>
        <span className="qnote flush" style={{ margin: 0 }}>
          当前依据：<strong>{SOURCE_KIND_LABEL[sourceKind] || '全部来源'}</strong>
          {sourceKind === 'exam' ? '（真题与教材题已分离，不混排）' : ''}
        </span>
      </div>

      {/* P0-6：当前来源 0 题、而另一侧有题时，给一个「去教材题」直达按钮。
          过去只显示一句"暂无数据"文案，用户不知道题库其实有题、只是不在这一侧。 */}
      {sourceKind === 'exam' && sourceCounts?.exam === 0 && (sourceCounts?.textbook || 0) > 0 && (
        <div className="card">
          <Empty
            icon="搜索"
            title="「历年真题」当前没有题目"
            desc={`题库里暂无真题（0 道），但教材题有 ${sourceCounts.textbook} 道。点击下方按钮直接切到教材题开始刷题。`}
            action={(
              <button className="btn primary" onClick={() => {
                setSourceKind('textbook')
                setGroupResetKey((k) => k + 1)
                toast(`已切换到「教材题」（${sourceCounts.textbook} 道），可直接开始练习`)
              }}>
                去教材题（{sourceCounts.textbook} 道）
              </button>
            )}
          />
        </div>
      )}

      {/* 三入口 Tab + 练习/背题切换 */}
      <div className="qbar">
        <div className="qtab-bar" role="tablist">
          {[
            { id: 'knowledge', label: '按知识点' },
            { id: 'year', label: '按年份' },
            { id: 'review', label: '错题库' }
          ].map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id}
              className={`qtab-btn ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>
        <div className="qmode-toggle">
          <button className={`qmode-btn ${mode === 'practice' ? 'active' : ''}`}
            onClick={() => setMode('practice')} title="作答后才显示答案与解析">练习模式</button>
          <button className={`qmode-btn ${mode === 'memorize' ? 'active' : ''}`}
            onClick={() => setMode('memorize')} title="直接显示答案与解析">背题模式</button>
        </div>
      </div>

      {/* 自定义练习：题量 / 科目多选 / 只练错题 / 只练收藏 */}
      <div className="card" style={{ padding: 'var(--space-3) var(--space-4)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 'var(--text-sm)', color: 'var(--fg-2)' }}>设置 自定义练习</strong>
          <div className="seg" role="tablist" aria-label="练习题量">
            {['5', '10', '20', 'custom'].map((c) => (
              <button key={c} role="tab" aria-selected={practiceCount === c}
                className={`seg-btn ${practiceCount === c ? 'active' : ''}`}
                onClick={() => setPracticeCount(c)}>
                {c === 'custom' ? '自定义' : `${c} 题`}
              </button>
            ))}
          </div>
          {practiceCount === 'custom' && (
            <input className="input" style={{ width: 90 }} type="number" min="1" max="200"
              value={customCount} onChange={(e) => setCustomCount(e.target.value)}
              placeholder="题量" aria-label="自定义题量" />
          )}
          <button className={`btn mini ${onlyWrong ? 'primary' : 'ghost'}`}
            onClick={() => { setOnlyWrong((v) => !v); if (!onlyWrong) setOnlyFav(false) }}>
            只练错题
          </button>
          <button className={`btn mini ${onlyFav ? 'primary' : 'ghost'}`}
            onClick={() => { setOnlyFav((v) => !v); if (!onlyFav) setOnlyWrong(false) }}>
            只练收藏
          </button>
          <button className="btn mini primary" disabled={customLoading} onClick={startCustomPractice}>
            {customLoading ? '出题中…' : '开始练习'}
          </button>
        </div>
        {/* 科目多选：默认收起。此前把全部科目摊成一整面 chip 墙，
            科目一多就挤满半屏，把真正要设置的题量/开关压到看不见。 */}
        {!onlyWrong && !onlyFav && subjects.length > 0 && (
          <details className="qsub-picker">
            <summary>
              <span className="qsub-label">科目范围</span>
              <b>{practiceSubs.length ? `已选 ${practiceSubs.length} 个` : '全部科目'}</b>
              {practiceSubs.length > 0 && (
                <span className="qsub-preview">{practiceSubs.slice(0, 3).join('、')}{practiceSubs.length > 3 ? ' 等' : ''}</span>
              )}
              <ChevronDown size={14} className="qsub-caret" />
            </summary>
            <div className="qsub-panel">
              <div className="qsub-chips">
                {subjects.map((s) => {
                  const name = s.subject || s.name
                  const on = practiceSubs.includes(name)
                  return (
                    <button key={name} className={`chip ${on ? 'active' : ''}`}
                      title={`${name} · 题量 ${s.question_count || 0}`}
                      onClick={() => setPracticeSubs((prev) => (on ? prev.filter((x) => x !== name) : [...prev, name]))}>
                      {name}
                      <small>{s.question_count || 0}</small>
                    </button>
                  )
                })}
              </div>
              <div className="qsub-foot">
                <span>不选 = 全部科目；可多选组合出题。</span>
                {practiceSubs.length > 0 && (
                  <button className="btn sm ghost" onClick={() => setPracticeSubs([])}>清空选择</button>
                )}
              </div>
            </div>
          </details>
        )}
      </div>

      {tab === 'knowledge' && (
        <>
          {/* V11 智能组卷（薄弱优先/易错重练/随机）：数据已齐，一键成卷 */}
          <div className="qsmart" style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', marginBottom: 'var(--space-3)' }}>
            <strong style={{ fontSize: 'var(--text-sm)', color: 'var(--fg-2)', alignSelf: 'center' }}>快速 智能组卷：</strong>
            {[
              { m: 'weak', label: '薄弱优先', tip: '按薄弱考点自动抽题' },
              { m: 'error_prone', label: '易错重练', tip: '从你的错题规律抽同类题' },
              { m: 'random', label: '随机', tip: '随机抽题练手感' },
            ].map(x => (
              <button key={x.m} className="chip" disabled={smartLoading} title={x.tip}
                onClick={() => runSmartPaper(x.m)}>
                {smartLoading === x.m ? '组卷中…' : x.label}
              </button>
            ))}
          </div>
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
      <QuizReview
        visible={visible && tab === 'review'}
        tab={tab}
        favs={favs}
        mode={mode}
        onBeginSession={onBeginSession}
      />
    </div>
  )
}
