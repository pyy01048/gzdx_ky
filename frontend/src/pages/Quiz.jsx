import React, { useMemo, useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Empty, toast, CountUp } from '../components/UI'
import { quizApi, taxonomyApi, errorsApi, goalsApi } from '../api/client'
import './Quiz.css'

/* =====================================================================
 * 刷题中心（V9 重做）
 * 信息架构移植自参考件 D:\桌面\1（Next.js 纯选择题训练）：
 *   首页 Hero+统计带 / 三入口 Tab（知识点·年份·错题收藏）/
 *   右侧答题卡 / 先选后提交 / 练习·背题双模式 / 键盘快捷键 /
 *   收藏星标 / 结果报告（正确率大字+知识点掌握+重练错题）。
 * 视觉全部走 V8 学术蓝设计令牌（Quiz.css 新增 class，不碰 global/v2）。
 * ===================================================================== */

/* 题型枚举：single 单选 / judge 判断 / fill 填空 / essay 简答 /
   calc 计算 / draw 作图 / multiple 多选（后端暂未返回，前端兼容）。 */
const TYPE_LABELS = {
  single: '单选', judge: '判断', fill: '填空',
  essay: '简答', calc: '计算', draw: '作图', multiple: '多选'
}
const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F']
const letterOf = (i) => LETTERS[i] || String(i + 1)

/* 本地错题 id 集合（与旧版 quiz_wrong 兼容；后端错题以 /api/errors 为准） */
const WRONG_KEY = 'quiz_wrong'
function loadWrong() { try { return JSON.parse(localStorage.getItem(WRONG_KEY) || '[]') } catch { return [] } }
function addWrong(id) {
  if (id == null) return
  const arr = loadWrong()
  if (!arr.map(String).includes(String(id))) {
    arr.push(String(id))
    try { localStorage.setItem(WRONG_KEY, JSON.stringify(arr)) } catch { /* 隐私模式 */ }
  }
}

/* 本地收藏（后端暂无 favorites 接口，按方案本地持久化题目快照） */
const FAV_KEY = 'quiz_favorites_v9'
function loadFavs() { try { return JSON.parse(localStorage.getItem(FAV_KEY) || '{}') } catch { return {} } }
function saveFavs(f) { try { localStorage.setItem(FAV_KEY, JSON.stringify(f)) } catch { /* 隐私模式 */ } }

/* V10 本地作答记录（单机口径）：{ [qid]: { times: n, correct: bool } }。
   替代标杆的「全站做过人数」，题号格颜色与做过次数均读这里。 */
const REC_KEY = 'quiz_records_v10'
function loadRecs() { try { return JSON.parse(localStorage.getItem(REC_KEY) || '{}') } catch { return {} } }
function pushRec(qid, correct) {
  try {
    const m = loadRecs()
    const prev = m[String(qid)] || { times: 0, correct: false }
    m[String(qid)] = { times: prev.times + 1, correct: !!correct }
    localStorage.setItem(REC_KEY, JSON.stringify(m))
  } catch { /* 隐私模式 */ }
}

/* 解析 source：`前缀:文档名`。真题/知识库/ai 三类来源。 */
function parseSource(src) {
  if (!src) return { prefix: '', doc: '' }
  const s = String(src)
  const i = s.indexOf(':')
  if (i < 0) return { prefix: '', doc: s }
  return { prefix: s.slice(0, i), doc: s.slice(i + 1) }
}
/* 分区：exam 真题原卷 / chapter 章节练习 / custom 自建题库（ai/其他）。
   知识库来源按文档名启发式判断是否为真题卷（含「真题/联考/年份」）。 */
function partitionOf(prefix, doc) {
  if (prefix === '真题') return 'exam'
  if (prefix === 'ai' || prefix === '') return 'custom'
  if (prefix === '知识库') {
    return /真题|联考|（\d{4}）|\(\d{4}\)|\d{4}\s*年|\d{4}年/.test(doc || '') ? 'exam' : 'chapter'
  }
  return 'custom'
}

/* 从 source 字段解析年份（如「真题:贵大2023年834真题.pdf」→ 2023）。
   后端 questions 接口暂无 year 筛选参数，故年份为前端解析，如实标注。 */
function yearOf(source) {
  if (!source) return null
  const m = String(source).match(/(?:19|20)\d{2}/)
  return m ? m[0] : null
}

function safeParseOptions(raw) {
  if (Array.isArray(raw)) return raw
  if (!raw) return []
  try { const v = JSON.parse(raw); return Array.isArray(v) ? v : [] } catch { return [] }
}

/* 剥掉选项自带的序号前缀。库内 options 元素普遍自带「A．」「A、」「A.」
   等前缀，若与 UI 的字母徽标同时渲染会出现「A  A．奇偶校验码」的重复文字。
   剥完为空时回退为原值，保证不丢内容。支持 A-H / a-h。 */
const OPT_LABEL_RE = /^\s*[（(]?\s*([A-Ha-h])\s*[）).、．:：]\s*/
export function stripOptLabel(opt) {
  const s = String(opt == null ? '' : opt)
  const m = s.match(OPT_LABEL_RE)
  if (!m) return s.trim()
  const rest = s.slice(m[0].length).trim()
  return rest || s.trim()
}

/* 从答案串中抽出正确选项的下标集合。兼容 'B' / 'B．' / '答案B' /
   'ABC'（多选）/ 'B、C' 等写法。返回 null 表示答案无法解析为字母。 */
export function answerIndexes(answer) {
  const s = String(answer == null ? '' : answer).toUpperCase()
  const m = s.match(/[A-H]/g)
  if (!m || !m.length) return null
  return new Set(m)
}

/** 判断第 optIndex 个选项（对应字母 letterOf(optIndex)）是否正确。 */
export function isCorrectOption(optIndex, answer) {
  const set = answerIndexes(answer)
  if (!set) return false
  return set.has(letterOf(optIndex))
}

/* 纯文本题（需要用户输入作答）：填空/简答/计算/作图。
   选择题的 answer 往往是孤立字母，不走输入自评流程——那条路径会让用户
   面对「答案是 D 却无选项」的题目输入文字并被判错，详见 isChoiceLike。 */
const TEXT_TYPES = ['fill', 'essay', 'calc', 'draw']
export function isTextQuestion(q) {
  if (TEXT_TYPES.includes(q?.question_type)) return true
  if (q?.question_type === 'multiple' || q?.question_type === 'single' || q?.question_type === 'judge') return false
  return !answerIndexes(q?.answer)   // 答案为纯字母 → 选择题
}
/** 选择题语义（含「options 为空但答案是字母」的残缺选择题）。 */
export function isChoiceLike(q) { return !isTextQuestion(q) }
/** 选择题但选项缺失：只读展示，禁止作答。 */
export function isChoiceWithoutOptions(q) {
  return isChoiceLike(q) && !(Array.isArray(q?.options) && q.options.filter(Boolean).length > 0)
}
/* 题面或答案依赖原书插图。 */
const FIG_RE = /如图|见图|下图|上图|图\s*\d+[-－]?\d*|所示图|图中/
export function dependsOnFigure(q) {
  return FIG_RE.test(String(q?.content || '')) || FIG_RE.test(String(q?.answer || ''))
}

