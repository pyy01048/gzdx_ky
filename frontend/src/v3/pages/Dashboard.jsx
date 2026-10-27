import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useStore from '../../store/useStore'
import { todayStr, weekdayIdx, WEEK_CN } from '../../utils/date'
import { examDaysLeft, examYear, examDateMD, resolveExamDate } from '../../utils/exam'
import { dueCards } from '../../utils/spaced'
import { ukey } from '../../utils/userKeys'
import { dashboardApi, insightApi, tasksApi } from '../../api/client'
import { kaoyanApi } from '../../api/kaoyanApi'
import {
  DASH_SECTIONS, resetUiLayout, toggleHidden, useUiLayout,
} from '../../hooks/useUiLayout'
import { MiniLineChart, HeatMap } from '../charts'
import {
  Activity, ArrowRight, BarChart3, Book, Brain, Calendar, CalendarClock, Check, ChevronRight,
  Clock, FileText, Flame, Layers, RefreshCw, RotateCcw, School, Settings, Sparkles, Target,
  Trophy, Warning, Zap,
} from '../icons'
import {
  AnimatedNumber, Badge, Button, CardHead, Chip, Dialog, Empty, IconButton, Progress, Ring,
  Segmented, Skeleton, Tile, cx, toast, toastOk, toastErr,
} from '../ui'
import { FocusTile } from './widgets'
import '../styles/pages.css'
import '../styles/dash-glass.css'
import { dedupeSubjects } from '../../api/hub'

const RANGES = [
  { value: 'today', label: '今日' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: 'all', label: '全部' },
]
const RANGE_DAYS = { today: 1, '7d': 7, '30d': 30, all: 0 }
const PHASE_LABEL = { base: '基础期', intensify: '强化期', warning: '30 天预警', sprint: '最后冲刺', passed: '初试已结束' }
const MODULE_ROUTE = { focus: '/planner', word: '/words', card: '/cards', wrongbook: '/error-review', task: '/tasks', question: '/quiz', realexam: '/exam' }
const MODULE_ICON = { focus: Clock, word: Book, card: Layers, wrongbook: FileText, task: Target, question: Zap, realexam: FileText }
const REC_ICON = { review: RotateCcw, todo: Target, target: Activity, brain: Brain }

const toArr = (v) => (Array.isArray(v) ? v : [])
const pctOf = (done, total) => (total > 0 ? Math.round((done / total) * 100) : 0)

function greeting() {
  const h = new Date().getHours()
  if (h < 5) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 13) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

function useClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

