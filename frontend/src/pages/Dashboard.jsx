import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import useStore from '../store/useStore'
import { todayStr, weekdayIdx, WEEK_CN } from '../utils/date'
import { examDaysLeft, examYear, examDateMD, resolveExamDate } from '../utils/exam'
import { reviewStatus } from '../utils/ebbinghaus'
import { dueCards } from '../utils/spaced'
import { migrateKey, ukey } from '../utils/userKeys'
import { CountUp, Empty, toast, toastOk, toastErr } from '../components/UI'
import { LoadingState } from '../components/States'
import { dashboardApi, insightApi, request, tasksApi } from '../api/client'
import { kaoyanApi } from '../api/kaoyanApi'
import { MiniLineChart, RingProgress } from '../components/Charts'
import FocusTimer from '../components/FocusTimer'
import NoticeBoard from '../components/NoticeBoard'
import {
  useUiLayout, applyOrder, toggleHidden, DASH_SECTIONS,
} from '../hooks/useUiLayout'
import {
  Target, Clock, Book, Calendar, Warning, ChevronRight, ChevronDown, CheckCircle,
  Folder, GraduationCap, Brain, MessageSquare, Settings, FileText, Cloud, Activity,
  Map as MapIcon, RefreshCw, Flame, Trophy, Zap, Check,
} from '../components/Icon'
import './Dashboard.css'

/* 今日建议卡片的图标映射。
   后端 insightApi.today() 返回语义化 icon key（不返回 emoji —— emoji 在
   不同系统字体下渲染差异大，且与产品图标体系风格冲突）。
   这里把 key 映射为项目统一的 SVG 图标组件。 */
const SUGGESTION_ICON = {
  review: <Book size={15} />,
  todo: <Target size={15} />,
  target: <Activity size={15} />,
  brain: <Brain size={15} />,
}

/* 首页模块跳转矩阵（仿大平台首页，一键直达任意功能） */
export const MODULES = [
  { id: '/tasks', to: '/tasks', label: '任务打卡', icon: Target },
  { id: '/knowledge', to: '/knowledge', label: '知识地图', icon: MapIcon },
  { id: '/quiz', to: '/quiz', label: '刷题中心', icon: Book },
  { id: '/codebank', to: '/codebank', label: '复试代码题库', icon: Book },
  { id: '/notebook', to: '/notebook', label: '错题本', icon: FileText },
  { id: '/words', to: '/words', label: '单词记忆', icon: GraduationCap },
  { id: '/cards', to: '/cards', label: '记忆卡片', icon: Brain },
  { id: '/documents', to: '/documents', label: '文档知识库', icon: Folder },
  { id: '/pan', to: '/pan', label: '网盘联动', icon: Cloud },
  { id: '/planner', to: '/planner', label: '学习计划', icon: Calendar },
  { id: '/assistant', to: '/assistant', label: 'AI 助手', icon: MessageSquare },
  { id: '/settings', to: '/settings', label: '设置', icon: Settings },
]

/* 今日任务清单（D-03）模块 → 跳转路由。
   后端只给 module key，路由归前端所有（数据契约里不该出现界面路径）。
   key 与 services/dashboard_service._DUE_ROLLUP 一一对应。
   realexam 故意不在表里：整卷模考页还没建（#15），没有目的地的格子不该画成可点。 */
const MODULE_ROUTE = {
  word: '/words',
  card: '/cards',
  wrongbook: '/notebook',
  task: '/tasks',
  question: '/quiz',
}

/* 目标分数字段 → 中文标签（Goal 的列名是固定的科目口径，不是数据） */
const SCORE_TARGET_LABEL = {
  total: '总分', politics: '政治', english: '英语', math: '数学', major: '专业课',
}

/* 倒计时阶段文案。阶段边界（≤90 强化 / ≤30 预警 / ≤7 冲刺）由后端
   services/exam_calendar.phase_of 单点判定，前端只负责贴标签——
   阈值绝不在这里重复写一遍，否则又变成第二个口径。 */
const PHASE_LABEL = {
  base: '基础期',
  intensify: '强化期',
  warning: '30 天预警',
  sprint: '最后冲刺',
  passed: '初试已结束',
}

/* 后端字段 → 数组。接口的数组字段一旦返回 null/对象（残缺响应），
   直接 .map 就是整页白屏；这里统一收口，页面只渲染空态而不是崩。 */
const toArr = (v) => (Array.isArray(v) ? v : [])

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

/* 时段问候：与 Apple「早上好」一致的四段口径 */
function greetingText() {
  const h = new Date().getHours()
  if (h < 5) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 13) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

/* 连续打卡天数：**不在前端算**。口径唯一来自后端 services/study_calendar.py
   的 day_ledger + streak_summary（日界=北京自然日，当日「专注≥10 分钟 或
   复习≥10 词 或 答题≥5 道」才算打卡日）。此前这里另有一套「daily_trend.duration
   >0 即打卡」的本地算法，是全站第 4 个 streak 答案，已随 #13 删除。 */

/* ---------- 统计时间范围（今日 / 近7天 / 近30天 / 全部） ----------
   数据口径：summary.heatmap.days 是后端逐日台账（近 53 周连续日），
   四档范围都在这一份数据上求和，不再受"后端只留 7 天"限制；范围之外
   如实没有数据，界面用 data_coverage 说明覆盖了多少天。 */
/* B4：两键是裸字符串（'today' / '1'），按登录账号隔离 —— 值不解析，
   用 migrateKey 做旧全局键的一次性迁移，真实键 `base:{uid}`。 */
