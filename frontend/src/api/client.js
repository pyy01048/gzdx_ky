/* ============================================================
   考研档案 · FastAPI 真实后端 API 客户端（全接口覆盖）
   统一封装 fetch，通过 vite /api 代理访问 127.0.0.1:8000
   全部对齐 backend-main-fastapi/routers/* 契约
   ============================================================ */

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

/** 从 FastAPI 错误体中提取可展示给用户的文本。 */
function extractDetail(data, fallback) {
  if (data === null || data === undefined) return fallback
  const detail = data.detail || data.error || data.message
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

// 从 localStorage 读取应用密码（认证启用时使用）
function getAppPassword() {
  try {
    return localStorage.getItem('app_password') || ''
  } catch {
    return ''
  }
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
 * @throws  {ApiError} code为 'timeout' | 'network' | 'aborted' | 'http_error'
 */
async function request(
  path,
  { method = 'GET', body, params, formData, timeout = DEFAULT_TIMEOUT, signal: externalSignal } = {}
) {
  let url = `${BASE}${path}`
  if (params) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    }
    const s = qs.toString()
    if (s) url += `?${s}`
  }
  const opts = { method, headers: {} }
  // 注入认证头（如果有密码）
  const password = getAppPassword()
  if (password) {
    opts.headers['X-App-Password'] = password
  }
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
      throw new ApiError(`请求超时（${Math.round(Number(timeout) / 1000)}s）：${method} ${path}`, {
        code: 'timeout',
      })
    }
    // 调用方主动取消
    if (e && (e.name === 'AbortError' || externalSignal?.aborted)) {
      throw new ApiError(`请求已取消：${method} ${path}`, { code: 'aborted' })
    }
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
     * 错误场景（非 2xx）由下方 !resp.ok 分支抛出带 detail 的 ApiError。
     */
    data = null
  }
  if (!resp.ok) {
    // 401 未授权：清除本地密码并触发登录事件
    if (resp.status === 401) {
      try { localStorage.removeItem('app_password') } catch {/* 忽略隐私模式异常 */}
      window.dispatchEvent(new CustomEvent('auth:required', { detail: data }))
    }
    throw new ApiError(extractDetail(data, `HTTP ${resp.status}`), {
      code: 'http_error',
      status: resp.status,
      data,
    })
  }
  return data
}

// 统一导出 request，供各业务 API client 复用（消除重复请求逻辑）
export { request, DEFAULT_TIMEOUT }

/* ---------------- Dashboard 驾驶舱 ---------------- */
export const dashboardApi = {
  get: () => request('/dashboard'),
  countdown: () => request('/dashboard/countdown'),
  todayTasks: () => request('/dashboard/today-tasks'),
  stats: () => request('/dashboard/stats'),
  weakness: () => request('/dashboard/weakness')
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
  university: () => request('/goals/university'),
  universitySearch: (params) => request('/goals/university/search', { params }),
  // AI 生成备考策略：后端同步阻塞真实 AI 调用，实测 19.9s~29.4s，需放宽超时
  strategy: (body) => request('/goals/strategy', { method: 'POST', body, timeout: AI_TIMEOUT })
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
  years: () => request('/quiz/years'),
  papersIndex: (params) => request('/quiz/papers-index', { params }),
  // 考频聚合：dimension = kp | chapter | paper（M2-7 考频分析页消费）
  frequency: (params) => request('/quiz/frequency', { params }),
  // 错因分布（错题复盘页筛选项）：{total, items:[{reason, count}]}
  wrongReasons: () => request('/quiz/wrong-reasons')
}

/* ---------------- Errors 错题本 ---------------- */
export const errorsApi = {
  list: (params) => request('/errors', { params }),
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
  getContent: (id, limit) => request(`/documents/${id}/content`, { params: { limit } }),
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
  batchImport: (body) => request('/words/batch-import', { method: 'POST', body }),
  // V3.0 批量导入
  importText: (body) => request('/words/import-text', { method: 'POST', body }),
  importExcel: (formData) => request('/words/import-excel', { method: 'POST', formData }),
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
  authStatus: () => request('/auth/status'),
  login: (password) => request('/auth/login', { method: 'POST', body: { password } }),
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
  wrongReasons: () => request('/quiz/wrong-reasons'),
  weakPoints: () => request('/quiz/weak-points'),
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
}

/* ---------------- 聚合导出 ---------------- */
export default {
  dashboardApi, tasksApi, goalsApi, quizApi, errorsApi, flashcardsApi,
  documentsApi, netdiskApi, importsApi, aiApi, customizationApi, plannerApi, wordsApi,
  studyApi, taxonomyApi, reviewApi, systemApi, kbApi, analysisApi, quizSectionApi, paperApi, planningApi,
  kbImportApi, qualityApi
}