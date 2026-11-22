/**
 * 今日聚合中枢 · 统一数据层（Single Source of Truth）
 *
 * 设计约束（对应产品要求的三条）：
 *  1. **页面只有一个数据出口**：Hub.jsx 只调用 `fetchHubOverview()`。
 *     现在由 4 个「聚合型」端点在浏览器侧组合；将来后端提供
 *     `GET /api/hub/overview` 时，只需把 `requestOverview()` 换成一个
 *     `request('/hub/overview')`，页面与测试无需改动 —— 这是「留接口」。
 *  2. **不出现不同科目不同数据源**：所有数字都带 `source`（哪个端点、
 *     哪个字段、什么切点），并在 `caliber` 里显式对账。同一指标只认一个
 *     出处，派生指标（如「今日航线」）只从这份模型计算，不再各自打接口。
 *  3. **可移植**：不读取 location / 端口，不写死 127.0.0.1；沿用 client.js
 *     的相对路径 `/api`，部署到服务器或打包进 App 时行为一致。
 *
 * 失败策略：`Promise.allSettled` 的等价实现（每个请求单独计时、单独降级）。
 * dashboard/summary 与 insight/today 至少一个成功即可渲染；其余接口失败
 * 时页面显示「部分数据不可用」，而不是整页报错。
 */
import { dashboardApi, insightApi, reviewApi, wordsApi } from './client'
import { MUTATION_EVENT } from './mutationEvent'

/** 缓存窗口：切页回来 45s 内不重复打接口；手动刷新可 force。 */
export const HUB_CACHE_TTL = 45_000

const PHASE_LABEL = {
  base: '基础期',
  intensify: '强化期',
  warning: '30 天预警',
  sprint: '最后冲刺',
  passed: '初试已结束',
}

const WEEK_CN = ['日', '一', '二', '三', '四', '五', '六']

const arr = (v) => (Array.isArray(v) ? v : [])
const toNum = (v, fallback = 0) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}
const clamp = (n, min = 0, max = 100) => Math.max(min, Math.min(max, toNum(n)))

/* -------------------------------------------------------------------------- */
/* 科目口径                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * 科目去重键：忽略空白、中英文括号、分隔符与大小写。
 * 只用于「同一科目只出现一次」的判断，不会改动展示名。
 */
export function subjectKey(raw) {
  return String(raw ?? '')
    .trim()
    .toLowerCase()
    .replace(/[\s·・\-—_/\\（）()【】[\]]/g, '')
}

/** 按 subjectKey 去重，保留首次出现的原始写法（展示名以用户配置为准）。 */
export function dedupeSubjects(items = []) {
  const seen = new Map()
  arr(items).forEach((it) => {
    const label = typeof it === 'string' ? it : it?.subject
    const key = subjectKey(label)
    if (key && !seen.has(key)) seen.set(key, String(label).trim())
  })
  return [...seen.values()]
}

/**
 * 科目 → 稳定色调编号（0-3，供装饰层循环取色）。
 * 先经 subjectKey 归一，再按字符码求和取模：比按显示名长度取模稳得多——
 * 空白/标点变体（「数学」与「数学 」、「英语 (一)」与「英语（一）」）映射到
 * 同一颜色，且不随科目顺序漂移。只影响配色，绝不影响任何数据与排序。
 */
export function subjectTone(raw) {
  const key = subjectKey(raw)
  let h = 0
  for (const ch of key) h = (h + ch.charCodeAt(0)) % 4
  return h
}

/* -------------------------------------------------------------------------- */
/* 归一化                                                                      */
/* -------------------------------------------------------------------------- */

export function normalizeCountdown(summary, insight) {
  const cd = summary?.countdown || insight?.countdown || {}
  const days = cd.days_left ?? cd.days ?? null
  return {
    days: days == null ? null : toNum(days),
    examDate: cd.exam_date || '',
    examYear: cd.exam_year || null,
    phase: cd.phase || '',
    phaseLabel: PHASE_LABEL[cd.phase] || '',
    university: cd.university || '',
    major: cd.major || '',
    source: cd.source || '',
    isDefault: !!cd.is_default,
  }
}

