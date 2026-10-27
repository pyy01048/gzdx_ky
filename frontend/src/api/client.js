/* ============================================================
   考研档案 · FastAPI 真实后端 API 客户端（全接口覆盖）
   统一封装 fetch，通过 vite /api 代理访问 127.0.0.1:8000
   全部对齐 backend-main-fastapi/routers/* 契约
   ============================================================ */

import { MUTATION_EVENT } from './mutationEvent'

const BASE = '/api'

/* ------------------------------------------------------------------
 * 默认超时：后端存在耗时 25s+ 的接口（embedding/ 重建/ 体检等），
 * 若前端不设上限，一个慢接口会让页面永久 loading（用户感知为"卡死"）。
 * 可在单次请求通过 options.timeout 覆盖（毫秒）；传 0 表示不限制。
 * ------------------------------------------------------------------ */
const DEFAULT_TIMEOUT = 30000

/* AI 生成类接口的专用超时（毫秒）。
   /api/goals/strategy 内部 await 真实 AI 调用，实测 19.9s~29.4s，
   紧贴DEFAULT_TIMEOUT(30s) 会导致间歇性"请求超时"误报，故单独放宽。
   这些接口是同步阻塞的（后端未提供进度查询），不能用 SSE，故只能放宽超时。 */
const AI_TIMEOUT = 90000

/* 知识库→题目全库扫描专用超时（毫秒）。
   POST /api/kb-import/scan 会遍历已解析文档并逐题做去重比对，
   文档量大时耗时显著超过默认 30s，故单独放宽到 3 分钟。 */
const KB_IMPORT_SCAN_TIMEOUT = 180000

/** 自定义错误类型：便于调用方按code 分支处理（超时/网络/ HTTP）。 */
export class ApiError extends Error {
  constructor(message, { code = 'http_error', status = 0, data = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.data = data
  }
}

/**
 * 从后端错误体中提取可展示给用户的文本。
 *
 * 权威壳是 utils/exceptions.py 的 ``{code, message, detail?}``（#19 接口约定巡检把
 * 全站 GET/POST 的非 2xx 都收口到这个形状），所以 **message 优先**。
 * ``detail`` 现在只剩结构化附注（``{path}``、``{action}``），排在 message 之后——
 * 早先它排第一，于是 404 toast 会把 ``{"path": "/api/..."}`` 直接甩给用户看。
 * 保留 ``detail`` 分支是为了兼容尚未迁移的历史端点与 422 校验数组。
 */
function extractDetail(data, fallback) {
  if (data === null || data === undefined) return fallback
  const detail = data.message || data.detail || data.error
  if (detail === undefined || detail === null || detail === '') return fallback
  if (typeof detail === 'string') return detail
  // FastAPI 422 校验错误为对象数组，压平为可读文本
  if (Array.isArray(detail)) {
    const text = detail
      .map((d) => (d && (d.msg || d.message)) || '')
      .filter(Boolean)
      .join('；')
    if (text) return text
  }
  try {
    return JSON.stringify(detail)
  } catch {
    return fallback
  }
}

/** 组合外部 signal 与超时 signal（任一触发即中断）。 */
function composeSignals(external, controller) {
  if (!external) return controller.signal
  if (typeof AbortController === 'undefined') return controller.signal
  const anyAbort = typeof AbortSignal !== 'undefined' && AbortSignal.any
  if (anyAbort) return anyAbort([external, controller.signal])
  const onAbort = () => controller.abort()
  external.addEventListener('abort', onAbort)
  controller.signal.addEventListener('abort', () => external.removeEventListener('abort', onAbort))
  return controller.signal
}

/**
 * 浏览器自己发起的字节流地址（iframe / 新窗口 / a[download]）。
 * 会话走 httpOnly cookie（同源自动携带），地址里不再放任何凭据。
 */
export function fileUrl(path, params = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  })
  const s = q.toString()
  return `${BASE}${path}${s ? `?${s}` : ''}`
}

// access 过期时并发请求共用同一次 refresh，避免 N 个 401 打出 N 次刷新
let refreshing = null
function refreshSession() {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'same-origin' })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => { setTimeout(() => { refreshing = null }, 0) })
  }
  return refreshing
}

// 精确路径：这些接口的 401 是业务语义（登录失败/刷新失败），不是 session 过期信号
const NO_REFRESH_PATHS = ['/auth/login', '/auth/refresh', '/auth/logout', '/auth/status']
// 前缀路径：整域的 401 都可能来自第三方资源状态（如网盘授权失效），
// 绝不能触发全局 session 修复把用户踢下线（2026-10-18 登录后卡死事故）
const NO_REFRESH_PREFIXES = ['/netdisk/']
const isNoRefreshPath = (p) =>
  NO_REFRESH_PATHS.includes(p) || NO_REFRESH_PREFIXES.some((pre) => p.startsWith(pre))

/* ------------------------------------------------------------------
 * 后端三态判定（P2-2）
 *
 * 旧口径只有「离线 / 在线」两态，且由 hydrate 的「任意一个数据域成功」推导，
 * 于是一个 500 接口就能把整站说成「离线：数据来自本地缓存」，与 /api/health
 * 正常的事实矛盾。现在拆成三态：
 *   online   —— health 可达 且 最近窗口内没有失败接口
 *   degraded —— health 可达，但最近窗口内有 5xx / 网络 / 超时（部分服务异常）
 *   offline  —— health 本身不可达（才说「数据来自本地缓存」）
 *
 * 失败集合按「接口路径」去重：同一接口连续失败只算 1 项，页面据此给出
 * 「N 项接口异常」而不是按请求次数刷屏；该路径再次成功即从集合里移除。
 * ------------------------------------------------------------------ */
export const FAILURE_WINDOW_MS = 5 * 60 * 1000
const HEALTH_PATH = '/health'
const recentFailures = new Map() // path -> { path, status, at }
const backendStatusListeners = new Set()
let backendState = { state: 'unknown', failures: [], checkedAt: 0 }
let probeTimer = null

/** 最近窗口内的失败接口（按时间倒序，已按路径去重）。 */
export function getRecentFailures() {
  const cutoff = Date.now() - FAILURE_WINDOW_MS
  for (const [key, item] of recentFailures) {
    if (item.at < cutoff) recentFailures.delete(key)
  }
  return Array.from(recentFailures.values()).sort((a, b) => b.at - a.at)
}

/** 当前三态快照。 */
export function getBackendState() {
  return backendState
}

/** 订阅三态变化，返回取消订阅函数（立即回放一次当前快照）。 */
export function subscribeBackendState(fn) {
  if (typeof fn !== 'function') return () => {}
  backendStatusListeners.add(fn)
  fn(backendState)
  return () => { backendStatusListeners.delete(fn) }
}

function emitBackendState() {
  for (const fn of backendStatusListeners) {
    try { fn(backendState) } catch { /* 订阅方异常不影响其它订阅 */ }
  }
}

