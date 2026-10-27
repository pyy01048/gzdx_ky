import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { FocusTile } from '../v3/pages/widgets'
import { ukey, setUser } from '../utils/userKeys'

/* ------------------------------------------------------------------ *
 * 专注计时（D-04 · 01-仪表盘 §2.1 / §2.2.2）
 *
 * v3 仪表盘用 FocusTile。这个组件唯一的价值在于「不撒谎」，用例围绕：
 *   1. 没点记录 → 一次请求都不发；
 *   2. 点记录 → 发的是**实际经过**的分钟数（番茄档封顶在名义档位）；
 *   3. 后端拒绝 → 计时状态保留，不把用户那段专注抹掉。
 *
 * 计时不靠假时钟推进：直接往 localStorage 写「时间戳 + 已累计毫秒」，
 * 组件按 Date.now() 反算 elapsed —— 顺带盖住刷新不丢计时的恢复路径。
 * ------------------------------------------------------------------ */

const apiMocks = { addSession: vi.fn() }

vi.mock('../api/client', () => ({
  studyApi: { addSession: (...a) => apiMocks.addSession(...a) },
}))

/** 后端真实返回壳（routers/dashboard.py::create_study_session） */
const sessionResp = (over = {}) => ({
  id: 7, ok: true, date: '2026-10-16', duration: 20,
  subject: null, task_type: 'pomodoro', day_total_minutes: 20, ...over,
})

const STORE = 'v3_focus_v1'
const seedTimer = (t) => localStorage.setItem(ukey(STORE), JSON.stringify(t))
const stored = () => localStorage.getItem(ukey(STORE))

/** 一条"暂停在 N 分钟"的计时：elapsed 恰为 N 分钟，不受测试执行耗时影响 */
const pausedAt = (minutes, nominal = 25) => ({
  runningSince: null, accumMs: minutes * 60000, minutes: nominal,
  subject: '', startedTs: Date.now() - minutes * 60000,
})

const renderTile = (props = {}) => render(<FocusTile {...props} />)

beforeEach(() => {
  apiMocks.addSession.mockReset().mockResolvedValue(sessionResp())
  localStorage.clear()
  setUser(1)
})
afterEach(() => { cleanup(); setUser(null) })

describe('FocusTile 空态与目标', () => {
  it('没有时长、没有目标：显示 0 分钟并说明未设目标，不编百分比', () => {
    const { container } = renderTile({ todayMinutes: 0, targetMinutes: null, subjects: [] })

    expect(container.querySelector('.v3-focus__meta strong').textContent).toBe('0 分钟')
    expect(screen.getByText('未设置每日时长目标')).toBeInTheDocument()
    expect(container.querySelector('.v3-focus__meta .v3-progress')).toBeNull()
  })

  it('有每日目标时进度条与百分比按后端时长计算', () => {
    const { container } = renderTile({ todayMinutes: 75, targetMinutes: 120 })

    expect(container.querySelector('.v3-progress__bar').style.width).toBe('63%')
    expect(screen.getByText('目标 120 分钟 · 63%')).toBeInTheDocument()
  })

  it('默认 25 分钟档，档位可切换', () => {
    renderTile()
    expect(screen.getByRole('button', { name: '25 分钟' })).toHaveClass('v3-chip--active')
    fireEvent.click(screen.getByRole('button', { name: '45 分钟' }))
    expect(screen.getByRole('button', { name: '45 分钟' })).toHaveClass('v3-chip--active')
  })
})

