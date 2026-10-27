import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { request, ApiError, DEFAULT_TIMEOUT, fetchAllPages, MAX_PAGE_SIZE } from '../api/client'
import { MUTATION_EVENT } from '../api/mutationEvent'

/* ------------------------------------------------------------------ *
 * P0-2 前端健壮性回归测试
 * 覆盖：超时中断、网络异常、错误透传、成功解析、参数过滤。
 * ------------------------------------------------------------------ */

describe('api/client request 健壮性', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('成功时返回解析后的 JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ items: [1, 2] }),
    }))
    const data = await request('/things')
    expect(data).toEqual({ items: [1, 2] })
  })

  it('非 2xx 抛出 ApiError 且透传后端 detail 文案', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 400, json: async () => ({ detail: '蓝图不存在' }),
    }))
    await expect(request('/x')).rejects.toThrow('蓝图不存在')
    await expect(request('/x')).rejects.toBeInstanceOf(ApiError)
  })

  it('超时会被中断并抛出 code=timeout（不会永久挂起）', async () => {
    // 模拟永不返回的请求：只有 abort 才会结束
    vi.stubGlobal('fetch', vi.fn((url, opts) => new Promise((_, reject) => {
      opts.signal.addEventListener('abort', () => {
        const err = new Error('aborted')
        err.name = 'AbortError'
        reject(err)
      })
    })))

    const p = request('/slow', { timeout: 1000 })
    const assertion = expect(p).rejects.toMatchObject({ code: 'timeout' })
    await vi.advanceTimersByTimeAsync(1100)
    await assertion
  })

  it('网络异常抛 code=network 且文案含"网络异常"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const p = request('/down')
    await expect(p).rejects.toMatchObject({ code: 'network' })
    await expect(p).rejects.toThrow(/网络异常/)
  })

  it('失败时绝不返回 undefined（下游 .map/.json 不会崩）', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('boom')))
    // 断言 Promise 状态为 rejected 而非 fulfilled undefined
    await expect(request('/boom')).rejects.toBeDefined()
  })

  it('无 JSON 体的成功响应返回 null（保持既有行为，不抛错）', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 204, json: async () => { throw new Error('no body') },
    }))
    await expect(request('/no-content')).resolves.toBeNull()
  })

  it('params 自动过滤 undefined/null/空串', async () => {
    const spy = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) })
    vi.stubGlobal('fetch', spy)
    await request('/q', { params: { a: 1, b: undefined, c: null, d: '', e: 'x' } })
    const url = spy.mock.calls[0][0]
    expect(url).toContain('a=1')
    expect(url).toContain('e=x')
    expect(url).not.toContain('b=')
    expect(url).not.toContain('c=')
    expect(url).not.toContain('d=')
  })

  it('导出默认超时为正数（避免配置缺失导致无超时）', () => {
    expect(DEFAULT_TIMEOUT).toBeGreaterThan(0)
  })

  it('非 GET 成功 → 广播 mutation 事件；GET / 失败 → 不广播（P0：聚合缓存失效链路）', async () => {
    const events = []
    const onMutation = (e) => events.push(e.detail)
    window.addEventListener(MUTATION_EVENT, onMutation)
    try {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true, status: 200, json: async () => ({}),
      }))
      await request('/tasks/1', { method: 'GET' })
      expect(events).toEqual([]) /* 读操作不改数据 */

      await request('/tasks/1', { method: 'POST', body: { done: true } })
      await request('/tasks/1', { method: 'DELETE' })
      expect(events).toEqual([
        { method: 'POST', path: '/tasks/1' },
        { method: 'DELETE', path: '/tasks/1' },
      ])

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false, status: 500, json: async () => ({ detail: 'boom' }),
      }))
      await expect(request('/tasks/1', { method: 'POST' })).rejects.toBeInstanceOf(ApiError)
      expect(events).toHaveLength(2) /* 失败的写不广播 */
    } finally {
      window.removeEventListener(MUTATION_EVENT, onMutation)
    }
  })
})

/* ------------------------------------------------------------------ *
 * fetchAllPages：取全量的唯一合法姿势。
 *
 * 后端把所有分页入参钉成 le=200（utils/response.py），page_size=500/1000 不是
 * "帮你截断"而是 **422**。历史故障正是前端自己写死 500/1000：sync 的
 * tasks/notebook/cards 三个域、Cards 页、错题本知识点候选、真题按套卷取题
 * 全部请求失败，被 catch 成空数组 → "后端有数据、页面永远空"。
 * ------------------------------------------------------------------ */
describe('api/client fetchAllPages 分页取全量', () => {
  const shell = (page, items, total, totalPages) => ({ total, page, page_size: MAX_PAGE_SIZE, total_pages: totalPages, items })

  it('按 total_pages 逐页翻，拼出全量且不漏尾批', async () => {
    const calls = []
    const fetchPage = vi.fn((p) => {
      calls.push(p)
      return Promise.resolve(p.page === 1
        ? shell(1, Array.from({ length: 200 }, (_, i) => i), 450, 3)
        : shell(p.page, Array.from({ length: p.page === 2 ? 200 : 50 }, (_, i) => i), 450, 3))
    })
    const all = await fetchAllPages(fetchPage)
    expect(all).toHaveLength(450)
    expect(calls.map((c) => c.page)).toEqual([1, 2, 3])
  })

  it('任何一页的 page_size 都不得超过后端上限（超限即 422）', async () => {
    const fetchPage = vi.fn((p) => Promise.resolve(shell(p.page, [1], 1, 1)))
    await fetchAllPages(fetchPage, { pageSize: 5000 })   // 传更大值也必须被夹到 200
    expect(fetchPage.mock.calls[0][0].page_size).toBe(MAX_PAGE_SIZE)
    expect(MAX_PAGE_SIZE).toBeLessThanOrEqual(200)
  })

  it('items 之外的字段别名也能取（老端点用 questions/errors/cards）', async () => {
    const fetchPage = vi.fn(() => Promise.resolve({ total: 2, total_pages: 1, questions: [{ id: 1 }, { id: 2 }] }))
    await expect(fetchAllPages(fetchPage, { keys: ['questions'] })).resolves.toEqual([{ id: 1 }, { id: 2 }])
  })

  it('裸数组响应视为全量，只请求一次', async () => {
    const fetchPage = vi.fn(() => Promise.resolve([1, 2, 3]))
    await expect(fetchAllPages(fetchPage)).resolves.toEqual([1, 2, 3])
    expect(fetchPage).toHaveBeenCalledTimes(1)
  })

  it('缺 total_pages 时按 total 推算页数', async () => {
    const fetchPage = vi.fn((p) => Promise.resolve({ total: 300, items: p.page === 1 ? new Array(200).fill(1) : new Array(100).fill(2) }))
    const all = await fetchAllPages(fetchPage)
    expect(all).toHaveLength(300)
    expect(fetchPage).toHaveBeenCalledTimes(2)
  })

  it('total 异常巨大也不会无限翻页（maxItems 安全上限）', async () => {
    const fetchPage = vi.fn((p) => Promise.resolve(shell(p.page, new Array(200).fill(p.page), 1e9, 5e6)))
    const all = await fetchAllPages(fetchPage, { maxItems: 600 })
    expect(all).toHaveLength(600)
    expect(fetchPage).toHaveBeenCalledTimes(3)
  })

  it('请求失败必须向上抛，不能静默成空数组', async () => {
    const fetchPage = vi.fn(() => Promise.reject(new ApiError('422 校验失败', { status: 422 })))
    await expect(fetchAllPages(fetchPage)).rejects.toThrow('422 校验失败')
  })
})