export function normalizeGoal(goal) {
  const g = goal || {}
  const targets = g.daily_targets || {}
  return {
    configured: !!g.configured,
    university: g.university || '',
    major: g.major || '',
    subjects: dedupeSubjects(g.subjects),
    supportSubjects: dedupeSubjects(g.support_subjects),
    dailyTargets: {
      focus: targets.focus_minutes == null ? null : toNum(targets.focus_minutes),
      questions: targets.questions == null ? null : toNum(targets.questions),
      reviewWords: targets.review_words == null ? null : toNum(targets.review_words),
      newWords: targets.new_words == null ? null : toNum(targets.new_words),
    },
    scoreTarget: g.score_targets?.total == null ? null : toNum(g.score_targets.total),
    targetsSet: !!g.targets_set,
  }
}

/**
 * 到期口径对账 —— 这是「统一数据源」的核心。
 *
 * 后端有三条**语义不同**的队列，过去容易被页面混成一句「待复习 N」：
 *  - 今日累计到期（summary.future_load.due_today）：截至今天 24:00，含此前欠账，
 *    用于「今天要清多少」，也是今日任务清单的口径；
 *  - 现在可做（summary.review_queue.total）：next_review ≤ now，用于「此刻点进去做」；
 *  - 艾宾浩斯计划（insight.today.due_review_count）：复盘计划模块的独立队列。
 * 这里把三者分开命名、分别标注来源，绝不求和成一个「总待复习」。
 */
export function normalizeDue({ summary, insight, words, review } = {}) {
  const fl = summary?.future_load?.due_today || {}
  const rq = summary?.review_queue || null
  const breakdown = {
    errors: toNum(fl.errors ?? review?.active_errors ?? summary?.errors?.active),
    cards: toNum(fl.flashcards),
    tasks: toNum(fl.tasks),
    words: toNum(fl.words),
  }
  const schedulerToday = toNum(fl.total, breakdown.errors + breakdown.cards + breakdown.tasks + breakdown.words)
  // review_queue 现含 words 段（2026-11-22 后端补齐）；旧响应无 words 时兜底求和不变
  const nowTotal = rq ? toNum(rq.total, arr(rq.cards).length + arr(rq.errors).length + arr(rq.tasks).length + arr(rq.words).length) : null
  const planner = toNum(insight?.due_review_count)
  const newWords = toNum(words?.new)
  const segments = [
    { key: 'planner', label: '艾宾浩斯', count: planner, tone: 'violet', to: '/quiz?tab=review' },
    { key: 'errors', label: '错题', count: breakdown.errors, tone: 'rose', to: '/error-review' },
    { key: 'words', label: '单词', count: breakdown.words, tone: 'green', to: '/words' },
    { key: 'cards', label: '卡片', count: breakdown.cards, tone: 'blue', to: '/cards' },
    { key: 'tasks', label: '待办', count: breakdown.tasks, tone: 'amber', to: '/tasks' },
  ]
  return {
    planner,
    schedulerToday,
    nowTotal,
    newWords,
    breakdown,
    segments,
    dueErrors: toNum(review?.due_errors, breakdown.errors),
    activeErrors: toNum(review?.active_errors, summary?.errors?.active),
  }
}

/**
 * 今日推荐量（W1 主口径）—— 页面「今天该做 N 项」只认这个。
 *
 * 后端 `services.daily_load.today_plan` 给的是
 * `min(真实到期/可学量, 目标配额或系统建议量, 合理上限)`，
 * 每条轨道带 `basis`（这个数字是谁定的）与 `overQuota`（转入复习债的差额）。
 *
 * 关键：后端没返回 `today_plan` 时这里给出 **null**，页面据此退回旧口径，
 * 而不是自己编一个默认量 —— 编出来的"今日 50 词"和无数据的整库到期一样是谎。
 */