/* 归一化后端题目 */
function normQ(q) {
  return {
    id: String(q.id),
    content: q.content || '',
    options: safeParseOptions(q.options),
    answer: q.answer ?? '',
    analysis: q.analysis || '',
    subject: q.subject || '',
    chapter: q.chapter || '',
    knowledge_point: q.knowledge_point || '',
    difficulty: q.difficulty || 1,
    source: q.source || '',
    question_type: q.question_type || '',
    year: q.year ?? null,
    paper: q.paper ?? null,
    question_no: q.question_no ?? null
  }
}
const isChoiceQ = (q) => Array.isArray(q.options) && q.options.length > 0
const isMultiQ = (q) => q.question_type === 'multiple'

/* 后端不可用时的最小演示题 */
const LOCAL_FALLBACK = [
  { id: 'l1', content: '设 A 为 3 阶矩阵，|A|=2，则 |2A^T| = ？', options: ['4', '8', '16', '32'], answer: 'C', analysis: '|kA|=k^n|A|=2^3×2=16。', subject: '数学', chapter: '行列式', difficulty: 2, question_type: 'single' },
  { id: 'l2', content: 'lim(x→0) (sin x)/x = ？', options: ['0', '1', '∞', '不存在'], answer: 'B', analysis: '重要极限之一。', subject: '数学', chapter: '极限', difficulty: 1, question_type: 'single' }
]

