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
