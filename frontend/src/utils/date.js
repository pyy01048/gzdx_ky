/* 日期工具函数（基于本地时区，所有日期统一使用 YYYY-MM-DD 字符串） */

export const pad2 = (n) => String(n).padStart(2, '0')

export const toDateStr = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`

export const todayStr = () => toDateStr(new Date())

export const parseDate = (s) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export const addDays = (s, n) => {
  const d = parseDate(s)
  d.setDate(d.getDate() + n)
  return toDateStr(d)
}

/** 两个日期字符串相差天数（b - a） */
export const daysBetween = (a, b) => {
  const ms = parseDate(b) - parseDate(a)
  return Math.round(ms / 86400000)
}

export const WEEK_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
export const WEEK_CN_SHORT = ['一', '二', '三', '四', '五', '六', '日']
export const WEEK_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const weekdayIdx = (dateStr) => {
  // 返回 0-6（0=周一）
  const d = parseDate(dateStr)
  const js = d.getDay() // 0=周日
  return (js + 6) % 7
}

/** 生成某月日历矩阵 [[dateStr, ...x7], ...] */
export const monthMatrix = (year, month) => {
  const first = new Date(year, month - 1, 1)
  const startDow = (first.getDay() + 6) % 7 // 周一起始
  const start = new Date(year, month - 1, 1 - startDow)
  const rows = []
  let cur = new Date(start)
  for (let r = 0; r < 6; r++) {
    const row = []
    for (let c = 0; c < 7; c++) {
      row.push(toDateStr(cur))
      cur.setDate(cur.getDate() + 1)
    }
    rows.push(row)
  }
  return rows
}

/** 中文短日期。缺日期就明说，不能渲染成「NaN月NaN日」假装有时间。 */
export const fmtDateCN = (dateStr) => {
  if (typeof dateStr !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(dateStr)) return '日期未知'
  const d = parseDate(dateStr.slice(0, 10))
  if (Number.isNaN(d.getTime())) return '日期未知'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

export const fmtFileSize = (kb) => {
  if (!kb) return '—'
  if (kb < 1024) return `${kb} KB`
  if (kb < 1024 * 1024) return `${(kb / 1024).toFixed(1)} MB`
  return `${(kb / 1024 / 1024).toFixed(1)} GB`
}

export const uid = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

/**
 * 相对日期文案：今天 / 昨天 / N 天前 / 具体日期（数据缺失时返回空串）。
 *
 * 全站**唯一**实现。之前在 NoticeBoard 与 NoticeCenter 各有一份同样的代码，
 * 两处「今天」的判定随其中一处被改动就会分叉。
 */
export function humanDate(dateStr) {
  if (!dateStr) return ''
  const day = String(dateStr).slice(0, 10)
  const m = /^(\d{4})-\d{2}-\d{2}$/.exec(day)
  if (!m) return day
  const target = parseDate(day)
  if (Number.isNaN(target.getTime())) return day
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((today - target) / 86400000)
  if (diff === 0) return '今天'
  if (diff === 1) return '昨天'
  if (diff > 1 && diff < 30) return `${diff} 天前`
  if (diff < 0) return '即将'
  return day
}

/**
 * 时间戳展示串（本地时区 `YYYY-MM-DD HH:mm`）。
 *
 * 后端时间列统一存 naive UTC，出参由 `UtcZJSONResponse` 补 `Z`（见
 * backend-main-fastapi/utils/response.py），所以这里**必须**走 `Date` 解析再按
 * 本地时区渲染，不能像以前那样 `String(x).slice(0, 16)` 直接截字符串——那是把
 * UTC 墙钟当北京时间显示，早 8 小时。无法解析的值如实返回空串，不猜。
 */
export function fmtDateTime(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}
