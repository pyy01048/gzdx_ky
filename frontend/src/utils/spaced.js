/* 记忆调度算法：SM-2 间隔重复 + 艾宾浩斯遗忘曲线节点 */

/** 艾宾浩斯短期/长期复习节点（天） */
export const EBBINGHAUS = [0, 1, 2, 4, 7, 15, 30]

/** 记忆卡状态 */
export const CARD_STATUS = {
  NEW: 'new',            // 新卡
  LEARNING: 'learning',  // 学习中
  REVIEWING: 'reviewing',// 复习中
  MASTERED: 'mastered'   // 已掌握
}

/** SM-2 评分等级 */
export const GRADE = {
  AGAIN: 1,  // 完全忘记
  HARD: 3,   // 很困难
  GOOD: 4,   // 正确但需努力回忆
  EASY: 5    // 轻松
}

/** 各等级对应的 next 间隔乘数 */
const INTERVAL_MULT = { 1: 1, 3: 1.2, 4: 1, 5: 1.3 }

/**
 * SM-2 核心：给定卡片与评分，返回新的调度状态
 * @param {object} card { ef(困难度, 默认2.5), interval(当前间隔天数), reps, lapses, due }
 * @param {number} grade 1|3|4|5
 */
export function sm2Schedule(card, grade) {
  const ef0 = card.ef ?? 2.5
  let ef = ef0 + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
  if (ef < 1.3) ef = 1.3
  let interval = 0
  let reps = card.reps ?? 0
  let lapses = card.lapses ?? 0

  if (grade === GRADE.AGAIN) {
    reps = 0
    lapses += 1
    interval = 0 // 立即重学
  } else if (grade === GRADE.HARD) {
    reps += 1
    interval = reps === 1 ? 1 : Math.max(1, Math.round((card.interval ?? 1) * 1.2))
  } else {
    reps += 1
    if (reps === 1) interval = 1
    else if (reps === 2) interval = 6
    else interval = Math.round((card.interval ?? 6) * ef * (INTERVAL_MULT[grade] ?? 1))
  }

  // 状态判定
  let status = card.status ?? CARD_STATUS.NEW
  if (grade === GRADE.AGAIN) status = CARD_STATUS.LEARNING
  else if (interval === 0) status = CARD_STATUS.LEARNING
  else if (interval >= 21 && grade >= GRADE.GOOD) status = CARD_STATUS.MASTERED
  else if (interval >= 1) status = CARD_STATUS.REVIEWING

  // 到期时间：间隔=1 天，顺延；interval=0 视为今天复习
  const now = new Date()
  const due = new Date(now)
  due.setDate(due.getDate() + Math.max(interval, interval === 0 ? 0 : 1))
  const dueStr = due.toISOString().slice(0, 10)

  return {
    ef: +ef.toFixed(2),
    interval,
    reps,
    lapses,
    status,
    due: dueStr,
    lastReview: today()
  }
}

/** 判断一张卡今天是否到期（或新卡） */
export function isDue(card, todayStr = today()) {
  if (!card.due) return true
  return card.due <= todayStr
}

/** 待复习队列（今天到期 + 新卡 + 学习中） */
export function dueCards(cards, todayStr = today()) {
  return cards.filter((c) => {
    if (c.status === CARD_STATUS.MASTERED) return false
    return isDue(c, todayStr)
  })
}

/** 艾宾浩斯复习日历：返回 0-30 天的复习强度（用于仪表盘） */
export function ebbinghausCurve() {
  return EBBINGHAUS.map((d) => ({ day: d, load: d === 0 ? 0.3 : 1 / d }))
}

/** 今日日期字符串 */
export function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 简单日期 +n 天 */
export function addDaysStr(base, n) {
  const d = new Date(base + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
