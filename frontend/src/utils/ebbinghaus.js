/* 艾宾浩斯遗忘曲线 + 七刷机制
   遗忘节点：5 分钟 / 30 分钟 / 12 小时 / 1 天 / 2 天 / 4 天 / 7 天 / 15 天
   七刷：按 3/7/21/40/70/120 天等间隔重做，直至掌握度拉满
*/

import { addDays, daysBetween, todayStr } from './date'

export const REVIEW_POINTS = [
  { label: '5 分', unit: 'min', value: 5 },
  { label: '30 分', unit: 'min', value: 30 },
  { label: '12 时', unit: 'hour', value: 12 },
  { label: '1 天', unit: 'day', value: 1 },
  { label: '2 天', unit: 'day', value: 2 },
  { label: '4 天', unit: 'day', value: 4 },
  { label: '7 天', unit: 'day', value: 7 },
  { label: '15 天', unit: 'day', value: 15 }
]

/* 七刷时间间隔（天），用于重做计划 */
export const SEVEN_PASS = [3, 7, 21, 40, 70, 120]

/** 计算下一复习节点标签 */
export function nextReviewLabel(lastReview, masterLevel) {
  if (!lastReview) return '初次记忆'
  const n = Math.min(masterLevel, REVIEW_POINTS.length - 1)
  return REVIEW_POINTS[n].label
}

/** 根据掌握度(0-7) 判断状态 */
export function reviewStatus(item, today = todayStr()) {
  // status: 'new' 未学 / 'due' 到期需复习 / 'reviewing' 进行中 / 'mastered' 已掌握
  if (!item.lastReview) return { status: 'new', nextDue: null, pass: 0 }
  const level = Math.min(item.mastery, 6)
  const interval = REVIEW_POINTS[level].value
  const nextDue = addDays(item.lastReview, interval)
  if (item.mastery >= 7) return { status: 'mastered', nextDue, pass: 7 }
  if (daysBetween(today, nextDue) <= 0) return { status: 'due', nextDue, pass: item.mastery }
  return { status: 'reviewing', nextDue, pass: item.mastery }
}

/** 下一次七刷日期 */
export function nextPassDate(createdAt, passIndex) {
  if (passIndex <= 0) return createdAt
  return addDays(createdAt, SEVEN_PASS[Math.min(passIndex, SEVEN_PASS.length) - 1])
}
