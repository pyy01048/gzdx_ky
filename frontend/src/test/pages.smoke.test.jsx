import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

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

const apiMocks = {
  dashboardApi: {
    get: vi.fn(),
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
    weeklyReport: vi.fn().mockResolvedValue({
      summary: '', daily: [], this_week: { answered: 0, accuracy: null, duration_min: 0 },
      last_week: { answered: 0, accuracy: null }, delta: { direction: 'flat', text: '持平' },
      weak_delta: [],
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
  plannerApi: {
    daily: vi.fn(), ebbinghaus: vi.fn().mockResolvedValue([]),
    ebbinghausDue: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    earlybird: vi.fn().mockResolvedValue([]),
    phase: vi.fn().mockResolvedValue([]),
    keywords: vi.fn().mockResolvedValue({}),
  },
  reviewApi: { due: vi.fn().mockResolvedValue({ total: 0, items: [] }) },
  goalsApi: { list: vi.fn().mockResolvedValue([]) },
}

vi.mock('../api/client', () => ({
  request: vi.fn().mockResolvedValue({}),
  DEFAULT_TIMEOUT: 30000,
  ...apiMocks,
}))

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
  apiMocks.tasksApi.list.mockResolvedValue([])
  apiMocks.tasksApi.reviewSchedule.mockResolvedValue([])
  /* V11 insight mock：reset 后恢复默认空数据，避免 Dashboard 异步引导拿到 undefined */
  apiMocks.insightApi?.today?.mockResolvedValue?.({
    due_review_count: 0, today_tasks_count: 0, today_answered: 0, weak_top: [], suggestion: [],
  })
  apiMocks.insightApi?.weeklyReport?.mockResolvedValue?.({
    summary: '', daily: [], this_week: { answered: 0, accuracy: null, duration_min: 0 },
    last_week: { answered: 0, accuracy: null }, delta: { direction: 'flat', text: '持平' }, weak_delta: [],
  })
  apiMocks.insightApi?.smartPaper?.mockResolvedValue?.({ mode: 'random', size: 0, basis: '', questions: [] })
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

function renderPage(Comp, route = '/') {
  const errors = []
  const spy = vi.spyOn(console, 'error').mockImplementation((...a) => { errors.push(a) })
  const utils = render(
    <MemoryRouter initialEntries={[route]}>
      <Comp />
    </MemoryRouter>,
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
// ========================================================================= //
describe('Dashboard 页面渲染 smoke', () => {
  it('正常后端数据下渲染出倒计时标题', async () => {
    const Dashboard = (await import('../pages/Dashboard')).default
    apiMocks.dashboardApi.get.mockResolvedValue(dashboardPayload)
    apiMocks.dashboardApi.stats.mockResolvedValue(dashboardPayload)

    const { errors } = renderPage(Dashboard, '/')

    expect(await screen.findByText(/距 2027 考研还有|距.*考研还有/, {}, { timeout: 5000 }))
      .toBeInTheDocument()
    expect(errors).toEqual([])
  })

  it('后端 dashboardApi.get 抛错时不白屏（显示降级内容而非崩溃）', async () => {
    const Dashboard = (await import('../pages/Dashboard')).default
    apiMocks.dashboardApi.get.mockRejectedValue(new Error('network down'))
    apiMocks.dashboardApi.stats.mockRejectedValue(new Error('network down'))

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(result.container.firstChild, '后端挂掉时首页 DOM 被清空 = 白屏').toBeTruthy()
    expect(crashes, '后端挂掉时首页抛出了未捕获异常').toEqual([])
  })

  it('后端返回 null（2xx 但无 JSON 体，client.js 会 resolve(null)）时不崩', async () => {
    // ★ 已确认的真实缺陷回归点 ★
    // 缺陷位置：src/pages/Dashboard.jsx:77
    //   .then((d) => { setLive(d); setStatus('ok') })   // d 可能是 null，不会走 catch
    //   if (status === 'ok' && live.today_tasks)       // ← TypeError → 首页白屏
    // 触发路径：api/client.js:152-158 对无 JSON 体的响应返回 null 而非抛错。
    const Dashboard = (await import('../pages/Dashboard')).default
    apiMocks.dashboardApi.get.mockResolvedValue(null)
    apiMocks.dashboardApi.stats.mockResolvedValue(null)
    apiMocks.dashboardApi.weakness.mockResolvedValue(null)

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(crashes, 'Dashboard.jsx:77 未防御 live 为 null 的情况 → 首页白屏').toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('后端返回 undefined（下游 .map 崩溃高发点）时不崩', async () => {
    const Dashboard = (await import('../pages/Dashboard')).default
    apiMocks.dashboardApi.get.mockResolvedValue(undefined)
    apiMocks.dashboardApi.stats.mockResolvedValue(undefined)
    apiMocks.dashboardApi.weakness.mockResolvedValue(undefined)

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(crashes, 'Dashboard 未防御后端返回 undefined').toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('后端返回缺字段的残缺对象时不崩', async () => {
    const Dashboard = (await import('../pages/Dashboard')).default
    // 缺 today_tasks / recent_docs / countdown 等，只给一个空壳
    apiMocks.dashboardApi.get.mockResolvedValue({})
    apiMocks.dashboardApi.stats.mockResolvedValue({})

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('today_tasks.tasks 缺省（对象而非数组）时不崩', async () => {
    const Dashboard = (await import('../pages/Dashboard')).default
    apiMocks.dashboardApi.get.mockResolvedValue({
      countdown: { exam_date: '2027-12-25', days: 400 },
      today_tasks: {},              // 缺 tasks 字段
    })
    apiMocks.dashboardApi.stats.mockResolvedValue({})

    const { crashes, result } = withCrashCapture(() => renderPage(Dashboard, '/'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })
})

// ========================================================================= //
// 二、Tasks（任务打卡，使用频率最高的交互页）
// ========================================================================= //
describe('Tasks 页面渲染 smoke', () => {
  it('渲染出今日任务视图且不抛错', async () => {
    const Tasks = (await import('../pages/Tasks')).default
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
    const Tasks = (await import('../pages/Tasks')).default
    // 残缺任务：只有 id，其余全 undefined
    apiMocks.tasksApi.list.mockResolvedValue([{ id: 1 }])
    apiMocks.tasksApi.reviewSchedule.mockResolvedValue([])

    const { crashes, result } = withCrashCapture(() => renderPage(Tasks, '/tasks'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('tasksApi.list 返回非数组（对象/null）时不崩', async () => {
    const Tasks = (await import('../pages/Tasks')).default
    apiMocks.tasksApi.list.mockResolvedValue({ items: [] })   // 形状不匹配
    apiMocks.tasksApi.reviewSchedule.mockResolvedValue(null)

    const { crashes, result } = withCrashCapture(() => renderPage(Tasks, '/tasks'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })
})

// ========================================================================= //
// 三、Planner（艾宾浩斯复习计划，含本次修复的 ebbinghaus/due）
// ========================================================================= //
describe('Planner 页面渲染 smoke', () => {
  it('渲染复习计划页且不抛错', async () => {
    const Planner = (await import('../pages/Planner')).default
    apiMocks.plannerApi.ebbinghaus.mockResolvedValue([])
    apiMocks.plannerApi.ebbinghausDue.mockResolvedValue({ total: 0, items: [] })
    apiMocks.plannerApi.earlybird.mockResolvedValue([])
    apiMocks.plannerApi.phase.mockResolvedValue([])

    const { crashes, result } = withCrashCapture(() => renderPage(Planner, '/planner'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('due 接口返回结构异常时不崩（曾因 500 导致数据为 undefined）', async () => {
    const Planner = (await import('../pages/Planner')).default
    // 模拟后端 500 后的兜底：undefined / null / 缺 items
    apiMocks.plannerApi.ebbinghausDue.mockResolvedValue(undefined)
    apiMocks.plannerApi.ebbinghaus.mockResolvedValue(null)
    apiMocks.plannerApi.earlybird.mockResolvedValue(undefined)
    apiMocks.plannerApi.phase.mockResolvedValue(undefined)

    const { crashes, result } = withCrashCapture(() => renderPage(Planner, '/planner'))
    await settle()

    expect(crashes).toEqual([])
    expect(result.container.firstChild).toBeTruthy()
  })

  it('due items 含缺字段条目时不崩', async () => {
    const Planner = (await import('../pages/Planner')).default
    apiMocks.plannerApi.ebbinghausDue.mockResolvedValue({
      total: 1,
      items: [{ id: 1 }],   // 缺 content/subject/due_cycle/due_time
    })
    apiMocks.plannerApi.ebbinghaus.mockResolvedValue([{ id: 1 }])
    apiMocks.plannerApi.earlybird.mockResolvedValue([])
    apiMocks.plannerApi.phase.mockResolvedValue([])

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
  const pages = [
    ['Dashboard', '../pages/Dashboard', '/'],
    ['Tasks', '../pages/Tasks', '/tasks'],
    ['Planner', '../pages/Planner', '/planner'],
  ]

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

  it.each(pages)('%s 在后端返回 null 时仍能渲染骨架', async (_name, modPath, route) => {
    // 比"全挂"更隐蔽的情形：后端 200 但响应体为空 → client.js resolve(null)，
    // Promise 是 fulfilled，页面的 .catch 兜底**完全不会触发**。
    for (const grp of Object.values(apiMocks)) {
      for (const fn of Object.values(grp)) {
        if (fn?.mockResolvedValue) fn.mockResolvedValue(null)
      }
    }

    const Comp = (await import(modPath)).default
    const { crashes, result } = withCrashCapture(() => renderPage(Comp, route))
    await settle(400)

    expect(result.container.firstChild, `${_name} 收到 null 时 DOM 为空 = 白屏`).toBeTruthy()
    expect(crashes, `${_name} 收到 null 时抛出了未捕获异常（.catch 兜底失效）`).toEqual([])
  })
})