export function normalizeTodayPlan(summary) {
  const p = summary?.today_plan
  if (!p || !Array.isArray(p.tracks)) return null
  const tracks = p.tracks.map((t) => ({
    key: t.key,
    label: t.label,
    unit: t.unit,
    value: toNum(t.value),
    available: toNum(t.available),
    quota: t.quota == null ? null : toNum(t.quota),
    cap: t.cap == null ? null : toNum(t.cap),
    countable: t.countable !== false,
    basis: t.basis || '',
    overQuota: toNum(t.over_quota),
    note: t.note || '',
  }))
  const by = {}
  tracks.forEach((t) => { by[t.key] = t })
  const backlog = p.backlog || {}
  return {
    itemsTotal: toNum(p.items_total),
    focusMinutes: p.focus_minutes == null ? null : toNum(p.focus_minutes),
    tracks,
    by,
    /** 复习类轨道之和（不含新词/待办/刷题）：对应「到期复习」这一步 */
    reviewTotal: ['review_words', 'cards', 'errors'].reduce((n, k) => n + (by[k]?.value || 0), 0),
    source: p.source || 'dashboard/summary · today_plan',
    version: p.version || '',
    rule: p.rule || '',
    subjectScope: Array.isArray(p.subject_scope) ? p.subject_scope : null,
    backlog: {
      dueTotal: toNum(backlog.due_total),
      outsideToday: toNum(backlog.outside_today),
      capacityPerDay: toNum(backlog.capacity_per_day),
      clearDays: toNum(backlog.clear_days),
      rule: backlog.rule || '',
    },
  }
}

/** 今日航线各步骤该显示的量：有 plan 用 plan，没有则退回旧口径（不编数）。 */
function planBy(plan, key, fallback) {
  const t = plan?.by?.[key]
  return t == null ? fallback : toNum(t.value)
}

const fmtInt = (n) => Number(n || 0).toLocaleString('zh-CN')

export function normalizeTasks(summary) {
  const block = summary?.today_tasks || {}
  const items = arr(block.tasks).map((t, i) => ({
    id: String(t.id ?? `task-${i}`),
    title: t.title || '未命名任务',
    subject: t.subject || '',
    status: t.status === 'done' ? 'done' : t.status === 'doing' ? 'doing' : 'pending',
  }))
  const modules = arr(block.modules).map((m) => ({
    key: m.module || m.key || m.label,
    label: m.label || m.module || '模块',
    done: toNum(m.done),
    due: m.due == null ? null : toNum(m.due),
    unit: m.unit || '',
    status: m.status || 'pending',
    note: m.note || '',
  }))
  return {
    items,
    modules,
    total: toNum(block.total, items.length),
    done: toNum(block.done, items.filter((t) => t.status === 'done').length),
    doing: toNum(block.doing),
    pending: toNum(block.pending, items.filter((t) => t.status !== 'done').length),
  }
}

export function normalizeWeakness(summary, insight) {
  const w = summary?.weakness || {}
  const fromSummary = arr(w.weak_points).map((p, i) => ({
    id: String(p.knowledge_point_id ?? `weak-${i}`),
    knowledgePointId: p.knowledge_point_id ?? null,
    name: p.name || p.kp || '未命名知识点',
    chapter: p.chapter || '',
    subject: p.subject || '',
    errorCount: toNum(p.error_count),
    mastery: p.mastery == null ? null : toNum(p.mastery),
  }))
  const points = fromSummary.length
    ? fromSummary
    : arr(insight?.weak_top).map((p, i) => ({
        id: String(p.knowledge_point_id ?? `weak-${i}`),
        knowledgePointId: p.knowledge_point_id ?? null,
        name: p.kp || p.name || '未命名知识点',
        chapter: '',
        subject: p.subject || '',
        errorCount: toNum(p.error_count),
        mastery: p.mastery == null ? null : toNum(p.mastery),
      }))
  const subjects = arr(w.weak_subjects).map((s) => ({
    subject: s.subject || '',
    count: toNum(s.count),
    level: s.level || 'low',
  }))
  const reasons = arr(w.common_reasons).map((r) => ({ reason: r.reason || '未标注', count: toNum(r.count) }))
  return {
    has: !!w.has_weakness || points.length > 0 || subjects.length > 0,
    totalErrors: toNum(w.total_errors, points.reduce((a, p) => a + p.errorCount, 0)),
    suggestion: w.suggestion || '',
    points,
    subjects,
    reasons,
  }
}

