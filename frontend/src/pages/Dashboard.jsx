import React, { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import useStore from '../store/useStore'
import { daysBetween, todayStr, weekdayIdx, WEEK_CN } from '../utils/date'
import { reviewStatus } from '../utils/ebbinghaus'
import { dueCards } from '../utils/spaced'
import { CountUp, Empty, toast } from '../components/UI'
import { dashboardApi } from '../api/client'
import { MiniLineChart, RingProgress } from '../components/Charts'
import {
  Target, Clock, Book, Calendar, Warning, ChevronRight, CheckCircle,
  Folder, GraduationCap, Brain, MessageSquare, Settings, FileText, Cloud,
  Map as MapIcon,
} from '../components/Icon'
import './Dashboard.css'

/* 首页模块跳转矩阵（仿大平台首页，一键直达任意功能） */
const MODULES = [
  { to: '/tasks', label: '任务打卡', icon: Target },
  { to: '/kbmap', label: '知识地图', icon: MapIcon },
  { to: '/quiz', label: '刷题中心', icon: Book },
  { to: '/codebank', label: '复试代码题库', icon: Book },
  { to: '/notebook', label: '错题本', icon: FileText },
  { to: '/words', label: '单词记忆', icon: GraduationCap },
  { to: '/cards', label: '记忆卡片', icon: Brain },
  { to: '/documents', label: '文档知识库', icon: Folder },
  { to: '/pan', label: '网盘联动', icon: Cloud },
  { to: '/planner', label: '学习计划', icon: Calendar },
  { to: '/assistant', label: 'AI 助手', icon: MessageSquare },
  { to: '/settings', label: '设置', icon: Settings },
]

/* 实时时钟 */
function LiveClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const wd = weekdayIdx(todayStr())
  return `${now.getMonth() + 1}月${now.getDate()}日 星期${WEEK_CN[wd].slice(1)}`
}

/* 连续打卡天数（依据后端每日学习时长，>0 分钟即算打卡） */
function calcStreak(dailyTrend) {
  const done = new Set((dailyTrend || []).filter((d) => (d.duration || 0) > 0).map((d) => d.date))
  const d = new Date()
  if (!done.has(todayStr())) d.setDate(d.getDate() - 1)
  let streak = 0
  while (done.has(todayStr(d))) {
    streak++
    d.setDate(d.getDate() - 1)
  }
  return streak
}

