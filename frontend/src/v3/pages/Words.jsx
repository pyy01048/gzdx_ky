import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import useStore from '../../store/useStore'
import { GRADE } from '../../utils/spaced'
import { todayStr, fmtDateCN } from '../../utils/date'
import { CORE_WORDS } from '../../utils/words'
import { wordsApi } from '../../api/client'
import { migrateKey, ukey } from '../../utils/userKeys'
import {
  Alert,
  AnimatedNumber,
  Badge,
  Button,
  Chip,
  Dialog,
  Empty,
  Field,
  IconButton,
  Input,
  PageHeader,
  Progress,
  Ring,
  Segmented,
  Select,
  Skeleton,
  Textarea,
  Tile,
  cx,
  toast,
  toastErr,
  toastOk,
  toastWarn,
} from '../ui'
import {
  AlertTriangle,
  ArrowRight,
  Book,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  Eye,
  EyeOff,
  Keyboard,
  Library,
  List,
  Play,
  Plus,
  Quote,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Star,
  Target,
  Trash,
  Upload,
  Volume2,
  Wand,
  X,
} from '../icons'
import '../styles/study-pages.css'
import '../styles/study-glass.css'

/* 内置核心词表是产品内容：只作为显式导入入口，不在页面初始化时写入词库。 */
const BUILTIN_WORD_TEXT = CORE_WORDS.map((w) => `${w.word} ${w.phonetic} ${w.pos} ${w.meaning}`).join('\n')

/* 后端 page_size 统一上限 200（utils/response.py: MAX_PAGE_SIZE） */
const PAGE_SIZE = 200

/* 列表一次性渲染上限：与旧页保持一致，超出时明确提示总数 */
const LIST_LIMIT = 200

const STATUS_LABEL = {
  new: '新词',
  learning: '学习中',
  reviewing: '复习中',
  mastered: '已掌握',
}

const STATUS_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'new', label: '新词' },
  { value: 'learning', label: '学习中' },
  { value: 'reviewing', label: '复习中' },
  { value: 'mastered', label: '已掌握' },
  /* 错词视图（对标扇贝错词本）：历史「忘记」次数 > 0 的词单独暴露 */
  { value: 'lapses', label: '错过' },
]

const EMPTY_WORD_FORM = {
  deckId: 'core',
  word: '',
  phonetic: '',
  pos: '',
  meaning: '',
  root: '',
  example: '',
  exCn: '',
  tag: '',
}

/* 将后端 WordOut 映射为前端词条结构（列表与评分刷新共用，避免字段漂移） */
function formatWord(w) {
  return {
    id: w.id,
    word: w.word,
    phonetic: w.phonetic,
    pos: w.pos,
    meaning: w.meaning,
    root: w.root,
    example: w.example,
    ex_cn: w.example_cn,
    tag: w.tag,
    frequency: w.frequency,
    deck: w.deck_id ? String(w.deck_id) : 'core',
    // 后端部分路径会漏出 DB 枚举 not_mastered；前端队列只认 new。
    status: w.status === 'not_mastered' ? 'new' : w.status || 'new',
    ef: w.ease_factor || 2.5,
    interval: w.interval || 0,
    reps: w.reps || 0,
    lapses: w.lapses || 0,
    // 没有到期日 ≠ 今日到期：新词/未排期的词 due 留空，由今日新词配额单独处理。
    // （旧口径把空 due 兜底成今天，导入整本词书后"今日待复习"直接爆成全库量级。）
    due: w.due_date || null,
    lastReview: w.last_review,
    history: w.review_history || [],
    extra: w.extra || null,
  }
}

/* 把例句里的目标词打码，用于「先沉浸例句、后揭晓词义」的答题体验（对标扇贝/不背单词）。
   仅按整词边界替换，避免把词根嵌在别的词里也误打码。 */
function maskWordInExample(example, word) {
  if (!example || !word) return example || ''
  try {
    const esc = String(word)
      .trim()
      .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    if (!esc) return example
    return example.replace(new RegExp(`\\b${esc}s?\\b`, 'gi'), '＿＿＿')
  } catch {
    return example
  }
}

/* 单页并发上限：贴近 HTTP/1.1 每源 6 连接，超过只会排队，不会更快。 */
const FETCH_CONCURRENCY = 6

/* 分页拉全量：GET /api/words 返回 {items,total,page,page_size,total_pages}。
   先取第 1 页拿到 total_pages，其余页并发拉取（按页号回填，顺序与后端 order_by(id) 一致）。
   词库越大收益越明显：5952 词从 30 次串行往返压成约 5 波并发。
   include_extra=false：extra（近义词/短语）占列表载荷约八成，而它只在「行展开 / 当前学习词」
   时展示，改为按需调 GET /api/words/{id} 补齐，批量拉取不再为它付费。 */
async function fetchAllWords() {
  const fetchPage = (page) => wordsApi.list({ page, page_size: PAGE_SIZE, include_extra: false })
  const first = await fetchPage(1)
  const firstItems = Array.isArray(first?.items) ? first.items : []
  if (firstItems.length === 0 && (first?.total || 0) > 0) {
    throw new Error(`单词列表接口未返回 items（total=${first.total}）`)
  }
  const totalPages = Math.max(
    1,
    first?.total_pages || Math.ceil((first?.total || firstItems.length) / PAGE_SIZE) || 1,
  )
  const pageItems = new Array(totalPages).fill(null)
  pageItems[0] = firstItems
  const remaining = []
  for (let p = 2; p <= totalPages; p += 1) remaining.push(p)

  let cursor = 0
  const worker = async () => {
    while (cursor < remaining.length) {
      const idx = cursor
      cursor += 1
      const page = remaining[idx]
      try {
        const resp = await fetchPage(page)
        pageItems[page - 1] = Array.isArray(resp?.items) ? resp.items : []
      } catch {
        /* 单页失败留空，避免一页抖动拖垮整页；总数仍以第 1 页 total 为准。 */
        pageItems[page - 1] = []
      }
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(FETCH_CONCURRENCY, remaining.length) }, worker),
  )
  return pageItems.flatMap((items) => items || []).map(formatWord)
}

function MasteryRing({ level = 0, size = 34 }) {
  const reps = Math.max(0, Math.min(7, Number(level) || 0))
  return (
    <Ring
      value={(reps / 7) * 100}
      size={size}
      stroke={Math.max(3, size / 10)}
      gradient
      className="v3-study-mastery"
    >
      <span>{reps}</span>
    </Ring>
  )
}