export function normalizeModules(summary) {
  /* W1：后端把「代码上机」这类工具模块移到 tool_modules，这里再兜一层，
     保证即使旧版后端还把它混在 module_progress 里，学习进度也不会被非考试科目污染。 */
  return arr(summary?.module_progress)
    .filter((m) => m.kind !== 'tool' && m.counts_toward_study !== false && m.module !== 'coding')
    .map((m) => ({
      key: m.module || m.key || m.label,
      label: m.label || m.module || '模块',
      done: m.done == null ? null : toNum(m.done),
      target: m.target == null ? null : toNum(m.target),
      targetSource: m.target_source || null,
      unit: m.unit || '',
      percent: m.percent == null ? null : clamp(m.percent),
      status: m.status || 'pending',
      note: m.note || '',
    }))
}

export function normalizeToolModules(summary) {
  return arr(summary?.tool_modules).map((m) => ({
    key: m.module || m.label,
    label: m.label || m.module || '工具',
    done: m.done == null ? null : toNum(m.done),
    unit: m.unit || '',
    reason: m.reason || m.note || '非备考科目，不计入学习进度',
  }))
}

export function normalizeTrend(summary) {
  const t = summary?.trend || {}
  const series = arr(t.series).map((d) => ({
    date: d.date || '',
    focus: toNum(d.focus_minutes),
    questions: toNum(d.questions_done),
    correct: toNum(d.questions_correct),
    correctRate: d.correct_rate == null ? null : toNum(d.correct_rate),
    words: toNum(d.words_done),
    cards: toNum(d.cards_done),
    tasks: toNum(d.tasks_done),
    effective: !!d.is_effective,
  }))
  return {
    days: toNum(t.days, series.length),
    series,
    weekFocus: toNum(t.week_focus_minutes),
    weeklyTasks: toNum(t.weekly_completed_tasks),
    subjectDurations: t.subject_durations && typeof t.subject_durations === 'object' ? t.subject_durations : {},
  }
}

export function normalizeHeatmap(summary) {
  const h = summary?.heatmap || {}
  const days = arr(h.days).map((d) => ({
    date: d.date || '',
    focus: toNum(d.focus_minutes),
    questions: toNum(d.questions_done),
    words: toNum(d.words_done),
    effective: !!d.is_effective,
  }))
  return {
    days,
    levels: arr(h.levels).map((v) => toNum(v)),
    valueField: h.value_field || 'focus_minutes',
  }
}

/* -------------------------------------------------------------------------- */
/* 今日航线（动态优先级队列）                                                   */
/* -------------------------------------------------------------------------- */

/**
 * 把「今日引导建议 + 到期总量 + 薄弱点 + 任务 + 单词 + 专注」合成一条航线。
 *
 * 优先级不是拍脑袋：到期复习（有欠账）> 薄弱点（有错题）> 今日待办 >
 * 单词/卡片到期 > 今天还没开始专注 > 今天还没刷题。`urgency` 只决定顺序。
 *
 * 完成口径（FE_REVIEW P0-3）：**分子只统计今天真实发生的完成动作**。
 *  - 「没有欠账」≠「已完成」：队列空且今天没有产出 → `empty`（中性待办，
 *    不计入进度分母），绝不伪造 done；
 *  - 队列空但今天有真实产出（复习过/背过词/清过卡片/任务全清）→ done；
 *  - 专注/刷题以「今天是否达到目标（未设目标则 ≥1）」判定。
 * 每一步带 `state`（done/doing/warning/todo），供页面映射 5 状态色。
 */
