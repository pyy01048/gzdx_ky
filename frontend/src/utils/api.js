import useStore from '../store/useStore'

/* ============================================================
   AI 统一调用层（OpenAI 兼容接口）
   支持任意服务商：DeepSeek / 豆包 / 通义 / 智谱 / OpenAI / 自定义
   ============================================================ */

export const PRESETS = [
  { key: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat', vision: false },
  { key: 'doubao', name: '豆包(火山方舟)', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seed-1-6-250615', vision: true },
  { key: 'qwen', name: '通义千问', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', vision: true },
  { key: 'zhipu', name: '智谱清言', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash', vision: true },
  { key: 'openai', name: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini', vision: true },
  { key: 'custom', name: '自定义', baseUrl: '', model: '', vision: false }
]

export function providerPreset(key) {
  return PRESETS.find((p) => p.key === key) || PRESETS[PRESETS.length - 1]
}

/* 非流式 AI 调用的超时上限（毫秒）。
   流式接口 chatStream 不设超时（长连接由调用方 signal 控制）。 */
const AI_TIMEOUT = 120000

/* 取当前生效的默认服务（优先启用且默认，其次第一个启用的） */
export function defaultProvider() {
  const { settings } = useStore.getState()
  const list = (settings && settings.aiProviders) || []
  return list.find((p) => p.enabled && p.default) || list.find((p) => p.enabled) || null
}

export function hasAiConfigured() {
  // 前端配置了provider且有apiKey，或者后端有默认provider（总是可用）
  const p = defaultProvider()
  if (p && p.apiKey && p.baseUrl && p.model) return true
  // 后端总是有默认AI服务商配置，所以前端未配置时也返回true
  return true
}

function normalizeUrl(baseUrl, endpoint) {
  return (baseUrl || '').replace(/\/+$/, '') + (endpoint || '/chat/completions')
}

/* 核心调用：返回 { text, usage, latency }
 * V2.0 修复：统一走后端代理 /api/ai/chat，避免浏览器直调 AI 服务商导致 CORS 失败。
 * 后端使用数据库中配置的默认服务商，并支持智能路由（本地+API自动选择）。
 */
export async function chatCompletion(provider, messages, { temperature = 0.6, maxTokens, json = false, useRag = false } = {}) {
  const start = performance.now()
  const body = {
    messages,
    temperature,
    use_rag: useRag,
    use_routing: true,
  }
  if (maxTokens) body.max_tokens = maxTokens

  let resp
  // 非流式调用加超时：后端代理可能阻塞数分钟，前端不应无限等待
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), AI_TIMEOUT)
  try {
    resp = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (e) {
    if (e && e.name === 'AbortError') {
      throw new Error(`后端代理请求超时（${AI_TIMEOUT / 1000}s），请稍后重试`)
    }
    throw new Error(`后端代理请求失败：${e.message}`)
  } finally {
    clearTimeout(timer)
  }
  const latency = Math.round(performance.now() - start)

  if (!resp.ok) {
    let detail = ''
    try {
      const j = await resp.json()
      // 后端错误壳是 {code, message, detail?}（utils/exceptions.py），message 才是给人看的那句
      detail = j.message || j.detail || JSON.stringify(j)
    } catch { /* ignore */ }
    throw new Error(`AI 接口错误 ${resp.status}：${detail || resp.statusText}`)
  }

  const data = await resp.json()
  const text = data.content || ''
  const usage = data.usage || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }
  return { text, usage, latency, model: data.model || provider?.model, provider: data.provider, route: data.route, route_reason: data.route_reason }
}

/* 简单连通性测试 */
export async function testProvider(provider, prompt = '你好，请只回复两个字：成功') {
  const r = await chatCompletion(provider, [{ role: 'user', content: prompt }], { maxTokens: 60 })
  return { ok: true, ...r, preview: (r.text || '').slice(0, 120) }
}

/* ============================================================
   SSE 流式对话（经后端 /api/ai/chat/stream，后端代理 + RAG 增强）
   复用「设置 → AI 服务」中已配置的服务商，无需在后端重复配置。
   ============================================================ */
export async function chatStream(provider, messages, { temperature = 0.6, useRag = false, onDelta, signal } = {}) {
  const body = {
    messages,
    use_rag: useRag,
  }
  // 如果前端配置了provider且有apiKey，传递给后端覆盖；否则让后端使用默认provider
  if (provider && provider.apiKey && provider.baseUrl && provider.model) {
    body.provider_override = {
      base_url: provider.baseUrl,
      api_key: provider.apiKey,
      model: provider.model,
      name: provider.name || provider.key,
      provider_type: provider.key === 'claude' ? 'claude' : 'openai',
      temperature: provider.temperature ?? temperature
    }
  }

  const resp = await fetch('/api/ai/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal
  })
  if (!resp.ok) {
    let detail = ''
    try { const j = await resp.json(); detail = j.message || j.detail || '' } catch { /* ignore */ }
    throw new Error(`AI 接口错误 ${resp.status}：${detail || resp.statusText}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let full = ''
  let usedRag = false
  let usedProvider = ''

  const handleEvent = (ev) => {
    if (!ev || typeof ev !== 'object') return
    if (ev.type === 'meta') { usedRag = !!ev.rag; onDelta?.({ meta: true, rag: usedRag }); return }
    if (ev.type === 'provider') { usedProvider = ev.name || ''; onDelta?.({ provider: usedProvider }); return }
    if (ev.type === 'delta') { full += ev.content || ''; onDelta?.({ content: ev.content || '' }); return }
    if (ev.type === 'error') throw new Error(ev.message || 'AI 流式调用失败')
  }

  try {
    while (true) {
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
        try { handleEvent(JSON.parse(payload)) } catch (e) {
          if (e.message && e.message.includes('流式调用失败')) throw e
          /* 非 JSON 数据忽略 */
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
  return { text: full, rag: usedRag, provider: usedProvider }
}

/* 多模态视觉调用（用于 OCR 识别题目图片等） */
export async function chatVision(provider, textPrompt, imageDataUrl) {
  if (!provider || !provider.apiKey) {
    throw new Error('尚未配置 AI 服务')
  }
  const start = performance.now()
  const body = {
    model: provider.model,
    temperature: 0.2,
    messages: [{
      role: 'user',
      content: [
        { type: 'text', text: textPrompt },
        { type: 'image_url', image_url: { url: imageDataUrl } }
      ]
    }]
  }
  let resp
  // 直连第三方视觉接口：同样加超时，避免外部服务无响应时永久挂起
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), AI_TIMEOUT)
  try {
    resp = await fetch(normalizeUrl(provider.baseUrl), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${provider.apiKey}` },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    })
  } catch (e) {
    if (e && e.name === 'AbortError') {
      throw new Error(`视觉接口请求超时（${AI_TIMEOUT / 1000}s）`)
    }
    throw new Error(`请求失败：${e.message}（若为跨域 CORS 限制，可配置本地代理）`)
  } finally {
    clearTimeout(timer)
  }
  const latency = Math.round(performance.now() - start)
  if (!resp.ok) {
    let detail = ''
    try { const j = await resp.json(); detail = j.error?.message || JSON.stringify(j) } catch { /* ignore */ }
    throw new Error(`视觉接口错误 ${resp.status}：${detail || resp.statusText}`)
  }
  const data = await resp.json()
  const text = data.choices?.[0]?.message?.content || ''
  const usage = data.usage || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }
  return { text, usage, latency }
}

/* 记录用量到 store（调用成功后调用） */
export function recordUsage(usage, providerId) {
  const { recordAiUsage } = useStore.getState()
  recordAiUsage(usage, providerId)
}

/* 从 AI 回复中稳健地提取 JSON 对象（兼容 markdown 代码块包裹） */
export function extractJson(text) {
  if (!text) return null
  const t = String(text).trim()
  // 去掉 ```json ... ``` 包裹
  const fence = /```(?:json)?\s*([\s\S]*?)```/.exec(t)
  const candidate = fence ? fence[1].trim() : t
  // 截取第一个 { 到最后一个 }
  const s = candidate.indexOf('{')
  const e = candidate.lastIndexOf('}')
  if (s < 0 || e <= s) return null
  try {
    return JSON.parse(candidate.slice(s, e + 1))
  } catch {
    return null
  }
}

export default { chatCompletion, chatStream, chatVision, testProvider, defaultProvider, hasAiConfigured, providerPreset, PRESETS, recordUsage, extractJson }
