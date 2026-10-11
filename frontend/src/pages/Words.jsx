import React, { useEffect, useMemo, useState, useCallback } from 'react'
import useStore from '../store/useStore'
import { Modal, Segmented, Empty, toast } from '../components/UI'
import { parseWordList } from '../utils/words'
import { dueCards, GRADE } from '../utils/spaced'
import { todayStr } from '../utils/date'
import { wordsApi } from '../api/client'
import { Play, ChevronLeft, ChevronRight, Book, Target, CheckCircle, Clock, RefreshCw, Check } from '../components/Icon'

const SUBJECT_COLOR = ['var(--accent)', '#e8a33d', '#5b8def', '#7a6fe8', '#43b581']

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

export default function Words() {
  const { words, decks, addDeck, importWords, reviewWord, removeWord, settings, setWords, setDecks } = useStore()
  const [view, setView] = useState('learn') // learn | list | decks | summary
  const [flashcard, setFlashcard] = useState(false)
  const [curIdx, setCurIdx] = useState(0)
  const [showAns, setShowAns] = useState(false)
  const [deckName, setDeckName] = useState('')
  const [importText, setImportText] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [packSel, setPackSel] = useState('core')
  const [loading, setLoading] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [importing, setImporting] = useState(false)
  const [excelFile, setExcelFile] = useState(null)
  // V2.0 新增：学习会话统计
  const [sessionStats, setSessionStats] = useState({ again: 0, hard: 0, good: 0, easy: 0, startTime: null, words: [] })
  const [dailyQuota, setDailyQuota] = useState(() => {
    const saved = localStorage.getItem('words_daily_quota')
    return saved ? parseInt(saved) : 30
  })

  // 从后端加载单词和词库数据
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      try {
        const backendDecks = await wordsApi.listDecks()
        if (backendDecks && backendDecks.length > 0) {
          const formattedDecks = backendDecks.map(d => ({
            id: d.id, name: d.name, count: d.word_count || 0,
            source: d.source || '后端', description: d.description, color: d.color
          }))
          setDecks(formattedDecks)
        }
        const backendWords = await wordsApi.list({ page: 1, page_size: 500 })
        if (backendWords && backendWords.length > 0) {
          const formattedWords = backendWords.map(w => ({
            id: w.id, word: w.word, phonetic: w.phonetic, pos: w.pos,
            meaning: w.meaning, root: w.root, example: w.example,
            ex_cn: w.example_cn, tag: w.tag, frequency: w.frequency,
            deck: w.deck_id ? String(w.deck_id) : 'core',
            status: w.status || 'new', ef: w.ease_factor || 2.5,
            interval: w.interval || 0, reps: w.reps || 0, lapses: w.lapses || 0,
            due: w.due_date ? w.due_date : todayStr(),
            lastReview: w.last_review, history: w.review_history || []
          }))
          setWords(formattedWords)
        }
      } catch (err) {
        console.warn('从后端加载单词失败，使用本地数据:', err.message)
        toast('后端词库加载失败，已切换为本地数据')
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [])

  const due = useMemo(() => dueCards(words, todayStr()), [words])
  const learned = words.filter((w) => w.status === 'mastered').length
  const learning = words.filter((w) => w.status !== 'mastered').length

  // 复习队列（到期词 + 新词），限制每日配额
  const queue = useMemo(() => {
    const inProgress = due.filter((w) => w.status === 'learning' || w.status === 'reviewing')
    const fresh = due.filter((w) => w.status === 'new')
    const all = [...inProgress, ...fresh]
    // 每日配额：新词不超过配额，但复习词不限制
    const reviewWords = all.filter(w => w.status !== 'new')
    const newWords = all.filter(w => w.status === 'new').slice(0, dailyQuota)
    return [...reviewWords, ...newWords]
  }, [due, dailyQuota])

  const current = queue[curIdx] || null
  const isSessionComplete = curIdx >= queue.length && queue.length > 0

  /* 单词发音 */
  const pronounce = (text) => {
    if (!text) return
    if (!('speechSynthesis' in window)) return toast('当前浏览器不支持语音发音')
    try {
      window.speechSynthesis.cancel()
      const u = new SpeechSynthesisUtterance(text)
      u.lang = 'en-US'
      u.rate = 0.9
      window.speechSynthesis.speak(u)
    } catch { toast('发音失败') }
  }

  // 开始新的学习会话
  const startSession = useCallback(() => {
    setSessionStats({ again: 0, hard: 0, good: 0, easy: 0, startTime: Date.now(), words: [] })
    setCurIdx(0)
    setShowAns(false)
    setView('learn')
  }, [])

  const grade = async (g) => {
    if (!current) return
    // 更新会话统计
    const gradeKey = g === GRADE.AGAIN ? 'again' : g === GRADE.HARD ? 'hard' : g === GRADE.GOOD ? 'good' : 'easy'
    setSessionStats(prev => ({
      ...prev,
      [gradeKey]: prev[gradeKey] + 1,
      words: [...prev.words, { id: current.id, word: current.word, grade: gradeKey }]
    }))
    try {
      await wordsApi.review(current.id, g)
    } catch (err) {
      console.warn('后端复习更新失败:', err.message)
    }
    reviewWord(current.id, g)
    setShowAns(false)
    // 自动进入下一个
    if (curIdx + 1 < queue.length) {
      setCurIdx(curIdx + 1)
    } else {
      // 会话完成，显示总结
      setView('summary')
    }
  }

  // 上一个单词
  const prevWord = () => {
    if (curIdx > 0) {
      setCurIdx(curIdx - 1)
      setShowAns(false)
    }
  }

  // 下一个单词（不评分，直接跳过）
  const nextWord = () => {
    if (curIdx + 1 < queue.length) {
      setCurIdx(curIdx + 1)
      setShowAns(false)
    }
  }

  // 列表视图中的评级
  const gradeWord = async (id, g) => {
    try { await wordsApi.review(id, g) } catch (err) { console.warn('后端复习更新失败:', err.message) }
    reviewWord(id, g)
    toast('已记录熟练度')
  }

  // 熟悉度徽标
  const wordBadge = (w) => {
    if (w.tag) return <span className="badge info">{w.tag}</span>
    if (w.frequency) return <span className="badge info">{w.frequency}</span>
    const stars = w.status === 'mastered' ? 3 : (w.status === 'learning' || w.status === 'reviewing') ? 2 : 1
    return <span className="badge neutral">{'★'.repeat(stars)} 熟悉度</span>
  }

  // 文本批量导入
  const handleImport = async () => {
    if (!importText.trim()) return toast('请输入单词内容')
    setImporting(true)
    setImportResult(null)
    try {
      const deckId = packSel !== 'core' ? Number(packSel) : null
      const result = await wordsApi.importText({ text: importText, deck_id: deckId })
      setImportResult(result)
      toast(`导入完成：成功 ${result.imported} 个，跳过 ${result.skipped} 个`)
      const backendWords = await wordsApi.list({ page: 1, page_size: 500 })
      if (backendWords && backendWords.length > 0) {
        const formattedWords = backendWords.map(w => ({
          id: w.id, word: w.word, phonetic: w.phonetic, pos: w.pos,
          meaning: w.meaning, root: w.root, example: w.example,
          ex_cn: w.example_cn, tag: w.tag, frequency: w.frequency,
          deck: w.deck_id ? String(w.deck_id) : 'core',
          status: w.status || 'new', ef: w.ease_factor || 2.5,
          interval: w.interval || 0, reps: w.reps || 0, lapses: w.lapses || 0,
          due: w.due_date ? w.due_date : todayStr(),
          lastReview: w.last_review, history: w.review_history || []
        }))
        setWords(formattedWords)
      }
    } catch (e) {
      toast(`导入失败: ${e.message}`)
    } finally {
      setImporting(false)
    }
  }

  // Excel批量导入
  const handleExcelImport = async () => {
    if (!excelFile) return toast('请选择Excel文件')
    setImporting(true)
    setImportResult(null)
    try {
      const formData = new FormData()
      formData.append('file', excelFile)
      if (packSel !== 'core') formData.append('deck_id', packSel)
      const result = await wordsApi.importExcel(formData)
      setImportResult(result)
      toast(`Excel导入完成：成功 ${result.imported} 个，跳过 ${result.skipped} 个`)
      const backendWords = await wordsApi.list({ page: 1, page_size: 500 })
      if (backendWords && backendWords.length > 0) {
        const formattedWords = backendWords.map(w => ({
          id: w.id, word: w.word, phonetic: w.phonetic, pos: w.pos,
          meaning: w.meaning, root: w.root, example: w.example,
          ex_cn: w.example_cn, tag: w.tag, frequency: w.frequency,
          deck: w.deck_id ? String(w.deck_id) : 'core',
          status: w.status || 'new', ef: w.ease_factor || 2.5,
          interval: w.interval || 0, reps: w.reps || 0, lapses: w.lapses || 0,
          due: w.due_date ? w.due_date : todayStr(),
          lastReview: w.last_review, history: w.review_history || []
        }))
        setWords(formattedWords)
      }
    } catch (e) {
      toast(`Excel导入失败: ${e.message}`)
    } finally {
      setImporting(false)
      setExcelFile(null)
    }
  }

  const addNewDeck = () => {
    if (!deckName.trim()) return toast('请输入词库名称')
    addDeck(deckName.trim())
    toast('词库已创建')
    setDeckName('')
  }

  const handleRemoveWord = async (id) => {
    try { await wordsApi.remove(id) } catch (err) { console.warn('后端删除失败:', err.message) }
    removeWord(id)
    toast('单词已删除')
  }

  // 保存每日配额
  const saveQuota = (val) => {
    setDailyQuota(val)
    localStorage.setItem('words_daily_quota', String(val))
    toast(`每日新词配额已设置为 ${val} 个`)
  }

  // 计算会话统计
  const sessionTotal = sessionStats.again + sessionStats.hard + sessionStats.good + sessionStats.easy
  const sessionCorrect = sessionStats.good + sessionStats.easy
  const sessionAccuracy = sessionTotal > 0 ? Math.round(sessionCorrect / sessionTotal * 100) : 0
  const sessionDuration = sessionStats.startTime ? Math.round((Date.now() - sessionStats.startTime) / 1000 / 60) : 0

  return (
    <div className="container stack">
      <div className="page-head">
        <div>
          <h1 className="page-title">单词记忆</h1>
          <p className="page-sub">SM-2 间隔重复 · 四档评分 · 每日配额 · 真题例句（对标不背单词 / 墨墨背单词）</p>
        </div>
        <div className="page-actions">
          <button className={`btn ghost ${flashcard ? 'active' : ''}`} onClick={() => setFlashcard((v) => !v)}>
            试卷模式
          </button>
          <button className="btn primary" onClick={() => setShowImport(true)}>📥 批量导入</button>
        </div>
      </div>

      {/* 统计条 */}
      <div className="stat-grid">
        <div className="stat-tile"><span className="st-ico blue"><Book size={20} /></span><span className="st-val">{words.length}</span><span className="st-label">总词数</span></div>
        <div className="stat-tile"><span className="st-ico red"><Target size={20} /></span><span className="st-val" style={{ color: 'var(--red)' }}>{due.length}</span><span className="st-label">今日待复习</span></div>
        <div className="stat-tile"><span className="st-ico amber"><Clock size={20} /></span><span className="st-val" style={{ color: 'var(--gold)' }}>{learning}</span><span className="st-label">学习中</span></div>
        <div className="stat-tile"><span className="st-ico green"><CheckCircle size={20} /></span><span className="st-val" style={{ color: 'var(--green)' }}>{learned}</span><span className="st-label">已掌握</span></div>
      </div>

      {/* 视图切换 */}
      <Segmented options={[
        { label: '今日复习', value: 'learn' },
        { label: '学习总结', value: 'summary' },
        { label: '词库列表', value: 'list' },
        { label: '词库管理', value: 'decks' }
      ]} value={view} onChange={setView} />

      {/* 学习视图 */}
      {view === 'learn' && (
        queue.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: '40px 16px' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>✓</div>
            <div className="card-title">今日单词已全部复习完成</div>
            <p className="card-sub">新增/导入单词后会按遗忘曲线自动排入复习</p>
            <button className="btn primary" style={{ marginTop: 16 }} onClick={startSession}>
              <RefreshCw size={16} style={{ marginRight: 6 }} /> 重新开始今日复习
            </button>
          </div>
        ) : current ? (
          <div className="card">
            {/* 顶部进度和导航 */}
            <div className="spread" style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <MasteryPie level={current.reps || 0} size={28} />
                <span className="badge accent">{current.tag || current.deck || '单词'}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button className="btn icon ghost" onClick={prevWord} disabled={curIdx === 0} title="上一个">
                  <ChevronLeft size={18} />
                </button>
                <span className="badge neutral">{curIdx + 1} / {queue.length}</span>
                <button className="btn icon ghost" onClick={nextWord} disabled={curIdx >= queue.length - 1} title="下一个（跳过）">
                  <ChevronRight size={18} />
                </button>
              </div>
            </div>

            {/* 进度条 */}
            <div className="progress thin" style={{ marginBottom: 16 }}>
              <i style={{ width: `${((curIdx + 1) / queue.length) * 100}%` }} />
            </div>

            {/* 单词卡片主体 */}
            <div style={{ textAlign: 'center', padding: '20px 0' }}>
              <div className="row" style={{ justifyContent: 'center', gap: 12, alignItems: 'center' }}>
                <div className="page-title" style={{ fontSize: 36, fontWeight: 700 }}>{current.word}</div>
                <button className="btn icon ghost" onClick={() => pronounce(current.word)} aria-label="朗读" style={{ padding: 8 }}>
                  <Play size={22} />
                </button>
              </div>
              {!flashcard && current.phonetic && (
                <div className="card-sub" style={{ marginTop: 8, fontSize: 16, color: 'var(--ink-2)' }}>
                  {current.phonetic}
                </div>
              )}

              {!flashcard && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 18, color: 'var(--ink)' }}>
                    {current.pos && <span style={{ color: 'var(--accent)', marginRight: 8, fontStyle: 'italic' }}>{current.pos}</span>}
                    {current.meaning}
                  </div>
                  {current.root && (
                    <div className="card-sub" style={{ marginTop: 10, padding: '8px 12px', background: 'var(--violet-soft)', borderRadius: 8, display: 'inline-block' }}>
                      🌱 词根：{current.root}
                    </div>
                  )}
                  {showAns && current.example && (
                    <div style={{ marginTop: 16, fontSize: 14, lineHeight: 1.8, background: 'var(--surface-2)', borderRadius: 12, padding: 16, textAlign: 'left' }}>
                      <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--accent)' }}>📖 真题例句</div>
                      <div style={{ marginBottom: 4 }}>{current.example}</div>
                      {current.ex_cn && <div className="card-sub" style={{ marginTop: 4 }}>{current.ex_cn}</div>}
                    </div>
                  )}
                </div>
              )}

              {flashcard && showAns && (
                <div style={{ fontSize: 18, marginTop: 16 }}>
                  {current.pos && <span style={{ color: 'var(--accent)', marginRight: 8 }}>{current.pos}</span>}
                  {current.meaning}
                </div>
              )}

              <div style={{ marginTop: 20, display: 'flex', justifyContent: 'center', gap: 24, fontSize: 12, color: 'var(--ink-3)' }}>
                <span>复习 {current.reps || 0} 次</span>
                <span>间隔 {current.interval || 0} 天</span>
                <span>EF {current.ef?.toFixed(1) || '2.5'}</span>
              </div>
            </div>

            {/* 操作按钮 */}
            {!showAns ? (
              <button className="btn primary block" style={{ fontSize: 16, padding: '12px' }} onClick={() => setShowAns(true)}>
                显示释义
              </button>
            ) : (
              <div>
                <div className="grid-4" style={{ gap: 8, marginBottom: 8 }}>
                  <button className="btn" onClick={() => grade(GRADE.AGAIN)}
                    style={{ background: 'var(--red-soft)', color: 'var(--red)', border: 'none', padding: '12px 4px' }}>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>忘记</div>
                    <div style={{ fontSize: 11, opacity: 0.8 }}>10分钟后</div>
                  </button>
                  <button className="btn" onClick={() => grade(GRADE.HARD)}
                    style={{ background: 'var(--gold-soft)', color: 'var(--gold)', border: 'none', padding: '12px 4px' }}>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>模糊</div>
                    <div style={{ fontSize: 11, opacity: 0.8 }}>{Math.max(1, Math.round((current.interval || 1) * 0.6))}天后</div>
                  </button>
                  <button className="btn" onClick={() => grade(GRADE.GOOD)}
                    style={{ background: 'var(--accent-soft)', color: 'var(--accent)', border: 'none', padding: '12px 4px' }}>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>记得</div>
                    <div style={{ fontSize: 11, opacity: 0.8 }}>{Math.round((current.interval || 1) * (current.ef || 2.5))}天后</div>
                  </button>
                  <button className="btn primary" onClick={() => grade(GRADE.EASY)}
                    style={{ padding: '12px 4px' }}>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>简单</div>
                    <div style={{ fontSize: 11, opacity: 0.8 }}>{Math.round((current.interval || 1) * (current.ef || 2.5) * 1.3)}天后</div>
                  </button>
                </div>
                <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--ink-3)' }}>
                  快捷键：1=忘记 2=模糊 3=记得 4=简单
                </div>
              </div>
            )}
          </div>
        ) : null
      )}

      {/* 学习总结视图 */}
      {view === 'summary' && (
        <div className="card" style={{ padding: 24 }}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>🎉</div>
            <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 4 }}>本轮学习完成！</h2>
            <p className="card-sub">继续保持，每天进步一点点</p>
          </div>

          {/* 核心统计 */}
          <div className="stat-grid" style={{ marginBottom: 24 }}>
            <div className="stat-tile">
              <span className="st-ico blue"><Book size={20} /></span>
              <span className="st-val">{sessionTotal}</span>
              <span className="st-label">学习单词</span>
            </div>
            <div className="stat-tile">
              <span className="st-ico green"><CheckCircle size={20} /></span>
              <span className="st-val" style={{ color: 'var(--green)' }}>{sessionAccuracy}%</span>
              <span className="st-label">正确率</span>
            </div>
            <div className="stat-tile">
              <span className="st-ico amber"><Check size={20} /></span>
              <span className="st-val" style={{ color: 'var(--gold)' }}>{sessionCorrect}</span>
              <span className="st-label">掌握词数</span>
            </div>
            <div className="stat-tile">
              <span className="st-ico red"><Target size={20} /></span>
              <span className="st-val" style={{ color: 'var(--red)' }}>{sessionStats.again}</span>
              <span className="st-label">需巩固</span>
            </div>
          </div>

          {/* 评分分布 */}
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>评分分布</h3>
            <div style={{ display: 'flex', gap: 8, height: 24, borderRadius: 8, overflow: 'hidden' }}>
              {sessionTotal > 0 && (
                <>
                  <div style={{ width: `${sessionStats.again / sessionTotal * 100}%`, background: 'var(--red)' }} title={`忘记 ${sessionStats.again}`} />
                  <div style={{ width: `${sessionStats.hard / sessionTotal * 100}%`, background: 'var(--gold)' }} title={`模糊 ${sessionStats.hard}`} />
                  <div style={{ width: `${sessionStats.good / sessionTotal * 100}%`, background: 'var(--accent)' }} title={`记得 ${sessionStats.good}`} />
                  <div style={{ width: `${sessionStats.easy / sessionTotal * 100}%`, background: 'var(--green)' }} title={`简单 ${sessionStats.easy}`} />
                </>
              )}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12, color: 'var(--ink-3)' }}>
              <span style={{ color: 'var(--red)' }}>忘记 {sessionStats.again}</span>
              <span style={{ color: 'var(--gold)' }}>模糊 {sessionStats.hard}</span>
              <span style={{ color: 'var(--accent)' }}>记得 {sessionStats.good}</span>
              <span style={{ color: 'var(--green)' }}>简单 {sessionStats.easy}</span>
            </div>
          </div>

          {/* 每日配额设置 */}
          <div style={{ marginBottom: 24, padding: 16, background: 'var(--surface-2)', borderRadius: 12 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>每日新词配额</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <input type="range" min="10" max="100" step="5" value={dailyQuota}
                onChange={(e) => saveQuota(Number(e.target.value))}
                style={{ flex: 1 }} />
              <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent)', minWidth: 60, textAlign: 'center' }}>
                {dailyQuota} 个/天
              </span>
            </div>
            <p className="card-sub" style={{ marginTop: 8 }}>复习词不受配额限制，新词每天最多学习 {dailyQuota} 个</p>
          </div>

          {/* 操作按钮 */}
          <div style={{ display: 'flex', gap: 12 }}>
            <button className="btn primary" style={{ flex: 1 }} onClick={startSession}>
              <RefreshCw size={16} style={{ marginRight: 6 }} /> 再来一轮
            </button>
            <button className="btn ghost" style={{ flex: 1 }} onClick={() => setView('list')}>
              查看词库列表
            </button>
          </div>
        </div>
      )}

      {/* 词库列表视图 */}
      {view === 'list' && (
        <div className="card flush">
          <div className="card-head" style={{ padding: '14px 18px' }}>
            <b className="card-title">单词列表（{words.length}）</b>
            <div className="search" style={{ maxWidth: 240 }}>
              <span>🔍</span>
              <input placeholder="搜索单词…" />
            </div>
          </div>
          {loading ? (
            <div className="loading-inline">正在加载单词…</div>
          ) : words.length === 0 ? (
            /* 批次2-2：单词列表为空时接入统一 Empty，替代此前空白卡片 */
            <div style={{ padding: '12px' }}>
              <Empty icon={<span style={{ fontSize: 32 }}>🔤</span>} title="还没有单词" desc="点击右上角「批量导入」粘贴文本或上传 Excel，系统会按遗忘曲线自动排复习" />
            </div>
          ) : (
          <div className="list" style={{ padding: '0 12px 12px' }}>
            {words.slice(0, 200).map((w) => (
              <div key={w.id} className="list-row">
                <MasteryPie level={w.reps || 0} size={28} />
                <button className="lr-ico" style={{ border: 'none', cursor: 'pointer', background: 'var(--accent-soft)', color: 'var(--accent)' }} onClick={() => pronounce(w.word)} aria-label="朗读">
                  <Play size={16} />
                </button>
                <div className="lr-main">
                  <div className="lr-title">{w.word}{w.phonetic && <span className="card-sub" style={{ marginLeft: 8 }}>{w.phonetic}</span>}</div>
                  <div className="lr-meta">{w.pos} {w.meaning}</div>
                </div>
                <div className="lr-actions">
                  {wordBadge(w)}
                  <button className="btn sm ghost" onClick={() => gradeWord(w.id, GRADE.AGAIN)} style={{ color: 'var(--red)' }}>忘</button>
                  <button className="btn sm ghost" onClick={() => gradeWord(w.id, GRADE.HARD)} style={{ color: 'var(--gold)' }}>难</button>
                  <button className="btn sm ghost" onClick={() => gradeWord(w.id, GRADE.GOOD)} style={{ color: 'var(--accent)' }}>良</button>
                  <button className="btn sm primary" onClick={() => gradeWord(w.id, GRADE.EASY)}>易</button>
                  <button className="btn sm danger" onClick={() => handleRemoveWord(w.id)}>删</button>
                </div>
              </div>
            ))}
            {words.length > 200 && (
              <div style={{ textAlign: 'center', padding: 12, color: 'var(--ink-3)', fontSize: 13 }}>
                仅显示前 200 个，共 {words.length} 个单词
              </div>
            )}
          </div>
          )}
        </div>
      )}

      {/* 词库管理视图 */}
      {view === 'decks' && (
        <div className="card">
          <div className="card-head"><b className="card-title">词库管理</b></div>
          {decks.length === 0 ? (
            /* 批次2-2：词库为空时接入统一 Empty */
            <Empty icon={<span style={{ fontSize: 32 }}>📚</span>} title="还没有词库" desc="在下方输入新词库名称并创建，或从后端同步默认词库" />
          ) : (
          <div className="grid-3">
            {decks.map((d, i) => (
              <div key={d.id} className="card" style={{ borderColor: SUBJECT_COLOR[i % 5], cursor: 'pointer' }}
                onClick={() => { setPackSel(String(d.id)); setView('learn'); toast(`已切换到词库：${d.name}`) }}>
                <b className="card-title">{d.name}</b>
                <div className="card-sub" style={{ marginTop: 4 }}>{d.count} 词 · {d.source}</div>
                {d.description && <div className="card-sub" style={{ marginTop: 4, fontSize: 11 }}>{d.description}</div>}
              </div>
            ))}
          </div>
          )}
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            <input className="input" style={{ flex: 1 }} placeholder="新词库名称（如：红宝书 Unit1）" value={deckName} onChange={(e) => setDeckName(e.target.value)} />
            <button className="btn primary" onClick={addNewDeck}>创建词库</button>
          </div>
        </div>
      )}

      {/* 导入弹窗 */}
      <Modal open={showImport} title="批量导入单词" onClose={() => { setShowImport(false); setImportResult(null); setExcelFile(null); }}>
          <p style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 8 }}>
            支持两种导入方式：文本粘贴 或 Excel文件上传
          </p>

          <label style={{ display: 'block', marginBottom: 12 }}>
            导入到词库
            <select className="input" value={packSel} onChange={(e) => setPackSel(e.target.value)}>
              <option value="core">默认词库</option>
              {decks.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.count}个)</option>)}
            </select>
          </label>

          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, display: 'block' }}>文本粘贴（每行一个单词）</label>
            <p style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 6 }}>
              支持格式：<code>apple 苹果</code>、<code>apple n. 苹果</code>、<code>apple /ˈæpl/ n. 苹果</code>
            </p>
            <textarea className="input" rows={6}
              placeholder={'abandon 放弃；抛弃\nabnormal /æbˈnɔːml/ adj. 反常的\nacademic n. 学者；adj. 学术的'}
              value={importText} onChange={(e) => setImportText(e.target.value)} />
            <button className="btn primary" style={{ marginTop: 8, width: '100%' }}
              onClick={handleImport} disabled={importing || !importText.trim()}>
              {importing ? '导入中...' : '开始文本导入'}
            </button>
          </div>

          <div style={{ marginBottom: 12, paddingTop: 12, borderTop: '1px solid var(--surface-3)' }}>
            <label style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, display: 'block' }}>Excel文件上传</label>
            <p style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 6 }}>
              必须包含列：<b>单词</b>、<b>释义</b>；可选列：音标、词性、词根、例句、例句翻译、标签
            </p>
            <input type="file" accept=".xlsx,.xls" onChange={(e) => setExcelFile(e.target.files[0])} style={{ marginBottom: 8 }} />
            {excelFile && <div style={{ fontSize: 12, color: 'var(--ink-2)', marginBottom: 8 }}>已选择：{excelFile.name}</div>}
            <button className="btn primary" style={{ width: '100%' }}
              onClick={handleExcelImport} disabled={importing || !excelFile}>
              {importing ? '导入中...' : '开始Excel导入'}
            </button>
          </div>

          {importResult && (
            <div style={{ marginTop: 12, padding: 12, background: 'var(--surface-2)', borderRadius: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>导入结果</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <div style={{ textAlign: 'center', padding: 8, background: 'var(--green)', color: '#fff', borderRadius: 6 }}>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{importResult.imported}</div>
                  <div style={{ fontSize: 11 }}>成功导入</div>
                </div>
                <div style={{ textAlign: 'center', padding: 8, background: 'var(--gold)', color: '#fff', borderRadius: 6 }}>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{importResult.skipped}</div>
                  <div style={{ fontSize: 11 }}>跳过（重复/无效）</div>
                </div>
              </div>
            </div>
          )}
      </Modal>
    </div>
  )
}