export function deriveFocusQueue({ due, tasks, weakness, words, today, suggestions, review, targets, plan } = {}) {
  const sug = arr(suggestions)
  const byIcon = (icon) => sug.find((s) => s.icon === icon)
  const focusMinutes = toNum(today?.focus_minutes)
  const answered = toNum(today?.questions_done)
  const wordsDoneToday = toNum(today?.words_done)
  const cardsDoneToday = toNum(today?.cards_done)
  const reviewsToday = toNum(review?.todayReviews)
  const weakPoints = arr(weakness?.points)
  const pendingTasks = toNum(tasks?.pending)
  const totalTasks = toNum(tasks?.total)
  /* W1：有今日推荐量时，步骤数字一律取推荐量（"今天该做多少"），
     整库到期量降级成 hint 里的复习债；没有 plan 才退回旧口径。
     旧口径把「词库未学总量」加进今日队列，正是"一天 11653 词"的来源。 */
  const dueWords = toNum(words?.due_today ?? due?.breakdown?.words)
  const wordCount = plan
    ? (plan.by.new_words?.value || 0) + (plan.by.review_words?.value || 0)
    : toNum(due?.newWords) + dueWords
  const reviewCount = plan ? plan.reviewTotal : toNum(due?.planner)
  const cardCount = planBy(plan, 'cards', toNum(due?.breakdown?.cards))
  const taskCount = planBy(plan, 'tasks', pendingTasks)
  const focusTarget = toNum(targets?.focus) || (plan?.by?.focus?.value ?? 0)
  const quizTarget = toNum(targets?.questions) || (plan?.by?.questions?.value ?? 0)
  const newWordQuota = toNum(targets?.newWords) || (plan?.by?.new_words?.value ?? 0)
  const debtHint = plan?.backlog?.dueTotal
    ? `复习债 ${fmtInt(plan.backlog.dueTotal)} 项，今日排 ${plan.itemsTotal} 项`
    : ''

  const items = [
    {
      id: 'review',
      order: 1,
      label: '到期复习',
      hint: byIcon('review')?.hint || (reviewCount ? '先清掉今天到期的复习队列' : reviewsToday ? '今天到期的复习已清完' : '暂无到期复习，保持节奏'),
      count: reviewCount,
      unit: '条',
      to: '/quiz?tab=review',
      tone: 'violet',
      icon: 'review',
      done: reviewCount === 0 && reviewsToday > 0,
      empty: reviewCount === 0 && reviewsToday === 0,
      urgency: reviewCount > 0 ? 100 : 10,
    },
    {
      id: 'weak',
      order: 2,
      label: '薄弱点练习',
      hint: byIcon('target')?.hint || (weakPoints.length ? '针对高频错点做专项训练' : '暂无薄弱点数据'),
      count: weakPoints.length,
      unit: '个',
      to: '/quiz?mode=weak',
      tone: 'rose',
      icon: 'target',
      /* 薄弱点没有「今日已练」的可靠信号：清零只代表没有欠账，不代表完成 */
      done: false,
      empty: weakPoints.length === 0,
      urgency: weakPoints.length ? 80 : 8,
    },
    {
      id: 'tasks',
      order: 3,
      label: '今日待办',
      hint: byIcon('todo')?.hint || (pendingTasks ? '按计划推进今天的任务' : totalTasks ? '今日任务已全部完成' : '还没有安排今日任务'),
      count: taskCount,
      unit: '项',
      to: '/tasks',
      tone: 'amber',
      icon: 'todo',
      done: totalTasks > 0 && taskCount === 0,
      empty: totalTasks === 0,
      urgency: taskCount ? 70 : 7,
    },
    {
      id: 'words',
      order: 4,
      label: '单词记忆',
      /* 诚实口径（W1）：数字是「今日推荐量 = 新词配额 + 复习配额」，
         词库未学总量只作为复习债出现在 hint 里，不再相加冒充今日任务 */
      hint: plan
        ? (debtHint || `今日新词 ${plan.by.new_words?.value || 0} · 复习 ${plan.by.review_words?.value || 0}`)
        : (newWordQuota
          ? `今日已学 ${wordsDoneToday}/${newWordQuota} · 到期 ${dueWords}`
          : `词库未学 ${toNum(due?.newWords)} · 到期 ${dueWords}`),
      count: wordCount,
      unit: '词',
      to: '/words',
      tone: 'green',
      icon: 'word',
      done: wordCount === 0 && wordsDoneToday > 0,
      empty: wordCount === 0 && wordsDoneToday === 0,
      urgency: wordCount ? 65 : 6,
    },
    {
      id: 'cards',
      order: 5,
      label: '记忆卡片',
      hint: cardCount ? '间隔复习到期，先清卡片' : cardsDoneToday ? '到期卡片已清完' : '暂无到期卡片',
      count: cardCount,
      unit: '张',
      to: '/cards',
      tone: 'blue',
      icon: 'card',
      done: cardCount === 0 && cardsDoneToday > 0,
      empty: cardCount === 0 && cardsDoneToday === 0,
      urgency: cardCount ? 60 : 5,
    },
    {
      id: 'focus',
      order: 6,
      label: '专注计时',
      hint: focusMinutes ? `今天已专注 ${focusMinutes} 分钟` : '今天还没开始，先来一轮 25 分钟',
      count: focusMinutes,
      unit: '分钟',
      to: '/planner',
      tone: 'indigo',
      icon: 'focus',
      done: focusMinutes >= (focusTarget || 1),
      empty: false,
      urgency: focusMinutes > 0 ? 4 : 55,
    },
    {
      id: 'quiz',
      order: 7,
      label: '今日刷题',
      hint: byIcon('brain')?.hint || (answered ? `今天已答 ${answered} 题` : '今天还没开始刷题'),
      count: answered,
      unit: '道',
      to: '/quiz',
      tone: 'cyan',
      icon: 'brain',
      done: answered >= (quizTarget || 1),
      empty: false,
      urgency: answered > 0 ? 3 : 45,
    },
  ]

  const ordered = [...items].sort((a, b) => b.urgency - a.urgency || a.order - b.order)
  const activeId = ordered.find((i) => !i.done && !i.empty)?.id || null
  ordered.forEach((i) => {
    if (i.done) i.state = 'done'
    else if (i.id === activeId) i.state = 'doing'
    else if (!i.empty && (i.id === 'review' || i.id === 'weak') && i.count > 0) i.state = 'warning'
    else i.state = 'todo'
  })
  const countable = ordered.filter((i) => !i.empty)
  const doneCount = ordered.filter((i) => i.done).length
  const remainingCount = countable.filter((i) => !i.done).length
  return {
    items: ordered,
    activeId,
    doneCount,
    total: ordered.length,
    countableTotal: countable.length,
    remainingCount,
    progress: countable.length ? Math.round((doneCount / countable.length) * 100) : 0,
  }
}

