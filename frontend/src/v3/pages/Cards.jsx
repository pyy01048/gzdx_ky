import React, { useCallback, useEffect, useMemo, useState } from 'react'
import useStore from '../../store/useStore'
import { dueCards, GRADE, CARD_STATUS } from '../../utils/spaced'
import { todayStr } from '../../utils/date'
import { noteToCard } from '../../utils/words'
import { flashcardsApi, fetchAllPages } from '../../api/client'
import { fetchSubjectNames } from '../../api/subjects'
import {
  Alert, AnimatedNumber, Badge, Button, Chip, Dialog, Empty, Field, IconButton,
  Input, PageHeader, Progress, Ring, Segmented, Select, Skeleton, Textarea, Tile,
  toast, toastErr, toastOk, toastWarn,
} from '../ui'
import {
  AlertCircle, Book, BookOpen, CheckCircle2, ChevronLeft, ChevronRight, Clock,
  Eye, Layers, List, Play, Plus, Quote, RefreshCw, Search, Target, Trash, Wand,
} from '../icons'
import '../styles/study-pages.css'
import '../styles/study-glass.css'

/* 后端 Flashcard.mastery（review_scheduler 写入）→ 前端 SM-2 状态。
   注意：后端使用 new/learning/review/mastered，前端 CARD_STATUS 用 reviewing。 */
const BACKEND_MASTERY_TO_STATUS = {
  new: CARD_STATUS.NEW,
  learning: CARD_STATUS.LEARNING,
  review: CARD_STATUS.REVIEWING,
  mastered: CARD_STATUS.MASTERED,
}

const CARD_STATUS_LABEL = {
  [CARD_STATUS.NEW]: '新卡',
  [CARD_STATUS.LEARNING]: '学习中',
  [CARD_STATUS.REVIEWING]: '复习中',
  [CARD_STATUS.MASTERED]: '已掌握',
}

const STATUS_TONE = {
  [CARD_STATUS.NEW]: 'outline',
  [CARD_STATUS.LEARNING]: 'warning',
  [CARD_STATUS.REVIEWING]: 'primary',
  [CARD_STATUS.MASTERED]: 'success',
}

const STATUS_FILTERS = [
  { value: 'all', label: '全部' },
  { value: CARD_STATUS.NEW, label: '新卡' },
  { value: CARD_STATUS.LEARNING, label: '学习中' },
  { value: CARD_STATUS.REVIEWING, label: '复习中' },
  { value: CARD_STATUS.MASTERED, label: '已掌握' },
]

const sideText = (val) => (typeof val === 'string' ? val : (val?.text || ''))

function CardStatusTag({ status }) {
  const s = status || CARD_STATUS.NEW
  return (
    <Badge tone={STATUS_TONE[s] || 'outline'} className="v3-study-status">
      {CARD_STATUS_LABEL[s] || s}
    </Badge>
  )
}

/* 渲染卡片正/反面：若含 media 字段则渲染图片/音频 */
function renderSide(val) {
  if (val && typeof val === 'object' && val.media) {
    const m = val.media
    return (
      <div className="v3-study-flip__media">
        {val.text ? <p>{val.text}</p> : null}
        {m.type === 'image' ? <img src={m.url} alt="" /> : null}
        {m.type === 'audio' ? <audio controls src={m.url} /> : null}
      </div>
    )
  }
  return <p className="v3-study-flip__text">{sideText(val)}</p>
}

