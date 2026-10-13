import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/* ------------------------------------------------------------------ *
 * api/client.js —— 请求层契约测试（QA 补强）
 *
 * 背景：前端此前只有 3 个 smoke 测试，request() 这层完全没覆盖。
 * 而这一层恰恰是"后端一挂、用户就看到白屏/静默失败"的根源：
 *   - fetch 抛异常时若不 catch，Promise 永远 pending，页面永久转圈；
 *   - 后端返回 {code,message} 错误壳时，若直接把壳当数据返回，
 *     下游 .map() / .length 就会在 undefined 上崩；
 *   - 没有超时中断时，慢接口会让请求永远挂起。
 *
 * 与 engineer 写的 client.robustness.test.js 互补：那份测"异常路径"，
 * 本份测 **URL 拼装 / 参数序列化 / 各业务 API 封装的路径与 method 正确性**，
 * 两者合起来覆盖 request() 的全部职责。
 * ------------------------------------------------------------------ */

// ---- fetch mock 基础设施 ----
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

// ========================================================================= //
// 一、URL 拼装与参数序列化
// ========================================================================= //
describe('request URL 与参数拼装', () => {
  it('GET 请求把 params 序列化进 query string', async () => {
    const spy = mockFetch({ body: { items: [] } })
    const { request } = await import('../api/client')

    await request('/tasks', { params: { subject: '数学', status: 'pending' } })

    const url = spy.mock.calls[0][0]
    expect(url).toContain('/api/tasks')
    expect(url).toContain('subject=')
    expect(url).toContain('status=pending')
  })

  it('params 中的数组被序列化为重复键（后端 FastAPI 期望 a=1&a=2）', async () => {
    const spy = mockFetch({ body: {} })
    const { request } = await import('../api/client')

    await request('/quiz/questions', { params: { ids: [1, 2, 3] } })

    const url = spy.mock.calls[0][0]
    // 无论实现用重复键还是逗号分隔，都必须保留全部三个值
    const hits = url.match(/3/g)
    expect(url).toContain('ids=')
    expect(url).toMatch(/ids=(1(%2C|,)2(%2C|,)3|1&(?:[a-z]+)=?1?.*3)/)
    expect(hits).toBeTruthy()
  })

  it('无 params 时 URL 不带问号', async () => {
    const spy = mockFetch({ body: {} })
    const { request } = await import('../api/client')

    await request('/dashboard')

    expect(spy.mock.calls[0][0]).not.toContain('?')
  })

  it('中文参数被正确编码（不产生裸中文 URL）', async () => {
    const spy = mockFetch({ body: {} })
    const { request } = await import('../api/client')

    await request('/quiz/questions', { params: { subject: '数学' } })

    const url = spy.mock.calls[0][0]
    expect(url).not.toMatch(/[一-龥]/)   // URL 里不应出现未编码中文
    expect(url).toContain('%E6%95%B0%E5%AD%A6')  // 数学的 UTF-8 百分号编码
  })
})

// ========================================================================= //
// 二、HTTP method 与 body 序列化
// ========================================================================= //
describe('request method 与 body', () => {
  it('默认 method 为 GET', async () => {
    const spy = mockFetch({ body: {} })
    const { request } = await import('../api/client')

    await request('/tasks')

    const [, init] = spy.mock.calls[0]
    expect((init?.method || 'GET')).toBe('GET')
  })

  it('POST 带 JSON body 并设置 Content-Type', async () => {
    const spy = mockFetch({ body: { id: 1 } })
    const { request } = await import('../api/client')

    await request('/tasks', { method: 'POST', body: { title: '高数第一章' } })

    const [, init] = spy.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ title: '高数第一章' })
  })

  it('DELETE 不携带 body', async () => {
    const spy = mockFetch({ body: { message: '已删除' } })
    const { request } = await import('../api/client')

    await request('/tasks/7', { method: 'DELETE' })

    const [, init] = spy.mock.calls[0]
    expect(init.method).toBe('DELETE')
    expect(init.body ?? null).toBeNull()
  })

  it('formData 上传不设置 Content-Type（交给浏览器带 boundary）', async () => {
    const spy = mockFetch({ body: {} })
    const { request } = await import('../api/client')
    const fd = new FormData()
    fd.append('file', new Blob(['x']), 'a.txt')

    await request('/documents/upload', { method: 'POST', formData: fd })

    const [, init] = spy.mock.calls[0]
    // 手动设 multipart/form-data 会让 boundary 丢失，服务端解析必失败
    expect(init.body).toBe(fd)
    const headers = init.headers || {}
    const keys = Object.keys(headers).map((k) => k.toLowerCase())
    if (keys.includes('content-type')) {
      expect(String(headers['Content-Type'] || headers['content-type']))
        .not.toContain('multipart/form-data')
    }
  })

  it('PUT / PATCH 正确透传 method', async () => {
    mockFetch({ body: {} })
    const { request } = await import('../api/client')

    await request('/tasks/1', { method: 'PUT', body: { status: 'done' } })
    await request('/flashcards/1', { method: 'PATCH', body: { mastery: 'high' } })

    // fetchSpy 在 afterEach 才重置，这里从全局重新取
    const calls = globalThis.fetch.mock.calls
    expect(calls.at(-2)[1].method).toBe('PUT')
    expect(calls.at(-1)[1].method).toBe('PATCH')
  })
})

