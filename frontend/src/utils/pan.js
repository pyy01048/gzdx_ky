/* ============================================================
   百度网盘前端客户端（对齐 FastAPI 真实后端 /api/netdisk/*）
   所有敏感操作（换取/刷新 token）都在后端完成，
   前端仅持有 access_token（可持久化到 localStorage）。

   注意：所有请求统一走 api/client.js 的 request()，
   以复用超时控制、错误透传与 401 处理，避免裸 fetch 造成
   "永久 loading / 错误不可见"。
   ============================================================ */

import { request } from '../api/client'

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

/* 文件列表：GET /api/netdisk/files?path=... 返回 local_files + api_files */
export async function listPanFiles(accessToken, dir = '/') {
  const j = await request('/netdisk/files', { params: { path: dir } })
  const local = (j.local_files || []).map((f) => ({
    fs_id: f.fs_id || f.id,
    server_filename: f.file_name,
    path: f.path,
    size: f.size,
    category: f.category,
    isdir: 0
  }))
  const api = (j.api_files || []).map((f) => ({
    fs_id: f.fs_id,
    server_filename: f.server_filename || f.filename,
    path: f.path || dir,
    size: f.size,
    category: f.category,
    isdir: f.isdir || 0
  }))
  // 合并去重
  const seen = new Set()
  const merged = []
  for (const f of [...api, ...local]) {
    const k = f.fs_id || f.server_filename
    if (seen.has(k)) continue
    seen.add(k)
    merged.push(f)
  }
  return merged
}

/* 文件元信息（含 dlink 预览）：后端通过 preview 接口按 fs_id 获取 */
export async function getFileMetas(accessToken, fsIds) {
  const metas = {}
  for (const id of fsIds.slice(0, 20)) {
    try {
      // 单个文件失败不影响整体：沿用原有"静默跳过"语义
      const j = await request(`/netdisk/preview/${id}`)
      if (j && j.dlink) metas[id] = { dlink: j.dlink, file_name: j.file_name }
    } catch { /* ignore */ }
  }
  return { list: Object.keys(metas).map((fs_id) => ({ fs_id, ...metas[fs_id] })) }
}

export default {
  getStoredPan, storePan, clearPan,
  getStatus, getAuthUrl, exchangeToken, refreshPanToken,
  listPanFiles, getFileMetas
}
