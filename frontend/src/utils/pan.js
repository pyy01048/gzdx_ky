/* ============================================================
   百度网盘前端客户端（对齐 FastAPI 真实后端 /api/netdisk/*）
   所有敏感操作（换取/刷新 token）都在后端完成，
   前端仅持有 access_token（可持久化到 localStorage）。

   注意：所有请求统一走 api/client.js 的 request()，
   以复用超时控制、错误透传与 401 处理，避免裸 fetch 造成
   "永久 loading / 错误不可见"。
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
  listPanFiles
}
