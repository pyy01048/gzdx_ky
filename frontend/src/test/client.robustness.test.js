import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { request, ApiError, DEFAULT_TIMEOUT } from '../api/client'

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
})