/* 失败登记后延迟重判：一次页面加载会并发多个请求，合并成一次 health 探测 */
function scheduleProbe() {
  if (!backendStatusListeners.size) return
  clearTimeout(probeTimer)
  probeTimer = setTimeout(() => { probeBackend().catch(() => {}) }, 400)
}

function noteFailure(path, status) {
  if (path === HEALTH_PATH) return
  recentFailures.set(path, { path, status, at: Date.now() })
  scheduleProbe()
}

function noteSuccess(path) {
  if (path === HEALTH_PATH) return
  if (recentFailures.delete(path)) scheduleProbe()
}

/**
 * 探测后端三态：只有 health 不可达才算 offline。
 * 刻意用裸 fetch 而不是 request()：health 不应该参与失败登记，也不该触发
 * 401 的全局会话修复（否则探测本身会把用户踢下线）。
 */
export async function probeBackend() {
  let reachable = true
  try {
    if (typeof fetch !== 'function') {
      reachable = false
    } else {
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
      const timer = controller ? setTimeout(() => controller.abort(), 8000) : null
      try {
        const resp = await fetch(`${BASE}${HEALTH_PATH}`, {
          credentials: 'same-origin',
          ...(controller ? { signal: controller.signal } : {}),
        })
        reachable = !!resp && resp.ok
      } finally {
        if (timer) clearTimeout(timer)
      }
    }
  } catch {
    reachable = false
  }
  const failures = getRecentFailures()
  backendState = {
    state: !reachable ? 'offline' : (failures.length ? 'degraded' : 'online'),
    failures,
    checkedAt: Date.now(),
  }
  emitBackendState()
  return backendState
}

/**
 * 统一请求封装。
 *
 * 健壮性约定（所有下游调用方可依赖）：
 * 1. 永不静默返回 undefined —— 失败一律 reject 一个带 code 的 ApiError；
 * 2. 超时可中断（AbortController），不会永久挂起；
 * 3. 错误信息透传（提取 FastAPI detail），用户可见；
 * 4. 成功时返回解析后的 JSON（无 JSON 体则返回 null，保持既有行为）。
 *
 * @param {string} path 以 / 开头的接口路径（不含 /api 前缀）
 * @param {object} [options]
 * @param {'GET'|'POST'|'PUT'|'DELETE'|'PATCH'} [options.method='GET']
 * @param {any}      [options.body]     JSON 序列化的请求体
 * @param {object}   [options.params]   查询参数（undefined/null/'' 自动跳过）
 * @param {FormData} [options.formData] multipart 上传体
 * @param {number}   [options.timeout]  超时毫秒数，0 表示不限制
 * @param {AbortSignal} [options.signal] 外部中断信号
 * @returns {Promise<any>} 解析后的响应体
 * @throws  {ApiError} code 为 'timeout' | 'network' | 'aborted'，
 *          HTTP 层失败时为后端错误壳的 code（缺省时 'http_error'）
 */
async function request(path, options = {}) {
  const {
    method = 'GET', body, params, formData, timeout = DEFAULT_TIMEOUT, signal: externalSignal, _retried = false,
  } = options
  let url = `${BASE}${path}`
  if (params) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    }
    const s = qs.toString()
    if (s) url += `?${s}`
  }
  const opts = { method, headers: {}, credentials: 'same-origin' }
  if (formData) {
    opts.body = formData // 浏览器自动设置 multipart boundary
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }

  // ---- 超时控制 ----
  const useTimeout = Number(timeout) > 0 && typeof AbortController !== 'undefined'
  const controller = useTimeout ? new AbortController() : null
  let timedOut = false
  let timer = null
  if (controller) {
    opts.signal = composeSignals(externalSignal, controller)
    timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, Number(timeout))
  } else if (externalSignal) {
    opts.signal = externalSignal
  }

  let resp
  try {
    resp = await fetch(url, opts)
  } catch (e) {
    if (timedOut) {
      noteFailure(path, 0)
      throw new ApiError(`请求超时（${Math.round(Number(timeout) / 1000)}s）：${method} ${path}`, {
        code: 'timeout',
      })
    }
    // 调用方主动取消
    if (e && (e.name === 'AbortError' || externalSignal?.aborted)) {
      throw new ApiError(`请求已取消：${method} ${path}`, { code: 'aborted' })
    }
    noteFailure(path, 0)
    throw new ApiError(`网络异常，无法连接后端服务：${method} ${path}（${e?.message || e}）`, {
      code: 'network',
    })
  } finally {
    if (timer) clearTimeout(timer)
  }

  let data = null
  try {
    data = await resp.json()
  } catch {
    /* 无 JSON 体（204 / 空响应 / HTML 错误页 / 反代返回空体）时返回 null。
     *
     * 契约说明（务必阅读，勿改成返回 {}）：
     * - 返回 null 而非 {}，是为了让下游 `if (!data)` / `data?.x` 这类falsy 守卫生效；
     *   {} 是 truthy，会使这些守卫失效，反而把问题推到更深处的 .map崩溃。
     * - 因此**成功无体时也会 resolve(null) 而不 reject**，调用方必须防御 null：
     *     const d = await api.get(); if (!d) { /* 降级 *\/ }else { d.items.map(...) }
     * - 保持 null 的另一个理由：向后兼容。既有调用方（如 Words.jsx 的
     *   `backendDecks && backendDecks.length`）已按null 语义编写。
     * 错误场景（非 2xx）由下方 !resp.ok 分支抛出带人类可读 message 的 ApiError。
     */
    data = null
  }
  if (!resp.ok) {
    const authPath = isNoRefreshPath(path)
    if (resp.status === 401 && !authPath) {
      if (!_retried && await refreshSession()) {
        return request(path, { ...options, _retried: true })
      }
      window.dispatchEvent(new CustomEvent('auth:required', { detail: data }))
    } else if (resp.status === 403 && data?.code === 'PASSWORD_CHANGE_REQUIRED') {
      window.dispatchEvent(new CustomEvent('auth:password-change', { detail: data }))
    }
    // 只有 5xx 才是「服务异常」；4xx 是请求本身的问题（参数/权限/不存在），
    // 记进来会把用户输错一次搜索词也算成「部分服务异常」。
    if (resp.status >= 500) noteFailure(path, resp.status)
    throw new ApiError(extractDetail(data, `HTTP ${resp.status}`), {
      // 后端错误壳里的 code（RESOURCE_NOT_FOUND / DATA_CONFLICT…）透传给调用方分支；
      // 缺失时仍回退 'http_error'，让既有 `e.code === 'timeout'` 之类判断语义不变。
      code: (data && data.code) || 'http_error',
      status: resp.status,
      data,
    })
  }
  noteSuccess(path)
  /* 写操作成功 → 广播「数据已变更」，聚合中枢等订阅方据此失效缓存。
     只在 2xx 成功时发；GET / 失败请求不改变数据，不污染订阅方。 */
  if (method !== 'GET' && typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new CustomEvent(MUTATION_EVENT, { detail: { method, path } }))
  }
  return data
}

// 统一导出 request，供各业务 API client 复用（消除重复请求逻辑）
export { request, DEFAULT_TIMEOUT }

