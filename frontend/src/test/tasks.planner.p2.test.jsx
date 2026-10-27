/**
 * P2 回归：Tasks 乐观打卡 / 口径文案 / Planner 自动保存与重排按钮降级。
 *
 * 背景：
 *  - Tasks 打卡上一版要等后端往返 + 整域刷新才变化（偶发慢 →「点了没反应」）；
 *  - 页头数字混着「全部累计/今日到期」两种口径，读数靠猜；
 *  - Planner 顺序调整只有 HTML5 拖拽一条路，触屏/键盘用户动不了；
 *  - Planner 草稿忘了点「保存」就丢。
 * 这里把这些行为的正反两面全部钉死。
 */
import React from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { todayStr } from '../utils/date'
import useStore from '../store/useStore'
import { subjectTone } from '../api/hub'

const TODAY = todayStr()

/* 服务端任务行形状（对齐 api/sync.js::toTask 的输入契约） */
const serverTask = (id, patch = {}) => ({
  id,
  title: `任务${id}`,
  subject: '数学',
  due_date: TODAY,
  status: 'pending',
  is_ai: false,
  ...patch,
})

vi.mock('../api/client', async (importOriginal) => {
  const real = await importOriginal()
  return {
    ...real,
    tasksApi: {
      ...real.tasksApi,
      list: vi.fn(),
      create: vi.fn().mockResolvedValue({ id: 1 }),
      complete: vi.fn().mockResolvedValue({}),
      uncomplete: vi.fn().mockResolvedValue({}),
      remove: vi.fn().mockResolvedValue({}),
      reviewSchedule: vi.fn().mockResolvedValue([]),
      aiGenerate: vi.fn().mockResolvedValue({ tasks: [] }),
    },
    plannerApi: {
      ...real.plannerApi,
      getDaily: vi.fn(),
      saveDaily: vi.fn().mockResolvedValue({ ok: true }),
      getMonth: vi.fn().mockResolvedValue({ year: 2026, month: 10, tasks: {}, completion: '', exists: false }),
      getWeek: vi.fn().mockResolvedValue({ week_start: '2026-10-12', tasks: {}, daily_records: [], exists: false }),
      listEbbinghaus: vi.fn().mockResolvedValue([]),
      listEarlyBird: vi.fn().mockResolvedValue([]),
      listPhase: vi.fn().mockResolvedValue([]),
      getPhaseReviews: vi.fn().mockResolvedValue({ plan_id: 1, reviews: [], total: 0 }),
    },
    goalsApi: {
      ...real.goalsApi,
      list: vi.fn().mockResolvedValue([]),
      subjects: vi.fn().mockResolvedValue({
        exam_subjects: ['数学', '英语', '政治'],
        support_subjects: [],
        all_known: ['数学', '英语', '政治'],
        using_default: true,
      }),
    },
  }
})

import { tasksApi, plannerApi } from '../api/client'
import { ToastHost } from '../v3/ui'
import Tasks from '../v3/pages/Tasks'
import Planner from '../v3/pages/Planner'

/* toast 队列由全局 ToastHost 渲染（应用壳挂载）；这里补挂才能断言提示文案 */
const renderTasks = () => render(<MemoryRouter><Tasks /><ToastHost /></MemoryRouter>)
const renderPlanner = () => render(<MemoryRouter><Planner /></MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  useStore.setState({ tasks: [] })
})

afterEach(cleanup)

/* ------------------------------ subjectTone ------------------------------ */
describe('api/hub subjectTone（科目稳定色调）', () => {
  it('空白/标点变体映射到同一色调，且不随输入顺序漂移', () => {
    expect(subjectTone('数学')).toBe(subjectTone('数学 '))
    expect(subjectTone('数学')).toBe(subjectTone(' 数学'))
    expect(subjectTone('英语 (一)')).toBe(subjectTone('英语（一）'))
    expect(subjectTone('')).toBe(subjectTone(null))
    /* 结果必须在 0-3 的色桶范围内 */
    for (const s of ['数学', '英语', '政治', '专业课', '数学一', '英']) {
      expect([0, 1, 2, 3]).toContain(subjectTone(s))
    }
  })
})

