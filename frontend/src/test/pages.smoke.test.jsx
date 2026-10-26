import React from 'react'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { summaryPayload, makeSummary, makeTaskModules } from './dashboardSummary.fixture'
import { apiSurface } from './apiSurface'
import { toggleHidden } from '../hooks/useUiLayout'

/* ------------------------------------------------------------------ *
 * 核心页面组件渲染 smoke（QA 补强）
 *
 * 目标：Dashboard / Tasks / Planner 三个高频页面在 jsdom 下
 *      **渲染不抛错、且能容忍后端返回异常数据**。
 *
 * 为什么重要：这批页面是用户每天必开的入口。此前只有 3 个 smoke 测试，
 * 只要页面白屏（undefined.map 之类）根本不会被发现 —— 而后端一旦
 * 某个字段缺失/返回 500，页面就会立刻崩掉。
 *
 * 关键设计：每个页面都测两种后端情形
 *   ① 正常数据 → 正常渲染
 *   ② 后端抛错 / 返回 undefined / 返回缺字段的残缺数据 → **仍不崩**
 * ② 才是这套测试的价值所在：一崩就是白屏。
 * ------------------------------------------------------------------ */

// ---------------------------------------------------------------- //
// echarts stub（jsdom 无 canvas）
// ---------------------------------------------------------------- //
vi.mock('echarts/core', () => ({
  use: vi.fn(),
  init: vi.fn(() => ({
    setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(),
    on: vi.fn(), off: vi.fn(), clear: vi.fn(),
    showLoading: vi.fn(), hideLoading: vi.fn(),
  })),
}))
vi.mock('echarts/charts', () => ({
  BarChart: {}, LineChart: {}, ScatterChart: {}, PieChart: {},
  RadarChart: {}, MapChart: {}, GaugeChart: {}, HeatmapChart: {},
}))
vi.mock('echarts/components', () => ({
  TitleComponent: {}, TooltipComponent: {}, LegendComponent: {}, GridComponent: {},
  PolarComponent: {}, RadarComponent: {}, GeoComponent: {}, VisualMapComponent: {},
  DatasetComponent: {}, TransformComponent: {},
}))
vi.mock('echarts/features', () => ({ LabelLayout: {}, UniversalTransition: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

// ---------------------------------------------------------------- //
// 后端 API stub
// ---------------------------------------------------------------- //
const dashboardPayload = {
  countdown: { exam_date: '2027-12-25', days: 400 },
  today_tasks: { tasks: [] },
  week_minutes: 0,
  review_due: 0,
  errors_today: 0,
  recent_docs: [],
}

/* /api/analysis/profile 的空态契约（键与 services/learner_profile.py 的 return 一一对应）。
   新注册用户看到的就是这个：结构完整、数值全 0，界面据此走空态而不是报错。 */
const emptyProfile = {
  generated_at: '2026-10-16T00:00:00Z',
  overview: {
    total_answers: 0, overall_accuracy: null, error_stock: 0, error_resolved: 0,
    exam_count: 0, exam_avg_score: null, study_days: 0, days_window: 30,
  },
  subjects: [],
  weak_points: [],
  knowledge_points: { total: 0, unlearned: 0, weak: 0, mastered: 0, labels: { unlearned: '未学', weak: '薄弱', mastered: '已掌握' } },
  review_queue: { scheduled: 0, overdue: 0, due_today: 0, no_schedule: 0 },
  trend: [],
  suggestions: ['节奏健康：保持当前学习频率，优先清空到期复习'],
}

const apiMocks = {
  /* 学习画像页（/profile）只有一个首屏请求。
     形状以 services/learner_profile.py 的 return 为准：knowledge_points 是
     {total,unlearned,weak,mastered,labels} 对象、review_queue 是四计数对象，
     写成 [] / {} 会让对应区块永不渲染，用例就等于只测了「不崩」。 */
  analysisApi: { profile: vi.fn() },
  dashboardApi: {
    get: vi.fn(),
    /* #13：首屏唯一聚合出口。Dashboard 只请求 summary，
       review_queue 由它内嵌下发，不再单独打 /dashboard/review-queue。 */
    summary: vi.fn(),
    reviewQueue: vi.fn(),
    countdown: vi.fn().mockResolvedValue(dashboardPayload.countdown),
    todayTasks: vi.fn().mockResolvedValue(dashboardPayload.today_tasks),
    stats: vi.fn().mockResolvedValue({ week_minutes: 0, review_due: 0, errors_today: 0 }),
    weakness: vi.fn().mockResolvedValue({ items: [] }),
  },
  /* V11 学习洞察（Dashboard 今日引导/周报） */
  insightApi: {
    today: vi.fn().mockResolvedValue({
      due_review_count: 0, today_tasks_count: 0, today_answered: 0,
      weak_top: [], suggestion: [],
    }),
    /* 字段以 routers/insight.py::weekly_report 的真实返回为准（accuracy 是 0-1，
       环比是 answered_delta，daily 元素是 {date, answered, correct}）。
       此前 mock 的是想象中的字段名，测试全绿而线上面板直接崩。 */
    weeklyReport: vi.fn().mockResolvedValue({
      summary: '', daily: [],
      this_week: { answered: 0, correct: 0, accuracy: null, duration: 0 },
      last_week: { answered: 0, correct: 0, accuracy: null, duration: 0 },
      answered_delta: null,
    }),
    smartPaper: vi.fn().mockResolvedValue({ mode: 'random', size: 0, basis: '', questions: [] }),
  },
  tasksApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn().mockResolvedValue({ id: 1 }),
    update: vi.fn().mockResolvedValue({}),
    remove: vi.fn().mockResolvedValue({}),
    complete: vi.fn().mockResolvedValue({}),
    uncomplete: vi.fn().mockResolvedValue({}),
    reviewSchedule: vi.fn().mockResolvedValue([]),
    aiGenerate: vi.fn().mockResolvedValue([]),
  },
  /* plannerApi 这一组此前整组都是**旧方法名**（daily/ebbinghaus/ebbinghausDue/
     earlybird/phase/keywords），而 client.js 里根本没有这些键——页面的真实调用
     （getDaily/listEbbinghaus/listEarlyBird/listPhase/getPhaseReviews）落到了
     未被 mock 的真实实现上，测试里的 mockResolvedValue 一次都没生效。
     现在按 routers/planner.py 的真实返回重写：三个 list 端点都是**裸数组**。 */
  plannerApi: {
    getDaily: vi.fn().mockResolvedValue({
      date: '2026-10-16', days_to_exam: null, tasks: {}, timeline: [],
      study_duration: 0, wasted_duration: 0, score: 0, summary: '', exists: false,
    }),
    listEbbinghaus: vi.fn().mockResolvedValue([]),
    listEarlyBird: vi.fn().mockResolvedValue([]),
    listPhase: vi.fn().mockResolvedValue([]),
    getPhaseReviews: vi.fn().mockResolvedValue({ plan_id: 1, reviews: [], total: 0 }),
    getMonth: vi.fn().mockResolvedValue({ year: 2026, month: 10, tasks: {}, completion: '', exists: false }),
    getWeek: vi.fn().mockResolvedValue({ week_start: '2026-10-12', tasks: {}, daily_records: [], exists: false }),
  },
  reviewApi: { due: vi.fn().mockResolvedValue({ total: 0, items: [] }) },
  /* 专注计时（D-04）唯一的写入口。响应体以
     routers/dashboard.py::create_study_session 的真实返回为准。 */
  studyApi: {
    addSession: vi.fn().mockResolvedValue({
      id: 1, ok: true, date: '2026-10-16', duration: 25,
      subject: null, task_type: 'pomodoro', day_total_minutes: 25,
    }),
  },
  /* Favorites / CodeBank / Growth 三组此前只写在 vi.mock 工厂的字面量里，
     「后端全挂」守卫翻不动它们 —— 于是这三个页面从没被真正的离线场景测过。
     移进 apiMocks 才能和别的分组一起被 reject。
     offlineProbe 是 client.js 的裸 request（CodeBank 直接用它，不走 api 分组）。 */
  favoritesApi: {
    list: vi.fn(), add: vi.fn(), check: vi.fn(), toggle: vi.fn(), remove: vi.fn(),
  },
  growthApi: { timeline: vi.fn() },
  offlineProbe: { request: vi.fn() },
  goalsApi: {
    list: vi.fn().mockResolvedValue([]),

    // hooks/useSubjectConfig 首屏读取：科目下拉/分类页签/进度分母的唯一来源
    subjects: vi.fn().mockResolvedValue({
      exam_subjects: ['数学', '英语', '政治'],
      support_subjects: [],
      all_known: ['数学', '英语', '政治'],
      using_default: true,
    }),
  },
}

/* 把 client.js 里每一个会打后端的方法都补成 vi.fn。
   手写清单一定会漏（上面 plannerApi 就整组漏了），而漏掉的方法有两种坏后果：
   ① 分组被 apiMocks 整体替换后该方法是 undefined，页面一调用就
      "xxx is not a function" ——「后端全挂」守卫测的其实是这个假 TypeError；
   ② 分组没被替换时它走真实实现，mockResolvedValue 根本管不到它。
   补全之后，下面的 sweep 循环才能真正把「全部 232 个端点」一起打挂。 */
const apiSurfaceInfo = apiSurface()
for (const [group, method] of apiSurfaceInfo.network) {
  const grp = (apiMocks[group] ??= {})
  if (!grp[method]) grp[method] = vi.fn()
}

vi.mock('../api/client', async (importOriginal) => {
  const real = await importOriginal()
  const merged = { ...real, DEFAULT_TIMEOUT: 30000 }
  /* 按分组合并，而不是用 apiMocks 整组替换：
     documentsApi.rawUrl / netdiskApi.contentUrl 这类只拼 URL 不发请求的 builder
     必须保留真实实现（返回字符串），被 sweep 成 reject 反而会让页面在渲染时同步抛错。 */
  for (const [group, fns] of Object.entries(apiMocks)) {
    merged[group] = { ...(real[group] ?? {}), ...fns }
  }
  // 裸 request 用延迟调用包一层：工厂在页面被 await import 时才执行，
  // 此时 apiMocks 已初始化（见 memory 里的 vi.mock TDZ 陷阱）。
  merged.request = (...a) => apiMocks.offlineProbe.request(...a)
  return merged
})

vi.mock('../api/sync', () => ({
  default: { hydrate: vi.fn().mockResolvedValue(undefined), syncTask: vi.fn() },
  syncTask: vi.fn(),
  hydrate: vi.fn().mockResolvedValue(undefined),
}))

beforeEach(() => {
  for (const grp of Object.values(apiMocks)) {
    for (const fn of Object.values(grp)) if (fn?.mockReset) fn.mockReset()
  }
  apiMocks.dashboardApi.countdown.mockResolvedValue(dashboardPayload.countdown)
  apiMocks.dashboardApi.todayTasks.mockResolvedValue(dashboardPayload.today_tasks)
  /* 首屏唯一请求：mockReset 后必须重新注入 summary，否则 Dashboard 拿到 undefined */
  apiMocks.dashboardApi.summary.mockResolvedValue(summaryPayload)
  /* reviewQueue 与其它 dashboardApi 方法一样被 beforeEach 的 mockReset 清空实现，
     必须在此重新注入，否则 Dashboard.jsx:138 的 .then() 会拿到 undefined 而抛错。 */
  apiMocks.dashboardApi.reviewQueue.mockResolvedValue(null)
  /* 专注计时写入口（routers/dashboard.py::create_study_session）的真实返回壳 */
  apiMocks.studyApi.addSession.mockResolvedValue({
    id: 1, ok: true, date: '2026-10-16', duration: 25,
    subject: null, task_type: 'pomodoro', day_total_minutes: 25,
  })
  apiMocks.tasksApi.list.mockResolvedValue([])
  apiMocks.tasksApi.reviewSchedule.mockResolvedValue([])
  /* 学习画像首屏：默认给「结构完整的空态」，个别用例再自己覆盖成有数据形状 */
  apiMocks.analysisApi.profile.mockResolvedValue(emptyProfile)
  /* V11 insight mock：reset 后恢复默认空数据，避免 Dashboard 异步引导拿到 undefined */
  apiMocks.insightApi?.today?.mockResolvedValue?.({
    due_review_count: 0, today_tasks_count: 0, today_answered: 0, weak_top: [], suggestion: [],
  })
  apiMocks.insightApi?.weeklyReport?.mockResolvedValue?.({
    summary: '', daily: [],
    this_week: { answered: 0, correct: 0, accuracy: null, duration: 0 },
    last_week: { answered: 0, correct: 0, accuracy: null, duration: 0 },
    answered_delta: null,
  })
  apiMocks.insightApi?.smartPaper?.mockResolvedValue?.({ mode: 'random', size: 0, basis: '', questions: [] })
  /* 收藏 / 代码题库 / 成长 三组：mockReset 后按各自后端的空态壳恢复
     （形状以 routers/favorites.py 分页壳、routers/codebank*.py 的真实返回为准） */
  apiMocks.favoritesApi.list.mockResolvedValue({ total: 0, items: [] })
  apiMocks.favoritesApi.add.mockResolvedValue({ ok: true, id: 1 })
  apiMocks.favoritesApi.check.mockResolvedValue({ favorited: false, id: null })
  apiMocks.favoritesApi.toggle.mockResolvedValue({ favorited: false })
  apiMocks.favoritesApi.remove.mockResolvedValue({ ok: true })
  apiMocks.growthApi.timeline.mockResolvedValue({
    days: 30, streak_days: 0, active_days: 0, timeline: [], subject_breakdown: [],
  })
  apiMocks.offlineProbe.request.mockResolvedValue({})
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

/* 静态 import 会在 vi.mock 工厂读 apiMocks 之前求值 client（TDZ），所以延后到 beforeAll 再取 */
let AuthProvider = ({ children }) => children
beforeAll(async () => { ({ AuthProvider } = await import('../auth/AuthContext')) })

function renderPage(Comp, route = '/') {
  const errors = []
  const spy = vi.spyOn(console, 'error').mockImplementation((...a) => { errors.push(a) })
  const utils = render(
    <AuthProvider>
      <MemoryRouter initialEntries={[route]}>
        <Comp />
      </MemoryRouter>
    </AuthProvider>,
  )
  // 只关心真实的崩溃（TypeError/ReferenceError），忽略 React 的 act/key 警告
  const real = errors.filter(([m]) =>
    typeof m === 'string' && /TypeError|ReferenceError|is not a function|Cannot read/i.test(m))
  return { ...utils, errors: real, spy }
}

/**
 * React 渲染期间的未捕获异常**不会**让 render() 抛出，而是被 React 记到
 * window.onerror / console.error 上。若只检查 render 是否返回，
 * 页面崩了测试也会"通过"（假绿）。
 *
 * 这里显式监听 window 的 error 事件，把它转成显式断言，
 * 确保"渲染崩溃"这类 Bug 一定会让用例变红。
 */
function withCrashCapture(fn) {
  const crashes = []
  const onError = (e) => { crashes.push(e?.message || String(e)) }
  window.addEventListener('error', onError)
  try {
    return { crashes, result: fn() }
  } finally {
    window.removeEventListener('error', onError)
  }
}

/** 等待 React 完成一轮渲染与异步数据落地，然后断言期间没有崩溃。 */
async function settle(ms = 250) {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}

// ========================================================================= //
// 一、Dashboard（首页，用户每天第一眼看到的页面）
//     #13 起首屏只请求一个端点：dashboardApi.summary()
// ========================================================================= //
describe('Dashboard 页面渲染 smoke', () => {
  it('正常后端数据下渲染出倒计时标题', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(summaryPayload)

    const { errors } = renderPage(Dashboard, '/')

    // 标题年份取自 summary.countdown.exam_year（后端 exam_calendar 单点判定），
    // 前端不再从日期字符串自己截取年份。
    const cd = summaryPayload.countdown
    expect(await screen.findByText(new RegExp(`距离 ${cd.exam_year} 考研初试还有`), {}, { timeout: 5000 }))
      .toBeInTheDocument()
    expect(errors).toEqual([])
  })

  it('后端 dashboardApi.summary 抛错时不白屏（显示降级内容而非崩溃）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockRejectedValue(new Error('network down'))

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(result.container.firstChild, '后端挂掉时首页 DOM 被清空 = 白屏').toBeTruthy()
    expect(crashes, '后端挂掉时首页抛出了未捕获异常').toEqual([])
  })

  it('后端返回 null（2xx 但无 JSON 体，client.js 会 resolve(null)）时不崩', async () => {
    // 重点 已确认的真实缺陷回归点 重点
    // 缺陷位置：src/v3/pages/Dashboard.jsx
    //   .then((d) => { setLive(d); setStatus('ok') })   // d 可能是 null，不会走 catch
    //   读取处必须用 live?.today_tasks 而不是 live.today_tasks，否则 TypeError → 首页白屏
    // 触发路径：api/client.js 对无 JSON 体的响应返回 null 而非抛错。
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(null)
    apiMocks.dashboardApi.weakness.mockResolvedValue(null)

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(crashes, 'Dashboard 未防御 live 为 null 的情况 → 首页白屏').toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('后端返回 undefined（下游 .map 崩溃高发点）时不崩', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(undefined)
    apiMocks.dashboardApi.weakness.mockResolvedValue(undefined)

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(crashes, 'Dashboard 未防御后端返回 undefined').toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('后端返回缺字段的残缺对象时不崩', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    // 只给一个空壳：countdown / kpi / module_progress / heatmap 全缺
    apiMocks.dashboardApi.summary.mockResolvedValue({})

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('summary 内嵌字段形状不匹配（tasks 非数组 / days 为对象）时不崩', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue({
      countdown: { exam_date: '2027-12-25', days: 400 },
      today_tasks: {},              // 缺 tasks 字段
      heatmap: { days: {} },        // 应为数组
      trend: { series: null },
      module_progress: null,
      future_load: { due_today: null },
    })

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  /* ---- #13 契约：空数据框架必须渲染成"无到期/未跟踪"，而不是伪造 0% ---- */
  it('未设每日目标时不伪造进度百分比（空台账如实显示无到期 / 未跟踪）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(summaryPayload)
    renderPage(Dashboard, '/')

    expect(await screen.findByText('今日模块进度', {}, { timeout: 5000 })).toBeInTheDocument()
    const grid = document.querySelector('.v3-dash-modules__grid')
    expect(grid, '模块进度网格未渲染').toBeTruthy()
    // 4 个有排程源的模块 due=0 → 无到期；2 个无排程源 → — + 原因；都不写 0%
    expect(grid.querySelectorAll('.v3-dash-mod.is-clear')).toHaveLength(4)
    expect(grid.querySelectorAll('.v3-dash-mod.is-untracked')).toHaveLength(2)
    expect(grid.textContent).not.toMatch(/\d+%/)
  })

  it('KPI 正确率无答题时如实为空（null 渲染成占位而不是 0%）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(summaryPayload)
    renderPage(Dashboard, '/')

    await screen.findByText('今日模块进度', {}, { timeout: 5000 })
    const strip = document.querySelector('.v3-dash-kpi')
    expect(strip, 'summary.kpi 存在时应渲染今日 KPI 条').toBeTruthy()
    expect(strip.textContent).toContain('正确率')
    expect(strip.textContent).toMatch(/—/)
  })

  it('目标卡按后端区块渲染（空目标时给配置引导）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(summaryPayload)
    renderPage(Dashboard, '/')

    await screen.findByText('目标与分数线', {}, { timeout: 5000 })
    expect(await screen.findByText('还没设置目标')).toBeInTheDocument()
    expect(screen.getByText('去择校')).toBeInTheDocument()
    // 没配置就没有分数线区块，更不画假折线
    expect(document.querySelector('.v3-dash-goal__lines')).toBeNull()
  })

  it('后端复习队列缺失时，待复习数字标出「本机估算」而不是装作权威值', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const noQueue = makeSummary({ review_queue: null })
    apiMocks.dashboardApi.summary.mockResolvedValue(noQueue)
    renderPage(Dashboard, '/')

    const cards = await screen.findAllByText('待复习', {}, { timeout: 5000 })
    expect(cards.length, '统计卡应渲染').toBeGreaterThan(0)
    expect(await screen.findByText('本机估算 · 后端队列不可达')).toBeInTheDocument()
  })

  it('复习队列正常时不再打「本机估算」标记', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(summaryPayload)
    renderPage(Dashboard, '/')

    await screen.findAllByText('待复习', {}, { timeout: 5000 })
    expect(screen.queryByText('本机估算 · 后端队列不可达')).not.toBeInTheDocument()
    expect(await screen.findByText('复习调度器口径')).toBeInTheDocument()
  })

  it('KPI 正确率按后端百分数原样渲染（曾因前端再乘 100 显示 8250%）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const active = makeSummary()
    active.kpi.today = { ...active.kpi.today, questions_done: 40, questions_correct: 33, correct_rate: 82.5 }
    active.kpi.delta.correct_rate_pp = 2.5
    apiMocks.dashboardApi.summary.mockResolvedValue(active)
    renderPage(Dashboard, '/')

    await screen.findByText('今日模块进度', {}, { timeout: 5000 })
    const strip = document.querySelector('.v3-dash-kpi')
    expect(strip.textContent).toContain('83%')
    expect(strip.textContent).not.toMatch(/8250/)
  })

  it('学习周报面板读后端真实字段（时长/环比/逐日柱），缺字段也不整块崩', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(summaryPayload)
    apiMocks.insightApi.weeklyReport.mockResolvedValue({
      summary: '本周答题 40 题，正确率 83%，学习 120 分钟',
      this_week: { answered: 40, correct: 33, accuracy: 0.825, duration: 120 },
      last_week: { answered: 32, correct: 24, accuracy: 0.75, duration: 90 },
      answered_delta: 25.0,
      daily: [
        { date: '2026-10-12', answered: 10, correct: 8 },
        { date: '2026-10-13', answered: 0, correct: 0 },
        { date: '2026-10-14', answered: 30, correct: 25 },
      ],
    })
    const { crashes } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await screen.findByText('今日模块进度', {}, { timeout: 5000 })

    await act(async () => { fireEvent.click(screen.getByText('学习周报')) })

    const dialog = await screen.findByRole('dialog', { name: '学习周报' }, { timeout: 5000 })
    const text = dialog.textContent
    // accuracy 后端是 0-1，前端必须 ×100 再四舍五入（曾直接 Math.round(0.825) 显示 1%）
    expect(text).toContain('83%')
    expect(text).toContain('120')
    expect(text).toContain('学习时长')
    expect(text).toContain('环比 +25%')
    const bars = dialog.querySelectorAll('.v3-dash-goal__bar')
    expect(bars).toHaveLength(3)
    expect(bars[0].textContent).toContain('10')
    expect(bars[2].textContent).toContain('30')
    expect(crashes, `周报面板渲染不应抛错：${crashes.map(String).join(' | ')}`).toHaveLength(0)
  })

  it('今日任务清单按模块给到期量；无排程源的模块显示「—」+ 原因而不是 0（D-03）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const dueToday = { flashcards: 12, tasks: 3, errors: 5, words: 48, total: 68, cutoff: '2026-10-16T16:00:00Z' }
    const busy = makeSummary()
    busy.future_load = { ...busy.future_load, due_today: dueToday }
    busy.kpi.today = { ...busy.kpi.today, words_done: 10, errors_done: 2 }
    busy.today_tasks = { ...busy.today_tasks, modules: makeTaskModules(dueToday, busy.kpi.today) }
    apiMocks.dashboardApi.summary.mockResolvedValue(busy)
    renderPage(Dashboard, '/')

    await screen.findByText('今日模块进度', {}, { timeout: 5000 })
    const wrap = document.querySelector('.v3-dash-modules__grid')
    expect(wrap, '今日任务清单（D-03）未渲染').toBeTruthy()
    // 到期数来自 future_load.due_today，完成数来自日活台账
    expect(wrap.textContent).toContain('10/48 个')
    expect(wrap.textContent).toContain('2/5 道')
    // 刷题/真题没有排程源：破折号 + note，绝不显示 0（0 会说"你今天没欠东西"）
    const dead = [...wrap.querySelectorAll('.v3-dash-mod.is-untracked')]
    expect(dead).toHaveLength(2)
    for (const cell of dead) {
      expect(cell.querySelector('.v3-dash-mod__value').textContent.trim()).toBe('—')
      expect(cell.getAttribute('title'), 'not_tracked 必须说明缺的是哪一块').toBeTruthy()
    }
    expect(wrap.textContent).toContain('题库没有排程字段')
    // 没有 percent：到期数 ÷ 完成数不是进度
    expect(wrap.textContent).not.toMatch(/%/)
  })

  it('空库时清单如实显示「无到期」，不编造待办数', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    apiMocks.dashboardApi.summary.mockResolvedValue(summaryPayload)
    renderPage(Dashboard, '/')

    await screen.findByText('今日模块进度', {}, { timeout: 5000 })
    const wrap = document.querySelector('.v3-dash-modules__grid')
    expect(wrap).toBeTruthy()
    expect(wrap.querySelectorAll('.v3-dash-mod.is-clear')).toHaveLength(4)
    expect(wrap.textContent).toContain('无到期')
  })

  it('今日任务勾选即上报后端并重新拉 summary（§2.3.1 复选框）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const withTask = makeSummary()
    withTask.today_tasks = {
      ...withTask.today_tasks, total: 1, pending: 1,
      tasks: [{ id: 7, title: 'D03 勾选上报测试', subject: '数学', status: 'pending', due_date: '2026-10-16' }],
    }
    apiMocks.dashboardApi.summary.mockResolvedValue(withTask)
    renderPage(Dashboard, '/')

    await waitFor(() => expect(document.querySelector('.v3-dash-task__title')).toBeTruthy())
    const before = apiMocks.dashboardApi.summary.mock.calls.length
    const box = document.querySelector('.v3-dash-task')
    expect(box.getAttribute('aria-label')).toBe('标记完成：D03 勾选上报测试')

    await act(async () => {
      fireEvent.click(box)
      await new Promise((r) => setTimeout(r, 50))
    })

    expect(apiMocks.tasksApi.complete).toHaveBeenCalledWith(7)
    // 上报后必须重新拉一次：清单/进度环/日活台账都从同一份 summary 派生
    await waitFor(() => expect(apiMocks.dashboardApi.summary.mock.calls.length).toBeGreaterThan(before))
  })

  it('目标院校卡渲染近 3 年复试线 + 择校入口（D-02）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const withGoal = makeSummary()
    withGoal.goal = {
      ...withGoal.goal, configured: true, university: '测试大学', major: '计算机科学与技术',
      recent_score_lines: [{ year: 2024, total_line: 320 }, { year: 2025, total_line: 335 }, { year: 2026, total_line: 350 }],
    }
    apiMocks.dashboardApi.summary.mockResolvedValue(withGoal)
    const { crashes } = withCrashCapture(() => renderPage(Dashboard, '/'))

    await screen.findByText('目标与分数线', {}, { timeout: 5000 })
    const block = document.querySelector('.v3-dash-goal__lines')
    expect(block, 'D-02 要求近 3 年复试线可视化').toBeTruthy()
    expect(block.querySelectorAll('.v3-dash-goal__bar')).toHaveLength(3)
    expect(block.textContent).toContain('2024')
    expect(block.textContent).toContain('320')
    expect(screen.getByText(/测试大学/)).toBeInTheDocument()
    expect(await screen.findByText('择校')).toBeInTheDocument()
    expect(crashes).toEqual([])
  })

  it('院校无分数线记录时留白说明，不画一条 0 线冒充趋势（D-02）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const noLines = makeSummary()
    noLines.goal = { ...noLines.goal, configured: true, university: '测试大学', recent_score_lines: [] }
    apiMocks.dashboardApi.summary.mockResolvedValue(noLines)
    renderPage(Dashboard, '/')

    await screen.findByText('目标与分数线', {}, { timeout: 5000 })
    expect(document.querySelector('.v3-dash-goal__lines')).toBeNull()
    expect(await screen.findByText(/库里还没有这所院校的复试线/)).toBeInTheDocument()
  })

  // ---- D-04 今日学习时长（专注计时）----
  it('专注计时面板的今日时长与每日目标都读后端字段（D-04）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const withFocus = makeSummary()
    withFocus.kpi = {
      ...withFocus.kpi,
      today: { ...withFocus.kpi.today, focus_minutes: 152, effective: true },
    }
    withFocus.goal = {
      ...withFocus.goal, configured: true, subjects: ['数学'],
      daily_targets: { ...withFocus.goal.daily_targets, focus_minutes: 120 },
    }
    apiMocks.dashboardApi.summary.mockResolvedValue(withFocus)
    const { crashes } = withCrashCapture(() => renderPage(Dashboard, '/'))

    await screen.findByText('专注计时', {}, { timeout: 5000 })
    const panel = document.querySelector('.v3-dash-focus')
    expect(panel, 'D-04 的计时入口未渲染').toBeTruthy()
    // 今日时长必须来自 kpi.today.focus_minutes（后端台账），不是前端自己攒的
    expect(panel.querySelector('.v3-focus__meta strong').textContent).toBe('152 分钟')
    expect(panel.querySelector('.v3-focus__meta .v3-progress__bar').style.width).toBe('100%')
    expect(panel.textContent).toContain('目标 120 分钟 · 100%')
    expect(panel.textContent).not.toContain('未设置每日时长目标')
    // 科目候选只来自 summary.goal.subjects，前端不补「政治/英语」这种默认科
    const opts = Array.from(panel.querySelector('select').options).map((o) => o.value)
    expect(opts).toEqual(['', '数学'])
    expect(crashes).toEqual([])
  })

  it('首屏点「记录」写后端并重新拉 summary（D-04 闭环）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    // 键名与 FocusTile 同源：按账号隔离后的真实存储键
    const { ukey } = await import('../utils/userKeys')
    const before = apiMocks.dashboardApi.summary.mock.calls.length
    // 已暂停在 20 分钟的一段专注：刷新页面不该丢掉它（组件按时间戳恢复）
    localStorage.setItem(ukey('v3_focus_v1'), JSON.stringify({
      runningSince: null, accumMs: 20 * 60000, minutes: 25,
      subject: '数学', startedTs: Date.now() - 20 * 60000,
    }))
    apiMocks.studyApi.addSession.mockResolvedValue({
      id: 9, ok: true, date: '2026-10-16', duration: 20,
      subject: '数学', task_type: 'pomodoro', day_total_minutes: 20,
    })
    renderPage(Dashboard, '/')

    await screen.findByText('专注计时', {}, { timeout: 5000 })
    const record = [...document.querySelectorAll('.v3-dash-focus button')]
      .find((b) => /记录 20 分钟/.test(b.textContent))
    expect(record, '恢复的计时没接着显示记录按钮').toBeTruthy()
    fireEvent.click(record)

    await waitFor(() => expect(apiMocks.studyApi.addSession).toHaveBeenCalledTimes(1))
    // 记的是实际经过的 20 分钟，不是 25 分钟档位
    expect(apiMocks.studyApi.addSession.mock.calls[0][0]).toMatchObject({
      duration: 20, task_type: 'pomodoro', subject: '数学',
    })
    await waitFor(() => expect(apiMocks.dashboardApi.summary.mock.calls.length).toBeGreaterThan(before))
  })

  it('界面定制勾掉「专注计时」后首屏不再出现该面板（区块 id 接线）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    act(() => { toggleHidden('dashHidden', 'focus') })
    try {
      renderPage(Dashboard, '/')
      await screen.findByText('今日任务', { selector: '.v3-card__title' }, { timeout: 5000 })
      expect(document.querySelector('.v3-dash-focus')).toBeNull()
    } finally {
      act(() => { toggleHidden('dashHidden', 'focus') })
    }
    renderPage(Dashboard, '/')
    await screen.findByText('专注计时', {}, { timeout: 5000 })
    expect(document.querySelector('.v3-dash-focus')).toBeTruthy()
  })

  // ---- D-10 薄弱知识点 Top3（联动错题本）----
  it('首屏显示薄弱知识点 Top3，点击跳错题本并按该考点筛（D-10）', async () => {
    const { Routes, Route, useLocation } = await import('react-router-dom')
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const withWeak = makeSummary()
    withWeak.weakness = {
      ...withWeak.weakness,
      has_weakness: true, total_errors: 30,
      weak_subjects: [{ subject: '数学', count: 20, level: 'high' }],
      // 后端 error_linker.weak_knowledge_points 已排好序并截断到 3 条
      weak_points: [
        { knowledge_point_id: 101, name: '极限存在准则', subject: '数学', chapter: '高等数学上', mastery: 20, error_count: 20 },
        { knowledge_point_id: 102, name: '中值定理', subject: '数学', chapter: '高等数学上', mastery: 45, error_count: 10 },
      ],
      suggestion: '建议重点复习薄弱科目，针对常见错误原因进行专项训练。',
    }
    apiMocks.dashboardApi.summary.mockResolvedValue(withWeak)

    const Loc = () => {
      const loc = useLocation()
      return <div data-testid="loc">{loc.pathname + loc.search}</div>
    }
    render(
      <MemoryRouter initialEntries={['/']}>
        <Loc />
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/error-review" element={<div>错题复盘页</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await screen.findByText('薄弱考点', {}, { timeout: 5000 })
    const chips = [...document.querySelectorAll('.v3-dash-weak__item')]
    expect(chips.map((c) => c.querySelector('.v3-dash-weak__name').textContent)).toEqual(['极限存在准则', '中值定理'])
    expect(chips[0].textContent).toContain('错 20 次')

    fireEvent.click(chips[1])
    await waitFor(() => expect(screen.getByTestId('loc').textContent)
      .toBe('/error-review?kp_id=102&kp_name=%E4%B8%AD%E5%80%BC%E5%AE%9A%E7%90%86'))
  })

  it('错题还没挂上知识点时如实说明，不拿科目名冒充考点（D-10 空态）', async () => {
    const Dashboard = (await import('../v3/pages/Dashboard')).default
    const noKp = makeSummary()
    noKp.weakness = {
      ...noKp.weakness, has_weakness: true, total_errors: 8,
      weak_subjects: [{ subject: '数学', count: 8, level: 'medium' }],
      weak_points: [], common_reasons: [{ reason: '计算失误', count: 5 }],
    }
    apiMocks.dashboardApi.summary.mockResolvedValue(noKp)
    renderPage(Dashboard, '/')

    await screen.findByText('薄弱考点', {}, { timeout: 5000 })
    expect(document.querySelectorAll('.v3-dash-weak__item')).toHaveLength(0)
    expect(await screen.findByText(/错题还没归集到考点/)).toBeInTheDocument()
  })
})

