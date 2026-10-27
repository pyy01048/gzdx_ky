/* ============================================================
   用户可读的 AI 报错（dogfood 报告 ISSUE-002）
   --------------------------------------------------------------
   此前界面直接显示后端原始异常（401 Authorization Required、
   api.deepseek.com 地址等），既暴露内部实现，用户也看不懂。
   这里把常见失败翻译成一句可操作的中文提示；原始错误只进
   控制台日志，不再进界面。未知错误透传原文，但抹去 URL。

   注：本想放进 utils/api.js（与 chatCompletion 同处），但该文件
   含既有 provider 配置传递代码，安全护栏拒绝整文件写入，
   故独立成模块，供 Tasks / GlobalAI 等所有 AI 调用面复用。
   ============================================================ */

export function friendlyAiError(e) {
  const raw = String((e && (e.message || e.detail)) || e || '')
  console.error('[AI] 原始错误：', e)
  const clean = raw.replace(/https?:\/\/[^\s"'）)]+/g, '…').replace(/\s+/g, ' ').trim()
  if (/401|Unauthorized|Authorization Required/i.test(clean)) return 'AI 服务鉴权失败：请到「设置 → AI 服务」检查 API Key 是否有效、账户是否有余额。'
  if (/402|quota|insufficient|余额不足/i.test(clean)) return 'AI 服务额度不足：请到服务商控制台充值，或在「设置 → AI 服务」更换服务商。'
  if (/429|rate limit|Too Many Requests/i.test(clean)) return 'AI 请求太频繁，被限流了：请等几秒再试。'
  if (/\b403\b|\b404\b|Forbidden|Not Found/i.test(clean)) return 'AI 服务拒绝了本次请求：请检查「设置 → AI 服务」里的模型名称与接口地址。'
  if (/\b5\d\d\b|Internal Server Error|Bad Gateway|Service Unavailable/i.test(clean)) return 'AI 服务暂时不可用（服务器错误）：请稍后重试。'
  if (/AbortError|timeout|timed? ?out/i.test(clean)) return 'AI 请求超时：请稍后重试；若反复超时，请检查网络与服务商状态。'
  if (/Failed to fetch|NetworkError|ECONNREFUSED|后端代理请求失败/i.test(clean)) return '网络连接失败：请检查本机网络或后端服务是否在线。'
  return clean ? `AI 请求失败：${clean}` : 'AI 请求失败，请稍后重试。'
}
