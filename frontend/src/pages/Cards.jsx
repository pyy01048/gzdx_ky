import React, { useEffect, useMemo, useState, useCallback } from 'react'
import useStore from '../store/useStore'
import { Modal, Segmented, Empty, toast } from '../components/UI'
import { dueCards, GRADE } from '../utils/spaced'
import { todayStr } from '../utils/date'
import { noteToCard } from '../utils/words'
import { flashcardsApi } from '../api/client'
import { ChevronLeft, ChevronRight, Book, Target, CheckCircle, Clock, RefreshCw, Play } from '../components/Icon'

const PACK_COLOR = ['var(--accent)', '#e8a33d', '#5b8def', '#7a6fe8', '#43b581']

// 掌握度饼图组件
function MasteryPie({ level, size = 32 }) {
  const percentage = Math.min(level / 7 * 100, 100)
  const color = percentage >= 80 ? 'var(--green)' : percentage >= 50 ? 'var(--gold)' : percentage >= 20 ? 'var(--orange)' : 'var(--red)'
  const circumference = 2 * Math.PI * 14
  const offset = circumference - (percentage / 100) * circumference
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" style={{ flexShrink: 0 }}>
      <circle cx="16" cy="16" r="14" fill="none" stroke="var(--surface-3)" strokeWidth="3" />
      <circle cx="16" cy="16" r="14" fill="none" stroke={color} strokeWidth="3"
        strokeDasharray={circumference} strokeDashoffset={offset}
        strokeLinecap="round" transform="rotate(-90 16 16)"
        style={{ transition: 'stroke-dashoffset 0.5s ease' }} />
    </svg>
  )
}

/* 渲染卡片正/反面：若含 media 字段则渲染图片/音频 */
function renderSide(val) {
  if (val && typeof val === 'object' && val.media) {
    const m = val.media
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {val.text && <p style={{ margin: 0, lineHeight: 1.6 }}>{val.text}</p>}
        {m.type === 'image' && <img src={m.url} alt="" style={{ maxWidth: '100%', borderRadius: 8, border: '1px solid var(--line)' }} />}
        {m.type === 'audio' && <audio controls src={m.url} style={{ width: '100%' }} />}
      </div>
    )
  }
  return <p style={{ margin: 0, lineHeight: 1.6 }}>{val}</p>
}

