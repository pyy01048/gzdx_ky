import React, { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, CardHead, Chip, Input, PageHeader, Progress, Ring, Segmented,
  toast,
} from '../ui'
import {
  Bot, ChevronLeft, RotateCcw, Sparkles, Target, TrendingUp,
} from '../icons'
import { quizApi, recommendApi, request } from '../../api/client'
import '../styles/quiz-v3.css'

/* =====================================================================
 * 刷题中心 · 复盘报告（v3）
 * 正确率大字 + 知识点/章节掌握情况 + 重练错题 / 再练一次
 * + V14 场景化 AI 讲题（错题逐条三问 + 追问弹层）。
 * + P1-E 多 Agent 协作答疑（orchestrated）：answer + confidence + trace 时间线
 * + P0-C 薄弱点强化：三信号融合薄弱点 / 生成变式题 / 掌握门控
 * 讲题会话状态（tutor）仅本视图使用，就近下沉。
 * ===================================================================== */

/* ---- 薄弱点来源标签（三信号融合） ---- */
const WEAK_SOURCE_LABELS = {
  quiz: '答题信号',
  review: '复习信号',
  error: '错题信号',
  ai: 'AI信号',
}

export default function QuizResult({ session, records, startedFromRef, tutorMode, setTutorMode, onBeginSession, onGoHome }) {
  /* V14 场景化 AI 讲题状态 */
  const [tutor, setTutor] = useState(null)
  /* 仍未理解 → 盲点池（闭环：AI 讲题产出回流学习数据主线） */
  const [stuckMarked, setStuckMarked] = useState(false)

  /* P1-E 多 Agent 协作答疑状态 */
  const [orch, setOrch] = useState(null)   // {qid, loading, answer, confidence, degraded, trace, error}
  const [orchQid, setOrchQid] = useState(null)

  /* P0-C 薄弱点强化状态 */
  const [weakPoints, setWeakPoints] = useState(null)   // null=加载中 | [] | [{kp_id,name,weak_score,sources}]
  const [weakError, setWeakError] = useState('')
  const [variantLoading, setVariantLoading] = useState({})
  const [gateResults, setGateResults] = useState({})   // { [kp_id]: {passed, consecutive_required, ...} }
  const [gateLoading, setGateLoading] = useState({})

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
    onBeginSession(`${session.title} · 错题重练`, wrong, src?.mode)
  }
  const redoAll = () => {
    const src = startedFromRef.current
    onBeginSession(src?.title || session.title, src?.questions || list, src?.mode)
  }

  /* V14 场景化 AI 讲题：错题逐条三问 + 追问弹层 */
  const askTutor = async (qid, angle, myAnswer) => {
    setTutor({ qid, angle, loading: true, content: '', history: [] })
    try {
      const r = await request('/ai/tutoring/explain', {
        method: 'POST',
        body: { question_id: qid, angle, my_answer: myAnswer || undefined,
                source_kind: tutorMode === 'auto' ? undefined : tutorMode },
      })
      setTutor({ qid, angle, loading: false, content: r.content, provider: r.provider,
                 mode: r.mode, source_kind: r.source_kind,
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
      const r = await request('/ai/tutoring/followup', {
        method: 'POST',
        body: { question_id: tutor.qid, message, history: hist.slice(-6),
                source_kind: tutorMode === 'auto' ? undefined : tutorMode },
      })
      setTutor(t => ({ ...t, loading: false, content: r.content,
                       mode: r.mode || t?.mode, source_kind: r.source_kind || t?.source_kind,
                       history: [...hist, { role: 'user', content: message },
                                { role: 'assistant', content: r.content }] }))
    } catch (e) {
      setTutor({ ...tutor, loading: false, content: e?.message || '追问失败' })
    }
  }

  /* 「仍未理解，加入盲点池」：把 AI 讲题后仍未搞懂的知识点沉淀到盲区池。 */
  const markStuck = async () => {
    if (!tutor?.qid || stuckMarked) return
    try {
      await request('/ai/tutoring/stuck', {
        method: 'POST',
        body: { question_id: Number(tutor.qid), note: 'AI 讲题后仍未理解', angle: tutor.angle || 'solution' },
      })
      setStuckMarked(true)
      toast('已加入盲点池：将进入复习队列 / 周会议题安排巩固')
    } catch (e) {
      toast(e?.message || '加入盲点池失败，请稍后重试')
    }
  }

  /* P1-E 多 Agent 协作答疑：POST /api/ai/tutoring/orchestrated
     请求 {question_id, my_answer?}；响应 {answer, trace, confidence, degraded} */
  const askOrchestrated = async (qid) => {
    if (orch?.loading) return
    setOrchQid(qid)
    setOrch({ qid, loading: true, answer: '', confidence: '', degraded: false, trace: [], error: '' })
    try {
      const rec = records[qid]
      const myAnswer = rec?.selected || ''
      const r = await quizApi.orchestratedTutoring({ question_id: Number(qid), my_answer: myAnswer || undefined })
      setOrch({
        qid,
        loading: false,
        answer: r?.answer || '',
        confidence: r?.confidence || '',
        degraded: !!r?.degraded,
        trace: Array.isArray(r?.trace) ? r.trace : [],
        error: '',
      })
    } catch (e) {
      setOrch({ qid, loading: false, answer: '', confidence: '', degraded: false, trace: [], error: e?.message || 'AI 协作讲解失败，请稍后重试' })
    }
  }

  /* P0-C 薄弱点加载：GET /api/recommend/weak-points?subject=&limit=5 */
  const loadWeakPoints = useCallback(async () => {
    const subject = session.questions[0]?.subject || ''
    try {
      const data = await recommendApi.weakPoints({ subject: subject || undefined, limit: 5 })
      const items = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
      setWeakPoints(items)
      setWeakError('')
    } catch (e) {
      setWeakError(e?.message || '薄弱点加载失败')
      setWeakPoints([])
    }
  }, [session.questions])

  useEffect(() => {
    loadWeakPoints()
  }, [loadWeakPoints])

  /* 生成变式题：POST /api/recommend/variants {kp_id, count: 3} */
  const generateVariants = async (kp) => {
    const kpId = kp.kp_id ?? kp.id
    if (variantLoading[kpId]) return
    setVariantLoading((m) => ({ ...m, [kpId]: true }))
    try {
      const r = await recommendApi.variants({ kp_id: Number(kpId), count: 3 })
      const created = r?.created ?? r?.created_count ?? 0
      toast(`已生成 ${created} 道变式题`)
    } catch (e) {
      toast(`生成变式题失败：${e?.message || '请稍后重试'}`)
    } finally {
      setVariantLoading((m) => ({ ...m, [kpId]: false }))
    }
  }

  /* 掌握门控：POST /api/recommend/mastery-gate {kp_id, consecutive_required: 3} */
  const checkMasteryGate = async (kp) => {
    const kpId = kp.kp_id ?? kp.id
    if (gateLoading[kpId]) return
    setGateLoading((m) => ({ ...m, [kpId]: true }))
    try {
      const r = await recommendApi.masteryGate({ kp_id: Number(kpId), consecutive_required: 3 })
      setGateResults((m) => ({ ...m, [kpId]: r || {} }))
      const passed = !!r?.passed
      toast(passed ? '已达到连续答对阈值，掌握门控通过' : '尚未达到连续答对阈值，继续巩固')
    } catch (e) {
      toast(`掌握门控检查失败：${e?.message || '请稍后重试'}`)
    } finally {
      setGateLoading((m) => ({ ...m, [kpId]: false }))
    }
  }

  const tutorModeLabel = tutor?.mode === 'exam'
    ? '真题模式 · 评分视角'
    : tutor?.mode === 'textbook'
      ? '教材模式 · 理解视角'
      : '通用模式'

  return (
    <div className="v3-quiz">
      <PageHeader
        eyebrow="QUIZ REPORT · 练习报告"
        title={session.title}
        sub={`${session.mode === 'memorize' ? '背题模式' : '练习模式'} · 共 ${list.length} 题 · 答题结果与知识点掌握情况`}
      />

      <div className="v3-quiz-result">
        <Card variant="hero" className="v3-quiz-result-hero">
          <div className="v3-quiz-result-hero__ring">
            <Ring value={accuracy} size={164} stroke={12} gradient>
              <span className="v3-quiz-ring-center">
                <strong>{accuracy}<small style={{ fontSize: 'var(--v3-fs-18)' }}>%</small></strong>
                <span>正确率</span>
              </span>
            </Ring>
          </div>
          <div className="v3-quiz-result-hero__copy">
            <h2>{accuracy >= 80 ? '发挥稳定，继续保持这个节奏。' : accuracy >= 50 ? '基础在手，错题值得再过一遍。' : '先看清错因，再重练一轮。'}</h2>
            <p>{session.title} · 练习报告</p>
            <dl className="v3-quiz-result-stats">
              <div className="v3-quiz-result-stat"><dt>题目总数</dt><dd>{list.length}</dd></div>
              <div className="v3-quiz-result-stat"><dt>已作答</dt><dd>{answered.length}</dd></div>
              <div className="v3-quiz-result-stat is-ok"><dt>答对</dt><dd>{correct.length}</dd></div>
              <div className="v3-quiz-result-stat is-bad"><dt>答错</dt><dd>{wrong.length}</dd></div>
            </dl>
            <div className="v3-quiz-result-actions" style={{ marginTop: 16 }}>
              {wrong.length > 0 && (
                <Button variant="filled" icon={<RotateCcw size={15} />} onClick={redoWrong}>
                  重练错题（{wrong.length}）
                </Button>
              )}
              <Button variant="tonal" icon={<TrendingUp size={15} />} onClick={redoAll}>再练一次</Button>
              <Button variant="ghost" icon={<ChevronLeft size={15} />} onClick={onGoHome}>返回题库</Button>
            </div>
          </div>
        </Card>

        {byChapter.size > 0 && (
          <Card>
            <CardHead
              title="知识点 / 章节掌握情况"
              sub="按本次作答题目所属章节聚合"
              actions={<Target size={17} style={{ color: 'var(--v3-text-3)' }} />}
            />
            <div className="v3-quiz-chapter-rows">
              {Array.from(byChapter.entries()).map(([name, v]) => {
                const p = v.total ? Math.round((v.correct / v.total) * 100) : 0
                return (
                  <div key={name} className="v3-quiz-chapter-stat">
                    <span className="v3-quiz-chapter-stat__name">{name}</span>
                    <Progress value={p} />
                    <span className="v3-quiz-chapter-stat__num">{v.correct}/{v.total}</span>
                  </div>
                )
              })}
            </div>
          </Card>
        )}

        {/* V14 场景化 AI 讲题：错题逐条三问 + 追问弹层 + P1-E 多Agent协作讲解 */}
        {wrong.length > 0 && (
          <Card>
            <CardHead
              title="智能 AI 讲题"
              sub="点错题即问，自动带题目上下文"
              actions={<Sparkles size={17} style={{ color: 'var(--v3-secondary)' }} />}
            />
            {/* 讲题模式（M0-103②）：真题=评分视角，教材=理解视角；auto 由题目来源自动判定 */}
            <div className="v3-quiz-inline" style={{ marginBottom: 12 }}>
              <span style={{ fontSize: 'var(--v3-fs-12)', color: 'var(--v3-text-3)' }}>讲解模式：</span>
              <Segmented
                ariaLabel="AI 讲题模式"
                value={tutorMode}
                onChange={setTutorMode}
                options={[
                  { value: 'auto', label: '自动（按题目来源）' },
                  { value: 'exam', label: '真题模式' },
                  { value: 'textbook', label: '教材模式' },
                ]}
              />
              {tutor?.mode && <Chip as="span">当前按【{tutorModeLabel}】讲解</Chip>}
            </div>
            <p className="v3-quiz-note" style={{ marginBottom: 10 }}>
              真题模式按阅卷评分视角：踩分点 / 失分步骤 / 答题规范；教材模式按概念理解视角：原理讲透 / 推导链 / 概念辨析。
            </p>

            <div className="v3-quiz-wrong-list">
              {wrong.slice(0, 10).map((q) => (
                <div key={q.id} className="v3-quiz-wrong">
                  <span className="v3-quiz-wrong__text" title={q.content}>{(q.content || '').slice(0, 40)}</span>
                  <div className="v3-quiz-wrong__btns">
                    {[['why_wrong', '为什么我错'], ['solution', '解题思路'], ['method', '举一反三']].map(([a, label]) => (
                      <Button key={a} size="sm" variant="ghost" disabled={tutor?.loading}
                        onClick={() => askTutor(q.id, a, records[q.id]?.selected)}>
                        {tutor?.qid === q.id && tutor?.loading ? '…' : label}
                      </Button>
                    ))}
                    {/* P1-E 多 Agent 协作答疑入口 */}
                    <Button size="sm" variant="tonal" disabled={orch?.loading}
                      onClick={() => askOrchestrated(q.id)}>
                      {orch?.qid === q.id && orch?.loading ? '协作讲解中…' : 'AI 协作讲解'}
                    </Button>
                  </div>
                </div>
              ))}
            </div>

            {tutor?.content && (
              <div className="v3-quiz-tutor">
                <div className="v3-quiz-tutor__meta">
                  讲答来源：{tutor.provider || 'AI'} · 可继续追问
                </div>
                <div className="v3-quiz-tutor__content">{tutor.content}</div>
                <div className="v3-quiz-tutor__stuck">
                  {stuckMarked ? (
                    <span className="v3-quiz-stuck-ok">
                      ✓ 已加入盲点池：将在复习队列 / 周会议题中安排巩固
                    </span>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={markStuck}>仍未理解，加入盲点池</Button>
                  )}
                </div>
                <FollowupBox onSend={askFollowup} busy={tutor?.loading} />
              </div>
            )}

            {/* P1-E 多 Agent 协作答疑结果：answer + confidence + degraded + trace 时间线 */}
            {orch?.qid != null && (
              <div className="v3-quiz-orch">
                {orch.loading ? (
                  <div className="v3-quiz-orch__loading">多 Agent 协作讲解中，正在检索 / 求解 / 验证 / 补救…</div>
                ) : orch.error ? (
                  <div className="v3-quiz-orch__error">{orch.error}</div>
                ) : (
                  <>
                    <div className="v3-quiz-orch__head">
                      <span>多 Agent 协作讲解</span>
                      {orch.confidence && <ConfidenceBadge confidence={orch.confidence} />}
                      {orch.degraded && <span className="v3-quiz-orch__degraded">降级模式 · 部分 Agent 不可用</span>}
                    </div>
                    <div className="v3-quiz-orch__answer">{orch.answer}</div>
                    {Array.isArray(orch.trace) && orch.trace.length > 0 && (
                      <div className="v3-quiz-orch__trace">
                        {orch.trace.map((stage, i) => (
                          <TraceItem key={`${stage.stage || i}-${i}`} stage={stage} index={i} />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </Card>
        )}

        {/* P0-C 薄弱点强化：三信号融合薄弱点 → 变式题 / 掌握门控 */}
        <Card>
          <CardHead
            title="薄弱点强化"
            sub="三信号融合（答题 / 复习 / 错题）定位薄弱知识点，生成变式题强化训练"
            actions={<Target size={17} style={{ color: 'var(--v3-secondary)' }} />}
          />
          {weakPoints === null ? (
            <div className="v3-quiz-weak-loading">薄弱点分析中…</div>
          ) : weakError ? (
            <div className="v3-quiz-weak-empty">
              薄弱点加载失败：{weakError}（不影响本页其它功能）
            </div>
          ) : !weakPoints.length ? (
            <div className="v3-quiz-weak-empty">暂无薄弱知识点，继续保持。</div>
          ) : (
            <div className="v3-quiz-weak-list">
              {weakPoints.map((kp) => {
                const kpId = kp.kp_id ?? kp.id
                const gate = gateResults[kpId]
                const passed = !!gate?.passed
                return (
                  <div key={String(kpId)} className="v3-quiz-weak-item">
                    <div className="v3-quiz-weak-item__main">
                      <span className="v3-quiz-weak-item__name">{kp.name || `知识点 #${kpId}`}</span>
                      {kp.weak_score != null && (
                        <span className="v3-quiz-weak-item__score">薄弱度 {Number(kp.weak_score)}</span>
                      )}
                      <div className="v3-quiz-weak-item__sources">
                        {Array.isArray(kp.sources) && kp.sources.map((s) => (
                          <span key={s} className="v3-quiz-weak-item__source">
                            {WEAK_SOURCE_LABELS[s] || s}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="v3-quiz-weak-item__btns">
                      <Button size="sm" variant="tonal" disabled={!!variantLoading[kpId]}
                        onClick={() => generateVariants(kp)}>
                        {variantLoading[kpId] ? '生成中…' : '生成变式题'}
                      </Button>
                      <Button size="sm" variant="ghost" disabled={!!gateLoading[kpId]}
                        onClick={() => checkMasteryGate(kp)}>
                        {gateLoading[kpId] ? '门控检查中…' : '掌握门控'}
                      </Button>
                    </div>
                    {gate && (
                      <div className={`v3-quiz-weak-item__gate ${passed ? 'is-ok' : 'is-na'}`}>
                        {passed
                          ? `✓ 已连续答对 ${gate.consecutive_required ?? 3} 题，达到掌握阈值`
                          : `未达阈值：还需连续答对 ${Math.max(0, (gate.consecutive_required ?? 3) - (gate.current_streak ?? 0))} 题`}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

/* confidence 徽标：high=绿 / medium=黄 / low=红 */
function ConfidenceBadge({ confidence }) {
  const tone = confidence === 'high' ? 'success' : confidence === 'medium' ? 'warning' : 'danger'
  const label = confidence === 'high' ? '高置信' : confidence === 'medium' ? '中置信' : '低置信'
  return <span className={`v3-quiz-orch__confidence is-${tone}`}>{label}</span>
}

/* 轨迹时间线单项：stage 名 + status 徽标 + elapsed_ms + data 摘要 */
function TraceItem({ stage, index }) {
  const stageName = stage?.stage || `阶段 ${index + 1}`
  const status = stage?.status || ''
  const elapsed = stage?.elapsed_ms
  const data = stage?.data
  return (
    <div className="v3-quiz-orch__trace-item">
      <span className="v3-quiz-orch__trace-idx">{index + 1}</span>
      <span className="v3-quiz-orch__trace-stage">{stageName}</span>
      {status && <span className={`v3-quiz-orch__trace-status is-${status}`}>{status}</span>}
      {elapsed != null && <span className="v3-quiz-orch__trace-elapsed">{Number(elapsed)}ms</span>}
      <span className="v3-quiz-orch__trace-data"><TraceData stage={stage} data={data} /></span>
    </div>
  )
}

/* 各阶段 data 摘要：
   retrieve → hits 数量；solve → 答案/要点；verify → verification 摘要；remedy → suggestions 列表 */
function TraceData({ stage, data }) {
  if (!data || typeof data !== 'object') return null
  const stageName = stage?.stage || ''
  if (stageName === 'retrieve' && Array.isArray(data.hits)) {
    return <span>检索命中 {data.hits.length} 条</span>
  }
  if (stageName === 'verify' && (data.verification || data.verified_score != null)) {
    const v = data.verification || data
    const score = v.verified_score != null ? v.verified_score : (v.score != null ? v.score : null)
    return <span>{score != null ? `验证得分 ${score}` : '验证完成'}</span>
  }
  if (stageName === 'remedy' && Array.isArray(data.suggestions)) {
    return <span>补救建议 {data.suggestions.length} 条</span>
  }
  // 通用文本摘要
  const text = typeof data === 'string' ? data
    : data.summary || data.answer || data.content || data.reason || data.message || ''
  return text ? <span>{String(text).slice(0, 60)}</span> : null
}

/* V14 追问输入框（结果页 AI 讲题弹层内） */
function FollowupBox({ onSend, busy }) {
  const [text, setText] = useState('')
  const send = () => {
    if (busy || !text.trim()) return
    onSend(text)
    setText('')
  }
  return (
    <div className="v3-quiz-followup">
      <Input
        style={{ flex: 1 }}
        aria-label="继续追问"
        value={text}
        disabled={busy}
        placeholder="继续追问，如：第 2 步为什么用戴维南定理？"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && !busy) { onSend(text); setText('') } }}
      />
      <Button size="sm" variant="filled" icon={<Bot size={15} />} disabled={busy || !text.trim()} onClick={send}>
        追问
      </Button>
    </div>
  )
}