describe('FocusTile 记录真实时长', () => {
  it('没点记录之前一次请求都不发，计时状态落盘', () => {
    renderTile()

    fireEvent.click(screen.getByRole('button', { name: /开始专注/ }))

    expect(apiMocks.addSession).not.toHaveBeenCalled()
    expect(stored()).toBeTruthy()
    expect(screen.getByRole('button', { name: /记录 0 分钟/ })).toBeDisabled()
  })

  it('恢复暂停在 20 分钟的计时：记的是 20 分钟，不是 25 分钟档', async () => {
    seedTimer(pausedAt(20, 25))
    const onRecorded = vi.fn()
    renderTile({ onRecorded })

    const record = screen.getByRole('button', { name: /记录 20 分钟/ })
    expect(record).not.toBeDisabled()
    fireEvent.click(record)

    await waitFor(() => expect(apiMocks.addSession).toHaveBeenCalledTimes(1))
    expect(apiMocks.addSession.mock.calls[0][0]).toMatchObject({
      duration: 20, task_type: 'pomodoro', subject: null,
    })
    expect(onRecorded).toHaveBeenCalledTimes(1)
    expect(stored()).toBeNull()
  })

  it('到点后挂着不记不会继续涨：40 分钟的番茄只按 25 分钟记', async () => {
    seedTimer(pausedAt(40, 25))
    renderTile()

    expect(screen.getByRole('button', { name: /记录 25 分钟/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /记录 25 分钟/ }))

    await waitFor(() => expect(apiMocks.addSession).toHaveBeenCalledTimes(1))
    expect(apiMocks.addSession.mock.calls[0][0].duration).toBe(25)
  })

  it('放弃计时：一行不写，持久化状态清掉', () => {
    seedTimer(pausedAt(18, 25))
    renderTile()

    fireEvent.click(screen.getByRole('button', { name: '放弃' }))

    expect(apiMocks.addSession).not.toHaveBeenCalled()
    expect(stored()).toBeNull()
    expect(screen.getByRole('button', { name: /开始专注/ })).toBeInTheDocument()
  })

  it('后端拒绝时保留计时状态，不把用户那段专注抹掉', async () => {
    apiMocks.addSession.mockRejectedValue(new Error('今天已累计 1430 分钟，再加 20 分钟就超过一天的长度了'))
    seedTimer(pausedAt(20, 25))
    renderTile()

    fireEvent.click(screen.getByRole('button', { name: /记录 20 分钟/ }))

    await waitFor(() => expect(apiMocks.addSession).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('button', { name: /记录 20 分钟/ }), '写入失败后计时器必须还在').toBeInTheDocument()
    expect(stored()).toBeTruthy()
  })
})

describe('FocusTile 科目', () => {
  it('科目候选只来自调用方，选中的科目原样进请求', async () => {
    seedTimer(pausedAt(20, 25))
    renderTile({ subjects: ['数学', '数字电子技术'] })

    const select = screen.getByLabelText('专注科目')
    expect([...select.options].map((o) => o.value)).toEqual(['', '数学', '数字电子技术'])

    fireEvent.change(select, { target: { value: '数字电子技术' } })
    fireEvent.click(screen.getByRole('button', { name: /记录 20 分钟/ }))

    await waitFor(() => expect(apiMocks.addSession).toHaveBeenCalledTimes(1))
    expect(apiMocks.addSession.mock.calls[0][0].subject).toBe('数字电子技术')
  })

  it('不限科目时传 null，不传空串（空串会变成一个看不见的科目）', async () => {
    seedTimer(pausedAt(20, 25))
    renderTile({ subjects: ['数学'] })

    fireEvent.click(screen.getByRole('button', { name: /记录 20 分钟/ }))

    await waitFor(() => expect(apiMocks.addSession).toHaveBeenCalledTimes(1))
    expect(apiMocks.addSession.mock.calls[0][0].subject).toBeNull()
  })

  it('恢复的计时带着一个已被移除的科目时，下拉仍然显示它而不是留白', () => {
    seedTimer({ ...pausedAt(12, 25), subject: '结构力学' })
    renderTile({ subjects: ['数学'] })

    const select = screen.getByLabelText('专注科目')
    expect(select.value).toBe('结构力学')
    expect(Array.from(select.options).map((o) => o.value)).toContain('结构力学')
  })
})