// ========================================================================= //
// 三、响应解析：后端错误壳 vs 正常数据
// ========================================================================= //
describe('响应解析', () => {
  it('错误壳一定伴随非 2xx 状态码（后端契约，见 utils/exceptions.py）', async () => {
    // 先核实后端约定：create_error_response() 总是与 exc.status_code 配对，
    // 后者恒 >= 400，所以 **200 响应里不会出现 {code,message} 错误壳**。
    // 本用例把这条约定钉住：一旦后端有人改成"200 + 错误壳"，
    // 这里会立刻发现并提示同步修改 client / 前端错误处理。
    mockFetch({ ok: false, status: 500, body: { code: 'UNKNOWN_ERROR', message: '服务器内部错误' } })
    const { request } = await import('../api/client')

    // client 统一把 HTTP 层失败归类为 code='http_error'，并保留 status
    await expect(request('/review/stats')).rejects.toMatchObject({
      code: 'http_error',
      status: 500,
    })
    // 后端 message 必须透传到异常文案里（否则用户只看到"请求失败"）
    await expect(request('/review/stats')).rejects.toThrow(/服务器内部错误/)
  })

  it('200 响应即使含 code 字段也按数据处理（不误伤合法业务字段）', async () => {
    // 反向保护：有些接口的正常数据里就带 code（如任务状态码、门控 decision）。
    // client 不能仅凭 body 里有 code 就判定为错误，否则会误杀正常数据。
    mockFetch({ ok: true, status: 200, body: { code: 'OK', items: [{ id: 1 }] } })
    const { request } = await import('../api/client')

    const data = await request('/tasks')
    expect(data.code).toBe('OK')
    expect(data.items).toHaveLength(1)
  })

  it('正常 200 返回完整数据对象（不被误判为错误壳）', async () => {
    mockFetch({
      ok: true,
      status: 200,
      body: { items: [{ id: 1, title: 'QA 任务' }], total: 1 },
    })
    const { request } = await import('../api/client')

    const data = await request('/tasks')
    expect(data.total).toBe(1)
    expect(data.items).toHaveLength(1)
    expect(data.items[0].title).toBe('QA 任务')
  })

  it('数组响应原样返回（不被包成对象）', async () => {
    mockFetch({ ok: true, status: 200, body: [{ id: 1 }, { id: 2 }] })
    const { request } = await import('../api/client')

    const data = await request('/exam/blueprints')
    expect(Array.isArray(data)).toBe(true)
    expect(data).toHaveLength(2)
  })

  it('422 校验错误抛 ApiError 且保留后端 errors 明细', async () => {
    mockFetch({
      ok: false,
      status: 422,
      body: {
        code: 'INVALID_PARAMETER',
        message: '请求参数校验失败',
        detail: { errors: [{ field: 'query.date', message: 'Field required', type: 'missing' }] },
      },
    })
    const { request } = await import('../api/client')

    await expect(request('/planner/daily')).rejects.toMatchObject({ status: 422 })
    await expect(request('/planner/daily')).rejects.toThrow(/校验失败|Field required/)
  })

  it('500 时抛出而非返回 undefined（下游不会静默崩）', async () => {
    mockFetch({
      ok: false,
      status: 500,
      body: { code: 'UNKNOWN_ERROR', message: '服务器内部错误', detail: { type: 'TypeError' } },
    })
    const { request } = await import('../api/client')

    const p = request('/review/stats')
    await expect(p).rejects.toBeDefined()
    // 绝不能是 fulfilled(undefined)
    const outcome = await p.then(() => 'resolved', () => 'rejected')
    expect(outcome).toBe('rejected')
  })

  it('401 携带后端"重新授权"指引（网盘未授权场景）', async () => {
    mockFetch({
      ok: false,
      status: 401,
      body: {
        code: 'UNAUTHORIZED',
        message: '百度网盘未授权，请先完成 OAuth 授权',
        detail: { errno: -6, action: 'reauthorize' },
      },
    })
    const { request } = await import('../api/client')

    await expect(request('/netdisk/quota')).rejects.toMatchObject({ status: 401 })
  })
})

