import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'

/* ------------------------------------------------------------------ *
 * E2: 核心路由 smoke test
 * 目标：关键路由（首页 / 择校中心 / 院校库）在 jsdom 下渲染不抛错。
 * 策略：mock echarts 与后端 API，避免网络与 canvas 依赖。
 * ------------------------------------------------------------------ */

// 1) mock echarts 系列模块（jsdom 无 canvas，EChart 仅需 stub）
vi.mock('echarts/core', () => ({
  use: vi.fn(),
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    clear: vi.fn(),
    showLoading: vi.fn(),
    hideLoading: vi.fn(),
  })),
}))
vi.mock('echarts/charts', () => ({
  BarChart: {}, LineChart: {}, ScatterChart: {}, PieChart: {}, RadarChart: {}, MapChart: {},
}))
vi.mock('echarts/components', () => ({
  TitleComponent: {}, TooltipComponent: {}, LegendComponent: {}, GridComponent: {},
  PolarComponent: {}, RadarComponent: {}, GeoComponent: {}, VisualMapComponent: {},
  DatasetComponent: {}, TransformComponent: {},
}))
vi.mock('echarts/features', () => ({ LabelLayout: {}, UniversalTransition: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

// 2) mock 后端 API（返回空数据，避免真实网络请求）
vi.mock('../api/client', () => ({
  api: { get: vi.fn().mockResolvedValue({ data: {} }) },
  dashboardApi: {
    get: vi.fn().mockResolvedValue({
      countdown: { exam_date: '2027-12-25', days: 400 },
      today_tasks: { tasks: [] },
      week_minutes: 0,
      review_due: 0,
      errors_today: 0,
      recent_docs: [],
    }),
  },
  tasksApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn().mockResolvedValue({}), update: vi.fn().mockResolvedValue({}), remove: vi.fn().mockResolvedValue({}) },
  errorsApi: { list: vi.fn().mockResolvedValue([]), resolve: vi.fn().mockResolvedValue({}) },
  flashcardsApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn().mockResolvedValue({}) },
}))

vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: {
    stats: vi.fn().mockResolvedValue({
      school_count: 0, major_count: 0, admission_records: 0,
      scoreline_records: 0, subject_count: 0,
    }),
    subjects: vi.fn().mockResolvedValue([]),
    schools: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    listSchools: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    scatter: vi.fn().mockResolvedValue({ items: [] }),
    // 院校库页在首屏并行调用以下接口，缺失 mock 会让页面进入错误态，
    // 导致「院校数据库」标题永远不渲染（曾表现为 5s 超时），故必须补齐。
    hot: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    dashboardAnalysis: vi.fn().mockResolvedValue(null),
    schoolMajors: vi.fn().mockResolvedValue([]),
    // 首页「院校公告」栏（NoticeBoard）调用：跨校聚合 + 近期更新概览
    notices: vi.fn().mockResolvedValue({ items: [], stats: { total: 0, school_count: 0, by_type: {} } }),
    noticeUpdates: vi.fn().mockResolvedValue({ days: 7, total_schools: 0, total_notices: 0, schools: [] }),
    // 全局未读角标：Layout 侧边栏「院校数据中心」模块任何页面都会渲染 NoticeUnreadBadge
    // → useUnreadNotices() 在首屏调用 noticeUnreadStats()。mock 缺失该方法会抛
    // "noticeUnreadStats is not a function" 未捕获异常（vitest 报 unhandled error）。
    // 返回字段需覆盖 useUnreadNotices 读取的快照键，否则角标拿不到 unread。
    noticeUnreadStats: vi.fn().mockResolvedValue({
      total: 0, unread: 0, read: 0, starred: 0,
      important_unread: 0, important_total: 0, urgent_unread: 0,
      by_type: {}, by_school: {},
    }),
    noticeList: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }),
  },
}))

function renderApp(route) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>
  )
}

describe('核心路由 smoke test', () => {
  it('首页 Dashboard 渲染不报错（含倒计时标题）', async () => {
    renderApp('/')
    // React.lazy 懒加载：等待真实页面挂载
    expect(await screen.findByText(/距 2027 考研还有/, {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('择校中心 /kaoyan 渲染不报错', async () => {
    renderApp('/kaoyan')
    expect(await screen.findByText('考研择校数据中心', {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('院校库 /kaoyan/schools 渲染不报错', async () => {
    renderApp('/kaoyan/schools')
    expect(await screen.findByText('院校数据库', {}, { timeout: 5000 })).toBeInTheDocument()
  })
})
