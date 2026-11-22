/* ============================================================
   金币激励 + 个人资料 API（W6）
   ------------------------------------------------------------
   独立成模块而不是塞进 client.js：本轮 W1/W4 智能体并行改的是
   练习/单词/中枢那批接口，这里只挂 /api/gamification 与 /api/profile
   两组新契约，减少同文件冲突面。请求实现复用 client.js 的 request
   （超时、错误壳 {code,message,detail}、后端在线状态都已经在它里面）。
   后端契约来源：backend-main-fastapi/routers/study/gamification.py
                backend-main-fastapi/routers/auth/profile.py
   ============================================================ */

import { request } from './client'

export const coinsApi = {
  /** 总览：余额 / 今日进度 / 两个「连续」/ 下一里程碑 */
  summary: () => request('/gamification/summary'),
  /** 规则说明：单价、计量口径、单日上限（钱怎么算的必须能查到） */
  rules: () => request('/gamification/rules'),
  /** 把已发生的学习痕迹折算成金币（服务端幂等，重复调只补差额） */
  sync: (date) => request('/gamification/sync', { method: 'POST', body: date ? { date } : {} }),
  checkin: () => request('/gamification/checkin', { method: 'POST' }),
  makeup: (date) => request('/gamification/checkin/makeup', { method: 'POST', body: { date } }),
  calendar: (days = 35) => request('/gamification/calendar', { params: { days } }),
  ledger: (params) => request('/gamification/ledger', { params }),
  shop: () => request('/gamification/shop'),
  redeem: (code) => request('/gamification/redeem', { method: 'POST', body: { code } }),

  admin: {
    overview: (days = 14) => request('/gamification/admin/overview', { params: { days } }),
    rules: () => request('/gamification/admin/rules'),
    updateRule: (code, body) => request(`/gamification/admin/rules/${code}`, { method: 'PUT', body }),
    settings: () => request('/gamification/admin/settings'),
    updateSettings: (values) => request('/gamification/admin/settings', { method: 'PUT', body: { values } }),
    items: () => request('/gamification/admin/items'),
    upsertItem: (body) => request('/gamification/admin/items', { method: 'POST', body }),
    toggleItem: (code, isActive) =>
      request(`/gamification/admin/items/${code}`, { method: 'PATCH', body: { is_active: isActive } }),
    adjust: (body) => request('/gamification/admin/adjust', { method: 'POST', body }),
    ledger: (params) => request('/gamification/admin/ledger', { params }),
    user: (id) => request(`/gamification/admin/users/${id}`),
  },
}

export const profileApi = {
  get: () => request('/profile'),
  update: (body) => request('/profile', { method: 'PUT', body }),
}

/** 流水方向 → 展示语气（不猜语义：未知方向按中性处理） */
export const DIRECTION_LABEL = { earn: '获得', spend: '消耗', adjust: '调整' }

/** 兑换被挡的原因码 → 人话（后端 shop 接口逐件返回 blocked） */
export const BLOCKED_LABEL = {
  owned: '已拥有',
  monthly_limit: '本月已达上限',
  insufficient: '金币不足',
}

/** 签到格子的四种状态；auto = 有效学习日自动计入，不是用户点的 */
export const CHECKIN_KIND_LABEL = { manual: '签到', makeup: '补签', auto: '有效学习日' }

export const FRAME_CLASS = {
  flame: 'v3-coin-frame--flame',
  scholar: 'v3-coin-frame--scholar',
  star: 'v3-coin-frame--star',
}

export default coinsApi
