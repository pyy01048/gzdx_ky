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

export const fmtDateCN = (dateStr) => {
  const d = parseDate(dateStr)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

export const fmtFileSize = (kb) => {
  if (!kb) return '—'
  if (kb < 1024) return `${kb} KB`
  if (kb < 1024 * 1024) return `${(kb / 1024).toFixed(1)} MB`
  return `${(kb / 1024 / 1024).toFixed(1)} GB`
}

export const uid = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`
