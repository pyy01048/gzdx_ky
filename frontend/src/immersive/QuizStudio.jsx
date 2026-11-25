import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import ImmersiveLayout from './ImmersiveLayout'
import Disclosure from './Disclosure'
import { cx, Ic, Chip, Empty, Stat } from './lib'
import { quizApi, taxonomyApi } from '../api/client'
import {
  AlertCircle, BookOpen, Brain, Check, CheckCircle, ChevronLeft, ChevronRight,
  Eye, Keyboard, Layers, RefreshCw, Target, X,
} from '../v3/icons'

const TYPE_LABEL = { single: '单选', multiple: '多选', judge: '判断', fill: '填空', calc: '计算', essay: '简答', draw: '作图', proof: '证明', other: '其他' }
const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']

function safeParseOptions(raw) {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'string') {
    try { const p = JSON.parse(raw); return Array.isArray(p) ? p : [] } catch { return [] }
  }
  return []
}
function normalizeOptions(raw) {
  const arr = safeParseOptions(raw)
  const out = []
  arr.forEach((o, i) => {
    if (o == null) return
    let key, text
    if (typeof o === 'string') { key = LETTERS[i]; text = o }
    else { key = o.key || o.label || LETTERS[i]; text = o.text ?? o.value ?? o.label ?? '' }
    if (String(text).trim()) out.push({ key: String(key).toUpperCase(), text: String(text).trim() })
  })
  return out
}
function normQ(q) {
  return {
    id: String(q.id),
    content: q.content || '',
    options: normalizeOptions(q.options),
    answer: q.answer ?? '',
    analysis: q.analysis || '',
    subject: q.subject || '',
    chapter: q.chapter || '',
    knowledge_point: q.knowledge_point || '',
    difficulty: q.difficulty || 1,
    source: q.source || q.source_label || '',
    question_type: q.question_type || '',
    answer_type: q.answer_type || '',
    quality: q.quality || '',
    is_available: q.is_available,
  }
}
function answerLetters(ans) {
  if (!ans) return []
  const s = String(ans).replace(/[\s,，、;；]/g, '').toUpperCase()
  return [...s].filter((c) => /[A-Z]/.test(c))
}
function judgeAns(ans) {
  const s = String(ans || '').trim()
  if (/^(正确|对|√|T|TRUE|Y|是)$/i.test(s)) return 'T'
  if (/^(错误|错|×|F|FALSE|N|否)$/i.test(s)) return 'F'
  return s.toUpperCase()
}
const isChoice = (q) => q.options.length >= 2

