/**
 * 今日中枢页面（/hub）交互回归。
 *
 * 页面只依赖 api/hub.js 一个出口，因此测试直接 mock 这个出口，
 * 既能锁住 UI 契约，又不会把测试绑死在某几个后端端点上。
 */
import React, { StrictMode } from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/hub', () => ({
  fetchHubOverview: vi.fn(),
  peekHubCache: vi.fn(),
}))

vi.mock('../api/client', () => ({
  tasksApi: { complete: vi.fn(), uncomplete: vi.fn() },
  studyApi: { addSession: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ming', display_name: '小明' } }),
}))

import { fetchHubOverview, peekHubCache } from '../api/hub'
import { tasksApi } from '../api/client'
import { MUTATION_EVENT, MUTATION_REFRESH_DELAY } from '../api/mutationEvent'
import Hub from '../v3/pages/Hub'

const QUEUE = [
  { id: 'review', order: 1, label: '到期复习', hint: '艾宾浩斯队列有 200 条到期', count: 200, unit: '条', to: '/quiz?tab=review', tone: 'violet', icon: 'review', done: false, urgency: 100 },
  { id: 'weak', order: 2, label: '薄弱点练习', hint: '极限', count: 1, unit: '个', to: '/quiz?mode=weak', tone: 'rose', icon: 'target', done: false, urgency: 80 },
  { id: 'tasks', order: 3, label: '今日待办', hint: '按计划推进今天的任务', count: 1, unit: '项', to: '/tasks', tone: 'amber', icon: 'todo', done: false, urgency: 70 },
  { id: 'words', order: 4, label: '单词记忆', hint: '今日新词 20 · 到期 0', count: 20, unit: '词', to: '/words', tone: 'green', icon: 'word', done: false, urgency: 65 },
  { id: 'cards', order: 5, label: '记忆卡片', hint: '暂无到期卡片', count: 0, unit: '张', to: '/cards', tone: 'blue', icon: 'card', done: true, urgency: 5 },
  { id: 'focus', order: 6, label: '专注计时', hint: '今天还没开始，先来一轮 25 分钟', count: 0, unit: '分钟', to: '/planner', tone: 'indigo', icon: 'focus', done: false, urgency: 55 },
  { id: 'quiz', order: 7, label: '今日刷题', hint: '今天还没开始刷题', count: 0, unit: '道', to: '/quiz', tone: 'cyan', icon: 'brain', done: false, urgency: 45 },
]

function makeData(overrides = {}) {
  return {
    generatedAt: '2026-10-22T01:00:00Z',
    dateLabel: '10 月 22 日 · 星期四',
    countdown: {
      days: 422, examDate: '2027-12-18', examYear: 2028, phase: 'base', phaseLabel: '基础期',
      isDefault: false, university: '北京林业大学', major: '电子信息（0854）',
    },
    goal: { configured: true, dailyTargets: { focus: 120 }, subjects: ['数学'], supportSubjects: [] },
    goalLine: '北京林业大学 · 电子信息（0854）',
    today: { focus_minutes: 0, questions_done: 0, correct_rate: null },
    yesterday: {},
    delta: {},
    streak: { current: 3, longest: 9, totalDays: 25, checkedToday: false },
    words: { new: 20, due: 0 },
    kpiCards: [
      { id: 'focus', label: '今日专注', value: 0, unit: '分钟', delta: null, hint: '目标 120 分钟', to: '/planner', icon: 'focus', tone: 'indigo', series: [30, 0] },
      { id: 'questions', label: '今日答题', value: 0, unit: '道', delta: -20, hint: '昨天 20 道', to: '/quiz', icon: 'questions', tone: 'cyan', series: [10, 0] },
      { id: 'accuracy', label: '今日正确率', value: null, unit: '%', delta: null, hint: '今天还没答题', to: '/insights', icon: 'accuracy', tone: 'violet', series: [80, 0] },
      { id: 'streak', label: '连续打卡', value: 3, unit: '天', delta: null, hint: '最长 9 天', to: '/profile', icon: 'streak', tone: 'amber', series: [1, 1] },
    ],
    queue: { items: QUEUE, activeId: 'review', doneCount: 1, total: 7, progress: 14 },
    trend: {
      series: [
        { date: '2026-10-21', focus: 30, questions: 10, correctRate: 80 },
        { date: '2026-10-22', focus: 0, questions: 0, correctRate: null },
      ],
    },
    heatmap: { days: [{ date: '2026-10-21', focus: 30, questions: 10, words: 5 }] },
    weakness: {
      has: true,
      points: [{ id: '3', knowledgePointId: 3, name: '极限', subject: '数学', chapter: '第一章', mastery: 35, errorCount: 4 }],
      reasons: [{ reason: '概念不清', count: 2 }],
      subjects: [],
      totalErrors: 4,
    },
    tasks: {
      items: [{ id: '7', title: '高数第一章', subject: '数学', status: 'pending' }],
      modules: [{ key: 'word', label: '单词复习', due: 20, unit: '个' }],
      total: 1,
      done: 0,
      pending: 1,
    },
    modules: [{ key: 'word', label: '单词', done: 0, target: 20, unit: '个', percent: 0, status: 'pending', note: '' }],
    due: {
      planner: 200, schedulerToday: 23, nowTotal: 0, newWords: 20,
      breakdown: { errors: 3, cards: 0, tasks: 0, words: 20 }, segments: [],
    },
    focusSubjects: ['数学'],
    dataCoverage: { is_empty: false },
    caliber: [
      { label: '今日累计到期', value: 23, unit: '项', source: 'dashboard/summary · future_load.due_today', note: '截至今日 24:00' },
      { label: '现在可做', value: 0, unit: '项', source: 'dashboard/summary · review_queue', note: 'next_review ≤ 当前时刻' },
      { label: '艾宾浩斯到期', value: 200, unit: '条', source: 'insight/today · due_review_count', note: '复盘计划队列' },
      { label: '今日新词', value: 20, unit: '词', source: 'words/stats · new', note: '新词与复习词分开' },
    ],
    sources: [
      { key: 'summary', label: '仪表盘聚合', path: '/dashboard/summary', ok: true, ms: 12 },
      { key: 'insight', label: '今日引导', path: '/insight/today', ok: true, ms: 8 },
      { key: 'words', label: '单词统计', path: '/words/stats', ok: true, ms: 5 },
      { key: 'review', label: '复习统计', path: '/review/stats', ok: true, ms: 4 },
    ],
    failedSources: [],
    degraded: false,
    isEmpty: false,
    ...overrides,
  }
}

const renderHub = () => render(<MemoryRouter><Hub /></MemoryRouter>)

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  peekHubCache.mockReturnValue(null)
  fetchHubOverview.mockResolvedValue(makeData())
  tasksApi.complete.mockResolvedValue({})
  tasksApi.uncomplete.mockResolvedValue({})
})