export default function Words() {
  /* 字段级选择器：store 其他字段变化不触发整页重渲染 */
  const words = useStore((s) => s.words)
  const decks = useStore((s) => s.decks)
  const addDeck = useStore((s) => s.addDeck)
  const reviewWord = useStore((s) => s.reviewWord)
  const removeWord = useStore((s) => s.removeWord)
  const setWords = useStore((s) => s.setWords)
  const setDecks = useStore((s) => s.setDecks)

  const [view, setView] = useState('learn')
  const [statsOpen, setStatsOpen] = useState(false) // 今日复习视图顶部 bento 统计默认折叠成一行摘要
  const [flashcard, setFlashcard] = useState(false)
  const [curIdx, setCurIdx] = useState(0)
  const [showAns, setShowAns] = useState(false)
  const [grading, setGrading] = useState(false)
  const [deckName, setDeckName] = useState('')
  const [creatingDeck, setCreatingDeck] = useState(false)
  const [importText, setImportText] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [packSel, setPackSel] = useState('all')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [stats, setStats] = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [importing, setImporting] = useState(false)
  const [excelFile, setExcelFile] = useState(null)
  const [sessionStats, setSessionStats] = useState({
    again: 0,
    hard: 0,
    good: 0,
    easy: 0,
    startTime: null,
    words: [],
  })
  const [reviewedIds, setReviewedIds] = useState([])
  /* 错词回炉（对标扇贝/Anki）：本轮评「忘记」的词排到队尾重过，直到记得才放行 */
  const [relearnIds, setRelearnIds] = useState([])
  /* 错词重练聚焦：null = 正常队列；数组 = 只练这些词（来自本轮/历史错词清单） */
  const [focusIds, setFocusIds] = useState(null)
  const [dailyQuota, setDailyQuota] = useState(() => {
    migrateKey('words_daily_quota')
    const saved = localStorage.getItem(ukey('words_daily_quota'))
    return saved ? parseInt(saved, 10) : 30
  })
  const [freeMode, setFreeMode] = useState(false)
  /* 拼写练习模式（对标「不背单词」拼写）：看释义/音标，输入单词拼写 */
  const [spellMode, setSpellMode] = useState(false)
  /* 沉浸答题模式：只留题卡，隐去页头/统计/工具条（对标扇贝专注模式，Esc 退出） */
  const [immersive, setImmersive] = useState(false)
  const [spellAnswer, setSpellAnswer] = useState('')
  const [spellResult, setSpellResult] = useState(null)
  const [spellChecking, setSpellChecking] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [expandedId, setExpandedId] = useState(null)
  const [showAddWord, setShowAddWord] = useState(false)
  const [wordForm, setWordForm] = useState(EMPTY_WORD_FORM)
  const [wordErr, setWordErr] = useState('')
  const [savingWord, setSavingWord] = useState(false)

  const today = todayStr()

  /* 从后端加载单词 / 词库 / 统计；失败展示真实错误，不回退本地假数据。 */
  const loadData = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [backendDecks, backendWords, statsResp] = await Promise.all([
        wordsApi.listDecks().catch(() => []),
        fetchAllWords(),
        wordsApi.stats(),
      ])
      if (Array.isArray(backendDecks) && backendDecks.length > 0) {
        setDecks(
          backendDecks.map((d) => ({
            id: d.id,
            name: d.name,
            count: d.word_count || 0,
            source: d.source || '后端',
            description: d.description,
            color: d.color,
          })),
        )
      }
      setWords(backendWords)
      setStats(statsResp || null)
      return true
    } catch (err) {
      console.error('单词数据加载失败：', err)
      setLoadError(err?.message || '未知错误')
      return false
    } finally {
      setLoading(false)
    }
  }, [setDecks, setWords])

  useEffect(() => {
    loadData()
  }, [loadData])

  const refresh = async () => {
    const ok = await loadData()
    if (ok) toastOk('单词数据已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  const refreshStats = useCallback(async () => {
    try {
      setStats(await wordsApi.stats())
    } catch {
      /* 统计刷新失败不阻塞主流程 */
    }
  }, [])

  /* 复习队列（learning + reviewing）：只认后端真实 due_date ≤ 今天。
     不再走 dueCards()——它把「无到期日」也当今日到期，会把整库新词灌进今日队列。 */
  const dueReviewAll = useMemo(
    () =>
      words.filter((w) => (w.status === 'learning' || w.status === 'reviewing') && w.due && w.due <= today),
    [words, today],
  )
  const newWordsPool = useMemo(() => words.filter((w) => w.status === 'new'), [words])

  /* W1 今日计划供数（GET /words/stats · daily_load.today_plan）：
     today_new / today_review 是"今天该学多少"的唯一答案；后端没给时退回
     本机口径（到期全量 + 本地配额），并在界面上明确标注口径来源。 */
  const planReview = Number.isFinite(stats?.today_review) ? Math.max(0, stats.today_review) : null
  const planNew = Number.isFinite(stats?.today_new) ? Math.max(0, stats.today_new) : null
  const planSource = planReview != null || planNew != null
  const dueReview = planReview != null ? dueReviewAll.slice(0, planReview) : dueReviewAll
  const freshSlice = newWordsPool.slice(0, planNew != null ? planNew : dailyQuota)

  /* 复习队列：到期复习词 + 今日计划（或本机配额）内的新词 */
  const queue = useMemo(() => [...dueReview, ...freshSlice], [dueReview, freshSlice])

  const freeQueue = useMemo(() => words.filter((w) => w.status !== 'mastered'), [words])
  const focusQueue = useMemo(
    () => (focusIds ? focusIds.map((id) => words.find((w) => w.id === id)).filter(Boolean) : null),
    [focusIds, words],
  )
  const activeQueue = focusQueue || (freeMode ? freeQueue : queue)
  /* 同一轮里已评分的词不再出现：评分后 due 可能仍是今天（忘记），
     队列缩短也不会让 curIdx 跳过下一个词。评「忘记」的词进 relearn 队尾回炉。 */
  const remainingQueue = useMemo(() => {
    const head = activeQueue.filter((w) => !reviewedIds.includes(w.id))
    const tail = relearnIds
      .filter((id) => !head.some((w) => w.id === id))
      .map((id) => words.find((w) => w.id === id))
      .filter(Boolean)
    return [...head, ...tail]
  }, [activeQueue, reviewedIds, relearnIds, words])
  const current = remainingQueue[curIdx] || null
  /* 沉浸模式只在答题视图有当前词时生效 */
  const immersiveOn = immersive && view === 'learn' && !!current

  /* 批量拉取不带 extra（约占载荷八成）；行展开或成为当前学习词时按需补齐一次。
     detailTried 防重复：无 extra 的词拉一次后不再重试，避免无限请求。 */
  const detailTried = useRef(new Set())
  const hydrateDetail = useCallback(
    async (id) => {
      if (!id || detailTried.current.has(id)) return
      detailTried.current.add(id)
      try {
        const detail = await wordsApi.get(id)
        if (!detail || detail.id == null) return
        setWords((ws) => ws.map((w) => (w.id === detail.id ? formatWord(detail) : w)))
      } catch {
        /* 详情是增强信息，失败不打断学习流程 */
      }
    },
    [setWords],
  )

  useEffect(() => {
    if (expandedId == null) return
    const w = words.find((x) => x.id === expandedId)
    if (w && !w.extra) hydrateDetail(expandedId)
  }, [expandedId, words, hydrateDetail])

  useEffect(() => {
    if (current?.id != null && !current.extra) hydrateDetail(current.id)
  }, [current?.id, current?.extra, hydrateDetail])

  const nextDue = useMemo(() => {
    const future = words.filter((w) => w.status !== 'mastered' && w.due && w.due > today)
    if (future.length === 0) return null
    return future.reduce((m, w) => (w.due < m ? w.due : m), future[0].due)
  }, [words, today])

  const reviewedToday = useMemo(
    () => words.filter((w) => w.lastReview && String(w.lastReview).slice(0, 10) === today).length,
    [words, today],
  )
  const todayTarget = reviewedToday + queue.length
  const todayPct =
    words.length === 0
      ? 0
      : queue.length === 0
        ? 100
        : Math.min(100, Math.round((reviewedToday / (reviewedToday + queue.length)) * 100))
  /* 复习债：真实到期但今日计划没排下的差额（口径与 hub「今日累计到期」一致，
     只在数字后面做提示，不并进「今日」主数字制造恐慌）。 */
  const reviewDebt = Math.max(0, dueReviewAll.length - dueReview.length)

  const masteredCount = stats ? stats.mastered : words.filter((w) => w.status === 'mastered').length
  const learningCount = stats
    ? (stats.learning || 0) + (stats.reviewing || 0)
    : words.filter((w) => w.status === 'learning' || w.status === 'reviewing').length
  const masteryPct = words.length ? Math.round((masteredCount / words.length) * 100) : 0
  const newDue = queue.filter((w) => w.status === 'new').length
  const reviewDue = queue.length - newDue

  const sessionTotal = sessionStats.again + sessionStats.hard + sessionStats.good + sessionStats.easy
  const sessionCorrect = sessionStats.good + sessionStats.easy
  const sessionAccuracy = sessionTotal > 0 ? Math.round((sessionCorrect / sessionTotal) * 100) : 0
  const sessionDuration = sessionStats.startTime
    ? Math.round((Date.now() - sessionStats.startTime) / 1000 / 60)
    : 0

  /* 本轮错词暴露（对标扇贝「错词本」）：凡评过「忘记」/拼错的词都列出来，
     并标注是否已在回炉环节记牢。 */
  const sessionWrong = useMemo(() => {
    const byId = new Map()
    sessionStats.words.forEach((r) => {
      if (r.grade === 'again' && !byId.has(r.id)) {
        byId.set(r.id, { id: r.id, word: r.word, passed: !relearnIds.includes(r.id) })
      }
    })
    byId.forEach((v) => {
      v.passed = !relearnIds.includes(v.id)
    })
    return [...byId.values()]
  }, [sessionStats.words, relearnIds])
  const wrongMeaningOf = useCallback((id) => words.find((w) => w.id === id)?.meaning || '', [words])

  /* 今日计划主数字：后端 daily_load 供数优先；没有才退回本机队列口径并明确标注 */
  const todayPlanTotal = planSource ? (planNew ?? 0) + (planReview ?? 0) : queue.length

  const pronounce = (text) => {
    if (!text) return
    if (!('speechSynthesis' in window)) return toastWarn('当前浏览器不支持语音发音')
    try {
      window.speechSynthesis.cancel()
      const u = new SpeechSynthesisUtterance(text)
      u.lang = 'en-US'
      u.rate = 0.9
      window.speechSynthesis.speak(u)
    } catch {
      toastErr('发音失败')
    }
  }

  const startSession = useCallback(() => {
    setSessionStats({ again: 0, hard: 0, good: 0, easy: 0, startTime: Date.now(), words: [] })
    setReviewedIds([])
    setRelearnIds([])
    setFocusIds(null)
    setCurIdx(0)
    setShowAns(false)
    setSpellAnswer('')
    setSpellResult(null)
    setView('learn')
  }, [])

  const startFreeSession = useCallback(() => {
    if (freeQueue.length === 0) {
      toastWarn('没有可学习的单词')
      return
    }
    setFocusIds(null)
    setFreeMode(true)
    startSession()
  }, [freeQueue.length, startSession])

  /* 错词重练：只练本轮标出的错词（含拼写错的词）。startSession 会清 focusIds，
     所以必须先起会话再落聚焦名单。 */
  const startWrongRounds = useCallback(
    (ids) => {
      if (!ids.length) return
      setFreeMode(false)
      startSession()
      setFocusIds(ids)
    },
    [startSession],
  )

  const exitFreeSession = useCallback(() => {
    setFreeMode(false)
    setFocusIds(null)
    setReviewedIds([])
    setRelearnIds([])
    setCurIdx(0)
    setShowAns(false)
  }, [])

  const grade = async (g) => {
    if (!current || grading) return
    setGrading(true)
    const gradeKey =
      g === GRADE.AGAIN ? 'again' : g === GRADE.HARD ? 'hard' : g === GRADE.GOOD ? 'good' : 'easy'
    const isAgain = g === GRADE.AGAIN
    setSessionStats((prev) => ({
      ...prev,
      [gradeKey]: prev[gradeKey] + 1,
      words: [...prev.words, { id: current.id, word: current.word, grade: gradeKey }],
    }))
    /* 忘记 → 轮换取队尾回炉；记得 → 从回炉名单放行 */
    setRelearnIds((prev) => {
      const rest = prev.filter((x) => x !== current.id)
      return isAgain ? [...rest, current.id] : rest
    })
    try {
      const updated = await wordsApi.review(current.id, g)
      if (updated) {
        setWords((ws) => ws.map((w) => (w.id === updated.id ? formatWord(updated) : w)))
        refreshStats()
      } else {
        reviewWord(current.id, g)
      }
    } catch (err) {
      toastErr(`评分保存失败：${err?.message || '未知错误'}`)
      reviewWord(current.id, g)
    } finally {
      setGrading(false)
    }
    setReviewedIds((prev) => (prev.includes(current.id) ? prev : [...prev, current.id]))
    setShowAns(false)
    /* 当前词从队列移除后，下一词落到同一索引；忘记的词回到队尾，队列不缩短 */
    const nextLen = remainingQueue.length - (isAgain ? 0 : 1)
    if (curIdx >= nextLen) setView('summary')
  }

  const prevWord = () => {
    if (curIdx > 0) {
      setCurIdx(curIdx - 1)
      setShowAns(false)
    }
  }

  /* 拼写模式：提交当前词的拼写，自动判对错并记录复习（正确=grade5，错误=grade1） */
  const submitSpell = async (e) => {
    if (e) e.preventDefault()
    if (!current || spellChecking) return
    if (!spellAnswer.trim()) return
    setSpellChecking(true)
    try {
      const res = await wordsApi.spellCheck(current.id, spellAnswer, true)
      const correct = !!res?.correct
      setSpellResult(res || { correct: false, word: current.word, user_answer: spellAnswer })
      setSessionStats((prev) => ({
        ...prev,
        [correct ? 'good' : 'again']: (prev[correct ? 'good' : 'again'] || 0) + 1,
        words: [...prev.words, { id: current.id, word: current.word, grade: correct ? 'good' : 'again' }],
      }))
      if (res?.review) {
        setWords((ws) => ws.map((w) => (w.id === res.review.id ? formatWord(res.review) : w)))
        refreshStats()
      }
      /* 拼错的词同样进回炉队列，本轮必须记牢才放行 */
      setRelearnIds((prev) => {
        const rest = prev.filter((x) => x !== current.id)
        return correct ? rest : [...rest, current.id]
      })
      setReviewedIds((prev) => (prev.includes(current.id) ? prev : [...prev, current.id]))
    } catch (err) {
      toastErr(`拼写检查失败：${err?.message || '未知错误'}`)
      setSpellResult({ correct: false, word: current.word, user_answer: spellAnswer })
    } finally {
      setSpellChecking(false)
    }
  }

  /* 拼写模式：查看结果后进入下一词。
     submitSpell 已把当前词移出 head（错词转入回炉 tail），remainingQueue 在本帧
     已是「移除后」的口径，下一词就落在同一 curIdx；curIdx 越界才是本轮结束。
     （旧条件 curIdx+1 >= length 会在还剩一词时提前跳总结页。） */
  const nextSpell = () => {
    setSpellAnswer('')
    setSpellResult(null)
    setShowAns(false)
    if (curIdx >= remainingQueue.length) setView('summary')
  }

  /* 切换拼写模式：切换时清空输入与结果 */
  const toggleSpellMode = () => {
    setSpellMode((prev) => {
      const next = !prev
      setSpellAnswer('')
      setSpellResult(null)
      setShowAns(false)
      return next
    })
  }
  const nextWord = () => {
    if (curIdx + 1 < remainingQueue.length) {
      setCurIdx(curIdx + 1)
      setShowAns(false)
    }
  }

  /* 快捷键：显示释义后按 1-4 评分（与页面提示一致；拼写模式走输入框，不触发） */
  useEffect(() => {
    if (view !== 'learn' || !showAns || spellMode) return undefined
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const tag = e.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target?.isContentEditable) return
      if (['1', '2', '3', '4'].includes(e.key)) {
        e.preventDefault()
        grade([GRADE.AGAIN, GRADE.HARD, GRADE.GOOD, GRADE.EASY][Number(e.key) - 1])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // grade 依赖的评分状态都由函数式更新处理，这里只需在切换卡片/阶段时重绑。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, showAns, current?.id, curIdx, remainingQueue.length, grading])

  /* 沉浸模式：Esc 退出 */
  useEffect(() => {
    if (!immersive) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') setImmersive(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [immersive])

  const gradeWord = async (id, g) => {
    try {
      const updated = await wordsApi.review(id, g)
      if (updated) {
        setWords((ws) => ws.map((w) => (w.id === updated.id ? formatWord(updated) : w)))
        refreshStats()
      }
      toastOk('已记录熟练度')
    } catch (err) {
      toastErr(`评分保存失败：${err?.message || '未知错误'}`)
    }
  }

  const wordBadge = (w) => {
    if (w.tag) return <Badge tone="primary">{w.tag}</Badge>
    if (w.frequency) return <Badge tone="primary">{w.frequency}</Badge>
    const stars = w.status === 'mastered' ? 3 : w.status === 'learning' || w.status === 'reviewing' ? 2 : 1
    return (
      <Badge tone="outline" className="v3-study-familiarity">
        <Star size={11} /> {stars}/3 熟悉度
      </Badge>
    )
  }

  const deckTarget = () => {
    const n = Number(packSel)
    return packSel !== 'all' && packSel !== 'core' && Number.isFinite(n) ? n : null
  }

  const runTextImport = async (text) => {
    if (!text.trim()) {
      toastWarn('请输入单词内容')
      return
    }
    setImporting(true)
    setImportResult(null)
    try {
      const result = await wordsApi.importText({ text, deck_id: deckTarget() })
      setImportResult(result)
      toastOk(`导入完成：成功 ${result?.imported ?? 0} 个，跳过 ${result?.skipped ?? 0} 个`)
      setWords(await fetchAllWords())
      refreshStats()
    } catch (e) {
      toastErr(`导入失败：${e.message}`)
    } finally {
      setImporting(false)
    }
  }

  const handleImport = () => runTextImport(importText)
  const handleImportBuiltin = () => runTextImport(BUILTIN_WORD_TEXT)

  const handleExcelImport = async () => {
    if (!excelFile) {
      toastWarn('请选择 Excel 文件')
      return
    }
    setImporting(true)
    setImportResult(null)
    try {
      const formData = new FormData()
      formData.append('file', excelFile)
      if (deckTarget() != null) formData.append('deck_id', packSel)
      const result = await wordsApi.importExcel(formData)
      setImportResult(result)
      toastOk(`Excel 导入完成：成功 ${result?.imported ?? 0} 个，跳过 ${result?.skipped ?? 0} 个`)
      setWords(await fetchAllWords())
      refreshStats()
    } catch (e) {
      toastErr(`Excel 导入失败：${e.message}`)
    } finally {
      setImporting(false)
      setExcelFile(null)
    }
  }

  const addNewDeck = async () => {
    const name = deckName.trim()
    if (!name) {
      toastWarn('请输入词库名称')
      return
    }
    setCreatingDeck(true)
    try {
      const created = await wordsApi.createDeck({ name })
      if (created?.id != null) {
        const item = {
          id: created.id,
          name: created.name || name,
          count: created.word_count || 0,
          source: created.source || '自定义',
          description: created.description,
          color: created.color,
        }
        setDecks([...decks, item])
        setPackSel(String(created.id))
        toastOk('词库已创建')
      } else {
        addDeck(name)
        toastOk('词库已创建')
      }
    } catch {
      // 后端不可用时沿用旧的本地词库行为，避免输入丢失。
      addDeck(name)
      toastWarn('后端同步失败，词库已保存到本地')
    } finally {
      setCreatingDeck(false)
      setDeckName('')
    }
  }

  const handleRemoveWord = async (id) => {
    try {
      await wordsApi.remove(id)
      removeWord(id)
      refreshStats()
      toastOk('单词已删除')
    } catch (err) {
      toastErr(`删除失败：${err?.message || '未知错误'}`)
    }
  }

  /* 导出 PDF（对标「不背单词」纸质导出）：按当前词库/状态筛选导出 */
  const exportPdf = async () => {
    if (words.length === 0) {
      toastWarn('词库为空，没有可导出的单词')
      return
    }
    try {
      await wordsApi.exportPdf({
        deck_id: packSel !== 'all' && packSel !== 'core' ? packSel : undefined,
        /* 「错过」是前端筛选视图，不是后端 status 枚举，导出时不传 status */
        status: statusFilter !== 'all' && statusFilter !== 'lapses' ? statusFilter : undefined,
      })
      toastOk('单词本 PDF 已导出')
    } catch (err) {
      toastErr(`导出失败：${err?.message || '未知错误'}`)
    }
  }

  const saveQuota = (val) => {
    setDailyQuota(val)
    localStorage.setItem(ukey('words_daily_quota'), String(val))
    toast(`每日新词配额已设置为 ${val} 个`)
  }

  const openAddWord = () => {
    setWordForm({
      ...EMPTY_WORD_FORM,
      deckId: packSel !== 'all' && packSel !== 'core' ? packSel : 'core',
    })
    setWordErr('')
    setShowAddWord(true)
  }

  const submitWord = async () => {
    if (!wordForm.word.trim() || !wordForm.meaning.trim()) {
      setWordErr('请填写单词与释义')
      return
    }
    setWordErr('')
    setSavingWord(true)
    try {
      const deckId = Number(wordForm.deckId)
      const payload = {
        word: wordForm.word.trim(),
        meaning: wordForm.meaning.trim(),
        deck_id: wordForm.deckId !== 'core' && Number.isFinite(deckId) ? deckId : null,
      }
      if (wordForm.phonetic.trim()) payload.phonetic = wordForm.phonetic.trim()
      if (wordForm.pos.trim()) payload.pos = wordForm.pos.trim()
      if (wordForm.root.trim()) payload.root = wordForm.root.trim()
      if (wordForm.example.trim()) payload.example = wordForm.example.trim()
      if (wordForm.exCn.trim()) payload.example_cn = wordForm.exCn.trim()
      if (wordForm.tag.trim()) payload.tag = wordForm.tag.trim()
      await wordsApi.create(payload)
      setWords(await fetchAllWords())
      refreshStats()
      setShowAddWord(false)
      setWordForm(EMPTY_WORD_FORM)
      toastOk('单词已添加')
    } catch (err) {
      setWordErr(err?.message || '添加失败，请稍后重试')
    } finally {
      setSavingWord(false)
    }
  }

  const deckFiltered = useMemo(
    () => (packSel === 'all' ? words : words.filter((w) => w.deck === packSel)),
    [words, packSel],
  )

  const filteredWords = useMemo(() => {
    const q = searchTerm.trim().toLowerCase()
    return deckFiltered.filter((w) => {
      if (statusFilter === 'lapses') {
        if (!(w.lapses > 0)) return false
      } else if (statusFilter !== 'all' && w.status !== statusFilter) return false
      if (!q) return true
      return [w.word, w.meaning, w.pos, w.root, w.tag, w.phonetic]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    })
  }, [deckFiltered, searchTerm, statusFilter])

  const shownWords = filteredWords.slice(0, LIST_LIMIT)

  const currentDeckName = current
    ? decks.find((d) => String(d.id) === current.deck)?.name ||
      (current.deck && current.deck !== 'core' ? current.deck : '默认词库')
    : ''

  const totalWords = stats ? stats.total : words.length

  return (
    <div className={cx('v3-stack v3-study v3-glasspage', immersiveOn && 'v3-words--immersive')}>
      {!immersiveOn && (
        <PageHeader
          eyebrow="WORDS · FSRS 间隔重复"
          title="单词记忆"
          sub="按真实复习排期安排新词与复习，四档评分决定下一次出现的时间。"
          actions={
            <>
              <IconButton
                label="刷新单词数据"
                icon={<RefreshCw size={17} />}
                onClick={refresh}
                disabled={loading}
              />
              <Button
                variant={flashcard ? 'tonal' : 'text'}
                icon={flashcard ? <EyeOff size={16} /> : <Eye size={16} />}
                aria-pressed={flashcard}
                onClick={() => setFlashcard((v) => !v)}
              >
                试卷模式
              </Button>
              <Button
                variant="text"
                icon={<Play size={16} />}
                aria-pressed={immersive}
                disabled={queue.length === 0 && !freeMode && !focusIds}
                title="只保留题卡的专注答题模式（Esc 退出）"
                onClick={() => {
                  setSpellMode(false)
                  setImmersive(true)
                }}
              >
                沉浸模式
              </Button>
              <Button variant="tonal" icon={<Upload size={16} />} onClick={() => setShowImport(true)}>
                导入单词
              </Button>
              <Button
                variant="text"
                icon={<Download size={16} />}
                onClick={exportPdf}
                disabled={words.length === 0}
              >
                导出 PDF
              </Button>
              <Button variant="gradient" icon={<Plus size={16} />} onClick={openAddWord}>
                添加单词
              </Button>
            </>
          }
        />
      )}

      {loading && !words.length && !loadError ? (
        <div className="v3-bento">
          {Array.from({ length: 4 }).map((_, i) => (
            <Tile span={3} key={i} className="v3-study-skeleton-tile">
              <Skeleton height={64} />
            </Tile>
          ))}
          <Tile span={8}>
            <Skeleton height={250} />
          </Tile>
          <Tile span={4}>
            <Skeleton height={250} />
          </Tile>
        </div>
      ) : loadError && !words.length ? (
        <Alert tone="danger" icon={<BookOpen size={24} />} className="v3-study-alert" role="alert">
          <div className="v3-study-alert__inner">
            <div><strong>单词数据加载失败</strong><p>后端接口请求失败：{loadError}</p></div>
            <Button variant="tonal" onClick={loadData}>重新加载</Button>
          </div>
        </Alert>
      ) : (
        <>
          {loadError ? (
            <Alert tone="danger" className="v3-study-alert">
              <div className="v3-study-alert__inner">
                <span>刷新失败，当前展示的是上次加载的数据：{loadError}</span>
                <Button size="sm" variant="text" onClick={loadData}>
                  重试
                </Button>
              </div>
            </Alert>
          ) : null}

          {view === 'learn' && !immersiveOn ? (
            <button
              type="button"
              className="v3-study-statsbar"
              aria-expanded={statsOpen}
              onClick={() => setStatsOpen((v) => !v)}
            >
              <span className="v3-study-statsbar__text">
                词库库存 <b>{stats ? stats.total : '—'}</b> 词 · 今日计划{' '}
                <b className="is-danger">{todayPlanTotal}</b> · 累计到期{' '}
                <b>{stats?.due_today ?? dueReviewAll.length}</b>
                {reviewDebt > 0 ? (
                  <em className="v3-study-debt">（今日未排满，复习债 {reviewDebt} 词分批还）</em>
                ) : null}{' '}
                · 学习中 <b>{learningCount}</b> · 已掌握 <b className="is-success">{masteredCount}</b>（
                {masteryPct}%）· 今日已评 <b>{reviewedToday}</b>
              </span>
              <span className="v3-study-statsbar__act">{statsOpen ? '收起统计' : '展开统计'}</span>
              <ChevronDown size={16} className={cx('v3-study-statsbar__chev', statsOpen && 'is-open')} />
            </button>
          ) : null}

          {(view !== 'learn' || statsOpen) && !immersiveOn ? (
            <div className="v3-bento">
              <Tile span={3} className="v3-study-stat">
                <span className="v3-tile__label">
                  <Book size={15} /> 词库库存
                </span>
                <span className="v3-tile__value">
                  {stats ? <AnimatedNumber value={stats.total} /> : '—'}
                  <em>词</em>
                </span>
                <span className="v3-tile__hint">全部词库累计词数</span>
              </Tile>
              <Tile span={3} className="v3-study-stat" title={stats?.usage || ''}>
                <span className="v3-tile__label">
                  <Target size={15} /> 今日计划
                </span>
                <span className="v3-tile__value v3-study-tone-danger">
                  {todayPlanTotal}
                  <em>词</em>
                </span>
                <span className="v3-tile__hint">
                  {planSource
                    ? `后端排期：新词 ${planNew ?? 0} + 复习 ${planReview ?? 0}`
                    : '后端未下发今日计划 · 本机到期口径'}
                </span>
              </Tile>
              <Tile span={3} className="v3-study-stat">
                <span className="v3-tile__label">
                  <Clock size={15} /> 学习中
                </span>
                <span className="v3-tile__value v3-study-tone-warning">
                  {learningCount}
                  <em>词</em>
                </span>
                <span className="v3-tile__hint">learning + reviewing</span>
              </Tile>
              <Tile span={3} className="v3-study-stat">
                <span className="v3-tile__label">
                  <CheckCircle2 size={15} /> 已掌握
                </span>
                <span className="v3-tile__value v3-study-tone-success">
                  {masteredCount}
                  <em>词</em>
                </span>
                <span className="v3-tile__hint">掌握度 {masteryPct}%</span>
              </Tile>

              <Tile span={8} variant="hero" className="v3-study-hero">
                <div className="v3-study-hero__body">
                  <div className="v3-study-hero__ring">
                    <Ring value={todayPct} size={136} stroke={11} gradient>
                      <div className="v3-study-ring-center">
                        <strong>{todayPct}%</strong>
                        <span>今日进度</span>
                        <em>{todayTarget > 0 ? `${reviewedToday}/${todayTarget} 词` : '今日无到期'}</em>
                      </div>
                    </Ring>
                  </div>
                  <div className="v3-study-hero__copy">
                    <span className="v3-eyebrow v3-study-hero__eyebrow">
                      <Sparkles size={14} data-idle="spin" /> 今日复习
                    </span>
                    <h2>
                      {words.length === 0
                        ? '先把词库装满，再按记忆曲线复习。'
                        : queue.length === 0
                          ? '今天的队列已经清空。'
                          : '按记忆曲线，把今天的词过一遍。'}
                    </h2>
                    <p>
                      {words.length === 0
                        ? '导入自己的单词表或内置核心词表，系统会按遗忘曲线自动排期。'
                        : queue.length === 0
                          ? planSource
                            ? `今日 ${todayPlanTotal} 词已排空。词库还有 ${Math.max(0, totalWords - masteredCount)} 词在路上，${nextDue ? `下一批复习在 ${fmtDateCN(nextDue)}。` : '全部单词都已掌握。'}`
                            : `没有今天到期的复习项（词库总量 ${totalWords} 词是库存，不是今天的任务）。${nextDue ? `最早下次复习在 ${fmtDateCN(nextDue)}。` : '全部单词都已掌握。'}`
                          : `${planSource ? `今日计划 ${todayPlanTotal} 词` : `今日到期队列 ${queue.length} 词（后端未下发计划）`}：到期复习 ${reviewDue} 词 + ${planSource ? '计划' : '配额内'}新词 ${newDue} 词${reviewDebt > 0 ? `；另有复习债 ${reviewDebt} 词按每日计划分批消化` : ''}；评分后自动排入下一次复习。`}
                    </p>
                    <div className="v3-study-hero__meta">
                      <span>
                        <Target size={14} /> 今日计划 {todayPlanTotal}
                      </span>
                      <span>
                        <Clock size={14} />{' '}
                        {planSource
                          ? `新词计划 ${planNew ?? 0}（本机上限 ${dailyQuota}）`
                          : `新词上限 ${dailyQuota}`}
                      </span>
                      <span>
                        <CheckCircle2 size={14} /> 已掌握 {masteredCount}
                      </span>
                    </div>
                    <div className="v3-study-hero__actions">
                      {words.length === 0 ? (
                        <Button
                          variant="filled"
                          icon={<Upload size={16} />}
                          onClick={() => setShowImport(true)}
                        >
                          导入词库
                        </Button>
                      ) : queue.length > 0 ? (
                        <>
                          <Button
                            variant="gradient"
                            icon={<Play size={16} />}
                            onClick={() => {
                              setSpellMode(false)
                              startSession()
                            }}
                          >
                            {sessionTotal > 0 ? '继续今日复习' : '开始今日复习'}
                          </Button>
                          <Button
                            variant={spellMode ? 'filled' : 'tonal'}
                            icon={<Keyboard size={16} />}
                            onClick={toggleSpellMode}
                          >
                            {spellMode ? '拼写模式已开' : '拼写模式'}
                          </Button>
                        </>
                      ) : freeQueue.length > 0 ? (
                        <Button variant="tonal" icon={<RotateCcw size={16} />} onClick={startFreeSession}>
                          自由学习（{freeQueue.length} 词）
                        </Button>
                      ) : (
                        <Badge tone="success">今日队列已清空</Badge>
                      )}
                      <Button variant="text" onClick={() => setView('list')}>
                        浏览单词列表
                      </Button>
                    </div>
                  </div>
                </div>
              </Tile>

              <Tile span={4} className="v3-study-side">
                <div className="v3-study-side__head">
                  <div>
                    <span className="v3-tile__label">
                      <Library size={15} /> 词库掌握
                    </span>
                    <strong className="v3-study-side__pct">{masteryPct}%</strong>
                  </div>
                  <Badge tone="outline">{totalWords} 词</Badge>
                </div>
                <Progress value={masteryPct} gradient height={8} />
                <div className="v3-study-kv">
                  <div>
                    <span>学习中</span>
                    <b>{learningCount}</b>
                  </div>
                  <div>
                    <span>已掌握</span>
                    <b>{masteredCount}</b>
                  </div>
                  <div>
                    <span>今日已评分</span>
                    <b>{reviewedToday}</b>
                  </div>
                </div>
                <div className="v3-study-side__note">
                  <Clock size={14} />
                  <span>{nextDue ? `最早下次复习：${nextDue}` : '暂无排期中的复习词'}</span>
                </div>
                <div className="v3-study-side__note">
                  <Book size={14} />
                  <span>{decks.length ? `${decks.length} 个词库可用` : '尚未创建自定义词库'}</span>
                </div>
              </Tile>
            </div>
          ) : null}

          {!immersiveOn && (
            <div className="v3-study-toolbar">
              <Segmented
                ariaLabel="单词页视图"
                value={view}
                onChange={setView}
                options={[
                  { value: 'learn', label: '今日复习', icon: <Play size={14} /> },
                  { value: 'summary', label: '学习总结', icon: <Target size={14} /> },
                  { value: 'list', label: '词库列表', icon: <List size={14} /> },
                  { value: 'decks', label: '词库管理', icon: <Library size={14} /> },
                ]}
              />
              <div className="v3-study-toolbar__end">
                <Badge tone={flashcard ? 'warning' : 'outline'}>
                  {flashcard ? '试卷模式开' : '试卷模式关'}
                </Badge>
                <Badge tone="outline">{loading ? '同步中…' : `${words.length} 词已载入`}</Badge>
              </div>
            </div>
          )}

          {view === 'learn' && freeMode && remainingQueue.length > 0 ? (
            <Alert tone="info" className="v3-study-banner">
              <div className="v3-study-banner__inner">
                <span>自由学习模式：提前复习尚未到期的词，评分照常计入记忆调度。</span>
                <Button size="sm" variant="text" onClick={exitFreeSession}>
                  退出自由学习
                </Button>
              </div>
            </Alert>
          ) : null}

          {view === 'learn' && focusIds && remainingQueue.length > 0 ? (
            <Alert tone="warning" className="v3-study-banner">
              <div className="v3-study-banner__inner">
                <span>错词重练：只过本轮标出的 {remainingQueue.length} 个错词，记牢才放行。</span>
                <Button size="sm" variant="text" onClick={startSession}>
                  返回今日复习
                </Button>
              </div>
            </Alert>
          ) : null}

          {view === 'learn' ? (
            remainingQueue.length === 0 ? (
              (stats?.total || words.length) === 0 ? (
                <Tile span={12} className="v3-study-empty">
                  <Empty
                    icon={<BookOpen size={26} />}
                    title="还没有学习单词"
                    text="词库为空。先选择或创建词书，或批量导入自己的单词表；导入后系统会按遗忘曲线自动排入复习。"
                    action={
                      <div className="v3-row v3-study-empty__actions">
                        <Button
                          variant="gradient"
                          icon={<Upload size={16} />}
                          onClick={() => setShowImport(true)}
                        >
                          导入单词
                        </Button>
                        <Button variant="tonal" onClick={() => setView('decks')}>
                          前往词库管理
                        </Button>
                      </div>
                    }
                  />
                </Tile>
              ) : (
                <Tile span={12} className="v3-study-empty">
                  <Empty
                    icon={<CheckCircle2 size={26} />}
                    title="本轮复习完成"
                    text={
                      activeQueue.length > 0
                        ? `本轮已评 ${sessionTotal} 词；这些词本轮不再重复出现，可稍后再学或查看词库列表。`
                        : `今日没有排入的复习（词库库存 ${totalWords} 词是总量，不是今日任务）。${nextDue ? `最早的下次复习在 ${fmtDateCN(nextDue)}，想提前过一遍可以用自由学习。` : '全部单词都已掌握。'}`
                    }
                    action={
                      freeQueue.length > 0 ? (
                        <Button variant="gradient" icon={<Play size={16} />} onClick={startFreeSession}>
                          自由学习（{freeQueue.length} 词）
                        </Button>
                      ) : (
                        <Button variant="tonal" onClick={() => setView('list')}>
                          查看词库列表
                        </Button>
                      )
                    }
                  />
                </Tile>
              )
            ) : current ? (
              <Tile span={12} className="v3-study-focus">
                <div className="v3-study-focus__head">
                  <div className="v3-study-focus__badges">
                    <MasteryRing level={current.reps} size={38} />
                    <Badge tone="primary">{current.tag || currentDeckName || '单词'}</Badge>
                    {flashcard ? <Badge tone="warning">试卷模式</Badge> : null}
                    {focusIds ? <Badge tone="danger">错词重练 {remainingQueue.length} 词</Badge> : null}
                    {relearnIds.includes(current.id) ? (
                      <Badge tone="danger">错词回炉 · 记牢才放行</Badge>
                    ) : null}
                    <span className="v3-caption v3-study-focus__status">
                      {STATUS_LABEL[current.status] || '新词'}
                    </span>
                  </div>
                  <div className="v3-study-focus__nav">
                    {immersiveOn ? (
                      <Button
                        size="sm"
                        variant="text"
                        icon={<X size={15} />}
                        onClick={() => setImmersive(false)}
                      >
                        退出沉浸（Esc）
                      </Button>
                    ) : null}
                    <IconButton
                      label="上一个单词"
                      size="sm"
                      icon={<ChevronLeft size={17} />}
                      onClick={prevWord}
                      disabled={curIdx === 0}
                    />
                    <Badge tone="outline">
                      {curIdx + 1} / {remainingQueue.length}
                    </Badge>
                    <IconButton
                      label="下一个单词（跳过）"
                      size="sm"
                      icon={<ChevronRight size={17} />}
                      onClick={nextWord}
                      disabled={curIdx >= remainingQueue.length - 1}
                    />
                  </div>
                </div>

                <Progress
                  value={
                    remainingQueue.length
                      ? ((sessionTotal + curIdx + 1) / (sessionTotal + remainingQueue.length)) * 100
                      : 0
                  }
                  gradient
                  height={6}
                  className="v3-study-focus__progress"
                />

                {!spellMode ? (
                  <div className="v3-study-word-stage">
                    <div className="v3-study-word">
                      <h2>{current.word}</h2>
                      <IconButton
                        label="朗读单词"
                        icon={<Volume2 size={20} />}
                        onClick={() => pronounce(current.word)}
                      />
                    </div>
                    {!flashcard && current.phonetic ? (
                      <div className="v3-study-phonetic">{current.phonetic}</div>
                    ) : null}

                    {!flashcard ? (
                      <>
                        <div className="v3-study-meaning">
                          {current.pos ? <em>{current.pos}</em> : null}
                          <span>{current.meaning}</span>
                        </div>
                        {current.root ? (
                          <div className="v3-study-root">
                            <Wand size={14} /> 词根：{current.root}
                          </div>
                        ) : null}
                        {!showAns && current.example ? (
                          <div className="v3-study-example v3-study-example--cloze">
                            <span className="v3-study-example__label">
                              <Quote size={14} /> 例句填空 · 先想被遮住的词，再显示解析
                            </span>
                            <p lang="en">{maskWordInExample(current.example, current.word)}</p>
                          </div>
                        ) : null}
                        {current.extra &&
                        (current.extra.synonyms?.length || current.extra.phrases?.length) ? (
                          <div className="v3-study-example">
                            {current.extra.synonyms?.length ? (
                              <p className="v3-study-example__line">
                                <b>同近义：</b>
                                {current.extra.synonyms
                                  .map((s) => `${s.pos ? `${s.pos} ` : ''}${(s.words || []).join(' / ')}`)
                                  .filter(Boolean)
                                  .join('；')}
                              </p>
                            ) : null}
                            {current.extra.phrases?.length ? (
                              <p className="v3-study-example__line">
                                <b>短语：</b>
                                {current.extra.phrases
                                  .map((p) => `${p.phrase}${p.cn ? `（${p.cn}）` : ''}`)
                                  .join('；')}
                              </p>
                            ) : null}
                          </div>
                        ) : null}
                        {showAns && current.example ? (
                          <div className="v3-study-example">
                            <span className="v3-study-example__label">
                              <Quote size={14} /> 真题例句
                            </span>
                            <p lang="en">{current.example}</p>
                            {current.ex_cn ? <p className="v3-study-example__cn">{current.ex_cn}</p> : null}
                          </div>
                        ) : null}
                      </>
                    ) : showAns ? (
                      <div className="v3-study-meaning">
                        {current.pos ? <em>{current.pos}</em> : null}
                        <span>{current.meaning}</span>
                      </div>
                    ) : (
                      <>
                        <p className="v3-study-hidden">释义已隐藏：先读例句猜词，再点下方揭晓答案。</p>
                        {current.example ? (
                          <div className="v3-study-example v3-study-example--cloze">
                            <span className="v3-study-example__label">
                              <Quote size={14} /> 例句填空
                            </span>
                            <p lang="en">{maskWordInExample(current.example, current.word)}</p>
                          </div>
                        ) : null}
                      </>
                    )}

                    <div className="v3-study-word-meta">
                      <span>复习 {current.reps || 0} 次</span>
                      <span>间隔 {current.interval || 0} 天</span>
                      <span>EF {(Number(current.ef) || 2.5).toFixed(1)}</span>
                      <span>{STATUS_LABEL[current.status] || '新词'}</span>
                    </div>
                  </div>
                ) : (
                  <div className="v3-study-word-stage v3-study-word-stage--spell">
                    <div className="v3-study-word">
                      <h2 className="v3-spell-word">
                        {spellResult ? current.word : String(current.word || '').replace(/[^\s]/g, '•')}
                      </h2>
                      <IconButton
                        label="朗读单词"
                        icon={<Volume2 size={20} />}
                        onClick={() => pronounce(current.word)}
                      />
                    </div>
                    {current.phonetic ? <div className="v3-study-phonetic">{current.phonetic}</div> : null}
                    <div className="v3-study-meaning">
                      {current.pos ? <em>{current.pos}</em> : null}
                      <span>{current.meaning}</span>
                    </div>
                    {current.root ? (
                      <div className="v3-study-root">
                        <Wand size={14} /> 词根：{current.root}
                      </div>
                    ) : null}
                    {spellResult ? (
                      <div className={`v3-spell-result ${spellResult.correct ? 'is-correct' : 'is-wrong'}`}>
                        {spellResult.correct ? (
                          <>
                            <CheckCircle2 size={16} /> 拼写正确！已记为「记得」
                          </>
                        ) : (
                          <>
                            <EyeOff size={16} /> 拼写错误 · 正确答案：<b>{current.word}</b>
                            （已记为「忘记」，本轮稍后回炉重拼）
                          </>
                        )}
                      </div>
                    ) : null}
                    {spellResult && current.example ? (
                      <div className="v3-study-example">
                        <span className="v3-study-example__label">
                          <Quote size={14} /> 真题例句
                        </span>
                        <p lang="en">{current.example}</p>
                        {current.ex_cn ? <p className="v3-study-example__cn">{current.ex_cn}</p> : null}
                      </div>
                    ) : !spellResult ? (
                      <form className="v3-spell-form" onSubmit={submitSpell}>
                        <Input
                          className="v3-spell-input"
                          value={spellAnswer}
                          onChange={(e) => setSpellAnswer(e.target.value)}
                          placeholder="输入单词拼写后回车"
                          autoFocus
                          disabled={spellChecking}
                        />
                        <Button
                          type="submit"
                          variant="gradient"
                          disabled={spellChecking || !spellAnswer.trim()}
                        >
                          {spellChecking ? '检查中…' : '检查拼写'}
                        </Button>
                      </form>
                    ) : null}
                    <div className="v3-study-word-meta">
                      <span>复习 {current.reps || 0} 次</span>
                      <span>间隔 {current.interval || 0} 天</span>
                      <span>{STATUS_LABEL[current.status] || '新词'}</span>
                    </div>
                  </div>
                )}

                <div className="v3-study-session-mini">
                  <span>本轮 {sessionTotal} 词</span>
                  <span>正确 {sessionCorrect}</span>
                  <span>准确率 {sessionAccuracy}%</span>
                  {relearnIds.length > 0 ? (
                    <span className="v3-study-tone-danger">待回炉 {relearnIds.length}</span>
                  ) : null}
                  {sessionDuration > 0 ? <span>用时 {sessionDuration} 分钟</span> : null}
                </div>

                <div className="v3-study-actionzone">
                  {!spellMode ? (
                    !showAns ? (
                      <Button
                        variant="gradient"
                        block
                        size="lg"
                        icon={<Eye size={18} />}
                        onClick={() => setShowAns(true)}
                      >
                        显示释义
                      </Button>
                    ) : (
                      <>
                        <div className="v3-study-grades">
                          <Button
                            variant="tonal"
                            className="v3-study-grade v3-study-grade--again"
                            disabled={grading}
                            onClick={() => grade(GRADE.AGAIN)}
                          >
                            <span className="v3-study-grade__label">忘记</span>
                            <span className="v3-study-grade__hint">10 分钟后</span>
                          </Button>
                          <Button
                            variant="tonal"
                            className="v3-study-grade v3-study-grade--hard"
                            disabled={grading}
                            onClick={() => grade(GRADE.HARD)}
                          >
                            <span className="v3-study-grade__label">模糊</span>
                            <span className="v3-study-grade__hint">
                              {Math.max(1, Math.round((current.interval || 1) * 0.6))} 天后
                            </span>
                          </Button>
                          <Button
                            variant="tonal"
                            className="v3-study-grade v3-study-grade--good"
                            disabled={grading}
                            onClick={() => grade(GRADE.GOOD)}
                          >
                            <span className="v3-study-grade__label">记得</span>
                            <span className="v3-study-grade__hint">
                              {Math.round((current.interval || 1) * (current.ef || 2.5))} 天后
                            </span>
                          </Button>
                          <Button
                            variant="tonal"
                            className="v3-study-grade v3-study-grade--easy"
                            disabled={grading}
                            onClick={() => grade(GRADE.EASY)}
                          >
                            <span className="v3-study-grade__label">简单</span>
                            <span className="v3-study-grade__hint">
                              {Math.round((current.interval || 1) * (current.ef || 2.5) * 1.3)} 天后
                            </span>
                          </Button>
                        </div>
                        <p className="v3-study-keyhint">快捷键：1 = 忘记 · 2 = 模糊 · 3 = 记得 · 4 = 简单</p>
                      </>
                    )
                  ) : spellResult ? (
                    <Button
                      variant="gradient"
                      block
                      size="lg"
                      icon={<ArrowRight size={18} />}
                      onClick={nextSpell}
                    >
                      下一词
                    </Button>
                  ) : (
                    <p className="v3-study-keyhint">
                      看释义/音标输入拼写：正确自动记为「记得」，错误记为「忘记」并进入下次复习。
                    </p>
                  )}
                </div>
              </Tile>
            ) : null
          ) : null}

          {view === 'summary' ? (
            <div className="v3-bento">
              <Tile span={8} className="v3-study-summary">
                <div className="v3-study-summary__hero">
                  <span className="v3-study-summary__orb">
                    <CheckCircle2 size={30} />
                  </span>
                  <div>
                    <h2>本轮学习完成！</h2>
                    <p>继续保持，每天进步一点点。评分已按 SM-2 / FSRS 排入下一次复习。</p>
                  </div>
                </div>

                <div className="v3-study-mini-stats">
                  <div>
                    <span>学习单词</span>
                    <b>{sessionTotal}</b>
                  </div>
                  <div>
                    <span>正确率</span>
                    <b>{sessionAccuracy}%</b>
                  </div>
                  <div>
                    <span>掌握词数</span>
                    <b>{sessionCorrect}</b>
                  </div>
                  <div>
                    <span>需巩固</span>
                    <b>{sessionStats.again}</b>
                  </div>
                </div>

                <div className="v3-study-dist">
                  <div className="v3-study-dist__head">
                    <span>评分分布</span>
                    <span>{sessionTotal > 0 ? `共 ${sessionTotal} 次评分` : '还没有评分记录'}</span>
                  </div>
                  <div className="v3-study-dist__bar" aria-hidden="true">
                    {sessionTotal > 0 ? (
                      <>
                        <i
                          className="is-again"
                          style={{ width: `${(sessionStats.again / sessionTotal) * 100}%` }}
                          title={`忘记 ${sessionStats.again}`}
                        />
                        <i
                          className="is-hard"
                          style={{ width: `${(sessionStats.hard / sessionTotal) * 100}%` }}
                          title={`模糊 ${sessionStats.hard}`}
                        />
                        <i
                          className="is-good"
                          style={{ width: `${(sessionStats.good / sessionTotal) * 100}%` }}
                          title={`记得 ${sessionStats.good}`}
                        />
                        <i
                          className="is-easy"
                          style={{ width: `${(sessionStats.easy / sessionTotal) * 100}%` }}
                          title={`简单 ${sessionStats.easy}`}
                        />
                      </>
                    ) : (
                      <i className="is-empty" style={{ width: '100%' }} />
                    )}
                  </div>
                  <div className="v3-study-dist__legend">
                    <span className="is-again">忘记 {sessionStats.again}</span>
                    <span className="is-hard">模糊 {sessionStats.hard}</span>
                    <span className="is-good">记得 {sessionStats.good}</span>
                    <span className="is-easy">简单 {sessionStats.easy}</span>
                  </div>
                </div>

                {/* 错词暴露（对标扇贝错词本）：本轮「忘记/拼错」的词逐条列出，
                    标注是否已在回炉环节记牢，可一键只错词重练一轮。 */}
                <div className="v3-study-wrongwords">
                  <div className="v3-study-wrongwords__head">
                    <span>
                      <AlertTriangle size={14} /> 本轮错词 {sessionWrong.length} 个
                      {sessionWrong.length
                        ? `（${sessionWrong.filter((w) => w.passed).length} 个已回炉记牢）`
                        : ''}
                    </span>
                    {sessionWrong.length > 0 ? (
                      <Button
                        size="sm"
                        variant="tonal"
                        icon={<RotateCcw size={14} />}
                        onClick={() => startWrongRounds(sessionWrong.map((w) => w.id))}
                      >
                        只错词重练一轮
                      </Button>
                    ) : null}
                  </div>
                  {sessionWrong.length > 0 ? (
                    <ul className="v3-study-wrongwords__list">
                      {sessionWrong.map((w) => (
                        <li key={w.id}>
                          <b lang="en">{w.word}</b>
                          <span>{wrongMeaningOf(w.id) || '释义待补充'}</span>
                          <Badge tone={w.passed ? 'success' : 'danger'}>
                            {w.passed ? '已记牢' : '仍不熟'}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="v3-study-wrongwords__clean">
                      {sessionTotal > 0 ? '本轮没有错词，全部一次记起。' : '本轮还没有作答记录，暂无错词。'}
                    </p>
                  )}
                </div>

                <div className="v3-study-summary__actions">
                  <Button
                    variant="gradient"
                    icon={<RefreshCw size={16} />}
                    onClick={startSession}
                    disabled={activeQueue.length === 0}
                  >
                    再来一轮
                  </Button>
                  <Button variant="text" onClick={() => setView('list')}>
                    查看词库列表
                  </Button>
                </div>
              </Tile>

              <Tile span={4} className="v3-study-quota">
                <span className="v3-tile__label">
                  <Target size={15} /> 每日新词配额
                </span>
                <div className="v3-study-quota__value">
                  {dailyQuota}
                  <em>个/天</em>
                </div>
                <input
                  className="v3-study-range"
                  type="range"
                  min="10"
                  max="100"
                  step="5"
                  aria-label="每日新词配额"
                  value={dailyQuota}
                  onChange={(e) => saveQuota(Number(e.target.value))}
                />
                <p className="v3-study-quota__hint">
                  {planSource
                    ? `今日新词量由后端「${stats?.today_basis?.new_words || '每日计划'}」下发为 ${planNew ?? 0} 个；此处上限是本机兜底值，仅在后端计划缺失时生效。复习词不受配额限制。`
                    : '复习词不受配额限制，新词每天最多学习 ' +
                      dailyQuota +
                      ' 个。调整后立即生效并保存在本机。后端下发今日计划后，以计划为准。'}
                </p>
                <div className="v3-study-quota__stats">
                  <div>
                    <span>今日计划</span>
                    <b>{todayPlanTotal}</b>
                  </div>
                  <div>
                    <span>自由学习池</span>
                    <b>{freeQueue.length}</b>
                  </div>
                </div>
                {freeQueue.length > 0 ? (
                  <Button variant="tonal" block icon={<RotateCcw size={16} />} onClick={startFreeSession}>
                    自由学习
                  </Button>
                ) : null}
              </Tile>
            </div>
          ) : null}

          {view === 'list' ? (
            <Tile span={12} className="v3-study-panel">
              <div className="v3-study-panel__head">
                <div>
                  <h2>单词列表（{filteredWords.length}）</h2>
                  <p>搜索、按状态与词库筛选；展开行查看词根、例句与调度信息。</p>
                </div>
                <div className="v3-study-panel__actions">
                  <Input
                    icon={<Search size={15} />}
                    className="v3-study-search"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="搜索单词 / 释义 / 词根…"
                    aria-label="搜索单词"
                  />
                  <Button size="sm" variant="tonal" icon={<Plus size={15} />} onClick={openAddWord}>
                    添加
                  </Button>
                  <Button
                    size="sm"
                    variant="text"
                    icon={<Upload size={15} />}
                    onClick={() => setShowImport(true)}
                  >
                    导入
                  </Button>
                </div>
              </div>

              <div className="v3-study-filters">
                <div className="v3-study-filter-group" role="group" aria-label="按状态筛选">
                  {STATUS_FILTERS.map((f) => (
                    <Chip
                      key={f.value}
                      active={statusFilter === f.value}
                      onClick={() => setStatusFilter(f.value)}
                    >
                      {f.label}
                    </Chip>
                  ))}
                </div>
                <div className="v3-study-filter-group" role="group" aria-label="按词库筛选">
                  <Chip active={packSel === 'all'} onClick={() => setPackSel('all')}>
                    全部词库
                  </Chip>
                  {decks.map((d) => (
                    <Chip
                      key={d.id}
                      active={packSel === String(d.id)}
                      onClick={() => {
                        setPackSel(String(d.id))
                        setExpandedId(null)
                      }}
                      title={`${d.name} · ${d.count} 词`}
                    >
                      {d.name}
                    </Chip>
                  ))}
                </div>
              </div>

              {words.length === 0 ? (
                <Empty
                  icon={<BookOpen size={26} />}
                  title="还没有单词"
                  text="点击「导入」粘贴文本或上传 Excel，系统会按遗忘曲线自动排复习。"
                  action={
                    <Button
                      variant="gradient"
                      icon={<Upload size={16} />}
                      onClick={() => setShowImport(true)}
                    >
                      导入单词
                    </Button>
                  }
                />
              ) : filteredWords.length === 0 ? (
                <Empty
                  icon={<Search size={26} />}
                  title="没有匹配的单词"
                  text="换一个关键词，或把状态 / 词库筛选切回「全部」。"
                  action={
                    <Button
                      variant="tonal"
                      onClick={() => {
                        setSearchTerm('')
                        setStatusFilter('all')
                        setPackSel('all')
                      }}
                    >
                      清空筛选
                    </Button>
                  }
                />
              ) : (
                <>
                  <div className="v3-study-word-list">
                    {shownWords.map((w) => {
                      const open = expandedId === w.id
                      return (
                        <div key={w.id} className={`v3-study-word-row${open ? ' is-open' : ''}`}>
                          <div className="v3-study-word-row__top">
                            <MasteryRing level={w.reps} size={34} />
                            <button
                              type="button"
                              className="v3-study-word-row__main"
                              aria-expanded={open}
                              onClick={() => setExpandedId(open ? null : w.id)}
                            >
                              <span className="v3-study-word-row__word">
                                {w.word}
                                {w.phonetic ? <em>{w.phonetic}</em> : null}
                              </span>
                              <span className="v3-study-word-row__meaning">
                                {w.pos ? <b>{w.pos}</b> : null}
                                {w.meaning}
                              </span>
                            </button>
                            <div className="v3-study-word-row__badges">{wordBadge(w)}</div>
                            <div className="v3-study-word-row__actions">
                              <IconButton
                                label="朗读"
                                size="sm"
                                icon={<Volume2 size={15} />}
                                onClick={() => pronounce(w.word)}
                              />
                              <Button
                                size="sm"
                                variant="text"
                                className="v3-study-grade-text is-again"
                                onClick={() => gradeWord(w.id, GRADE.AGAIN)}
                              >
                                忘
                              </Button>
                              <Button
                                size="sm"
                                variant="text"
                                className="v3-study-grade-text is-hard"
                                onClick={() => gradeWord(w.id, GRADE.HARD)}
                              >
                                难
                              </Button>
                              <Button
                                size="sm"
                                variant="text"
                                className="v3-study-grade-text is-good"
                                onClick={() => gradeWord(w.id, GRADE.GOOD)}
                              >
                                良
                              </Button>
                              <Button
                                size="sm"
                                variant="tonal"
                                className="v3-study-grade-text is-easy"
                                onClick={() => gradeWord(w.id, GRADE.EASY)}
                              >
                                易
                              </Button>
                              <IconButton
                                label="删除单词"
                                size="sm"
                                icon={<Trash size={15} />}
                                onClick={() => handleRemoveWord(w.id)}
                              />
                              <IconButton
                                label={open ? '收起详情' : '展开详情'}
                                size="sm"
                                className={open ? 'is-open' : ''}
                                icon={<ChevronDown size={15} />}
                                onClick={() => setExpandedId(open ? null : w.id)}
                              />
                            </div>
                          </div>
                          {open ? (
                            <div className="v3-study-word-row__details">
                              <div>
                                <span>音标</span>
                                <b>{w.phonetic || '—'}</b>
                              </div>
                              <div>
                                <span>词性</span>
                                <b>{w.pos || '—'}</b>
                              </div>
                              <div>
                                <span>复习次数</span>
                                <b>{w.reps || 0}</b>
                              </div>
                              <div>
                                <span>复习间隔</span>
                                <b>{w.interval || 0} 天</b>
                              </div>
                              <div>
                                <span>EF</span>
                                <b>{(Number(w.ef) || 2.5).toFixed(1)}</b>
                              </div>
                              <div>
                                <span>下次复习</span>
                                <b>{w.due ? fmtDateCN(w.due) : '—'}</b>
                              </div>
                              <div>
                                <span>状态</span>
                                <b>{STATUS_LABEL[w.status] || '新词'}</b>
                              </div>
                              <div>
                                <span>上次复习</span>
                                <b>{w.lastReview ? fmtDateCN(String(w.lastReview).slice(0, 10)) : '—'}</b>
                              </div>
                              {w.root ? (
                                <div className="is-wide">
                                  <span>词根</span>
                                  <b>{w.root}</b>
                                </div>
                              ) : null}
                              {w.extra && (w.extra.synonyms?.length || w.extra.phrases?.length) ? (
                                <div className="is-wide">
                                  {w.extra.synonyms?.length ? (
                                    <p className="v3-study-example">
                                      <b>同近义：</b>
                                      {w.extra.synonyms
                                        .map(
                                          (s) => `${s.pos ? `${s.pos} ` : ''}${(s.words || []).join(' / ')}`,
                                        )
                                        .filter(Boolean)
                                        .join('；')}
                                    </p>
                                  ) : null}
                                  {w.extra.phrases?.length ? (
                                    <p className="v3-study-example">
                                      <b>短语：</b>
                                      {w.extra.phrases
                                        .map((p) => `${p.phrase}${p.cn ? `（${p.cn}）` : ''}`)
                                        .join('；')}
                                    </p>
                                  ) : null}
                                </div>
                              ) : null}
                              {w.example ? (
                                <div className="is-wide">
                                  <span>真题例句</span>
                                  <p lang="en">{w.example}</p>
                                  {w.ex_cn ? <p className="v3-study-example__cn">{w.ex_cn}</p> : null}
                                </div>
                              ) : null}
                              {w.tag ? (
                                <div>
                                  <span>标签</span>
                                  <b>{w.tag}</b>
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                  {filteredWords.length > LIST_LIMIT ? (
                    <p className="v3-study-list-more">
                      仅显示前 {LIST_LIMIT} 个，共 {filteredWords.length} 个单词。用搜索或筛选缩小范围。
                    </p>
                  ) : null}
                </>
              )}
            </Tile>
          ) : null}

          {view === 'decks' ? (
            <Tile span={12} className="v3-study-panel">
              <div className="v3-study-panel__head">
                <div>
                  <h2>词库管理</h2>
                  <p>选择词库用于导入目标与列表筛选；复习队列仍按到期顺序推进。</p>
                </div>
                <Badge tone="outline">{decks.length} 个词库</Badge>
              </div>

              {decks.length === 0 ? (
                <Empty
                  icon={<Library size={26} />}
                  title="还没有词库"
                  text="在下方输入新词库名称并创建，或从后端同步默认词库。"
                />
              ) : (
                <div className="v3-study-deck-grid">
                  {decks.map((d, i) => (
                    <div
                      key={d.id}
                      role="button"
                      tabIndex={0}
                      className={`v3-study-deck tone-${i % 5}${packSel === String(d.id) ? ' is-selected' : ''}`}
                      onClick={() => {
                        setPackSel(String(d.id))
                        setView('learn')
                        toast(`已切换到词库：${d.name}`)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          setPackSel(String(d.id))
                          setView('learn')
                          toast(`已切换到词库：${d.name}`)
                        }
                      }}
                    >
                      <div className="v3-study-deck__top">
                        <span className="v3-study-deck__glyph">
                          <BookOpen size={18} />
                        </span>
                        <Badge tone={packSel === String(d.id) ? 'primary' : 'outline'}>{d.count} 词</Badge>
                      </div>
                      <strong className="v3-study-deck__name">{d.name}</strong>
                      <span className="v3-study-deck__meta">
                        {d.source || '后端'}
                        {d.description ? ` · ${d.description}` : ''}
                      </span>
                      <span className="v3-study-deck__go">
                        进入学习 <ArrowRight size={14} />
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <div className="v3-study-deck-create">
                <Input
                  value={deckName}
                  onChange={(e) => setDeckName(e.target.value)}
                  placeholder="新词库名称（如：红宝书 Unit1）"
                  aria-label="新词库名称"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') addNewDeck()
                  }}
                />
                <Button
                  variant="gradient"
                  icon={<Plus size={16} />}
                  loading={creatingDeck}
                  onClick={addNewDeck}
                >
                  创建词库
                </Button>
              </div>
            </Tile>
          ) : null}
        </>
      )}

      <Dialog
        open={showImport}
        title="批量导入单词"
        sub="文本粘贴或 Excel 上传 · 解析后按遗忘曲线自动排期"
        onClose={() => {
          setShowImport(false)
          setImportResult(null)
          setExcelFile(null)
        }}
      >
        <div className="v3-study-dialog">
          <Field label="导入到词库">
            <Select value={packSel === 'all' ? 'core' : packSel} onChange={(e) => setPackSel(e.target.value)}>
              <option value="core">默认词库</option>
              {decks.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}（{d.count} 个）
                </option>
              ))}
            </Select>
          </Field>

          <section className="v3-study-import-block">
            <div className="v3-study-import-block__head">
              <span>文本粘贴</span>
              <em>每行一个单词</em>
            </div>
            <p className="v3-study-import-block__hint">
              支持格式：<code>apple 苹果</code>、<code>apple n. 苹果</code>、<code>apple /ˈæpl/ n. 苹果</code>
            </p>
            <Textarea
              rows={6}
              aria-label="批量导入文本"
              placeholder={
                'abandon 放弃；抛弃\nabnormal /æbˈnɔːml/ adj. 反常的\nacademic n. 学者；adj. 学术的'
              }
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
            />
            <div className="v3-study-import-block__actions">
              <Button variant="gradient" onClick={handleImport} disabled={importing || !importText.trim()}>
                {importing ? '导入中…' : '开始文本导入'}
              </Button>
              <Button variant="tonal" onClick={handleImportBuiltin} disabled={importing}>
                导入内置核心词表（{CORE_WORDS.length} 词）
              </Button>
            </div>
          </section>

          <section className="v3-study-import-block">
            <div className="v3-study-import-block__head">
              <span>Excel 文件上传</span>
              <em>.xlsx / .xls</em>
            </div>
            <p className="v3-study-import-block__hint">
              必须包含列：<b>单词</b>、<b>释义</b>；可选列：音标、词性、词根、例句、例句翻译、标签。
            </p>
            <input
              className="v3-study-file"
              type="file"
              accept=".xlsx,.xls"
              aria-label="上传 Excel 单词文件"
              onChange={(e) => setExcelFile(e.target.files?.[0] || null)}
            />
            {excelFile ? <p className="v3-study-file__name">已选择：{excelFile.name}</p> : null}
            <div className="v3-study-import-block__actions">
              <Button variant="gradient" onClick={handleExcelImport} disabled={importing || !excelFile}>
                {importing ? '导入中…' : '开始 Excel 导入'}
              </Button>
            </div>
          </section>

          {importResult ? (
            <section className="v3-study-import-result" aria-live="polite">
              <div className="v3-study-import-result__head">导入结果</div>
              <div className="v3-study-import-result__grid">
                <div className="is-success">
                  <b>{importResult.imported ?? 0}</b>
                  <span>成功导入</span>
                </div>
                <div className="is-warning">
                  <b>{importResult.skipped ?? 0}</b>
                  <span>跳过（重复 / 无效）</span>
                </div>
              </div>
            </section>
          ) : null}
        </div>
      </Dialog>

      <Dialog
        open={showAddWord}
        title="添加单词"
        sub="保存后立即排入复习队列"
        onClose={() => {
          setShowAddWord(false)
          setWordErr('')
        }}
        footer={
          <>
            <Button variant="text" onClick={() => setShowAddWord(false)}>
              取消
            </Button>
            <Button variant="gradient" loading={savingWord} onClick={submitWord}>
              保存单词
            </Button>
          </>
        }
      >
        <div className="v3-study-dialog">
          {wordErr ? <Alert tone="danger">{wordErr}</Alert> : null}
          <div className="v3-study-form-grid">
            <Field label="单词" className="v3-study-field--wide">
              <Input
                value={wordForm.word}
                onChange={(e) => setWordForm({ ...wordForm, word: e.target.value })}
                placeholder="如：abandon"
              />
            </Field>
            <Field label="释义" className="v3-study-field--wide">
              <Input
                value={wordForm.meaning}
                onChange={(e) => setWordForm({ ...wordForm, meaning: e.target.value })}
                placeholder="如：放弃；抛弃"
              />
            </Field>
            <Field label="音标">
              <Input
                value={wordForm.phonetic}
                onChange={(e) => setWordForm({ ...wordForm, phonetic: e.target.value })}
                placeholder="/əˈbændən/"
              />
            </Field>
            <Field label="词性">
              <Input
                value={wordForm.pos}
                onChange={(e) => setWordForm({ ...wordForm, pos: e.target.value })}
                placeholder="v. / n. / adj."
              />
            </Field>
            <Field label="词根（可选）" className="v3-study-field--wide">
              <Input
                value={wordForm.root}
                onChange={(e) => setWordForm({ ...wordForm, root: e.target.value })}
                placeholder="词根词缀或助记"
              />
            </Field>
            <Field label="例句（可选）" className="v3-study-field--wide">
              <Textarea
                rows={2}
                value={wordForm.example}
                onChange={(e) => setWordForm({ ...wordForm, example: e.target.value })}
                placeholder="英文例句"
              />
            </Field>
            <Field label="例句翻译（可选）" className="v3-study-field--wide">
              <Input
                value={wordForm.exCn}
                onChange={(e) => setWordForm({ ...wordForm, exCn: e.target.value })}
                placeholder="例句中文翻译"
              />
            </Field>
            <Field label="标签（可选）">
              <Input
                value={wordForm.tag}
                onChange={(e) => setWordForm({ ...wordForm, tag: e.target.value })}
                placeholder="如：高频"
              />
            </Field>
            <Field label="所属词库">
              <Select
                value={wordForm.deckId}
                onChange={(e) => setWordForm({ ...wordForm, deckId: e.target.value })}
              >
                <option value="core">默认词库</option>
                {decks.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