/* ------------------------------ Tasks 页 ------------------------------ */
describe('Tasks · 乐观打卡（store 驱动，页面薄层）', () => {
  const boot = () => {
    const rows = [serverTask(11), serverTask(22, { status: 'done' })]
    tasksApi.list.mockResolvedValue({ tasks: rows, total: rows.length, page: 1, page_size: 200, total_pages: 1 })
    return rows
  }

  it('勾选立即生效（本地先行），后端按 store 的异步同步路径打卡', async () => {
    boot()
    let resolveToggle
    tasksApi.complete.mockImplementation(() => new Promise((resolve) => { resolveToggle = resolve }))

    renderTasks()
    await screen.findByText(/后端已连接/)

    const row = [...document.querySelectorAll('.v3-task-row')].find((el) => el.textContent.includes('任务11'))
    expect(row).toBeTruthy()
    fireEvent.click(row.querySelector('.v3-task-row__check'))

    /* 关键断言：complete 的 Promise 尚未 resolve，界面必须已经变化 */
    expect(row.className).toContain('is-done')
    /* store.toggleTask 直传 String id（见 sync.js::toTask） */
    expect(tasksApi.complete).toHaveBeenCalledWith('11')

    resolveToggle({})
    await waitFor(() => expect(row.className).toContain('is-done'))
    /* 页面层不再手工重复调用（P2 前是双写） */
    expect(tasksApi.complete).toHaveBeenCalledTimes(1)
  })

  it('打卡/页头口径：今日到期 N 与全部累计分开表述', async () => {
    boot()
    renderTasks()
    await screen.findByText(/后端已连接/)
    expect(screen.getByText(/今日到期 2/)).toBeInTheDocument()
    expect(screen.getByText(/已完成 1\/2/)).toBeInTheDocument()
  })

  it('打卡失败 → 状态保持乐观结果并入失败队列重试，同时给出可感知提示', async () => {
    boot()
    tasksApi.complete.mockRejectedValueOnce(new Error('boom'))

    renderTasks()
    await screen.findByText(/后端已连接/)

    const row = [...document.querySelectorAll('.v3-task-row')].find((el) => el.textContent.includes('任务11'))
    fireEvent.click(row.querySelector('.v3-task-row__check'))

    /* 失败队列语义：不打断用户，本地结果保留，网络恢复自动重试 */
    await waitFor(() => expect(row.className).toContain('is-done'))
    expect(await screen.findByText(/任务打卡未同步，已加入失败队列/)).toBeInTheDocument()
  })

  it('删除确认弹窗取消 → 任务保留（乐观删除不越过确认）', async () => {
    boot()
    renderTasks()
    await screen.findByText(/后端已连接/)

    const row = [...document.querySelectorAll('.v3-task-row')].find((el) => el.textContent.includes('任务11'))
    fireEvent.click([...row.querySelectorAll('button')].find((b) => (b.getAttribute('aria-label') || '').includes('删除')))

    await screen.findByText('删除任务')
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(row.isConnected).toBe(true)
    expect(tasksApi.remove).not.toHaveBeenCalled()
  })

  it('删除确认 → 本地立即摘掉，store 异步同步删除接口', async () => {
    boot()
    renderTasks()
    await screen.findByText(/后端已连接/)

    const row = [...document.querySelectorAll('.v3-task-row')].find((el) => el.textContent.includes('任务11'))
    fireEvent.click([...row.querySelectorAll('button')].find((b) => (b.getAttribute('aria-label') || '').includes('删除')))
    fireEvent.click(await screen.findByRole('button', { name: '确定' }))

    await waitFor(() => expect(tasksApi.remove).toHaveBeenCalledWith('11'))
    await waitFor(() => {
      expect([...document.querySelectorAll('.v3-task-row')].some((el) => el.textContent.includes('任务11'))).toBe(false)
    })
  })

  it('删除失败 → 提示已入队重试（不做静默丢失）', async () => {
    boot()
    tasksApi.remove.mockRejectedValueOnce(new Error('boom'))

    renderTasks()
    await screen.findByText(/后端已连接/)

    const row = [...document.querySelectorAll('.v3-task-row')].find((el) => el.textContent.includes('任务11'))
    fireEvent.click([...row.querySelectorAll('button')].find((b) => (b.getAttribute('aria-label') || '').includes('删除')))
    fireEvent.click(await screen.findByRole('button', { name: '确定' }))

    expect(await screen.findByText(/任务删除未同步，已加入失败队列/)).toBeInTheDocument()
  })
})

/* ------------------------------ Planner 页 ------------------------------ */
describe('Planner · 重排按钮与自动保存', () => {
  const boot = (patchPlan = {}) => {
    plannerApi.getDaily.mockResolvedValue({
      date: TODAY, days_to_exam: null, exists: true,
      tasks: [
        { id: 'a', title: '任务A', subject: '数学', duration: 25, completed: false, subtasks: [] },
        { id: 'b', title: '任务B', subject: '英语', duration: 45, completed: false, subtasks: [] },
        { id: 'c', title: '任务C', subject: '政治', duration: 30, completed: true, subtasks: [] },
      ],
      timeline: [], score: 0, summary: '', study_duration: 0, wasted_duration: 0,
      ...patchPlan,
    })
  }

  const titles = () => [...document.querySelectorAll('.v3-plan-task__title')].map((el) => el.textContent.trim())

  it('上移/下移按钮（触屏/键盘可用的拖拽降级）重排生效', async () => {
    boot()
    renderPlanner()
    await screen.findByText('任务A')

    expect(titles()).toEqual(['任务A', '任务B', '任务C'])

    /* 边界：第一行「上移」禁用、末行「下移」禁用 */
    expect(screen.getByRole('button', { name: '上移「任务A」' }).disabled).toBe(true)
    expect(screen.getByRole('button', { name: '下移「任务C」' }).disabled).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: '下移「任务A」' }))
    expect(titles()).toEqual(['任务B', '任务A', '任务C'])

    fireEvent.click(screen.getByRole('button', { name: '上移「任务A」' }))
    expect(titles()).toEqual(['任务A', '任务B', '任务C'])
  })

  it('草稿防抖自动保存：改动 ~1.2s 后静默落库，无需点「保存计划」', async () => {
    boot()
    renderPlanner()
    await screen.findByText('任务A')

    fireEvent.click(screen.getByRole('checkbox', { name: '标记「任务A」为已完成' }))

    await waitFor(() => {
      const last = plannerApi.saveDaily.mock.calls.at(-1)?.[0]
      expect(last?.tasks?.find((t) => t.id === 'a')?.completed).toBe(true)
    }, { timeout: 3000 })
  })

  it('空草稿不触发自动保存（打开页面不悄悄建记录）', async () => {
    plannerApi.getDaily.mockResolvedValue({
      date: TODAY, days_to_exam: null, exists: false,
      tasks: [], timeline: [], score: 0, summary: '',
    })
    renderPlanner()
    await screen.findByText('还没有任务')
    await new Promise((resolve) => setTimeout(resolve, 1500))
    expect(plannerApi.saveDaily).not.toHaveBeenCalled()
  })
})
