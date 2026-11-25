import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { todayStr } from '../utils/date'
import useStore from '../store/useStore'

const TODAY = todayStr()
const TOMORROW_DATE = new Date(`${TODAY}T00:00:00`)
TOMORROW_DATE.setDate(TOMORROW_DATE.getDate() + 1)
const TOMORROW = `${TOMORROW_DATE.getFullYear()}-${String(TOMORROW_DATE.getMonth() + 1).padStart(2, '0')}-${String(TOMORROW_DATE.getDate()).padStart(2, '0')}`
const DAY_AFTER_DATE = new Date(`${TOMORROW}T00:00:00`)
DAY_AFTER_DATE.setDate(DAY_AFTER_DATE.getDate() + 1)
const DAY_AFTER = `${DAY_AFTER_DATE.getFullYear()}-${String(DAY_AFTER_DATE.getMonth() + 1).padStart(2, '0')}-${String(DAY_AFTER_DATE.getDate()).padStart(2, '0')}`

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    plannerApi: {
      ...actual.plannerApi,
      getDaily: vi.fn(),
      saveDaily: vi.fn(),
      getMonth: vi.fn(),
      getWeek: vi.fn(),
      listEbbinghaus: vi.fn().mockResolvedValue([]),
      listEarlyBird: vi.fn().mockResolvedValue([]),
      listPhase: vi.fn().mockResolvedValue([]),
      getPhaseReviews: vi.fn().mockResolvedValue({ reviews: [], total: 0 }),
    },
    goalsApi: {
      ...actual.goalsApi,
      subjects: vi.fn().mockResolvedValue({
        exam_subjects: ['数学', '英语', '政治'],
        support_subjects: [],
        all_known: ['数学', '英语', '政治'],
        using_default: true,
      }),
    },
  }
})

import { plannerApi } from '../api/client'
import Planner from '../v3/pages/Planner'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function dailyPlan(date, title) {
  return {
    date,
    days_to_exam: null,
    exists: true,
    tasks: [{ id: title, title, subject: '数学', duration: 25, completed: false, subtasks: [] }],
    timeline: [],
    score: 0,
    summary: '',
  }
}

const renderPlanner = () => render(<MemoryRouter><Planner /></MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useStore.setState({ tasks: [], countdown: null, settings: { ...useStore.getState().settings, examDate: '' } })
  plannerApi.saveDaily.mockResolvedValue({ ok: true })
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

describe('Planner 加载代际', () => {
  it('连续切换日期后只接受最新响应，旧日期任务不覆盖新日期草稿', async () => {
    plannerApi.getDaily.mockResolvedValueOnce(dailyPlan(TODAY, '初始日期任务'))
    const staleRequest = deferred()
    const latestRequest = deferred()
    plannerApi.getDaily.mockImplementation((date) => {
      if (date === TOMORROW) return staleRequest.promise
      if (date === DAY_AFTER) return latestRequest.promise
      return Promise.resolve(dailyPlan(date, '兜底任务'))
    })

    renderPlanner()
    await screen.findByText('初始日期任务')
    fireEvent.change(screen.getByLabelText('计划日期'), { target: { value: TOMORROW } })
    await waitFor(() => expect(plannerApi.getDaily).toHaveBeenCalledWith(TOMORROW))
    fireEvent.change(screen.getByLabelText('计划日期'), { target: { value: DAY_AFTER } })
    await waitFor(() => expect(plannerApi.getDaily).toHaveBeenCalledWith(DAY_AFTER))

    await act(async () => { latestRequest.resolve(dailyPlan(DAY_AFTER, '最新日期任务')) })
    expect(await screen.findByText('最新日期任务')).toBeInTheDocument()

    await act(async () => { staleRequest.resolve(dailyPlan(TOMORROW, '过期日期任务')) })
    expect(screen.getByText('最新日期任务')).toBeInTheDocument()
    expect(screen.queryByText('过期日期任务')).not.toBeInTheDocument()
  })
})

describe('Planner 保存串行与草稿保护', () => {
  it('手动保存响应不回灌草稿，保存期间的新编辑保留且不触发 reload', async () => {
    plannerApi.getDaily.mockResolvedValue(dailyPlan(TODAY, '任务A'))
    const saveRequest = deferred()
    plannerApi.saveDaily.mockReturnValue(saveRequest.promise)

    renderPlanner()
    await screen.findByText('任务A')
    const summary = screen.getByLabelText('今日总结')
    fireEvent.change(summary, { target: { value: '点击保存时的草稿' } })
    fireEvent.click(screen.getByRole('button', { name: '保存计划' }))
    await waitFor(() => expect(plannerApi.saveDaily).toHaveBeenCalledTimes(1))

    fireEvent.change(summary, { target: { value: '保存期间的新草稿' } })
    await act(async () => { saveRequest.resolve({ ok: true }) })

    await waitFor(() => expect(summary).toHaveValue('保存期间的新草稿'))
    expect(plannerApi.getDaily).toHaveBeenCalledTimes(1)
    expect(plannerApi.getDaily).toHaveBeenCalledWith(TODAY)
  })

  it('自动保存失败显示持久错误，草稿仍保留', async () => {
    plannerApi.getDaily.mockResolvedValue(dailyPlan(TODAY, '任务A'))
    plannerApi.saveDaily.mockRejectedValue(new Error('网络离线'))

    renderPlanner()
    await screen.findByText('任务A')
    fireEvent.click(screen.getByRole('checkbox', { name: '标记「任务A」为已完成' }))

    expect(await screen.findByText('日计划保存失败', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText(/网络离线。草稿仍保留在当前页面/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /标记「任务A」/ })).toBeChecked()
  })

  it('自动保存串行执行，前一响应回来后才发送后一草稿', async () => {
    plannerApi.getDaily.mockResolvedValue(dailyPlan(TODAY, '任务A'))
    const requests = []
    plannerApi.saveDaily.mockImplementation((payload) => {
      const request = deferred()
      request.payload = payload
      requests.push(request)
      return request.promise
    })

    renderPlanner()
    await screen.findByText('任务A')
    const summary = screen.getByLabelText('今日总结')
    fireEvent.change(summary, { target: { value: '第一版草稿' } })
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 3000 })

    fireEvent.change(summary, { target: { value: '第二版草稿' } })
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1300)) })
    expect(requests).toHaveLength(1)

    await act(async () => { requests[0].resolve({ ok: true }) })
    await waitFor(() => expect(requests).toHaveLength(2), { timeout: 3000 })
    expect(requests[0].payload.summary).toBe('第一版草稿')
    expect(requests[1].payload.summary).toBe('第二版草稿')
    expect(screen.getByLabelText('今日总结')).toHaveValue('第二版草稿')
  })
})