export default function QuizStudio() {
  const navigate = useNavigate()
  const [sp] = useSearchParams()
  const paramSubject = sp.get('subject')
  const paramType = sp.get('question_type')
  const paramKp = sp.get('kp_id')

  const [subjects, setSubjects] = useState([])
  const [subject, setSubject] = useState(paramSubject || '')
  const [questions, setQuestions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [idx, setIdx] = useState(0)
  const [answers, setAnswers] = useState({})
  const [revealed, setRevealed] = useState({})
  const [flagged, setFlagged] = useState(new Set())
  const [typeFilter, setTypeFilter] = useState(paramType || 'all')

  // 1) 取科目清单（公开接口），确定默认科目
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const d = await taxonomyApi.subjects()
        const list = (d?.subjects || []).filter((s) => (s.question_count || 0) > 0)
        if (!alive) return
        setSubjects(list)
        if (!paramSubject) {
          const top = [...list].sort((a, b) => (b.question_count || 0) - (a.question_count || 0))[0]
          if (top) setSubject(top.subject)
        }
      } catch { /* 忽略，用 paramSubject */ }
    })()
    return () => { alive = false }
  }, [paramSubject])

  // 2) 拉题
  const load = useCallback(async () => {
    if (!subject) return
    setLoading(true); setError(''); setIdx(0); setAnswers({}); setRevealed({})
    const params = { subject, question_type: paramType || undefined, kp_id: paramKp || undefined, page: 1, page_size: 200 }
    try {
      let d = await quizApi.questions({ ...params, answerable: true })
      let qs = (d?.questions || d?.items || []).map(normQ)
      if (!qs.length) {
        d = await quizApi.questions({ ...params, answerable: false })
        qs = (d?.questions || d?.items || []).map(normQ)
      }
      if (!qs.length) {
        // 来源回退：去掉 answerable 也无则再试不带 type
        d = await quizApi.questions({ subject, page: 1, page_size: 200 })
        qs = (d?.questions || d?.items || []).map(normQ)
      }
      setQuestions(qs)
    } catch (e) {
      setError(e?.message || '题目加载失败')
    } finally {
      setLoading(false)
    }
  }, [subject, paramType, paramKp])

  useEffect(() => { load() }, [load])

  const filtered = useMemo(() => {
    if (typeFilter === 'all') return questions
    return questions.filter((q) => q.question_type === typeFilter)
  }, [questions, typeFilter])

  const typeCounts = useMemo(() => {
    const m = { all: questions.length }
    questions.forEach((q) => { m[q.question_type] = (m[q.question_type] || 0) + 1 })
    return m
  }, [questions])

  const q = filtered[idx]
  const total = filtered.length
  const progress = total ? Math.round(((idx + 1) / total) * 100) : 0
  const doneCount = Object.values(revealed).filter(Boolean).length

  const selectOption = useCallback((key) => {
    if (!q) return
    if (q.question_type === 'multiple') {
      setAnswers((a) => {
        const cur = a[q.id] || []
        const next = cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key].sort()
        return { ...a, [q.id]: next }
      })
    } else {
      setAnswers((a) => ({ ...a, [q.id]: key }))
    }
  }, [q])

  const reveal = useCallback(async () => {
    if (!q) return
    setRevealed((r) => ({ ...r, [q.id]: true }))
    const ans = answers[q.id]
    if (ans) {
      try { await quizApi.submit({ question_id: q.id, my_answer: Array.isArray(ans) ? ans.join(',') : ans }) } catch { /* 静默 */ }
    }
  }, [q, answers])

  const toggleFlag = useCallback(() => {
    if (!q) return
    setFlagged((s) => {
      const n = new Set(s); n.has(q.id) ? n.delete(q.id) : n.add(q.id); return n
    })
  }, [q])

  const correctAns = useMemo(() => {
    if (!q) return []
    if (q.question_type === 'judge') return [judgeAns(q.answer)]
    return answerLetters(q.answer)
  }, [q])

  const userAns = q ? answers[q.id] : undefined
  const isRevealed = q ? !!revealed[q.id] : false

  const optionState = (key) => {
    if (!isRevealed) return userAns === key || (Array.isArray(userAns) && userAns.includes(key)) ? 'is-selected' : ''
    if (correctAns.includes(key)) return 'is-correct'
    if (userAns === key || (Array.isArray(userAns) && userAns.includes(key))) return 'is-wrong'
    return ''
  }

  // 作答判定：correct / wrong / unanswered / neutral(主观题)
  const verdict = useMemo(() => {
    if (!q || !isRevealed) return null
    if (q.question_type === 'judge') {
      if (!userAns) return 'unanswered'
      return correctAns[0] === userAns ? 'correct' : 'wrong'
    }
    if (isChoice(q)) {
      const empty = !userAns || (Array.isArray(userAns) && userAns.length === 0)
      if (empty) return 'unanswered'
      const ua = (Array.isArray(userAns) ? [...userAns] : [userAns]).sort().join(',')
      const ca = [...correctAns].sort().join(',')
      return ua === ca ? 'correct' : 'wrong'
    }
    return 'neutral'
  }, [q, isRevealed, userAns, correctAns])

  // 键盘快捷键：← → 切题，Enter/Space 显示答案，1-9 / A-J 选选项，F 标记
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target
      if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(total - 1, i + 1)) }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(0, i - 1)) }
      else if (e.key === 'Enter' || e.key === ' ') { if (q && !isRevealed) { e.preventDefault(); reveal() } }
      else if (e.key === 'f' || e.key === 'F') { toggleFlag() }
      else if (/^[1-9]$/.test(e.key)) {
        const n = Number(e.key) - 1
        if (q && isChoice(q) && q.options[n] && !isRevealed) selectOption(q.options[n].key)
      } else if (/^[a-jA-J]$/.test(e.key)) {
        const k = e.key.toUpperCase()
        if (q && isChoice(q) && q.options.some((o) => o.key === k) && !isRevealed) selectOption(k)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [q, total, isRevealed, reveal, toggleFlag, selectOption])

  const leftRail = (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12, padding: '0 4px' }}>
        {['all', 'single', 'multiple', 'judge', 'fill', 'essay'].map((t) => typeCounts[t] ? (
          <button
            key={t}
            className={cx('im-chip', typeFilter === t && 'im-chip--accent')}
            onClick={() => { setTypeFilter(t); setIdx(0) }}
            style={{ cursor: 'pointer' }}
          >
            {t === 'all' ? '全部' : TYPE_LABEL[t] || t} {typeCounts[t]}
          </button>
        ) : null)}
      </div>
      <div className="im-qnav">
        {filtered.map((qq, i) => {
          const done = !!revealed[qq.id]
          const active = i === idx
          return (
            <button
              key={qq.id}
              className={cx('im-qnav__btn', active && 'is-active', done && 'is-done', flagged.has(qq.id) && 'is-flag')}
              onClick={() => setIdx(i)}
              title={`第 ${i + 1} 题 · ${TYPE_LABEL[qq.question_type] || qq.question_type}`}
            >
              {i + 1}
            </button>
          )
        })}
      </div>
    </div>
  )

  const rightRail = q ? (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="im-card im-card__pad" style={{ padding: 14 }}>
        <div style={{ fontSize: 12, color: 'var(--im-text-subtle)', marginBottom: 6 }}>题目信息</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
          <MetaRow label="题型" value={TYPE_LABEL[q.question_type] || q.question_type || '—'} />
          <MetaRow label="科目" value={q.subject || subject} />
          <MetaRow label="章节" value={q.chapter || '—'} />
          <MetaRow label="难度" value={'★'.repeat(Math.min(5, Math.max(1, Number(q.difficulty) || 1)))} />
          {q.knowledge_point && <MetaRow label="知识点" value={q.knowledge_point} />}
          {q.source && <MetaRow label="来源" value={q.source} />}
        </div>
      </div>
      <button
        className="im-btn im-btn--sm"
        style={{ justifyContent: 'flex-start' }}
        onClick={() => navigate(`/studio/subject/${encodeURIComponent(q.subject || subject)}`)}
      >
        <Ic of={BookOpen} size={14} /> 复习本科目知识地图
      </button>
      <div style={{ fontSize: 11.5, color: 'var(--im-text-subtle)', lineHeight: 1.6, padding: '0 4px' }}>
        提示：点击「显示答案」后记录作答；题序侧栏可收起，把空间让给题干。
      </div>
    </div>
  ) : null

  return (
    <ImmersiveLayout
      title="沉浸式刷题"
      subtitle={subject || '选择科目开始'}
      subject={subject}
      progress={progress}
      progressLabel={`第 ${idx + 1} / ${total} 题 · 已做 ${doneCount}`}
      left={leftRail} leftTitle="题序" leftIcon={Layers}
      right={rightRail} rightTitle="题目信息" rightIcon={Target}
      defaultLeftOpen
      actions={
        <select
          className="im-btn im-btn--sm"
          style={{ minWidth: 110, cursor: 'pointer' }}
          value={subject}
          onChange={(e) => { setSubject(e.target.value); setTypeFilter('all') }}
          aria-label="选择科目"
        >
          {subjects.length === 0 && <option value={subject}>{subject}</option>}
          {subjects.map((s) => (
            <option key={s.subject} value={s.subject}>{s.subject}（{s.question_count}）</option>
          ))}
        </select>
      }
    >
      <div className="im-hero">
        <div>
          <h1>{subject || '加载中…'}</h1>
          <p>全屏专注模式：收起侧栏把空间还给题干，做完自动记录，薄弱点随时跳回知识地图复习。</p>
        </div>
        <div className="im-hero__stats">
          <Stat value={total} label="本题单" />
          <Stat value={doneCount} label="已作答" tone="success" />
          <Stat value={flagged.size} label="已标记" tone="warning" />
        </div>
      </div>

      {loading ? (
        <div style={{ display: 'grid', gap: 12 }}>
          <div style={{ height: 22 }} className="im-skeleton" />
          <div style={{ height: 90 }} className="im-skeleton" />
          <div style={{ height: 48 }} className="im-skeleton" />
          <div style={{ height: 48 }} className="im-skeleton" />
        </div>
      ) : error ? (
        <Empty icon={AlertCircle} title="加载失败" hint={error} action={<button className="im-btn im-btn--primary" onClick={load}><Ic of={RefreshCw} size={15} /> 重试</button>} />
      ) : total === 0 ? (
        <Empty
          icon={BookOpen}
          title="该范围暂无可用题目"
          hint="换个科目或题型试试，或先到知识地图把知识点和题目关联起来。"
          action={<button className="im-btn im-btn--primary" onClick={() => navigate('/knowledge')}><Ic of={BookOpen} size={15} /> 去知识地图</button>}
        />
      ) : q ? (
        <div className="im-card im-card__pad" style={{ padding: '26px 30px' }}>
          <div className="im-q">
            <div className="im-q__head">
              <span className="im-q__index">第 {idx + 1} / {total} 题</span>
              <Chip tone="accent">{TYPE_LABEL[q.question_type] || q.question_type}</Chip>
              {flagged.has(q.id) && <Chip tone="warn">已标记</Chip>}
              <div style={{ marginLeft: 'auto' }}>
                <button className="im-btn im-btn--sm" onClick={toggleFlag}>
                  <Ic of={Target} size={14} /> {flagged.has(q.id) ? '取消标记' : '标记'}
                </button>
              </div>
            </div>

            <div className="im-q__stem">{q.content || '（题干为空）'}</div>

            {isChoice(q) ? (
              <div className="im-options">
                {q.options.map((op) => (
                  <div
                    key={op.key}
                    className={cx('im-option', optionState(op.key))}
                    onClick={() => !isRevealed && selectOption(op.key)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); !isRevealed && selectOption(op.key) } }}
                  >
                    <span className="im-option__key">{op.key}</span>
                    <span className="im-option__text">{op.text}</span>
                  </div>
                ))}
              </div>
            ) : q.question_type === 'judge' ? (
              <div className="im-options" style={{ flexDirection: 'row' }}>
                {['T', 'F'].map((k) => (
                  <div
                    key={k}
                    className={cx('im-option', optionState(k))}
                    style={{ flex: 1, justifyContent: 'center' }}
                    onClick={() => !isRevealed && selectOption(k)}
                    role="button" tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); !isRevealed && selectOption(k) } }}
                  >
                    <span className="im-option__key">{k}</span>
                    <span className="im-option__text">{k === 'T' ? '正确' : '错误'}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: 12, background: 'var(--im-surface-2)', borderRadius: 9, fontSize: 13, color: 'var(--im-text-muted)' }}>
                <Ic of={Brain} size={14} /> 主观题 · 请先在脑中作答，再展开查看参考答案与解析。
              </div>
            )}

            {!isRevealed ? (
              <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
                <button className="im-btn im-btn--primary" onClick={reveal}>
                  <Ic of={Eye} size={15} /> 显示答案与解析
                </button>
              </div>
            ) : (
              <>
                {verdict === 'correct' && (
                  <div className="im-result is-correct"><Ic of={CheckCircle} size={18} /> 回答正确<span className="im-result__spacer" /><span className="im-result__sub">保持节奏</span></div>
                )}
                {verdict === 'wrong' && (
                  <div className="im-result is-wrong"><Ic of={X} size={18} /> 回答错误<span className="im-result__spacer" /><span className="im-result__sub">正确答案已标出</span></div>
                )}
                {verdict === 'unanswered' && (
                  <div className="im-result is-neutral"><Ic of={Eye} size={18} /> 未作答<span className="im-result__spacer" /><span className="im-result__sub">已显示参考答案</span></div>
                )}
                {verdict === 'neutral' && (
                  <div className="im-result is-neutral"><Ic of={Check} size={18} /> 已查看参考答案</div>
                )}
                <div className="im-answer">
                  <div className="im-answer__label">参考答案</div>
                  <div className="im-answer__value">{q.answer || '（参考答案为空）'}</div>
                </div>
                {q.analysis && (
                  <Disclosure label={<>解析（{q.analysis.length} 字）</>} defaultOpen={false} className="im-analysis">
                    <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.85 }}>{q.analysis}</div>
                  </Disclosure>
                )}
              </>
            )}

            <div style={{ display: 'flex', gap: 10, marginTop: 14, paddingTop: 16, borderTop: '1px solid var(--im-border)' }}>
              <button className="im-btn" disabled={idx === 0} onClick={() => setIdx((i) => Math.max(0, i - 1))}>
                <Ic of={ChevronLeft} size={15} /> 上一题
              </button>
              <div style={{ flex: 1 }} />
              <button className="im-btn" onClick={() => setIdx((i) => Math.min(total - 1, i + 1))} disabled={idx === total - 1}>
                下一题 <Ic of={ChevronRight} size={15} />
              </button>
            </div>
            <div className="im-kbd" style={{ justifyContent: 'center', marginTop: 12, flexWrap: 'wrap', gap: 14 }}>
              <Ic of={Keyboard} size={13} />
              <span><kbd>←</kbd> <kbd>→</kbd> 切题</span>
              <span><kbd>Enter</kbd> 看答案</span>
              <span><kbd>1</kbd>-<kbd>9</kbd> 选选项</span>
              <span><kbd>F</kbd> 标记</span>
            </div>
          </div>
        </div>
      ) : null}
    </ImmersiveLayout>
  )
}

function MetaRow({ label, value }) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <span style={{ color: 'var(--im-text-subtle)', minWidth: 52 }}>{label}</span>
      <span style={{ color: 'var(--im-text)', flex: 1, wordBreak: 'break-word' }}>{value}</span>
    </div>
  )
}