/* --------------------------------------------------------------------------
 * AI 流式对话（SSE）—— 显式错误分支（P0-5）
 *
 * 旧实现（utils/api.js 的 chatStream）把 SSE 的 error 事件**吞掉了**：
 *     try { handleEvent(JSON.parse(payload)) } catch (e) {
 *       if (e.message && e.message.includes('流式调用失败')) throw e
 *       /* 非 JSON 数据忽略 *\/
 *     }
 * 后端 error 事件带的真实文案是「AI 服务暂时不可用（xxx）：…」，并不含
 * 「流式调用失败」四个字，于是被当成噪声行静默丢弃。结果：HTTP 200 + 空流，
 * 用户点了快捷问题后界面既不出现回答也不出现错误提示，只能以为"卡住了"。
 *
 * 这里把流式失败显式分成四种可区分的 code，交给调用方分别渲染：
 *   network          —— fetch 直接失败 / 超时 / 连接中断
 *   http_error       —— 非 2xx（含 UNAUTHORIZED / 502 等，message 取后端壳的 message）
 *   ai_stream_error  —— HTTP 200 但 SSE 里带 type=error 事件（后端已带 code）
 *   ai_empty_stream  —— HTTP 200 但整条流没有任何 delta，也没有 error 事件
 * -------------------------------------------------------------------------- */
export async function aiChatStream(body, { onDelta, signal, timeout = AI_TIMEOUT } = {}) {
  const url = `${BASE}/ai/chat/stream`
  const useTimeout = Number(timeout) > 0 && typeof AbortController !== 'undefined'
  const controller = useTimeout ? new AbortController() : null
  let timedOut = false
  let timer = null
  const opts = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(body || {}),
  }
  if (controller) {
    opts.signal = composeSignals(signal, controller)
    timer = setTimeout(() => { timedOut = true; controller.abort() }, Number(timeout))
  } else if (signal) {
    opts.signal = signal
  }

  let resp
  try {
    resp = await fetch(url, opts)
  } catch (e) {
    if (timedOut) {
      throw new ApiError(`AI 响应超时（${Math.round(Number(timeout) / 1000)}s）`, { code: 'network' })
    }
    if (e && (e.name === 'AbortError' || signal?.aborted)) {
      throw new ApiError('AI 请求已取消', { code: 'aborted' })
    }
    throw new ApiError(`网络异常，无法连接 AI 服务（${e?.message || e}）`, { code: 'network' })
  } finally {
    if (timer) clearTimeout(timer)
  }

  if (!resp.ok) {
    let data = null
    try { data = await resp.json() } catch { data = null }
    if (resp.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:required', { detail: data }))
    }
    throw new ApiError(extractDetail(data, `AI 接口错误 ${resp.status}`), {
      code: (data && data.code) || 'http_error',
      status: resp.status,
      data,
    })
  }

  // 没有 ReadableStream（老浏览器 / 反代缓冲了整条流）时不能静默返回空串
  if (!resp.body || typeof resp.body.getReader !== 'function') {
    throw new ApiError('当前环境不支持流式响应，AI 未返回任何内容', { code: 'ai_empty_stream' })
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let full = ''

  const handleEvent = (ev) => {
    if (!ev || typeof ev !== 'object') return
    if (ev.type === 'error') {
      // ← 关键：error 事件必须向上抛，绝不吞掉
      throw new ApiError(ev.message || 'AI 流式调用失败', {
        code: 'ai_stream_error',
        data: ev,
      })
    }
    if (ev.type === 'delta') {
      full += ev.content || ''
      onDelta?.({ content: ev.content || '' })
      return
    }
    if (ev.type === 'meta') { onDelta?.({ meta: true, rag: !!ev.rag }); return }
    if (ev.type === 'provider') { onDelta?.({ provider: ev.name || '' }); return }
    onDelta?.(ev)
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, idx).trim()
        buf = buf.slice(idx + 1)
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (!payload) continue
        try {
          handleEvent(JSON.parse(payload))
        } catch (e) {
          if (e instanceof ApiError) throw e
          /* 单行解析失败：忽略噪声行，不中断整条流 */
        }
      }
    }
  } catch (e) {
    if (e instanceof ApiError) throw e
    if (e && e.name === 'AbortError') throw new ApiError('AI 请求已取消', { code: 'aborted' })
    throw new ApiError(`AI 流式连接中断（${e?.message || e}）`, { code: 'network' })
  } finally {
    reader.releaseLock()
  }

  // 200 但一个 delta 都没有：显式报空流，而不是让调用方拿到空串后静默
  if (!full) {
    throw new ApiError('AI 服务返回了空回复（HTTP 200 但没有输出任何内容）', { code: 'ai_empty_stream' })
  }
  return { text: full }
}

/* ---------------- 分页取全量（与后端 MAX_PAGE_SIZE 同一口径） ----------------
 *
 * 后端 utils/response.py 把所有分页/limit 入参钉成 ``ge=1, le=200``，且
 * tests/test_api_conventions.py 会巡检这条。关键一点：**page_size=500 不是
 * "服务端帮你截到 200"，而是 422 校验失败**。
 *
 * 这正是此前的真实故障：sync 的 tasks/notebook/cards 三个域、Cards 页、
 * 错题本页的知识点候选、真题按套卷取题都写死 page_size=500/1000，
 * 请求一律 422，被 catch 成空数组 —— 用户看到的就是"后端有数据，页面永远空"。
 * 要全量就得逐页翻，所以下面这个 helper 是唯一合法入口。
 */
export const MAX_PAGE_SIZE = 200

/** 从一页响应里取出条目数组；裸数组响应也算一页。 */
function pageItems(resp, aliasKeys) {
  if (Array.isArray(resp)) return resp
  if (!resp || typeof resp !== 'object') return []
  for (const key of ['items', ...aliasKeys]) {
    if (Array.isArray(resp[key])) return resp[key]
  }
  return []
}

/**
 * 逐页取回一个分页端点的全部条目。
 *
 * @param {(params: {page: number, page_size: number}) => Promise<any>} fetchPage 单页请求
 * @param {{keys?: string[], pageSize?: number, maxItems?: number}} [opts]
 *        keys      —— items 之外的条目字段别名（部分老端点用 questions/errors/cards）；
 *        maxItems  —— 安全上限，total 异常或后端返回巨大页数时不至于无限翻页。
 * @returns {Promise<any[]>} 全部条目（顺序 = 后端分页顺序）
 */
export async function fetchAllPages(fetchPage, opts = {}) {
  const pageSize = Math.min(opts.pageSize || MAX_PAGE_SIZE, MAX_PAGE_SIZE)
  const aliasKeys = opts.keys || []
  const cap = opts.maxItems || 5000
  const out = []
  let page = 1
  for (;;) {
    const resp = await fetchPage({ page, page_size: pageSize })
    out.push(...pageItems(resp, aliasKeys))
    if (Array.isArray(resp)) break // 无分页壳：这一包就是全量
    const pages = typeof resp?.total_pages === 'number'
      ? resp.total_pages
      : (typeof resp?.total === 'number' ? Math.ceil(resp.total / pageSize) : 1)
    page += 1
    if (page > pages || out.length >= cap) break
  }
  return out
}