export default function Dashboard() {
  const navigate = useNavigate()
  const settings = useStore((s) => s.settings)
  const tasks = useStore((s) => s.tasks)
  const words = useStore((s) => s.words)
  const notebook = useStore((s) => s.notebook)
  const cards = useStore((s) => s.cards)
  const toggletLocalTask = useStore((s) => s.toggleTask)
  const layout = useUiLayout()
  const now = useClock()

  const [live, setLive] = useState(null)
  const [status, setStatus] = useState('loading')
  const [range, setRange] = useState(() => {
    try { return localStorage.getItem(ukey('dash_range_v2')) || 'today' } catch { return 'today' }
  })
  const [auto, setAuto] = useState(() => {
    try { return localStorage.getItem(ukey('dash_auto_v2')) === '1' } catch { return false }
  })
  const [editOpen, setEditOpen] = useState(false)
  const [taskBusy, setTaskBusy] = useState(null)
  const [insight, setInsight] = useState(null)
  const [notices, setNotices] = useState([])
  const [reportOpen, setReportOpen] = useState(false)
  const [report, setReport] = useState(null)
  const [reportErr, setReportErr] = useState(null)
  const retry = useRef({ timer: null, attempt: 0 })

  const loadAll = useCallback(() => {
    if (retry.current.timer) {
      clearTimeout(retry.current.timer)
      retry.current.timer = null
    }
    return dashboardApi.summary()
      .then((d) => {
        setLive(d)
        setStatus('ok')
        retry.current.attempt = 0
        return true
      })
      .catch(() => {
        setStatus('error')
        const s = retry.current
        if (s.attempt >= 5) return false
        if (s.attempt === 0) toastErr('实时数据加载失败，正在自动重试…')
        s.attempt += 1
        s.timer = setTimeout(() => { s.timer = null; loadAll() }, 1000 * 2 ** (s.attempt - 1))
        return false
      })
  }, [])

  useEffect(() => {
    loadAll()
    const t = auto ? setInterval(loadAll, 30000) : null
    return () => {
      if (t) clearInterval(t)
      if (retry.current.timer) clearTimeout(retry.current.timer)
    }
  }, [loadAll, auto])

  useEffect(() => {
    let alive = true
    insightApi.today().then((d) => { if (alive) setInsight(d) }).catch(() => {})
    kaoyanApi.noticesFeed({ page: 1, page_size: 6 })
      .then((r) => { if (alive) setNotices(toArr(r?.items)) })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  const pickRange = (v) => {
    setRange(v)
    try { localStorage.setItem(ukey('dash_range_v2'), v) } catch { /* ignore */ }
  }
  const toggleAuto = () => {
    setAuto((v) => {
      try { localStorage.setItem(ukey('dash_auto_v2'), v ? '0' : '1') } catch { /* ignore */ }
      return !v
    })
  }
  const refresh = async () => {
    const ok = await loadAll()
    if (ok) toastOk('仪表盘已刷新')
  }

  const cd = live?.countdown || {}
  const effectiveExamDate = settings.examDate || cd.exam_date
  const examDate = resolveExamDate(effectiveExamDate, null)
  const days = examDaysLeft(examDate) ?? cd.days_left ?? null
  const examY = cd.exam_year || examYear(examDate)
  const phase = cd.phase || null
  const school = [cd.university || settings.school, cd.major || settings.major].filter(Boolean).join(' · ')
  const goalSchool = [live?.goal?.university, live?.goal?.major].filter(Boolean).join(' · ') || school
  const recentLines = toArr(live?.goal?.recent_score_lines)
  const lineScope = recentLines[0]?.scope

  const kpi = live?.kpi || {}
  const today = kpi.today || {}
  const delta = kpi.delta || {}
  const streak = kpi.streak || {}
  const queue = live?.review_queue || null
  const dueErrors = toArr(queue?.errors)
  const dueCardList = queue ? toArr(queue.cards) : dueCards(cards)
  const dueWordList = dueCards(words)
  const dueWordCount = dueWordList.length
  const dueTotal = dueErrors.length + dueCardList.length + dueWordCount
  const queueLocal = !queue || queue.source !== 'review_scheduler'

  const serverTasks = status === 'ok' ? toArr(live?.today_tasks?.tasks) : null
  const todayTasks = serverTasks
    ? serverTasks.map((t) => ({ id: String(t.id), title: t.title, subject: t.subject, status: t.status }))
    : tasks.filter((t) => t.due === todayStr()).map((t) => ({ id: String(t.id), title: t.title, subject: t.subject, status: t.done ? 'done' : 'pending' }))
  const doneTasks = todayTasks.filter((t) => t.status === 'done').length
  const taskPct = pctOf(doneTasks, todayTasks.length)

  const onToggleTask = async (t) => {
    const id = Number(t.id)
    if (status !== 'ok' || !Number.isInteger(id)) {
      toggletLocalTask(t.id)
      return
    }
    setTaskBusy(t.id)
    try {
      if (t.status === 'done') await tasksApi.uncomplete(id)
      else await tasksApi.complete(id)
      await loadAll()
    } catch {
      toggletLocalTask(t.id)
      toast('后端同步失败，已记在本地')
    } finally {
      setTaskBusy(null)
    }
  }

  const allDays = useMemo(() => toArr(live?.heatmap?.days).map((d) => ({
    date: d.date,
    duration: d.focus_minutes || 0,
    questions: d.questions_done || 0,
  })), [live])

  const rangeDays = RANGE_DAYS[range]
  const rangeCutoff = useMemo(() => {
    if (!rangeDays) return null
    const d = new Date()
    d.setDate(d.getDate() - (rangeDays - 1))
    return todayStr(d)
  }, [rangeDays])
  const rangeSeries = useMemo(() => {
    if (rangeDays === 1) {
      const s = toArr(live?.trend?.series).map((d) => ({
        date: d.date, duration: d.focus_minutes || 0, questions: d.questions_done || 0,
      }))
      return s.length ? s : allDays.slice(-14)
    }
    if (!rangeCutoff) return allDays
    return allDays.filter((d) => d.date >= rangeCutoff)
  }, [rangeDays, rangeCutoff, allDays, live])
  const rangeMinutes = rangeDays === 1
    ? (today.focus_minutes || 0)
    : rangeSeries.reduce((a, d) => a + d.duration, 0)
  const chartData = rangeSeries.map((d, i) => ({
    value: d.duration,
    label: i === rangeSeries.length - 1 ? '今天' : WEEK_CN[weekdayIdx(d.date)].slice(1),
  }))

  const weakness = live?.weakness?.has_weakness ? live.weakness : null
  const weakPoints = toArr(weakness?.weak_points)
  const modules = toArr(live?.module_progress)
  const taskModules = toArr(live?.today_tasks?.modules)
  const focusSubjects = useMemo(
    () => dedupeSubjects([...toArr(live?.goal?.subjects), ...toArr(live?.goal?.support_subjects)]),
    [live],
  )
  const recommendations = toArr(insight?.suggestions).slice(0, 4)

  const openReport = () => {
    setReportOpen(true)
    setReportErr(null)
    if (!report) {
      insightApi.weeklyReport().then(setReport).catch((e) => setReportErr(e?.message || '周报加载失败'))
    }
  }

  const visible = (id) => !layout.dashHidden.includes(id)
  const sections = DASH_SECTIONS
  const hiddenSections = new Set(layout.dashHidden)

  return (
    <div className="v3-dash v3-stack" style={{ gap: 20 }}>
      <header className="v3-page-head">
        <div>
          <div className="v3-eyebrow">
            {`${now.getMonth() + 1} 月 ${now.getDate()} 日 · 星期${WEEK_CN[weekdayIdx(todayStr())].slice(1)}`}
            {school ? ` · ${school}` : ' · 尚未设置目标院校'}
          </div>
          <h1 className="v3-h1" style={{ marginTop: 6 }}>{greeting()}，同学</h1>
          <p className="v3-body" style={{ marginTop: 6 }}>
            {days != null && days >= 0
              ? `距离 ${examY} 考研还有 ${days} 天，今天也把节奏握在手里。`
              : '今天也把节奏握在手里。'}
          </p>
        </div>
        <div className="v3-row v3-wrap" style={{ gap: 8 }}>
          <Button variant="tonal" size="sm" icon={<Sparkles size={15} />} onClick={() => navigate('/hub')}>今日中枢</Button>
          <Segmented options={RANGES} value={range} onChange={pickRange} ariaLabel="统计时间范围" />

          <IconButton label="刷新" icon={<RefreshCw size={17} />} onClick={refresh} />
          <IconButton label="自定义仪表盘" icon={<Settings size={17} />} onClick={() => setEditOpen(true)} />
          <Button variant="tonal" size="sm" icon={<BarChart3 size={15} />} onClick={openReport}>学习周报</Button>
        </div>
      </header>

      {/* 学科快捷入口（2026-10-24 全新展示：一键选学科刷题） */}
      {focusSubjects.length > 0 ? (
        <section className="v3-dash-subjects" aria-label="备考学科快捷入口">
          <div className="v3-dash-subjects__head">
            <h2 className="v3-h3">备考学科</h2>
            <button type="button" className="v3-dash-link" onClick={() => navigate('/quiz')}>全部刷题 →</button>
          </div>
          <div className="v3-dash-subjects__grid">
            {focusSubjects.map((s) => (
              <button
                key={s}
                type="button"
                className="v3-dash-subject"
                onClick={() => navigate(`/quiz?subject=${encodeURIComponent(s)}`)}
              >
                <span className="v3-dash-subject__name">{s}</span>
                <span className="v3-dash-subject__go">去刷题 <ArrowRight size={13} /></span>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {status === 'loading' ? (
        <div className="v3-bento">
          <Tile span={8}><Skeleton height={200} /></Tile>
          <Tile span={4}><Skeleton height={200} /></Tile>
          <Tile span={12}><Skeleton height={92} /></Tile>
        </div>
      ) : status === 'error' && !live ? (
        <Tile span={12}>
          <Empty
            icon={<Warning size={26} />}
            title="暂时连不上后端"
            text="数据不会用假数字填充。后端恢复后会自动重试。"
            action={<Button variant="tonal" onClick={refresh}>立即重试</Button>}
          />
        </Tile>
      ) : (
        <div className="v3-bento v3-dash__bento">
          {visible('hero') && (
            <>
              <Tile span={8} variant="gradient" className="v3-dash-hero">
                <div className="v3-row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div className="v3-dash-hero__eyebrow"><Calendar size={15} /> 考研倒计时</div>
                  {phase && <Badge tone="glass">{PHASE_LABEL[phase] || phase}</Badge>}
                </div>
                <div className="v3-dash-hero__count">
                  {days == null ? (
                    <span className="v3-dash-hero__word">先设置初试日期</span>
                  ) : days < 0 ? (
                    <>
                      <span className="v3-dash-hero__word">{examY} 初试已结束</span>
                      <Button
                        variant="glass"
                        size="sm"
                        icon={<CalendarClock size={15} />}
                        onClick={() => navigate('/settings')}
                        style={{ marginTop: 10 }}
                      >
                        设定下一年目标
                      </Button>
                    </>
                  ) : (
                    <>
                      <span className="v3-dash-hero__small">距离 {examY} 考研初试还有</span>
                      <span className="v3-dash-hero__days"><AnimatedNumber value={days} /></span>
                      <span className="v3-dash-hero__unit">天</span>
                    </>
                  )}
                </div>
                <div className="v3-dash-hero__meta">
                  <span><School size={14} /> {school || '未设置目标院校'}</span>
                  <span><Target size={14} /> 目标 {cd.total_score_target ?? settings.targetScore ?? '—'} 分</span>
                  <span><Calendar size={14} /> {examDate ? examDateMD(examDate) : '待设置'}{cd.is_default ? ' 预估' : ''}</span>
                  {cd.signup_hint ? <span><Clock size={14} /> {cd.signup_hint}</span> : null}
                </div>
                <div className="v3-row v3-wrap" style={{ gap: 10, marginTop: 'auto', paddingTop: 18 }}>
                  <Button variant="glass" icon={<FileText size={16} />} onClick={() => navigate('/notebook')}>拍一道错题</Button>
                  <Button variant="glass" icon={<Target size={16} />} onClick={() => navigate('/quiz')}>开始刷题</Button>
                  {cd.is_official === false && (
                    <Link to="/settings" className="v3-dash-hero__link"><Warning size={13} /> 核对初试日期</Link>
                  )}
                </div>
              </Tile>

              <Tile span={4} className="v3-dash-pulse">
                <CardHead title="今日节奏" sub="任务完成度与连续打卡" icon={<Activity size={17} />} />
                <div className="v3-dash-pulse__ring">
                  <Ring value={taskPct} size={132} stroke={11} gradient>
                    <div className="v3-dash-pulse__pct">
                      <strong><AnimatedNumber value={taskPct} format={(n) => `${Math.round(n)}%`} /></strong>
                      <span className="v3-caption">今日任务</span>
                    </div>
                  </Ring>
                </div>
                <div className="v3-dash-pulse__stats">
                  <div><Check size={15} /><span>已完成</span><b>{doneTasks}/{todayTasks.length}</b></div>
                  <div><Clock size={15} /><span>今日专注</span><b>{today.focus_minutes || 0} 分钟</b></div>
                  <div><Flame size={15} /><span>连续打卡</span><b>{streak.current || 0} 天</b></div>
                  <div><Trophy size={15} /><span>历史最长</span><b>{streak.longest || 0} 天</b></div>
                </div>
              </Tile>
            </>
          )}

          {visible('kpi') && (
            <Tile span={12} variant="well" className="v3-dash-kpi">
              {[
                { key: 'focus', label: '专注', value: today.focus_minutes, unit: '分钟', delta: delta.focus_minutes, icon: Clock },
                { key: 'questions', label: '答题', value: today.questions_done, unit: '道', delta: delta.questions_done, icon: Zap },
                { key: 'accuracy', label: '正确率', value: today.correct_rate, unit: '%', pct: true, icon: CrosshairIcon },
                { key: 'tasks', label: '完成任务', value: today.tasks_done, unit: '个', delta: delta.tasks_done, icon: Check },
                { key: 'errors', label: '错题复习', value: today.errors_done, unit: '道', delta: delta.errors_done, icon: RotateCcw },
                { key: 'words', label: '复习单词', value: today.words_done, unit: '个', delta: delta.words_done, icon: Book },
              ].map((m) => {
                const Icon = m.icon
                return (
                  <div key={m.key} className={cx('v3-dash-kpi__cell', m.value == null && 'is-nil')}>
                    <span className="v3-dash-kpi__label"><Icon size={14} /> {m.label}</span>
                    <span className="v3-dash-kpi__value">
                      {m.value == null ? '—' : m.pct ? `${Math.round(m.value)}%` : <AnimatedNumber value={m.value} />}
                      {m.value != null && !m.pct ? <em>{m.unit}</em> : null}
                    </span>
                    <span className={cx('v3-dash-kpi__delta', m.delta > 0 ? 'is-up' : m.delta < 0 ? 'is-down' : '')}>
                      {m.delta == null ? '昨日无可比数据' : m.delta === 0 ? '与昨日持平' : `${m.delta > 0 ? '↑' : '↓'} ${Math.abs(m.delta)}${m.pct ? '' : ''} 环比昨日`}
                    </span>
                  </div>
                )
              })}
            </Tile>
          )}

          {visible('todo') && (
            <Tile span={4} className="v3-dash-todo">
              <CardHead
                title="今日任务"
                sub={todayTasks.length ? `${doneTasks}/${todayTasks.length} 已完成` : '今天还没有安排'}
                icon={<Target size={17} />}
                actions={<Link to="/tasks" className="v3-dash-link">全部 <ChevronRight size={14} /></Link>}
              />
              {todayTasks.length ? (
                <div className="v3-dash-tasks">
                  {todayTasks.slice(0, 6).map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      className={cx('v3-dash-task', t.status === 'done' && 'is-done')}
                      aria-label={`${t.status === 'done' ? '标记未完成' : '标记完成'}：${t.title}`}
                      onClick={() => onToggleTask(t)}
                      disabled={taskBusy === t.id}
                    >
                      <span className="v3-dash-task__check">{t.status === 'done' ? <Check size={13} /> : null}</span>
                      <span className="v3-dash-task__main">
                        <span className="v3-dash-task__title">{t.title}</span>
                        {t.subject ? <span className="v3-caption">{t.subject}</span> : null}
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <Empty icon={<Check size={22} />} title="暂无今日任务" text="去任务页安排今天的三件事。" action={<Button size="sm" variant="tonal" onClick={() => navigate('/tasks')}>去安排</Button>} />
              )}
            </Tile>
          )}

          {visible('trend') && (
            <Tile span={5} className="v3-dash-trend">
              <CardHead
                title="学习趋势"
                sub={`${RANGES.find((r) => r.value === range)?.label || '今日'} · 共 ${rangeMinutes} 分钟`}
                icon={<Activity size={17} />}
                actions={<Badge tone="soft">分钟</Badge>}
              />
              <div className="v3-dash-trend__chart">
                <MiniLineChart data={chartData} height={150} />
              </div>
              <div className="v3-dash-trend__axis">
                {chartData.filter((_, i) => i % Math.max(1, Math.floor(chartData.length / 7)) === 0).map((d, i) => (
                  <span key={i}>{d.label}</span>
                ))}
              </div>
              <div className="v3-dash-trend__foot">
                <span><Zap size={13} /> 本周答题 {live?.trend?.weekly_completed_tasks ?? 0} 个任务</span>
                <Link to="/insights" className="v3-dash-link">学习洞察 <ArrowRight size={13} /></Link>
              </div>
            </Tile>
          )}

          {visible('review') && (
            <Tile span={3} className="v3-dash-review">
              <CardHead title="待复习" sub={queueLocal ? '本机估算 · 后端队列不可达' : '复习调度器口径'} icon={<RotateCcw size={17} />} />
              <div className="v3-dash-review__list">
                {[
                  { label: '错题', count: dueErrors.length, to: '/error-review', icon: FileText },
                  { label: '卡片', count: dueCardList.length, to: '/cards', icon: Layers },
                  { label: '单词', count: dueWordCount, to: '/words', icon: Book },
                ].map((x) => {
                  const Icon = x.icon
                  return (
                    <Link key={x.label} to={x.to} className="v3-dash-review__item">
                      <span className="v3-dash-review__icon"><Icon size={16} /></span>
                      <span className="v3-dash-review__label">{x.label}</span>
                      <b>{x.count}</b>
                      <ChevronRight size={14} />
                    </Link>
                  )
                })}
              </div>
              <button type="button" className="v3-dash-review__cta" onClick={() => navigate(dueErrors.length ? '/error-review' : '/cards')}>
                共 {dueTotal} 项待处理 <ArrowRight size={14} />
              </button>
            </Tile>
          )}

          {visible('heat') && (
            <Tile span={7} className="v3-dash-heat">
              <CardHead
                title="学习热力图"
                sub={`累计 ${Math.round(allDays.reduce((a, d) => a + d.duration, 0) / 60)} 小时 · 近 ${Math.ceil(allDays.length / 7)} 周`}
                icon={<CalendarClock size={17} />}
              />
              <div className="v3-dash-heat__chart">
                <HeatMap data={allDays.map((d) => ({ date: d.date, value: d.duration }))} color="var(--v3-primary)" />
              </div>
              <div className="v3-dash-heat__legend">
                <span className="v3-caption">少</span>
                {[0.15, 0.35, 0.55, 0.75, 1].map((o) => (
                  <i key={o} style={{ opacity: o }} />
                ))}
                <span className="v3-caption">多</span>
              </div>
            </Tile>
          )}

          {visible('goal') && (
            <Tile span={5} className="v3-dash-goal">
              <CardHead title="目标与分数线" sub={goalSchool || '尚未设置目标院校'} icon={<School size={17} />} actions={<Link to="/kaoyan" className="v3-dash-link">择校 <ChevronRight size={14} /></Link>} />
              {live?.goal?.configured ? (
                <>
                  <div className="v3-dash-goal__target">
                    <div>
                      <span className="v3-caption">目标总分</span>
                      <strong>{live.goal.score_targets?.total ?? '—'}</strong>
                    </div>
                    <div className="v3-dash-goal__subjects">
                      {dedupeSubjects(toArr(live.goal.subjects)).slice(0, 4).map((s) => <Chip key={s} as="span">{s}</Chip>)}
                    </div>
                  </div>
                  {recentLines.length ? (
                    <div className="v3-dash-goal__lines">
                      <span className="v3-caption">
                        近年复试线{lineScope === 'major' ? '（目标专业最低）' : lineScope === 'school' ? '（全校最低）' : ''}
                      </span>
                      <div className="v3-row" style={{ gap: 10, alignItems: 'flex-end', marginTop: 8 }}>
                        {recentLines.slice(0, 5).map((l, i) => {
                          const max = Math.max(...recentLines.map((x) => x.total_line || 0), 1)
                          return (
                            <div key={`${l.year}-${i}`} className="v3-dash-goal__bar">
                              <b>{l.total_line}</b>
                              <i style={{ height: `${Math.max(12, ((l.total_line || 0) / max) * 74)}px` }} />
                              <span className="v3-caption">{l.year}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ) : (
                    <p className="v3-caption" style={{ marginTop: 14 }}>库里还没有这所院校的复试线，不补造数据。</p>
                  )}
                </>
              ) : (
                <Empty icon={<School size={22} />} title="还没设置目标" text="在择校中心确定院校与专业，倒数与分数线会一起对齐。" action={<Button size="sm" variant="tonal" onClick={() => navigate('/kaoyan')}>去择校</Button>} />
              )}
            </Tile>
          )}

          {visible('focus') && (
            <Tile span={4} className="v3-dash-focus">
              <CardHead title="专注计时" sub="真实写入学习时长" icon={<Clock size={17} />} />
              <FocusTile
                todayMinutes={today.focus_minutes || 0}
                targetMinutes={live?.goal?.daily_targets?.focus_minutes ?? null}
                subjects={focusSubjects}
                onRecorded={loadAll}
              />
            </Tile>
          )}

          {visible('weakness') && (
            <Tile span={4} className="v3-dash-weak">
              <CardHead title="薄弱考点" sub={weakness ? `活跃错题 ${weakness.total_errors} 道` : '暂未识别到薄弱点'} icon={<Warning size={17} />} actions={<Link to="/error-review" className="v3-dash-link">复盘 <ChevronRight size={14} /></Link>} />
              {weakPoints.length ? (
                <div className="v3-dash-weak__list">
                  {weakPoints.slice(0, 4).map((w) => (
                    <Link
                      key={`${w.knowledge_point_id}-${w.name}`}
                      to={`/error-review?kp_id=${w.knowledge_point_id}&kp_name=${encodeURIComponent(w.name || '')}`}
                      className="v3-dash-weak__item"
                    >
                      <span className="v3-dash-weak__name">{w.name}</span>
                      <span className="v3-caption">{w.subject || w.chapter || '未归类'} · 错 {w.error_count} 次</span>
                      <Progress value={Number(w.mastery) || 0} height={5} />
                    </Link>
                  ))}
                </div>
              ) : (
                <Empty
                  icon={<Sparkles size={22} />}
                  title={weakness ? '错题还没归集到考点' : '没有薄弱点'}
                  text={weakness
                    ? '有错题但还没挂到具体考点，去错题本逐题补挂后这里会排出薄弱顺序。'
                    : '继续按计划复习，错题会在这里汇总。'}
                />
              )}
            </Tile>
          )}

          {visible('recommend') && (
            <Tile span={4} className="v3-dash-recs">
              <CardHead title="今日建议" sub="来自学习洞察" icon={<Sparkles size={17} />} />
              {recommendations.length ? (
                <div className="v3-dash-recs__list">
                  {recommendations.map((r, i) => {
                    const Icon = REC_ICON[r.icon] || Sparkles
                    return (
                      <Link key={`${r.to}-${i}`} to={r.to || '/quiz'} className="v3-dash-rec">
                        <span className={cx('v3-dash-rec__icon', `tone-${i % 4}`)}><Icon size={16} /></span>
                        <span className="v3-dash-rec__main">
                          <span className="v3-dash-rec__title">{r.label}{r.count != null ? ` · ${r.count}` : ''}</span>
                          <span className="v3-caption">{r.hint}</span>
                        </span>
                        <ChevronRight size={14} />
                      </Link>
                    )
                  })}
                </div>
              ) : (
                <Empty icon={<Sparkles size={22} />} title="建议生成中" text="有足够学习记录后，这里会按优先级给出今天的三件事。" action={<Button size="sm" variant="tonal" onClick={() => navigate('/quiz')}>直接刷题</Button>} />
              )}
            </Tile>
          )}

          {visible('modules') && (
            <Tile span={12} className="v3-dash-modules">
              <CardHead title="今日模块进度" sub="每个数字都来自后端聚合，不写死目标" icon={<Layers size={17} />} actions={<Link to="/insights" className="v3-dash-link">看全部 <ChevronRight size={14} /></Link>} />
              <div className="v3-dash-modules__grid">
                {taskModules.length ? taskModules.map((m) => {
                  const Icon = MODULE_ICON[m.module] || Layers
                  const untracked = m.status === 'not_tracked'
                  const ratio = m.due > 0 ? Math.round(((m.done || 0) / m.due) * 100) : 0
                  return (
                    <Link
                      key={m.module}
                      to={MODULE_ROUTE[m.module] || '/tasks'}
                      className={cx('v3-dash-mod', untracked && 'is-untracked', m.status === 'clear' && 'is-clear')}
                      title={untracked ? m.note : undefined}
                    >
                      <span className="v3-dash-mod__icon"><Icon size={17} /></span>
                      <span className="v3-dash-mod__label">{m.label}</span>
                      <span className="v3-dash-mod__value">{untracked ? '—' : m.due > 0 ? `${m.done || 0}/${m.due} ${m.unit}` : '无到期'}</span>
                      {untracked
                        ? <span className="v3-caption v3-dash-mod__note">{m.note}</span>
                        : <Progress value={ratio} height={4} />}
                    </Link>
                  )
                }) : modules.map((m) => {
                  const Icon = MODULE_ICON[m.module] || Layers
                  return (
                    <Link key={m.module} to={MODULE_ROUTE[m.module] || '/tasks'} className="v3-dash-mod">
                      <span className="v3-dash-mod__icon"><Icon size={17} /></span>
                      <span className="v3-dash-mod__label">{m.label}</span>
                      <span className="v3-dash-mod__value">{m.percent == null ? `${m.done ?? '—'} ${m.unit}` : `${m.percent}%`}</span>
                      <Progress value={m.percent || 0} height={4} />
                    </Link>
                  )
                })}
              </div>
            </Tile>
          )}

          {visible('notice') && notices.length > 0 && (
            <Tile span={12} className="v3-dash-notice">
              <CardHead title="院校公告" sub="来自择校模块的当日推送" icon={<FileText size={17} />} actions={<Link to="/kaoyan/notices" className="v3-dash-link">全部公告 <ChevronRight size={14} /></Link>} />
              <div className="v3-dash-notice__list">
                {notices.slice(0, 4).map((n, i) => (
                  <Link key={n.id || i} to="/kaoyan/notices" className="v3-dash-notice__item">
                    <Badge tone="soft">{n.source || n.school || '公告'}</Badge>
                    <span>{n.title}</span>
                    <span className="v3-caption">{n.published_at || n.date || ''}</span>
                  </Link>
                ))}
              </div>
            </Tile>
          )}
        </div>
      )}

      <Dialog open={editOpen} title="自定义仪表盘" sub="显隐偏好保存在本机，不影响其他设备。" onClose={() => setEditOpen(false)} footer={(
        <>
          <Button variant="text" icon={<RotateCcw size={15} />} onClick={() => { resetUiLayout(); toast('已恢复默认布局') }}>恢复默认</Button>
          <Button onClick={() => setEditOpen(false)}>完成</Button>
        </>
      )}>
        <div className="v3-stack" style={{ gap: 6 }}>
          {sections.map((s) => (
            <div key={s.id} className="v3-dash-edit-row">
              <span>{s.label}</span>
              <Button size="sm" variant={hiddenSections.has(s.id) ? 'text' : 'tonal'} onClick={() => toggleHidden('dashHidden', s.id)}>
                {hiddenSections.has(s.id) ? '已隐藏' : '显示中'}
              </Button>
            </div>
          ))}
          <div className="v3-dash-edit-row">
            <span>自动刷新（30 秒）</span>
            <Button size="sm" variant={auto ? 'tonal' : 'text'} onClick={toggleAuto}>{auto ? '已开启' : '已关闭'}</Button>
          </div>
        </div>
      </Dialog>

      <Dialog open={reportOpen} title="学习周报" sub="本周与上周的真实聚合" onClose={() => setReportOpen(false)} footer={<Button onClick={() => setReportOpen(false)}>关闭</Button>}>
        {reportErr ? <Empty icon={<Warning size={22} />} title="周报加载失败" text={reportErr} /> : !report ? <Skeleton height={160} /> : (
          <div className="v3-stack" style={{ gap: 16 }}>
            <div className="v3-grid-3">
              {[
                { label: '答题', value: report.this_week?.answered ?? 0, unit: '道' },
                { label: '正确率', value: report.this_week?.accuracy == null ? '—' : Math.round(report.this_week.accuracy * 100), unit: report.this_week?.accuracy == null ? '' : '%' },
                { label: '学习时长', value: report.this_week?.duration ?? 0, unit: '分钟' },
              ].map((x) => (
                <div key={x.label} className="v3-well" style={{ padding: 14, borderRadius: 16 }}>
                  <span className="v3-caption">{x.label}</span>
                  <div className="v3-h2" style={{ marginTop: 4 }}>{x.value}<span className="v3-caption"> {x.unit}</span></div>
                </div>
              ))}
            </div>
            <div className="v3-row v3-wrap" style={{ gap: 12 }}>
              <Badge tone={report.answered_delta == null ? 'outline' : report.answered_delta >= 0 ? 'success' : 'warning'}>
                环比 {report.answered_delta == null ? '无可比数据' : `${report.answered_delta > 0 ? '+' : ''}${report.answered_delta}%`}
              </Badge>
              <span className="v3-caption">
                上周 {report.last_week?.answered ?? '—'} 题 · 正确率 {report.last_week?.accuracy == null ? '—' : `${Math.round(report.last_week.accuracy * 100)}%`}
              </span>
            </div>
            <div>
              <div className="v3-caption" style={{ marginBottom: 8 }}>每日答题</div>
              <div className="v3-row" style={{ gap: 8, alignItems: 'flex-end', height: 90 }}>
                {toArr(report.daily).map((d) => {
                  const max = Math.max(...toArr(report.daily).map((x) => x.answered || 0), 1)
                  return (
                    <div key={d.date} className="v3-dash-goal__bar" style={{ flex: 1 }}>
                      <b>{d.answered || 0}</b>
                      <i style={{ height: `${Math.max(6, ((d.answered || 0) / max) * 56)}px` }} />
                      <span className="v3-caption">{d.date?.slice(5)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
            {report.summary ? <p className="v3-body">{report.summary}</p> : null}
          </div>
        )}
      </Dialog>
    </div>
  )
}

function CrosshairIcon(props) {
  return <Activity {...props} />
}
