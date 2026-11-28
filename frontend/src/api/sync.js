/* ============================================================
   考研档案 · 数据同步层（P0-1）
   后端优先：应用挂载时从 FastAPI 拉取真实数据回填 zustand store，
   覆盖 localStorage 中的历史数据；后端不可用则静默保留本地。
   写操作的后端同步已内联在 useStore.js 各 action 中（fire-and-forget）。
   ============================================================ */

import {
  tasksApi, errorsApi, flashcardsApi, netdiskApi, goalsApi, aiApi, dashboardApi,
  wordsApi, fetchAllPages, getBackendState, isBackendOnline,
} from './client'
import useStore from '../store/useStore'
import { todayStr } from '../utils/date'
import { currentUid } from '../utils/userKeys'

/* P0（跨账号串号）：hydrate 代际守卫。
   A 账号发起的回填请求还在途时用户切到 B（setUser 改 uid），响应回来若
   无条件 setState，A 的数据会落进 B 的 store 并按 B 的 uid 落盘。
   每个 loader 发起时记录当时的 uid，回写前校验未变；变了就丢弃响应。 */
const stale = (uidAtStart) => currentUid() !== uidAtStart
const inactive = (uidAtStart, signal) => stale(uidAtStart) || signal?.aborted

/* 分类为空就留空：补成「专业课」等于凭空造了一个分类，筛选里会多出一个假桶。 */
const PAN_TYPE_LABEL = { pdf: 'PDF', video: '视频', doc: '文档', zip: '压缩包' }

/* 后端字段 → 前端 store 字段映射 */
function toTask(t) {
  return {
    id: String(t.id),
    title: t.title,
    // 科目为空就留空：补成 'major' 会让页面显示「专业课」，等于凭空给用户加了一个科目。
    subject: t.subject || '',
    // W3：多选科目 / 子科目模块 / 起止 / 循环 / 提醒 / 进度条 / 按日打卡（后端为权威）
    subjects: Array.isArray(t.subjects) && t.subjects.length ? t.subjects : (t.subject ? [t.subject] : []),
    modules: t.modules || [],
    due: (t.due_date || t.due || todayStr()).slice(0, 10),
    start: t.start_date ? String(t.start_date).slice(0, 10) : null,
    end: t.end_date ? String(t.end_date).slice(0, 10) : null,
    recurrence: t.recurrence || { freq: 'none' },
    remind: t.remind || null,
    showProgress: !!t.show_progress,
    progressTotal: t.progress_total ?? null,
    progressDone: t.progress_done || 0,
    doneDates: t.checkin_dates || [],
    isRecurring: !!t.is_recurring,
    done: t.status === 'done' || t.status === 'completed',
    ai: !!t.is_ai,
    reviewCount: t.review_count || 0
  }
}

function toNote(n) {
  return {
    id: String(n.id),
    subject: n.subject || 'other',
    question: n.content || n.question || '',
    answer: n.correct_answer || n.answer || '',
    analysis: n.analysis || '',
    reason: n.error_reason || '',
    mastery: Math.min(Math.max(Number(n.accuracy) >= 0.8 ? 5 : Number(n.review_count || 0) % 7, 0), 7),
    tags: n.tags || [],
    createdAt: (n.created_at || todayStr()).slice(0, 10),
    lastReview: n.last_review ? n.last_review.slice(0, 10) : null,
    reviews: []
  }
}

function toCard(c) {
  const masteryMap = { new: 'new', learning: 'new', mastered: 'mastered', review: 'learning' }
  return {
    id: String(c.id),
    front: c.front,
    back: c.back,
    hint: '',
    // 后端卡片无卡组概念，统一归入“全部卡组”
    packId: 'all',
    status: masteryMap[c.mastery] || 'new',
    ef: c.ease_factor || 2.5,
    interval: c.interval || 0,
    reps: c.review_count || 0,
    lapses: 0,
    due: c.next_review ? c.next_review.slice(0, 10) : todayStr(),
    lastReview: null
  }
}

function toPan(f) {
  const typeMap = { pdf: 'pdf', video: 'video', doc: 'doc', zip: 'zip' }
  return {
    id: String(f.id),
    name: f.file_name,
    type: typeMap[f.file_type] || 'other',
    size: f.size || 0,
    cat: f.category || PAN_TYPE_LABEL[f.file_type] || '未分类',
    desc: f.path || '',
    // 后端不再下发百度 dlink（带签名的临时直连地址）。取流统一走后端代理，
    // 由它补百度强制的 User-Agent，也顺带让 access_token 留在服务端。
    url: f.id ? netdiskApi.contentUrl(f.id) : '',
    synced: true,
    // 没有 created_at 就留空：写成今天会让「最近同步」把无日期项顶到第一位，
    // 排序依据就成了编的。页面用 fmtDateCN 兜底显示「日期未知」。
    date: f.created_at ? String(f.created_at).slice(0, 10) : '',
    remote: true,
    fsId: f.fs_id ?? null
  }
}