export default function Dashboard() {
  const navigate = useNavigate()
  const settings = useStore((s) => s.settings)
  const tasks = useStore((s) => s.tasks)
  const notebook = useStore((s) => s.notebook)
  const words = useStore((s) => s.words)
  const cards = useStore((s) => s.cards)

  const [live, setLive] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ok | error

  useEffect(() => {
    let alive = true
    dashboardApi.get()
      .then((d) => { if (alive) { setLive(d); setStatus('ok') } })
      .catch(() => {
        if (alive) {
          setStatus('error')
          toast('驾驶舱实时数据加载失败，已切换为本地缓存概览')
        }
      })
    return () => { alive = false }
  }, [])

  /* ---------- 倒计时 ---------- */
  const cd = live && live.countdown
  const examDate = (cd && cd.exam_date) || settings.examDate || '2027-12-25'
  const days = cd && cd.days != null ? cd.days : daysBetween(todayStr(), examDate)

  /* ---------- 今日任务（后端优先，本地兜底） ----------
     注意 live 可能为 null：后端返回 2xx 但无 JSON 体时 client 会 resolve(null)，
     此时 status 仍是 'ok'，故这里必须用 live?. 防御，否则整页白屏。 */
  let todayTasks = []
  if (status === 'ok' && live?.today_tasks) {
    todayTasks = (live.today_tasks.tasks || []).map((t) => ({
      id: String(t.id),
      title: t.title,
      subject: t.subject,
      status: t.status,
    }))
  } else {
    todayTasks = tasks.filter((t) => t.due === todayStr()).map((t) => ({
      id: String(t.id), title: t.title, subject: t.subject, status: t.done ? 'done' : 'pending',
    }))
  }
  const doneCount = todayTasks.filter((t) => t.status === 'done').length
  const todayPct = todayTasks.length ? Math.round((doneCount / todayTasks.length) * 100) : 0

  /* ---------- 复习队列 ---------- */
  const reviews = notebook
    .map((n) => ({ n, rs: reviewStatus(n) }))
    .filter((x) => x.rs.status !== 'new')
    .sort((a, b) => ({ due: 0, reviewing: 1, mastered: 2 }[a.rs.status] - { due: 0, reviewing: 1, mastered: 2 }[b.rs.status]))
  const dueReviews = reviews.filter((x) => x.rs.status === 'due').length
  const dueWordCount = dueCards(words).length
  const dueCardCount = dueCards(cards).length

  /* ---------- 统计（后端优先） ----------
     学习时长/趋势/打卡全部来自后端 study_sessions 聚合，
     不再依赖已移除的番茄钟本地数据。 */
  const stats = live && live.stats
  const weekMinutes = stats ? (stats.week_duration || 0) : 0
  const activeErrors = stats ? (stats.active_errors || 0) : notebook.length
  const weeklyDone = stats ? (stats.weekly_completed_tasks || 0) : tasks.filter((t) => t.done).length

  /* 每日学习时长（近 7 天，后端为准；无数据时补零） */
  const dailyTrend = useMemo(() => {
    const fromApi = (stats && stats.daily_trend ? stats.daily_trend : [])
    if (fromApi.length) return fromApi
    const out = []
    const today = new Date()
    for (let i = 6; i >= 0; i--) {
      const d = new Date(today)
      d.setDate(d.getDate() - i)
      out.push({ date: todayStr(d), duration: 0 })
    }
    return out
  }, [stats])

  const streak = calcStreak(dailyTrend)

  /* ---------- 趋势数据（单位：分钟） ---------- */
  const trend = dailyTrend.map((d) => ({
    label: WEEK_CN[weekdayIdx(d.date)].slice(1),
    value: Math.round(d.duration || 0),
  }))

  const weakness = live && live.weakness && live.weakness.has_weakness ? live.weakness : null
  const loading = status === 'loading'
  const topReviews = reviews.slice(0, 4)

  /* ---------- 学习热力图（12周×7天，单位：分钟） ---------- */
  const heatmapData = useMemo(() => {
    // 后端只给近 7 天，其余按 0 处理 —— 不再依赖已移除的番茄钟本地记录
    const byDate = new Map((stats?.daily_trend || []).map((d) => [d.date, d.duration || 0]))
    const weeks = []
    const today = new Date()
    const startDate = new Date(today)
    startDate.setDate(startDate.getDate() - 12 * 7 + (6 - today.getDay()))
    for (let w = 0; w < 12; w++) {
      const week = []
      for (let d = 0; d < 7; d++) {
        const date = new Date(startDate)
        date.setDate(date.getDate() + w * 7 + d)
        const key = todayStr(date)
        week.push({ date: key, count: byDate.get(key) || 0, isFuture: date > today })
      }
      weeks.push(week)
    }
    return weeks
  }, [stats])

  const heatmapMax = Math.max(...heatmapData.flat().map((d) => d.count), 1)
  const totalHeatmap = heatmapData.flat().filter((d) => !d.isFuture).reduce((a, d) => a + d.count, 0)
  /* 蓝系热力分级：0 空 / 1-5 由浅到深 */
  const heatLevel = (day) => {
    if (day.isFuture || day.count === 0) return 0
    return Math.min(5, Math.max(1, Math.round((day.count / heatmapMax) * 5)))
  }

  /* ---------- 智能每日推荐 ---------- */
  const smartRecommendations = useMemo(() => {
    const recs = []
    // 1. 待复习错题
    if (dueReviews > 0) {
      recs.push({
        type: 'review', icon: '📝',
        title: `复习 ${dueReviews} 道错题`,
        desc: '按艾宾浩斯曲线，这些错题今天需要复习巩固',
        action: '/notebook', priority: 1,
      })
    }
    // 2. 待复习单词
    if (dueWordCount > 0) {
      recs.push({
        type: 'words', icon: '📖',
        title: `背诵 ${dueWordCount} 个单词`,
        desc: '今日待复习单词，四档评分高效记忆',
        action: '/words', priority: 2,
      })
    }
    // 3. 待完成任务
    const pendingTasks = todayTasks.filter((t) => t.status !== 'done')
    if (pendingTasks.length > 0) {
      recs.push({
        type: 'tasks', icon: '✅',
        title: `完成 ${pendingTasks.length} 个今日任务`,
        desc: pendingTasks[0]?.title || '今日待办任务',
        action: '/tasks', priority: 3,
      })
    }
    // 4. 薄弱科目
    if (weakness && weakness.weak_subjects?.length > 0) {
      recs.push({
        type: 'weakness', icon: '⚠️',
        title: `攻克 ${weakness.weak_subjects[0].subject} 薄弱点`,
        desc: `${weakness.weak_subjects[0].count} 道活跃错题，建议专项突破`,
        action: '/notebook', priority: 4,
      })
    }
    // 5. 兜底推荐：去刷题
    if (recs.length === 0) {
      recs.push({
        type: 'focus', icon: '🎯',
        title: '开始今天的刷题',
        desc: '从真题库挑一组题练手',
        action: '/quiz', priority: 1,
      })
    }
    return recs.sort((a, b) => a.priority - b.priority).slice(0, 4)
  }, [dueReviews, dueWordCount, todayTasks, weakness])

  /* ---------- 今日时间轴 ---------- */
  const todayTimeline = useMemo(() => {
    const events = []
    // 今日学习时长（后端聚合）
    const todayMinutes = (stats && stats.today_duration) || 0
    if (todayMinutes > 0) {
      events.push({
        time: '全天', icon: '⏱',
        title: `今日学习 ${todayMinutes} 分钟`,
        desc: `约 ${(todayMinutes / 60).toFixed(1)} 小时`,
        type: 'focus',
      })
    }
    // 今日完成的任务
    todayTasks.filter((t) => t.status === 'done').forEach((t) => {
      events.push({
        time: '今日', icon: '✅', title: t.title, desc: '任务已完成', type: 'task',
      })
    })
    // 今日待复习
    if (dueReviews > 0) {
      events.push({
        time: '待完成', icon: '📝',
        title: `${dueReviews} 道错题待复习`,
        desc: '按艾宾浩斯曲线复习',
        type: 'review',
      })
    }
    return events.slice(0, 6)
  }, [stats, todayTasks, dueReviews])

  const [today, setToday] = useState(null)
  const [report, setReport] = useState(null)
  const [showReport, setShowReport] = useState(false)

  useEffect(() => {
    /* V11: 今日学习引导（一次拉齐：到期复习/今日任务/今日答题/薄弱点/行动清单） */
    import('../api/client').then(({ insightApi }) => {
      insightApi.today().then(setToday).catch(() => setToday(null))
    })
  }, [])

  const openReport = () => {
    setShowReport(true)
    if (!report) {
      import('../api/client').then(({ insightApi }) => {
        insightApi.weeklyReport().then(setReport).catch(() => setShowReport(false))
      })
    }
  }

  return (
    <div className="dash">
      {/* ===== V11 今日学习引导条（打开就知道该干什么） ===== */}
      {today && (
        <section className="dash-today" aria-label="今日学习引导">
          <div className="dash-today-head">
            <strong>📌 今日该干什么</strong>
            <span className="dash-today-sub">{today.suggestion?.[0] || '按下面清单推进即可'}</span>
          </div>
          <div className="dash-today-grid">
            <button className="dash-today-card" onClick={() => navigate('/review')}>
              <em style={{ color: 'var(--gold)' }}>{today.due_review_count}</em>
              <span>到期复习</span>
            </button>
            <button className="dash-today-card" onClick={() => navigate('/tasks')}>
              <em style={{ color: 'var(--accent)' }}>{today.today_tasks_count}</em>
              <span>今日任务</span>
            </button>
            <button className="dash-today-card" onClick={() => navigate('/quiz')}>
              <em style={{ color: '#16a34a' }}>{today.today_answered}</em>
              <span>今日已答</span>
            </button>
            {today.weak_top?.[0] && (
              <button className="dash-today-card" onClick={() => navigate('/quiz?subject=' + encodeURIComponent(today.weak_top[0].subject || ''))}>
                <em style={{ color: '#ef4444' }}>薄弱</em>
                <span>{(today.weak_top[0].knowledge_point || '').slice(0, 10) || '考点待诊断'}</span>
              </button>
            )}
            <button className="dash-today-card" onClick={openReport}>
              <em style={{ color: 'var(--accent-strong)' }}>周报</em>
              <span>本周 vs 上周</span>
            </button>
          </div>
        </section>
      )}

      {/* ===== V11 学习周报弹层 ===== */}
      {showReport && (
        <div className="dash-report-mask" onClick={() => setShowReport(false)}>
          <div className="dash-report" onClick={e => e.stopPropagation()}>
            <div className="dash-report-head">
              <strong>📊 学习周报</strong>
              <button className="dash-report-close" onClick={() => setShowReport(false)}>✕</button>
            </div>
            {!report ? (
              <div className="dash-report-loading">生成中…</div>
            ) : (
              <>
                <div className="dash-report-summary">{report.summary}</div>
                <div className="dash-report-grid">
                  <div><em>{report.this_week.answered}</em><span>本周答题{report.last_week.answered ? `（上周 ${report.last_week.answered}）` : ''}</span></div>
                  <div><em>{report.this_week.accuracy != null ? Math.round(report.this_week.accuracy * 100) + '%' : '—'}</em><span>正确率{report.last_week.accuracy != null ? `（上周 ${Math.round(report.last_week.accuracy * 100)}%）` : ''}</span></div>
                  <div><em>{report.this_week.duration_min}</em><span>学习时长（分钟）</span></div>
                  <div><em>{report.delta.direction === 'up' ? '↑' : report.delta.direction === 'down' ? '↓' : '→'}</em><span>环比 {report.delta.text}</span></div>
                </div>
                <div className="dash-report-bars">
                  {report.daily.map(d => (
                    <div key={d.date} className="dash-report-bar-item" title={d.date}>
                      <i style={{ height: `${Math.min(100, d.answered * 6)}%` }} />
                      <b>{d.answered || ''}</b>
                      <span>{d.label}</span>
                    </div>
                  ))}
                </div>
                {report.weak_delta?.length > 0 && (
                  <div className="dash-report-weak">
                    <b>薄弱考点变化：</b>
                    {report.weak_delta.map((w, i) => (
                      <span key={i} className="dash-report-weak-tag">{w.knowledge_point?.slice(0, 12)} {w.change}</span>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* ===== Hero 渐变倒计时 ===== */}
      <section className="dash-hero">
        <div className="dash-hero-glow" />
        <div className="dash-hero-inner">
          <div>
            <div className="dash-hero-greet">
              {LiveClock()} · 目标 {cd?.university || settings.school || '贵州大学'} {cd?.major || settings.major || '电子信息'}
            </div>
            <h1 className="dash-hero-title">
              距 2027 考研还有<span className="dash-hero-days"><CountUp value={days > 0 ? days : 0} /></span>天
            </h1>
            <div className="dash-hero-goal">
              <span><Target size={14} /> 目标分数 {cd?.total_score_target || settings.targetScore || 360}</span>
              <span><Clock size={14} /> 今日 {todayTasks.length} 个任务</span>
              <span><Book size={14} /> 本周学习 {weekMinutes} 分钟</span>
            </div>
          </div>
          <div className="dash-hero-cta">
            <button className="btn primary" onClick={() => navigate('/notebook')}>
              <FileText size={18} /> 拍一道错题
            </button>
            <div className="hero-stats">
              <span className="hero-stat">连续打卡 <b>{streak}</b> 天</span>
              <span className="hero-stat">本周完成 <b>{weeklyDone}</b></span>
              <span className="hero-stat">活跃错题 <b>{activeErrors}</b></span>
            </div>
          </div>
        </div>
      </section>

      {/* ===== 加载骨架 ===== */}
      {loading && (
        <div className="stat-grid">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="stat-card">
              <div className="skeleton" />
              <div className="skeleton sk-line" />
              <div className="skeleton sk-line" />
            </div>
          ))}
        </div>
      )}

      {/* ===== 错误态（toast 已在请求失败时弹出，此处就地提示 + 本地缓存降级） ===== */}
      {status === 'error' && (
        <div className="dash-error">
          驾驶舱实时数据加载失败（后端未启动或网络异常）。已为你展示本地缓存概览，启动后端后将自动恢复实时数据。
        </div>
      )}

      {/* ===== 4 张统计卡（全部可点，跳转对应模块） ===== */}
      {!loading && (
        <div className="stat-grid">
          <div className="stat-card clickable" role="button" tabIndex={0}
            onClick={() => navigate('/kbmap')}
            onKeyDown={(e) => { if (e.key === 'Enter') navigate('/kbmap') }}>
            <div className="stat-top">
              <div className="stat-ico blue"><Clock size={18} /></div>
              <span className="stat-trend up">本周</span>
            </div>
            <div className="stat-val">{(weekMinutes / 60).toFixed(1)}<span className="stat-unit">h</span></div>
            <div className="stat-label">学习时长</div>
            <span className="stat-go">查看 <ChevronRight size={13} /></span>
          </div>
          <div className="stat-card clickable" role="button" tabIndex={0}
            onClick={() => navigate('/tasks')}
            onKeyDown={(e) => { if (e.key === 'Enter') navigate('/tasks') }}>
            <div className="stat-top">
              <div className="stat-ico green"><Target size={18} /></div>
              <span className="stat-trend flat">今日</span>
            </div>
            <div className="stat-val">{todayTasks.length}</div>
            <div className="stat-label">今日任务 · 已完成 {doneCount}</div>
            <span className="stat-go">查看 <ChevronRight size={13} /></span>
          </div>
          <div className="stat-card clickable" role="button" tabIndex={0}
            onClick={() => navigate('/notebook')}
            onKeyDown={(e) => { if (e.key === 'Enter') navigate('/notebook') }}>
            <div className="stat-top">
              <div className="stat-ico amber"><Book size={18} /></div>
              <span className="stat-trend flat">待处理</span>
            </div>
            <div className="stat-val">{dueReviews + dueWordCount + dueCardCount}</div>
            <div className="stat-label">待复习（错/词/卡）</div>
            <span className="stat-go">查看 <ChevronRight size={13} /></span>
          </div>
          <div className="stat-card clickable" role="button" tabIndex={0}
            onClick={() => navigate('/planner')}
            onKeyDown={(e) => { if (e.key === 'Enter') navigate('/planner') }}>
            <div className="stat-top">
              <div className="stat-ico violet"><Calendar size={18} /></div>
              <span className="stat-trend up">连续</span>
            </div>
            <div className="stat-val">{streak}<span className="stat-unit">天</span></div>
            <div className="stat-label">学习打卡</div>
            <span className="stat-go">查看 <ChevronRight size={13} /></span>
          </div>
        </div>
      )}

      {/* ===== 今日任务 + 复习提醒 ===== */}
      {!loading && (
        <div className="dash-row">
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">今日待办</h3>
              <span className="panel-badge">{doneCount}/{todayTasks.length} 已完成</span>
            </div>
            <div className="today-progress">
              <RingProgress percent={todayPct} size={72} strokeWidth={7}>
                <span className="today-progress-pct">{todayPct}%</span>
              </RingProgress>
              <div className="today-progress-info">
                <p className="today-progress-hint">完成 {doneCount} 个，还剩 {todayTasks.length - doneCount} 个</p>
                <button className="link-btn" onClick={() => navigate('/tasks')}>
                  查看全部任务 <ChevronRight size={13} />
                </button>
              </div>
            </div>
            <div className="task-list">
              {todayTasks.length === 0 && (
                <Empty icon={<CheckCircle size={22} />} title="今日暂无任务" desc="去任务页安排今天的复习计划" />
              )}
              {todayTasks.slice(0, 6).map((t) => (
                <div key={t.id} className={`task-item ${t.status === 'done' ? 'done' : ''}`}>
                  <span className={`task-dot ${t.status === 'done' ? 'done' : t.status === 'doing' ? 'doing' : ''}`} />
                  <span className="task-text">{t.title}</span>
                  {t.subject && <span className="task-subject">{t.subject}</span>}
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">复习提醒</h3>
              <span className="panel-badge amber">{dueReviews} 项逾期</span>
            </div>
            <div className="review-list">
              {topReviews.length === 0 && (
                <Empty icon={<CheckCircle size={22} />} title="暂无待复习内容" desc="状态良好，继续保持" />
              )}
              {topReviews.map(({ n, rs }) => (
                <div key={n.id} className="review-item">
                  <span className={`review-dot ${rs.status === 'due' ? 'due' : 'soon'}`} />
                  <div className="review-info">
                    <div className="review-name">{n.subject || n.title || '未命名错题'}</div>
                    <div className="review-meta">{rs.status === 'due' ? '已到期 · 建议立即复习' : '复习中 · 按计划巩固'}</div>
                  </div>
                  <button className="review-btn" onClick={() => navigate('/notebook')}>复习</button>
                </div>
              ))}
            </div>
            <button className="btn primary full" onClick={() => navigate('/notebook')}>全部开始复习</button>
          </div>
        </div>
      )}

      {/* ===== 可视化区：本周专注趋势 + 学习热力图 ===== */}
      {!loading && (
        <div className="dash-row">
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">本周专注趋势</h3>
              <span className="panel-sub">单位：学习分钟数</span>
            </div>
            <div className="focus-chart">
              <MiniLineChart data={trend} height={180} showArea color="var(--accent)" />
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">学习热力图</h3>
              <span className="panel-sub">近12周 · 共 {totalHeatmap} 分钟</span>
            </div>
            <div className="heat-wrap">
              {heatmapData.map((week, wi) => (
                <div key={wi} className="heat-col">
                  {week.map((day, di) => (
                    <div
                      key={di}
                      className={`heat-cell lvl-${heatLevel(day)}`}
                      title={`${day.date}: ${day.count} 分钟`}
                    />
                  ))}
                </div>
              ))}
            </div>
            <div className="heat-legend">
              <span>少</span>
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <span key={i} className={`heat-cell lvl-${i}`} />
              ))}
              <span>多</span>
            </div>
          </div>
        </div>
      )}

      {/* ===== 智能每日推荐 + 今日时间轴 ===== */}
      {!loading && (
        <div className="dash-row">
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">🎯 今日智能推荐</h3>
              <span className="panel-badge">AI 规划</span>
            </div>
            <div className="rec-list">
              {smartRecommendations.map((rec, i) => (
                <div
                  key={i}
                  className="rec-item"
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(rec.action)}
                  onKeyDown={(e) => { if (e.key === 'Enter') navigate(rec.action) }}
                >
                  <span className="rec-icon">{rec.icon}</span>
                  <div className="rec-main">
                    <div className="rec-title">{rec.title}</div>
                    <div className="rec-desc">{rec.desc}</div>
                  </div>
                  <ChevronRight size={16} className="rec-chev" />
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">⏱️ 今日时间轴</h3>
              <span className="panel-sub">学习活动记录</span>
            </div>
            {todayTimeline.length === 0 ? (
              <Empty icon={<Clock size={22} />} title="今天还没有学习记录" desc="去刷题或看看考点吧" />
            ) : (
              <div className="tl">
                {todayTimeline.map((event, i) => (
                  <div key={i} className="tl-item">
                    <span className={`tl-dot ${event.type}`} />
                    <div className="tl-time">{event.time}</div>
                    <div className="tl-title">{event.icon} {event.title}</div>
                    <div className="tl-desc">{event.desc}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ===== 薄弱预警 ===== */}
      {!loading && (
        weakness ? (
          <div className="weak-card">
            <div className="weak-head">
              <div className="weak-ico"><Warning size={18} /></div>
              <h3 className="panel-title">薄弱科目预警</h3>
              <span className="panel-badge amber">{weakness.total_errors} 道活跃错题</span>
            </div>
            <div className="weak-body">
              <p className="weak-desc">{weakness.suggestion || (weakness.weak_subjects || []).map((s) => `${s.subject}(${s.count}道)`).join('、')}</p>
              <button className="btn outline" onClick={() => navigate('/notebook')}>查看薄弱知识点</button>
            </div>
          </div>
        ) : (
          <div className="weak-card good">
            <div className="weak-head">
              <div className="weak-ico"><CheckCircle size={18} /></div>
              <h3 className="panel-title">学习状态良好</h3>
            </div>
            <p className="weak-desc">目前没有明显薄弱科目，继续保持！</p>
          </div>
        )
      )}

      {/* ===== 全部模块入口（首页直达矩阵） ===== */}
      {!loading && (
        <div className="panel">
          <div className="panel-head">
            <h3 className="panel-title">全部模块</h3>
            <span className="panel-sub">一键直达任意功能</span>
          </div>
          <div className="mod-grid">
            {MODULES.map((m) => (
              <button key={m.to} className="mod-cell" onClick={() => navigate(m.to)}>
                <m.icon size={22} />
                <span>{m.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