/* -------------------------------------------------------------------------- */
/* 组装                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * 纯函数：把 4 个端点的响应组装成页面模型。任何入参为空都能安全返回，
 * 便于单测与「部分接口失败」的降级渲染。
 */
export function buildHubModel({ summary = null, insight = null, words = null, review = null, sources = [] } = {}) {
  const now = new Date()
  const countdown = normalizeCountdown(summary, insight)
  const goal = normalizeGoal(summary?.goal)
  const kpi = summary?.kpi || {}
  const today = kpi.today || {}
  const yesterday = kpi.yesterday || {}
  const delta = kpi.delta || {}
  const streak = kpi.streak || {}
  const trend = normalizeTrend(summary)
  const heatmap = normalizeHeatmap(summary)
  const tasks = normalizeTasks(summary)
  const weakness = normalizeWeakness(summary, insight)
  const due = normalizeDue({ summary, insight, words, review })
  const plan = normalizeTodayPlan(summary)
  const modules = normalizeModules(summary)
  const wordsModel = {
    total: toNum(words?.total),
    new: toNum(words?.new),
    due: toNum(words?.due_today),
    learning: toNum(words?.learning),
    reviewing: toNum(words?.reviewing),
    mastered: toNum(words?.mastered),
  }
  const reviewModel = {
    activeErrors: toNum(review?.active_errors),
    dueErrors: toNum(review?.due_errors),
    graduatedErrors: toNum(review?.graduated_errors),
    todayReviews: toNum(review?.today_reviews),
    totalReviews: toNum(review?.total_reviews),
  }
  const range = arr(trend.series).slice(-14)
  const numSeries = (key) => range.map((d) => toNum(d[key]))
  const activitySeries = heatmap.days.slice(-14).map((d) => (d.focus > 0 || d.questions > 0 || d.words > 0 ? 1 : 0))

  const kpiCards = [
    {
      id: 'focus',
      label: '今日专注',
      value: toNum(today.focus_minutes),
      unit: '分钟',
      delta: toNum(delta.focus_minutes),
      hint: goal.dailyTargets.focus
        ? `目标 ${goal.dailyTargets.focus} 分钟`
        : (plan?.focusMinutes ? `今日建议 ${plan.focusMinutes} 分钟（系统按可用时长排）` : '未设置每日时长目标'),
      to: '/planner',
      icon: 'focus',
      tone: 'indigo',
      series: numSeries('focus'),
    },
    {
      id: 'questions',
      label: '今日答题',
      value: toNum(today.questions_done),
      unit: '道',
      delta: toNum(delta.questions_done),
      hint: goal.dailyTargets.questions
        ? `目标 ${goal.dailyTargets.questions} 道`
        : (plan?.by?.questions?.value
          ? `今日建议 ${plan.by.questions.value} 道 · 昨天 ${toNum(yesterday.questions_done)} 道`
          : `昨天 ${toNum(yesterday.questions_done)} 道`),
      to: '/quiz',
      icon: 'quiz',
      tone: 'cyan',
      series: numSeries('questions'),
    },
    {
      id: 'accuracy',
      label: '今日正确率',
      value: today.correct_rate == null ? null : toNum(today.correct_rate),
      unit: '%',
      delta: delta.correct_rate_pp == null ? null : toNum(delta.correct_rate_pp),
      hint: today.correct_rate == null ? '今天还没答题' : `昨天 ${today.correct_rate == null ? '—' : `${toNum(yesterday.correct_rate)}%`}`,
      to: '/insights',
      icon: 'accuracy',
      tone: 'violet',
      series: range.map((d) => toNum(d.correctRate)),
    },
    {
      id: 'streak',
      label: '连续打卡',
      value: toNum(streak.current),
      unit: '天',
      delta: null,
      hint: `最长 ${toNum(streak.longest)} 天 · 累计 ${toNum(streak.total_days)} 天`,
      to: '/profile',
      icon: 'streak',
      tone: 'amber',
      series: activitySeries,
    },
  ]

  const queue = deriveFocusQueue({
    due,
    tasks,
    weakness,
    words: wordsModel,
    today,
    suggestions: insight?.suggestions,
    review: reviewModel,
    targets: goal.dailyTargets,
    plan,
  })

  const goalLine = [goal.university || countdown.university, goal.major || countdown.major].filter(Boolean).join(' · ')

  /* 口径对账表：一个指标一行，只写「谁算的、什么切点」。
     W1 把「今日推荐量」放在第一行 —— 它才是页面主数字的出处；
     到期/复习债降级为后面的对照行，明确"这不是今天该做完的量"。 */
  const caliber = [
    {
      label: '今日推荐量',
      value: plan ? plan.itemsTotal : null,
      unit: '项',
      source: plan ? `dashboard/summary · ${plan.source}` : '后端未返回 today_plan（退回旧口径）',
      note: plan
        ? 'min(真实到期, 目标配额或系统建议量, 合理上限)；专注分钟不并入项数'
        : '主数字暂时退回「今日累计到期」口径，请升级后端',
    },
    {
      label: '今日累计到期',
      value: due.schedulerToday,
      unit: '项',
      source: 'dashboard/summary · future_load.due_today',
      note: '截至今日 24:00 的复习债（含此前欠账），不是今天要做完的量',
    },
    {
      label: '现在可做',
      value: due.nowTotal == null ? null : due.nowTotal,
      unit: '项',
      source: 'dashboard/summary · review_queue',
      note: 'next_review ≤ 当前时刻；与「今日累计」切点不同，不冲突',
    },
    {
      label: '艾宾浩斯到期',
      value: due.planner,
      unit: '条',
      source: 'insight/today · due_review_count',
      note: insight?.due_review_truncated ? '命中取数上限 200，实际到期更多' : '复盘计划的独立队列，不计入卡片/错题调度',
    },
    {
      label: '词库未学',
      value: due.newWords,
      unit: '词',
      source: 'words/stats · new',
      note: '词库内未学总量（库存），不是今日新词配额；今日新词见上行 today_plan',
    },
  ]

  const failed = arr(sources).filter((s) => !s.ok)
  return {
    generatedAt: summary?.generated_at || '',
    dateLabel: `${now.getMonth() + 1} 月 ${now.getDate()} 日 · 星期${WEEK_CN[now.getDay()]}`,
    countdown,
    goal,
    goalLine,
    today,
    yesterday,
    delta,
    streak: {
      current: toNum(streak.current),
      longest: toNum(streak.longest),
      totalDays: toNum(streak.total_days),
      checkedToday: !!streak.checked_today,
      rule: streak.rule || '',
    },
    kpiCards,
    due,
    /* 页面唯一主数字（W1）：「今天该做 N 项」= 今日推荐量（算法 + 配额 + 上限）。
       复习债（今日累计到期）与「现在可做」降级为副文案，切点不同、语义不同，
       绝不再拿复习债当主数字 —— 那是"今天该做 5700 项"的直接来源。 */
    todayTodoCount: plan ? plan.itemsTotal : due.schedulerToday,
    nowAvailableCount: due.nowTotal,
    reviewDebtCount: due.schedulerToday,
    plan,
    toolModules: normalizeToolModules(summary),
    tasks,
    weakness,
    words: wordsModel,
    review: reviewModel,
    modules,
    trend,
    heatmap,
    reviewQueue: summary?.review_queue || null,
    focusSubjects: dedupeSubjects([...goal.subjects, ...goal.supportSubjects]),
    dataCoverage: summary?.data_coverage || null,
    queue,
    caliber,
    sources: arr(sources),
    failedSources: failed,
    degraded: failed.length > 0,
    isEmpty: !!summary?.data_coverage?.is_empty,
  }
}