function toProvider(p) {
  return {
    id: String(p.id),
    key: p.provider_type || 'custom',
    name: p.name,
    baseUrl: p.base_url || '',
    model: p.model_name || '',
    apiKey: p.api_key || '',
    enabled: p.is_enabled !== false,
    default: !!p.is_default,
    vision: false,
    proxy: '',
    test: null
  }
}

/* 各数据域拉取与回填。
   后端成功响应即为准：空数组也要覆盖本地，否则"删光了"会被显示成"还没同步"。
   请求抛错时该域不动（离线时保留本地已有内容）。
   取全量一律走 fetchAllPages —— 后端 page_size 上限 200，写 500 是 422 而不是截断，
   以前三个域都因此从未真正回填过。 */
const LOADERS = {
  tasks: async (signal) => {
    const uidAtStart = currentUid()
    const list = await fetchAllPages((p, requestSignal) => tasksApi.list(p, { signal: requestSignal }), { keys: ['tasks'], signal })
    if (inactive(uidAtStart, signal)) return
    useStore.setState({ tasks: list.map(toTask) })
  },
  notebook: async (signal) => {
    const uidAtStart = currentUid()
    const list = await fetchAllPages((p, requestSignal) => errorsApi.list(p, { signal: requestSignal }), { keys: ['errors'], signal })
    if (inactive(uidAtStart, signal)) return
    useStore.setState({ notebook: list.map(toNote) })
  },
  cards: async (signal) => {
    const uidAtStart = currentUid()
    const list = await fetchAllPages((p, requestSignal) => flashcardsApi.list(p, { signal: requestSignal }), { keys: ['cards'], signal })
    if (inactive(uidAtStart, signal)) return
    useStore.setState({ cards: list.map(toCard) })
  },
  /* 单词域：Settings 的「学习数据一览」读 store.words，但这里从来没有加载器，
     导致后端 /api/words 明明有数据、页面永远显示 0。补上（响应是统一分页壳 items）。 */
  words: async (signal) => {
    const uidAtStart = currentUid()
    // include_extra=false：词库页自己会按需补详情，后台同步不必为近义词/短语付八成载荷。
    const list = await fetchAllPages(
      (p, requestSignal) => wordsApi.list({ ...p, include_extra: false }, { signal: requestSignal }),
      { keys: ['items', 'words'], signal },
    )
    if (inactive(uidAtStart, signal)) return
    useStore.setState({ words: list })
  },
  /* 网盘域（P2-1）：
     后端现在把三种状态分开 —— 从未授权返回 200 + netdisk_authorized=false，
     曾授权但 token 失效才 409（action=reauthorize）。首屏 hydrate 会拉本域，
     未绑网盘的机器以前每次都吃一个 409 噪音。
     这里再兜一层：即使后端仍抛 409（token 途中过期），本域也静默降级 ——
     store.pan 只喂给助手/设置页的本地文件视图，不该让整次 hydrate 记为失败。 */
  pan: async (signal) => {
    const uidAtStart = currentUid()
    try {
      const list = await fetchAllPages((p, requestSignal) => netdiskApi.files(p, { signal: requestSignal }), { keys: ['local_files'], signal })
      if (inactive(uidAtStart, signal)) return
      useStore.setState({ pan: list.map(toPan) })
    } catch (e) {
      if (inactive(uidAtStart, signal)) return
      // ApiError.status 是 HTTP 码；网盘授权类错误体里带 code=NETDISK_AUTH_*
      const code = e?.data?.code || ''
      if (e?.status === 409 || String(code).startsWith('NETDISK_AUTH')) return
      throw e
    }
  },
  countdown: async (signal) => {
    const uidAtStart = currentUid()
    const d = await dashboardApi.countdown({ signal })
    if (inactive(uidAtStart, signal)) return
    if (d && d.exam_date) useStore.setState({ countdown: d })
  },
  settings: async (signal) => {
    const uidAtStart = currentUid()
    const g = await goalsApi.list({ signal })
    if (inactive(uidAtStart, signal)) return
    const goal = Array.isArray(g) ? (g[0] || null) : (g || null)
    if (goal) {
      const patch = {}
      if (goal.university) patch.school = goal.university
      if (goal.major) patch.major = goal.major
      if (goal.exam_date) patch.examDate = String(goal.exam_date).slice(0, 10)
      if (goal.total_score_target != null) patch.targetScore = goal.total_score_target
      useStore.setState((s) => ({ settings: { ...s.settings, ...patch } }))
    }
  },
  aiProviders: async (signal) => {
    const uidAtStart = currentUid()
    const d = await aiApi.providers({ signal })
    if (inactive(uidAtStart, signal)) return
    const list = d.providers || d.items || (Array.isArray(d) ? d : [])
    if (Array.isArray(list) && list.length) {
      useStore.setState((s) => ({ settings: { ...s.settings, aiProviders: list.map(toProvider) } }))
    }
  }
}

/**
 * 单域回填：给页面级「刷新」按钮用。
 * 与 hydrate 走的是同一个 loader，所以两处的口径（全量分页、空结果也覆盖本地）
 * 天然一致——以前 Tasks.jsx 自己写了一遍拉取逻辑，结果页面和同步层对同一份数据
 * 有两种解释（比如 subject 为空时被补成「专业课」）。
 */