/* ---------------- Dashboard 驾驶舱 ---------------- */
export const dashboardApi = {
  /** 首屏唯一聚合出口（D-01…D-11）：倒计时/目标/KPI/进度环/热力图/趋势/未来负荷 */
  summary: () => request('/dashboard/summary'),
  get: () => request('/dashboard'),
  countdown: () => request('/dashboard/countdown'),
  todayTasks: () => request('/dashboard/today-tasks'),
  stats: () => request('/dashboard/stats'),
  weakness: () => request('/dashboard/weakness'),
  reviewQueue: (limit = 50) => request(`/dashboard/review-queue?limit=${limit}`)
}

/* ---------------- V11 学习洞察（今日引导/周报/智能组卷） ---------------- */
export const insightApi = {
  today: () => request('/insight/today'),
  weeklyReport: () => request('/insight/weekly-report'),
  smartPaper: (body) => request('/insight/smart-paper', { method: 'POST', body }),
}

/* ---------------- Tasks 任务 ---------------- */
export const tasksApi = {
  list: (params) => request('/tasks', { params }),
  create: (body) => request('/tasks', { method: 'POST', body }),
  update: (id, body) => request(`/tasks/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/tasks/${id}`, { method: 'DELETE' }),
  complete: (id) => request(`/tasks/${id}/complete`, { method: 'POST' }),
  uncomplete: (id) => request(`/tasks/${id}/uncomplete`, { method: 'POST' }),
  reviewSchedule: () => request('/tasks/review-schedule'),
  aiGenerate: (body) => request('/tasks/ai-generate', { method: 'POST', body })
}

/* 非流式 AI 调用的超时上限（毫秒）。
   后端 /api/goals/strategy 等接口内部 await 真实 AI 调用，
   实测耗时 19.9s~29.4s，接近默认 30s 上限，会导致间歇性"请求超时"。
   故该接口单独放宽到 90s；其余接口沿用 DEFAULT_TIMEOUT。 */
/* ---------------- Goals 目标 ---------------- */
export const goalsApi = {
  list: () => request('/goals'),
  update: (body) => request('/goals', { method: 'PUT', body }),
  // 备考科目配置（考试口径 + 专业课支撑）
  subjects: () => request('/goals/subjects'),
  updateSubjects: (body) => request('/goals/subjects', { method: 'PUT', body }),
  // 届数 / 初试日期（唯一权威出口 services/exam_calendar；届可随时调整）
  examCalendar: () => request('/goals/exam-calendar'),
  updateExamCalendar: (body) => request('/goals/exam-calendar', { method: 'PUT', body }),
  university: () => request('/goals/university'),
  universitySearch: (params) => request('/goals/university/search', { method: 'POST', params }),
  // AI 生成备考策略：后端同步阻塞真实 AI 调用，实测 19.9s~29.4s，需放宽超时
  strategy: () => request('/goals/strategy', { timeout: AI_TIMEOUT })
}

/* ---------------- Quiz 刷题中心 ---------------- */
export const quizApi = {
  list: (params) => request('/quiz/questions', { params }),
  questions: (params) => request('/quiz/questions', { params }),
  create: (body) => request('/quiz/questions', { method: 'POST', body }),
  update: (id, body) => request(`/quiz/questions/${id}`, { method: 'PUT', body }),

  remove: (id) => request(`/quiz/questions/${id}`, { method: 'DELETE' }),
  submit: (body) => request('/quiz/submit', { method: 'POST', body }),
  modes: () => request('/quiz/modes'),
  stats: () => request('/quiz/stats'),
  subjects: () => request('/quiz/subjects'),
  sections: (params) => request('/quiz/sections', { params }),
  years: (params) => request('/quiz/years', { params }),
  papersIndex: (params) => request('/quiz/papers-index', { params }),
  // 考频聚合：dimension = kp | chapter | paper（M2-7 考频分析页消费）
  frequency: (params) => request('/quiz/frequency', { params }),
  // 错因分布（错题复盘页筛选项）：{total, items:[{reason, count}]}
  wrongReasons: (params) => request('/quiz/wrong-reasons', { params }),
  // 题库 CSV 导出（blob 下载，Excel 兼容 BOM）
  exportCsv: async (params) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params || {})) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    }
    const s2 = qs.toString()
    const resp = await fetch(`${BASE}/quiz/export${s2 ? '?' + s2 : ''}`, { credentials: 'same-origin' })
    if (!resp.ok) throw new Error(`导出失败（HTTP ${resp.status}）`)
    const blob = await resp.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `quiz_questions_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  },
  // 题库批量删除（硬删除，上限 500）
  batchDelete: (ids) => request('/quiz/batch-delete', { method: 'POST', body: ids }),
  // P0-1 刷题生词提取：POST /api/quiz/{question_id}/extract-words
  // 响应 {question_id, words: [{word, exists, source}]}，exists=true 表示已在当前用户词库
  extractWords: (questionId) => request(`/quiz/${questionId}/extract-words`, { method: 'POST' }),
  // P0-2 主观题 AI 批改：POST /api/quiz/grade-subjective
  // 请求 {question_id, my_answer, max_score}；响应 {score, max_score, evaluation, reference_answer}
  gradeSubjective: (body) => request('/quiz/grade-subjective', { method: 'POST', body }),
  // P1-E 多Agent编排答疑：POST /api/ai/tutoring/orchestrated
  // 请求 {question_id, my_answer?, subject?}；响应 {answer, trace, confidence, degraded}
  orchestratedTutoring: (body) => request('/ai/tutoring/orchestrated', { method: 'POST', body, timeout: AI_TIMEOUT }),
}

/* ---------------- 薄弱点闭环推荐（55号 DeepTutor 方案 P0-C） ----------------
 * 三信号融合薄弱点 + 变式题生成入库 + 掌握门控。
 * 依赖 quizApi 之上的 recommend 域，独立导出便于调用方按需引入。
 */
export const recommendApi = {
  // GET /api/recommend/weak-points?subject=&limit= —— 三信号融合薄弱点
  weakPoints: (params) => request('/recommend/weak-points', { params }),
  // POST /api/recommend/variants  {kp_id, count} —— 生成变式题入库，返回 {created, kp_id, ...}
  variants: (body) => request('/recommend/variants', { method: 'POST', body, timeout: AI_TIMEOUT }),
  // POST /api/recommend/mastery-gate {kp_id, consecutive_required} —— 掌握门控判定
  masteryGate: (body) => request('/recommend/mastery-gate', { method: 'POST', body }),
}

/* 从 Content-Disposition 解析 RFC 5987 文件名，失败时用 fallback */
function parseContentDispositionFilename(header, fallback) {
  if (header) {
    const m = header.match(/filename\*=UTF-8''([^;]+)/i) || header.match(/filename="?([^";]+)"?/i)
    if (m && m[1]) {
      try { return decodeURIComponent(m[1]) } catch { return m[1] }
    }
  }
  return fallback
}

/** 通用二进制下载：GET 接口返回 blob，按响应头文件名保存。 */
async function downloadBlob(path, params = {}, fallbackName = 'download') {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, v)
  }
  const s2 = qs.toString()
  const resp = await fetch(`${BASE}${path}${s2 ? '?' + s2 : ''}`, { credentials: 'same-origin' })
  if (!resp.ok) throw new Error(`导出失败（HTTP ${resp.status}）`)
  const blob = await resp.blob()
  const filename = parseContentDispositionFilename(
    resp.headers.get('Content-Disposition'),
    fallbackName,
  )
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

/* ---------------- Errors 错题本 ---------------- */
export const errorsApi = {
  exportCsv: async (params) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params || {})) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    }
    const s2 = qs.toString()
    const resp = await fetch(`${BASE}/errors/export${s2 ? '?' + s2 : ''}`, { credentials: 'same-origin' })
    if (!resp.ok) throw new Error(`导出失败（HTTP ${resp.status}）`)
    const blob = await resp.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `errors_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  },
  // PDF 导出（对标「不背单词」纸质导出）：支持与列表一致的筛选参数
  exportPdf: (params) => downloadBlob('/errors/export-pdf', params, `错题本_${new Date().toISOString().slice(0, 10)}.pdf`),
  batchDelete: (ids) => request('/errors/batch-delete', { method: 'POST', body: ids }),

  list: (params) => request('/errors', { params }),
  // 错题统计（唯一口径：与仪表盘 stats.active_errors/due_errors 同一聚合函数）
  stats: (params) => request('/errors/stats', { params }),
  create: (body) => request('/errors', { method: 'POST', body }),
  update: (id, body) => request(`/errors/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/errors/${id}`, { method: 'DELETE' }),
  // review: 后端无 /api/errors/{id}/review 接口，错题复习请用 aiAnalyze / graduate
  ocr: (formData) => request('/errors/ocr', { method: 'POST', formData }),
  aiAnalyze: (id) => request(`/errors/${id}/ai-analyze`, { method: 'POST' }),
  graduate: (id) => request(`/errors/${id}/graduate`, { method: 'POST' }),
  // 知识点关联：GET 返回 {error_id, items:[]}；POST body {knowledge_point_id}
  knowledgePoints: (id) => request(`/errors/${id}/knowledge-points`),
  linkKnowledge: (id, body) => request(`/errors/${id}/link-knowledge`, { method: 'POST', body }),
  unlinkKnowledge: (linkId) => request(`/errors/links/${linkId}`, { method: 'DELETE' })
}