export default function Cards() {
  const { cards, packs, notebook, addCard, addPack, reviewCard, removeCard, removePack, setCards, setPacks } = useStore()
  const [view, setView] = useState('study') // study | summary | packs | list
  const [curIdx, setCurIdx] = useState(0)
  const [showBack, setShowBack] = useState(false)
  const [flipped, setFlipped] = useState(false)
  const [packId, setPackId] = useState('all')
  const [showAddPack, setShowAddPack] = useState(false)
  const [packName, setPackName] = useState('')
  const [packSubject, setPackSubject] = useState('math')
  const [showFromNote, setShowFromNote] = useState(false)
  const [showAddCard, setShowAddCard] = useState(false)
  const [form, setForm] = useState({ packId: '', front: '', back: '', hint: '' })
  const [loading, setLoading] = useState(false)
  // 学习会话统计
  const [sessionStats, setSessionStats] = useState({ again: 0, hard: 0, good: 0, easy: 0, startTime: null, cards: [] })

  // 从后端加载卡片
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      try {
        const backendCards = await flashcardsApi.list({ page: 1, page_size: 500 })
        if (backendCards && backendCards.length > 0) {
          const formatted = backendCards.map(c => ({
            id: c.id,
            front: c.front,
            back: c.back,
            hint: c.hint,
            packId: c.deck_id ? String(c.deck_id) : 'default',
            status: c.status || 'new',
            ef: c.ease_factor || 2.5,
            interval: c.interval || 0,
            reps: c.reps || 0,
            lapses: c.lapses || 0,
            due: c.due_date ? c.due_date : todayStr(),
            lastReview: c.last_review,
            tags: c.tags || []
          }))
          setCards(formatted)
        }
      } catch (err) {
        console.warn('从后端加载卡片失败，使用本地数据:', err.message)
        toast('后端卡片加载失败，已显示本机数据')
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [])

  // 选择包过滤
  const scope = useMemo(() => (packId === 'all' ? cards : cards.filter((c) => c.packId === packId)), [cards, packId])
  const due = useMemo(() => dueCards(scope, todayStr()), [scope])
  const queue = useMemo(() => {
    const inProgress = due.filter((c) => c.status !== 'new')
    const fresh = due.filter((c) => c.status === 'new')
    return [...inProgress, ...fresh]
  }, [due])

  const current = queue[curIdx] || null
  const mastered = cards.filter((c) => c.status === 'mastered').length
  const active = cards.length - mastered

  // 各卡包掌握度统计
  const packStats = useMemo(() => packs.map((p) => {
    const inPack = cards.filter((c) => c.packId === p.id)
    const m = inPack.filter((c) => c.status === 'mastered').length
    const avgInterval = inPack.length ? Math.round(inPack.reduce((a, c) => a + (c.interval || 0), 0) / inPack.length) : 0
    return { ...p, total: inPack.length, mastered: m, ratio: inPack.length ? Math.round((m / inPack.length) * 100) : 0, avgInterval }
  }), [packs, cards])

  // 开始新的学习会话
  const startSession = useCallback(() => {
    setSessionStats({ again: 0, hard: 0, good: 0, easy: 0, startTime: Date.now(), cards: [] })
    setCurIdx(0)
    setShowBack(false)
    setFlipped(false)
    setView('study')
  }, [])

  const grade = async (g) => {
    if (!current) return
    // 更新会话统计
    const gradeKey = g === GRADE.AGAIN ? 'again' : g === GRADE.HARD ? 'hard' : g === GRADE.GOOD ? 'good' : 'easy'
    setSessionStats(prev => ({
      ...prev,
      [gradeKey]: prev[gradeKey] + 1,
      cards: [...prev.cards, { id: current.id, front: typeof current.front === 'string' ? current.front : current.front?.text, grade: gradeKey }]
    }))
    // 后端同步
    // V7.0 P0-4：后端 FlashcardReview 只接受 `quality`（0-5 必填），此前误传 `grade`
    // 导致 FastAPI 直接 422，页面却用 console.warn 静默吞掉，复习打卡 100% 失败而不自知。
    // 现在：① 参数名修正；② 失败必须让用户看见（toast），不再静默。
    try {
      await flashcardsApi.review(current.id, { quality: g })
    } catch (err) {
      toast(`复习记录同步失败：${err?.message || '未知错误'}（本地进度已保存）`)
    }
    reviewCard(current.id, g)
    setShowBack(false)
    setFlipped(false)
    // 自动进入下一张
    if (curIdx + 1 < queue.length) {
      setCurIdx(curIdx + 1)
    } else {
      // 会话完成，显示总结
      setView('summary')
    }
  }

  // 上一张卡片
  const prevCard = () => {
    if (curIdx > 0) {
      setCurIdx(curIdx - 1)
      setShowBack(false)
      setFlipped(false)
    }
  }

  // 下一张卡片（不评分，直接跳过）
  const nextCard = () => {
    if (curIdx + 1 < queue.length) {
      setCurIdx(curIdx + 1)
      setShowBack(false)
      setFlipped(false)
    }
  }

  // 翻转卡片
  const flipCard = () => {
    setFlipped(!flipped)
    setShowBack(!showBack)
  }

  const createPack = () => {
    if (!packName.trim()) return toast('请输入卡包名称')
    addPack(packName.trim(), packSubject, 0)
    toast('卡包已创建')
    setPackName('')
    setShowAddPack(false)
  }

  const noteToCardNow = async (note) => {
    const pack = packs[0]
    if (!pack) return toast('请先创建卡包')
    const newCard = { ...noteToCard(note), packId: pack.id }
    addCard(newCard)
    // 后端同步
    try {
      await flashcardsApi.create({ front: newCard.front, back: newCard.back, hint: newCard.hint, deck_id: pack.id })
    } catch (err) {
      // 同 P0-4：静默失败会让用户以为卡片已入库，改为可见提示
      toast(`卡片同步到后端失败：${err?.message || '未知错误'}（仅保存在本机）`)
    }
    toast('已生成记忆卡片')
    setShowFromNote(false)
  }

  const createCard = async () => {
    if (!form.packId || !form.front.trim() || !form.back.trim()) return toast('请补全卡片内容')
    const newCard = { ...form, packId: form.packId }
    addCard(newCard)
    // 后端同步
    try {
      await flashcardsApi.create({ front: newCard.front, back: newCard.back, hint: newCard.hint, deck_id: form.packId })
    } catch (err) {
      toast(`卡片同步到后端失败：${err?.message || '未知错误'}（仅保存在本机）`)
    }
    toast('卡片已添加')
    setForm({ packId: '', front: '', back: '', hint: '' })
    setShowAddCard(false)
  }

  const handleRemoveCard = async (id) => {
    try {
      await flashcardsApi.remove(id)
    } catch (err) {
      toast(`删除同步失败：${err?.message || '未知错误'}（本机已删除，刷新后可能复现）`)
    }
    removeCard(id)
    toast('卡片已删除')
  }

  // 会话统计
  const sessionTotal = sessionStats.again + sessionStats.hard + sessionStats.good + sessionStats.easy
  const sessionCorrect = sessionStats.good + sessionStats.easy
  const sessionAccuracy = sessionTotal > 0 ? Math.round(sessionCorrect / sessionTotal * 100) : 0

  return (
    <div className="container stack">
      <div className="page-head">
        <div>
          <h1 className="page-title">记忆卡片</h1>
          <p className="page-sub">SM-2 间隔重复 · 卡片翻转 · 四档评分 · 后端同步（对标 Anki / Quizlet / 记乎）</p>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={() => setShowFromNote(true)}>错题转卡片</button>
          <button className="btn ghost" onClick={() => setShowAddCard(true)}>新建卡片</button>
          <button className="btn primary" onClick={() => setShowAddPack(true)}>新建卡包</button>
        </div>
      </div>

      {/* 统计条 */}
      <div className="stat-grid">
        <div className="stat-tile"><span className="st-ico blue"><Book size={20} /></span><span className="st-val">{cards.length}</span><span className="st-label">卡片总数</span></div>
        <div className="stat-tile"><span className="st-ico red"><Target size={20} /></span><span className="st-val" style={{ color: 'var(--red)' }}>{due.length}</span><span className="st-label">今日待复习</span></div>
        <div className="stat-tile"><span className="st-ico amber"><Clock size={20} /></span><span className="st-val" style={{ color: 'var(--gold)' }}>{active}</span><span className="st-label">进行中</span></div>
        <div className="stat-tile"><span className="st-ico green"><CheckCircle size={20} /></span><span className="st-val" style={{ color: 'var(--green)' }}>{mastered}</span><span className="st-label">已掌握</span></div>
      </div>

      {/* 视图切换 */}
      <Segmented options={[
        { label: '📖 复习', value: 'study' },
        { label: '📊 总结', value: 'summary' },
        { label: '📦 卡包', value: 'packs' },
        { label: '📋 列表', value: 'list' }
      ]} value={view} onChange={setView} />

      {/* 空状态引导：没有卡包时 */}
      {packs.length === 0 && view === 'study' && (
        <div className="card" style={{ textAlign: 'center', padding: '40px 20px' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>📦</div>
          <div className="card-title" style={{ marginBottom: 8 }}>还没有卡包</div>
          <p className="card-sub" style={{ marginBottom: 16 }}>创建一个卡包，开始添加记忆卡片，使用SM-2间隔重复算法高效记忆</p>
          <button className="btn primary" onClick={() => setShowAddPack(true)}>➕ 新建卡包</button>
        </div>
      )}

      {/* 空状态引导：有卡包但没有卡片时 */}
      {packs.length > 0 && cards.length === 0 && view === 'study' && (
        <div className="card" style={{ textAlign: 'center', padding: '40px 20px' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>🃏</div>
          <div className="card-title" style={{ marginBottom: 8 }}>还没有卡片</div>
          <p className="card-sub" style={{ marginBottom: 16 }}>添加记忆卡片，或从错题本一键转卡片</p>
          <div className="row" style={{ gap: 10, justifyContent: 'center' }}>
            <button className="btn primary" onClick={() => setShowAddCard(true)}>➕ 新建卡片</button>
            <button className="btn ghost" onClick={() => setShowFromNote(true)}>📝 错题转卡片</button>
          </div>
        </div>
      )}

      {/* 卡包筛选 */}
      {packs.length > 0 && (
        <Segmented
          options={[{ label: '全部卡组', value: 'all' }, ...packs.map((p) => ({ label: p.name, value: p.id }))]}
          value={packId} onChange={(v) => { setPackId(v); setCurIdx(0); setFlipped(false) }}
        />
      )}

      {/* 学习视图 */}
      {view === 'study' && queue.length > 0 && current && (
        <div className="card">
          {/* 顶部导航 */}
          <div className="spread" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <MasteryPie level={current.reps || 0} size={28} />
              <span className="badge accent">{packs.find((p) => p.id === current.packId)?.name || '卡片'}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button className="btn icon ghost" onClick={prevCard} disabled={curIdx === 0} title="上一张">
                <ChevronLeft size={18} />
              </button>
              <span className="badge neutral">{curIdx + 1} / {queue.length}</span>
              <button className="btn icon ghost" onClick={nextCard} disabled={curIdx >= queue.length - 1} title="下一张（跳过）">
                <ChevronRight size={18} />
              </button>
            </div>
          </div>

          {/* 进度条 */}
          <div className="progress thin" style={{ marginBottom: 16 }}>
            <i style={{ width: `${((curIdx + 1) / queue.length) * 100}%` }} />
          </div>

          {/* 卡片翻转区域 */}
          <div style={{ perspective: '1000px', marginBottom: 16 }}>
            <div
              onClick={flipCard}
              style={{
                position: 'relative',
                width: '100%',
                minHeight: 200,
                transformStyle: 'preserve-3d',
                transition: 'transform 0.6s',
                transform: flipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
                cursor: 'pointer'
              }}
            >
              {/* 正面 */}
              <div style={{
                position: 'absolute',
                width: '100%',
                minHeight: 200,
                backfaceVisibility: 'hidden',
                background: 'var(--surface)',
                border: '2px solid var(--accent)',
                borderRadius: 16,
                padding: 24,
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                alignItems: 'center',
                textAlign: 'center'
              }}>
                <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: 1 }}>正面 · 点击翻转</div>
                <div style={{ fontSize: 20, fontWeight: 600, lineHeight: 1.6, color: 'var(--ink)' }}>
                  {renderSide(current.front)}
                </div>
              </div>
              {/* 背面 */}
              <div style={{
                position: 'absolute',
                width: '100%',
                minHeight: 200,
                backfaceVisibility: 'hidden',
                transform: 'rotateY(180deg)',
                background: 'var(--surface-2)',
                border: '2px solid var(--green)',
                borderRadius: 16,
                padding: 24,
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                alignItems: 'center',
                textAlign: 'center'
              }}>
                <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: 1 }}>背面 · 答案</div>
                <div style={{ fontSize: 18, lineHeight: 1.6, color: 'var(--ink)' }}>
                  {renderSide(current.back)}
                </div>
                {current.hint && (
                  <div style={{ marginTop: 12, fontSize: 13, color: 'var(--gold)', padding: '8px 12px', background: 'var(--gold-soft)', borderRadius: 8 }}>
                    💡 提示：{current.hint}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* 复习统计 */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: 24, fontSize: 12, color: 'var(--ink-3)', marginBottom: 16 }}>
            <span>复习 {current.reps || 0} 次</span>
            <span>间隔 {current.interval || 0} 天</span>
            <span>EF {(current.ef || 2.5).toFixed(1)}</span>
            <span>遗忘 {current.lapses || 0} 次</span>
          </div>

          {/* 操作按钮 */}
          {!showBack ? (
            <button className="btn primary block" style={{ fontSize: 16, padding: '12px' }} onClick={flipCard}>
              点击卡片或点击此处显示答案
            </button>
          ) : (
            <div>
              <div className="grid-4" style={{ gap: 8, marginBottom: 8 }}>
                <button className="btn" onClick={() => grade(GRADE.AGAIN)}
                  style={{ background: 'var(--red-soft)', color: 'var(--red)', border: 'none', padding: '12px 4px' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>重学</div>
                  <div style={{ fontSize: 11, opacity: 0.8 }}>10分钟后</div>
                </button>
                <button className="btn" onClick={() => grade(GRADE.HARD)}
                  style={{ background: 'var(--gold-soft)', color: 'var(--gold)', border: 'none', padding: '12px 4px' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>困难</div>
                  <div style={{ fontSize: 11, opacity: 0.8 }}>{Math.max(1, Math.round((current.interval || 1) * 0.6))}天后</div>
                </button>
                <button className="btn" onClick={() => grade(GRADE.GOOD)}
                  style={{ background: 'var(--accent-soft)', color: 'var(--accent)', border: 'none', padding: '12px 4px' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>良好</div>
                  <div style={{ fontSize: 11, opacity: 0.8 }}>{Math.round((current.interval || 1) * (current.ef || 2.5))}天后</div>
                </button>
                <button className="btn primary" onClick={() => grade(GRADE.EASY)} style={{ padding: '12px 4px' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>轻松</div>
                  <div style={{ fontSize: 11, opacity: 0.8 }}>{Math.round((current.interval || 1) * (current.ef || 2.5) * 1.3)}天后</div>
                </button>
              </div>
              <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--ink-3)' }}>
                快捷键：1=重学 2=困难 3=良好 4=轻松
              </div>
            </div>
          )}
        </div>
      )}

      {/* 学习完成空状态 */}
      {view === 'study' && queue.length === 0 && packs.length > 0 && cards.length > 0 && (
        <div className="card" style={{ textAlign: 'center', padding: '40px 16px' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>✓</div>
          <div className="card-title">当前卡组今日卡片已复习完成</div>
          <p className="card-sub">掌握越熟练，复习间隔越长，符合间隔重复原理</p>
          <button className="btn primary" style={{ marginTop: 16 }} onClick={startSession}>
            <RefreshCw size={16} style={{ marginRight: 6 }} /> 重新开始复习
          </button>
        </div>
      )}

      {/* 学习总结视图 */}
      {view === 'summary' && (
        <div className="card" style={{ padding: 24 }}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>🎉</div>
            <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 4 }}>本轮复习完成！</h2>
            <p className="card-sub">继续保持，间隔重复让记忆更牢固</p>
          </div>

          {/* 核心统计 */}
          <div className="stat-grid" style={{ marginBottom: 24 }}>
            <div className="stat-tile">
              <span className="st-ico blue"><Book size={20} /></span>
              <span className="st-val">{sessionTotal}</span>
              <span className="st-label">复习卡片</span>
            </div>
            <div className="stat-tile">
              <span className="st-ico green"><CheckCircle size={20} /></span>
              <span className="st-val" style={{ color: 'var(--green)' }}>{sessionAccuracy}%</span>
              <span className="st-label">掌握率</span>
            </div>
            <div className="stat-tile">
              <span className="st-ico amber"><Clock size={20} /></span>
              <span className="st-val" style={{ color: 'var(--gold)' }}>{sessionCorrect}</span>
              <span className="st-label">掌握卡片</span>
            </div>
            <div className="stat-tile">
              <span className="st-ico red"><Target size={20} /></span>
              <span className="st-val" style={{ color: 'var(--red)' }}>{sessionStats.again}</span>
              <span className="st-label">需重学</span>
            </div>
          </div>

          {/* 评分分布 */}
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>评分分布</h3>
            <div style={{ display: 'flex', gap: 4, height: 24, borderRadius: 8, overflow: 'hidden' }}>
              {sessionTotal > 0 && (
                <>
                  <div style={{ width: `${sessionStats.again / sessionTotal * 100}%`, background: 'var(--red)' }} title={`重学 ${sessionStats.again}`} />
                  <div style={{ width: `${sessionStats.hard / sessionTotal * 100}%`, background: 'var(--gold)' }} title={`困难 ${sessionStats.hard}`} />
                  <div style={{ width: `${sessionStats.good / sessionTotal * 100}%`, background: 'var(--accent)' }} title={`良好 ${sessionStats.good}`} />
                  <div style={{ width: `${sessionStats.easy / sessionTotal * 100}%`, background: 'var(--green)' }} title={`轻松 ${sessionStats.easy}`} />
                </>
              )}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12, color: 'var(--ink-3)' }}>
              <span style={{ color: 'var(--red)' }}>重学 {sessionStats.again}</span>
              <span style={{ color: 'var(--gold)' }}>困难 {sessionStats.hard}</span>
              <span style={{ color: 'var(--accent)' }}>良好 {sessionStats.good}</span>
              <span style={{ color: 'var(--green)' }}>轻松 {sessionStats.easy}</span>
            </div>
          </div>

          {/* 操作按钮 */}
          <div style={{ display: 'flex', gap: 12 }}>
            <button className="btn primary" style={{ flex: 1 }} onClick={startSession}>
              <RefreshCw size={16} style={{ marginRight: 6 }} /> 再来一轮
            </button>
            <button className="btn ghost" style={{ flex: 1 }} onClick={() => setView('list')}>
              查看卡片列表
            </button>
          </div>
        </div>
      )}

      {/* 卡包视图 */}
      {view === 'packs' && (
        packStats.length === 0 ? (
          <Empty icon={<Book size={32} />} title="还没有卡包" desc="点击右上角「新建卡包」开始组织记忆卡片" action={<button className="btn primary" onClick={() => setShowAddPack(true)}>新建卡包</button>} />
        ) : (
        <div className="grid-3">
          {packStats.map((p, i) => (
            <div key={p.id} className="card" style={{ borderColor: PACK_COLOR[i % 5], cursor: 'pointer' }}
              onClick={() => { setPackId(p.id); setView('study'); setCurIdx(0); toast(`已切换到卡包：${p.name}`) }}>
              <div className="card-head">
                <b className="card-title">{p.name}</b>
                <button className="btn sm danger" onClick={(e) => { e.stopPropagation(); removePack(p.id) }}>删除</button>
              </div>
              <div className="row" style={{ gap: 8, marginBottom: 10 }}>
                <span className="badge neutral">{p.total} 卡</span>
                <span className="badge success">已掌握 {p.mastered}</span>
                <span className="badge info">均间隔 {p.avgInterval}d</span>
              </div>
              <div className="card-sub" style={{ marginBottom: 6 }}>掌握度 {p.ratio}%</div>
              <div className="progress thin"><i style={{ width: `${p.ratio}%` }} /></div>
            </div>
          ))}
        </div>
        )
      )}

      {/* 列表视图 */}
      {view === 'list' && (
        <div className="card flush">
          <div className="card-head" style={{ padding: '14px 18px' }}>
            <b className="card-title">卡片列表（{scope.length}）</b>
          </div>
          {loading ? (
            <div className="loading-inline">正在加载卡片…</div>
          ) : scope.length === 0 ? (
            <Empty title="暂无卡片" desc="从错题本一键转卡片，或新建卡片" />
          ) : (
          <div className="list" style={{ padding: '0 12px 12px' }}>
            {scope.map((c) => (
              <div key={c.id} className="list-row">
                <MasteryPie level={c.reps || 0} size={28} />
                <div className="lr-main">
                  <div className="lr-title">{typeof c.front === 'string' ? c.front : (c.front?.text || '卡片')}</div>
                  <div className="lr-meta">{typeof c.back === 'string' ? c.back : (c.back?.text || '')}</div>
                </div>
                <div className="lr-actions">
                  <span className="badge accent">间隔 {c.interval || 0}d</span>
                  <span className="badge neutral">连对 {c.reps || 0}</span>
                  <button className="btn sm danger" onClick={() => handleRemoveCard(c.id)}>删</button>
                </div>
              </div>
            ))}
          </div>
          )}
        </div>
      )}

      {/* 新建卡包弹窗 */}
      <Modal open={showAddPack} title="新建卡包" onClose={() => setShowAddPack(false)}>
          <input className="input" style={{ marginBottom: 8 }} placeholder="卡包名称（如：政治大题背诵）" value={packName} onChange={(e) => setPackName(e.target.value)} />
          <select className="input" value={packSubject} onChange={(e) => setPackSubject(e.target.value)}>
            <option value="math">数学</option>
            <option value="english">英语</option>
            <option value="politics">政治</option>
            <option value="major">专业课</option>
            <option value="other">其他</option>
          </select>
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            <button className="btn primary" style={{ flex: 1 }} onClick={createPack}>创建</button>
            <button className="btn ghost" onClick={() => setShowAddPack(false)}>取消</button>
          </div>
      </Modal>

      {/* 错题转卡片弹窗 */}
      <Modal open={showFromNote} title="错题一键转卡片" onClose={() => setShowFromNote(false)}>
          <p style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 8 }}>选择一条错题，自动生成问答卡片并归入当前卡包：</p>
          <div className="list">
            {notebook.slice(0, 12).map((n) => (
              <button key={n.id} className="list-row" style={{ cursor: 'pointer', textAlign: 'left' }} onClick={() => noteToCardNow(n)}>
                <span className="lr-ico" style={{ background: 'var(--surface-2)', color: 'var(--accent)' }}>📝</span>
                <div className="lr-main"><div className="lr-title">{n.question}</div><div className="lr-meta">{n.answer}</div></div>
              </button>
            ))}
          </div>
      </Modal>

      {/* 新建卡片弹窗 */}
      <Modal open={showAddCard} title="新建记忆卡片" onClose={() => setShowAddCard(false)}>
          <select className="input" style={{ marginBottom: 8 }} value={form.packId} onChange={(e) => setForm({ ...form, packId: e.target.value })}>
            <option value="">选择卡包</option>
            {packs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input className="input" style={{ marginBottom: 8 }} placeholder="正面（问题 / 知识点）" value={form.front} onChange={(e) => setForm({ ...form, front: e.target.value })} />
          <textarea className="input" rows={3} style={{ marginBottom: 8 }} placeholder="背面（答案 / 解析）" value={form.back} onChange={(e) => setForm({ ...form, back: e.target.value })} />
          <input className="input" placeholder="提示（可选）" value={form.hint} onChange={(e) => setForm({ ...form, hint: e.target.value })} />
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            <button className="btn primary" style={{ flex: 1 }} onClick={createCard}>添加</button>
            <button className="btn ghost" onClick={() => setShowAddCard(false)}>取消</button>
          </div>
      </Modal>
    </div>
  )
}
