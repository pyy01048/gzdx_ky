/**
 * 会话清理链（P0 跨账号串号）回归。
 *
 * 锁住三条底线：
 *   ① auth:required / refresh 401 走完整清理链（不发网络）：
 *      resetAll（含 syncState）→ 收藏缓存 → 网盘授权 → hub 缓存 → 解绑 uid；
 *      顺序必须是「先清内存/缓存，再解绑 uid」—— uid-changed 广播那一刻，
 *      所有模块级快照必须已经是干净的。
 *   ② resetAll 清空 failedQueue / pendingOps / inflight，且旧账号在途请求
 *      回来后不得污染新账号的同步队列（代际守卫）。
 *   ③ logout 不再 clearStorage：当前账号的落盘归档（AI 会话等纯本地数据）
 *      保留到下次登录。
 *
 * 全部 mock api/client 与 api/hub，不触网。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react'

vi.mock('../api/client', async (importOriginal) => {
  const orig = await importOriginal()
  return {
    ...orig,
    authApi: {
      me: vi.fn(), refresh: vi.fn(), logout: vi.fn(),
      login: vi.fn(), changePassword: vi.fn(),
    },
    tasksApi: { ...orig.tasksApi, complete: vi.fn(), uncomplete: vi.fn() },
  }
})

vi.mock('../api/hub', () => ({
  clearHubCache: vi.fn(),
  fetchHubOverview: vi.fn(),
  peekHubCache: vi.fn(),
}))

import { authApi, tasksApi } from '../api/client'
import { clearHubCache } from '../api/hub'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import useStore, { __syncStateForTest, __pendingOpsForTest } from '../store/useStore'
import { primeFavorites, useFavorite } from '../hooks/useFavorites'
import { storePan, getStoredPan } from '../utils/pan'
import { currentUid, setUser } from '../utils/userKeys'

const USER = { id: 7, username: 'alice', role: 'user', must_change_password: false }

function Probe() {
  const auth = useAuth()
  const fav = useFavorite('document', 1)
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="fav">{JSON.stringify({ f: fav.favorited, k: fav.known })}</span>
      <button type="button" data-testid="logout" onClick={auth.logout}>退出</button>
    </div>
  )
}

const renderProbe = () => render(<AuthProvider><Probe /></AuthProvider>)
const favState = () => JSON.parse(screen.getByTestId('fav').textContent)

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  setUser(null)
  useStore.getState().resetAll()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('auth:required 完整清理链', () => {
  it('强制下线时按序清空 store/同步队列/收藏/网盘/hub 缓存，最后才解绑 uid，且不发网络', async () => {
    authApi.me.mockResolvedValue(USER)
    renderProbe()
    expect(await screen.findByTestId('status')).toHaveTextContent('ready')
    expect(currentUid()).toBe(7)

    /* 污染当前账号的各类内存态 */
    act(() => {
      useStore.setState({ tasks: [{ id: '1', title: 'A 的任务', done: false }] })
      __syncStateForTest.failedQueue.push({ fn: () => Promise.resolve() })
      __syncStateForTest.inflight = 2
      __pendingOpsForTest['local-1'] = [() => {}]
      primeFavorites([{ item_type: 'document', item_id: 1 }])
      storePan('token-of-alice')
    })
    expect(favState()).toEqual({ f: true, k: true })
    expect(getStoredPan()).toBe('token-of-alice')

    /* uid-changed 广播瞬间抓快照：此刻所有缓存必须已经清完（顺序契约） */
    let atUnbind = null
    const onUid = () => {
      atUnbind = {
        tasks: useStore.getState().tasks.length,
        failed: __syncStateForTest.failedQueue.length,
        inflight: __syncStateForTest.inflight,
        pending: Object.keys(__pendingOpsForTest).length,
        hubCleared: clearHubCache.mock.calls.length,
        panKey: localStorage.getItem('kaoyan_pan_token:7'),
      }
    }
    window.addEventListener('userkeys:uid-changed', onUid)
    try {
      act(() => { window.dispatchEvent(new Event('auth:required')) })
    } finally {
      window.removeEventListener('userkeys:uid-changed', onUid)
    }

    expect(screen.getByTestId('status')).toHaveTextContent('anon')
    expect(currentUid()).toBeNull()
    expect(atUnbind).toEqual({
      tasks: 0, failed: 0, inflight: 0, pending: 0, hubCleared: 1, panKey: null,
    })
    expect(favState()).toEqual({ f: false, k: false })
    /* 清理链不发任何网络请求 */
    expect(authApi.logout).not.toHaveBeenCalled()
    expect(authApi.refresh).not.toHaveBeenCalled()
  })

  it('定时续期收到 401 同样走清理链回到未登录', async () => {
    vi.useFakeTimers()
    authApi.me.mockResolvedValue(USER)
    authApi.refresh.mockRejectedValue(Object.assign(new Error('expired'), { status: 401 }))
    renderProbe()
    await act(async () => { await vi.advanceTimersByTimeAsync(10) })
    expect(screen.getByTestId('status')).toHaveTextContent('ready')

    act(() => {
      useStore.setState({ tasks: [{ id: '1', title: 'A 的任务', done: false }] })
      primeFavorites([{ item_type: 'document', item_id: 1 }])
    })

    await act(async () => { await vi.advanceTimersByTimeAsync(15 * 60 * 1000 + 10) })
    expect(screen.getByTestId('status')).toHaveTextContent('anon')
    expect(currentUid()).toBeNull()
    expect(useStore.getState().tasks).toEqual([])
    expect(favState()).toEqual({ f: false, k: false })
    expect(clearHubCache).toHaveBeenCalled()
  })
})

