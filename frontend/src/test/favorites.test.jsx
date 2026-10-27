import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

/* ------------------------------------------------------------------ *
 * S7 收藏链路测试
 *
 * 锁三件事：
 *  1. api 层路径/method 与后端 /api/favorites 契约一致（改契约必挂）；
 *  2. useFavorites 的共享缓存不会让 N 行列表发 N 次 /check（N+1 请求）；
 *  3. toggle 失败必须回滚本地态 —— 否则用户看到"已收藏"实际没写进去，
 *     这是最难排查的一类 bug（UI 与数据不一致且不报错）。
 * ------------------------------------------------------------------ */

const state = { fetchImpl: null, calls: [] }

beforeEach(() => {
  state.calls = []
  state.fetchImpl = null
  vi.resetModules()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function stubFetch(handler) {
  const spy = vi.fn(async (url, opts = {}) => {
    state.calls.push({ url: String(url), method: (opts.method || 'GET').toUpperCase() })
    const res = handler(String(url), opts)
    return {
      ok: true,
      status: 200,
      json: async () => res,
    }
  })
  vi.stubGlobal('fetch', spy)
  return spy
}

// ---------- 1. api 层契约 ----------
describe('favoritesApi 契约', () => {
  it('列表带筛选与分页参数', async () => {
    stubFetch(() => ({ total: 0, items: [] }))
    const { favoritesApi } = await import('../api/client')
    const mod = await import('../hooks/useFavorites')
    mod.clearFavoriteCache()

    await favoritesApi.list({ item_type: 'document', q: '数电', limit: 20, offset: 40 })
    const call = state.calls[state.calls.length - 1]
    expect(call.method).toBe('GET')
    expect(call.url).toContain('/favorites')
    expect(call.url).toContain('item_type=document')
    expect(call.url).toContain('limit=20')
    expect(call.url).toContain('offset=40')
  })

  it('toggle 走 POST /favorites/toggle，remove 走 DELETE 且类型被编码', async () => {
    stubFetch(() => ({ favorited: true }))
    const { favoritesApi } = await import('../api/client')

    await favoritesApi.toggle({ item_type: 'question', item_id: 7, title: 'T' })
    expect(state.calls.at(-1).method).toBe('POST')
    expect(state.calls.at(-1).url).toContain('/favorites/toggle')

    await favoritesApi.remove('kp', 3)
    expect(state.calls.at(-1).method).toBe('DELETE')
    expect(state.calls.at(-1).url).toContain('/favorites/kp/3')
  })

  it('check 传 item_type 与 item_id 两个查询参数', async () => {
    stubFetch(() => ({ favorited: false, id: null }))
    const { favoritesApi } = await import('../api/client')
    await favoritesApi.check('word', 12)
    const url = state.calls.at(-1).url
    expect(url).toContain('/favorites/check')
    expect(url).toContain('item_type=word')
    expect(url).toContain('item_id=12')
  })
})

// ---------- 2. 共享缓存：N+1 请求防护 ----------
describe('useFavoriteProbe 批量探测', () => {
  it('同一批实体重复探测只发一次请求（按类型批量，不再逐项 check）', async () => {
    // P0-3：批量接口回 { map }，逐项接口回 { favorited }。断言请求数必须按"类型数"
    // 而不是"实体数"——3 个实体跨 2 种类型 = 2 次请求，逐项探测会是 3 次。
    stubFetch((url) =>
      url.includes('ids=')
        ? { item_type: 'document', requested: 2, map: { 1: false, 2: false, 3: false }, favorited_ids: [] }
        : { favorited: true })
    const mod = await import('../hooks/useFavorites')
    mod.clearFavoriteCache()

    const items = [
      { item_type: 'document', item_id: 1 },
      { item_type: 'document', item_id: 2 },
      { item_type: 'question', item_id: 3 },
    ]

    function Probe() {
      const { probe } = mod.useFavoriteProbe(items)
      React.useEffect(() => {
        probe()
      }, [probe])
      return <div>probe</div>
    }

    const { unmount } = render(<Probe />)
    await waitFor(() => expect(state.calls.length).toBe(2))
    // 两条都打批量接口：一条带 document 的两个 id，一条带 question 的单个 id
    for (const c of state.calls) {
      expect(c.url).toContain('/favorites/check')
      expect(c.url).toContain('ids=')
    }
    unmount()

    // 换一个组件实例，缓存命中，不应再发请求
    const before = state.calls.length
    const { unmount: u2 } = render(<Probe />)
    await waitFor(() => expect(state.calls.length).toBe(before))
    u2()
  })
})

// ---------- 3. 乐观更新与失败回滚 ----------
describe('useFavorite 乐观更新', () => {
  it('toggle 失败时本地态回滚', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        state.calls.push({ url: '/api/favorites/toggle', method: 'POST' })
        throw new Error('network down')
      })
    )

    const mod = await import('../hooks/useFavorites')
    mod.clearFavoriteCache()

    function Probe() {
      const { favorited, toggle } = mod.useFavorite('document', 99)
      return (
        <button
          data-testid="favorite-star"
          aria-pressed={favorited}
          onClick={() => { toggle({ title: '回滚测试' }).catch(() => {}) }}
        />
      )
    }

    render(<Probe />)
    const btn = screen.getByTestId('favorite-star')
    expect(btn.getAttribute('aria-pressed')).toBe('false')

    // 点击 → 乐观置为 true → 请求失败 → 回滚为 false
    fireEvent.click(btn)
    await waitFor(() => expect(state.calls.length).toBe(1))
    await waitFor(() => expect(screen.getByTestId('favorite-star').getAttribute('aria-pressed')).toBe('false'))
  })

  it('toggle 成功时保持新状态', async () => {
    stubFetch(() => ({ favorited: true }))
    const mod = await import('../hooks/useFavorites')
    mod.clearFavoriteCache()

    function Probe() {
      const { favorited, toggle } = mod.useFavorite('question', 55)
      return (
        <button
          data-testid="favorite-star"
          aria-pressed={favorited}
          onClick={() => { toggle({ title: '成功测试' }) }}
        />
      )
    }

    render(<Probe />)
    fireEvent.click(screen.getByTestId('favorite-star'))
    await waitFor(() => expect(screen.getByTestId('favorite-star').getAttribute('aria-pressed')).toBe('true'))
  })
})