export default function Cards() {
  /* 字段级选择器：store 其他字段变化不触发整页重渲染 */
  const cards = useStore((s) => s.cards)
  const packs = useStore((s) => s.packs)
  const notebook = useStore((s) => s.notebook)
  const addCard = useStore((s) => s.addCard)
  const addPack = useStore((s) => s.addPack)
  const reviewCard = useStore((s) => s.reviewCard)
  const removeCard = useStore((s) => s.removeCard)
  const removePack = useStore((s) => s.removePack)
  const setCards = useStore((s) => s.setCards)

  const [view, setView] = useState('study') // study | summary | packs | list
  const [curIdx, setCurIdx] = useState(0)
  const [showBack, setShowBack] = useState(false)
  const [flipped, setFlipped] = useState(false)
  const [packId, setPackId] = useState('all')
  const [showAddPack, setShowAddPack] = useState(false)
  const [packName, setPackName] = useState('')
  const [packSubject, setPackSubject] = useState('')
  const [subjects, setSubjects] = useState([])
  const [showFromNote, setShowFromNote] = useState(false)
  const [showAddCard, setShowAddCard] = useState(false)
  const [form, setForm] = useState({ packId: '', front: '', back: '', hint: '' })
  const [cardErr, setCardErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  const [sessionStats, setSessionStats] = useState({
    again: 0, hard: 0, good: 0, easy: 0, startTime: null, cards: [],
  })
  const [reviewedIds, setReviewedIds] = useState([])
  const [grading, setGrading] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  const today = todayStr()

  /* 科目清单：唯一来源 /api/taxonomy/subjects，不硬编码科目名 */
  useEffect(() => {
    let alive = true
    fetchSubjectNames()
      .then((names) => {
        if (!alive) return
        setSubjects(names)
        setPackSubject((prev) => prev || names[0] || '')
      })
      .catch(() => { if (alive) setSubjects([]) })
    return () => { alive = false }
  }, [])

  /* 逐页拉全量卡片（后端 page_size 上限 200），失败不静默复用本机数据 */
  useEffect(() => {
    let alive = true
    const loadData = async () => {
      setLoading(true)
      setLoadErr('')
      try {
        const rows = await fetchAllPages((p) => flashcardsApi.list(p), { keys: ['cards'] })
        if (!alive) return
        const formatted = rows.map((c) => ({
          id: c.id,
          front: c.front,
          back: c.back,
          hint: c.hint || '',
          knowledgePointId: c.knowledge_point_id ?? null,
          packId: c.deck_id ? String(c.deck_id) : 'default',
          status: BACKEND_MASTERY_TO_STATUS[c.mastery] || CARD_STATUS.NEW,
          mastery: c.mastery || 'new',
          ef: c.ease_factor || 2.5,
          interval: c.interval || 0,
          reps: c.review_count || 0,
          due: c.next_review ? String(c.next_review).slice(0, 10) : null,
          lastReview: c.last_review || null,
          tags: c.tags || [],
        }))
        setCards(formatted)
      } catch (err) {
        if (alive) setLoadErr(err?.message || '未知错误')
      } finally {
        if (alive) setLoading(false)
      }
    }
    loadData()
    return () => { alive = false }
  }, [reloadKey, setCards])

  const scope = useMemo(
    () => (packId === 'all' ? cards : cards.filter((c) => c.packId === packId)),
    [cards, packId],
  )
  const due = useMemo(() => dueCards(scope, today), [scope, today])
  const queue = useMemo(() => {
    const inProgress = due.filter((c) => c.status !== CARD_STATUS.NEW)
    const fresh = due.filter((c) => c.status === CARD_STATUS.NEW)
    return [...inProgress, ...fresh]
  }, [due])

  /* 本次会话已评分的卡不再出现：评分后 due 可能当天仍到期（重学），
     但同一轮里不应立刻重复；队列缩短也不会导致索引跳过下一张。 */
  const remaining = useMemo(
    () => queue.filter((c) => !reviewedIds.includes(c.id)),
    [queue, reviewedIds],
  )
  const current = remaining[curIdx] || null
  const mastered = cards.filter((c) => c.status === CARD_STATUS.MASTERED).length
  const active = cards.length - mastered

  const nextDue = useMemo(() => {
    const future = cards.filter((c) => c.status !== CARD_STATUS.MASTERED && c.due && c.due > today)
    if (future.length === 0) return null
    return future.reduce((m, c) => (c.due < m ? c.due : m), future[0].due)
  }, [cards, today])

  const packStats = useMemo(() => packs.map((p) => {
    const inPack = cards.filter((c) => c.packId === p.id)
    const m = inPack.filter((c) => c.status === CARD_STATUS.MASTERED).length
    const avgInterval = inPack.length
      ? Math.round(inPack.reduce((a, c) => a + (c.interval || 0), 0) / inPack.length)
      : 0
    return {
      ...p,
      total: inPack.length,
      mastered: m,
      ratio: inPack.length ? Math.round((m / inPack.length) * 100) : 0,
      avgInterval,
    }
  }), [packs, cards])

  const listFiltered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return scope.filter((c) => {
      if (statusFilter !== 'all' && c.status !== statusFilter) return false
      if (!q) return true
      return [sideText(c.front), sideText(c.back), c.hint, ...(c.tags || [])]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    })
  }, [scope, search, statusFilter])

  const sessionTotal = sessionStats.again + sessionStats.hard + sessionStats.good + sessionStats.easy
  const sessionCorrect = sessionStats.good + sessionStats.easy
  const sessionAccuracy = sessionTotal > 0 ? Math.round((sessionCorrect / sessionTotal) * 100) : 0
  const masteryPct = cards.length ? Math.round((mastered / cards.length) * 100) : 0
  const todayPct = cards.length === 0
    ? 0
    : remaining.length === 0
      ? 100
      : Math.min(100, Math.round((sessionTotal / (sessionTotal + remaining.length)) * 100))

  const refresh = useCallback(() => {
    setReloadKey((k) => k + 1)
  }, [])

  const startSession = useCallback(() => {
    setSessionStats({ again: 0, hard: 0, good: 0, easy: 0, startTime: Date.now(), cards: [] })
    setReviewedIds([])
    setCurIdx(0)
    setShowBack(false)
    setFlipped(false)
    setView('study')
  }, [])

  const grade = async (g) => {
    if (!current || grading) return
    setGrading(true)
    const gradeKey = g === GRADE.AGAIN ? 'again' : g === GRADE.HARD ? 'hard' : g === GRADE.GOOD ? 'good' : 'easy'
    setSessionStats((prev) => ({
      ...prev,
      [gradeKey]: prev[gradeKey] + 1,
      cards: [
        ...prev.cards,
        { id: current.id, front: sideText(current.front), grade: gradeKey },
      ],
    }))
    /* 后端 FlashcardReview 只接受 quality（0-5 必填）；失败必须让用户看见 */
    try {
      await flashcardsApi.review(current.id, { quality: g })
    } catch (err) {
      toastErr(`复习记录同步失败：${err?.message || '未知错误'}（本地进度已保存）`)
    } finally {
      reviewCard(current.id, g)
      setReviewedIds((prev) => (prev.includes(current.id) ? prev : [...prev, current.id]))
      setShowBack(false)
      setFlipped(false)
      /* 当前卡从 remaining 中移除后，下一张会落到同一索引，无需 +1 */
      if (curIdx + 1 >= remaining.length) setView('summary')
      setGrading(false)
    }
  }

  const prevCard = () => {
    if (curIdx > 0) {
      setCurIdx(curIdx - 1)
      setShowBack(false)
      setFlipped(false)
    }
  }

  /* 不评分，直接跳过到下一张 */
  const nextCard = () => {
    if (curIdx + 1 < remaining.length) {
      setCurIdx(curIdx + 1)
      setShowBack(false)
      setFlipped(false)
    }
  }

  const flipCard = () => {
    setFlipped((v) => !v)
    setShowBack((v) => !v)
  }

  /* 显示答案后支持 1-4 快捷键评分（与页面提示一致） */
  useEffect(() => {
    if (view !== 'study' || !showBack) return undefined
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
    // grade 的依赖状态在切卡时都会变化，这里只需在阶段/卡片变化时重绑。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, showBack, current?.id, curIdx, remaining.length, grading])

  const openAddCard = () => {
    setCardErr('')
    setShowAddCard(true)
  }

  const createPack = () => {
    if (!packName.trim()) {
      toastWarn('请输入卡包名称')
      return
    }
    if (!packSubject) {
      toastWarn('请选择科目')
      return
    }
    addPack(packName.trim(), packSubject, 0)
    toastOk('卡包已创建')
    setPackName('')
    setShowAddPack(false)
  }

  const noteToCardNow = async (note) => {
    const pack = packs[0]
    if (!pack) {
      toastWarn('请先创建卡包')
      return
    }
    const newCard = { ...noteToCard(note), packId: pack.id }
    addCard(newCard)
    try {
      await flashcardsApi.create({
        front: newCard.front,
        back: newCard.back,
        hint: newCard.hint,
        deck_id: pack.id,
      })
    } catch (err) {
      toastErr(`卡片同步到后端失败：${err?.message || '未知错误'}（仅保存在本机）`)
    }
    toastOk('已生成记忆卡片')
    setShowFromNote(false)
  }

  const createCard = async () => {
    if (!form.packId) {
      setCardErr(packs.length ? '请先选择卡包' : '还没有卡包：请先新建一个卡包再添加卡片')
      return
    }
    if (!form.front.trim() || !form.back.trim()) {
      setCardErr('请补全卡片正面与背面的内容')
      return
    }
    setCardErr('')
    const newCard = { ...form, packId: form.packId }
    addCard(newCard)
    try {
      await flashcardsApi.create({
        front: newCard.front,
        back: newCard.back,
        hint: newCard.hint,
        deck_id: form.packId,
      })
    } catch (err) {
      toastErr(`卡片同步到后端失败：${err?.message || '未知错误'}（仅保存在本机）`)
    }
    toastOk('卡片已添加')
    setForm({ packId: '', front: '', back: '', hint: '' })
    setShowAddCard(false)
  }

  const handleRemoveCard = async (id) => {
    try {
      await flashcardsApi.remove(id)
    } catch (err) {
      toastErr(`删除同步失败：${err?.message || '未知错误'}（本机已删除，刷新后可能复现）`)
    }
    removeCard(id)
    toastOk('卡片已删除')
  }

  const handleRemovePack = (pack) => {
    removePack(pack.id)
    if (packId === pack.id) setPackId('all')
    toastOk('卡包已删除')
  }

  const selectPack = (id) => {
    if (id !== packId) {
      setSessionStats({ again: 0, hard: 0, good: 0, easy: 0, startTime: null, cards: [] })
    }
    setPackId(id)
    setReviewedIds([])
    setCurIdx(0)
    setShowBack(false)
    setFlipped(false)
  }

  const openPackStudy = (pack) => {
    selectPack(pack.id)
    setView('study')
    toast(`已切换到卡包：${pack.name}`)
  }

  const packNameOf = (id) => packs.find((p) => p.id === id)?.name || '卡片'

  const renderLoading = () => (
    <div className="v3-bento">
      {Array.from({ length: 4 }).map((_, i) => (
        <Tile span={3} key={i} className="v3-study-skeleton-tile"><Skeleton height={64} /></Tile>
      ))}
      <Tile span={8}><Skeleton height={250} /></Tile>
      <Tile span={4}><Skeleton height={250} /></Tile>
    </div>
  )

  return (
    <div className="v3-stack v3-study v3-glasspage">
      <PageHeader
        eyebrow="CARDS · FSRS 间隔重复"
        title="记忆卡片"
        sub={`共 ${cards.length} 张卡片 · 今日到期 ${due.length} 张 · 已掌握 ${mastered} 张 · ${packs.length} 个卡包`}
        actions={(
          <>
            <IconButton label="刷新卡片数据" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading} />
            <Button variant="text" icon={<Quote size={16} />} onClick={() => setShowFromNote(true)}>错题转卡片</Button>
            <Button variant="tonal" icon={<Plus size={16} />} onClick={openAddCard}>新建卡片</Button>
            <Button variant="gradient" icon={<Layers size={16} />} onClick={() => setShowAddPack(true)}>新建卡包</Button>
          </>
        )}
      />

      {loading && cards.length === 0 && !loadErr ? renderLoading() : loadErr && cards.length === 0 ? (
        <Tile span={12}>
          <Empty
            icon={<AlertCircle size={26} />}
            title="卡片加载失败"
            text={`后端接口请求失败：${loadErr}`}
            action={<Button variant="tonal" onClick={refresh}>重新加载</Button>}
          />
        </Tile>
      ) : (
        <>
          {loadErr ? (
            <Alert tone="danger" className="v3-study-alert">
              <div className="v3-study-alert__inner">
                <span>刷新失败，当前展示的是上次加载的数据：{loadErr}</span>
                <Button size="sm" variant="text" onClick={refresh}>重试</Button>
              </div>
            </Alert>
          ) : null}

          <div className="v3-bento">
            <Tile span={3} className="v3-study-stat">
              <span className="v3-tile__label"><Book size={15} /> 卡片总数</span>
              <span className="v3-tile__value">
                <AnimatedNumber value={cards.length} />
                <em>张</em>
              </span>
              <span className="v3-tile__hint">全部卡包累计卡片</span>
            </Tile>
            <Tile span={3} className="v3-study-stat">
              <span className="v3-tile__label"><Target size={15} /> 今日待复习</span>
              <span className="v3-tile__value v3-study-tone-danger">
                {due.length}
                <em>张</em>
              </span>
              <span className="v3-tile__hint">{packId === 'all' ? '全部卡包到期卡片' : '当前卡包到期卡片'}</span>
            </Tile>
            <Tile span={3} className="v3-study-stat">
              <span className="v3-tile__label"><Clock size={15} /> 进行中</span>
              <span className="v3-tile__value v3-study-tone-warning">
                {active}
                <em>张</em>
              </span>
              <span className="v3-tile__hint">未标记为已掌握的卡片</span>
            </Tile>
            <Tile span={3} className="v3-study-stat">
              <span className="v3-tile__label"><CheckCircle2 size={15} /> 已掌握</span>
              <span className="v3-tile__value v3-study-tone-success">
                {mastered}
                <em>张</em>
              </span>
              <span className="v3-tile__hint">整体掌握度 {masteryPct}%</span>
            </Tile>

            <Tile span={8} variant="hero" className="v3-study-hero">
              <div className="v3-study-hero__body">
                <div className="v3-study-hero__ring">
                  <Ring value={todayPct} size={136} stroke={11} gradient>
                    <div className="v3-study-ring-center">
                      <strong>{todayPct}%</strong>
                      <span>今日进度</span>
                      <em>{queue.length === 0 && sessionTotal === 0 ? '今日无到期' : `${sessionTotal} 张已评分`}</em>
                    </div>
                  </Ring>
                </div>
                <div className="v3-study-hero__copy">
                  <span className="v3-eyebrow v3-study-hero__eyebrow">
                    <Layers size={14} data-idle="breathe" /> 间隔重复
                  </span>
                  <h2>
                    {cards.length === 0
                      ? (packs.length === 0
                        ? '先建一个卡包，再把知识点做成卡片。'
                        : '卡包已就位，往里放第一张卡片。')
                      : remaining.length === 0
                        ? (queue.length > 0 ? '本轮复习已经完成。' : '今天的到期卡片已经清空。')
                        : '到期卡片优先，按记忆强度评分。'}
                  </h2>
                  <p>
                    {cards.length === 0
                      ? (packs.length === 0
                        ? '卡包按科目或专题组织卡片，正反面、提示和错题都能变成复习素材。'
                        : '新建卡片或从错题本一键转换；每张卡都会按 SM-2 / FSRS 排入复习。')
                      : remaining.length === 0
                        ? (queue.length > 0
                          ? `本次已评 ${sessionTotal} 张，仍有 ${queue.length} 张重学卡留在今日队列，可点「再来一轮」继续。`
                          : `当前范围共 ${scope.length} 张卡片，没有今天到期的项目。${nextDue ? `最早下次复习在 ${nextDue}。` : '所有卡片都已掌握。'}`)
                        : `当前范围剩余 ${remaining.length} 张待复习，新卡排在队尾；四档评分决定下一次间隔。`}
                  </p>
                  <div className="v3-study-hero__meta">
                    <span><Target size={14} /> 到期 {due.length}</span>
                    <span><Clock size={14} /> 进行中 {active}</span>
                    <span><CheckCircle2 size={14} /> 已掌握 {mastered}</span>
                  </div>
                  <div className="v3-study-hero__actions">
                    {cards.length === 0 ? (
                      packs.length === 0 ? (
                        <Button variant="gradient" icon={<Plus size={16} />} onClick={() => setShowAddPack(true)}>
                          创建第一个卡包
                        </Button>
                      ) : (
                        <>
                          <Button variant="gradient" icon={<Plus size={16} />} onClick={openAddCard}>新建卡片</Button>
                          <Button variant="text" onClick={() => setShowFromNote(true)}>错题转卡片</Button>
                        </>
                      )
                    ) : remaining.length > 0 ? (
                      <Button variant="gradient" icon={<Play size={16} />} onClick={startSession}>
                        {sessionTotal > 0 ? '继续今日复习' : '开始今日复习'}
                      </Button>
                    ) : (
                      <>
                        {queue.length > 0 ? (
                          <Button variant="gradient" icon={<RefreshCw size={16} />} onClick={startSession}>
                            再来一轮
                          </Button>
                        ) : null}
                        <Button variant="tonal" icon={<List size={16} />} onClick={() => setView('list')}>
                          浏览卡片列表
                        </Button>
                      </>
                    )}
                    {packs.length > 0 ? (
                      <Button variant="text" onClick={() => setView('packs')}>卡包管理</Button>
                    ) : null}
                  </div>
                </div>
              </div>
            </Tile>

            <Tile span={4} className="v3-study-side">
              <div className="v3-study-side__head">
                <div>
                  <span className="v3-tile__label"><Layers size={15} /> 卡组掌握</span>
                  <strong className="v3-study-side__pct">{masteryPct}%</strong>
                </div>
                <Badge tone="outline">{cards.length} 张</Badge>
              </div>
              <Progress value={masteryPct} gradient height={8} />
              <div className="v3-study-kv">
                <div><span>到期</span><b>{due.length}</b></div>
                <div><span>进行中</span><b>{active}</b></div>
                <div><span>已掌握</span><b>{mastered}</b></div>
              </div>
              <div className="v3-study-side__note">
                <Clock size={14} />
                <span>{nextDue ? `最早下次复习：${nextDue}` : '暂无排期中的复习卡'}</span>
              </div>
              <div className="v3-study-side__note">
                <Book size={14} />
                <span>{packs.length ? `${packs.length} 个卡包可用` : '尚未创建卡包'}</span>
              </div>
            </Tile>
          </div>

          <div className="v3-study-toolbar">
            <Segmented
              ariaLabel="记忆卡片视图"
              value={view}
              onChange={setView}
              options={[
                { value: 'study', label: '复习', icon: <Play size={14} /> },
                { value: 'summary', label: '总结', icon: <Target size={14} /> },
                { value: 'packs', label: '卡包', icon: <Layers size={14} /> },
                { value: 'list', label: '列表', icon: <List size={14} /> },
              ]}
            />
            <div className="v3-study-toolbar__end">
              <Badge tone={remaining.length ? 'warning' : 'success'}>
                {remaining.length ? `待复习 ${remaining.length}` : (queue.length ? '本轮已清空' : '今日已清空')}
              </Badge>
              <Badge tone="outline">{loading ? '同步中…' : `${cards.length} 张已载入`}</Badge>
            </div>
          </div>

          {packs.length > 0 ? (
            <div className="v3-study-filters">
              <div className="v3-study-filter-group" role="group" aria-label="按卡包筛选">
                <Chip active={packId === 'all'} onClick={() => selectPack('all')}>全部卡组</Chip>
                {packs.map((p) => (
                  <Chip
                    key={p.id}
                    active={packId === p.id}
                    onClick={() => selectPack(p.id)}
                    title={`${p.name}${p.subject ? ` · ${p.subject}` : ''}`}
                  >
                    {p.name}
                  </Chip>
                ))}
              </div>
            </div>
          ) : null}

          {view === 'study' ? (
            cards.length === 0 ? (
              packs.length === 0 ? (
                <Tile span={12} className="v3-study-empty">
                  <Empty
                    icon={<Layers size={26} />}
                    title="还没有卡包"
                    text="创建一个卡包，开始添加记忆卡片，使用 SM-2 / FSRS 间隔重复高效记忆。"
                    action={<Button variant="gradient" icon={<Plus size={16} />} onClick={() => setShowAddPack(true)}>创建第一个卡包</Button>}
                  />
                </Tile>
              ) : (
                <Tile span={12} className="v3-study-empty">
                  <Empty
                    icon={<BookOpen size={26} />}
                    title="还没有卡片"
                    text="添加记忆卡片，或从错题本一键转卡片；每张卡都会自动排入复习。"
                    action={(
                      <div className="v3-row v3-study-empty__actions">
                        <Button variant="gradient" icon={<Plus size={16} />} onClick={openAddCard}>新建卡片</Button>
                        <Button variant="tonal" onClick={() => setShowFromNote(true)}>错题转卡片</Button>
                      </div>
                    )}
                  />
                </Tile>
              )
            ) : scope.length === 0 ? (
              <Tile span={12} className="v3-study-empty">
                <Empty
                  icon={<Layers size={26} />}
                  title="这个卡包还没有卡片"
                  text="当前筛选范围没有卡片。切回全部卡组，或往这个卡包里添加卡片。"
                  action={(
                    <div className="v3-row v3-study-empty__actions">
                      <Button variant="tonal" onClick={() => selectPack('all')}>查看全部卡组</Button>
                      <Button variant="gradient" icon={<Plus size={16} />} onClick={openAddCard}>新建卡片</Button>
                    </div>
                  )}
                />
              </Tile>
            ) : remaining.length === 0 || !current ? (
              <Tile span={12} className="v3-study-empty">
                <Empty
                  icon={<CheckCircle2 size={26} />}
                  title="本次复习完成"
                  text={queue.length > 0
                    ? `本次已评 ${sessionTotal} 张，仍有 ${queue.length} 张重学卡留在今日队列，可再来一轮继续。`
                    : `共 ${scope.length} 张卡片，没有今天到期的项目。${nextDue ? `最早下次复习在 ${nextDue}。` : '所有卡片都已掌握。'}`}
                  action={(
                    <div className="v3-row v3-study-empty__actions">
                      {queue.length > 0 ? (
                        <Button variant="gradient" icon={<RefreshCw size={16} />} onClick={startSession}>
                          再来一轮
                        </Button>
                      ) : null}
                      <Button variant="tonal" icon={<RefreshCw size={16} />} onClick={refresh}>重新检查到期</Button>
                      <Button variant="text" onClick={() => setView('list')}>查看卡片列表</Button>
                    </div>
                  )}
                />
              </Tile>
            ) : (
              <Tile span={12} className="v3-study-focus">
                <div className="v3-study-focus__head">
                  <div className="v3-study-focus__badges">
                    <CardStatusTag status={current.status} />
                    <Badge tone="primary">{packNameOf(current.packId)}</Badge>
                    <span className="v3-caption v3-study-focus__status">
                      {CARD_STATUS_LABEL[current.status] || '新卡'}
                    </span>
                  </div>
                  <div className="v3-study-focus__nav">
                    <IconButton label="上一张卡片" size="sm" icon={<ChevronLeft size={17} />} onClick={prevCard} disabled={curIdx === 0} />
                    <Badge tone="outline">{curIdx + 1} / {remaining.length}</Badge>
                    <IconButton
                      label="下一张卡片（跳过）"
                      size="sm"
                      icon={<ChevronRight size={17} />}
                      onClick={nextCard}
                      disabled={curIdx >= remaining.length - 1}
                    />
                  </div>
                </div>

                <Progress
                  value={remaining.length ? ((sessionTotal + curIdx + 1) / (sessionTotal + remaining.length)) * 100 : 0}
                  gradient
                  height={6}
                  className="v3-study-focus__progress"
                />

                <div
                  className="v3-study-flip-scene"
                  role="button"
                  tabIndex={0}
                  aria-label={flipped ? '翻转回正面' : '翻转查看答案'}
                  aria-pressed={flipped}
                  onClick={flipCard}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      flipCard()
                    }
                  }}
                >
                  <div className={`v3-study-flip${flipped ? ' is-flipped' : ''}`}>
                    <div className="v3-study-flip__face v3-study-flip__face--front">
                      <span className="v3-study-flip__tag">正面 · 点击翻转</span>
                      <div className="v3-study-flip__content">{renderSide(current.front)}</div>
                    </div>
                    <div className="v3-study-flip__face v3-study-flip__face--back">
                      <span className="v3-study-flip__tag">背面 · 答案</span>
                      <div className="v3-study-flip__content">{renderSide(current.back)}</div>
                      {current.hint ? (
                        <div className="v3-study-flip__hint">
                          <Wand size={14} />
                          <span>提示：{current.hint}</span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>

                <div className="v3-study-card-meta">
                  <span>复习 {current.reps || 0} 次</span>
                  <span>间隔 {current.interval || 0} 天</span>
                  <span>EF {(Number(current.ef) || 2.5).toFixed(1)}</span>
                  <span>状态 {CARD_STATUS_LABEL[current.status] || '新卡'}</span>
                </div>

                <div className="v3-study-session-mini">
                  <span>本轮 {sessionTotal} 张</span>
                  <span>正确 {sessionCorrect}</span>
                  <span>准确率 {sessionAccuracy}%</span>
                </div>

                {!showBack ? (
                  <Button variant="gradient" block size="lg" icon={<Eye size={18} />} onClick={flipCard}>
                    点击卡片或点击此处显示答案
                  </Button>
                ) : (
                  <>
                    <div className="v3-study-grades">
                      <Button variant="tonal" className="v3-study-grade v3-study-grade--again" disabled={grading} onClick={() => grade(GRADE.AGAIN)}>
                        <span className="v3-study-grade__label">重学</span>
                        <span className="v3-study-grade__hint">10 分钟后</span>
                      </Button>
                      <Button variant="tonal" className="v3-study-grade v3-study-grade--hard" disabled={grading} onClick={() => grade(GRADE.HARD)}>
                        <span className="v3-study-grade__label">困难</span>
                        <span className="v3-study-grade__hint">{Math.max(1, Math.round((current.interval || 1) * 0.6))} 天后</span>
                      </Button>
                      <Button variant="tonal" className="v3-study-grade v3-study-grade--good" disabled={grading} onClick={() => grade(GRADE.GOOD)}>
                        <span className="v3-study-grade__label">良好</span>
                        <span className="v3-study-grade__hint">{Math.round((current.interval || 1) * (current.ef || 2.5))} 天后</span>
                      </Button>
                      <Button variant="tonal" className="v3-study-grade v3-study-grade--easy" disabled={grading} onClick={() => grade(GRADE.EASY)}>
                        <span className="v3-study-grade__label">轻松</span>
                        <span className="v3-study-grade__hint">{Math.round((current.interval || 1) * (current.ef || 2.5) * 1.3)} 天后</span>
                      </Button>
                    </div>
                    <p className="v3-study-keyhint">快捷键：1 = 重学 · 2 = 困难 · 3 = 良好 · 4 = 轻松</p>
                  </>
                )}
              </Tile>
            )
          ) : null}

          {view === 'summary' ? (
            <div className="v3-bento">
              <Tile span={8} className="v3-study-summary">
                <div className="v3-study-summary__hero">
                  <span className="v3-study-summary__orb"><CheckCircle2 size={30} /></span>
                  <div>
                    <h2>本轮复习完成！</h2>
                    <p>继续保持，间隔重复让记忆更牢固。评分已按 SM-2 / FSRS 排入下一次复习。</p>
                  </div>
                </div>

                <div className="v3-study-mini-stats">
                  <div><span>复习卡片</span><b>{sessionTotal}</b></div>
                  <div><span>掌握率</span><b>{sessionAccuracy}%</b></div>
                  <div><span>掌握卡片</span><b>{sessionCorrect}</b></div>
                  <div><span>需重学</span><b>{sessionStats.again}</b></div>
                </div>

                <div className="v3-study-dist">
                  <div className="v3-study-dist__head">
                    <span>评分分布</span>
                    <span>{sessionTotal > 0 ? `共 ${sessionTotal} 次评分` : '本轮还没有评分记录'}</span>
                  </div>
                  <div className="v3-study-dist__bar" aria-hidden="true">
                    {sessionTotal > 0 ? (
                      <>
                        <i className="is-again" style={{ width: `${(sessionStats.again / sessionTotal) * 100}%` }} title={`重学 ${sessionStats.again}`} />
                        <i className="is-hard" style={{ width: `${(sessionStats.hard / sessionTotal) * 100}%` }} title={`困难 ${sessionStats.hard}`} />
                        <i className="is-good" style={{ width: `${(sessionStats.good / sessionTotal) * 100}%` }} title={`良好 ${sessionStats.good}`} />
                        <i className="is-easy" style={{ width: `${(sessionStats.easy / sessionTotal) * 100}%` }} title={`轻松 ${sessionStats.easy}`} />
                      </>
                    ) : <i className="is-empty" style={{ width: '100%' }} />}
                  </div>
                  <div className="v3-study-dist__legend">
                    <span className="is-again">重学 {sessionStats.again}</span>
                    <span className="is-hard">困难 {sessionStats.hard}</span>
                    <span className="is-good">良好 {sessionStats.good}</span>
                    <span className="is-easy">轻松 {sessionStats.easy}</span>
                  </div>
                </div>

                <div className="v3-study-summary__actions">
                  <Button
                    variant="gradient"
                    icon={<RefreshCw size={16} />}
                    onClick={startSession}
                    disabled={queue.length === 0}
                  >
                    再来一轮
                  </Button>
                  <Button variant="text" onClick={() => setView('list')}>查看卡片列表</Button>
                </div>
                {queue.length === 0 ? (
                  <p className="v3-study-keyhint">当前没有到期卡片；去卡包添加新卡，或等下一次复习日期到达。</p>
                ) : null}
              </Tile>

              <Tile span={4} className="v3-study-side">
                <span className="v3-tile__label"><Target size={15} /> 今日概览</span>
                <div className="v3-study-kv">
                  <div><span>到期</span><b>{due.length}</b></div>
                  <div><span>队列</span><b>{queue.length}</b></div>
                  <div><span>已掌握</span><b>{mastered}</b></div>
                </div>
                <div className="v3-study-side__note">
                  <Clock size={14} />
                  <span>{nextDue ? `最早下次复习：${nextDue}` : '暂无排期中的复习卡'}</span>
                </div>
                <div className="v3-study-side__note">
                  <Layers size={14} />
                  <span>{packs.length ? `${packs.length} 个卡包 · ${cards.length} 张卡片` : '还没有卡包'}</span>
                </div>
                <Button variant="tonal" block icon={<Layers size={16} />} onClick={() => setView('packs')}>
                  卡包管理
                </Button>
              </Tile>
            </div>
          ) : null}

          {view === 'packs' ? (
            <Tile span={12} className="v3-study-panel">
              <div className="v3-study-panel__head">
                <div>
                  <h2>卡包（{packs.length}）</h2>
                  <p>点击卡包切换到该卡组复习；掌握度按已掌握卡片占比计算。</p>
                </div>
                <div className="v3-study-panel__actions">
                  <Button size="sm" variant="gradient" icon={<Plus size={15} />} onClick={() => setShowAddPack(true)}>
                    新建卡包
                  </Button>
                </div>
              </div>

              {packStats.length === 0 ? (
                <Empty
                  icon={<Layers size={26} />}
                  title="还没有卡包"
                  text="创建卡包后，卡片可以按科目或专题分组复习。"
                  action={<Button variant="gradient" onClick={() => setShowAddPack(true)}>创建卡包</Button>}
                />
              ) : (
                <div className="v3-study-pack-grid">
                  {packStats.map((p, i) => (
                    <div
                      key={p.id}
                      role="button"
                      tabIndex={0}
                      className={`v3-study-pack tone-${i % 5}`}
                      onClick={() => openPackStudy(p)}
                      onKeyDown={(e) => {
                        if (e.target !== e.currentTarget) return
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          openPackStudy(p)
                        }
                      }}
                    >
                      <div className="v3-study-pack__top">
                        <span className="v3-study-pack__glyph"><Layers size={18} /></span>
                        <IconButton
                          label={`删除卡包 ${p.name}`}
                          size="sm"
                          icon={<Trash size={15} />}
                          onClick={(e) => {
                            e.stopPropagation()
                            handleRemovePack(p)
                          }}
                        />
                      </div>
                      <strong className="v3-study-pack__name">{p.name}</strong>
                      <span className="v3-study-pack__meta">
                        {p.subject ? `${p.subject} · ` : ''}{p.total} 张卡片
                      </span>
                      <div className="v3-study-pack__stats">
                        <span><b>{p.mastered}</b> 已掌握</span>
                        <span>均间隔 <b>{p.avgInterval}d</b></span>
                      </div>
                      <div className="v3-study-pack__ratio">
                        <span>掌握度</span>
                        <b>{p.ratio}%</b>
                      </div>
                      <Progress value={p.ratio} height={6} />
                    </div>
                  ))}
                </div>
              )}
            </Tile>
          ) : null}

          {view === 'list' ? (
            <Tile span={12} className="v3-study-panel">
              <div className="v3-study-panel__head">
                <div>
                  <h2>卡片列表（{listFiltered.length}）</h2>
                  <p>搜索正面、背面与提示；按调度状态筛选当前卡组。</p>
                </div>
                <div className="v3-study-panel__actions">
                  <Input
                    icon={<Search size={15} />}
                    className="v3-study-search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="搜索卡片内容…"
                    aria-label="搜索卡片"
                  />
                  <Button size="sm" variant="tonal" icon={<Plus size={15} />} onClick={openAddCard}>添加</Button>
                </div>
              </div>

              <div className="v3-study-filters">
                <div className="v3-study-filter-group" role="group" aria-label="按状态筛选卡片">
                  {STATUS_FILTERS.map((f) => (
                    <Chip key={f.value} active={statusFilter === f.value} onClick={() => setStatusFilter(f.value)}>
                      {f.label}
                    </Chip>
                  ))}
                </div>
              </div>

              {cards.length === 0 ? (
                <Empty
                  icon={<BookOpen size={26} />}
                  title="还没有卡片"
                  text="新建卡片或从错题本一键转卡片，保存后自动排入复习。"
                  action={<Button variant="gradient" icon={<Plus size={16} />} onClick={openAddCard}>新建卡片</Button>}
                />
              ) : listFiltered.length === 0 ? (
                <Empty
                  icon={<Search size={26} />}
                  title="没有匹配的卡片"
                  text="换一个关键词，或把状态筛选切回「全部」。"
                  action={(
                    <Button
                      variant="tonal"
                      onClick={() => {
                        setSearch('')
                        setStatusFilter('all')
                        selectPack('all')
                      }}
                    >
                      清空筛选
                    </Button>
                  )}
                />
              ) : (
                <div className="v3-study-card-list">
                  {listFiltered.map((c) => (
                    <div key={c.id} className="v3-study-card-row">
                      <div className="v3-study-card-row__status">
                        <CardStatusTag status={c.status} />
                      </div>
                      <div className="v3-study-card-row__main">
                        <div className="v3-study-card-row__title">{sideText(c.front) || '卡片'}</div>
                        <div className="v3-study-card-row__meta">{sideText(c.back)}</div>
                      </div>
                      <div className="v3-study-card-row__actions">
                        <Badge tone="outline">间隔 {c.interval || 0}d</Badge>
                        <Badge tone="outline">复习 {c.reps || 0} 次</Badge>
                        <IconButton
                          label="删除卡片"
                          size="sm"
                          icon={<Trash size={15} />}
                          onClick={() => handleRemoveCard(c.id)}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Tile>
          ) : null}
        </>
      )}

      <Dialog
        open={showAddPack}
        title="新建卡包"
        sub="卡包用于按科目或专题组织记忆卡片"
        onClose={() => setShowAddPack(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowAddPack(false)}>取消</Button>
            <Button variant="gradient" onClick={createPack}>创建</Button>
          </>
        )}
      >
        <div className="v3-study-dialog">
          <Field label="卡包名称">
            <Input
              placeholder="卡包名称（如：政治大题背诵）"
              aria-label="卡包名称"
              value={packName}
              onChange={(e) => setPackName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') createPack() }}
            />
          </Field>
          <Field
            label="科目"
            hint={subjects.length === 0 ? '科目接口不可用，请稍后重试（科目以「设置 → 科目管理」为唯一来源）。' : undefined}
          >
            <Select aria-label="卡包科目" value={packSubject} onChange={(e) => setPackSubject(e.target.value)}>
              <option value="" disabled>选择科目</option>
              {subjects.map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
          </Field>
        </div>
      </Dialog>

      <Dialog
        open={showFromNote}
        title="错题一键转卡片"
        sub="选择一条错题，自动生成问答卡片并归入第一个卡包"
        onClose={() => setShowFromNote(false)}
      >
        <div className="v3-study-dialog">
          {packs.length === 0 ? (
            <Alert tone="warning">还没有卡包。请先创建卡包，再回来转换错题。</Alert>
          ) : null}
          {notebook.length === 0 ? (
            <Empty
              icon={<BookOpen size={26} />}
              title="错题本还是空的"
              text="先在错题本记录错题，再回来一键生成记忆卡片。"
            />
          ) : (
            <>
              <div className="v3-study-note-list">
                {notebook.slice(0, 12).map((n) => (
                  <button key={n.id} type="button" className="v3-study-note" onClick={() => noteToCardNow(n)}>
                    <span className="v3-study-note__icon"><Quote size={15} /></span>
                    <span className="v3-study-note__main">
                      <span className="v3-study-note__title">{n.question}</span>
                      <span className="v3-study-note__meta">{n.answer}</span>
                    </span>
                  </button>
                ))}
              </div>
              {notebook.length > 12 ? (
                <p className="v3-study-subject-note">仅显示最近 12 条错题，可先在错题本整理后再转换。</p>
              ) : null}
            </>
          )}
        </div>
      </Dialog>

      <Dialog
        open={showAddCard}
        title="新建记忆卡片"
        sub="正面写问题，背面写答案"
        onClose={() => { setShowAddCard(false); setCardErr('') }}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowAddCard(false)}>取消</Button>
            <Button variant="gradient" onClick={createCard}>添加</Button>
          </>
        )}
      >
        <div className="v3-study-dialog">
          {packs.length === 0 ? (
            <Alert tone="warning">
              还没有卡包。请先关闭本弹窗，点右上角「新建卡包」，再回来添加卡片。
            </Alert>
          ) : null}
          {cardErr ? <Alert tone="danger">{cardErr}</Alert> : null}

          <div className="v3-study-form-grid">
            <Field label="所属卡包" className="v3-study-field--wide">
              <Select
                aria-label="选择卡包"
                value={form.packId}
                onChange={(e) => setForm({ ...form, packId: e.target.value })}
              >
                <option value="">选择卡包</option>
                {packs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </Field>
            <Field label="正面（问题 / 知识点）" className="v3-study-field--wide">
              <Input
                placeholder="正面（问题 / 知识点）"
                aria-label="卡片正面（问题）"
                value={form.front}
                onChange={(e) => setForm({ ...form, front: e.target.value })}
              />
            </Field>
            <Field label="背面（答案 / 解析）" className="v3-study-field--wide">
              <Textarea
                rows={3}
                placeholder="背面（答案 / 解析）"
                aria-label="卡片背面（答案）"
                value={form.back}
                onChange={(e) => setForm({ ...form, back: e.target.value })}
              />
            </Field>
            <Field label="提示（可选）" className="v3-study-field--wide">
              <Input
                placeholder="提示（可选）"
                aria-label="卡片提示（可选）"
                value={form.hint}
                onChange={(e) => setForm({ ...form, hint: e.target.value })}
              />
            </Field>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
