import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { examApi } from '../../api/client'
import MathText from '../../components/MathText'
import { normalizeOptions } from '../../utils/optionText'
import {
  Button, Card, CardHead, Chip, Dialog, Empty, PageHeader, Progress, Ring,
  Segmented, Select, Skeleton, Textarea, Tile, toastErr, toastOk,
} from '../ui'
import {
  ArrowRight, BarChart3, CheckCircle2, ChevronLeft, ChevronRight,
  Clock, FileText, Info, Layers, ListChecks, RefreshCw, Target, Timer, Trophy, X,
} from '../icons'
import { letterOf, stripOptLabel, isChoiceQ, TYPE_LABELS } from './quizShared'
import '../styles/exam-mock.css'

/* =====================================================================
 * 模考中心（/exam-mock）· P0-3
 * 蓝图 → 发起（模式/题量）→ 答题（倒计时/选择/主观）→ 交卷 → 报告
 * 历史记录：会话列表 / 状态 / 得分 / 查看报告。
 * 仅消费 /api/exam/* 契约，不依赖 ExamCenter 与 /exam 路由。
 * ===================================================================== */

const MODE_OPTIONS = [
  { value: 'normal', label: '标准模考', desc: '按蓝图题量顺序作答，贴近真实考试节奏。' },
  { value: 'weakest', label: '薄弱优先', desc: '优先抽取你薄弱知识点下的题目，针对性补强。' },
  { value: 'random', label: '随机抽题', desc: '从蓝图范围内随机抽题，每次组合都不同。' },
]

const MODE_LABELS = {
  normal: '标准模考',
  weakest: '薄弱优先',
  random: '随机抽题',
}

const STATUS_LABELS = {
  ongoing: '进行中',
  submitted: '已交卷',
  expired: '已过期',
}

