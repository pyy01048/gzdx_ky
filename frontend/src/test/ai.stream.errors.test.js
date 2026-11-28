import { describe, it, expect, vi, afterEach } from 'vitest'
import { aiChatStream } from '../api/client'

/* ------------------------------------------------------------------ *
 * P0-5 回归：AI 助手「无回复也无报错」
 *
 * 线上现象：点快捷问题后界面既不出回答也不出错误提示。根因是 SSE 的 error
 * 事件被当成「非 JSON 噪声」吞掉（旧 utils/api.js 的 chatStream），
 * 200 + 空流 = 静默。
 *
 * 本测试锁定 api/client.js 的 aiChatStream 必须**显式抛出**四种失败：
 *   ① SSE error 事件      → code = ai_stream_error
 *   ② 200 但无任何 delta  → code = ai_empty_stream
 *   ③ fetch 直接失败      → code = network
 *   ④ 非 2xx（如 502）    → code = http_error
 * 只有抛出可区分的 code，Assistant.jsx 才能给用户对应的可见提示与重试入口。
 * ------------------------------------------------------------------ */

/** 构造一个按块吐 SSE 文本的 Response 桩。 */
function sseResponse(chunks, cancel = vi.fn().mockResolvedValue(undefined)) {
  let i = 0
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        async read() {
          if (i >= chunks.length) return { done: true, value: undefined }
          return { done: false, value: new TextEncoder().encode(chunks[i++]) }
        },
        cancel,
        releaseLock() {},
      }),
    },
  }
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('aiChatStream 错误分支（P0-5）', () => {
  it('① SSE 携带 error 事件时必须抛出 ai_stream_error，而不是静默吞掉', async () => {
    // 每次调用都要拿到一条全新的流（SSE 是单次消费的）
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(sseResponse([
      'data: {"type":"meta","rag":false}\n\n',
      'data: {"type":"error","code":"provider_auth","message":"AI 服务暂时不可用（provider_auth）：已配置服务商的 API Key 缺失或无效（上游返回 401/403）。"}\n\n',
    ]))))

    const err = await aiChatStream({ messages: [] }).catch((e) => e)
    expect(err.code).toBe('ai_stream_error')
    expect(err.message).toContain('provider_auth')
  })

  it('② HTTP 200 但整条流没有任何 delta 时必须报 ai_empty_stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'data: {"type":"meta","rag":true}\n\n',
    ])))

    await expect(aiChatStream({ messages: [] })).rejects.toMatchObject({
      code: 'ai_empty_stream',
    })
  })

  it('③ fetch 直接失败（后端未启动/断网）时报 network', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(aiChatStream({ messages: [] })).rejects.toMatchObject({
      code: 'network',
    })
  })

  it('④ 非 2xx（/api/ai/chat 的 502）时把后端 detail 透出为 http_error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({
        detail: 'AI 服务暂时不可用（provider_auth）：已配置服务商的 API Key 缺失或无效（上游返回 401/403）。',
      }),
    }))

    const err = await aiChatStream({ messages: [] }).catch((e) => e)
    expect(err.code).toBe('http_error')
    expect(err.status).toBe(502)
    // 关键：拿到的是后端分类后的原因，而不是笼统的一句「HTTP 502」
    expect(err.message).toContain('provider_auth')
  })

  it('非 2xx 响应体挂起时 timeout 必须返回网络超时，不能误报 http_error', async () => {
    vi.useFakeTimers()
    const json = vi.fn(() => new Promise(() => {}))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json }))

    let outcome
    aiChatStream({ messages: [] }, { timeout: 20 }).then(
      (value) => { outcome = { value } },
      (error) => { outcome = { error } },
    )
    await vi.advanceTimersByTimeAsync(0)
    expect(json).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(20)
    expect(outcome?.error).toMatchObject({ code: 'network' })
    expect(outcome?.error?.message).toContain('超时')
  })

  it('非 2xx 的 401 响应体挂起时外部取消不得广播 auth:required', async () => {
    const controller = new AbortController()
    const json = vi.fn(() => new Promise(() => {}))
    const dispatchEvent = vi.spyOn(window, 'dispatchEvent')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json }))

    const pending = aiChatStream({ messages: [] }, { signal: controller.signal, timeout: 0 })
    await vi.waitFor(() => expect(json).toHaveBeenCalledTimes(1))
    controller.abort()
    const outcome = await Promise.race([
      pending.then((value) => ({ value }), (error) => ({ error })),
      new Promise((resolve) => setTimeout(() => resolve({ timedOut: true }), 100)),
    ])
    expect(outcome.timedOut).not.toBe(true)
    expect(outcome.error).toMatchObject({ code: 'aborted' })
    expect(dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'auth:required' }))
  })

  it('fetch 挂起时 timeout 必须结束请求', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    let outcome
    aiChatStream({ messages: [] }, { timeout: 20 }).then(
      (value) => { outcome = { value } },
      (error) => { outcome = { error } },
    )
    await vi.advanceTimersByTimeAsync(20)
    expect(outcome?.error).toMatchObject({ code: 'network' })
    expect(outcome?.error?.message).toContain('超时')
  })

  it('getReader 初始化失败时必须清理超时计时器', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => { throw new Error('reader init failed') } },
    }))

    await expect(aiChatStream({ messages: [] }, { timeout: 20 })).rejects.toMatchObject({ code: 'network' })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('TextDecoder 初始化失败时必须清理计时器并释放已取得的 reader', async () => {
    vi.useFakeTimers()
    const cancel = vi.fn().mockResolvedValue(undefined)
    const releaseLock = vi.fn()
    vi.stubGlobal('TextDecoder', class {
      constructor() { throw new Error('decoder init failed') }
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => ({ cancel, releaseLock }) },
    }))

    await expect(aiChatStream({ messages: [] }, { timeout: 20 })).rejects.toMatchObject({ code: 'network' })
    expect(vi.getTimerCount()).toBe(0)
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(releaseLock).toHaveBeenCalledTimes(1)
  })

  it('正常流：逐段拼接 delta 并返回全文', async () => {
    const cancel = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'data: {"type":"meta","rag":false}\n\n',
      'data: {"type":"delta","content":"你"}\n\n',
      'data: {"type":"delta","content":"好"}\n\n',
    ], cancel)))

    const seen = []
    const r = await aiChatStream({ messages: [] }, { onDelta: (ev) => ev.content && seen.push(ev.content) })
    expect(seen).toEqual(['你', '好'])
    expect(r.text).toBe('你好')
    expect(cancel).not.toHaveBeenCalled()
  })

  it('reader.read 挂起时外部取消必须返回 aborted 并取消底层流', async () => {
    const controller = new AbortController()
    const read = vi.fn(() => new Promise(() => {}))
    const cancel = vi.fn().mockResolvedValue(undefined)
    const releaseLock = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => ({ read, cancel, releaseLock }) },
    }))

    const pending = aiChatStream({ messages: [] }, { signal: controller.signal, timeout: 0 })
    await vi.waitFor(() => expect(read).toHaveBeenCalledTimes(1))
    controller.abort()
    const outcome = await Promise.race([
      pending.then((value) => ({ value }), (error) => ({ error })),
      new Promise((resolve) => setTimeout(() => resolve({ timedOut: true }), 100)),
    ])
    expect(outcome.timedOut).not.toBe(true)
    expect(outcome.error).toMatchObject({ code: 'aborted' })
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(releaseLock).toHaveBeenCalledTimes(1)
  })

  it('reader.read 挂起时 timeout 必须覆盖整个流并取消底层流', async () => {
    vi.useFakeTimers()
    const read = vi.fn(() => new Promise(() => {}))
    const cancel = vi.fn().mockResolvedValue(undefined)
    const releaseLock = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => ({ read, cancel, releaseLock }) },
    }))

    let outcome
    aiChatStream({ messages: [] }, { timeout: 20 }).then(
      (value) => { outcome = { value } },
      (error) => { outcome = { error } },
    )
    await vi.advanceTimersByTimeAsync(0)
    expect(read).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(20)
    expect(outcome?.error).toMatchObject({ code: 'network' })
    expect(outcome?.error?.message).toContain('超时')
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(releaseLock).toHaveBeenCalledTimes(1)
  })

  it('SSE error 中断读取时必须取消底层流', async () => {
    const cancel = vi.fn().mockResolvedValue(undefined)
    const releaseLock = vi.fn()
    const read = vi.fn().mockResolvedValue({
      done: false,
      value: new TextEncoder().encode('data: {"type":"error","message":"provider unavailable"}\n\n'),
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => ({ read, cancel, releaseLock }) },
    }))

    const err = await aiChatStream({ messages: [] }, { timeout: 0 }).catch((e) => e)
    expect(err.code).toBe('ai_stream_error')
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(releaseLock).toHaveBeenCalledTimes(1)
  })
})
