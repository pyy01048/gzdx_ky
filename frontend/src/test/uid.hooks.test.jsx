/**
 * uid-changed 快照重置（P0 跨账号串号）：
 * useSubjectConfig / useUnreadNotices 的模块级快照必须在切号广播时作废，
 * 否则 ready/version 短路会让 B 账号一直看到 A 的科目与未读角标。
 *
 * 隔离：vi.resetModules + 动态 import，每个用例拿干净的模块级单例。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, act } from '@testing-library/react'

const hoisted = vi.hoisted(() => ({
  goalsSubjects: vi.fn(),
  unreadStats: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  goalsApi: { subjects: hoisted.goalsSubjects },
}))

vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: { noticeUnreadStats: hoisted.unreadStats },
}))

const CONFIG_A = { exam_subjects: ['数学'], support_subjects: [], all_known: ['数学', '英语'], using_default: false }
const CONFIG_B = { exam_subjects: ['英语'], support_subjects: [], all_known: ['数学', '英语'], using_default: false }

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(cleanup)

async function freshUserKeys() {
  return import('../utils/userKeys')
}

describe('useSubjectConfig uid-changed 重置', () => {
  it('切号后快照作废并替新账号重拉，不再短路复用 A 的配置', async () => {
    vi.resetModules()
    const { setUser } = await freshUserKeys()
    const mod = await import('../hooks/useSubjectConfig')

    setUser(1)
    hoisted.goalsSubjects.mockResolvedValue(CONFIG_A)
    const a = await mod.refreshSubjectConfig(true)
    expect(a.exam).toEqual(['数学'])

    /* 切号：重置必须让 ready 短路失效，下一次 refresh 真正发请求 */
    hoisted.goalsSubjects.mockClear()
    hoisted.goalsSubjects.mockResolvedValue(CONFIG_B)
    setUser(2)
    const b = await mod.refreshSubjectConfig()
    expect(hoisted.goalsSubjects).toHaveBeenCalledTimes(1)
    expect(b.exam).toEqual(['英语'])
  })

  it('A 的科目响应在途时切号：回来不得冒充 B 的口径', async () => {
    vi.resetModules()
    const { setUser } = await freshUserKeys()
    const mod = await import('../hooks/useSubjectConfig')

    let resolveA
    hoisted.goalsSubjects.mockImplementation(() => new Promise((res) => { resolveA = res }))
    setUser(1)
    const p = mod.refreshSubjectConfig(true)
    setUser(2)
    await act(async () => {
      resolveA(CONFIG_A)
      await p
    })
    /* 旧响应被丢弃：快照仍未就绪 */
    hoisted.goalsSubjects.mockResolvedValue(CONFIG_B)
    const b = await mod.refreshSubjectConfig()
    expect(b.exam).toEqual(['英语'])
  })
})

describe('useUnreadNotices uid-changed 重置', () => {
  it('切号后 version 归零，挂载的订阅者替新账号重拉角标', async () => {
    vi.resetModules()
    const { setUser } = await freshUserKeys()
    const mod = await import('../hooks/useUnreadNotices')

    setUser(1)
    hoisted.unreadStats.mockResolvedValue({ total: 5, unread: 3 })
    const s1 = await mod.refreshUnread()
    expect(s1.unread).toBe(3)

    hoisted.unreadStats.mockClear()
    hoisted.unreadStats.mockResolvedValue({ total: 0, unread: 0 })
    setUser(2)

    function Probe() {
      const s = mod.useUnreadNotices()
      return <div data-testid="unread">{s.unread}</div>
    }
    render(<Probe />)
    /* 旧 bug：version>0 短路 → 不重拉，B 一直看到 A 的 3 */
    await waitFor(() => expect(hoisted.unreadStats).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByTestId('unread')).toHaveTextContent('0'))
  })

  it('A 的未读响应在途时切号：回来不得写进 B 的快照', async () => {
    vi.resetModules()
    const { setUser } = await freshUserKeys()
    const mod = await import('../hooks/useUnreadNotices')

    let resolveA
    hoisted.unreadStats.mockImplementation(() => new Promise((res) => { resolveA = res }))
    setUser(1)
    const p = mod.refreshUnread()
    setUser(2) /* 重置 inflight，B 可立即发起自己的请求 */
    hoisted.unreadStats.mockResolvedValue({ total: 0, unread: 0 })
    const s2 = await mod.refreshUnread()
    expect(s2.unread).toBe(0)
    await act(async () => {
      resolveA({ total: 9, unread: 9 })
      await p
    })
    /* 用探针读快照（version>0 不会再发请求）：A 的 9 若泄漏会直接显示出来 */
    function Probe() {
      const s = mod.useUnreadNotices()
      return <div data-testid="unread">{s.unread}</div>
    }
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('unread')).toHaveTextContent('0'))
  })
})