/* -------------------------------------------------------------------------- */
/* 拉取 + 缓存                                                                 */
/* -------------------------------------------------------------------------- */

let cache = { at: 0, data: null }
let inflight = null
/* 代际号：mutation 发生在请求期间时，完成后不得把「已过时的快照」写回缓存 */
let generation = 0

/** 同步读取缓存快照：用于「切页回来先渲染旧数据，再后台刷新」。 */
export function peekHubCache() {
  return cache.data
}

/** 测试/退出登录时清空，避免上一个账号的聚合数据被复用。 */
export function clearHubCache() {
  cache = { at: 0, data: null }
  inflight = null
  generation += 1
}

/* client.js 任何非 GET 请求成功都会广播 MUTATION_EVENT；
   立刻失效缓存，下一次进入 /hub 直接重新拉取，保证 45s TTL 内也不会展示旧数字。 */
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener(MUTATION_EVENT, clearHubCache)
}

function nowMs() {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') return performance.now()
  return Date.now()
}

async function timed(fn) {
  const t0 = nowMs()
  try {
    const value = await fn()
    return { ok: true, value, ms: Math.round(nowMs() - t0) }
  } catch (error) {
    return { ok: false, error, ms: Math.round(nowMs() - t0) }
  }
}

/**
 * 唯一对外出口。
 *
 * @param {{ force?: boolean, ttl?: number }} opts
 *   force=true 跳过缓存（手动刷新）；ttl 可覆盖默认缓存窗口。
 * @returns 页面模型；`fromCache` 标记是否命中缓存。
 */
