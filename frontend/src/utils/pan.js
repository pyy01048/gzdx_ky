/* ============================================================
   百度网盘前端客户端（对齐 FastAPI 真实后端 /api/netdisk/*）
   所有敏感操作（换取/刷新 token）都在后端完成，
   前端仅持有 access_token（可持久化到 localStorage）。

   注意：所有请求统一走 api/client.js 的 request()，
   以复用超时控制、错误透传与 401 处理，避免裸 fetch 造成
   "永久 loading / 错误不可见"。

   #netdisk-refactor：授权状态的唯一事实来源是**后端 token-status**，
   不再是 localStorage 残留 token —— 旧写法让浏览器里一份过期 token
   就能打开"目录"面板，而后端其实早已失效，用户看到的是本地缓存冒充的目录。
   ============================================================ */

import { request } from '../api/client'
import { toDateStr } from './date'

export function getStoredPan() {
  try {
    return JSON.parse(localStorage.getItem('kaoyan_pan_token') || 'null')
  } catch {
    return null
  }
}

export function storePan(tok) {
  localStorage.setItem('kaoyan_pan_token', JSON.stringify(tok))
}

export function clearPan() {
  localStorage.removeItem('kaoyan_pan_token')
}

/* 网盘状态：从后端 platform-configs 判断百度网盘是否已授权 */
export async function getStatus() {
  const j = await request('/netdisk/platform-configs')
  const baidu = (j.configs && j.configs.baidu) || null
  return {
    configured: !!(baidu && baidu.token),
    platform: 'baidu_netdisk',
    token: baidu ? baidu.token : '',
    last_sync: baidu ? baidu.last_sync : null,
    sync_enabled: baidu ? baidu.sync_enabled : false
  }
}

/* 获取 OAuth 授权 URL：后端返回 { auth_url } */
export async function getAuthUrl() {
  const j = await request('/netdisk/auth-url', { params: { redirect_uri: 'oob' } })
  return j.auth_url || j.url || ''
}

/* 授权码换 token：POST /api/netdisk/callback?code=... */
export async function exchangeToken(code) {
  const j = await request('/netdisk/callback', {
    method: 'POST',
    params: { code, redirect_uri: 'oob' },
  })
  // 后端返回的 token 结构可能为 { access_token, refresh_token, expires_in, ... }
  const tok = j.access_token ? j : (j.token || j)
  storePan(tok)
  return tok
}

/* 刷新 token：走后端本地 OAuth，仅传 refresh_token */
export async function refreshPanToken(refreshToken) {
  // 后端当前通过回调流程自动维护 token；此处本地无法直接调用百度接口，
  // 交由后端回调重新授权。返回 null 表示需用户重新授权。
  return null
}

/* 授权状态：唯一事实来源 = 后端 /netdisk/token-status。
 * 返回 { authorized, expired, expires_in_seconds, has_refresh_token, ... }。
 * 页面门禁只认它：localStorage 有残留 token 但后端未授权时，一律视为未连接。 */
export async function getTokenStatus() {
  return request('/netdisk/token-status')
}

/* 目录浏览：只取百度真实文件列表（api_files），
 * 不混本地同步缓存（local_files 是 /netdisk/sync 写的 DB 行，
 * 混进来会让"没连接也显示目录"的 bug 复活）。
 * 授权失效时后端明确 401（ApiError.status === 401），调用方据此要求重新授权。 */
export async function fetchRemoteFiles(dir = '/') {
  const j = await request('/netdisk/files', { params: { path: dir } })
  if (j && j.api_error) console.warn('[pan] 网盘列表部分失败：', j.api_error)
  return (j.api_files || []).map((f) => normalize(f, dir))
}

/* 退出授权：清后端 token + 本地遗留键 */
export async function logoutPan() {
  try {
    await request('/netdisk/logout', { method: 'POST' })
  } finally {
    clearPan()
  }
}

/* 夸克网盘 Web 视图嵌入地址。
 * 夸克没有官方开放 API（无 OAuth / 无文件列表），后端只提供可嵌入地址，
 * 登录态由浏览器 Cookie 维护。返回 { url, configured, defaulted, mode, message }。 */
export async function getQuarkView() {
  return request('/netdisk/quark/web-view')
}

/* 文件列表：GET /api/netdisk/files?path=... 返回 local_files + api_files
 *
 * 两个来源字段名不一样（百度是 server_filename/server_mtime 秒级，本地记录是
 * file_name 且没有 mtime），页面统一只吃 name / date / size_kb —— 在这里归一，
 * 免得每个调用点各自猜。size 用 KB：fmtFileSize 的入参就是 KB。 */
function normalize(f, dir) {
  const mtime = f.server_mtime || f.mtime || null
  return {
    // 本地行的 id 是数据库主键，和百度 fs_id 不是同一个命名空间。旧写法
    // `f.fs_id || f.id` 会把主键当 fs_id 传给取流接口，链接必然 404；
    // 现在后端 local_files 直出真 fs_id，拿不到就留 null 让页面明说。
    fs_id: f.fs_id ?? null,
    name: f.server_filename || f.filename || f.file_name || '',
    path: f.path || dir,
    size_kb: Math.round((f.size || 0) / 1024),
    date: mtime ? toDateStr(new Date(mtime * 1000)) : (f.created_at ? String(f.created_at).slice(0, 10) : ''),
    category: f.category,
    isdir: !!f.isdir,
  }
}

export async function listPanFiles(accessToken, dir = '/') {
  const j = await request('/netdisk/files', { params: { path: dir } })
  const api = (j.api_files || []).map((f) => normalize(f, dir))
  const local = (j.local_files || []).map((f) => normalize(f, dir))
  // 合并去重：有真 fs_id 就按 fs_id，否则退回文件名（不能用数据库主键冒充 fs_id）
  const seen = new Set()
  const merged = []
  for (const f of [...api, ...local]) {
    const k = f.fs_id ? `fs:${f.fs_id}` : `name:${f.name}`
    if (seen.has(k)) continue
    seen.add(k)
    merged.push(f)
  }
  return merged
}

export default {
  getStoredPan, storePan, clearPan,
  getStatus, getAuthUrl, exchangeToken, refreshPanToken,
  listPanFiles,
  // #netdisk-refactor 新增：后端授权状态 / 真实目录浏览 / 退出授权 / 夸克 Web 视图
  getTokenStatus, fetchRemoteFiles, logoutPan, getQuarkView,
}