export default function Quiz() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const urlSubject = searchParams.get('subject') || ''
  const urlChapter = searchParams.get('chapter') || ''
  const urlType = searchParams.get('question_type') || ''
  /* 知识点级精确筛选（M1-3 全景页 startPractice 传入）。
     存在 kp_id 时按知识点拉题，否则保持原有 subject/chapter 降级逻辑不变。 */
  const urlKpId = searchParams.get('kp_id') || ''
  const urlKpName = searchParams.get('kp_name') || ''

  /* ---------- 视图与模式 ---------- */
  const [view, setView] = useState('home')            // home | practice | result
  const [tab, setTab] = useState('knowledge')        // knowledge | year | review
  const [mode, setMode] = useState('practice')       // practice | memorize
  const [backendOk, setBackendOk] = useState(true)

  /* ---------- 首页数据 ---------- */
  const [stats, setStats] = useState(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsErr, setStatsErr] = useState(false)

  const [subjects, setSubjects] = useState([])
  const [subjLoading, setSubjLoading] = useState(true)

  /* 按知识点：左选科目 + 右知识点树 */
  const [selSubject, setSelSubject] = useState(urlSubject || '')
  const selSubjectRef = useRef(false)
  const [tree, setTree] = useState(null)
  const [treeLoading, setTreeLoading] = useState(false)
  const [treeErr, setTreeErr] = useState(false)

  /* 真题套卷 / 按年份：改用后端聚合端点（/quiz/papers-index、/quiz/years），
     不再前端拉 500 题猜分组。题目按需懒加载，点击套卷/年份才取该组全部题目。 */
  const [yearSub, setYearSub] = useState('paper')     // paper 套卷索引 | year 按年份
  const [papers, setPapers] = useState([])            // 真题套卷列表
  const [yearsData, setYearsData] = useState([])      // 年份×科目聚合
  const [yearLoading, setYearLoading] = useState(false)
  const [yearErr, setYearErr] = useState(false)
  const [groupQs, setGroupQs] = useState({})          // {key: questions[]} 懒加载缓存
  const [groupLoading, setGroupLoading] = useState({})// {key: bool}
  const [openKey, setOpenKey] = useState(null)        // 当前展开的分组 key

  /* V10：套卷总览的三视图模式（grid 网格 / list 列表 / deck 卡片堆） */
  const [localRecs, setLocalRecs] = useState(loadRecs)
  const [paperView, setPaperView] = useState('grid')       // grid | list | deck

  /* 错题与收藏 */
  const [errorItems, setErrorItems] = useState([])
  const [errLoading, setErrLoading] = useState(false)
  const [errErr, setErrErr] = useState(false)
  const [favs, setFavs] = useState(loadFavs())

  /* ---------- 错题闭环面板（由 QuizSection 合并保留：薄弱点 / 错因 / 待复习队列） ---------- */
  const [weak, setWeak] = useState([])
  const [reasons, setReasons] = useState([])
  const [closedStats, setClosedStats] = useState(null)
  const [due, setDue] = useState([])
  const [panelError, setPanelError] = useState('')

  /* ---------- 练习会话 ---------- */
  const [session, setSession] = useState(null)      // {title, questions:[], mode}
  const [idx, setIdx] = useState(0)
  const [drafts, setDrafts] = useState({})         // 选择题提交前草稿
  const [textDraft, setTextDraft] = useState({})      // 文本题草稿
  const [records, setRecords] = useState({})        // 已判分 {qid:{correct,selected,correctAnswer,analysis}}
  const [selfCheck, setSelfCheck] = useState(null)   // 文本题对照 {qid,myAns,correctAnswer,analysis}
  const [submitting, setSubmitting] = useState(false)
  const startedFromRef = useRef(null)               // 记录会话来源，便于「再练一次」

  /* ---------- 知识点级筛选标识（仅当 URL 带 kp_id 时生效） ---------- */
  const [kpFilter, setKpFilter] = useState(null)    // { id, name } | null
  /* 知识点筛选无题时的空态（避免白屏）：{ name } | null */
  const [kpEmpty, setKpEmpty] = useState(null)

  /* ================= 数据加载 ================= */
  const loadStats = useCallback(async () => {
    setStatsLoading(true); setStatsErr(false)
    try {
      setStats(await quizApi.stats()); setBackendOk(true)
    } catch { setStatsErr(true); setBackendOk(false) }
    finally { setStatsLoading(false) }
  }, [])

  /* 用户配置的考试/支撑科目顺序（goals/subjects），用于科目列表排序与默认选中 */
  const [cfgOrder, setCfgOrder] = useState([])
  const cfgLoadedRef = useRef(false)
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
      /* 默认选中：优先配置科目中第一个有题的，其次配置科目首位，再退有题科目 */
      if (!selSubjectRef.current) {
        const preferred = cfgOrder
          .map((n) => sorted.find((s) => (s.subject || s.name) === n))
          .filter(Boolean)
        const target = preferred.find((s) => (s.question_count || 0) > 0) || preferred[0]
          || sorted.find((s) => (s.question_count || 0) > 0) || sorted[0]
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

  /* 拉取真题套卷索引 + 年份×科目聚合（后端已回填 paper/year/question_no） */
  const loadYears = useCallback(async () => {
    setYearLoading(true); setYearErr(false)
    try {
      const [pi, yr] = await Promise.all([
        quizApi.papersIndex().catch(() => ({ papers: [] })),
        quizApi.years().catch(() => ({ years: [] })),
      ])
      setPapers(pi?.papers || [])
      setYearsData(yr?.years || [])
    } catch { setYearErr(true) }
    finally { setYearLoading(false) }
  }, [])

  /* 懒加载某个分组的题目：套卷按 question_no 顺序，年份按科目筛选 */
  const loadGroup = useCallback(async (key, params) => {
    if (groupQs[key]) { setOpenKey(key); return }
    setGroupLoading((s) => ({ ...s, [key]: true }))
    setOpenKey(key)
    try {
      const d = await quizApi.questions({ ...params, page: 1, page_size: 1000, mode: 'sequential' })
      const qs = (d?.questions || d?.items || []).map(normQ)
      setGroupQs((s) => ({ ...s, [key]: qs }))
    } catch {
      setGroupQs((s) => ({ ...s, [key]: [] }))
    } finally {
      setGroupLoading((s) => ({ ...s, [key]: false }))
    }
  }, [groupQs])

  const loadErrors = useCallback(async () => {
    setErrLoading(true); setErrErr(false)
    try {
      const d = await errorsApi.list({ page: 1, page_size: 200, status: 'active' })
      setErrorItems(d?.items || [])
    } catch { setErrErr(true) }
    finally { setErrLoading(false) }
  }, [])

  /* 错题闭环面板：薄弱点 / 错因 / 艾宾浩斯待复习队列（QuizSection 合并保留） */
  const loadPanel = useCallback(async () => {
    setPanelError('')
    try {
      const [w, rs, st, d] = await Promise.all([
        quizSectionApi.weakPoints({ limit: 15 }),
        quizSectionApi.wrongReasons({ limit: 15 }),
        quizSectionApi.reviewStats(),
        quizSectionApi.reviews({ limit: 30 }),
      ])
      setWeak(w.items || [])
      setReasons(rs.items || [])
      setClosedStats(st)
      setDue(d.items || [])
    } catch (e) { setPanelError(e.message || '加载错题闭环数据失败'); toast(e.message || '加载错题闭环数据失败') }
  }, [])

  /* 待复习队列：提交复习结果（忘了 / 模糊 / 掌握） */
  const reviewItem = async (item, result) => {
    try {
      await quizSectionApi.submitReview({
        item_type: item.item_type || 'error',
        item_id: item.item_id,
        result,
      })
      toast('复习已记录')
      loadPanel()
    } catch (e) { toast(e.message || '复习提交失败') }
  }

  useEffect(() => { loadStats() }, [loadStats])
  useEffect(() => { loadCfgOrder() }, [loadCfgOrder])
  /* 等配置科目顺序就绪后再加载科目列表，保证排序/默认选中正确 */
  useEffect(() => { if (cfgLoadedRef.current || cfgOrder.length) loadSubjects() }, [cfgOrder, loadSubjects])
  /* 科目加载后，若未指定科目则默认选中第一个（驱动右侧知识点树） */
  useEffect(() => {
    if (!selSubject && subjects.length) setSelSubject(subjects[0].subject)
  }, [subjects, selSubject])
  useEffect(() => { loadTree(selSubject) }, [selSubject, loadTree])
  useEffect(() => { if (tab === 'year' && !papers.length && !yearsData.length && !yearLoading) loadYears() }, [tab, papers.length, yearsData.length, yearLoading, loadYears])
  useEffect(() => { if (tab === 'review') loadErrors() }, [tab, loadErrors])

  /* ================= 会话开始 ================= */
  const beginSession = useCallback((title, questions, modeUsed, startIdx = 0) => {
    if (!questions || !questions.length) { toast('当前筛选条件下暂无题目'); return }
    const si = Math.max(0, Math.min(startIdx, questions.length - 1))
    setSession({ title, questions, mode: modeUsed || mode })
    setIdx(si); setDrafts({}); setTextDraft({}); setRecords({}); setSelfCheck(null)
    startedFromRef.current = { title, questions, mode: modeUsed || mode }
    setView('practice')
    window.scrollTo({ top: 0 })
  }, [mode])

  /* V11 智能组卷：调 /api/insight/smart-paper 成卷后直接进入练习 */
  const [smartLoading, setSmartLoading] = useState(null)
  const runSmartPaper = async (m) => {
    setSmartLoading(m)
    try {
      const { insightApi } = await import('../api/client')
      const r = await insightApi.smartPaper({ mode: m, size: 20, subject: selSubject || undefined })
      beginSession(`智能组卷 · ${m === 'weak' ? '薄弱优先' : m === 'error_prone' ? '易错重练' : '随机'}（${r.size}题）`, r.questions, 'practice')
      toast(`已生成 ${r.size} 题：${r.basis?.slice(0, 40) || '就绪'}`)
    } catch (e) {
      toast(e?.message || '智能组卷失败')
    } finally {
      setSmartLoading(null)
    }
  }

  /* V14 场景化 AI 讲题状态（组件顶层，Hooks 规则） */
  const [tutor, setTutor] = useState(null)
  const askTutor = async (qid, angle, myAnswer) => {
    setTutor({ qid, angle, loading: true, content: '', history: [] })
    try {
      const { request } = await import('../api/client')
      const r = await request('/ai/tutoring/explain', {
        method: 'POST',
        body: { question_id: qid, angle, my_answer: myAnswer || undefined },
      })
      setTutor({ qid, angle, loading: false, content: r.content, provider: r.provider,
                 similar: r.similar, history: [
                   { role: 'user', content: angle },
                   { role: 'assistant', content: r.content }] })
    } catch (e) {
      setTutor({ qid, angle, loading: false, content: e?.message || '讲题失败', history: [] })
    }
  }
  const askFollowup = async (message) => {
    if (!tutor?.qid || !message.trim()) return
    const hist = tutor.history || []
    setTutor(t => ({ ...t, loading: true }))
    try {
      const { request } = await import('../api/client')
      const r = await request('/ai/tutoring/followup', {
        method: 'POST',
        body: { question_id: tutor.qid, message, history: hist.slice(-6) },
      })
      setTutor(t => ({ ...t, loading: false, content: r.content,
                       history: [...hist, { role: 'user', content: message },
                                { role: 'assistant', content: r.content }] }))
    } catch (e) {
      setTutor(t => ({ ...t, loading: false, content: e?.message || '追问失败' }))
    }
  }

  /* 返回首页时刷新本地作答记录（套卷网格颜色/做过次数随之更新） */
  useEffect(() => {
    if (view === 'home') setLocalRecs(loadRecs())
  }, [view])

  /* 按筛选条件向后端拉题并开始（知识点精确 / 知识点章节 / 整科）。
     kp_id 为可选：传入时按知识点级精确筛选（后端 /api/quiz/questions 已支持）。 */
  const startWithFilter = useCallback(async ({ subject, chapter, question_type, kp_id, kp_name, title }) => {
    setSubmitting(true)
    try {
      const d = await quizApi.questions({
        subject: subject || undefined,
        chapter: chapter || undefined,
        question_type: question_type || undefined,
        kp_id: kp_id || undefined,
        page: 1, page_size: 100
      })
      const qs = (d?.questions || d?.items || []).map(normQ)
      setBackendOk(true)
      /* 记录本次是否为知识点级筛选，供界面标识与空态判断使用 */
      const kp = kp_id ? { id: String(kp_id), name: kp_name || `#${kp_id}` } : null
      setKpFilter(kp)
      /* 知识点级筛选命中 0 题：给出显式 Empty 兜底，不进入空会话（避免白屏） */
      if (kp && !qs.length) {
        setKpEmpty({ name: kp.name })
        setSubmitting(false)
        return
      }
      setKpEmpty(null)
      beginSession(title, qs, mode)
    } catch {
      setBackendOk(false)
      const kp = kp_id ? { id: String(kp_id), name: kp_name || `#${kp_id}` } : null
      setKpFilter(kp)
      const qs = LOCAL_FALLBACK.filter((x) => !subject || x.subject === subject)
      beginSession(title, qs.length ? qs : LOCAL_FALLBACK, mode)
    } finally { setSubmitting(false) }
  }, [beginSession, mode])

  /* QuizSection 深链：?subject=&chapter= 直达该章练习；
     ?kp_id=&kp_name= 直达该知识点精确刷题。 */
  useEffect(() => {
    if ((urlChapter || urlKpId) && view === 'home') {
      const title = urlKpName
        ? `知识点 · ${urlKpName}`
        : `${urlSubject || ''} · ${urlChapter || ''}`.trim()
      startWithFilter({
        subject: urlSubject,
        chapter: urlChapter,
        question_type: urlType,
        kp_id: urlKpId,
        kp_name: urlKpName,
        title
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /* ================= 作答与判分 ================= */
  /* 多选仍需逐个勾选后判分；单选/判断在 toggleDraft 里点选即判。 */
  const toggleDraft = (qid, i) => {
    const q = session.questions[idx]
    if (records[qid]) return
    if (isMultiQ(q)) {
      setDrafts((prev) => {
        const cur = Array.isArray(prev[qid]) ? prev[qid] : []
        const next = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort((a, b) => a - b)
        return { ...prev, [qid]: next }
      })
      return
    }
    // 单选/判断：记录草稿并立即判分，点选即给反馈，不等提交
    setDrafts((prev) => ({ ...prev, [qid]: i }))
    gradeChoice(q, i)
  }

  /* 选择题判分。sel 为下标或下标数组（多选）。 */
  const gradeChoice = async (q, sel) => {
    if (records[q.id] || selfCheck || submitting) return
    const myAns = Array.isArray(sel) ? sel.map(letterOf).join('') : letterOf(sel)
    let correct = false, correctAnswer = q.answer, analysis = q.analysis
    if (backendOk && !q.id.startsWith('l')) {
      setSubmitting(true)
      try {
        const r = await quizApi.submit({ question_id: Number(q.id), my_answer: myAns })
        correct = !!r.correct
        correctAnswer = r.correct_answer ?? correctAnswer
        analysis = r.analysis ?? analysis
      } catch {
        correct = String(myAns).toUpperCase() === String(q.answer).toUpperCase()
      } finally { setSubmitting(false) }
    } else {
      correct = String(myAns).toUpperCase() === String(q.answer).toUpperCase()
    }
    applyGrade(q, correct, myAns, correctAnswer, analysis)
  }

  const applyGrade = (q, correct, selected, correctAnswer, analysis) => {
    setRecords((prev) => ({ ...prev, [q.id]: { correct, selected, correctAnswer, analysis } }))
    pushRec(q.id, correct)   // V10 本地作答累计（做过次数 + 最近对错）
    if (correct) toast('回答正确')
    else { addWrong(q.id); toast('答错已加入错题本') }
  }

  const doSubmit = async () => {
    if (!session) return
    const q = session.questions[idx]
    if (records[q.id] || selfCheck) return
    if (submitting) return

    /* ---- 多选题：勾选后提交 ---- */
    if (isChoiceQ(q) && isMultiQ(q)) {
      const sel = drafts[q.id]
      const empty = sel == null || (Array.isArray(sel) && !sel.length)
      if (empty) { toast('请至少选择一个选项'); return }
      await gradeChoice(q, sel)
      return
    }

    /* ---- 文本题（填空/简答/计算/作图）：输入 → 对照 → 自评 ---- */
    const txt = (textDraft[q.id] || '').trim()
    if (!txt) { toast('请先输入你的作答，再点「对照答案」'); return }
    let correctAnswer = q.answer, analysis = q.analysis
    if (backendOk && !q.id.startsWith('l')) {
      setSubmitting(true)
      try {
        const r = await quizApi.submit({ question_id: Number(q.id), my_answer: txt })
        correctAnswer = r.correct_answer ?? correctAnswer
        analysis = r.analysis ?? analysis
      } catch { /* 自评模式，后端不可用不影响 */ } finally { setSubmitting(false) }
    }
    setSelfCheck({ qid: q.id, myAns: txt, correctAnswer, analysis })
  }

  /* 文本题自评落分 */
  const selfGrade = (correct) => {
    if (!selfCheck) return
    const q = session.questions.find((x) => x.id === selfCheck.qid)
    if (!q) return
    applyGrade(q, correct, selfCheck.myAns, selfCheck.correctAnswer, selfCheck.analysis)
    setSelfCheck(null)
  }

  const go = useCallback((n) => {
    if (!session) return
    if (n < 0 || n >= session.questions.length) return
    setIdx(n); setSelfCheck(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [session])

  const finishSession = () => { setView('result'); window.scrollTo({ top: 0 }) }
  const goHome = () => { setView('home'); setSession(null); window.scrollTo({ top: 0 }) }

  /* 收藏切换 */
  const toggleFav = (q) => {
    setFavs((prev) => {
      const next = { ...prev }
      if (next[q.id]) delete next[q.id]
      else next[q.id] = { content: q.content, subject: q.subject, chapter: q.chapter, type: q.question_type }
      saveFavs(next)
      return next
    })
  }

  /* 键盘快捷键：A–F 选择 · Enter 提交/下一题 · ← → 切换 */
  useEffect(() => {
    const onKey = (e) => {
      if (view !== 'practice' || !session) return
      const t = e.target
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      const q = session.questions[idx]
      if (!q) return
      if (isChoiceQ(q) && !records[q.id]) {
        const k = e.key.toUpperCase()
        const i = LETTERS.indexOf(k)
        if (i >= 0 && i < q.options.length) { toggleDraft(q.id, i); return }
      }
      if (e.key === 'Enter') {
        // 残缺选择题（无选项不可作答）按 Enter 直接跳下一题
        if (isChoiceWithoutOptions(q)) {
          if (idx + 1 < session.questions.length) go(idx + 1)
          else finishSession()
        } else if (!records[q.id] && !selfCheck) doSubmit()
        else if (idx + 1 < session.questions.length) go(idx + 1)
        else finishSession()
      } else if (e.key === 'ArrowLeft') go(idx - 1)
      else if (e.key === 'ArrowRight') go(idx + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  /* ================= 渲染：首页 ================= */
  const renderHome = () => {
    return (
      <div className="container stack">
        {/* Hero + 统计带 */}
        <section className="qh-hero">
          <div className="qh-hero-top">
            <div>
              <div className="qh-hero-eyebrow">QUIZ CENTER · 刷题中心</div>
              <h1 className="qh-hero-title">历年真题，按知识点、按年份精准刷</h1>
              <p className="qh-hero-desc">
                覆盖考纲知识点与历年真题，点选即判、即时显示答案与解析；答错自动收入错题本，
                薄弱点一目了然。支持练习 / 背题双模式与键盘快捷作答。
              </p>
            </div>
            <dl className="qh-hero-stats">
              <div className="qh-hstat">
                <dt>题库总量</dt>
                <dd>{statsLoading ? '…' : <CountUp value={stats?.total_questions || 0} />}<small>题</small></dd>
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
            <span>数据来源：/api/quiz/stats</span>
            {backendOk
              ? <span className="live-dot">· 已连接真实题库</span>
              : <span className="offline-dot">· 统计加载失败，显示为 0，可重试</span>}
          </div>
        </section>

        {/* 知识点级筛选标识：仅在 URL 带 kp_id 时出现，让用户明确当前按知识点刷题 */}
        {kpFilter && (
          <div className="qkp-filter card">
            <span className="qkp-filter-tag">🔖 当前筛选：知识点 {kpFilter.name}</span>
            <button className="btn mini ghost" onClick={() => { setKpFilter(null); setKpEmpty(null); goHome() }}>
              清除筛选
            </button>
          </div>
        )}

        {/* 知识点筛选命中 0 题：显式空态兜底，不白屏 */}
        {kpEmpty && (
          <Empty icon="🔍" title={`知识点「${kpEmpty.name}」暂无关联题目`}
            desc="该知识点尚未关联题目，可先返回知识点全景页选择其它知识点，或按科目/章节刷题。"
            action={<button className="btn primary" onClick={() => { setKpEmpty(null); setKpFilter(null); goHome() }}>
              返回题库首页
            </button>} />
        )}

        {statsErr && (
          <div className="qerr card">
            <div className="qerr-t">统计数据加载失败</div>
            <button className="btn ghost" onClick={loadStats}>重试</button>
          </div>
        )}

        {/* 三入口 Tab + 练习/背题切换 */}
        <div className="qbar">
          <div className="qtab-bar" role="tablist">
            {[
              { id: 'knowledge', label: '按知识点' },
              { id: 'year', label: '按年份' },
              { id: 'review', label: '错题与收藏' }
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

        {tab === 'knowledge' && (
          <>
            {/* V11 智能组卷（薄弱优先/易错重练/随机）：数据已齐，一键成卷 */}
            <div className="qsmart" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
              <strong style={{ fontSize: 13, color: 'var(--ink-2)', alignSelf: 'center' }}>⚡ 智能组卷：</strong>
              {[
                { m: 'weak', label: '薄弱优先', tip: '按薄弱考点自动抽题' },
                { m: 'error_prone', label: '易错重练', tip: '从你的错题规律抽同类题' },
                { m: 'random', label: '随机', tip: '随机抽题练手感' },
              ].map(x => (
                <button key={x.m} className="qtab-btn" disabled={smartLoading} title={x.tip}
                  onClick={() => runSmartPaper(x.m)}>
                  {smartLoading === x.m ? '组卷中…' : x.label}
                </button>
              ))}
            </div>
            {renderKnowledge()}
          </>
        )}
        {tab === 'year' && renderYear()}
        {tab === 'review' && renderReview()}
        {tab === 'review' && renderClosedLoop()}
      </div>
    )
  }

  /* ---------- 按知识点 ---------- */
  const renderKnowledge = () => {
    if (subjLoading) return <div className="qloading card">正在加载科目列表…</div>
    if (!subjects.length) {
      return <Empty icon="📚" title="暂无科目" desc="科目从后端动态加载，请稍后重试"
        action={<button className="btn primary" onClick={loadSubjects}>重试</button>} />
    }
    /* 默认选中第一个有题的科目（避免落在 0 题科目上，点「开始练习」无反应） */
    const active = subjects.find((s) => s.subject === selSubject)
      || subjects.find((s) => (s.question_count || 0) > 0)
      || subjects[0]
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
                <span className="qknow-subj-meta">
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
                startWithFilter({ subject: active.subject, title: `${active.subject} · 整科练习` })
              }}>
              整科练习（{active?.question_count || 0}）
            </button>
          </div>

          {treeLoading && <div className="qloading card">正在加载知识点树…</div>}
          {treeErr && (
            <div className="qerr card">
              <div className="qerr-t">知识点树加载失败</div>
              <button className="btn ghost" onClick={() => loadTree(active?.subject)}>重试</button>
            </div>
          )}
          {!treeLoading && !treeErr && !chapters.length && (
            <Empty icon="🗂️" title="该科目暂无章节" desc="可先在科目管理中维护考纲章节" />
          )}

          {!treeLoading && !treeErr && !!chapters.length && (
            <div className="qknow-list">
              {chapters.map((c, i) => {
                const mastery = Math.round((c.avg_mastery || 0) * 100)
                return (
                  <button key={c.title} className="qknow-row"
                    onClick={() => startWithFilter({ subject: active.subject, chapter: c.title, title: `${active.subject} · ${c.title}` })}>
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

  /* ---------- 真题套卷 / 按年份（对标 gitgraduate 题库索引；数据来自后端聚合，不前端猜） ---------- */
  const renderGroup = (key, title, subtitle, chips, params, count, numbered) => {
    const list = groupQs[key]
    const loading = groupLoading[key]
    const open = openKey === key
    const done = list ? list.filter((q) => localRecs[q.id]).length : 0
    const pct = list && list.length ? Math.round((done / list.length) * 100) : 0
    const noOf = (q, i) => (numbered ? (q.question_no || i + 1) : (i + 1))
    return (
      <section key={key} className="qpaper">
        <div className="qpaper-head">
          <span className="qpaper-year">{subtitle}</span>
          <span className="qpaper-title" title={title}>{title}</span>
          {chips}
          <span className="qpaper-meta">{count} 题{list ? ` · 已做 ${done}/${list.length} · ${pct}%` : ''}</span>
          {list && list.length > 0 && <span className="qpaper-bar progress thin"><i style={{ width: `${pct}%` }} /></span>}
          <button className="btn mini primary" onClick={() => loadGroup(key, params)}>
            {list ? '开始练习' : '载入题号'}
          </button>
        </div>

        {loading && <div className="qloading card">正在载入题目…</div>}

        {open && list && list.length > 0 && (
          <div className="qpaper-body">
            {paperView === 'grid' ? (
              <div className="qcell-grid">
                {list.map((q, i) => {
                  const r = localRecs[q.id]
                  let cls = 'qcell'
                  if (r) cls += r.correct ? ' ok' : ' bad'
                  return (
                    <button key={q.id} className={cls}
                      title={`第 ${noOf(q, i)} 题${r ? ` · 做过 ${r.times} 次` : ' · 未做'}`}
                      onClick={() => beginSession(title, list, mode, i)}>
                      {noOf(q, i)}
                      {r?.times > 0 && <span className="t">{r.times}</span>}
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="qpaper-rows">
                {list.map((q, i) => {
                  const r = localRecs[q.id]
                  return (
                    <div key={q.id} className="qp-row" onClick={() => beginSession(title, list, mode, i)}>
                      <span className="qp-no">{noOf(q, i)}</span>
                      <span className={`qp-state ${r ? (r.correct ? 'ok' : 'bad') : ''}`} />
                      <span className="qp-txt">{q.content}</span>
                      <span className="qpaper-meta">{r ? `做过 ${r.times} 次` : '未做'}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {open && list && list.length === 0 && !loading && (
          <Empty icon="📄" title="当前筛选条件下暂无题目" desc="换个套卷或年份试试" />
        )}
      </section>
    )
  }

  const renderYear = () => {
    if (yearLoading) return <div className="qloading card">正在载入真题套卷与年份索引…</div>
    if (yearErr) {
      return <div className="qerr card">
        <div className="qerr-t">索引加载失败</div>
        <button className="btn ghost" onClick={loadYears}>重试</button>
      </div>
    }
    const yearTotal = yearsData.reduce((a, y) => a + (y.total || 0), 0)
    return (
      <div>
        <div className="qpart-wrap">
          <div className="qtab-bar" role="tablist">
            {[
              { id: 'paper', label: `真题套卷 (${papers.length})` },
              { id: 'year', label: `按年份 (${yearsData.length})` }
            ].map((t) => (
              <button key={t.id} role="tab" aria-selected={yearSub === t.id}
                className={`qtab-btn ${yearSub === t.id ? 'active' : ''}`}
                onClick={() => setYearSub(t.id)}>{t.label}</button>
            ))}
          </div>
          <div className="qmode-toggle">
            {[{ id: 'grid', label: '题号网格' }, { id: 'list', label: '列表' }].map((v) => (
              <button key={v.id} className={`qmode-btn ${paperView === v.id ? 'active' : ''}`}
                onClick={() => setPaperView(v.id)}>{v.label}</button>
            ))}
          </div>
        </div>

        {yearSub === 'paper' && (
          papers.length
            ? papers.map((p) => renderGroup(
                `paper::${p.paper}`, p.paper, p.year_label || '套卷',
                Object.entries(p.subjects || {}).slice(0, 3).map(([s, c]) => <span key={s} className="chip">{s} {c}</span>),
                { paper: p.paper }, p.count, true))
            : <Empty icon="📚" title="暂无真题套卷" desc="题库中还没有可归卷的真题" />
        )}

        {yearSub === 'year' && (
          yearsData.length
            ? yearsData.map((y) => renderGroup(
                `year::${y.year}`, `${y.year} 年真题`, String(y.year),
                Object.entries(y.subjects || {}).slice(0, 4).map(([s, c]) => <span key={s} className="chip">{s} {c}</span>),
                { year: y.year }, y.total, false))
            : <Empty icon="📅" title="暂无按年份数据" desc="只有能可靠解析年份的真题才会出现在这里" />
        )}

        <p className="qnote">
          口径说明（诚实）：套卷名与年份由后端从真题文档名回填（paper / year 列），题号 question_no 为套卷内录入顺序号（非原卷题号）；
          「按年份」仅覆盖能无歧义解析年份的真题子集（共 {yearTotal} 题），不伪造年份。
          题格对错与「做过次数」为本地单机记录（localStorage）。点击「载入题号」按需拉取该组全部题目。
        </p>
      </div>
    )
  }

  /* ---------- 错题与收藏 ---------- */
  const renderReview = () => {
    const errQuestions = errorItems.map((e) => ({
      id: String(e.question_id || e.id),
      content: e.content || '',
      options: [], answer: e.correct_answer || '', analysis: e.analysis || '',
      subject: e.subject || '', chapter: '错题', difficulty: 1, question_type: ''
    }))
    const favEntries = Object.entries(favs)
    const favQuestions = favEntries.map(([id, f]) => ({
      id, content: f.content || '', options: [], answer: '', analysis: '',
      subject: f.subject || '', chapter: f.chapter || '', difficulty: 1, question_type: f.type || ''
    }))
    return (
      <div className="qreview-grid">
        <section className="qreview-col">
          <div className="qreview-head">
            <div className="qreview-head-t">❌ 错题本 <span className="qreview-head-c">{errorItems.length} 题</span></div>
            <button className="btn mini primary" disabled={!errQuestions.length}
              onClick={() => beginSession('错题重练', errQuestions, mode)}>全部重练</button>
          </div>
          {errLoading && <div className="qloading">正在加载错题…</div>}
          {errErr && <div className="qerr"><div className="qerr-t">错题加载失败</div>
            <button className="btn ghost" onClick={loadErrors}>重试</button></div>}
          {!errLoading && !errErr && !errQuestions.length && (
            <Empty icon="🎉" title="还没有错题" desc="继续保持，答错的题目会自动归集到这里" />
          )}
          {!errLoading && errQuestions.map((q) => (
            <div key={`${q.id}-${q.content.slice(0, 8)}`} className="qreview-item">
              <div className="qreview-item-meta">{q.subject}{q.chapter ? ` · ${q.chapter}` : ''}</div>
              <div className="qreview-item-txt">{q.content}</div>
            </div>
          ))}
        </section>

        <section className="qreview-col">
          <div className="qreview-head">
            <div className="qreview-head-t">⭐ 我的收藏 <span className="qreview-head-c">{favQuestions.length} 题</span></div>
            <button className="btn mini primary" disabled={!favQuestions.length}
              onClick={() => beginSession('收藏题目', favQuestions, mode)}>全部重练</button>
          </div>
          {!favQuestions.length && (
            <Empty icon="⭐" title="还没有收藏" desc="作答时点击右上角星标即可收藏题目" />
          )}
          {favQuestions.map((q) => (
            <div key={q.id} className="qreview-item">
              <div className="qreview-item-meta">{q.subject}{q.chapter ? ` · ${q.chapter}` : ''}</div>
              <div className="qreview-item-txt">{q.content}</div>
            </div>
          ))}
          <p className="qnote flush">
            口径说明：后端暂无 favorites 接口，收藏为本地持久化（localStorage），随浏览器保留。
          </p>
        </section>
      </div>
    )
  }

  /* ---------- 错题闭环面板（QuizSection 合并保留：薄弱点 / 错因 / 待复习队列） ---------- */
  const renderClosedLoop = () => {
    return (
      <div className="stack">
        {panelError ? (
          <div className="card">
            <div className="empty-state">
              <div className="empty-state-title">错题闭环数据加载失败</div>
              <div className="empty-state-desc">{panelError}</div>
              <div className="empty-state-action">
                <button className="btn ghost" onClick={loadPanel}>重试</button>
              </div>
            </div>
          </div>
        ) : (
          <div className="row spread">
            <div className="card" style={{ flex: 1 }}>
              <div className="card-title">薄弱点排行</div>
              {weak.length === 0 ? <Empty title="暂无薄弱点数据" /> : (
                <div className="list">
                  {weak.map((w, i) => (
                    <div key={w.key || i} className="list-row spread">
                      <div>
                        <div className="lr-title">{w.chapter || w.subject}{w.knowledge_point ? ` · ${w.knowledge_point}` : ''}</div>
                        <div className="lr-main card-sub">{w.subject}</div>
                      </div>
                      <div className="badge danger">{w.error_count} 错</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="card" style={{ flex: 1 }}>
              <div className="card-title">错因分布</div>
              {reasons.length === 0 ? <Empty title="暂无错因数据" /> : (
                <div className="list">
                  {reasons.map((r, i) => (
                    <div key={i} className="list-row spread">
                      <div className="lr-title">{r.reason}</div>
                      <div className="badge amber">{r.count}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        <div className="card">
          <div className="card-title spread">
            <span>待复习队列（艾宾浩斯）</span>
            <span className="card-sub">今日已复习 {closedStats ? closedStats.today_reviews : '-'} 次 · 累计 {closedStats ? closedStats.total_reviews : '-'} 次</span>
          </div>
          {due.length === 0 ? <Empty title="暂无待复习项" /> : (
            <div className="list">
              {due.map((item) => (
                <div key={item.id || item.item_id} className="list-row spread">
                  <div style={{ flex: 1 }}>
                    <div className="lr-title">{item.title || item.content || `${item.item_type}#${item.item_id}`}</div>
                    <div className="lr-main card-sub">{item.subject || ''} · {item.chapter || ''} · 掌握度 {item.mastery || 0}</div>
                  </div>
                  <div className="row">
                    <button className="btn sm ghost" onClick={() => reviewItem(item, 'forgotten')}>忘了</button>
                    <button className="btn sm ghost" onClick={() => reviewItem(item, 'fuzzy')}>模糊</button>
                    <button className="btn sm primary" onClick={() => reviewItem(item, 'mastered')}>掌握</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  /* ================= 渲染：练习视图 ================= */
  const renderPractice = () => {
    if (!session) return null
    const q = session.questions[idx]
    const total = session.questions.length
    const rec = records[q.id]
    const memorize = session.mode === 'memorize'
    const revealed = memorize || !!rec
    const draft = drafts[q.id]
    const answeredCount = Object.keys(records).length
    // total=0（这道题集没载到题）时进度必须是 0，不能让 NaN 流进 style.width
    const pct = total > 0 ? Math.round(((memorize ? idx + 1 : answeredCount) / total) * 100) : 0
    const favOn = !!favs[q.id]

    return (
      <div className="container">
        <div className="qprac-layout">
          <article className="qprac-article">
            <div className="qprac-meta">
              <button className="btn mini ghost" onClick={goHome}>‹ 返回题库</button>
              <span>{session.title}</span>
              {/* 知识点级筛选标识：明确告知用户当前按知识点精确出题 */}
              {kpFilter && <span className="chip kp" title={`知识点 ID ${kpFilter.id}`}>🔖 知识点 · {kpFilter.name}</span>}
              <span className="chip">{memorize ? '背题模式' : '练习模式'}</span>
              <span className="chip">{TYPE_LABELS[q.question_type] || q.question_type || '题目'}</span>
              {q.subject && <span className="chip">{q.subject}</span>}
              {q.chapter && <span className="chip">{q.chapter}</span>}
              <button className={`qstar ${favOn ? 'on' : ''}`} onClick={() => toggleFav(q)}>
                {favOn ? '★ 已收藏' : '☆ 收藏'}
              </button>
            </div>

            <div className="qprac-body">
              <div className="qprac-progress">
                <span className="progress thin"><i style={{ width: `${pct}%` }} /></span>
                <span className="qprac-progress-num">{memorize ? `${idx + 1}` : `${answeredCount}`}/{total}</span>
              </div>

              <p className="qprac-stem">
                <span className="no">{idx + 1}.</span>{q.content}
              </p>

              {/* 依赖原书插图的题目给出提示，避免用户对着「见下图」困惑 */}
              {dependsOnFigure(q) && (
                <p className="qfig-note">本题依赖原书插图，答案见原书。</p>
              )}

              {/* 选择题：点选即判 */}
              {isChoiceQ(q) && (
                <div className="qopt-list">
                  {q.options.map((o, i) => {
                    const isAns = isCorrectOption(i, rec?.correctAnswer ?? q.answer)
                    const picked = Array.isArray(draft) ? draft.includes(i) : draft === i
                    const wasBad = revealed && !isAns && (
                      Array.isArray(rec?.selected)
                        ? rec.selected.includes(letterOf(i))
                        : String(rec?.selected || '').toUpperCase().includes(letterOf(i))
                    )
                    let cls = 'qopt'
                    if (!revealed && picked) cls += ' sel'
                    if (revealed) {
                      if (isAns) cls += ' ok'
                      else if (wasBad) cls += ' bad'
                    }
                    return (
                      <button key={i} className={cls} disabled={revealed} onClick={() => toggleDraft(q.id, i)}>
                        <span className="qopt-letter">
                          {revealed && isAns ? '✓' : revealed && wasBad ? '✗' : letterOf(i)}
                        </span>
                        <span className="qopt-body">{stripOptLabel(o)}</span>
                      </button>
                    )
                  })}
                </div>
              )}

              {/* 残缺选择题：答案是字母但 options 为空。只读展示，禁止作答 */}
              {!isChoiceQ(q) && isChoiceWithoutOptions(q) && (
                <div className="qopt-none">
                  <span className="qopt-none-t">本题无选项，答案：{q.answer || '—'}</span>
                  <span className="qopt-none-d">题库缺少该题选项内容，仅供记忆参考，不可作答。</span>
                </div>
              )}

              {/* 文本题：输入 + 对照自评 */}
              {isTextQuestion(q) && (
                <div className="qtext-area">
                  <textarea className="qtext-input" placeholder="在此输入你的作答（填空 / 简答 / 计算过程 / 作图描述）…"
                    value={textDraft[q.id] || ''} disabled={revealed}
                    onChange={(e) => setTextDraft((p) => ({ ...p, [q.id]: e.target.value }))} />
                  {!revealed && !selfCheck && (
                    <div className="qtext-row">
                      <button className="btn primary" disabled={submitting} onClick={doSubmit}>对照答案</button>
                      <span className="qkey-hint">提交后展开参考答案与解析，再由你自评对错</span>
                    </div>
                  )}
                </div>
              )}

              {/* 揭示区：判分结果 / 背题答案 / 文本题对照 */}
              {(revealed || selfCheck) && (
                <div className={`qreveal ${rec ? (rec.correct ? 'ok' : 'bad') : (selfCheck ? 'plain' : 'plain')}`}>
                  <div className="qreveal-row">
                    <span>正确答案：<span className="ans">{rec?.correctAnswer ?? q.answer}</span></span>
                    {rec && <span>{rec.correct ? '· 回答正确 ✓' : `· 你的答案 ${rec.selected || ''}，回答错误 ✗`}</span>}
                    {selfCheck && <span>· 你的作答：{selfCheck.myAns}</span>}
                  </div>
                  {(rec?.analysis || q.analysis || selfCheck?.analysis) && (
                    <div className="qreveal-row"><span>解析：{rec?.analysis || selfCheck?.analysis || q.analysis}</span></div>
                  )}
                  {selfCheck && (
                    <div className="qtext-row">
                      <button className="btn primary" onClick={() => selfGrade(true)}>✅ 我答对了</button>
                      <button className="btn danger" onClick={() => selfGrade(false)}>❌ 我答错了</button>
                    </div>
                  )}
                </div>
              )}

              {/* 未作答提示：单选/判断点选即判；多选仍需提交 */}
              {!revealed && !selfCheck && isChoiceQ(q) && isMultiQ(q) && (
                <p className="qkey-hint">勾选所有正确选项后，点「提交答案」判分。</p>
              )}
            </div>

            <div className="qprac-foot">
              <button className="btn ghost" onClick={() => go(idx - 1)} disabled={idx === 0}>‹ 上一题</button>
              <span className="qkey-hint">快捷键：A–F 选择 · Enter 提交/下一题 · ← → 切换</span>
              <div className="qprac-foot-btns">
                <button className="btn ghost" onClick={() => navigate('/assistant')}>🤖 问 AI</button>
                {!revealed && !selfCheck && isChoiceQ(q) && isMultiQ(q) && (
                  <button className="btn primary" disabled={submitting} onClick={doSubmit}>提交答案</button>
                )}
                {/* 残缺选择题不可作答，允许直接跳到下一题 */}
                {isChoiceWithoutOptions(q) && (
                  idx + 1 < total ? (
                    <button className="btn primary" onClick={() => go(idx + 1)}>下一题 ›</button>
                  ) : (
                    <button className="btn primary" onClick={finishSession}>{memorize ? '完成背题' : '交卷并查看报告'}</button>
                  )
                )}
                {(revealed || selfCheck) && idx + 1 < total && (
                  <button className="btn primary" onClick={() => go(idx + 1)}>下一题 ›</button>
                )}
                {(revealed || selfCheck) && idx + 1 >= total && (
                  <button className="btn primary" onClick={finishSession}>{memorize ? '完成背题' : '交卷并查看报告'}</button>
                )}
              </div>
            </div>
          </article>

          {/* 右侧答题卡 */}
          <aside className="qsheet">
            <div className="qsheet-t">答题卡</div>
            <div className="qsheet-grid">
              {session.questions.map((qq, i) => {
                const r = records[qq.id]
                const skipped = isChoiceWithoutOptions(qq)
                let cls = 'qsheet-cell'
                if (skipped) cls += ' skip'
                else if (r) cls += r.correct ? ' ok' : ' bad'
                else if (drafts[qq.id] != null || textDraft[qq.id]) cls += ' draft'
                if (i === idx) cls += ' cur'
                return (
                  <button key={qq.id} className={cls} onClick={() => go(i)}
                    aria-label={`第 ${i + 1} 题${skipped ? '，无选项不可作答' : r ? (r.correct ? '，正确' : '，错误') : ''}`}>
                    {i + 1}
                  </button>
                )
              })}
            </div>
            <ul className="qsheet-legend">
              <li><span className="qsheet-dot ok" />正确</li>
              <li><span className="qsheet-dot bad" />错误</li>
              <li><span className="qsheet-dot todo" />未做</li>
              <li><span className="qsheet-dot skip" />无选项</li>
            </ul>
            <button className="btn ghost qsheet-finish" onClick={finishSession}>
              {memorize ? '结束背题' : '交卷并查看报告'}
            </button>
          </aside>
        </div>
      </div>
    )
  }

  /* ================= 渲染：结果报告 ================= */
  const renderResult = () => {
    if (!session) return null
    const list = session.questions
    const answered = list.filter((q) => records[q.id])
    const correct = answered.filter((q) => records[q.id].correct)
    const wrong = answered.filter((q) => !records[q.id].correct)
    const accuracy = answered.length ? Math.round((correct.length / answered.length) * 100) : 0

    const byChapter = new Map()
    answered.forEach((q) => {
      const k = q.chapter || q.subject || '未分组'
      const e = byChapter.get(k) || { total: 0, correct: 0 }
      e.total += 1
      if (records[q.id].correct) e.correct += 1
      byChapter.set(k, e)
    })

    const redoWrong = () => {
      if (!wrong.length) { toast('本轮没有错题'); return }
      const src = startedFromRef.current
      beginSession(`${session.title} · 错题重练`, wrong, src?.mode)
    }
    const redoAll = () => {
      const src = startedFromRef.current
      beginSession(src?.title || session.title, src?.questions || list, src?.mode)
    }

    /* V14 场景化 AI 讲题：状态在组件顶层（Hooks 规则），此处仅用 */
    const askTutor = async (qid, angle, myAnswer) => {
      setTutor({ qid, angle, loading: true, content: '', history: [] })
      try {
        const { request } = await import('../api/client')
        const r = await request('/ai/tutoring/explain', {
          method: 'POST',
          body: { question_id: qid, angle, my_answer: myAnswer || undefined },
        })
        setTutor({ qid, angle, loading: false, content: r.content, provider: r.provider,
                   similar: r.similar, history: [{ role: 'user', content: angle }, { role: 'assistant', content: r.content }] })
      } catch (e) {
        setTutor({ qid, angle, loading: false, content: e?.message || '讲题失败', history: [] })
      }
    }
    const askFollowup = async (message) => {
      if (!tutor?.qid || !message.trim()) return
      const hist = tutor.history || []
      setTutor({ ...tutor, loading: true })
      try {
        const { request } = await import('../api/client')
        const r = await request('/ai/tutoring/followup', {
          method: 'POST',
          body: { question_id: tutor.qid, message, history: hist.slice(-6) },
        })
        setTutor(t => ({ ...t, loading: false, content: r.content,
                         history: [...hist, { role: 'user', content: message }, { role: 'assistant', content: r.content }] }))
      } catch (e) {
        setTutor({ ...tutor, loading: false, content: e?.message || '追问失败' })
      }
    }

    return (
      <div className="container">
        <div className="qresult">
          <section className="qresult-hero">
            <div className="qresult-sub">{session.title} · 练习报告</div>
            <div className="qresult-acc">{accuracy}<small>%</small></div>
            <div className="qresult-sub">正确率</div>
            <dl className="qresult-stats">
              <div className="qresult-stat"><dt>题目总数</dt><dd>{list.length}</dd></div>
              <div className="qresult-stat"><dt>已作答</dt><dd>{answered.length}</dd></div>
              <div className="qresult-stat ok"><dt>答对</dt><dd>{correct.length}</dd></div>
              <div className="qresult-stat bad"><dt>答错</dt><dd>{wrong.length}</dd></div>
            </dl>
          </section>

          {byChapter.size > 0 && (
            <section className="qresult-panel">
              <div className="qresult-panel-t">知识点 / 章节掌握情况</div>
              {Array.from(byChapter.entries()).map(([name, v]) => (
                <div key={name} className="qresult-row">
                  <span className="qrow-name">{name}</span>
                  <span className="progress thin"><i style={{ width: `${v.total ? Math.round((v.correct / v.total) * 100) : 0}%` }} /></span>
                  <span className="qrow-num">{v.correct}/{v.total}</span>
                </div>
              ))}
            </section>
          )}

          <div className="qresult-actions">
            {wrong.length > 0 && <button className="btn primary" onClick={redoWrong}>重练错题（{wrong.length}）</button>}
            <button className="btn ghost" onClick={redoAll}>再练一次</button>
            <button className="btn ghost" onClick={goHome}>返回题库</button>
          </div>

          {/* V14 场景化 AI 讲题：错题逐条三问 + 追问弹层 */}
          {wrong.length > 0 && (
            <section className="qresult-panel">
              <div className="qresult-panel-t">🤖 AI 讲题（点错题即问，自动带题目上下文）</div>
              {wrong.slice(0, 10).map((q) => (
                <div key={q.id} className="qresult-row" style={{ gap: 8, alignItems: 'center' }}>
                  <span className="qrow-name" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {(q.content || '').slice(0, 40)}
                  </span>
                  {[['why_wrong', '为什么我错'], ['solution', '解题思路'], ['method', '举一反三']].map(([a, label]) => (
                    <button key={a} className="btn sm ghost" disabled={tutor?.loading}
                      onClick={() => askTutor(q.id, a, records[q.id]?.selected)}>
                      {tutor?.qid === q.id && tutor?.loading ? '…' : label}
                    </button>
                  ))}
                </div>
              ))}
              {tutor?.content && (
                <div className="qtutor-panel" style={{ marginTop: 12, padding: '14px 16px', borderRadius: 12, background: 'var(--surface-2, rgba(0,0,0,.03))' }}>
                  <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 6 }}>
                    讲答来源：{tutor.provider || 'AI'} · 可继续追问
                  </div>
                  <div style={{ whiteSpace: 'pre-wrap', fontSize: 14, lineHeight: 1.7 }}>{tutor.content}</div>
                  <FollowupBox onSend={askFollowup} busy={tutor?.loading} />
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    )
  }

  return (
    <>
      {view === 'home' && renderHome()}
      {view === 'practice' && renderPractice()}
      {view === 'result' && renderResult()}
    </>
  )
}

/* V14 追问输入框（结果页 AI 讲题弹层内） */
function FollowupBox({ onSend, busy }) {
  const [text, setText] = useState('')
  return (
    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
      <input className="input" style={{ flex: 1 }} value={text} disabled={busy}
        placeholder="继续追问，如：第 2 步为什么用戴维南定理？"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && !busy) { onSend(text); setText('') } }} />
      <button className="btn sm primary" disabled={busy || !text.trim()}
        onClick={() => { onSend(text); setText('') }}>追问</button>
    </div>
  )
}