export async function fetchHubOverview({ force = false, ttl = HUB_CACHE_TTL } = {}) {
  if (!force && cache.data && Date.now() - cache.at < ttl) {
    return { ...cache.data, fromCache: true }
  }
  if (inflight) return inflight

  const gen = generation
  inflight = (async () => {
    const [summary, insight, words, review] = await Promise.all([
      timed(() => dashboardApi.summary()),
      timed(() => insightApi.today()),
      timed(() => wordsApi.stats()),
      timed(() => reviewApi.stats()),
    ])

    /* 两个核心聚合都挂了才认为整页失败；单点失败降级渲染。 */
    if (!summary.ok && !insight.ok) {
      throw summary.error || insight.error || new Error('聚合接口暂不可用')
    }

    const sources = [
      { key: 'summary', label: '仪表盘聚合', path: '/dashboard/summary', ok: summary.ok, ms: summary.ms, error: summary.error ? String(summary.error.message || summary.error) : '' },
      { key: 'insight', label: '今日引导', path: '/insight/today', ok: insight.ok, ms: insight.ms, error: insight.error ? String(insight.error.message || insight.error) : '' },
      { key: 'words', label: '单词统计', path: '/words/stats', ok: words.ok, ms: words.ms, error: words.error ? String(words.error.message || words.error) : '' },
      { key: 'review', label: '复习统计', path: '/review/stats', ok: review.ok, ms: review.ms, error: review.error ? String(review.error.message || review.error) : '' },
    ]
    const model = buildHubModel({
      summary: summary.value,
      insight: insight.value,
      words: words.value,
      review: review.value,
      sources,
    })
    /* 请求期间若发生 mutation（generation 变化），说明数据已被改写，
       这份快照已过时 —— 返回给调用方渲染，但不写回缓存。 */
    if (gen === generation) {
      cache = { at: Date.now(), data: model }
    }
    return model
  })().finally(() => {
    inflight = null
  })

  return inflight
}