export function loadDomain(key) {
  const fn = LOADERS[key]
  if (!fn) return Promise.reject(new Error(`未知数据域：${key}`))
  return fn()
}

/* 首屏关键路径保护（性能 · LCP）：
   words / cards / pan 是「翻全量」的重域——数千行、数十个分页请求。旧实现把它们
   与轻量域一起在应用挂载瞬间并发拉取；云端走 HTTP/1.1，每源只有 6 个并发连接，
   这股洪水会把首屏路由 chunk、schools 数据、字体全部挤到队尾，实测把 LCP 渲染延迟
   拖到 2.5s+（TTFB 仅 15ms，瓶颈全在前端渲染等待）。
   这些数据只有进入对应功能页才用到，且 Words/Flashcards 页本身会自加载，因此把重域
   挪到首屏渲染后/浏览器空闲时再拉；即时域只保留应用壳导航与在线判定所需的轻量调用。 */
const DEFERRED_DOMAINS = ['words', 'cards', 'pan']
const DEFERRED_SLICE = { words: 'words', cards: 'cards', pan: 'pan' }

function runDeferredDomains(uidAtStart, signal) {
  if (inactive(uidAtStart, signal)) return Promise.resolve()
  /* 重域之间串行错峰：即便放到后台，也不再形成数十并发的洪水，减轻 DB 与连接池压力。
     若对应 store 切片已有数据（功能页已自加载或本地缓存命中），跳过重复全量拉取。 */
  return DEFERRED_DOMAINS.reduce(
    (chain, key) =>
      chain.then(() => {
        if (inactive(uidAtStart, signal)) return null
        const slice = DEFERRED_SLICE[key]
        if (slice && Array.isArray(useStore.getState()[slice]) && useStore.getState()[slice].length > 0) {
          return null
        }
        return LOADERS[key](signal).catch(() => {
          /* 单域失败不影响其它域；离线时静默保留本地已有内容 */
        })
      }),
    Promise.resolve()
  )
}

function scheduleDeferredHydrate(uidAtStart, signal) {
  if (signal?.aborted) return
  const target = window
  let done = false
  let timer
  const cleanupTriggers = () => {
    target.removeEventListener('pointerdown', run)
    target.removeEventListener('keydown', run)
    target.removeEventListener('scroll', run, true)
    if (timer != null) clearTimeout(timer)
  }
  const cleanup = () => {
    cleanupTriggers()
    signal?.removeEventListener('abort', onAbort)
  }
  const run = () => {
    if (done) return
    done = true
    cleanupTriggers()
    void runDeferredDomains(uidAtStart, signal).finally(cleanup)
  }
  const onAbort = () => {
    done = true
    cleanup()
  }
  /* 「浏览器空闲」≠「首屏已渲染」：requestIdleCallback 会在 JS 执行完的短暂空闲里
     立即触发，仍与首屏路由/数据争抢连接。改用首次用户交互（必然发生在首屏渲染之后）
     或 4s 兜底，确保 words/cards/pan 的全量翻页请求绝不进入首屏关键路径。 */
  target.addEventListener('pointerdown', run, { passive: true, once: true })
  target.addEventListener('keydown', run, { passive: true, once: true })
  target.addEventListener('scroll', run, { passive: true, once: true })
  signal?.addEventListener('abort', onAbort, { once: true })
  timer = setTimeout(run, 4000)
}

/**
 * 从后端全量拉取各数据域并回填 store。
 * 仅做“后端优先”，任何单域失败不影响其它域；全部失败则保持本地兜底。
 * 重域（words/cards/pan）延迟到首屏后加载，避免拖慢首屏关键路径。
 */
export async function hydrate(signal) {
  if (signal?.aborted) return { online: false, total: 0, ok: 0 }
  const uidAtStart = currentUid()
  const immediateKeys = Object.keys(LOADERS).filter((k) => !DEFERRED_DOMAINS.includes(k))
  const results = await Promise.allSettled(immediateKeys.map((k) => LOADERS[k](signal)))
  const ok = results.filter((r) => r.status === 'fulfilled').length
  /* C5：backendOnline 不再是「任一数据域成功」的独立结论，而是三态的布尔投影。
     三态尚未探测（unknown）时才用本次 hydrate 的成功数临时兜底。
     切号后旧 hydrate 的在线结论也不属于新账号，不回写。 */
  const health = typeof getBackendState === 'function' ? getBackendState() : null
  const derived = typeof isBackendOnline === 'function' ? isBackendOnline(health) : null
  /* 只接受布尔结果：unknown（或测试桩未实现）才回落到本次 hydrate 成功数 */
  const online = typeof derived === 'boolean' ? derived : ok > 0
  if (!inactive(uidAtStart, signal)) useStore.setState({ backendOnline: online })
  if (!signal?.aborted) scheduleDeferredHydrate(uidAtStart, signal)
  return { online, total: results.length, ok }
}