/* ---------------- Flashcards 记忆卡片 ---------------- */
export const flashcardsApi = {
  list: (params) => request('/flashcards', { params }),
  create: (body) => request('/flashcards', { method: 'POST', body }),
  batchCreate: (body) => request('/flashcards/batch', { method: 'POST', body }),
  review: (id, body) => request(`/flashcards/${id}/review`, { method: 'PUT', body }),
  due: (params) => request('/flashcards/due', { params }),
  remove: (id) => request(`/flashcards/${id}`, { method: 'DELETE' })
}

/* ---------------- Documents 文档知识库 ---------------- */
export const documentsApi = {
  list: (params) => request('/documents', { params }),
  subjects: () => request('/documents/subjects'),
  upload: (formData) => request('/documents/upload', { method: 'POST', formData }),
  parse: (id) => request(`/documents/${id}/parse`, { method: 'POST' }),
  parseAll: () => request('/documents/parse-all', { method: 'POST' }),
  knowledgePoints: (id) => request(`/documents/${id}/knowledge-points`),
  chunks: (id) => request(`/documents/${id}/chunks`),
  // max_chars：正文字符数上限（后端按字符截断并回 truncated 标记），不是行分页参数
  getContent: (id, maxChars) => request(`/documents/${id}/content`, { params: { max_chars: maxChars } }),
  // 原文字节流：浏览器直接打开的地址（预览用 inline、下载用 attachment）
  rawUrl: (id) => fileUrl(`/documents/${id}/raw`),
  downloadUrl: (id) => fileUrl(`/documents/${id}/download`),
  generateQuiz: (id, body) => request(`/documents/${id}/generate-quiz`, { method: 'POST', body }),
  remove: (id) => request(`/documents/${id}`, { method: 'DELETE' }),
  ocrImage: (formData) => request('/documents/ocr', { method: 'POST', formData }),
  // V2.0 智能分析：长文本识别 + 自动分类知识点/题目/真题
  analyze: (id, params) => request(`/documents/${id}/analyze`, { method: 'POST', params }),
  extractKnowledgePoints: (id) => request(`/documents/${id}/extract-knowledge-points`, { method: 'POST' }),
  extractQuestions: (id) => request(`/documents/${id}/extract-questions`, { method: 'POST' }),
  analyzeBatch: (body) => request('/documents/analyze-batch', { method: 'POST', body }),
  // V3.0 题目预览与人工编辑
  previewQuestions: (id) => request(`/documents/${id}/preview-questions`, { method: 'POST' }),
  confirmQuestions: (id, body) => request(`/documents/${id}/confirm-questions`, { method: 'POST', body }),
}

/* ---------------- 知识库 → 刷题库 批量识别导入（V8 阶段3） ----------------
   两步式：
   ① scan  —— 只读扫描（全库或 doc_ids 分批），返回「文档 → 候选题」+ already_exists 去重标记，
             绝不写库；前端据此做预览、勾选。全库实测约 5 分钟，建议分批。
   ② confirm —— 把用户勾选的候选题写入题库（source=知识库:文档名），
             body 契约 {selected:[{doc_id, index}]}，index 取 scan 响应里候选自带的文档内下标；
             返回 {inserted, skipped_existing, out_of_range, by_subject}。
   契约以 routers/kb_import.py 为准；前端已对 items/candidates 做数组容错。 */
export const kbImportApi = {
  // body: { doc_ids?: number[] }；空对象 = 全库扫描
  scan: (body = {}) => request('/kb-import/scan', { method: 'POST', body, timeout: KB_IMPORT_SCAN_TIMEOUT }),
  // body: { selected: [ {doc_id, index} ] } —— 仅传用户勾选候选的文档内下标
  confirm: (body) => request('/kb-import/confirm', { method: 'POST', body, timeout: KB_IMPORT_SCAN_TIMEOUT }),
}

