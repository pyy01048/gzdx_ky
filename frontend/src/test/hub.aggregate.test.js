/**
 * 今日中枢数据层（api/hub.js）回归。
 *
 * 这里锁住的是「统一数据源」的硬约束，而不是实现细节：
 *   1) 科目去重：同一科目不同写法只出现一次，但展示名不被改写；
 *   2) 三种「到期」必须分开：今日累计 23 / 现在可做 0 / 艾宾浩斯 200，
 *      不允许相加成一个 223 的假总数；
 *   3) 航线排序由真实数据决定，done 状态也由数据推导；
 *   4) 部分接口失败可渲染，核心接口全挂才整页失败；
 *   5) 缓存、并发去重、force 刷新。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../api/client', () => ({
  dashboardApi: { summary: vi.fn() },
  insightApi: { today: vi.fn() },
  wordsApi: { stats: vi.fn() },
  reviewApi: { stats: vi.fn() },
}))

import { dashboardApi, insightApi, reviewApi, wordsApi } from '../api/client'
import {
  buildHubModel, clearHubCache, dedupeSubjects, deriveFocusQueue, fetchHubOverview,
  normalizeDue, peekHubCache, subjectKey,
} from '../api/hub'

const summary = {
  generated_at: '2026-10-22T01:00:00Z',
  countdown: {
    days: 422, exam_date: '2027-12-18', exam_year: 2028, phase: 'base',
    university: '北京林业大学', major: '电子信息（0854）', is_default: false,
  },
  goal: {
    configured: true,
    university: '北京林业大学',
    major: '电子信息（0854）',
    subjects: ['数学', ' 数学 ', '英语（一）'],
    support_subjects: ['政治'],
    daily_targets: { focus_minutes: 120, questions: 30, review_words: 50, new_words: 20 },
    score_targets: { total: 350 },
    targets_set: true,
  },
  kpi: {
    today: { focus_minutes: 0, questions_done: 0, questions_correct: 0, correct_rate: null, words_done: 0, tasks_done: 0 },
    yesterday: { focus_minutes: 40, questions_done: 20, questions_correct: 15, correct_rate: 75 },
    delta: { focus_minutes: -40, questions_done: -20, correct_rate_pp: -75 },
    streak: { current: 3, longest: 9, total_days: 25, checked_today: false },
  },
  today_tasks: {
    total: 1, pending: 1, done: 0, doing: 0,
    tasks: [{ id: 7, title: '高数第一章', subject: '数学', status: 'pending' }],
    modules: [{ module: 'word', label: '单词复习', due: 20, done: 0, unit: '个', status: 'pending', note: null }],
  },
  review_queue: { total: 0, cards: [], errors: [], tasks: [] },
  heatmap: {
    days: [
      { date: '2026-10-21', focus_minutes: 30, questions_done: 10, words_done: 5, is_effective: true },
      { date: '2026-10-22', focus_minutes: 0, questions_done: 0, words_done: 0, is_effective: false },
    ],
    levels: [0, 10, 30, 60],
    value_field: 'focus_minutes',
  },
  trend: {
    days: 14,
    series: [
      { date: '2026-10-21', focus_minutes: 30, questions_done: 10, questions_correct: 8, correct_rate: 80, words_done: 5, cards_done: 0, tasks_done: 1, is_effective: true },
      { date: '2026-10-22', focus_minutes: 0, questions_done: 0, questions_correct: 0, correct_rate: null, words_done: 0, cards_done: 0, tasks_done: 0, is_effective: false },
    ],
    week_focus_minutes: 30,
    weekly_completed_tasks: 1,
    subject_durations: { 数学: 30 },
  },
  weakness: {
    has_weakness: true,
    total_errors: 4,
    suggestion: '',
    weak_points: [{ knowledge_point_id: 3, name: '极限', chapter: '第一章', subject: '数学', error_count: 4, mastery: 35 }],
    weak_subjects: [{ subject: '数学', count: 4, level: 'high' }],
    common_reasons: [{ reason: '概念不清', count: 2 }],
  },
  module_progress: [
    { module: 'word', label: '单词', done: 0, target: 20, unit: '个', percent: 0, status: 'pending', note: '' },
    { module: 'question', label: '题库', done: 0, target: null, unit: '道', percent: null, status: 'not_tracked', note: '题库没有排程字段' },
  ],
  future_load: {
    due_today: { errors: 3, flashcards: 0, tasks: 0, words: 20, total: 23 },
    due_tomorrow: { errors: 3, flashcards: 0, tasks: 0, words: 20, total: 23 },
    due_this_week: { errors: 3, flashcards: 0, tasks: 0, words: 20, total: 23 },
    rule: '累计到期量（含此前未清的复习债）',
  },
  data_coverage: { is_empty: false },
  errors: { active: 3 },
}

const insight = {
  countdown: { days: 422 },
  due_review_count: 200,
  today_answered: 0,
  today_correct: 0,
  weak_top: [{ knowledge_point_id: 3, kp: '极限', subject: '数学', error_count: 4 }],
  suggestions: [
    { icon: 'review', label: '到期复习', count: 200, to: '/quiz?tab=review', hint: '艾宾浩斯队列有 200 条到期' },
    { icon: 'target', label: '薄弱点练习', count: 1, to: '/quiz?mode=weak', hint: '极限' },
  ],
}

const words = { due_today: 0, learning: 0, mastered: 0, new: 20, reviewing: 0, total: 20 }
const review = { active_errors: 3, due_errors: 0, graduated_errors: 0, today_reviews: 0, total_reviews: 0 }

const sources = [
  { key: 'summary', label: '仪表盘聚合', path: '/dashboard/summary', ok: true, ms: 12 },
  { key: 'insight', label: '今日引导', path: '/insight/today', ok: true, ms: 8 },
  { key: 'words', label: '单词统计', path: '/words/stats', ok: true, ms: 5 },
  { key: 'review', label: '复习统计', path: '/review/stats', ok: true, ms: 4 },
]

beforeEach(() => {
  clearHubCache()
  vi.clearAllMocks()
  dashboardApi.summary.mockResolvedValue(summary)
  insightApi.today.mockResolvedValue(insight)
  wordsApi.stats.mockResolvedValue(words)
  reviewApi.stats.mockResolvedValue(review)
})

describe('科目口径', () => {
  it('subjectKey 忽略空白/括号/分隔符，但不改展示名', () => {
    expect(subjectKey(' 数学（一） ')).toBe('数学一')
    expect(subjectKey('英语 (一)')).toBe('英语一')
    expect(subjectKey('')).toBe('')
  })

  it('dedupeSubjects 只保留首次写法', () => {
    expect(dedupeSubjects(['数学', ' 数学 ', '数学', '英语（一）', '英语(一)'])).toEqual(['数学', '英语（一）'])
    expect(dedupeSubjects([{ subject: '数学' }, { subject: '数学' }, { subject: '政治' }])).toEqual(['数学', '政治'])
  })
})

describe('到期口径对账', () => {
  it('三种到期分开计数，绝不合并成一个总数', () => {
    const due = normalizeDue({ summary, insight, words, review })
    expect(due.planner).toBe(200)          // 艾宾浩斯计划
    expect(due.schedulerToday).toBe(23)    // 截至今日 24:00 的累计
    expect(due.nowTotal).toBe(0)           // next_review ≤ now
    expect(due.newWords).toBe(20)
    expect(due.breakdown).toEqual({ errors: 3, cards: 0, tasks: 0, words: 20 })
    /* 关键约束：没有 total=223 这种把计划队列算进复习债的字段 */
    expect(due.total).toBeUndefined()
  })

  it('review_queue 缺失时 nowTotal 为 null，而不是伪造 0', () => {
    const due = normalizeDue({ summary: { ...summary, review_queue: null }, insight, words, review })
    expect(due.nowTotal).toBeNull()
  })
})

