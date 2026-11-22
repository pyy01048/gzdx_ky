/* W3 任务循环规则（与后端 backend-main-fastapi/services/task_recurrence.py 同口径）。
 *
 * recurrence JSON：
 *   { freq: 'none'|'daily'|'workdays'|'weekly'|'specific'|'custom'|'ebbinghaus',
 *     weekdays: [0..6]（0=周一，每周六=[5]）, interval: N, dates: ['YYYY-MM-DD'], until?: 'YYYY-MM-DD' }
 *
 * 在线模式日历发生日以后端 /api/tasks/calendar 为准；本模块只服务
 * 离线本地模式与「循环规则 → 文案」展示，两处口径必须同步改。
 */
import { addDays, daysBetween, weekdayIdx, WEEK_CN_SHORT } from './date'

/** 艾宾浩斯日粒度偏移（天）：锚点当天 + 1/2/4/7/15/30。分钟级节奏归计划模块的艾宾浩斯表。 */
export const EBBINGHAUS_DAY_OFFSETS = [0, 1, 2, 4, 7, 15, 30]

export const FREQ_OPTIONS = [
  { value: 'none', label: '不循环' },
  { value: 'daily', label: '每天' },
  { value: 'workdays', label: '每工作日（周一~周五）' },
  { value: 'weekly', label: '每周指定日' },
  { value: 'specific', label: '特定日期' },
  { value: 'custom', label: '自定义（每 N 天）' },
  { value: 'ebbinghaus', label: '艾宾浩斯记忆法' },
]

export const isRecurring = (task) => {
  const freq = task?.recurrence?.freq
  return !!freq && freq !== 'none'
}

/** 本地模式的循环展开：返回 [rangeStart, rangeEnd] 内的发生日（YYYY-MM-DD，升序）。 */
export function expandTaskDates(task, rangeStart, rangeEnd) {
  const rec = task.recurrence || {}
  const freq = rec.freq || 'none'
  const anchor = task.start || task.due || null
  let end = task.end || null
  if (rec.until && (!end || rec.until < end)) end = rec.until

  if (freq === 'none') {
    const due = task.due || anchor
    return due && due >= rangeStart && due <= rangeEnd ? [due] : []
  }
  if (!anchor) return []

  const lo = anchor > rangeStart ? anchor : rangeStart
  const hi = end && end < rangeEnd ? end : rangeEnd
  if (lo > hi) return []

  const out = []
  const push = (d) => {
    if (out.length < 3660) out.push(d)
  }

  if (freq === 'daily' || freq === 'workdays') {
    let d = lo
    while (d <= hi) {
      if (freq === 'daily' || weekdayIdx(d) < 5) push(d)
      d = addDays(d, 1)
    }
  } else if (freq === 'weekly') {
    const days = (rec.weekdays && rec.weekdays.length ? rec.weekdays : [0]).map(Number)
    let d = lo
    while (d <= hi) {
      if (days.includes(weekdayIdx(d))) push(d)
      d = addDays(d, 1)
    }
  } else if (freq === 'specific') {
    const dates = [...(rec.dates || [])].filter((x) => x >= lo && x <= hi).sort()
    dates.forEach(push)
  } else if (freq === 'custom') {
    const n = Math.max(1, Number(rec.interval) || 1)
    const k = Math.max(0, Math.floor(daysBetween(anchor, lo) / n))
    let d = addDays(anchor, k * n)
    while (d <= hi) {
      if (d >= lo) push(d)
      d = addDays(d, n)
    }
  } else if (freq === 'ebbinghaus') {
    for (const off of EBBINGHAUS_DAY_OFFSETS) {
      const d = addDays(anchor, off)
      if (d >= lo && d <= hi) push(d)
    }
    out.sort()
  }
  return out
}

/** 循环规则的短文案（任务行/导出用）。 */
export function freqLabel(task) {
  const rec = task.recurrence || {}
  const freq = rec.freq || 'none'
  if (freq === 'none' || !freq) return ''
  if (freq === 'daily') return '每天'
  if (freq === 'workdays') return '每工作日'
  if (freq === 'weekly') {
    const days = (rec.weekdays || []).map((w) => WEEK_CN_SHORT[Number(w)] || '').filter(Boolean)
    return days.length ? `每周${days.join('、')}` : '每周'
  }
  if (freq === 'specific') return `特定日期 ×${(rec.dates || []).length}`
  if (freq === 'custom') return `每 ${Math.max(1, Number(rec.interval) || 1)} 天`
  if (freq === 'ebbinghaus') return '艾宾浩斯复习'
  return ''
}

/** 提醒文案；明确标注「仅展示」——提醒目前只存储展示，未接系统推送。 */
export function remindLabel(task) {
  const r = task.remind
  if (!r || !r.type) return ''
  if (r.type === 'point') return `⏰ ${r.time} 提醒`
  if (r.type === 'range') return `⏰ ${r.start}~${r.end} 时段`
  return ''
}

const EMOBY_RULES = [
  [['真题', '考研题'], '📝'],
  [['单词', '词汇'], '🔤'],
  [['语法'], '📖'],
  [['作文', '写作'], '✍️'],
  [['阅读'], '📚'],
  [['政治', '肖四', '肖八', '马原', '毛中特'], '🚩'],
  [['数学', '线代', '高数', '概率'], '🧮'],
  [['复习', '复盘', '错题'], '🔁'],
  [['背诵', '记忆'], '🗣️'],
  [['模拟', '模考'], '🎯'],
  [['听力'], '🎧'],
  [['专业课'], '🧪'],
]

/** 任务 emoji：按「模块 → 类型 → 科目」关键词命中，兜底 📚。纯展示，不改数据。 */
export function taskEmoji(task) {
  const hay = [...(task.modules || []), task.task_type || '', ...(task.subjects || []), task.subject || '', task.title || ''].join(' ')
  for (const [words, emoji] of EMOBY_RULES) {
    if (words.some((w) => hay.includes(w))) return emoji
  }
  return '📚'
}

/** 某月日历格（6 周 ×7，周一起始，返回 42 个 YYYY-MM-DD）：日期选择面板用。 */
export function monthCells(year, month) {
  const first = new Date(year, month - 1, 1)
  const startDow = (first.getDay() + 6) % 7
  const cells = []
  const cur = new Date(year, month - 1, 1 - startDow)
  for (let i = 0; i < 42; i += 1) {
    cells.push(`${cur.getFullYear()}-${String(cur.getMonth() + 1).padStart(2, '0')}-${String(cur.getDate()).padStart(2, '0')}`)
    cur.setDate(cur.getDate() + 1)
  }
  return cells
}