/* ---------------- Netdisk 网盘联动 ---------------- */
export const netdiskApi = {
  authUrl: (redirectUri = 'oob') => request('/netdisk/auth-url', { params: { redirect_uri: redirectUri } }),
  callback: (code, redirectUri = 'oob') => request('/netdisk/callback', { method: 'POST', params: { code, redirect_uri: redirectUri } }),
  // token 生命周期：过期时间与手动刷新
  tokenStatus: () => request('/netdisk/token-status'),
  refreshToken: () => request('/netdisk/refresh-token', { method: 'POST' }),
  files: (params) => request('/netdisk/files', { params }),
  // 找资料：递归列目录 + 关键词搜索（考研资料目录层级深，搜索是主入口）
  recursiveFiles: (path = '/', maxItems = 2000) =>
    request('/netdisk/recursive-files', { params: { path, max_items: maxItems } }),
  search: (keyword, params) => request('/netdisk/search', { params: { keyword, ...params } }),
  quota: () => request('/netdisk/quota'),
  sync: (path = '/') => request('/netdisk/sync', { method: 'POST', params: { path } }),
  preview: (fileId) => request(`/netdisk/preview/${fileId}`),
  // 网盘原文取流必须走后端代理：百度 dlink 强制 User-Agent: pan.baidu.com，浏览器直连必 403
  contentUrl: (fileId, disposition = 'inline') =>
    fileUrl(`/netdisk/files/${fileId}/content`, { disposition }),
  // 目录浏览页只有 fs_id，没有本地记录 id，所以后端还有一条按 fs_id 取流的入口
  contentUrlByFsid: (fsId, disposition = 'inline') =>
    fileUrl('/netdisk/content', { fs_id: fsId, disposition }),
  classify: () => request('/netdisk/classify', { method: 'POST' }),
  // 网盘文件 → 本地知识库
  ingest: (fsId) => request('/netdisk/ingest', { method: 'POST', body: { fs_id: fsId } }),
  ingestAll: () => request('/netdisk/ingest-all', { method: 'POST' }),
  platformConfigs: () => request('/netdisk/platform-configs'),
  platformConfig: (platform) => request(`/netdisk/platform-config/${platform}`),
  updatePlatformConfig: (platform, body) => request(`/netdisk/platform-config/${platform}`, { method: 'PUT', body }),
  testConnection: (platform) => request(`/netdisk/test-connection/${platform}`, { method: 'POST' })
}

/* ---------------- Imports 数据导入 ---------------- */
export const importsApi = {
  scan: (params) => request('/imports/scan', { method: 'POST', params }),
  scanStatus: (taskId) => request(`/imports/scan/${taskId}`),
  scanCancel: (taskId) => request(`/imports/scan/${taskId}/cancel`, { method: 'POST' }),
  stats: () => request('/imports/stats')
}

/* ---------------- AI 服务 ---------------- */
export const statsApi = {
  overview: (params) => request('/stats/overview', { params }),
}

export const aiApi = {
  providers: () => request('/ai/providers'),
  saveProvider: (body) => request('/ai/providers', { method: 'POST', body }),
  updateProvider: (id, body) => request(`/ai/providers/${id}`, { method: 'PUT', body }),
  removeProvider: (id) => request(`/ai/providers/${id}`, { method: 'DELETE' }),
  // 连通性测试（后端服务端发起，无浏览器 CORS 限制）
  testProvider: (id) => request(`/ai/providers/${id}/test`, { method: 'POST' }),
  // T1 路由模式（auto互备/仅本地/仅云端，热切换）
  getRouting: () => request('/ai/routing'),
  setRouting: (mode) => request('/ai/routing', { method: 'PUT', body: { mode } }),
  // T4 电路读图：图片上传（multipart）+ 带图智能路由对话（Agentic 状态机，
  // qwen2.5vl 读图可能较慢，超时放宽到 320s > 后端 300s 护栏）
  uploadImage: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/ai/upload-image', { method: 'POST', formData: fd, timeout: 60000 })
  },
  chatRouter: (body) => request('/ai/chat/router', { method: 'POST', body, timeout: 320000 }),
  chat: (body) => request('/ai/chat', { method: 'POST', body }),
  explain: (body) => request('/ai/explain', { method: 'POST', body }),
  gradeEssay: (body) => request('/ai/grade-essay', { method: 'POST', body }),
  analyzeSentence: (body) => request('/ai/analyze-sentence', { method: 'POST', body }),
  generatePlan: (body) => request('/ai/generate-plan', { method: 'POST', body }),
  ragSearch: (body) => request('/ai/rag-search', { method: 'POST', body }),
  // 本地模型（Ollama）
  localStatus: () => request('/ai/local/status'),
  localModels: () => request('/ai/local/models'),
  localTest: (model, prompt) => request('/ai/local/test', { method: 'POST', params: { model, prompt } }),
  // 模型选型：硬件画像 / 全部档案 / 分科推荐
  modelCatalog: () => request('/ai/models/catalog'),
  modelHardware: () => request('/ai/models/hardware'),
  modelRecommend: (params) => request('/ai/models/recommend', { params }),
}

/* ---------------- Customization 快捷链接 / 系统设置 ---------------- */
export const customizationApi = {
  links: (params) => request('/links', { params }),
  createLink: (body) => request('/links', { method: 'POST', body }),
  updateLink: (id, body) => request(`/links/${id}`, { method: 'PUT', body }),
  deleteLink: (id) => request(`/links/${id}`, { method: 'DELETE' }),
  settings: () => request('/settings'),
  updateSettings: (body) => request('/settings', { method: 'PUT', body })
}

/* ---------------- Planner 学习计划表 ---------------- */
export const plannerApi = {
  // 日计划
  getDaily: (date) => request('/planner/daily', { params: { date } }),
  saveDaily: (body) => request('/planner/daily', { method: 'POST', body }),
  getDailyRange: (start, end) => request('/planner/daily/range', { params: { start, end } }),
  // 月计划
  getMonth: (year, month) => request('/planner/month', { params: { year, month } }),
  saveMonth: (body) => request('/planner/month', { method: 'POST', body }),
  // 周计划
  getWeek: (weekStart) => request('/planner/week', { params: { week_start: weekStart } }),
  saveWeek: (body) => request('/planner/week', { method: 'POST', body }),
  // 艾宾浩斯
  listEbbinghaus: (subject) => request('/planner/ebbinghaus', { params: { subject } }),
  createEbbinghaus: (body) => request('/planner/ebbinghaus', { method: 'POST', body }),
  markEbbinghausReview: (id, cycle) => request(`/planner/ebbinghaus/${id}/review/${cycle}`, { method: 'POST' }),
  updateEbbinghausReviewTime: (id, body) => request(`/planner/ebbinghaus/${id}/review-time`, { method: 'PUT', body }),
  updateEbbinghausCycles: (id, body) => request(`/planner/ebbinghaus/${id}/cycles`, { method: 'PUT', body }),
  deleteEbbinghaus: (id) => request(`/planner/ebbinghaus/${id}`, { method: 'DELETE' }),
  // 早起打卡
  listEarlyBird: () => request('/planner/earlybird'),
  createEarlyBird: (body) => request('/planner/earlybird', { method: 'POST', body }),
  // 阶段复习
  listPhase: () => request('/planner/phase'),
  createPhase: (body) => request('/planner/phase', { method: 'POST', body }),
  getPhaseReviews: (planId) => request(`/planner/phase/${planId}/reviews`),
  checkPhaseDay: (planId, dayNum) => request(`/planner/phase/${planId}/check/${dayNum}`, { method: 'POST' }),
}