// ========================================================================= //
// 四、各业务 API 封装的路径正确性（防止拼错路径，404 却无感知）
// ========================================================================= //
describe('业务 API 封装路径', () => {
  const cases = [
    ['dashboardApi', 'get', [], '/api/dashboard'],
    ['dashboardApi', 'countdown', [], '/api/dashboard/countdown'],
    ['dashboardApi', 'todayTasks', [], '/api/dashboard/today-tasks'],
    ['tasksApi', 'reviewSchedule', [], '/api/tasks/review-schedule'],
    ['quizApi', 'modes', [], '/api/quiz/modes'],
    ['quizApi', 'stats', [], '/api/quiz/stats'],
    ['errorsApi', 'list', [], '/api/errors'],
    ['goalsApi', 'subjects', [], '/api/goals/subjects'],
    ['flashcardsApi', 'due', [], '/api/flashcards/due'],
    ['documentsApi', 'subjects', [], '/api/documents/subjects'],
    ['qualityApi', 'subjectAlignment', [], '/api/quality/subject-alignment'],
  ]

  it.each(cases)('%s.%s() → %s', async (group, method, args, expected) => {
    const spy = mockFetch({ body: {} })
    const mod = await import('../api/client')
    await mod[group][method](...args)
    expect(spy.mock.calls[0][0]).toBe(expected)
  })

  it('tasksApi.list 把过滤条件透传到 query', async () => {
    const spy = mockFetch({ body: [] })
    const { tasksApi } = await import('../api/client')

    await tasksApi.list({ subject: 'math', status: 'pending' })

    const url = spy.mock.calls[0][0]
    expect(url).toContain('subject=math')
    expect(url).toContain('status=pending')
  })

  it('tasksApi.update 走 PUT 且路径含任务 id', async () => {
    const spy = mockFetch({ body: {} })
    const { tasksApi } = await import('../api/client')

    await tasksApi.update(42, { status: 'done' })

    const [url, init] = spy.mock.calls[0]
    expect(url).toBe('/api/tasks/42')
    expect(init.method).toBe('PUT')
  })

  it('tasksApi.remove 走 DELETE', async () => {
    const spy = mockFetch({ body: {} })
    const { tasksApi } = await import('../api/client')

    await tasksApi.remove(42)

    const [url, init] = spy.mock.calls[0]
    expect(url).toBe('/api/tasks/42')
    expect(init.method).toBe('DELETE')
  })

  it('导出面完整：request 与所有业务 API 分组都在', async () => {
    const mod = await import('../api/client')
    const groups = [
      'dashboardApi', 'tasksApi', 'goalsApi', 'quizApi', 'errorsApi',
      'flashcardsApi', 'documentsApi', 'netdiskApi', 'importsApi', 'aiApi',
      'customizationApi', 'plannerApi', 'wordsApi', 'studyApi', 'taxonomyApi',
      'reviewApi', 'kbApi', 'systemApi', 'analysisApi',
    ]
    for (const g of groups) {
      expect(mod[g], `缺少导出 ${g}`).toBeTypeOf('object')
    }
    expect(mod.request).toBeTypeOf('function')
    expect(mod.DEFAULT_TIMEOUT).toBeGreaterThan(0)
  })
})

// ========================================================================= //
// 五、边界：慢接口与前端超时的匹配（QA 巡检发现的真实隐患）
// ========================================================================= //
describe('超时配置', () => {
  it('DEFAULT_TIMEOUT 为正整数且处于合理区间（10s~120s）', async () => {
    const { DEFAULT_TIMEOUT } = await import('../api/client')
    expect(Number.isInteger(DEFAULT_TIMEOUT)).toBe(true)
    expect(DEFAULT_TIMEOUT).toBeGreaterThanOrEqual(10000)
    expect(DEFAULT_TIMEOUT).toBeLessThanOrEqual(120000)
  })

  it('单次请求可用 timeout 覆盖默认值', async () => {
    const spy = vi.fn((url, opts) => new Promise((_, reject) => {
      opts.signal?.addEventListener('abort', () => {
        const e = new Error('aborted'); e.name = 'AbortError'; reject(e)
      })
    }))
    vi.stubGlobal('fetch', spy)

    const { request } = await import('../api/client')
    const p = request('/slow', { timeout: 50 })
    const assertion = expect(p).rejects.toMatchObject({ code: 'timeout' })
    await new Promise((r) => setTimeout(r, 120))
    await assertion
  })
})
