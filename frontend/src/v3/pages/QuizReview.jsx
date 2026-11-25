/**
 * 题库复核队列（/admin/quiz-review，仅管理员）
 *
 * 闭环处理 needs_review 题，分两类：
 *   - quarantined  隔离中：OCR 损坏（validation_errors 写明原因），已移出练习池，
 *                   可「编辑 → 修复后上架」或「永久下架」；
 *   - low_confidence 低置信：自动分类置信度低，仍在练习池，可「确认无误」或「永久下架」。
 * 后端：GET /api/quiz/review-queue · POST /api/quiz/review/{id}（routers/study/quiz.py）。
 * 非管理员手输 URL 由 RequireAdmin 送去 403。
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import '../styles/pages.css'
import { quizApi } from '../../api/client'
import {
  Button, Card, Badge, Chip, Input, Textarea, Empty, LoadingState, Segmented,
  Select, Alert, cx, toastOk, toastErr, PageHeader,
} from '../ui'
import { RefreshCw, Check, X, Edit, Trash, RotateCcw, AlertTriangle, Eye } from '../icons'

const STATUS_TABS = [
  { value: '', label: '全部' },
  { value: 'quarantined', label: '隔离待修复' },
  { value: 'low_confidence', label: '低置信待确认' },
]

const TYPE_LABEL = {
  single: '单选', multiple: '多选', judge: '判断',
  fill: '填空', calc: '计算', essay: '简答', draw: '作图', proof: '证明', other: '其他',
}

function sameJson(a, b) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

export default function QuizReview() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('')
  const [subject, setSubject] = useState('')
  const [subjects, setSubjects] = useState([])
  const [limit, setLimit] = useState(50)
  const [drafts, setDrafts] = useState({})   // id -> {content, options, answer, analysis}
  const [editing, setEditing] = useState({})  // id -> bool
  const [busyId, setBusyId] = useState(null)
  const alive = useRef(true)

  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const params = { limit }
      if (status) params.status = status
      if (subject) params.subject = subject
      const res = await quizApi.reviewQueue(params)
      if (!alive.current) return
      setItems(Array.isArray(res?.items) ? res.items : [])
      setTotal(res?.total || 0)
    } catch (e) {
      if (!alive.current) return
      setError(e)
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [limit, status, subject])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    quizApi.subjects()
      .then((s) => {
        const list = Array.isArray(s) ? s : (s?.items || s?.subjects || [])
        setSubjects(list.map((x) => (typeof x === 'string' ? { value: x, label: x } : { value: x?.name || x?.value, label: x?.name || x?.label || x?.value })))
      })
      .catch(() => {})
  }, [])

  const shownCounts = useMemo(() => {
    const c = { quarantined: 0, low_confidence: 0 }
    for (const it of items) c[it.status] = (c[it.status] || 0) + 1
    return c
  }, [items])

  const getDraft = (it) => drafts[it.id] || {
    content: it.content ?? '', options: it.options ?? [], answer: it.answer ?? '', analysis: it.analysis ?? '',
  }
  const setDraft = (id, patch) => setDrafts((d) => ({ ...d, [id]: { ...(d[id] || {}), ...patch } }))
  const isDirty = (it) => {
    const d = drafts[it.id]; if (!d) return false
    return !(sameJson(d.content, it.content) && sameJson(d.options, it.options)
      && sameJson(d.answer, it.answer) && sameJson(d.analysis, it.analysis))
  }

  const act = async (it, action) => {
    const edited = !!editing[it.id]
    const body = { action }
    if (edited) {
      const d = getDraft(it)
      body.content = d.content
      body.options = d.options
      body.answer = d.answer
      body.analysis = d.analysis
    }
    setBusyId(it.id)
    try {
      const res = await quizApi.reviewAction(it.id, body)
      toastOk(res?.message || '已处理')
      setItems((prev) => prev.filter((x) => x.id !== it.id))
      setTotal((t) => Math.max(0, t - 1))
      setDrafts((d) => { const n = { ...d }; delete n[it.id]; return n })
      setEditing((e) => { const n = { ...e }; delete n[it.id]; return n })
    } catch (e) {
      toastErr(e?.message || '处理失败，请重试')
    } finally {
      setBusyId(null)
    }
  }

  const confirmReject = (it) => {
    if (window.confirm(`确认永久作废该题？作废后移出练习与复核，不可在本页恢复。\n\n${String(it.content || '').slice(0, 80)}`)) {
      act(it, 'reject')
    }
  }

  const toggleEdit = (id) => setEditing((e) => ({ ...e, [id]: !e[id] }))

  // ---- 渲染 ----
  if (loading && items.length === 0) {
    return <div className="quiz-review"><LoadingState text="复核队列加载中…" /></div>
  }
  if (error && items.length === 0) {
    return (
      <div className="quiz-review">
        <Alert tone="danger" icon={<AlertTriangle size={18} />}>
          复核队列加载失败：{String(error?.message || '接口不可达')}
          <Button variant="text" size="sm" style={{ marginLeft: 12 }} onClick={() => load()}>重试</Button>
        </Alert>
      </div>
    )
  }

  return (
    <div className="quiz-review">
      <PageHeader
        eyebrow="题库治理"
        icon={<AlertTriangle size={18} />}
        title="题库复核队列"
        sub={`共 ${total} 条待复核：隔离待修复 ${shownCounts.quarantined} 条，低置信待确认 ${shownCounts.low_confidence} 条。修复后上架的题目会立即回到练习池。`}
        actions={
          <Button variant="filled" icon={<RefreshCw size={16} />} onClick={() => load()} loading={loading}>刷新</Button>
        }
      />

      <div className="quiz-review__filters">
        <Segmented options={STATUS_TABS} value={status} onChange={setStatus} ariaLabel="复核状态筛选" />
        <div className="quiz-review__filter-right">
          <Select
            aria-label="按科目筛选"
            placeholder="全部科目"
            value={subject}
            onChange={(v) => setSubject(v)}
            options={[{ value: '', label: '全部科目' }, ...subjects.filter((s) => s.value)]}
            style={{ minWidth: 180 }}
          />
        </div>
      </div>

      {items.length === 0 ? (
        <Empty
          icon={<Check size={32} />}
          title="复核队列为空"
          text={status || subject ? '当前筛选条件下没有待复核题目。' : '所有题目都已复核完毕，题库状态健康。'}
          action={<Button variant="filled" onClick={() => load()}>刷新</Button>}
        />
      ) : (
        <div className="quiz-review__list">
          {items.map((it) => {
            const isQ = it.status === 'quarantined'
            const ed = !!editing[it.id]
            const draft = getDraft(it)
            const dirty = isDirty(it)
            const busy = busyId === it.id
            return (
              <Card key={it.id} className={cx('quiz-review__card', isQ && 'is-quarantined')}>
                <div className="quiz-review__card-head">
                  <div className="quiz-review__card-meta">
                    <Badge tone={isQ ? 'warn' : 'info'}>{isQ ? '隔离中' : '低置信'}</Badge>
                    <Chip size="sm">{it.subject || '未分科'}</Chip>
                    <Chip size="sm">{TYPE_LABEL[it.question_type] || it.question_type}</Chip>
                    <span className="quiz-review__id">#{it.id}</span>
                    {it.classify_confidence != null && (
                      <span className="quiz-review__conf">置信 {Math.round(it.classify_confidence * 100)}%</span>
                    )}
                  </div>
                  <div className="quiz-review__card-actions">
                    <Button variant="text" size="sm" icon={<Edit size={15} />} onClick={() => toggleEdit(it.id)}>
                      {ed ? '收起编辑' : '编辑'}
                    </Button>
                  </div>
                </div>

                {it.validation_errors?.length > 0 && (
                  <Alert tone="warn" icon={<AlertTriangle size={16} />} className="quiz-review__alert">
                    {it.validation_errors.map((e, i) => (
                      <div key={i}>{e.detail || e.code || '校验未通过'}</div>
                    ))}
                  </Alert>
                )}

                {/* 题干 */}
                {ed ? (
                  <Textarea
                    className="quiz-review__field"
                    value={draft.content}
                    onChange={(e) => setDraft(it.id, { content: e.target.value })}
                    rows={3}
                    aria-label="题干"
                  />
                ) : (
                  <p className="quiz-review__content">{it.content}</p>
                )}

                {/* 选项 */}
                {Array.isArray(draft.options) && draft.options.length > 0 && (
                  <div className="quiz-review__options">
                    {draft.options.map((o, i) => {
                      const correct = String(it.answer || '').includes(o.key)
                      return (
                        <div key={i} className={cx('quiz-review__option', correct && 'is-answer')}>
                          <span className="quiz-review__option-key">{o.key}</span>
                          {ed ? (
                            <Input
                              className="quiz-review__option-input"
                              value={o.text ?? ''}
                              onChange={(e) => {
                                const next = draft.options.map((x, j) => j === i ? { ...x, text: e.target.value } : x)
                                setDraft(it.id, { options: next })
                              }}
                              aria-label={`选项 ${o.key}`}
                            />
                          ) : (
                            <span className="quiz-review__option-text">{o.text}</span>
                          )}
                          {correct && <Check size={15} className="quiz-review__option-check" aria-label="正确答案" />}
                        </div>
                      )
                    })}
                  </div>
                )}

                {/* 答案行 */}
                <div className="quiz-review__answer-row">
                  <span className="quiz-review__answer-label">答案</span>
                  {ed ? (
                    <Input
                      className="quiz-review__answer-input"
                      value={draft.answer}
                      onChange={(e) => setDraft(it.id, { answer: e.target.value })}
                      aria-label="答案"
                    />
                  ) : (
                    <span className="quiz-review__answer-value">{it.answer || '—'}</span>
                  )}
                </div>

                {/* 解析 */}
                {ed ? (
                  <Textarea
                    className="quiz-review__field"
                    value={draft.analysis}
                    onChange={(e) => setDraft(it.id, { analysis: e.target.value })}
                    rows={2}
                    placeholder="解析（可留空）"
                    aria-label="解析"
                  />
                ) : it.analysis ? (
                  <p className="quiz-review__analysis">{it.analysis}</p>
                ) : null}

                {/* 底部操作 */}
                <div className="quiz-review__foot">
                  {dirty && <span className="quiz-review__dirty-hint">已修改未保存</span>}
                  <div className="quiz-review__foot-actions">
                    {isQ ? (
                      <Button
                        variant="filled"
                        size="sm"
                        icon={<RotateCcw size={15} />}
                        loading={busy}
                        onClick={() => { if (!ed) toggleEdit(it.id); else act(it, 'restore') }}
                      >
                        {ed ? '保存并上架' : '修复后上架'}
                      </Button>
                    ) : (
                      <Button
                        variant="filled"
                        size="sm"
                        icon={<Check size={15} />}
                        loading={busy}
                        onClick={() => act(it, 'accept')}
                      >
                        确认无误
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      tone="danger"
                      icon={<Trash size={15} />}
                      loading={busy}
                      onClick={() => confirmReject(it)}
                    >
                      永久下架
                    </Button>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {total > items.length && (
        <div className="quiz-review__more">
          <Button variant="outline" onClick={() => setLimit((l) => l + 50)}>
            还有 {total - items.length} 条，加载更多
          </Button>
        </div>
      )}
    </div>
  )
}