/* ---------------- 单词词库 ---------------- */
export const wordsApi = {
  // 词库分类
  listDecks: () => request('/words/decks'),
  createDeck: (body) => request('/words/decks', { method: 'POST', body }),
  deleteDeck: (id) => request(`/words/decks/${id}`, { method: 'DELETE' }),
  // 单词CRUD
  list: (params) => request('/words', { params }),
  get: (id) => request(`/words/${id}`),
  create: (body) => request('/words', { method: 'POST', body }),
  update: (id, body) => request(`/words/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/words/${id}`, { method: 'DELETE' }),
  // 统计与复习
  stats: () => request('/words/stats'),
  due: (limit) => request('/words/due', { params: { limit } }),
  review: (id, grade) => request(`/words/${id}/review`, { method: 'POST', body: { grade } }),
  // 拼写练习（对标「不背单词」拼写模式）：正确=grade5，错误=grade1，自动记入 SM-2/FSRS
  spellCheck: (wordId, answer, recordReview = true) => request('/words/spell-check', {
    method: 'POST', body: { word_id: wordId, answer, record_review: recordReview },
  }),
  batchImport: (body) => request('/words/batch-import', { method: 'POST', body }),
  // V3.0 批量导入
  importText: (body) => request('/words/import-text', { method: 'POST', body }),
  importExcel: (formData) => request('/words/import-excel', { method: 'POST', formData }),
  // PDF 导出（对标「不背单词」纸质导出）：支持与列表一致的筛选参数
  exportPdf: (params) => downloadBlob('/words/export-pdf', params, `单词本_${new Date().toISOString().slice(0, 10)}.pdf`),
}

/* ---------------- 学习时长记录 ---------------- */
export const studyApi = {
  addSession: (body) => request('/dashboard/study-session', { method: 'POST', body }),
}

/* ---------------- 知识结构（章节 → 知识点 → 题型） ---------------- */
export const taxonomyApi = {
  subjects: () => request('/taxonomy/subjects'),
  // V8 阶段1：科目管理 CRUD（科目名可能含中文，路径参数统一 encodeURIComponent）
  createSubject: (body) => request('/taxonomy/subjects', { method: 'POST', body }),
  updateSubject: (subject, body) =>
    request(`/taxonomy/subjects/${encodeURIComponent(subject)}`, { method: 'PUT', body }),
  removeSubject: (subject) =>
    request(`/taxonomy/subjects/${encodeURIComponent(subject)}`, { method: 'DELETE' }),
  tree: (subject, includeExtension = true) =>
    request('/taxonomy/tree', { params: { subject, include_extension: includeExtension } }),
  knowledgePoints: (params) => request('/taxonomy/knowledge-points', { params }),
  knowledgePoint: (id) => request(`/taxonomy/knowledge-points/${id}`),
  createKnowledgePoint: (body) => request('/taxonomy/knowledge-points', { method: 'POST', body }),
  updateKnowledgePoint: (id, body) => request(`/taxonomy/knowledge-points/${id}`, { method: 'PUT', body }),
  removeKnowledgePoint: (id) => request(`/taxonomy/knowledge-points/${id}`, { method: 'DELETE' }),
  coverage: () => request('/taxonomy/coverage'),
}

/* 科目清单的统一取法在 api/subjects.js —— 不放本文件，是因为测试会整体 mock
   api/client，helper 放这里就拿不到被 mock 的 taxonomyApi（等于绕过了注入点）。 */

/* ---------------- 教材目录（电子通信考研核心专业课教材） ----------------
 * 对应后端 routers/textbooks.py：26 本教材 / 初试复试分类 / 院校关联。
 * exam_stage 是教材属性（同书可初试复试两用），后端返回 stages 数组。
 */
export const textbooksApi = {
  // 教材清单（可按科目 / 阶段 / 院校 / 关键词筛选）
  list: (params) => request('/textbooks', { params }),
  // 按科目分组的教材清单——知识地图「教材」维度数据源
  bySubject: (stage) => request('/textbooks/by-subject', { params: { stage } }),
  // 教材详情（含院校使用清单与关联文档）
  detail: (id) => request(`/textbooks/${id}`),
  // 某院校涉及的全部教材——择校页用
  ofSchool: (schoolId) => request(`/textbooks/school/${schoolId}`),
  // 教材域概览统计
  stats: () => request('/textbooks/stats/overview'),
}

/* ---------------- 复习进度追踪 ---------------- */
export const reviewApi = {
  due: (params) => request('/review/due', { params }),
  submit: (body) => request('/review/submit', { method: 'POST', body }),
  progress: (subject) => request('/review/progress', { params: { subject } }),
  history: (params) => request('/review/history', { params }),
  weakPoints: (params) => request('/review/weak-points', { params }),
  linkStats: () => request('/review/link-stats'),
  stats: () => request('/review/stats'),
}

/* ---------------- 知识库健康（体检 + 自愈） ---------------- */
export const kbApi = {
  health: () => request('/kb/health'),
  heal: (params) => request('/kb/heal', { method: 'POST', params }),
  healStatus: () => request('/kb/heal/status'),
  repairPaths: () => request('/kb/repair-paths', { method: 'POST' }),
  normalizeStatus: () => request('/kb/normalize-status', { method: 'POST' }),
  pipeline: () => request('/kb/pipeline'),
}

/* ---------------- 系统 / 运行环境 ---------------- */
export const systemApi = {
  // 本机与局域网访问地址（含二维码），用于「手机访问」面板
  accessInfo: () => request('/access-info'),
  health: () => request('/health'),
  computeNodes: () => request('/admin/system/compute-nodes'),
}