const DASH_RANGE_KEY = 'dash_range_v1'
const DASH_AUTOREFRESH_KEY = 'dash_autorefresh_v1'
const DASH_RANGES = [
  { id: 'today', label: '今日', days: 1 },
  { id: '7d', label: '近7天', days: 7 },
  { id: '30d', label: '近30天', days: 30 },
  { id: 'all', label: '全部', days: 0 },
]
function dashRangeDays(id) {
  return (DASH_RANGES.find((r) => r.id === id) || DASH_RANGES[0]).days
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
  /* 复习队列：唯一口径来自后端 review_scheduler，随 summary 一起下发
     （不在前端自行算 due）。 */
  const queue = live?.review_queue || null
  const layout = useUiLayout()
  const hidden = (id) => layout.dashHidden.includes(id)

  /* ---------- 统计时间范围 / 自动刷新 / 编辑布局 ---------- */
  const [range, setRange] = useState(() => {
    try { migrateKey(DASH_RANGE_KEY); return localStorage.getItem(ukey(DASH_RANGE_KEY)) || 'today' } catch { return 'today' }
  })
  const rangeDays = dashRangeDays(range)
  const pickRange = (id) => {
    setRange(id)
    try { localStorage.setItem(ukey(DASH_RANGE_KEY), id) } catch { /* 隐私模式 */ }
  }
  const [autoRefresh, setAutoRefresh] = useState(() => {
    try { migrateKey(DASH_AUTOREFRESH_KEY); return localStorage.getItem(ukey(DASH_AUTOREFRESH_KEY)) === '1' } catch { return false }
  })
  const toggleAutoRefresh = () => {
    setAutoRefresh((v) => {
      const next = !v
      try { localStorage.setItem(ukey(DASH_AUTOREFRESH_KEY), next ? '1' : '0') } catch { /* 隐私模式 */ }
      return next
    })
  }
  const [editCards, setEditCards] = useState(false)

  /* 首屏唯一请求：GET /api/dashboard/summary（D-01…D-11）。
     旧版要同时打 /dashboard 与 /dashboard/review-queue 两个接口，同一份数据
     两套口径；review_queue 现在由 summary 内嵌，不再单独发请求。 */
  /* 失败自动重试（1/2/4/8/16s，最多 5 次）：
     冷启动时 summary 聚合慢/后端尚未就绪，旧实现会一直停在“后端不可达”，
     用户必须手动刷新。重试与“30s 自动刷新”解耦，恢复后自动隐藏降级提示。 */
  const retryRef = useRef({ timer: null, attempt: 0 })
  const loadAll = useCallback(() => {
    if (retryRef.current.timer) {
      clearTimeout(retryRef.current.timer)
      retryRef.current.timer = null
    }
    return dashboardApi.summary()
      .then((d) => {
        setLive(d)
        setStatus('ok')
        retryRef.current.attempt = 0
        return true
      })
      .catch(() => {
        setStatus('error')
        const state = retryRef.current
        if (state.attempt >= 5) return false
        const delay = 1000 * (2 ** state.attempt)
        if (state.attempt === 0) toastErr('实时数据加载失败，正在自动重试…')
        state.attempt += 1
        state.timer = setTimeout(() => { state.timer = null; loadAll() }, delay)
        return false
      })
  }, [])

  /* 手动刷新：只有点按钮才弹成败提示，30s 自动刷新保持安静 */
  const refreshAll = async () => {
    const ok = await loadAll()
    if (ok) toastOk('驾驶舱已刷新')
    else toastErr('刷新失败，正在自动重试…')
  }

  useEffect(() => {
    loadAll()
    /* 30s 自动刷新（用户开关，localStorage 记忆偏好）：复用同一套加载逻辑 */
    let timer = null
    if (autoRefresh) timer = setInterval(loadAll, 30000)
    return () => {
      if (timer) clearInterval(timer)
      if (retryRef.current.timer) clearTimeout(retryRef.current.timer)
    }
  }, [loadAll, autoRefresh])

  /* ---------- 今日待办勾选即上报（§2.3.1「每项带复选框，勾选即划掉并实时上报」）
     后端可达时写真库并重新拉 summary —— 清单、进度环、日活台账因此同一份数据；
     只有后端不可达才落本地 store，且明确告知用户"没上报"，不假装同步成功。 */
  const toggleTaskLocal = useStore((s) => s.toggleTask)
  const [taskBusy, setTaskBusy] = useState(null)
  const onToggleTask = async (t) => {
    const idNum = Number(t.id)
    if (status !== 'ok' || !Number.isInteger(idNum)) {
      toggleTaskLocal(t.id)
      return
    }
    setTaskBusy(t.id)
    try {
      if (t.status === 'done') await tasksApi.uncomplete(idNum)
      else await tasksApi.complete(idNum)
      loadAll()
    } catch {
      toggleTaskLocal(t.id)
      toast('后端同步失败，已记在本地')
    } finally {
      setTaskBusy(null)
    }
  }

  /* ---------- 倒计时 ----------
     后端 summary.countdown 是**唯一权威**：days_left 与 phase（基础/强化/预警/冲刺）
     由 services/exam_calendar.py 的 phase_of 单点判定，届（入学年）由 exam_year 给出。
     本地 utils/exam.js 只在后端不可达时兜底，避免两套数字并存。
     
     【修复】优先使用 settings.examDate（用户最新选择），其次才是后端缓存值。
     这样用户在设置页切换届数后，仪表盘立即反映新日期，无需等待后端同步。 */
  const cd = live && live.countdown
  // 优先用本地设置（实时更新），后端仅作为初始值和离线兜底
  const effectiveExamDate = settings.examDate || (cd && cd.exam_date)
  const examDate = resolveExamDate(effectiveExamDate, null)
  const days = examDaysLeft(examDate) ?? cd?.days_left ?? null
  /* 届（入学年）以后端 exam_year 为准：2026 年 12 月初试 = 2027 届，
     直接截日期年份会少一届。后端缺字段时才退回日期年份。 */
  const examY = cd?.exam_year || examYear(examDate)
  const phase = cd?.phase || null
  const phaseLabel = PHASE_LABEL[phase] || null
  // 后端无 Goal 时给的是兜底估算日期，必须标「预估」，不能伪装成官方日期；
  // 具体 M/D 由 examDateMD(examDate) 现算，不再写死 12/21（#105a/②）
  const estimated = !!cd?.is_default
  const schoolLabel = [cd?.university || settings.school, cd?.major || settings.major]
    .filter(Boolean).join(' ') || null
  const targetScore = cd?.total_score_target ?? settings.targetScore ?? null

  /* ---------- 今日任务（后端优先，本地兜底） ----------
     注意 live 可能为 null：后端返回 2xx 但无 JSON 体时 client 会 resolve(null)，
     此时 status 仍是 'ok'，故这里必须用 live?. 防御，否则整页白屏。 */
  let todayTasks = []
  if (status === 'ok' && live?.today_tasks) {
    todayTasks = toArr(live.today_tasks.tasks).map((t) => ({
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

  /* ---------- 复习队列（后端 review_scheduler 唯一口径） ----------
     报告 25 §D/§三：前端 localStorage 调度与后端 review_scheduler 两套口径。
     现改为后端 /dashboard/review-queue 派生结果；后端不可达时才回退本地估算，
     并把 queueSource 标为 local，便于界面提示口径来源。 */
  const queueSource = queue ? (queue.source || 'review_scheduler') : 'local'
  const dueReviews = queue ? (queue.errors || []).length
    : notebook.map((n) => reviewStatus(n)).filter((rs) => rs.status === 'due').length
  const dueCardCount = queue ? (queue.cards || []).length : dueCards(cards).length
  const dueWordCount = dueCards(words).length
  const reviews = notebook
    .map((n) => ({ n, rs: reviewStatus(n) }))
    .filter((x) => x.rs.status !== 'new')

  /* ---------- 统计（口径全部来自后端 summary，前端不二次计算） ----------
     live 现在是 GET /api/dashboard/summary：一次请求给出 kpi / trend / heatmap /
     errors / streak。这里把 summary 映射成 stats 这层旧字段名，只为沿用下面的
     渲染代码；不再发第二次请求，也不再依赖已移除的番茄钟本地数据。 */
  const kpi = live?.kpi
  const stats = useMemo(() => (live ? {
    today_duration: kpi?.today?.focus_minutes || 0,
    week_duration: live?.trend?.week_focus_minutes || 0,
    daily_trend: toArr(live?.trend?.series).map((d) => ({ date: d.date, duration: d.focus_minutes || 0 })),
    active_errors: live?.errors?.active || 0,
    weekly_completed_tasks: live?.trend?.weekly_completed_tasks || 0,
  } : null), [live, kpi])
  const weekMinutes = stats ? stats.week_duration : 0
  const activeErrors = stats ? stats.active_errors : notebook.length

  /* 逐日台账：summary.heatmap.days 是后端「周一起算、逐日连续、截至今日」的近 53 周
     序列（无数据的日子如实为 0，不伪造）。今日 / 近7 / 近30 / 全部四档都在这一份
     真实数据上聚合，旧版「后端只有近 7 天、30 天档只能补零」的口径缺口已消失。 */
  const allDays = useMemo(
    () => toArr(live?.heatmap?.days).map((d) => ({
      date: d.date,
      duration: d.focus_minutes || 0,
      questions: d.questions_done || 0,
      effective: !!d.is_effective,
    })),
    [live],
  )

  /* 范围起点（今日=当天；近7/30天=起点日期；全部=null 不限） */
  const rangeCutoff = useMemo(() => {
    if (!rangeDays) return null
    const d = new Date()
    d.setDate(d.getDate() - (rangeDays - 1))
    return todayStr(d)
  }, [rangeDays])

  /* 范围内的逐日序列。今日档画的是近 14 天曲线（后端 trend.series 同窗口），
     便于把今天放进趋势里看，而不是孤立一个点。 */
  const rangeSeries = useMemo(() => {
    if (rangeDays === 1) {
      const s = toArr(live?.trend?.series).map((d) => ({
        date: d.date, duration: d.focus_minutes || 0,
        questions: d.questions_done || 0, effective: !!d.is_effective,
      }))
      return s.length ? s : allDays.slice(-1)
    }
    if (!rangeCutoff) return allDays
    return allDays.filter((d) => d.date >= rangeCutoff)
  }, [rangeDays, rangeCutoff, allDays, live])

  /* 范围内学习分钟数：今日档直接取后端今日值，其余按范围内逐日求和 */
  const rangeMinutes = useMemo(() => {
    if (rangeDays === 1) return stats ? stats.today_duration : 0
    return rangeSeries.reduce((a, d) => a + (d.duration || 0), 0)
  }, [stats, rangeSeries, rangeDays])

  /* 范围内任务（今日=今日任务；其余按任务 due 落在范围内过滤；全部=全部任务） */
  const rangeTasks = useMemo(() => {
    if (rangeDays === 1) return todayTasks
    const today = todayStr()
    if (!rangeCutoff) {
      return tasks.map((t) => ({ id: String(t.id), title: t.title, subject: t.subject, status: t.done ? 'done' : 'pending' }))
    }
    return tasks
      .filter((t) => t.due && t.due >= rangeCutoff && t.due <= today)
      .map((t) => ({ id: String(t.id), title: t.title, subject: t.subject, status: t.done ? 'done' : 'pending' }))
  }, [rangeDays, rangeCutoff, todayTasks, tasks])
  const rangeTasksDone = rangeTasks.filter((t) => t.status === 'done').length

  /* 连续打卡：后端 kpi.streak 是唯一口径（当日专注≥10 分钟 或 复习≥10 词 或 答题≥5 道）。
     current=当前连续，longest=历史最长，total_days=累计打卡天数。 */
  const streakInfo = (kpi && kpi.streak) || {}
  const streak = typeof streakInfo.current === 'number' ? streakInfo.current : 0

  /* ---------- 趋势数据（单位：分钟，随统计范围取 rangeSeries） ---------- */
  const trend = rangeSeries.map((d) => ({
    label: WEEK_CN[weekdayIdx(d.date)].slice(1),
    value: Math.round(d.duration || 0),
  }))

  const weakness = live && live.weakness && live.weakness.has_weakness ? live.weakness : null
  /* D-10 薄弱知识点 Top3：后端 error_linker.weak_knowledge_points 已按
     「错题数×2 + 考频 − 掌握度/20」排好并截断到 3 条，这里既不再 slice，
     也不自己排序 —— 排序口径必须只有一个，否则仪表盘和错题页给两个「最薄弱考点」。 */
  const weakPoints = useMemo(() => toArr(weakness?.weak_points), [weakness])
  const loading = status === 'loading'
  const topReviews = reviews.slice(0, 4)

  /* ---------- 学习热力图（后端 53 周连续日按周切列） ----------
     深浅阈值只认后端下发的 heatmap.levels（绝对分钟数），前端不再抄一份
     [0,30,90,180] 当兜底——抄了就是第二个口径来源，后端改阈值时这里会静默错位。
     也就不用「除以本周最大值」的相对刻度（那会让只学了几天的新用户满屏深蓝）。
     levels 缺失时降级成「有活动即一级」，宁可朴素也不伪造阈值。 */
  const heatLevels = toArr(live?.heatmap?.levels)
  const heatmapData = useMemo(() => {
    const weeks = []
    for (let i = 0; i < allDays.length; i += 7) weeks.push(allDays.slice(i, i + 7))
    return weeks
  }, [allDays])
  const totalHeatmap = useMemo(() => allDays.reduce((a, d) => a + (d.duration || 0), 0), [allDays])
  const heatLevel = (day) => {
    const v = day.duration || 0
    if (v <= 0) return 0
    if (!heatLevels.length) return 1
    let lvl = 0
    for (const th of heatLevels) { if (v >= th) lvl += 1 }
    return Math.min(5, lvl)
  }

  /* ---------- 目标卡 / 模块进度环 / 未来负荷（全部读 summary，不再发请求） ---------- */
  const goalBlock = live?.goal || null
  // D-02 近年复试线：后端查不到就是空数组，前端绝不补一条 0 线
  const scoreLines = useMemo(
    () => toArr(goalBlock?.recent_score_lines).filter((l) => l?.year != null && l?.total_line != null),
    [goalBlock],
  )
  const targetsSet = !!goalBlock?.targets_set
  // 专注计时的科目候选 = 用户自己配的备考科目（+ 支撑科目），去重后原样传给面板。
  // 不在这里写死「数学/英语/政治」：科目名会被写进 study_sessions.subject 并进分科目时长。
  const focusSubjects = useMemo(
    () => Array.from(new Set([...toArr(goalBlock?.subjects), ...toArr(goalBlock?.support_subjects)])),
    [goalBlock],
  )
  const moduleProgress = useMemo(() => toArr(live?.module_progress), [live])
  // 今日任务清单（D-03）：按模块的「到期 / 已做」，口径来自后端 due_today
  const taskModules = useMemo(() => toArr(live?.today_tasks?.modules), [live])
  const futureLoad = live?.future_load || null
  const futureRows = useMemo(() => {
    const src = [
      { key: 'due_today', label: '今日到期' },
      { key: 'due_tomorrow', label: '到明日' },
      { key: 'due_this_week', label: '到本周日' },
    ]
    return src
      .map((s) => {
        const e = futureLoad?.[s.key]
        return e ? { ...s, ...e } : null
      })
      .filter(Boolean)
  }, [futureLoad])
  const futureMax = futureRows.reduce((a, r) => Math.max(a, r.total || 0), 0)

  /* ---------- 智能每日推荐 ---------- */
  const smartRecommendations = useMemo(() => {
    const recs = []
    // 1. 待复习错题
    if (dueReviews > 0) {
      recs.push({
        type: 'review', icon: '记录',
        title: `复习 ${dueReviews} 道错题`,
        desc: '按艾宾浩斯曲线，这些错题今天需要复习巩固',
        action: '/notebook', priority: 1,
      })
    }
    // 2. 待复习单词
    if (dueWordCount > 0) {
      recs.push({
        type: 'words', icon: '资料',
        title: `背诵 ${dueWordCount} 个单词`,
        desc: '今日待复习单词，四档评分高效记忆',
        action: '/words', priority: 2,
      })
    }
    // 3. 待完成任务
    const pendingTasks = todayTasks.filter((t) => t.status !== 'done')
    if (pendingTasks.length > 0) {
      recs.push({
        type: 'tasks', icon: '已完成',
        title: `完成 ${pendingTasks.length} 个今日任务`,
        desc: pendingTasks[0]?.title || '今日待办任务',
        action: '/tasks', priority: 3,
      })
    }
    // 4. 薄弱科目
    if (weakness && weakness.weak_subjects?.length > 0) {
      recs.push({
        type: 'weakness', icon: '注意',
        title: `攻克 ${weakness.weak_subjects[0].subject} 薄弱点`,
        desc: `${weakness.weak_subjects[0].count} 道活跃错题，建议专项突破`,
        action: '/notebook', priority: 4,
      })
    }
    // 5. 兜底推荐：去刷题
    if (recs.length === 0) {
      recs.push({
        type: 'focus', icon: '目标',
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
        time: '今日', icon: '已完成', title: t.title, desc: '任务已完成', type: 'task',
      })
    })
    // 今日待复习
    if (dueReviews > 0) {
      events.push({
        time: '待完成', icon: '记录',
        title: `${dueReviews} 道错题待复习`,
        desc: '按艾宾浩斯曲线复习',
        type: 'review',
      })
    }
    return events.slice(0, 6)
  }, [stats, todayTasks, dueReviews])

  /* ---------- 可自定义部分（显隐/排序偏好见 hooks/useUiLayout.js） ----------
     统计卡随时间范围切换重算：
       · 学习时长 → 今日=后端 kpi.today.focus_minutes；其余按 rangeSeries 求和
       · 任务    → 今日=今日任务；近7/30天=store 内 due 落在范围的任务；全部=全部任务
       · 待复习/打卡与时间范围无关，保持不变
     角标 delta 一律来自后端 kpi.delta（今日−昨日），前端不再自己作差。 */
  const rangeLabel = DASH_RANGES.find((r) => r.id === range)?.label || '今日'
  const minutesTrendText = rangeDays === 1 ? '今日' : (rangeDays === 7 ? '本周' : rangeLabel)
  const coverageNote = live?.data_coverage?.days_with_activity
    ? `已有 ${live.data_coverage.days_with_activity} 天学习记录`
    : null
  const fmtDelta = (n, unit) => {
    if (n == null) return ''
    if (n === 0) return '与昨日持平'
    return `${n > 0 ? '+' : '−'}${Math.abs(n)}${unit || ''} 环比昨日`
  }
  const statCards = useMemo(() => {
    const all = [
      {
        id: 'minutes', ico: Clock, tone: 'blue',
        trend: (kpi?.delta?.focus_minutes ?? 0) >= 0 ? 'up' : 'down',
        trendText: minutesTrendText,
        value: (rangeMinutes / 60).toFixed(1), unit: 'h', label: '学习时长', to: '/kbmap',
        sub: rangeDays === 1 ? fmtDelta(kpi?.delta?.focus_minutes, ' 分钟') : coverageNote,
      },
      {
        id: 'tasks', ico: Target, tone: 'green', trend: 'flat', trendText: rangeLabel,
        value: rangeTasks.length, unit: '', label: `${rangeLabel}任务 · 已完成 ${rangeTasksDone}`, to: '/tasks',
        sub: rangeDays === 1 ? fmtDelta(kpi?.delta?.tasks_done, ' 个') : null,
      },
      {
        id: 'review', ico: Book, tone: 'amber', trend: 'flat', trendText: '待处理',
        value: dueReviews + dueWordCount + dueCardCount, unit: '', label: '待复习（错/词/卡）', to: '/notebook',
        // 这个数字是三种口径相加：错题/卡片优先取后端 review_queue，单词恒为本机估算。
        // 后端队列不可达时整条都是本机估算，必须在副标题说清楚，不能看着和权威值一样。
        sub: queueSource === 'local' ? '后端队列不可达 · 本机估算' : fmtDelta(kpi?.delta?.errors_done, ' 道'),
      },
      {
        id: 'questions', ico: Zap, tone: 'cyan', trend: 'flat', trendText: '今日',
        value: kpi?.today?.questions_done ?? 0, unit: ' 道', label: '答题量', to: '/quiz',
        sub: fmtDelta(kpi?.delta?.questions_done, ' 道'),
      },
      {
        id: 'accuracy', ico: Activity, tone: 'violet', trend: 'flat',
        trendText: kpi?.today?.correct_rate == null ? '暂无答题' : '今日',
        // 后端 correct_rate 已经是百分数（study_calendar.DayActivity.correct_rate =
        // round(100*correct/done, 1)），这里不能再 *100，否则 82.5% 会渲染成 8250%。
        // 无答题时是 null（不是 0），如实显示占位而不是伪造 0% 正确率。
        value: kpi?.today?.correct_rate == null ? '—' : Math.round(kpi.today.correct_rate),
        unit: kpi?.today?.correct_rate == null ? '' : '%', label: '正确率', to: '/notebook',
        sub: kpi?.delta?.correct_rate_pp == null ? null : `环比 ${kpi.delta.correct_rate_pp >= 0 ? '+' : '−'}${Math.abs(kpi.delta.correct_rate_pp)}pp`,
      },
      {
        id: 'streak', ico: Flame, tone: 'violet', trend: 'up',
        trendText: streakInfo.checked_today ? '今日已打卡' : '今日未打卡',
        value: streak, unit: '天', label: '连续打卡', to: '/planner',
        sub: `最长 ${streakInfo.longest ?? streak} 天 · 累计 ${streakInfo.total_days ?? 0} 天`,
      },
    ]
    return applyOrder(all.filter((c) => !layout.statsHidden.includes(c.id)), layout.statsOrder)
  }, [rangeMinutes, minutesTrendText, rangeTasks, rangeTasksDone, rangeLabel, dueReviews, dueWordCount, dueCardCount, streak,
    kpi, streakInfo, coverageNote, queueSource,
    layout.statsHidden, layout.statsOrder])

  const moduleCells = useMemo(
    () => applyOrder(MODULES.filter((m) => !layout.modsHidden.includes(m.id)), layout.modsOrder),
    [layout.modsHidden, layout.modsOrder],
  )

  /* ---------- V11 今日学习引导 / V16 当日院校公告 / 学习周报 ---------- */
  const [today, setToday] = useState(null)
  const [dayNotices, setDayNotices] = useState([])
  const [report, setReport] = useState(null)
  const [reportError, setReportError] = useState(null)
  const [showReport, setShowReport] = useState(false)

  /* ---------- docx/22 G2：学习工作台（任务打卡 / 学习计划 / 学习画像 聚合） ----------
     任务打卡数据取自 store / live；学习计划、学习画像摘要按需向后端拉取。
     后端不可用或接口缺字段时保持 null，卡片显示占位文案，绝不白屏。
     这里用底层 request 而不是 plannerApi / analysisApi 具名导入：
     只依赖 client 的 request（各测试 mock 都提供），避免新增导出触发 mock 缺口。 */
  const [workbench, setWorkbench] = useState({ plan: null, profile: null })
  const [openWb, setOpenWb] = useState(null) // tasks | planner | profile | null
  const toggleWb = (k) => setOpenWb((cur) => (cur === k ? null : k))

  useEffect(() => {
    let alive = true
    ;(async () => {
      const plan = { earlyStreak: null, ebbing: null, phase: null }
      try {
        const eb = await request('/planner/earlybird')
        const sv = eb && eb.current_streak
        plan.earlyStreak = typeof sv === 'number'
          ? sv
          : (Array.isArray(eb && eb.records) ? eb.records.length : null)
      } catch { /* 后端未启动：计划摘要留空 */ }
      try {
        const r = await request('/planner/ebbinghaus')
        plan.ebbing = (Array.isArray(r) ? r : (r && r.items) || []).length
      } catch { /* 忽略 */ }
      try {
        const r = await request('/planner/phase')
        plan.phase = (Array.isArray(r) ? r : (r && r.plans) || []).length
      } catch { /* 忽略 */ }
      let profile = null
      try { profile = await request('/analysis/profile', { params: { days: 30 } }) } catch { /* 忽略 */ }
      if (alive) setWorkbench({ plan, profile: profile || null })
    })()
    return () => { alive = false }
  }, [])

  useEffect(() => {
    let alive = true
    insightApi.today().then((d) => { if (alive) setToday(d) }).catch(() => {})
    kaoyanApi.noticesFeed({ page: 1, page_size: 8 })
      .then((r) => { if (alive) setDayNotices(r.items || []) })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  const openReport = () => {
    setShowReport(true)
    setReportError(null)
    if (!report) {
      // 失败不再「默默关掉面板」：用户点了却什么都没发生，是最难复现的一类 bug。
      insightApi.weeklyReport().then(setReport).catch((e) => setReportError(e?.message || '周报加载失败'))
    }
  }

  /* 学习画像摘要（工作台卡片用；后端缺字段时全部退化为占位）。
     薄弱考点只有一处口径：summary.weakness.weak_points 与画像的 weak_points 都出自
     error_linker.weak_points_view，所以这里直接用上面的 weakPoints，不再从 profile 取一份。 */
  const pv = workbench.profile?.overview
  const pSubjects = workbench.profile?.subjects || []

  return (
    <div className="dash">

      {/* ===== 页面头部：问候 + 日期 + 统计范围 / 刷新 / 布局 ===== */}
      <header className="dash-page-head">
        <div>
          <h1 className="dash-greeting">{greetingText()}，同学</h1>
          <p className="dash-greeting-sub">
            {LiveClock()} · {schoolLabel ? `目标 ${schoolLabel}` : '尚未设置目标院校专业'}
          </p>
        </div>
        <div className="dash-head-actions">
          <div className="seg" role="tablist" aria-label="统计时间范围">
            {DASH_RANGES.map((r) => (
              <button key={r.id} role="tab" aria-selected={range === r.id}
                className={`seg-btn ${range === r.id ? 'active' : ''}`}
                onClick={() => pickRange(r.id)}>
                {r.label}
              </button>
            ))}
          </div>
          <button className={`btn sm dash-hide-sm ${autoRefresh ? 'primary' : 'ghost'}`} onClick={toggleAutoRefresh}
            title="每 30 秒自动刷新驾驶舱数据（偏好保存在本机）">
            {autoRefresh ? '自动刷新中' : '自动刷新'}
          </button>
          <button className="btn sm ghost" onClick={refreshAll} title="立即刷新驾驶舱数据">
            <RefreshCw size={14} /> 刷新
          </button>
          <button className={`btn sm dash-hide-sm ${editCards ? 'primary' : 'ghost'}`} onClick={() => setEditCards((v) => !v)}
            title="编辑布局：隐藏 / 显示各模块卡片">
            <Settings size={14} /> 布局
          </button>
        </div>
      </header>

      {/* ===== Hero：倒计时 + 目标 + 连续打卡（首屏第一焦点） ===== */}
      {!hidden('hero') && (
      <section className="dash-hero" aria-label="考研倒计时">
        <div className="dash-hero-inner">
          <div>
            <div className="dash-hero-greet">
              <Calendar size={14} /> 考研倒计时
            </div>
            <h2 className="dash-hero-title">
              {!examDate ? (
                <>距考研还有<span className="dash-hero-days">—</span>天
                  <Link className="dash-hero-set" to="/settings">设置初试日期</Link>
                </>
              ) : (days != null && days < 0) ? (
                <>{examY} 考研初试<span className="dash-hero-days">已结束</span>
                  <Link className="dash-hero-set" to="/settings">配置新目标</Link>
                </>
              ) : (
                <>距 {examY} 考研初试还有<span className="dash-hero-days"><CountUp value={days > 0 ? days : 0} /></span>天
                  {phaseLabel && <span className={`dash-hero-phase ph-${phase}`}>{phaseLabel}</span>}
                  {estimated && examDate && (
                    <span className="dash-hero-est">{examDateMD(examDate)} 预估</span>
                  )}
                </>
              )}
            </h2>
            <div className="dash-hero-goal">
              {(targetScore || targetScore === 0) && (
                <span><Target size={14} /> 目标分数 {targetScore}</span>
              )}
              <span><Clock size={14} /> 今日 {todayTasks.length} 个任务</span>
              <span><Book size={14} /> 本周学习 {weekMinutes} 分钟</span>
              {cd?.signup_hint && <span><Calendar size={14} /> {cd.signup_hint}</span>}
            </div>
            {/* 日期口径如实标注（D-02） */}
            {cd && cd.is_official === false && cd.source && (
              <div className="dash-hero-warn">
                <Warning size={13} /> 初试日期：{cd.source}
                <Link to="/settings">去核对</Link>
              </div>
            )}
          </div>
          <div className="dash-hero-cta">
            <button className="btn primary" onClick={() => navigate('/notebook')}>
              <FileText size={17} /> 拍一道错题
            </button>
            <div className="hero-stats">
              <span className="hero-stat" title={streakInfo.rule || '打卡口径由后端给出'}>
                <Flame size={13} /> 连续打卡 <b>{streak}</b> 天
              </span>
              <span className="hero-stat" title="历史最长连续 / 累计打卡天数（同一口径）">
                <Trophy size={13} /> 最长 <b>{streakInfo.longest ?? streak}</b> · 累计 <b>{streakInfo.total_days ?? 0}</b>
              </span>
              <span className="hero-stat">活跃错题 <b>{activeErrors}</b></span>
            </div>
          </div>
        </div>
      </section>
      )}

      {/* ===== 今日 KPI + 环比（D-02）=====
           数字全部来自 summary.kpi（后端 day_ledger 同一天行），
           delta 是「今日 − 昨日」的整数差；correct_rate_pp 在任一天无答题
           时为 null（不是 0），界面如实显示「—」而不是伪造 0% 正确率。
           pct 标记只表示「值已是 0-100 的百分数、后缀加 %」，不做任何换算。 */}
      {!loading && !hidden('kpi') && live?.kpi && (
        <section className="kpi-strip" aria-label="今日 KPI 与环比">
          {[
            { key: 'focus_minutes', label: '专注（分钟）', value: kpi?.today?.focus_minutes, delta: kpi?.delta?.focus_minutes, unit: '' },
            { key: 'questions_done', label: '答题', value: kpi?.today?.questions_done, delta: kpi?.delta?.questions_done, unit: ' 道' },
            { key: 'correct_rate', label: '正确率', value: kpi?.today?.correct_rate, delta: null, unit: '', pct: true },
            { key: 'tasks_done', label: '完成任务', value: kpi?.today?.tasks_done, delta: kpi?.delta?.tasks_done, unit: ' 个' },
            { key: 'errors_done', label: '错题复习', value: kpi?.today?.errors_done, delta: kpi?.delta?.errors_done, unit: ' 道' },
            { key: 'words_done', label: '复习单词', value: kpi?.today?.words_done, delta: kpi?.delta?.words_done, unit: ' 个' },
          ].map((m) => (
            <div key={m.key} className={`kpi-cell ${m.value == null ? 'is-nil' : ''}`}>
              <span className="kpi-label">{m.label}</span>
              <span className="kpi-val">
                {m.pct
                  ? (m.value == null ? '—' : `${Math.round(m.value)}%`)
                  : (m.value == null ? '—' : `${m.value}${m.unit}`)}
              </span>
              {m.delta != null && m.delta !== 0 && (
                <span className={`kpi-delta ${m.delta > 0 ? 'up' : 'down'}`}>
                  {m.delta > 0 ? '↑' : '↓'}{Math.abs(m.delta)}
                  {m.pct ? '' : m.unit.trim() || '个'}
                </span>
              )}
              {m.delta == null && !m.pct && <span className="kpi-delta flat">与昨日持平</span>}
              {m.pct && kpi?.delta?.correct_rate_pp != null && (
                <span className={`kpi-delta ${kpi.delta.correct_rate_pp >= 0 ? 'up' : 'down'}`}>
                  {kpi.delta.correct_rate_pp >= 0 ? '↑' : '↓'}{Math.abs(kpi.delta.correct_rate_pp)}pp
                </span>
              )}
            </div>
          ))}
        </section>
      )}

      {/* 编辑布局面板：复用 ui_layout 的 dashHidden 显隐口径（默认全显） */}
      {editCards && (
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', alignItems: 'center',
          padding: 'var(--space-3) var(--space-4)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)', background: 'var(--surface-2)', marginBottom: 'var(--space-4)' }}>
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--fg-2)', width: '100%' }}>
            点卡片名切换显示 / 隐藏（保存在本机，默认全部显示）
          </span>
          {DASH_SECTIONS.map((s) => (
            <button key={s.id} className={`btn mini ${hidden(s.id) ? 'ghost' : 'primary'}`}
              onClick={() => toggleHidden('dashHidden', s.id)}>
              {hidden(s.id) ? '已隐藏 · ' : '显示 · '}{s.label}
            </button>
          ))}
        </div>
      )}

      {/* ===== 今日（合并原「今日复习队列」与「今日该干什么」）=====

          信息架构修正（2026-10）：
          原本这里是**两个区块、8 张卡片**，但语义高度重叠——
            · 「今日复习队列」显示 dueReviews / 单词 / 卡片 / 继续刷题
            · 「今日该干什么」显示 due_review_count / 任务 / 今日已答 / 薄弱 / 周报
          「错题到期数」和「到期复习数」是同一件事的两个数据源（一个本地 queue、
          一个后端 API），数字还可能不一致，用户无从判断该信哪个。

          现合并为单区块，数据统一取后端 insightApi.today()（权威口径），
          并补充 hint 说明"这个数字意味着什么"，避免用户猜。
          单词/记忆卡数量本地可算，作为补充项并入同一网格。 */}
      <section className="dash-today" aria-label="今日">
        <div className="dash-today-head">
          <strong>今日</strong>
          <span className="dash-today-sub">今天该做什么，一眼看清</span>
        </div>
        <div className="dash-today-grid">
          {(today?.suggestions || []).map((s) => (
            <button
              key={s.label}
              className={`dash-today-card ${s.count ? '' : 'is-idle'}`}
              onClick={() => navigate(s.to)}
            >
              <span className="ico">{SUGGESTION_ICON[s.icon] || <Book size={15} />}</span>
              <em>{s.count}</em>
              <span>{s.label}</span>
              {s.hint && <span className="hint" title={s.hint}>{s.hint}</span>}
            </button>
          ))}

          {/* 本地可算的两项：单词 / 记忆卡（后端 today 不含，避免重复请求）。
              数字口径必须写明白：后端 review_queue 不含单词队列，单词恒为本机估算；
              卡片在有后端队列时取调度结果、否则回落本机 —— 两类数字以前长得一样，
              用户无法分辨「待复习 12」到底是权威值还是猜测值。 */}
          <button
            className={`dash-today-card ${dueWordCount ? '' : 'is-idle'}`}
            onClick={() => navigate('/words')}
          >
            <span className="ico"><FileText size={15} /></span>
            <em>{dueWordCount}</em>
            <span>待背单词</span>
            <span className="hint" title="后端复习队列不含单词分项，按本机记忆曲线估算">本机估算 · 到期待复习</span>
          </button>
          <button
            className={`dash-today-card ${dueCardCount ? '' : 'is-idle'}`}
            onClick={() => navigate('/cards')}
          >
            <span className="ico"><Brain size={15} /></span>
            <em>{dueCardCount}</em>
            <span>待复习卡片</span>
            <span className="hint" title={queue ? '取自后端 review_scheduler 到期队列' : '后端复习队列不可达，按本机记忆曲线估算'}>
              {queue ? '按记忆曲线到期' : '本机估算 · 后端不可达'}
            </span>
          </button>

          {/* 周报入口：非"待办"性质，独立为操作项，不显示计数 */}
          <button className="dash-today-card" onClick={openReport}>
            <span className="ico"><Target size={15} /></span>
            <em>周报</em>
            <span>本周 vs 上周</span>
            <span className="hint">答题量 · 正确率 · 学习时长</span>
          </button>
        </div>
      </section>

      {/* ===== docx/22 G2：学习工作台（任务打卡 / 学习计划 / 学习画像 聚合到仪表盘） =====
          三个入口的核心摘要直接落在首页，点标题展开细节、点链接进对应页；
          「设置」不进下拉，保持单列（见 Layout.jsx）。 */}
      <section className="dash-workbench" aria-label="学习工作台">
        <div className="dash-today-head">
          <strong>学习工作台</strong>
          <span className="dash-today-sub">任务打卡 · 学习计划 · 学习画像 已并入仪表盘 · 点标题展开摘要</span>
        </div>
        <div className="wb-grid">
          {/* 任务打卡 */}
          <div className={`wb-card ${openWb === 'tasks' ? 'open' : ''}`}>
            <button className="wb-head" onClick={() => toggleWb('tasks')} aria-expanded={openWb === 'tasks'}>
              <span className="wb-ico"><Target size={16} /></span>
              <span className="wb-title">任务打卡</span>
              <span className="wb-summary">今日 {doneCount}/{todayTasks.length} · 连续 {streak} 天</span>
              <ChevronDown size={15} className={`wb-caret ${openWb === 'tasks' ? 'open' : ''}`} />
            </button>
            {openWb === 'tasks' && (
              <div className="wb-body">
                <div className="wb-metrics">
                  <div><em>{doneCount}</em><span>今日已完成</span></div>
                  <div><em>{Math.max(0, todayTasks.length - doneCount)}</em><span>今日待办</span></div>
                  <div><em>{streak}</em><span>连续打卡（天）</span></div>
                </div>
                {todayTasks.length > 0 ? (
                  <ul className="wb-list">
                    {todayTasks.slice(0, 4).map((t) => (
                      <li key={t.id}>
                        <span className={`task-dot ${t.status === 'done' ? 'done' : t.status === 'doing' ? 'doing' : ''}`} />
                        <span className="wb-li-text">{t.title}</span>
                        {t.subject && <span className="task-subject">{t.subject}</span>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="wb-empty">今日暂无任务，去任务打卡页安排今天。</p>
                )}
                <button className="link-btn" onClick={() => navigate('/tasks')}>
                  进入任务打卡 <ChevronRight size={13} />
                </button>
              </div>
            )}
          </div>

          {/* 学习计划 */}
          <div className={`wb-card ${openWb === 'planner' ? 'open' : ''}`}>
            <button className="wb-head" onClick={() => toggleWb('planner')} aria-expanded={openWb === 'planner'}>
              <span className="wb-ico"><Calendar size={16} /></span>
              <span className="wb-title">学习计划</span>
              <span className="wb-summary">
                {workbench.plan
                  ? `早起连续 ${workbench.plan.earlyStreak ?? 0} 天 · 艾宾浩斯 ${workbench.plan.ebbing ?? 0} 条`
                  : '正在读取计划…'}
              </span>
              <ChevronDown size={15} className={`wb-caret ${openWb === 'planner' ? 'open' : ''}`} />
            </button>
            {openWb === 'planner' && (
              <div className="wb-body">
                <div className="wb-metrics">
                  <div><em>{workbench.plan?.earlyStreak ?? '—'}</em><span>早起连续（天）</span></div>
                  <div><em>{workbench.plan?.ebbing ?? '—'}</em><span>艾宾浩斯在学</span></div>
                  <div><em>{workbench.plan?.phase ?? '—'}</em><span>阶段计划</span></div>
                </div>
                <p className="wb-empty">日 / 周 / 月计划、艾宾浩斯复习点、早起打卡与阶段复习都在「学习计划」页。</p>
                <button className="link-btn" onClick={() => navigate('/planner')}>
                  进入学习计划 <ChevronRight size={13} />
                </button>
              </div>
            )}
          </div>

          {/* 学习画像 */}
          <div className={`wb-card ${openWb === 'profile' ? 'open' : ''}`}>
            <button className="wb-head" onClick={() => toggleWb('profile')} aria-expanded={openWb === 'profile'}>
              <span className="wb-ico"><Activity size={16} /></span>
              <span className="wb-title">学习画像</span>
              <span className="wb-summary">
                {pv
                  ? `累计答题 ${pv.total_answers ?? 0} · 正确率 ${pv.overall_accuracy != null ? pv.overall_accuracy + '%' : '—'}`
                  : '正在读取画像…'}
              </span>
              <ChevronDown size={15} className={`wb-caret ${openWb === 'profile' ? 'open' : ''}`} />
            </button>
            {openWb === 'profile' && (
              <div className="wb-body">
                <div className="wb-metrics">
                  <div><em>{pv?.total_answers ?? '—'}</em><span>累计答题</span></div>
                  <div><em>{pv?.overall_accuracy != null ? pv.overall_accuracy + '%' : '—'}</em><span>总正确率</span></div>
                  <div><em>{pv?.error_stock ?? '—'}</em><span>错题存量</span></div>
                </div>
                {pSubjects.length > 0 && (
                  <ul className="wb-list">
                    {pSubjects.slice(0, 3).map((s) => (
                      <li key={s.subject}>
                        <span className="wb-tag">{s.mastery}</span>
                        <span className="wb-li-text">{s.subject}</span>
                        <span className="task-subject">正确率 {s.accuracy != null ? s.accuracy + '%' : '—'}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {weakPoints.length > 0 && (
                  <p className="wb-empty">薄弱考点：{weakPoints.map((p) => p.name).join('、')}</p>
                )}
                {!pv && weakPoints.length === 0 && (
                  <p className="wb-empty">画像数据来自答题 / 错题 / 模考记录，先去刷几题就会生成。</p>
                )}
                <button className="link-btn" onClick={() => navigate('/profile')}>
                  进入学习画像 <ChevronRight size={13} />
                </button>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ===== V11 学习周报弹层 ===== */}
      {showReport && (
        <div className="dash-report-mask" onClick={() => setShowReport(false)}>
          <div className="dash-report" onClick={e => e.stopPropagation()}>
            <div className="dash-report-head">
              <strong>学习周报</strong>
              <button className="dash-report-close" onClick={() => setShowReport(false)}>关闭</button>
            </div>
            {reportError ? (
              <div className="dash-report-summary">周报加载失败：{reportError}</div>
            ) : !report ? (
              <LoadingState text="周报生成中…" rows={0} />
            ) : (
              <>
                <div className="dash-report-summary">{report.summary}</div>
                <div className="dash-report-grid">
                  <div><em>{report.this_week.answered}</em><span>本周答题{report.last_week?.answered ? `（上周 ${report.last_week.answered}）` : ''}</span></div>
                  {/* 注意口径差异：/insight/weekly-report 的 accuracy 是 0-1 小数
                      （correct/answered），与 summary.kpi.correct_rate 的 0-100 百分数不同。 */}
                  <div><em>{report.this_week.accuracy != null ? Math.round(report.this_week.accuracy * 100) + '%' : '—'}</em><span>正确率{report.last_week?.accuracy != null ? `（上周 ${Math.round(report.last_week.accuracy * 100)}%）` : ''}</span></div>
                  <div><em>{report.this_week.duration ?? 0}</em><span>学习时长（分钟）</span></div>
                  <div>
                    <em>{report.answered_delta == null ? '—' : (report.answered_delta > 0 ? '↑' : report.answered_delta < 0 ? '↓' : '→')}</em>
                    <span>{report.answered_delta == null ? '环比（上周无答题）' : `环比 ${report.answered_delta > 0 ? '+' : ''}${report.answered_delta}%`}</span>
                  </div>
                </div>
                <div className="dash-report-bars">
                  {(() => {
                    // 柱高按本周实际峰值归一，不用「答题数 × 6」这类魔法系数——
                    // 系数只对每天几十题的量级好看，一天 200 题会顶格、5 题几乎看不见。
                    const peak = Math.max(1, ...toArr(report.daily).map((d) => d.answered || 0))
                    return toArr(report.daily).map(d => (
                      <div key={d.date} className="dash-report-bar-item" title={`${d.date} 答 ${d.answered || 0} 题`}>
                        <i style={{ height: `${Math.round(((d.answered || 0) / peak) * 100)}%` }} />
                        <b>{d.answered || ''}</b>
                        <span>{d.label || WEEK_CN[weekdayIdx(d.date)].slice(1)}</span>
                      </div>
                    ))
                  })()}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ===== V16 当日院校公告（工科/理科招生动态，随时查看） ===== */}
      {dayNotices.length > 0 && (
        <section className="dash-today" style={{ marginBottom: 'var(--space-5)' }} aria-label="当日院校公告">
          <div className="dash-today-head">
            <strong>院校公告速递</strong>
            <span className="dash-today-sub">最新 {dayNotices.length} 条 · 点标题看原文</span>
            <Link to="/kaoyan/notices" style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)' }}>进入通知中心 →</Link>
          </div>
          <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
            {dayNotices.slice(0, 6).map(n => (
              <a key={n.id} href={n.url} target="_blank" rel="noreferrer"
                style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'baseline', fontSize: 'var(--text-sm)', textDecoration: 'none', color: 'var(--fg-2)' }}>
                <em style={{ fontStyle: 'normal', fontSize: 'var(--text-xs)', padding: '1px var(--space-2)', borderRadius: 999, background: 'var(--accent-soft, rgba(43,90,158,.1))', color: 'var(--accent)', flexShrink: 0 }}>{n.notice_type || '公告'}</em>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.title}</span>
                <span style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', flexShrink: 0 }}>{n.school_name}</span>
              </a>
            ))}
          </div>
        </section>
      )}
      {/* ===== 加载骨架 ===== */}
      {loading && (
        <div className="stat-grid">
          {[0, 1, 2, 3, 4, 5].map((i) => (
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
        <div className="dash-error" role="status">
          <Warning size={15} />
          <span>实时数据暂不可用，正在展示本地缓存；启动后端后会自动恢复。</span>
          <button type="button" className="link-btn" onClick={loadAll}>重试</button>
        </div>
      )}

      {/* ===== 统计卡（可隐藏/排序，全部可点跳转对应模块） ===== */}
      {!loading && !hidden('stats') && statCards.length > 0 && (
        <div className="stat-grid">
          {statCards.map((c) => (
            <div key={c.id} className="stat-card clickable" role="button" tabIndex={0}
              onClick={() => navigate(c.to)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(c.to) } }}>
              <div className="stat-top">
                <div className={`stat-ico ${c.tone}`}><c.ico size={18} /></div>
                <span className={`stat-trend ${c.trend}`}>{c.trendText}</span>
              </div>
              <div className="stat-val">{c.value}{c.unit && <span className="stat-unit">{c.unit}</span>}</div>
              <div className="stat-label">{c.label}</div>
              {c.sub && <div className="stat-sub">{c.sub}</div>}
              <span className="stat-go">查看 <ChevronRight size={13} /></span>
            </div>
          ))}
        </div>
      )}

      {/* ===== 今日模块进度环（D-04/D-06） =====
           后端 module_progress 每项带 status，四种状态各有独立画法：
             · reached / ok  → 真实百分比环
             · no_target     → 虚线空环 +「未设目标」，不画 0%（0% 会说谎：
                               今天明明做了题，只是没定目标）
             · not_tracked   → 灰环 + 后端 note 说明缺的是哪个事件源
           目标值只来自 Goal.daily_*（用户在设置页填），前端绝不猜默认目标。 */}
      {!loading && !hidden('rings') && moduleProgress.length > 0 && (
        <div className="panel rings-panel">
          <div className="panel-head">
            <h3 className="panel-title">今日模块进度</h3>
            <span className="panel-sub">
              {targetsSet ? '目标来自目标设置' : '尚未设置每日目标 · 去设置页填一项即可点亮进度环'}
            </span>
            {!targetsSet && (
              <button className="link-btn" onClick={() => navigate('/settings')}>
                设置每日目标 <ChevronRight size={13} />
              </button>
            )}
          </div>
          <div className="ring-grid">
            {moduleProgress.map((m) => {
              const pct = m.percent == null ? 0 : Math.min(100, m.percent)
              return (
                <div key={m.module} className={`ring-cell ${m.status}`} title={m.note || null}>
                  <RingProgress percent={pct} size={72} strokeWidth={7}
                    color={m.status === 'reached' ? 'var(--success)' : 'var(--accent)'}>
                    <span className="ring-pct">
                      {m.percent == null ? (m.status === 'not_tracked' ? '—' : '0') : `${m.percent}%`}
                    </span>
                  </RingProgress>
                  <div className="ring-info">
                    <div className="ring-label">{m.label}</div>
                    <div className="ring-nums">
                      {m.done == null ? '暂无事件源' : `${m.done} / ${m.target ?? '未设'} ${m.unit}`}
                    </div>
                    <div className="ring-state">
                      {m.status === 'reached' && <span className="tag ok">已达成</span>}
                      {m.status === 'ok' && <span className="tag">进行中</span>}
                      {m.status === 'no_target' && <span className="tag muted">未设目标</span>}
                      {m.status === 'not_tracked' && <span className="tag muted">{m.note || '数据源未接入'}</span>}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ===== 目标院校 + 未来复习负荷 ===== */}
      {!loading && (!hidden('goal') || !hidden('future')) && (
        <div className="dash-row">
          {!hidden('goal') && (
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">目标与分数线</h3>
              <span className="panel-sub">来自后端 Goal / 院校分数线</span>
            </div>
            {goalBlock?.configured ? (
              <>
                <div className="goal-line">
                  <GraduationCap size={16} />
                  <b>{goalBlock.university || '未填院校'}</b>
                  <span>{goalBlock.major || '未填专业'}</span>
                </div>
                <div className="goal-scores">
                  {Object.entries(goalBlock.score_targets || {}).map(([k, v]) => (
                    <span key={k} className="goal-score">
                      <em>{SCORE_TARGET_LABEL[k] || k}</em><b>{v ?? '—'}</b>
                    </span>
                  ))}
                </div>
                {toArr(goalBlock.subjects).length > 0 && (
                  <div className="goal-subjects">
                    {goalBlock.subjects.map((s) => <span key={s} className="chip">{s}</span>)}
                  </div>
                )}
                {scoreLines.length > 0 ? (
                  /* D-02：近 3 年复试线画成迷你折线（§2.3.1「近 3 年复试分数线迷你折线」），
                     年份/分数原样列出，避免只有曲线时读不出具体数值。 */
                  <div className="goal-score-block">
                    <MiniLineChart data={scoreLines.map((l) => ({ label: String(l.year), value: l.total_line }))} height={78} />
                    <div className="goal-score-axis">
                      {scoreLines.map((l) => (
                        <span key={l.year}>
                          <em>{l.year}</em><b>{l.total_line}</b>
                        </span>
                      ))}
                    </div>
                    <p className="goal-score-cap">复试线（总分）· 来自院校库</p>
                  </div>
                ) : (
                  <p className="goal-empty">
                    暂无该院校的分数线记录。可在「院校库」录入，或先到目标页配置科目。
                  </p>
                )}
                <div className="goal-links">
                  <button className="link-btn" onClick={() => navigate('/kaoyan/schools')}>
                    去院校库看详情 <ChevronRight size={13} />
                  </button>
                  <button className="link-btn" onClick={() => navigate('/settings')}>
                    修改目标 <ChevronRight size={13} />
                  </button>
                </div>
              </>
            ) : (
              <Empty icon={<Target size={22} />} title="尚未配置考研目标"
                desc="设定院校、专业与目标分后，倒计时与进度环才会按你的口径计算"
                action={<button className="btn primary" onClick={() => navigate('/settings')}>去设置目标</button>} />
            )}
          </div>
          )}

          {/* 未来负荷（D-05）：Anki Future Due 口径的**累计**到期量，含此前欠下的复习债。
              三档可直接比大小（同一规则，切点为对应北京自然日 24:00）。 */}
          {!hidden('future') && (
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">未来复习负荷</h3>
              <span className="panel-sub">{futureLoad?.rule || '累计到期量'}</span>
            </div>
            {futureRows.length === 0 ? (
              <Empty icon={<Zap size={22} />} title="暂无到期安排"
                desc="调度器还没有为卡片 / 错题写入下次复习时间" />
            ) : (
              <div className="future-list">
                {futureRows.map((r) => (
                  <div key={r.key} className="future-row">
                    <div className="future-head">
                      <span>{r.label}</span>
                      <b>{r.total}<em>项到期</em></b>
                    </div>
                    <div className="future-bar">
                      <i style={{ width: `${futureMax ? Math.round((r.total / futureMax) * 100) : 0}%` }} />
                    </div>
                    <div className="future-split">
                      <span>错题 {r.errors}</span><span>卡片 {r.flashcards}</span>
                      <span>单词 {r.words}</span><span>任务 {r.tasks}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          )}
        </div>
      )}

      {/* ===== 专注计时（D-04 · §2.2.2「开启专注计时」） =====
          面板只负责计时与提交：写 study_sessions，读 services/study_calendar，
          同一张表同一个 sum(duration)，所以"计时器记了 25 分钟"和上面那张
          学习时长卡不可能给出两个数。没点「记录」就一行不写。 */}
      {!loading && !hidden('focus') && (
        <div className="dash-row">
          <div className="panel focus-panel">
            <div className="panel-head">
              <h3 className="panel-title">专注计时</h3>
              <span className="panel-sub">
                时长只认真实记录 · 未点「记录」不入库
                {status === 'ok' ? '' : ' · 后端不可达，暂时记不了'}
              </span>
            </div>
            <FocusTimer
              todayMinutes={kpi?.today?.focus_minutes ?? 0}
              targetMinutes={goalBlock?.daily_targets?.focus_minutes ?? null}
              subjects={focusSubjects}
              onRecorded={loadAll}
            />
          </div>
        </div>
      )}

      {/* ===== 今日任务 + 复习提醒 ===== */}
      {!loading && (!hidden('todo') || !hidden('review')) && (
        <div className="dash-row">
          {!hidden('todo') && (
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
            {/* 今日任务清单（D-03）：按模块分组的到期量。
                due=null（not_tracked）显示破折号 + 后端 note，绝不显示 0——
                "0 个到期"会说谎：它把"调度器还没接入"渲染成"你今天没欠东西"。 */}
            {taskModules.length > 0 && (
              <div className="todo-modules">
                {taskModules.map((m) => {
                  const to = MODULE_ROUTE[m.module]
                  return (
                    <button
                      key={m.module}
                      className={`todo-module ${m.status}`}
                      title={m.note || null}
                      disabled={!to}
                      onClick={() => to && navigate(to)}
                    >
                      <span className="todo-module-label">{m.label}</span>
                      <strong className="todo-module-due">
                        {m.due == null ? '—' : m.due}
                        <i>{m.due == null ? '' : m.unit}</i>
                      </strong>
                      <span className="todo-module-sub">
                        {m.status === 'not_tracked'
                          ? (m.note || '暂无排程数据源')
                          : m.status === 'clear'
                            ? '今日无到期'
                            : `今日已做 ${m.done ?? 0} ${m.unit}`}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
            <div className="task-list">
              {todayTasks.length === 0 && (
                <Empty icon={<CheckCircle size={22} />} title="今日暂无任务" desc="去任务页安排今天的复习计划"
                  action={<Link className="btn sm primary" to="/tasks">去安排任务</Link>} />
              )}
              {todayTasks.slice(0, 6).map((t) => (
                <div key={t.id} className={`task-item ${t.status === 'done' ? 'done' : ''}`}>
                  {/* 复选框：勾选即划掉并实时上报（§2.3.1），上报中禁用防连点 */}
                  <button
                    className={`task-check ${t.status === 'done' ? 'done' : ''}`}
                    aria-label={`${t.status === 'done' ? '取消完成' : '标记完成'}：${t.title || '未命名任务'}`}
                    aria-pressed={t.status === 'done'}
                    disabled={taskBusy === t.id}
                    onClick={() => onToggleTask(t)}
                  >
                    {t.status === 'done' ? <Check size={13} /> : null}
                  </button>
                  <span className="task-text">{t.title}</span>
                  {t.subject && <span className="task-subject">{t.subject}</span>}
                </div>
              ))}
            </div>
          </div>
          )}

          {!hidden('review') && (
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
            <button className="btn outline full" onClick={() => navigate('/notebook')}>全部开始复习</button>
          </div>
          )}
        </div>
      )}

      {/* ===== 可视化区：专注趋势 + 学习热力图 ===== */}
      {!loading && (!hidden('trend') || !hidden('heat')) && (
        <div className="dash-row">
          {!hidden('trend') && (
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">{rangeDays === 1 ? '近 14 日' : `${rangeLabel}学习`}趋势</h3>
              <span className="panel-sub">
                单位：分钟 · 只统计有学习记录的日子
              </span>
            </div>
            <div className="focus-chart">
              {trend.length === 0 ? (
                <Empty icon={<Activity size={22} />} title="暂无趋势数据"
                  desc="开始一次专注或刷题后，这里会出现逐日曲线"
                  action={<Link className="btn sm primary" to="/quiz">去刷题</Link>} />
              ) : (
                <MiniLineChart data={trend} height={180} showArea color="var(--accent)" />
              )}
            </div>
          </div>
          )}

          {!hidden('heat') && (
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">学习热力图</h3>
              <span className="panel-sub">
                近 {live?.heatmap?.weeks || heatmapData.length} 周 · {rangeLabel}共 {totalHeatmap} 分钟
                {coverageNote ? ` · ${coverageNote}` : ''}
              </span>
            </div>
            {heatmapData.length === 0 ? (
              <Empty icon={<Calendar size={22} />} title="还没有学习日历"
                desc={live?.data_coverage?.empty_hint
                  || '启动后端并记录一次学习，热力图的第一格就会亮起来'} />
            ) : (
              <>
                <div className="heat-wrap">
                  {heatmapData.map((week, wi) => (
                    <div key={wi} className="heat-col">
                      {week.map((day) => (
                        <div
                          key={day.date}
                          className={`heat-cell lvl-${heatLevel(day)}${day.effective ? ' eff' : ''}`}
                          title={`${day.date}：${day.duration} 分钟 · 答题 ${day.questions} 道`
                            + `${day.effective ? ' · 打卡日' : ''}`}
                        />
                      ))}
                    </div>
                  ))}
                </div>
                <div className="heat-legend">
                  <span>少</span>
                  {/* 档位数 = 后端阈值数 + 1（空档），不写死格子数量 */}
                  {Array.from({ length: heatLevels.length + 1 }, (_, i) => (
                    <span key={i} className={`heat-cell lvl-${i}`}
                      title={i === 0 ? '无学习记录'
                        : (i <= heatLevels.length - 1 ? `≥ ${heatLevels[i]} 分钟` : `≥ ${heatLevels[heatLevels.length - 1]} 分钟`)} />
                  ))}
                  <span>多</span>
                  <span className="heat-eff"><i className="heat-cell eff" /> 打卡日（当日达阈值，口径见 streak 规则）</span>
                </div>
              </>
            )}
          </div>
          )}
        </div>
      )}

      {/* ===== 院校公告栏（跨校聚合，当日哪些院校更新） ===== */}
      {!loading && !hidden('notice') && (
        <div className="dash-row">
          <div className="notice-board-full">
            <NoticeBoard />
          </div>
        </div>
      )}

      {/* ===== 智能每日推荐 + 今日时间轴 ===== */}
      {!loading && (!hidden('recommend') || !hidden('timeline')) && (
        <div className="dash-row">
          {!hidden('recommend') && (
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">今日智能推荐</h3>
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
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(rec.action) } }}
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
          )}

          {!hidden('timeline') && (
          <div className="panel">
            <div className="panel-head">
              <h3 className="panel-title">今日时间轴</h3>
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
          )}
        </div>
      )}

      {/* ===== 薄弱预警 ===== */}
      {!loading && !hidden('weakness') && (
        weakness ? (
          <div className="weak-card">
            <div className="weak-head">
              <div className="weak-ico"><Warning size={18} /></div>
              <h3 className="panel-title">薄弱科目预警</h3>
              <span className="panel-badge amber">{weakness.total_errors ?? 0} 道活跃错题</span>
            </div>
            <div className="weak-body">
              <p className="weak-desc">{weakness.suggestion || toArr(weakness.weak_subjects).map((s) => `${s.subject}(${s.count}道)`).join('、')}</p>
              {weakPoints.length > 0 ? (
                <div className="weak-points">
                  <span className="weak-points-label">最薄弱考点</span>
                  {weakPoints.map((p) => (
                    <button
                      key={p.knowledge_point_id}
                      type="button"
                      className="weak-point"
                      title={`${p.subject || '未分类'}${p.chapter ? ' · ' + p.chapter : ''}`}
                      onClick={() => navigate(`/error-review?kp_id=${p.knowledge_point_id}&kp_name=${encodeURIComponent(p.name || '')}`)}
                    >
                      <b>{p.name}</b>
                      <em>{p.error_count} 道错题 · 掌握度 {p.mastery ?? 0}</em>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="weak-points-none">
                  错题还没归集到考点 —— 到「错题复盘」给错题挂上知识点，这里才会给出考点名。
                </p>
              )}
              <button className="btn outline" onClick={() => navigate('/error-review')}>去错题本复盘</button>
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

      {/* ===== 全部模块入口（首页直达矩阵，可隐藏/排序） ===== */}
      {!loading && !hidden('modules') && moduleCells.length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <h3 className="panel-title">全部模块</h3>
            <span className="panel-sub">一键直达任意功能</span>
          </div>
          <div className="mod-grid">
            {moduleCells.map((m) => (
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