function fmtScore(n) {
  const v = Number(n)
  if (Number.isNaN(v)) return '—'
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtDuration(minutes) {
  const m = Number(minutes)
  if (!m || m < 0) return '—'
  if (m < 60) return `${Math.round(m)} 分钟`
  const h = Math.floor(m / 60)
  const rest = Math.round(m % 60)
  return rest ? `${h} 小时 ${rest} 分` : `${h} 小时`
}

/* 归一化题目选项：兼容字符串数组与 {key,text} 对象数组 */
function safeOptions(raw) {
  return normalizeOptions(raw)
}

export default function ExamMock() {
  /* ---------- 视图 ---------- */
  const [tab, setTab] = useState('launch')        // launch | history
  const [view, setView] = useState('list')        // list | session | report
  const [sessionId, setSessionId] = useState(null)

  /* ---------- 发起视图 ---------- */
  const [blueprints, setBlueprints] = useState([])
  const [bpLoading, setBpLoading] = useState(true)
  const [bpError, setBpError] = useState('')

  /* ---------- 配置弹窗 ---------- */
  const [configOpen, setConfigOpen] = useState(false)
  const [selectedBp, setSelectedBp] = useState(null)
  const [mode, setMode] = useState('normal')
  const [countOverride, setCountOverride] = useState('')

  /* ---------- 答题会话 ---------- */
  const [session, setSession] = useState(null)    // build 返回的会话（含 sections）
  const [answers, setAnswers] = useState({})      // { [qid]: {answer, time_spent} }
  const [current, setCurrent] = useState(0)       // 当前题下标（全量展平索引）
  const [submitting, setSubmitting] = useState(false)
  const [leftSec, setLeftSec] = useState(0)

  /* ---------- 报告 ---------- */
  const [report, setReport] = useState(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError] = useState('')

  /* ---------- 历史记录 ---------- */
  const [sessions, setSessions] = useState([])
  const [histLoading, setHistLoading] = useState(false)
  const [histError, setHistError] = useState('')
  const [histSubject, setHistSubject] = useState('')

  const timerRef = useRef(null)
  const startedAtRef = useRef(Date.now())

  /* 展平题目：sections[].questions 拍平为单一列表，保留题号连续可跳转 */
  const questions = useMemo(() => {
    if (!session?.sections) return []
    return session.sections.flatMap((sec) => (Array.isArray(sec.questions) ? sec.questions : []))
  }, [session])

  const totalCount = session?.total_count ?? questions.length
  const totalScore = session?.total_score ?? 0

  /* ================= 蓝图加载 ================= */
  const loadBlueprints = useCallback(async () => {
    setBpLoading(true)
    setBpError('')
    try {
      const data = await examApi.blueprints()
      const list = Array.isArray(data) ? data : []
      setBlueprints(list)
      if (!list.length) toastErr('暂无可用模考蓝图')
      return true
    } catch (e) {
      setBpError(e?.message || '模考蓝图加载失败')
      return false
    } finally {
      setBpLoading(false)
    }
  }, [])

  useEffect(() => {
    loadBlueprints()
  }, [loadBlueprints])

  /* ================= 历史记录加载 ================= */
  const loadSessions = useCallback(async () => {
    setHistLoading(true)
    setHistError('')
    try {
      const params = {}
      if (histSubject) params.subject = histSubject
      const data = await examApi.sessions(params)
      setSessions(Array.isArray(data) ? data : [])
      return true
    } catch (e) {
      setHistError(e?.message || '模考记录加载失败')
      return false
    } finally {
      setHistLoading(false)
    }
  }, [histSubject])

  useEffect(() => {
    if (tab !== 'history') return
    loadSessions()
  }, [tab, loadSessions])

  /* ================= 倒计时 ================= */
  useEffect(() => {
    if (view !== 'session' || !session?.expires_at) return undefined
    const tick = () => {
      const diff = new Date(session.expires_at).getTime() - Date.now()
      setLeftSec(Math.max(0, Math.floor(diff / 1000)))
    }
    tick()
    timerRef.current = window.setInterval(tick, 1000)
    return () => window.clearInterval(timerRef.current)
  }, [view, session])

  /* 交卷后清理计时 */
  useEffect(() => {
    if (view !== 'session') {
      if (timerRef.current) window.clearInterval(timerRef.current)
    }
  }, [view])

  /* ================= 发起模考 ================= */
  const openConfig = (bp) => {
    setSelectedBp(bp)
    setMode('normal')
    setCountOverride('')
    setConfigOpen(true)
  }

  const closeConfig = () => {
    setConfigOpen(false)
    setSelectedBp(null)
  }

  const startExam = async () => {
    if (!selectedBp) return
    setSubmitting(true)
    try {
      const body = {
        subject: selectedBp.subject,
        paper: selectedBp.paper || undefined,
        year: selectedBp.year || undefined,
        mode,
        count_override: countOverride ? Number(countOverride) : undefined,
        question_source: 'all',
        exclude_recent_days: 14,
      }
      const data = await examApi.build(body)
      if (!data?.session_id) throw new Error('后端未返回 session_id')
      setSession(data)
      setAnswers({})
      setCurrent(0)
      setReport(null)
      setReportError('')
      setSessionId(data.session_id)
      startedAtRef.current = Date.now()
      setView('session')
      setConfigOpen(false)
      toastOk('模考已开始，请按考试节奏作答')
      window.scrollTo({ top: 0 })
    } catch (e) {
      toastErr(e?.message || '发起模考失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  /* ================= 作答交互 ================= */
  const currentQ = questions[current] || null

  const pickOption = (qid, i) => {
    if (!currentQ) return
    if (currentQ.question_type === 'multiple') {
      setAnswers((prev) => {
        const cur = Array.isArray(prev[qid]?.answer) ? prev[qid].answer : []
        const next = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort((a, b) => a - b)
        return { ...prev, [qid]: { ...prev[qid], answer: next } }
      })
      return
    }
    setAnswers((prev) => ({ ...prev, [qid]: { ...prev[qid], answer: i } }))
  }

  const setTextAnswer = (qid, text) => {
    setAnswers((prev) => ({ ...prev, [qid]: { ...prev[qid], answer: text } }))
  }

  const goPrev = () => setCurrent((i) => Math.max(0, i - 1))
  const goNext = () => setCurrent((i) => Math.min(questions.length - 1, i + 1))

  const answeredCount = useMemo(
    () => Object.values(answers).filter((a) => {
      if (a?.answer == null) return false
      if (Array.isArray(a.answer)) return a.answer.length > 0
      return String(a.answer).trim() !== ''
    }).length,
    [answers],
  )

  /* ================= 交卷 ================= */
  const submitExam = async () => {
    if (!session?.session_id) return
    if (submitting) return
    const unanswered = questions.filter((q) => {
      const a = answers[q.id]?.answer
      if (a == null) return true
      if (Array.isArray(a)) return a.length === 0
      return String(a).trim() === ''
    })
    if (unanswered.length > 0) {
      const ok = window.confirm(`还有 ${unanswered.length} 题未作答，确定要交卷吗？`)
      if (!ok) return
    }
    setSubmitting(true)
    try {
      const payload = {
        answers: questions.map((q) => {
          const raw = answers[q.id]?.answer
          let user_answer = ''
          let self_score = null
          if (raw != null && !(Array.isArray(raw) && raw.length === 0)) {
            if (Array.isArray(raw)) {
              user_answer = raw.map(letterOf).join('')
            } else if (isChoiceQ(q) || typeof raw === 'number') {
              user_answer = letterOf(Number(raw))
            } else {
              user_answer = String(raw).trim()
              self_score = null
            }
          }
          return {
            question_id: q.id,
            user_answer,
            self_score,
            time_spent: Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000 / Math.max(1, questions.length))),
          }
        }),
      }
      const data = await examApi.submit(session.session_id, payload)
      setSession((prev) => ({ ...prev, status: 'submitted', correct_count: data.correct_count, score: data.score }))
      toastOk(`交卷成功：得分 ${fmtScore(data.score)}`)
      setView('report')
      setSessionId(session.session_id)
      window.scrollTo({ top: 0 })
    } catch (e) {
      toastErr(e?.message || '交卷失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  /* ================= 加载报告 ================= */
  const loadReport = useCallback(async (id) => {
    setReportLoading(true)
    setReportError('')
    try {
      const data = await examApi.report(id)
      setReport(data)
      return true
    } catch (e) {
      setReportError(e?.message || '报告加载失败')
      return false
    } finally {
      setReportLoading(false)
    }
  }, [])

  useEffect(() => {
    if (view !== 'report' || !sessionId) return undefined
    loadReport(sessionId)
  }, [view, sessionId, loadReport])

  const goHome = () => {
    setView('list')
    setSession(null)
    setReport(null)
    setSessionId(null)
    setAnswers({})
    setCurrent(0)
    setTab('launch')
    window.scrollTo({ top: 0 })
  }

  /* ================= 渲染：加载态 ================= */
  if (bpLoading) {
    return (
      <div className="v3-stack" style={{ gap: 20 }}>
        <PageHeader eyebrow="MOCK EXAM · 模考中心" title="模考中心" sub="按蓝图发起整卷模考，考后生成详细报告" />
        <div className="v3-grid" style={{ gridTemplateColumns: 'repeat(2, 1fr)' }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="v3-card" style={{ padding: 22 }}><Skeleton height={120} /></div>
          ))}
        </div>
      </div>
    )
  }

  if (bpError && view === 'list' && tab === 'launch') {
    return (
      <div className="v3-stack" style={{ gap: 20 }}>
        <PageHeader eyebrow="MOCK EXAM · 模考中心" title="模考中心" sub="按蓝图发起整卷模考，考后生成详细报告" />
        <div className="v3-card" style={{ padding: 36 }}>
          <Empty
            icon={<Info size={26} />}
            title="模考蓝图加载失败"
            text={bpError}
            action={<Button variant="tonal" onClick={loadBlueprints}>重新加载</Button>}
          />
        </div>
      </div>
    )
  }

  /* ================= 渲染：答题视图 ================= */
  if (view === 'session') {
    const mm = Math.floor(leftSec / 60)
    const ss = leftSec % 60
    const timeLabel = leftSec > 0 ? `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : '时间到'
    const danger = leftSec <= 300
    const progressPct = totalCount ? Math.round(((current + 1) / totalCount) * 100) : 0

    return (
      <div className="v3-stack" style={{ gap: 14 }}>
        <PageHeader
          eyebrow="MOCK EXAM · 模考中"
          title={session?.subject || '模考'}
          sub={`${session?.paper || ''} · ${MODE_LABELS[session?.mode] || ''} · 共 ${totalCount} 题 / ${fmtScore(totalScore)} 分`}
        />

        <div className="exam-mock-topbar">
          <div className="exam-mock-topbar__info">
            <span className="exam-mock-topbar__subject">{session?.subject}</span>
            <span className="exam-mock-topbar__paper">{session?.paper}</span>
            <Chip><ListChecks size={13} /> {answeredCount}/{totalCount} 已答</Chip>
          </div>
          <div className={`exam-mock-timer${danger ? ' is-danger' : ''}`}>
            <Timer size={16} /> {timeLabel}
          </div>
        </div>

        <div className="exam-mock-progress-row">
          <Progress value={progressPct} gradient />
          <span className="exam-mock-progress-row__num">{current + 1} / {totalCount}</span>
        </div>

        {currentQ ? (
          <>
            <Card className="exam-mock-question-card">
              <div className="exam-mock-stem">
                <span className="exam-mock-stem__no">第 {current + 1} 题</span>
                <MathText text={currentQ.content || ''} />
              </div>

              {currentQ.images?.length > 0 && (
                <div className="v3-quiz-figs" style={{ marginTop: 12 }}>
                  {currentQ.images.map((img, i) => (
                    <img key={i} src={img.url} alt={`题目配图 ${i + 1}`} />
                  ))}
                </div>
              )}

              {isChoiceQ(currentQ) ? (
                <div className="exam-mock-options">
                  {safeOptions(currentQ.options).map((opt, i) => {
                    const sel = answers[currentQ.id]?.answer
                    const active = Array.isArray(sel)
                      ? sel.includes(i)
                      : sel === i
                    return (
                      <button
                        key={i}
                        type="button"
                        className={`exam-mock-opt${active ? ' is-sel' : ''}`}
                        onClick={() => pickOption(currentQ.id, i)}
                        disabled={false}
                      >
                        <span className="exam-mock-opt__letter">{letterOf(i)}</span>
                        <span className="exam-mock-opt__body"><MathText text={stripOptLabel(opt)} /></span>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="exam-mock-textarea-row">
                  <Textarea
                    aria-label="作答输入框"
                    className="v3-textarea"
                    placeholder="请在下方输入你的作答…"
                    value={answers[currentQ.id]?.answer || ''}
                    onChange={(e) => setTextAnswer(currentQ.id, e.target.value)}
                  />
                </div>
              )}
            </Card>

            <div className="exam-mock-nav">
              <Button variant="tonal" icon={<ChevronLeft size={15} />} onClick={goPrev} disabled={current === 0}>
                上一题
              </Button>
              <div className="exam-mock-nav__spacer">
                <span className="exam-mock-nav__count">{answeredCount}/{totalCount} 已答</span>
                {current < questions.length - 1 ? (
                  <Button variant="filled" icon={<ChevronRight size={15} />} onClick={goNext}>下一题</Button>
                ) : (
                  <Button variant="filled" icon={<CheckCircle2 size={15} />} onClick={submitExam} disabled={submitting}>
                    {submitting ? '交卷中…' : '交卷'}
                  </Button>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="v3-card" style={{ padding: 40 }}>
            <Empty icon={<Info size={26} />} title="题目列表为空" text="本次模考未包含任何题目，请返回重新发起。" />
          </div>
        )}

        {current === questions.length - 1 && (
          <div style={{ textAlign: 'right', marginTop: 4 }}>
            <Button variant="ghost" icon={<X size={15} />} onClick={submitExam} disabled={submitting}>
              提前交卷
            </Button>
          </div>
        )}
      </div>
    )
  }

  /* ================= 渲染：报告视图 ================= */
  if (view === 'report') {
    return (
      <div className="v3-stack" style={{ gap: 20 }}>
        <PageHeader
          eyebrow="MOCK REPORT · 模考报告"
          title="考后报告"
          sub={`${session?.subject || ''} · ${session?.paper || ''} · 答题情况与薄弱点分析`}
          actions={<Button variant="ghost" icon={<Clock size={15} />} onClick={goHome}>返回模考中心</Button>}
        />

        {reportLoading ? (
          <div className="v3-card" style={{ padding: 28 }}>
            <Skeleton height={180} />
            <div style={{ height: 12 }} />
            <Skeleton height={90} />
            <div style={{ height: 12 }} />
            <Skeleton height={90} />
          </div>
        ) : reportError ? (
          <div className="v3-card" style={{ padding: 36 }}>
            <Empty
              icon={<Info size={26} />}
              title="报告加载失败"
              text={reportError}
              action={<Button variant="tonal" onClick={() => loadReport(sessionId)}>重新加载</Button>}
            />
          </div>
        ) : report ? (
          <>
            {/* 总览 */}
            <Card variant="hero" className="exam-mock-report-hero">
              <div className="exam-mock-report-hero__ring">
                <Ring value={accuracyOf(report)} size={132} stroke={11} gradient>
                  <span className="v3-quiz-ring-center">
                    <strong>{accuracyOf(report)}<small style={{ fontSize: 'var(--v3-fs-18)' }}>%</small></strong>
                    <span>正确率</span>
                  </span>
                </Ring>
              </div>
              <div className="exam-mock-report-hero__copy">
                <h2>模考完成，以下是你的作答报告。</h2>
                <p>总分与正确率按后端判分结果展示；薄弱知识点来自错题归因。</p>
                <dl className="exam-mock-report-stats">
                  <div className="exam-mock-report-stat"><dt>得分</dt><dd>{fmtScore(report?.overview?.earned_score ?? report?.overview?.score)} / {fmtScore(report?.overview?.max_score ?? totalScore)}</dd></div>
                  <div className="exam-mock-report-stat is-ok"><dt>答对</dt><dd>{fmtScore(report?.overview?.correct_count)}</dd></div>
                  <div className="exam-mock-report-stat is-bad"><dt>答错</dt><dd>{fmtScore(report?.overview?.wrong_count)}</dd></div>
                  <div className="exam-mock-report-stat"><dt>总用时</dt><dd>{fmtDuration(report?.overview?.duration_minutes ?? report?.time_analysis?.total_minutes)}</dd></div>
                </dl>
                <div className="exam-mock-report-actions">
                  <Button variant="filled" icon={<Clock size={15} />} onClick={goHome}>返回模考中心</Button>
                </div>
              </div>
            </Card>

            {/* 分题型得分 */}
            {Array.isArray(report?.section_scores) && report.section_scores.length > 0 && (
              <Card>
                <CardHead
                  title="分题型得分"
                  sub="各题型/分卷的实际得分与满分"
                  actions={<Layers size={17} style={{ color: 'var(--v3-text-3)' }} />}
                />
                <div className="v3-stack" style={{ gap: 4 }}>
                  {report.section_scores.map((sec, i) => {
                    const p = sec.max_score ? Math.round((sec.earned_score / sec.max_score) * 100) : 0
                    return (
                      <div key={i} className="exam-mock-section-row">
                        <span className="exam-mock-section-row__name">{sec.title || sec.section || `第 ${i + 1} 部分`}</span>
                        <Progress value={p} />
                        <span className="exam-mock-section-row__num">{fmtScore(sec.earned_score)} / {fmtScore(sec.max_score)}</span>
                      </div>
                    )
                  })}
                </div>
              </Card>
            )}

            {/* 薄弱知识点 Top5 */}
            <Card>
              <CardHead
                title="薄弱知识点 Top5"
                sub="按错误次数聚合的知识点，建议优先复习"
                actions={<Target size={17} style={{ color: 'var(--v3-text-3)' }} />}
              />
              {Array.isArray(report?.knowledge_weakness) && report.knowledge_weakness.length > 0 ? (
                <div className="exam-mock-weak-list">
                  {report.knowledge_weakness.slice(0, 5).map((kp, i) => (
                    <div key={i} className="exam-mock-weak-item">
                      <span className="exam-mock-weak-item__rank">{i + 1}</span>
                      <span className="exam-mock-weak-item__name">{kp.name || kp.knowledge_point || '未命名知识点'}</span>
                      <span className="exam-mock-weak-item__count">错 {kp.error_count ?? kp.count ?? 0} 次</span>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty
                  icon={<Trophy size={24} />}
                  title="没有薄弱知识点"
                  text="本次模考错题较少或尚未归因到知识点，继续保持。"
                />
              )}
            </Card>

            {/* 错题列表 */}
            <Card>
              <CardHead
                title="错题回顾"
                sub="本次答错的题目与正确答案，可对照复习"
                actions={<FileText size={17} style={{ color: 'var(--v3-text-3)' }} />}
              />
              {Array.isArray(report?.wrong_questions) && report.wrong_questions.length > 0 ? (
                <div className="v3-stack" style={{ gap: 8 }}>
                  {report.wrong_questions.map((wq) => (
                    <WrongQuestionItem key={wq.question_id ?? wq.id} item={wq} />
                  ))}
                </div>
              ) : (
                <Empty
                  icon={<CheckCircle2 size={24} />}
                  title="本次没有错题"
                  text="所有题目都答对了，非常棒！"
                />
              )}
            </Card>
          </>
        ) : (
          <div className="v3-card" style={{ padding: 40 }}>
            <Empty icon={<Info size={26} />} title="暂无报告数据" text="交卷后报告会自动生成，请稍后重试。" />
          </div>
        )}
      </div>
    )
  }

  /* ================= 渲染：列表视图（发起 / 历史） ================= */
  return (
    <div className="v3-stack" style={{ gap: 20 }}>
      <PageHeader
        eyebrow="MOCK EXAM · 模考中心"
        title="模考中心"
        sub="按蓝图发起整卷模考 · 支持标准 / 薄弱优先 / 随机抽题 · 考后自动生成报告"
        actions={(
          <Button variant="tonal" icon={<RefreshCw size={15} />} onClick={tab === 'launch' ? loadBlueprints : loadSessions}>
            刷新
          </Button>
        )}
      />

      <Segmented
        ariaLabel="模考中心视图"
        value={tab}
        onChange={setTab}
        options={[
          { value: 'launch', label: '发起模考', icon: <Target size={15} /> },
          { value: 'history', label: '历史记录', icon: <Clock size={15} /> },
        ]}
      />

      {tab === 'launch' ? (
        <>
          {bpError ? (
            <div className="v3-card" style={{ padding: 36 }}>
              <Empty
                icon={<Info size={26} />}
                title="模考蓝图加载失败"
                text={bpError}
                action={<Button variant="tonal" onClick={loadBlueprints}>重新加载</Button>}
              />
            </div>
          ) : blueprints.length === 0 ? (
            <div className="v3-card" style={{ padding: 40 }}>
              <Empty
                icon={<FileText size={26} />}
                title="暂无可用模考蓝图"
                text="管理员配置蓝图后，这里会按科目分组展示可发起的模考。"
              />
            </div>
          ) : (
            <BlueprintGroups blueprints={blueprints} onStart={openConfig} />
          )}
        </>
      ) : (
        <>
          <div className="exam-mock-history-toolbar">
            <Select
              aria-label="按科目筛选"
              value={histSubject}
              onChange={(e) => setHistSubject(e.target.value)}
              options={[
                { value: '', label: '全部科目' },
                ...[...new Set((sessions || []).map((s) => s.subject).filter(Boolean))].map((s) => ({ value: s, label: s })),
              ]}
            />
            <span style={{ fontSize: 'var(--v3-fs-12)', color: 'var(--v3-text-3)' }}>
              共 {sessions.length} 条记录
            </span>
          </div>

          {histLoading ? (
            <div className="exam-mock-history-grid">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="v3-card" style={{ padding: 20 }}><Skeleton height={110} /></div>
              ))}
            </div>
          ) : histError ? (
            <div className="v3-card" style={{ padding: 36 }}>
              <Empty
                icon={<Info size={26} />}
                title="模考记录加载失败"
                text={histError}
                action={<Button variant="tonal" onClick={loadSessions}>重新加载</Button>}
              />
            </div>
          ) : sessions.length === 0 ? (
            <div className="v3-card" style={{ padding: 40 }}>
              <Empty
                icon={<Clock size={26} />}
                title="还没有模考记录"
                text="发起一次模考并交卷后，记录会出现在这里。"
                action={<Button variant="filled" onClick={() => setTab('launch')}>去发起模考</Button>}
              />
            </div>
          ) : (
            <div className="exam-mock-history-grid">
              {sessions.map((s) => (
                <SessionCard
                  key={s.id}
                  item={s}
                  onViewReport={(id) => {
                    setSessionId(id)
                    setSession((prev) => ({
                      ...(prev || {}),
                      session_id: id,
                      subject: s.subject,
                      paper: s.paper,
                      total_count: s.total_count,
                      total_score: s.max_score ?? s.total_score,
                    }))
                    setReport(null)
                    setReportError('')
                    setView('report')
                    window.scrollTo({ top: 0 })
                  }}
                />
              ))}
            </div>
          )}
        </>
      )}

      <Tile variant="well">
        <Info size={17} />
        <p>
          <b>说明：</b>模考报告由后端基于交卷答案自动生成，包含总分、分题型得分、薄弱知识点与错题回顾。
          交卷后可在历史记录中随时查看。
        </p>
      </Tile>

      {/* 发起配置弹窗 */}
      <Dialog
        open={configOpen}
        title="发起模考"
        sub={selectedBp ? `${selectedBp.subject} · ${selectedBp.paper || '综合卷'} · ${selectedBp.count || 0} 题` : ''}
        onClose={closeConfig}
        wide
        footer={(
          <>
            <Button variant="text" onClick={closeConfig}>取消</Button>
            <Button variant="filled" onClick={startExam} disabled={submitting}>
              {submitting ? '组卷中…' : '开始模考'}
            </Button>
          </>
        )}
      >
        <div className="v3-stack" style={{ gap: 12 }}>
          <div className="exam-mock-modes">
            {MODE_OPTIONS.map((m) => (
              <button
                key={m.value}
                type="button"
                className={`exam-mock-mode${mode === m.value ? ' is-active' : ''}`}
                onClick={() => setMode(m.value)}
              >
                <span className="exam-mock-mode__name">
                  {m.value === 'normal' ? <Timer size={14} /> : m.value === 'weakest' ? <Target size={14} /> : <RefreshCw size={14} />}
                  {m.label}
                </span>
                <span className="exam-mock-mode__desc">{m.desc}</span>
              </button>
            ))}
          </div>

          <div className="exam-mock-count-row">
            <label htmlFor="exam-mock-count">题量覆盖</label>
            <Select
              id="exam-mock-count"
              value={countOverride}
              onChange={(e) => setCountOverride(e.target.value)}
              options={[
                { value: '', label: '蓝图默认题量' },
                ...(selectedBp?.count ? [
                  { value: String(selectedBp.count), label: `全部 ${selectedBp.count} 题` },
                  { value: String(Math.max(1, Math.floor(selectedBp.count / 2))), label: `一半（${Math.max(1, Math.floor(selectedBp.count / 2))} 题）` },
                ] : []),
              ]}
            />
            <span className="exam-mock-count-hint">薄弱优先/随机抽题会从蓝图范围内抽取</span>
          </div>
        </div>
      </Dialog>
    </div>
  )
}

/* ================= 子组件 ================= */

function accuracyOf(report) {
  const ov = report?.overview || {}
  const total = ov.correct_count != null && ov.wrong_count != null
    ? ov.correct_count + ov.wrong_count
    : 0
  if (!total) return 0
  return Math.round((ov.correct_count / total) * 100)
}

/* 蓝图按科目分组 */
function BlueprintGroups({ blueprints, onStart }) {
  const groups = useMemo(() => {
    const map = new Map()
    for (const bp of blueprints) {
      const key = bp.subject || '未分组'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(bp)
    }
    return [...map.entries()]
  }, [blueprints])

  return (
    <div className="v3-stack" style={{ gap: 18 }}>
      {groups.map(([subject, list]) => (
        <section key={subject} className="exam-mock-group">
          <div className="exam-mock-group__head">
            <h3>{subject}</h3>
            <span className="exam-mock-group__count">{list.length} 个蓝图</span>
          </div>
          <div className="v3-stack" style={{ gap: 8 }}>
            {list.map((bp) => (
              <div key={bp.id} className="exam-mock-blueprint">
                <div className="exam-mock-blueprint__main">
                  <div className="exam-mock-blueprint__title">
                    {bp.paper || '综合卷'}
                    {bp.year ? <span className="exam-mock-bp-year">{bp.year} 年</span> : null}
                  </div>
                  <div className="exam-mock-blueprint__meta">
                    {bp.section ? <Chip>{bp.section}</Chip> : null}
                    {bp.question_type ? <Chip>{TYPE_LABELS[bp.question_type] || bp.question_type}</Chip> : null}
                    <span>{bp.count || 0} 题</span>
                    {bp.score_per_question ? <span>· 每题 {fmtScore(bp.score_per_question)} 分</span> : null}
                  </div>
                </div>
                <div className="exam-mock-blueprint__score">
                  共 {fmtScore((bp.count || 0) * (bp.score_per_question || 0))} 分
                </div>
                <Button variant="filled" icon={<ArrowRight size={15} />} onClick={() => onStart(bp)}>
                  开始模考
                </Button>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

/* 历史记录卡片 */
function SessionCard({ item, onViewReport }) {
  const status = item.status || 'ongoing'
  const accuracy = item.total_count
    ? Math.round(((item.correct_count || 0) / item.total_count) * 100)
    : 0
  return (
    <div className="exam-mock-history-card">
      <div className="exam-mock-history-card__top">
        <span className="exam-mock-history-card__subject">{item.subject || '模考'}</span>
        <Chip active={status === 'ongoing'}>{STATUS_LABELS[status] || status}</Chip>
      </div>
      <div className="exam-mock-history-card__paper" title={item.paper}>{item.paper || '—'}</div>
      <div className="exam-mock-history-card__stats">
        <span>得分 <b>{fmtScore(item.earned_score ?? item.score)}</b> / {fmtScore(item.max_score ?? item.total_score)}</span>
        <span>正确率 <b>{accuracy}%</b></span>
        <span>题量 <b>{item.total_count}</b></span>
      </div>
      <div className="exam-mock-history-card__foot">
        <span className="exam-mock-history-card__time">{fmtTime(item.started_at)}</span>
        {item.report_available || status === 'submitted' ? (
          <Button variant="tonal" size="sm" icon={<BarChart3 size={14} />} onClick={() => onViewReport(item.id)}>
            查看报告
          </Button>
        ) : (
          <span style={{ fontSize: 'var(--v3-fs-12)', color: 'var(--v3-text-3)' }}>交卷后生成报告</span>
        )}
      </div>
    </div>
  )
}

/* 错题可展开项 */
function WrongQuestionItem({ item }) {
  const [open, setOpen] = useState(false)
  const qid = item.question_id ?? item.id
  const content = item.content || item.question || '（题目内容缺失）'
  return (
    <div className="exam-mock-wrong-item">
      <button type="button" className="exam-mock-wrong-item__head" onClick={() => setOpen((v) => !v)}>
        <span className="exam-mock-wrong-item__q"><MathText text={content} /></span>
        <span className="exam-mock-wrong-item__badge">答错</span>
      </button>
      {open && (
        <div className="exam-mock-wrong-item__body">
          <div>
            <b>你的答案：</b>
            <span>{item.user_answer || item.my_answer || '（未作答）'}</span>
          </div>
          <div>
            <b>正确答案：</b>
            <span className="exam-mock-wrong-ans">{item.correct_answer || item.answer || '—'}</span>
          </div>
          {item.analysis ? (
            <div><b>解析：</b><span>{item.analysis}</span></div>
          ) : null}
          {item.knowledge_point ? (
            <div><b>知识点：</b><span>{item.knowledge_point}</span></div>
          ) : null}
        </div>
      )}
    </div>
  )
}