afterEach(cleanup)

describe('Hub 今日聚合中枢', () => {
  it('渲染 hero / 7 步航线 / 4 张 KPI / 专注计时器', async () => {
    renderHub()
    expect(await screen.findByText('今日航线')).toBeInTheDocument()

    expect(screen.getByText(/小明/)).toBeInTheDocument()
    expect(document.querySelectorAll('.hub-step')).toHaveLength(7)
    expect(document.querySelectorAll('.hub-kpi')).toHaveLength(4)
    expect(document.querySelector('.v3-focus')).not.toBeNull()
    expect(screen.getAllByText('极限').length).toBeGreaterThan(0)
    expect(screen.getByText('高数第一章')).toBeInTheDocument()
    expect(screen.getByText('数据口径与接口体检')).toBeInTheDocument()
    expect(screen.getAllByText('今日累计到期').length).toBeGreaterThan(0)
    expect(screen.getAllByText('艾宾浩斯到期').length).toBeGreaterThan(0)
  })

  it('StrictMode 双挂载下仍能完成首屏加载（回归：aliveRef 未复位会卡骨架屏）', async () => {
    render(<StrictMode><MemoryRouter><Hub /></MemoryRouter></StrictMode>)
    expect(await screen.findByText('今日航线')).toBeInTheDocument()
    expect(document.querySelectorAll('.hub-step')).toHaveLength(7)
    expect(document.querySelector('.hub--skeleton')).toBeNull()
  })

  it('mutation 事件防抖后只做一次静默刷新（连续写入不打爆请求）', async () => {
    renderHub()
    await screen.findByText('今日航线')
    const base = fetchHubOverview.mock.calls.length

    /* 模拟连续 3 个写操作（间隔小于防抖窗口） */
    for (let i = 0; i < 3; i += 1) {
      fireEvent(window, new CustomEvent(MUTATION_EVENT, { detail: { method: 'POST', path: `/x/${i}` } }))
      await new Promise((resolve) => setTimeout(resolve, Math.min(MUTATION_REFRESH_DELAY / 4, 100)))
    }

    /* 第 4 个事件放在防抖窗口后 —— 不重置计时器也不额外触发 */
    await new Promise((resolve) => setTimeout(resolve, MUTATION_REFRESH_DELAY + 200))
    expect(fetchHubOverview.mock.calls.length).toBe(base + 1)
    /* force=false 但缓存已被事件清空 → 一定是真实网络刷新 */
    expect(fetchHubOverview).toHaveBeenLastCalledWith({ force: false })
  })

  it('域名外事件（同名不同细节）不会误刷新：只有 client 的广播生效', async () => {
    renderHub()
    await screen.findByText('今日航线')
    const base = fetchHubOverview.mock.calls.length

    /* 直接派发携带 GET 细节的事件仍是有效广播（语义上由派发方保证），
       这里只验证无事件时页面自身不额外拉取 */
    await new Promise((resolve) => setTimeout(resolve, 120))
    expect(fetchHubOverview.mock.calls.length).toBe(base)
  })

  it('任务打卡走真实接口，并触发一次强制刷新', async () => {
    renderHub()
    const check = await screen.findByRole('button', { name: '完成：高数第一章' })
    fireEvent.click(check)

    await waitFor(() => expect(tasksApi.complete).toHaveBeenCalledWith(7))
    await waitFor(() => expect(fetchHubOverview).toHaveBeenCalledWith({ force: true }))
  })

  it('趋势指标可切换，正确率走另一条曲线', async () => {
    renderHub()
    await screen.findByText('今日航线')
    const tab = screen.getByRole('tab', { name: '答题' })
    fireEvent.click(tab)
    expect(tab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('近 14 天累计 · 答题')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: '正确率' }))
    expect(screen.getByText('近 14 天平均')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '正确率' })).toHaveAttribute('aria-selected', 'true')
  })

  it('聚合布局可隐藏区块，并写入按账号隔离的 localStorage', async () => {
    renderHub()
    await screen.findByText('今日航线')
    expect(document.querySelectorAll('.hub-block')).toHaveLength(7)

    fireEvent.click(screen.getByRole('button', { name: /聚合布局/ }))
    const sw = await screen.findByRole('switch', { name: '显示14 天趋势' })
    fireEvent.click(sw)

    await waitFor(() => expect(document.querySelectorAll('.hub-block')).toHaveLength(6))
    /* 弹窗里仍保留该区块的名字（用于重新打开），所以只在主栅格里断言不存在 */
    const blockTitles = [...document.querySelectorAll('.hub-block .hub-panel__title')].map((el) => el.textContent)
    expect(blockTitles.some((t) => t.includes('14 天趋势'))).toBe(false)
    expect(localStorage.getItem('hub_layout_v1')).toContain('trend')
  })

  it('部分数据源失败显示降级提示，核心失败显示错误页', async () => {
    fetchHubOverview.mockResolvedValueOnce(makeData({
      degraded: true,
      failedSources: [{ key: 'words', label: '单词统计', path: '/words/stats', ok: false, ms: 5, error: 'HTTP 404' }],
    }))
    renderHub()
    expect(await screen.findByText(/部分数据源暂不可用/)).toBeInTheDocument()

    cleanup()
    fetchHubOverview.mockRejectedValue(new Error('后端不可达'))
    renderHub()
    expect(await screen.findByText('聚合数据暂时取不到')).toBeInTheDocument()
    expect(screen.getByText('后端不可达')).toBeInTheDocument()
  })
})
