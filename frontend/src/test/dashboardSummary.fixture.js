/**
 * GET /api/dashboard/summary 的测试替身（#13 首屏唯一聚合出口）。
 *
 * 形状严格对齐后端 services/dashboard_service.DashboardService.get_summary：
 * 三个渲染 Dashboard 的用例文件都从这里取，避免同一契约在测试里被复制三份、
 * 各自漂移（漂移后就测不出「前端读的是不是后端真实字段」）。
 *
 * 默认是**空态**（用户还没放数据）：
 * - daily_targets 全 null → module_progress 全是 no_target / not_tracked，percent 为 null
 * - day_ledger 为空 → streak 全 0、heatmap/trend 序列存在但值为 0
 * - goal.configured=false、recent_score_lines=[]
 * 页面必须能在这一份数据上完整渲染，这是「无数据框架」验收的一部分。
 */
export function emptyDay(date = '2026-10-16') {
  return {
    date,
    focus_minutes: 0,
    words_done: 0,
    cards_done: 0,
    knowledge_done: 0,
    errors_done: 0,
    questions_done: 0,
    questions_correct: 0,
    correct_rate: null,
    exams_done: 0,
    tasks_done: 0,
    errors_added: 0,
    is_effective: false,
    is_active: false,
  }
}

const RANGE = 53 * 7

/** 今日任务清单（D-03）的模块表：[module, 到期键, 台账完成字段, 标签, 单位]。
 *  与后端 services/dashboard_service._DUE_ROLLUP 一一对应——到期键为 null 就是
 *  「无排程源」，必须渲染成 not_tracked 而不是 0。 */
const DUE_ROLLUP = [
  ['word', 'words', 'words_done', '单词复习', '个'],
  ['card', 'flashcards', 'cards_done', '记忆卡片', '张'],
  ['wrongbook', 'errors', 'errors_done', '错题复习', '道'],
  ['task', 'tasks', 'tasks_done', '任务待办', '项'],
  ['question', null, 'questions_done', '刷题', '道'],
  ['realexam', null, 'exams_done', '真题模考', '套'],
]
const DUE_NOTES = {
  question: '题库没有排程字段，到期量要等知识点调度（#12/#14）接入',
  realexam: '真题按套卷手动开考，没有到期队列',
}

/** 按后端同一规则派生 modules：到期数来自 future_load.due_today */
export function makeTaskModules(dueToday, day) {
  return DUE_ROLLUP.map(([module, dueKey, field, label, unit]) => {
    const due = dueKey && dueToday ? dueToday[dueKey] : null
    return {
      module,
      label,
      unit,
      due,
      done: day ? day[field] : null,
      status: due == null ? 'not_tracked' : (due === 0 ? 'clear' : 'pending'),
      note: DUE_NOTES[module] || null,
    }
  })
}

/** 近 53 周、周一对齐、截至今日的连续日序列（与后端 effective_activity_days 一致） */
function daySeries(count, today = new Date('2026-10-16')) {
  const out = []
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    out.push(emptyDay(d.toISOString().slice(0, 10)))
  }
  return out
}

export function makeSummary(overrides = {}) {
  const dueToday = { flashcards: 0, tasks: 0, errors: 0, words: 0, total: 0, cutoff: '2026-10-16T16:00:00Z' }
  const today = emptyDay('2026-10-16')
  const base = {
    generated_at: '2026-10-16T20:00:00Z',
    timezone: 'Asia/Shanghai',
    countdown: {
      days: 64, days_left: 64, exam_date: '2026-12-19', exam_year: 2027,
      phase: 'intensify', is_official: true, source: '教育部公布',
      university: null, major: null, total_score_target: null,
      is_passed: false, is_default: false, signup_hint: null,
    },
    goal: {
      configured: false, university: null, major: null,
      subjects: [], support_subjects: [],
      score_targets: { total: null, politics: null, english: null, math: null, major: null },
      daily_targets: { focus_minutes: null, new_words: null, review_words: null, questions: null },
      targets_set: false,
      recent_score_lines: [],
    },
    kpi: {
      today,
      yesterday: emptyDay('2026-10-15'),
      delta: { focus_minutes: 0, words_done: 0, questions_done: 0, tasks_done: 0, errors_done: 0, correct_rate_pp: null },
      streak: {
        current: 0, longest: 0, total_days: 0, checked_today: false,
        first_day: null, rule: '当日专注 ≥10 分钟，或复习单词 ≥10 个，或答题 ≥5 道',
      },
    },
    module_progress: [
      { module: 'focus', label: '专注时长', unit: '分钟', done: 0, target: null, percent: null, status: 'no_target', note: null },
      { module: 'word', label: '单词复习', unit: '个', done: 0, target: null, percent: null, status: 'no_target', note: null },
      { module: 'new_word', label: '今日新词', unit: '个', done: null, target: null, percent: null, status: 'not_tracked', note: '新学/复习要等 FSRS 调度器分流（#12）后才有事件源' },
      { module: 'question', label: '刷题', unit: '道', done: 0, target: null, percent: null, status: 'no_target', note: null },
      { module: 'realexam', label: '真题模考', unit: '套', done: 0, target: null, percent: null, status: 'no_target', note: null },
      { module: 'wrongbook', label: '错题复习', unit: '道', done: 0, target: null, percent: null, status: 'no_target', note: null },
      { module: 'coding', label: '代码上机', unit: '题', done: null, target: null, percent: null, status: 'not_tracked', note: '代码上机判题表未建（#16 OJ）' },
    ],
    today_tasks: { total: 0, pending: 0, doing: 0, done: 0, modules: makeTaskModules(dueToday, today), tasks: [] },
    review_queue: {
      generated_at: '2026-10-16T20:00:00Z', source: 'review_scheduler',
      total: 0, limit: 50, truncated: false, cards: [], tasks: [], errors: [],
    },
    heatmap: { weeks: 53, value_field: 'focus_minutes', levels: [0, 30, 90, 180], days: daySeries(RANGE) },
    trend: {
      days: 14, series: daySeries(14), week_focus_minutes: 0,
      subject_durations: {}, weekly_completed_tasks: 0,
    },
    // D-10：weak_points 由 services/error_linker.weak_knowledge_points 取前 3 条
    weakness: {
      has_weakness: false, total_errors: 0, weak_subjects: [],
      weak_points: [], common_reasons: [], suggestion: null,
    },
    future_load: {
      due_today: dueToday,
      due_tomorrow: { flashcards: 0, tasks: 0, errors: 0, words: 0, total: 0, cutoff: '2026-10-17T16:00:00Z' },
      due_this_week: { flashcards: 0, tasks: 0, errors: 0, words: 0, total: 0, cutoff: '2026-10-22T16:00:00Z' },
      rule: '累计到期量（含此前未清的复习债），切点为对应北京自然日 24:00',
    },
    errors: { active: 0, due: 0, source: 'services.error_linker.error_stats' },
    data_coverage: {
      days_with_activity: 0, first_day: null, today_effective: false,
      is_empty: true, empty_hint: '还没有学习记录，先去完成一次专注或复习 10 个词，今天的第一格就亮了。',
    },
  }
  return { ...base, ...overrides }
}

export const summaryPayload = makeSummary()