// ========================================================================= //
// 二、Tasks（任务打卡，使用频率最高的交互页）
// ========================================================================= //
describe('Tasks 页面渲染 smoke', () => {
  it('渲染出今日任务视图且不抛错', async () => {
    const Tasks = (await import('../v3/pages/Tasks')).default
    apiMocks.tasksApi.list.mockResolvedValue([])
    apiMocks.tasksApi.reviewSchedule.mockResolvedValue([])

    const { crashes, result } = withCrashCapture(() => renderPage(Tasks, '/tasks'))
    await settle()

    expect(result.container.firstChild).toBeTruthy()
    expect(crashes).toEqual([])
    // 页面应包含"任务"字样的入口或标题
    expect(result.container.textContent).toMatch(/任务|今日|打卡/)
  })

  it('task 字段缺失（无 title/subject）时不崩', async () => {
    const Tasks = (await import('../v3/pages/Tasks')).default
    // 残缺任务：只有 id，其余全 undefined
    apiMocks.tasksApi.list.mockResolvedValue([{ id: 1 }])
    apiMocks.tasksApi.reviewSchedule.mockResolvedValue([])

    const { crashes, result } = withCrashCapture(() => renderPage(Tasks, '/tasks'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('tasksApi.list 返回非数组（对象/null）时不崩', async () => {
    const Tasks = (await import('../v3/pages/Tasks')).default
    apiMocks.tasksApi.list.mockResolvedValue({ items: [] })   // 形状不匹配
    apiMocks.tasksApi.reviewSchedule.mockResolvedValue(null)

    const { crashes, result } = withCrashCapture(() => renderPage(Tasks, '/tasks'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })
})

// ========================================================================= //
// 三、Planner（日/周/月计划 + 艾宾浩斯 + 早起打卡 + 阶段复习）
//     注意：这一组 mock 的键必须是 client.js 的真实方法名。此前写的是
//     daily/ebbinghaus/ebbinghausDue/earlybird/phase 这些**不存在的旧名**，
//     mockResolvedValue 一次都没落到页面上（页面走的是未 mock 的真实实现）。
// ========================================================================= //
describe('Planner 页面渲染 smoke', () => {
  it('渲染复习计划页且不抛错', async () => {
    const Planner = (await import('../v3/pages/Planner')).default

    const { crashes, result } = withCrashCapture(() => renderPage(Planner, '/planner'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
    // 首屏真的打了这几个端点（而不是因为名字写错而一个都没发出去）
    expect(apiMocks.plannerApi.getDaily).toHaveBeenCalled()
    expect(apiMocks.plannerApi.listEarlyBird).toHaveBeenCalled()
    expect(apiMocks.plannerApi.listEbbinghaus).toHaveBeenCalled()
  })

  it('后端返回 undefined / null 时不崩（曾因 500 导致数据为 undefined）', async () => {
    const Planner = (await import('../v3/pages/Planner')).default
    // 模拟后端 500 后的兜底：undefined / null / 缺字段
    apiMocks.plannerApi.getDaily.mockResolvedValue(undefined)
    apiMocks.plannerApi.listEbbinghaus.mockResolvedValue(null)
    apiMocks.plannerApi.listEarlyBird.mockResolvedValue(undefined)
    apiMocks.plannerApi.listPhase.mockResolvedValue(undefined)
    apiMocks.plannerApi.getMonth.mockResolvedValue(null)
    apiMocks.plannerApi.getWeek.mockResolvedValue(undefined)

    const { crashes, result } = withCrashCapture(() => renderPage(Planner, '/planner'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('列表条目缺字段时不崩（后端只回了 id）', async () => {
    const Planner = (await import('../v3/pages/Planner')).default
    // 形状以 routers/planner.py 为准：三个 list 端点都是裸数组，元素字段可缺
    apiMocks.plannerApi.listEbbinghaus.mockResolvedValue([{ id: 1 }])
    apiMocks.plannerApi.listEarlyBird.mockResolvedValue([{ id: 1 }])
    apiMocks.plannerApi.listPhase.mockResolvedValue([{ id: 1 }])
    apiMocks.plannerApi.getPhaseReviews.mockResolvedValue({
      plan_id: 1, reviews: [{ day_num: 1 }], total: 1,
    })

    const { crashes, result } = withCrashCapture(() => renderPage(Planner, '/planner'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })
})

// ========================================================================= //
// 四、健壮性守卫：后端完全不可用时页面仍能出骨架
// ========================================================================= //
describe('页面健壮性总守卫', () => {
  /* App.jsx 里全部 37 个路由页面，逐个测两种最恶劣的后端形态。
     覆盖面就是这一节的价值：新加页面必须进这张表，否则它从未被离线场景测过
     ——CodeBank 的 null 白屏（subjects.length 直接崩）就是漏测的真实代价。 */
  const pages = [
    ['Dashboard', '../v3/pages/Dashboard', '/'],
    /* 今日中枢只消费聚合端点；核心接口全挂时显示可重试错误页，不白屏 */
    ['Hub', '../v3/pages/Hub', '/hub'],
    ['Tasks', '../v3/pages/Tasks', '/tasks'],
    ['KbMap', '../v3/pages/KbMap', '/knowledge'],
    ['KnowledgeArticle', '../v3/pages/KnowledgeArticle', '/knowledge/1'],
    ['Library', '../v3/pages/Library', '/library'],
    ['Notebook', '../v3/pages/Notebook', '/notebook'],
    ['Assistant', '../v3/pages/Assistant', '/assistant'],
    ['Pan', '../v3/pages/Pan', '/pan'],
    ['Words', '../v3/pages/Words', '/words'],
    ['Cards', '../v3/pages/Cards', '/cards'],
    ['Settings', '../v3/pages/Settings', '/settings'],
    ['CodeBank', '../v3/pages/CodeBank', '/codebank'],
    /* Quiz 是会话容器（真题/知识点会话引擎），子视图在 v3/pages/Quiz*，路由仍指向容器 */
    ['Quiz', '../v3/pages/Quiz', '/quiz'],
    ['QuizBank', '../v3/pages/QuizBank', '/admin/quiz-bank'],
    ['LearnerProfile', '../v3/pages/LearnerProfile', '/profile'],
    ['SubjectManager', '../v3/pages/SubjectManager', '/admin/subjects'],
    ['UserAdmin', '../v3/pages/UserAdmin', '/admin/users'],
    ['Documents', '../v3/pages/Documents', '/documents'],
    ['Planner', '../v3/pages/Planner', '/planner'],
    ['KaoyanGuide', '../v3/pages/KaoyanGuide', '/kaoyan/guide'],
    ['KaoyanSchools', '../v3/pages/KaoyanSchools', '/kaoyan/schools'],
    ['NoticeCenter', '../v3/pages/NoticeCenter', '/kaoyan/notices'],
    ['KaoyanSchoolDetail', '../v3/pages/KaoyanSchoolDetail', '/kaoyan/schools/1'],
    ['KaoyanCompare', '../v3/pages/KaoyanCompare', '/kaoyan/compare'],
    ['KaoyanAnalysis', '../v3/pages/KaoyanAnalysis', '/kaoyan/analysis'],
    ['KaoyanRecommend', '../v3/pages/KaoyanRecommend', '/kaoyan/recommend'],
    ['KaoyanImport', '../v3/pages/KaoyanImport', '/admin/schools'],
    ['KaoyanMap', '../v3/pages/KaoyanMap', '/kaoyan/map'],
    ['KaoyanScatter', '../v3/pages/KaoyanScatter', '/kaoyan/scatter'],
    ['KaoyanAssistant', '../v3/pages/KaoyanAssistant', '/kaoyan/assistant'],
    ['PlanPage', '../v3/pages/PlanPage', '/kaoyan/plan'],
    ['GrowthPage', '../v3/pages/GrowthPage', '/kaoyan/growth'],
    ['ErrorReview', '../v3/pages/ErrorReview', '/error-review'],
    ['QualityDashboard', '../v3/pages/QualityDashboard', '/admin/quality'],
    ['Insights', '../v3/pages/Insights', '/insights'],
    ['Favorites', '../v3/pages/Favorites', '/favorites'],
    ['LearningTimeline', '../v3/pages/LearningTimeline', '/timeline'],
    ['Textbooks', '../v3/pages/Textbooks', '/textbooks'],
    ['DataCenter', '../v3/pages/DataCenter', '/admin/overview'],
    ['ExamCenter', '../v3/pages/ExamCenter', '/exam'],
    ['ExamMock', '../v3/pages/ExamMock', '/exam-mock'],
    ['KaoyanCrawlSources', '../v3/pages/KaoyanCrawlSources', '/admin/crawl-sources'],
    ['KnowledgeBaseImport', '../v3/pages/KnowledgeBaseImport', '/admin/kb-import'],
    ['ModelTraining', '../v3/pages/ModelTraining', '/admin/model'],
    ['Login', '../v3/pages/Login', '/login'],
    /* 无身份时它会正确地跳回登录页（DOM 为空不是白屏），所以 null 场景以「须改密」身份进入 */
    ['ForceChangePassword', '../v3/pages/ForceChangePassword', '/force-change-password', { me: { id: 1, username: 'u', role: 'user', must_change_password: true } }],
    ['Forbidden', '../v3/pages/Forbidden', '/403'],
    ['GlassLab', '../v3/pages/GlassLab', '/glass'],
  ]
  const routes = new Set(pages.map(([, , r]) => r))

  it('守卫表覆盖 App.jsx 的每一个路由页面', async () => {
    const { default: fs } = await import('node:fs')
    const { default: nodePath } = await import('node:path')
    const app = fs.readFileSync(nodePath.resolve(process.cwd(), 'src', 'App.jsx'), 'utf8')
    const imported = [...app.matchAll(/lazy\(\(\) => import\('\.\/(?:v3\/)?pages\/(\w+)'\)\)/g)]
      .map((m) => m[1])
    const missing = imported.filter((n) => !pages.some(([name]) => name === n))
    expect(missing, `这些页面一次都没被离线守卫测过：${missing.join(', ')}`).toEqual([])
    expect(imported.length, 'App.jsx 的 lazy 页面解析数量变了，检查解析正则').toBeGreaterThan(30)
    expect(routes.size).toBe(pages.length)
  })

  it('apiMocks 里不存在 client.js 中没有的方法名', () => {
    /* 这一条封的是上一轮实测到的失效：plannerApi 整组写的是旧方法名，
       页面调真实方法、测试改的是不存在的键，两边互不相干 → 用例只测了个「不崩」。 */
    const declared = new Map()
    for (const [g, m] of apiSurfaceInfo.network) {
      if (!declared.has(g)) declared.set(g, new Set())
      declared.get(g).add(m)
    }
    const stale = []
    for (const [g, fns] of Object.entries(apiMocks)) {
      if (g === 'offlineProbe') continue
      for (const name of Object.keys(fns)) if (!declared.get(g)?.has(name)) stale.push(`${g}.${name}`)
    }
    expect(stale, `mock 了不存在的方法：${stale.join(', ')}`).toEqual([])
  })

  it('client.js 的每个网络方法都被 mock 覆盖（否则守卫翻不动它）', () => {
    const unmocked = apiSurfaceInfo.network
      .filter(([g, m]) => !apiMocks[g]?.[m]?.mock)
      .map(([g, m]) => `${g}.${m}`)
    expect(unmocked, `这些端点没进 mock：${unmocked.join(', ')}`).toEqual([])
    expect(apiSurfaceInfo.network.length).toBeGreaterThan(200)
  })

  it.each(pages)('%s 在后端全挂时仍能渲染骨架', async (_name, modPath, route) => {
    // 后端所有接口一律 reject —— 最恶劣的线上情形（服务完全不可用）
    for (const grp of Object.values(apiMocks)) {
      for (const fn of Object.values(grp)) {
        if (fn?.mockRejectedValue) fn.mockRejectedValue(new Error('backend offline'))
      }
    }

    const Comp = (await import(modPath)).default
    const { crashes, result } = withCrashCapture(() => renderPage(Comp, route))
    await settle(400)

    expect(result.container.firstChild, `${_name} 在后端全挂时 DOM 为空 = 白屏`).toBeTruthy()
    expect(crashes, `${_name} 在后端全挂时抛出了未捕获异常`).toEqual([])
  })

  it.each(pages)('%s 在后端返回 null 时仍能渲染骨架', async (_name, modPath, route, opts) => {
    // 比"全挂"更隐蔽的情形：后端 200 但响应体为空 → client.js resolve(null)，
    // Promise 是 fulfilled，页面的 .catch 兜底**完全不会触发**。
    for (const grp of Object.values(apiMocks)) {
      for (const fn of Object.values(grp)) {
        if (fn?.mockResolvedValue) fn.mockResolvedValue(null)
      }
    }
    if (opts?.me) apiMocks.authApi.me.mockResolvedValue(opts.me)

    const Comp = (await import(modPath)).default
    const { crashes, result } = withCrashCapture(() => renderPage(Comp, route))
    await settle(400)

    expect(result.container.firstChild, `${_name} 收到 null 时 DOM 为空 = 白屏`).toBeTruthy()
    expect(crashes, `${_name} 收到 null 时抛出了未捕获异常（.catch 兜底失效）`).toEqual([])
  })
})

// ========================================================================= //
// 二·五、LearnerProfile（学习画像 /profile）
//     只依赖一个端点：analysisApi.profile()。此前这个页面自己拼 useState+try/catch，
//     并把「200 但响应体为空」也报成「后端未启动或网络异常」——空数据是全新用户的
//     正常形态，不该往故障方向把人带偏。三态/失败/空三形在这里都锁住。
// ========================================================================= //
const profileWith = (over) => ({ ...emptyProfile, ...over })

describe('LearnerProfile：三态、空态与薄弱 TOP 严格按后端契约', () => {
  it('知识点三态卡由 {total,unlearned,weak,mastered} 对象渲染，分布条按同一比例', async () => {
    const LearnerProfile = (await import('../v3/pages/LearnerProfile')).default
    apiMocks.analysisApi.profile.mockResolvedValue(profileWith({
      knowledge_points: { total: 50, unlearned: 20, weak: 18, mastered: 12, labels: { unlearned: '未学', weak: '薄弱', mastered: '已掌握' } },
    }))

    renderPage(LearnerProfile, '/profile')
    await screen.findByText('知识点掌握度', {}, { timeout: 5000 })

    // mock 曾写成 knowledge_points: [] —— [ ].total 是 undefined，整块永不渲染，
    // 用例只会「通过」而什么都没测到。这里断言计数与标签都在。
    const sec = screen.getByText('知识点掌握度').closest('.v3-tile')
    expect(sec.textContent).toContain('共 50 个')
    expect(sec.textContent).toContain('未学')
    expect(sec.textContent).toContain('已掌握')
    expect(screen.getByText('18')).toBeInTheDocument()

    const bar = sec.querySelector('[aria-label="知识点掌握度分布"]')
    expect([...bar.children].map((s) => s.style.width)).toEqual(['40%', '36%', '24%'])
  })

  it('一个知识点都还没有时不渲染三态卡，也不拿「共 0 个」冒充数据', async () => {
    const LearnerProfile = (await import('../v3/pages/LearnerProfile')).default
    renderPage(LearnerProfile, '/profile')
    await screen.findByText('学习画像', {}, { timeout: 5000 })
    expect(screen.queryByText('知识点掌握度')).toBeNull()
  })

  it('后端 200 空体 → 空态文案，不再谎报「后端未启动」', async () => {
    const LearnerProfile = (await import('../v3/pages/LearnerProfile')).default
    apiMocks.analysisApi.profile.mockResolvedValue(null)
    renderPage(LearnerProfile, '/profile')
    await screen.findByText('还没有可聚合的学习行为', {}, { timeout: 5000 })
    expect(screen.queryByText(/后端未启动/)).toBeNull()
  })

  it('接口 500 → 错误态显示后端真实报错并可重试', async () => {
    const LearnerProfile = (await import('../v3/pages/LearnerProfile')).default
    const err = new Error('HTTP 500：内部错误')
    err.name = 'ApiError'
    apiMocks.analysisApi.profile.mockRejectedValue(err)

    renderPage(LearnerProfile, '/profile')
    await screen.findByText(/HTTP 500：内部错误/, {}, { timeout: 5000 })
    fireEvent.click(screen.getByRole('button', { name: /重新加载/ }))
    await settle(200)
    expect(apiMocks.analysisApi.profile).toHaveBeenCalledTimes(2)
  })

  it('薄弱知识点 TOP 显示后端给的考点名，点击按该考点筛错题（与 D-10 同一深链）', async () => {
    const { Routes, Route, useLocation } = await import('react-router-dom')
    const LearnerProfile = (await import('../v3/pages/LearnerProfile')).default
    apiMocks.analysisApi.profile.mockResolvedValue(profileWith({
      weak_points: [
        { knowledge_point_id: 101, name: '极限存在准则', subject: '数学', chapter: '高等数学上', mastery: 20, error_count: 20 },
        { knowledge_point_id: 102, name: '中值定理', subject: '数学', chapter: '高等数学上', mastery: 45, error_count: 10 },
      ],
    }))

    const Loc = () => {
      const loc = useLocation()
      return <div data-testid="loc">{loc.pathname + loc.search}</div>
    }
    render(
      <MemoryRouter initialEntries={['/profile']}>
        <Loc />
        <Routes>
          <Route path="/profile" element={<LearnerProfile />} />
          <Route path="/error-review" element={<div>错题复盘页</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await screen.findByText('薄弱知识点 TOP', {}, { timeout: 5000 })
    const rows = screen.getAllByRole('button', { name: /极限存在准则|中值定理/ })
    expect(rows).toHaveLength(2)

    fireEvent.click(rows[1])
    await waitFor(() => expect(screen.getByTestId('loc').textContent)
      .toBe('/error-review?kp_id=102&kp_name=%E4%B8%AD%E5%80%BC%E5%AE%9A%E7%90%86'))
  })
})

// ========================================================================= //
// 五、CodeBank 正向数据用例
//     入口归一化（toArr/toObj）只该在**缺键**时兜底，不该把真实数据吃掉；
//     上面的健壮性守卫只喂 null/reject，所以这里按后端真实壳再测一遍。
//     形状以 services/codebank_service.py 的 return 为准：
//       list_subjects → [{id,name,direction,question_count}]
//       list_questions → {total, items:[{id,title,subject,difficulty,tags,frequency,appear_years}]}
//       panorama → {subjects:[…], items:[{tag,subject,total,avg_frequency,hot}]}
//       exam_strategy → {top_questions:[…], by_subject:[{subject,count,avg_frequency}], by_direction:[…]}
// ========================================================================= //
describe('CodeBank：真实响应壳下三个页签都出内容', () => {
  const questionRow = {
    id: 7, title: '两数之和', subject: '数据结构', difficulty: 'easy',
    tags: ['数组'], frequency: 5, appear_years: [2024],
  }

  beforeEach(() => {
    apiMocks.offlineProbe.request.mockImplementation((p) => {
      if (p === '/codebank/subjects') {
        return Promise.resolve([{ id: 1, name: '数据结构', direction: '机试', question_count: 3 }])
      }
      if (p === '/codebank/panorama') {
        return Promise.resolve({
          subjects: ['数据结构'],
          items: [{ tag: '二叉树', subject: '数据结构', total: 2, avg_frequency: 4, hot: { title: '层序遍历' } }],
        })
      }
      if (p === '/codebank/questions') {
        return Promise.resolve({ total: 1, items: [questionRow] })
      }
      if (p === '/codebank/exam-strategy') {
        return Promise.resolve({
          top_questions: [questionRow],
          by_subject: [{ subject: '数据结构', count: 1, avg_frequency: 5 }],
          by_direction: [{ direction: '机试', count: 1 }],
        })
      }
      if (String(p).startsWith('/codebank/questions/')) {
        return Promise.resolve({
          ...questionRow, languages: ['cpp', 'python'], statement: '给一个数组和目标值',
          input_desc: 'n 与数组', output_desc: '两个下标', examples: [], hint: '', source: '',
        })
      }
      return Promise.resolve(null)
    })
  })

  it('全景 / 列表 / 考频 三页签各自渲染后端真实条目，且点行能开详情', async () => {
    const Comp = (await import('../v3/pages/CodeBank')).default
    const { crashes, result } = withCrashCapture(() => renderPage(Comp, '/codebank'))
    await settle(400)

    expect(crashes).toEqual([])
    expect(result.errors).toEqual([])
    // 科目行来自后端，不再是写死的「数学/数电/模电/信号/光学/408」
    expect(result.getByText(/1 个科目：数据结构/)).toBeTruthy()
    expect(result.getByText('二叉树')).toBeTruthy()
    expect(result.getByText(/最热：层序遍历/)).toBeTruthy()

    fireEvent.click(result.getByRole('tab', { name: /题库列表/ }))
    await settle(300)
    fireEvent.click(result.getByText('两数之和'))
    await settle(300)
    expect(result.getByText('给一个数组和目标值')).toBeTruthy()
    expect(result.getByText('cpp')).toBeTruthy()
    // 真实用户切页签前必须先关详情（弹层遮罩会吃掉背后的点击），测试走同一条路径。
    // v3 Dialog 头部的图标关闭与底部「关闭」同名，取第一个（图标按钮）即可。
    fireEvent.click(result.getAllByRole('button', { name: '关闭' })[0])
    await settle(100)

    fireEvent.click(result.getByRole('tab', { name: /考频分析/ }))
    await settle(300)
    expect(result.getAllByText('数据结构').length).toBeGreaterThan(0)
    // 断言必须锁定后端字段本身（题数与均考频分列渲染），而不是靠 /5/ 模糊撞上
    expect(result.getByText('1 题')).toBeTruthy()
    expect(result.getByText('均考频 5')).toBeTruthy()
  })
})
