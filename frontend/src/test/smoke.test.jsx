import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
/* 必须在 App 之前导入：vi.mock 工厂在 App 的依赖图求值时就要读到这个常量 */
import { summaryPayload } from './dashboardSummary.fixture'
import App from '../App'

/* ------------------------------------------------------------------ *
 * E2: 核心路由 smoke test
 * 目标：关键路由（首页 / 择校中心 / 院校库）在 jsdom 下渲染不抛错。
 * 策略：mock echarts 与后端 API，避免网络与 canvas 依赖。
 * ------------------------------------------------------------------ */

// 1) mock echarts 系列模块（jsdom 无 canvas，EChart 仅需 stub）
vi.mock('echarts/core', () => ({
  use: vi.fn(),
  registerMap: vi.fn(),
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
vi.mock('../api/client', async (importOriginal) => ({
  // 派生真实模块的导出清单：client.js 新增导出（如 fetchAllPages）不必再回来补枚举，
  // 否则页面一 import 就报 "No export is defined on the mock"。
  ...(await importOriginal()),
  favoritesApi: {
    list: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    add: vi.fn().mockResolvedValue({ ok: true, id: 1 }),
    check: vi.fn().mockResolvedValue({ favorited: false, id: null }),
    toggle: vi.fn().mockResolvedValue({ favorited: false }),
    remove: vi.fn().mockResolvedValue({ ok: true }),
  },
  growthApi: { timeline: vi.fn().mockResolvedValue({ days: 30, streak_days: 0, active_days: 0, timeline: [], subject_breakdown: [] }) },
  // 页面有直接 request('/quality/...') 的调用（院校库覆盖率），缺失会让整页进错误态
  request: vi.fn().mockResolvedValue(null),
  api: { get: vi.fn().mockResolvedValue({ data: {} }) },
  /* RequireAuth 首屏读 /auth/me：以管理员身份进入，才能覆盖 /subjects、/kaoyan/import 等管理路由 */
  authApi: {
    status: vi.fn().mockResolvedValue({ enabled: true }),
    me: vi.fn().mockResolvedValue({
      id: 1, username: 'admin', display_name: null, role: 'admin', is_active: true,
      must_change_password: false, last_login_at: null, created_at: null,
    }),
    refresh: vi.fn().mockResolvedValue({}),
    login: vi.fn().mockResolvedValue({}),
    logout: vi.fn().mockResolvedValue({ success: true }),
    changePassword: vi.fn().mockResolvedValue({}),
  },
  dashboardApi: {
    get: vi.fn().mockResolvedValue({
      countdown: { exam_date: '2027-12-25', days: 400 },
      today_tasks: { tasks: [] },
      week_minutes: 0,
      review_due: 0,
      errors_today: 0,
      recent_docs: [],
    }),
    // #13：Dashboard 首屏只请求 summary（GET /api/dashboard/summary），
    // 缺这个 mock 会让整页崩溃 → 用例红。契约形状见 dashboardSummary.fixture.js。
    summary: vi.fn().mockResolvedValue(summaryPayload),
    // sync.js 的 countdown 域加载器会单独调用该端点
    countdown: vi.fn().mockResolvedValue({ exam_date: '2027-12-25', days: 400, is_default: false }),
    // 旧端点保留给其它调用方；Dashboard 已不再单独请求它
    reviewQueue: vi.fn().mockResolvedValue(null),
  },
  // 科目配置单一来源（hooks/useSubjectConfig）：Analysis / Pan / Planner 首屏都会读
  goalsApi: {
    subjects: vi.fn().mockResolvedValue({
      exam_subjects: ['数学', '英语', '政治', '数字电子技术'],
      support_subjects: ['计算机学科专业基础408'],
      all_known: ['数学', '英语', '政治', '数字电子技术', '计算机学科专业基础408'],
      using_default: true,
    }),
  },
  tasksApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn().mockResolvedValue({}), update: vi.fn().mockResolvedValue({}), remove: vi.fn().mockResolvedValue({}) },
  errorsApi: { list: vi.fn().mockResolvedValue([]), resolve: vi.fn().mockResolvedValue({}) },
  flashcardsApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn().mockResolvedValue({}) },
  /* V11 学习洞察（Dashboard 引用） */
  insightApi: {
    today: vi.fn().mockResolvedValue({ due_review_count: 0, today_tasks_count: 0, today_answered: 0, weak_top: [], suggestion: [] }),
    weeklyReport: vi.fn().mockResolvedValue({ summary: '', daily: [], this_week: { answered: 0, correct: 0, accuracy: null, duration: 0 }, last_week: { answered: 0, correct: 0, accuracy: null, duration: 0 }, answered_delta: null }),
    smartPaper: vi.fn().mockResolvedValue({ mode: 'random', size: 0, basis: '', questions: [] }),
  },
  /* 科目管理页（/subjects）首屏只读 taxonomy.subjects */
  taxonomyApi: {
    subjects: vi.fn().mockResolvedValue([]),
    createSubject: vi.fn().mockResolvedValue({}),
    updateSubject: vi.fn().mockResolvedValue({}),
    removeSubject: vi.fn().mockResolvedValue({}),
  },
  /* 学习画像页（/profile）首屏读 analysis.profile；形状以
     services/learner_profile.py 的 return 为准（不是"看起来像"的骨架）：
     knowledge_points 是 {total,unlearned,weak,mastered,labels} **对象**，
     review_queue 是 {scheduled,overdue,due_today,no_schedule}。
     此前写成 knowledge_points: [] —— [ ].total 是 undefined，三态卡整块
     永不渲染，等于这条用例只测了"不崩"，从没测过那个卡片。 */
  analysisApi: {
    profile: vi.fn().mockResolvedValue({
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
      suggestions: [],
    }),
  },
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
    // 首页「今日公告」栏（Dashboard useEffect 调用 kaoyanApi.noticesFeed）。
    // 0bef498 起 Dashboard 调用该方法，mock 缺失会抛 TypeError 被 ErrorBoundary
    // 捕获 → 整页降级 → 本用例 5s 超时（存量缺口，此处补齐）。
    noticesFeed: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 }),
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
    // 采集中心页（/kaoyan/import）首屏调用：缺失会让 useEffect 里直接抛 TypeError。
    noticeTypeStats: vi.fn().mockResolvedValue({ items: [], by_type: {} }),
    collectionRuns: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }),
    refresh: vi.fn().mockResolvedValue({ ok: true }),
    dataYears: vi.fn().mockResolvedValue({ items: [] }),
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
    // React.lazy 懒加载：后续每个页面在 jsdom 里要跑完 v3 依赖图 + 多次 settle，
    // 5s 是旧页面的预算；这里放宽到 15s，断言的仍是真实页面文案而不是骨架。
    // 年份来自 summary.countdown.exam_year，不在前端猜。
    expect(await screen.findByText(/2027 考研初试还有/, {}, { timeout: 15000 })).toBeInTheDocument()
  }, 20000)

  /* 2026-10-19 信息架构调整（navConfig.MODULES 的 school 组）：
     /kaoyan 模块主页已由「择校数据中心」改为「院校库」，数据中心降为 /kaoyan/guide。
     旧断言跟着旧 IA 走，页面本身没坏。 */
  it('院校库 /kaoyan 渲染不报错', async () => {
    renderApp('/kaoyan')
    expect(await screen.findByRole('heading', { name: '院校库', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
  })

  /* 空库口径（上面 kaoyanApi.stats mock 就是全 0 + subjects 为空，即真实清库后的状态）：
     页面不能摆一排 0 冒充数据中心，也不许宣称「多年份 · 多学科」——
     必须给出导入入口。这是「没有数据时框架也要能用」的验收点。 */
  it('择校数据中心：库为空时显示导入空态而非 0 值统计卡', async () => {
    renderApp('/kaoyan/guide')
    expect(await screen.findByText('数据尚未导入', {}, { timeout: 15000 })).toBeInTheDocument()
    expect(screen.getByText('去导入择校数据')).toBeInTheDocument()
    expect(screen.queryByText('院校数')).not.toBeInTheDocument()
    expect(screen.queryByText(/多年份 · 多学科/)).not.toBeInTheDocument()
  }, 20000)

  it('院校库 /kaoyan/schools 渲染不报错', async () => {
    renderApp('/kaoyan/schools')
    expect(await screen.findByRole('heading', { name: '院校库', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
  })

  /* 散点图与分数分析曾被改成「重定向 + 查询参数」，而目标页不读那个参数，
     点导航「招生散点图」实际看到热力图。恢复直连后钉住落点，防止再退回去。 */
  it('招生散点图 /kaoyan/scatter 落在散点页而不是热力图', async () => {
    renderApp('/kaoyan/scatter')
    expect(await screen.findByRole('heading', { name: '招生人数分布', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText('区域择校热力图')).not.toBeInTheDocument()
  })

  it('分数线数据 /kaoyan/analysis 落在分数分析页而不是院校列表', async () => {
    renderApp('/kaoyan/analysis')
    expect(await screen.findByText('分数分析', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText('院校数据库')).not.toBeInTheDocument()
  })

  /* 旧管理路径书签必须重定向进 /admin 壳（带侧栏），而不是 404 或弹回首页 */
  it('旧路径 /kaoyan/import 重定向到 /admin/schools 采集中心', async () => {
    renderApp('/kaoyan/import')
    expect(await screen.findByRole('heading', { name: '采集中心' }, { timeout: 15000 })).toBeInTheDocument()
    expect(document.querySelector('.v3-admin-nav__item.is-active')?.textContent).toContain('院校数据管理')
  }, 20000)

  /* /subjects、/profile 曾整段被一条没闭合的 JSX 注释吞掉，路由不存在 → 点导航被
     兜底路由弹回首页；择校 AI 问答则重定向到 /assistant?scene=kaoyan，而 Assistant
     不读 scene，院校库口径的问答页没人引用。三条都钉住落点。 */
  it('择校 AI 问答 /kaoyan/assistant 落在择校问答页', async () => {
    renderApp('/kaoyan/assistant')
    expect(await screen.findByText('择校 AI 助手', {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('旧路径 /subjects 重定向到 /admin/subjects 科目管理页', async () => {
    renderApp('/subjects')
    expect(await screen.findByRole('heading', { name: '科目管理' }, { timeout: 15000 })).toBeInTheDocument()
    expect(document.querySelector('.v3-admin-nav__item.is-active')?.textContent).toContain('科目管理')
  }, 20000)

  it('/admin 默认落在数据中心', async () => {
    renderApp('/admin')
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '数据中心' })).toBeInTheDocument()
      expect(document.querySelector('.v3-admin-nav__item.is-active')?.textContent).toContain('数据中心')
    }, { timeout: 15000 })
  }, 20000)

  it('学习画像 /profile 落在画像页而不是被弹回首页', async () => {
    renderApp('/profile')
    expect(await screen.findByRole('heading', { name: '学习画像' }, { timeout: 15000 })).toBeInTheDocument()
  }, 20000)
})
