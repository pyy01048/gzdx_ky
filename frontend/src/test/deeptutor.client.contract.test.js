import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/* ------------------------------------------------------------------ *
 * 55号 DeepTutor 方案 · client.js 新增封装契约测试
 *
 * 用真实 client + stub fetch 验证：
 *   quizApi.orchestratedTutoring → POST /api/ai/tutoring/orchestrated
 *   recommendApi.weakPoints      → GET  /api/recommend/weak-points?subject=&limit=
 *   recommendApi.variants        → POST /api/recommend/variants
 *   recommendApi.masteryGate      → POST /api/recommend/mastery-gate
 * ------------------------------------------------------------------ */

let fetchSpy

function mockFetch(response = {}) {
  const payload = {
    ok: response.ok ?? true,
    status: response.status ?? 200,
    json: vi.fn().mockResolvedValue(response.body ?? {}),
  }
  fetchSpy = vi.fn().mockResolvedValue(payload)
  vi.stubGlobal('fetch', fetchSpy)
  return fetchSpy
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('55号方案 client 新增封装契约', () => {
  it('quizApi.orchestratedTutoring 已导出且请求 POST /api/ai/tutoring/orchestrated', async () => {
    const spy = mockFetch({ body: { answer: 'x' } })
    const { quizApi } = await import('../api/client')
    expect(quizApi.orchestratedTutoring).toBeTypeOf('function')

    await quizApi.orchestratedTutoring({ question_id: 2, my_answer: '微积分' })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe('/api/ai/tutoring/orchestrated')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ question_id: 2, my_answer: '微积分' })
  })

  it('recommendApi 已导出且包含 weakPoints/variants/masteryGate', async () => {
    const { recommendApi } = await import('../api/client')
    expect(recommendApi).toBeTypeOf('object')
    expect(recommendApi.weakPoints).toBeTypeOf('function')
    expect(recommendApi.variants).toBeTypeOf('function')
    expect(recommendApi.masteryGate).toBeTypeOf('function')
  })

  it('默认导出聚合中包含 recommendApi', async () => {
    const mod = await import('../api/client')
    expect(mod.default.recommendApi).toBeTypeOf('object')
  })

  it('recommendApi.weakPoints 请求 GET /api/recommend/weak-points 并透传 params', async () => {
    const spy = mockFetch({ body: { items: [] } })
    const { recommendApi } = await import('../api/client')

    await recommendApi.weakPoints({ subject: '数学', limit: 5 })
    const url = spy.mock.calls[0][0]
    expect(url).toContain('/api/recommend/weak-points')
    expect(url).toContain('subject=')
    expect(url).toContain('%E6%95%B0%E5%AD%A6')  // 数学的 UTF-8 编码
    expect(url).toContain('limit=5')
  })

  it('recommendApi.variants 请求 POST /api/recommend/variants 并带 body', async () => {
    const spy = mockFetch({ body: { created: 3 } })
    const { recommendApi } = await import('../api/client')

    await recommendApi.variants({ kp_id: 101, count: 3 })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe('/api/recommend/variants')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ kp_id: 101, count: 3 })
  })

  it('recommendApi.masteryGate 请求 POST /api/recommend/mastery-gate 并带 body', async () => {
    const spy = mockFetch({ body: { passed: true } })
    const { recommendApi } = await import('../api/client')

    await recommendApi.masteryGate({ kp_id: 101, consecutive_required: 3 })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe('/api/recommend/mastery-gate')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ kp_id: 101, consecutive_required: 3 })
  })
})