describe('buildHubModel', () => {
  it('把四个聚合端点组装成完整页面模型', () => {
    const model = buildHubModel({ summary, insight, words, review, sources })

    expect(model.countdown.days).toBe(422)
    expect(model.countdown.phaseLabel).toBe('基础期')
    expect(model.goal.subjects).toEqual(['数学', '英语（一）'])
    expect(model.goalLine).toBe('北京林业大学 · 电子信息（0854）')

    expect(model.kpiCards.map((c) => c.id)).toEqual(['focus', 'questions', 'accuracy', 'streak'])
    expect(model.kpiCards[0]).toMatchObject({ value: 0, unit: '分钟' })
    expect(model.kpiCards[2].value).toBeNull()
    expect(model.kpiCards[3].value).toBe(3)

    expect(model.tasks.items[0]).toMatchObject({ id: '7', title: '高数第一章' })
    expect(model.weakness.points[0]).toMatchObject({ name: '极限', mastery: 35 })
    expect(model.queue.items[0].id).toBe('review')
    expect(model.queue.activeId).toBe('review')
    expect(model.focusSubjects).toEqual(['数学', '英语（一）', '政治'])

    expect(model.caliber.find((r) => r.label === '今日累计到期').value).toBe(23)
    expect(model.caliber.find((r) => r.label === '现在可做').value).toBe(0)
    expect(model.caliber.find((r) => r.label === '艾宾浩斯到期').value).toBe(200)
    expect(model.degraded).toBe(false)
  })

  it('只有 insight 时也能渲染（部分接口缺失不崩）', () => {
    const model = buildHubModel({
      insight,
      sources: [{ ...sources[0], ok: false, error: 'HTTP 500' }, sources[1]],
    })
    expect(model.countdown.days).toBe(422)
    expect(model.tasks.total).toBe(0)
    expect(model.weakness.points[0].name).toBe('极限')
    expect(model.kpiCards).toHaveLength(4)
    expect(model.degraded).toBe(true)
    expect(model.failedSources.map((s) => s.key)).toEqual(['summary'])
  })

  it('全空入参返回零态模型而不是抛错', () => {
    const model = buildHubModel({})
    expect(model.countdown.days).toBeNull()
    expect(model.queue.items).toHaveLength(7)
    expect(model.queue.doneCount).toBe(5) // 卡片/待办/单词/复习/薄弱点均无欠账
  })
})