/* ---------------- 账号与会话（doc 11） ---------------- */
export const authApi = {
  status: () => request('/auth/status'),
  login: (username, password) => request('/auth/login', { method: 'POST', body: { username, password } }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  refresh: () => request('/auth/refresh', { method: 'POST' }),
  me: () => request('/auth/me'),
  changePassword: (oldPassword, newPassword) =>
    request('/auth/change-password', { method: 'POST', body: { old_password: oldPassword, new_password: newPassword } }),
}

/* ---------------- 用户管理（仅管理员） ---------------- */
export const adminUsersApi = {
  list: (params) => request('/admin/users', { params }),
  create: (body) => request('/admin/users', { method: 'POST', body }),
  update: (id, body) => request(`/admin/users/${id}`, { method: 'PATCH', body }),
  resetPassword: (id) => request(`/admin/users/${id}/reset-password`, { method: 'POST' }),
  /* 软删除（2026-10-19 补：原先无删除端点，DELETE 返回 405）——写 deleted_at，可恢复 */
  remove: (id) => request(`/admin/users/${id}`, { method: 'DELETE' }),
  restore: (id) => request(`/admin/users/${id}/restore`, { method: 'POST' }),
}


/* ---------------- 题目分析引擎 ---------------- */
export const analysisApi = {
  analyze: (body) => request('/analysis/analyze', { method: 'POST', body }),
  lecture: (body) => request('/analysis/lecture', { method: 'POST', body }),
  lectures: (params) => request('/analysis/lectures', { params }),
  ocr: (body) => request('/analysis/ocr', { method: 'POST', body }),
  // T7 学习者画像
  profile: (params) => request('/analysis/profile', { params })
}

/* ---------------- 刷题分项与错题闭环 ---------------- */
export const quizSectionApi = {
  subjects: () => request('/quiz/subjects'),
  sections: (params) => request('/quiz/sections', { params }),
  // start: 后端无 /api/quiz/start 接口，分项刷题请用 questions + submit
  submit: (body) => request('/quiz/submit', { method: 'POST', body }),
  wrongReasons: (params) => request('/quiz/wrong-reasons', { params }),
  weakPoints: (params) => request('/quiz/weak-points', { params }),
  reviews: (params) => request('/review/due', { params }),
  submitReview: (body) => request('/review/submit', { method: 'POST', body }),
  reviewStats: () => request('/review/stats')
}

/* ---------------- 组题网 ---------------- */
export const paperApi = {
  build: (body) => request('/papers/build', { method: 'POST', body }),
  save: (body) => request('/papers/save', { method: 'POST', body }),
  list: (params) => request('/papers', { params }),
  detail: (id) => request(`/papers/${id}`),
  delete: (id) => request(`/papers/${id}`, { method: 'DELETE' }),
  exportPdf: (id) => request(`/papers/${id}/export`),
  // questionPreview: 后端无 /api/papers/question-preview 接口，组卷预览请用 build / detail
}

/* ---------------- 考研规划 ---------------- */
export const planningApi = {
  universities: (params) => request('/kaoyan/schools', { params }),
  universityDetail: (id) => request(`/kaoyan/schools/${id}`),
  // strategy: 后端无 /api/planning/strategy，规划策略见 /api/planner/* 与 /api/plan/*
  phases: () => request('/planner/phase'),
  plan: () => request('/planner/phase'),
  savePlan: (body) => request('/planner/phase', { method: 'POST', body }),
  // materials / faq: 后端无 /api/planning/* 对应接口
}

/* ---------------- 评测与数据质量（/api/quality，只读） ---------------- */
export const qualityApi = {
  // 运行历史：kind ∈ qa | recognition | recognition_policy | corpus_probe | doc_lock
  evalRuns: (params) => request('/quality/eval-runs', { params }),
  evalRun: (id) => request(`/quality/eval-runs/${id}`),
  latest: (kind) => request('/quality/latest', { params: { kind } }),
  corpus: () => request('/quality/corpus', { timeout: 60000 }),
  treeOverlay: () => request('/quality/tree-overlay', { timeout: 60000 }),
  // 择校可靠度：专业初试科目 ↔ 知识库语料覆盖（L1 精确口径）
  majorCoverage: () => request('/quality/major-coverage', { timeout: 60000 }),
  // 学科词表对齐（只读）：documents.subject 哪些写法在分块侧没有同名值
  subjectAlignment: () => request('/quality/subject-alignment', { timeout: 60000 }),
}

/* ---------------- 全站收藏（S7：/api/favorites） ----------------
 * 弱引用模型：item_type + item_id 指向任意实体，无外键。
 * item_type 允许值由后端白名单校验：document/question/error/kp/word/flashcard/link。
 */
export const favoritesApi = {
  list: (params) => request('/favorites', { params }),
  add: (body) => request('/favorites', { method: 'POST', body }),
  // 是否收藏（单项；仅用于详情页等单个实体的场景）
  check: (itemType, itemId) =>
    request('/favorites/check', { params: { item_type: itemType, item_id: itemId } }),
  // 批量查询收藏态（P0-3）：一次拿回整页实体的收藏状态。
  // 此前列表页对每一行各发一次 /favorites/check —— 文档知识库 383 篇就是
  // 383 路并发，把 PG 连接池打满后连累所有个人数据接口 500。
  // 后端返回 { item_type, requested, map: { '<id>': bool }, favorited_ids: [...] }，
  // map 对未收藏的 id 显式给 false，调用方据此把缓存落成确定态。
  checkMany: (itemType, ids) =>
    request('/favorites/check', { params: { item_type: itemType, ids: (ids || []).join(',') } }),
  // 当前用户已收藏的全部 id（可选按类型收窄）
  ids: (itemType) => request('/favorites/ids', { params: { item_type: itemType } }),
  // 切换收藏：返回 { favorited: bool }
  toggle: (body) => request('/favorites/toggle', { method: 'POST', body }),
  remove: (itemType, itemId) =>
    request(`/favorites/${encodeURIComponent(itemType)}/${itemId}`, { method: 'DELETE' }),
}

/* ---------------- 学习轨迹（S7：/api/growth/timeline） ----------------
 * 按日聚合 study_events 事件流水 + 连续学习天数 + 科目分布。
 */
export const growthApi = {
  timeline: (days = 30) => request('/growth/timeline', { params: { days } }),
}

/* ---------------- 模考中心（P0-3：/api/exam） ----------------
 * 蓝图 → 组卷 → 答题 → 交卷 → 报告 全链路。
 * 响应契约：
 *   GET /exam/blueprints            → [{id, subject, paper, year, section, question_type, count, score_per_question, sort_order, is_active}]
 *   POST /exam/build                 → {session_id, blueprint_key, subject, paper, mode, total_count, total_score, sections:[{title, questions:[...]}], status, expires_at, time_limit_minutes}
 *   GET /exam/sessions?subject=&status= → [{id, blueprint_key, subject, paper, mode, total_count, total_score, correct_count, score, status, started_at, submitted_at, expires_at, report_available, max_score, earned_score}]
 *   GET /exam/sessions/{id}           → 会话详情（含 answers）
 *   GET /exam/sessions/{id}/report     → {overview, section_scores, knowledge_weakness, time_analysis, wrong_questions}
 *   POST /exam/{id}/submit            → {session_id, status, correct_count, score, stats_count, total_count, wrong_count, ai_unverified_count, scored_at}
 */
export const examApi = {
  blueprints: () => request('/exam/blueprints'),
  build: (body) => request('/exam/build', { method: 'POST', body }),
  sessions: (params) => request('/exam/sessions', { params }),
  session: (id) => request(`/exam/sessions/${id}`),
  report: (id) => request(`/exam/sessions/${id}/report`),
  submit: (id, body) => request(`/exam/${id}/submit`, { method: 'POST', body }),
}

/* ---------------- 聚合导出 ---------------- */
export default {
  dashboardApi, tasksApi, goalsApi, quizApi, errorsApi, flashcardsApi,
  documentsApi, netdiskApi, importsApi, aiApi, customizationApi, plannerApi, wordsApi,
  studyApi, taxonomyApi, reviewApi, systemApi, kbApi, analysisApi, quizSectionApi, paperApi, planningApi,
  kbImportApi, qualityApi, favoritesApi, growthApi, examApi, recommendApi
}