describe('resetAll 同步态清理 + 代际守卫', () => {
  it('清空 failedQueue / pendingOps / inflight', () => {
    __syncStateForTest.failedQueue.push({ fn: () => Promise.resolve() })
    __syncStateForTest.inflight = 3
    __pendingOpsForTest['local-x'] = [() => {}]
    useStore.getState().resetAll()
    expect(__syncStateForTest.failedQueue).toEqual([])
    expect(__syncStateForTest.inflight).toBe(0)
    expect(Object.keys(__pendingOpsForTest)).toEqual([])
  })

  it('旧账号在途的打卡请求失败回来，不会进新账号的 failedQueue、不会把 inflight 减成负数', async () => {
    let rejectInflight
    tasksApi.complete.mockImplementation(() => new Promise((_, rej) => { rejectInflight = rej }))
    useStore.setState({ tasks: [{ id: '5', title: '后端任务', done: false }] })
    act(() => { useStore.getState().toggleTask('5') })
    expect(__syncStateForTest.inflight).toBe(1)

    /* 切号/强制下线：代际自增 */
    useStore.getState().resetAll()
    await act(async () => {
      rejectInflight(new Error('旧账号的请求失败了'))
      await Promise.resolve()
    })
    expect(__syncStateForTest.failedQueue).toEqual([])
    expect(__syncStateForTest.inflight).toBe(0)
  })
})

describe('logout 保留本账号落盘归档', () => {
  it('不清 clearStorage：AI 会话等纯本地数据保留在 uid 命名空间，内存则彻底清空', async () => {
    authApi.me.mockResolvedValue(USER)
    authApi.logout.mockResolvedValue({})
    renderProbe()
    expect(await screen.findByTestId('status')).toHaveTextContent('ready')

    /* 模拟一段纯本地 AI 会话（partialize 白名单内容） */
    const aiSession = { localSessions: [{ id: 's1', title: 'A 的会话' }], activeSessionId: 's1', messages: { s1: [{ role: 'user', content: '你好' }] } }
    act(() => { useStore.setState({ ai: aiSession }) })
    expect(localStorage.getItem('kaoyan-archive-v1:7')).toContain('A 的会话')

    await act(async () => { fireEvent.click(screen.getByTestId('logout')) })
    expect(screen.getByTestId('status')).toHaveTextContent('anon')
    expect(currentUid()).toBeNull()

    /* 归档仍在且 AI 会话未被 seed 覆盖 */
    const archived = JSON.parse(localStorage.getItem('kaoyan-archive-v1:7'))
    expect(archived.state.ai.localSessions[0].title).toBe('A 的会话')
    /* 内存已清：下一个账号/访客看不到 A 的会话与任务 */
    expect(useStore.getState().ai.localSessions || []).toEqual([])
    expect(useStore.getState().tasks).toEqual([])
  })
})
