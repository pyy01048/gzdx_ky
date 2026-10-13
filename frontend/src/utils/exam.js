/* 考研初试倒计时的唯一口径。
   此前三处各算各的（侧边栏写死 2026-12-19、导航读本地设置、仪表盘读后端 Goal 并兜底
   '2027-12-25'），同一个应用给出 67/439 天两种答案。统一到这里：
   后端 Goal 优先，其次本地设置，都没有就是"未配置"——绝不编一个日期。 */
import { daysBetween, parseDate, todayStr } from './date'

/** @returns {string|null} 初试日期 YYYY-MM-DD */
export function resolveExamDate(backendExamDate, settingsExamDate) {
  const s = String(backendExamDate || settingsExamDate || '').slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : null
}

/** 剩余天数（已过为负）；未配置返回 null */
export function examDaysLeft(examDate) {
  return examDate ? daysBetween(todayStr(), examDate) : null
}

export function examYear(examDate) {
  return examDate ? Number(examDate.slice(0, 4)) : null
}

/** 侧边栏秒级倒计时用的当日 00:00 时间戳；未配置返回 null */
export function examDeadline(examDate) {
  return examDate ? parseDate(examDate).getTime() : null
}