describe('deriveFocusQueue', () => {
  const base = {
    due: { planner: 200, newWords: 20, breakdown: { errors: 3, cards: 0, tasks: 0, words: 20 } },
    tasks: { pending: 3 },
    weakness: { points: [{ id: '1' }, { id: '2' }] },
    words: { due_today: 0 },
    today: { focus_minutes: 0, questions_done: 0 },
  }

  it('有欠账时按 复习 → 薄弱点 → 任务 → 单词 → 专注 → 刷题 排序', () => {
    const q = deriveFocusQueue(base)
    expect(q.items.map((i) => i.id)).toEqual(['review', 'weak', 'tasks', 'words', 'focus', 'quiz', 'cards'])
    expect(q.activeId).toBe('review')
    expect(q.items.find((i) => i.id === 'review').count).toBe(200)
  })

  it('欠账清空后自动把「专注」推到当前步骤', () => {
    const q = deriveFocusQueue({
      ...base,
      due: { planner: 0, newWords: 0, breakdown: { errors: 0, cards: 0, tasks: 0, words: 0 } },
      tasks: { pending: 0 },
      weakness: { points: [] },
    })
    expect(q.activeId).toBe('focus')
    expect(q.items.find((i) => i.id === 'review').done).toBe(true)
    expect(q.items.find((i) => i.id === 'weak').done).toBe(true)
    expect(q.progress).toBeGreaterThan(50)
  })
})

describe('fetchHubOverview', () => {
  it('并发去重 + TTL 缓存 + force 跳过缓存', async () => {
    const [a, b] = await Promise.all([fetchHubOverview(), fetchHubOverview()])
    expect(dashboardApi.summary).toHaveBeenCalledTimes(1)
    expect(a.countdown.days).toBe(422)
    expect(b.countdown.days).toBe(422)

    const cached = await fetchHubOverview()
    expect(cached.fromCache).toBe(true)
    expect(dashboardApi.summary).toHaveBeenCalledTimes(1)

    await fetchHubOverview({ force: true })
    expect(dashboardApi.summary).toHaveBeenCalledTimes(2)
    expect(peekHubCache()).not.toBeNull()
  })

  it('单词接口失败只降级，不影响整页', async () => {
    wordsApi.stats.mockRejectedValue(new Error('HTTP 404'))
    const model = await fetchHubOverview()
    expect(model.degraded).toBe(true)
    expect(model.failedSources.map((s) => s.key)).toEqual(['words'])
    expect(model.kpiCards[0].value).toBe(0)
  })

  it('summary 与 insight 同时失败才整页失败，且不写缓存', async () => {
    dashboardApi.summary.mockRejectedValue(new Error('boom'))
    insightApi.today.mockRejectedValue(new Error('boom'))
    await expect(fetchHubOverview()).rejects.toThrow('boom')
    expect(peekHubCache()).toBeNull()
  })
})
