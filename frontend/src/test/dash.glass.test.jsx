/**
 * 仪表盘玻璃化增量回归（P1）：
 *   1) 科目口径与 /hub 统一 —— 重复/变体写法（'数学'、'数学 '、'数学（一）'）
 *      在目标卡里只出现一次，且不改写展示名；
 *   2) 页头新增「今日中枢」直达按钮，点击后真正路由到 /hub；
 *   3) KPI 控制台仍是 6 格（新样式层不改结构）。
 */
import React from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { makeSummary } from './dashboardSummary.fixture'

vi.mock('../api/client', async (importOriginal) => {
  const real = await importOriginal()
  return {
    ...real,
    dashboardApi: { ...real.dashboardApi, summary: vi.fn() },
    insightApi: { ...real.insightApi, today: vi.fn() },
  }
})

vi.mock('../api/kaoyanApi', async (importOriginal) => {
  const real = await importOriginal()
  return {
    ...real,
    kaoyanApi: { ...real.kaoyanApi, noticesFeed: vi.fn().mockResolvedValue({ items: [] }) },
  }
})

import { dashboardApi, insightApi } from '../api/client'
import Dashboard from '../v3/pages/Dashboard'

const summary = makeSummary({
  countdown: {
    days: 422, days_left: 422, exam_date: '2027-12-18', exam_year: 2028,
    phase: 'base', is_official: false, source: '', university: '北京林业大学',
    major: '电子信息（0854）', total_score_target: 350, is_passed: false,
    is_default: false, signup_hint: null,
  },
  goal: {
    configured: true,
    university: '北京林业大学',
    major: '电子信息（0854）',
    /* 故意混入：尾部空格、全角/半角括号变体 —— 与 /hub 的 subjectKey 口径一致 */
    subjects: ['数学', '数学 ', '数学（一）', '英语（一）', '英语 (一)'],
    support_subjects: ['政治'],
    score_targets: { total: 350, politics: null, english: null, math: null, major: null },
    daily_targets: { focus_minutes: 120, new_words: 20, review_words: 50, questions: 30 },
    targets_set: true,
    recent_score_lines: [{ year: '2026', total_line: 340 }, { year: '2025', total_line: 330 }],
  },
})

const renderDash = () => render(
  <MemoryRouter initialEntries={['/']}>
    <Routes>
      <Route path="*" element={<Dashboard />} />
      <Route path="/hub" element={<div data-testid="hub-stub">今日中枢页面桩</div>} />
    </Routes>
  </MemoryRouter>,
)

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  dashboardApi.summary.mockResolvedValue(summary)
  insightApi.today.mockResolvedValue({
    countdown: { days: 422 }, due_review_count: 0, today_tasks_count: 0,
    today_answered: 0, today_correct: 0, weak_top: [], suggestions: [],
  })
})

afterEach(cleanup)

describe('Dashboard 玻璃化增量', () => {
  it('目标卡科目与 /hub 同口径：变体去重且不改写展示名', async () => {
    renderDash()
    await screen.findByText('今日中枢')

    expect(dashboardApi.summary).toHaveBeenCalledTimes(1)
    const chips = [...document.querySelectorAll('.v3-dash-goal__subjects .v3-chip')].map((el) => el.textContent.trim())
    expect(chips).toEqual(['数学', '数学（一）', '英语（一）'])
  })

  it('页头「今日中枢」按钮可直达 /hub', async () => {
    renderDash()
    fireEvent.click(await screen.findByRole('button', { name: /今日中枢/ }))
    expect(await screen.findByTestId('hub-stub')).toBeInTheDocument()
  })

  it('KPI 控制台保持 6 格结构', async () => {
    renderDash()
    await screen.findByText('今日中枢')
    expect(document.querySelectorAll('.v3-dash-kpi__cell')).toHaveLength(6)
  })
})
