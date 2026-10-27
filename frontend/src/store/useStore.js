import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { todayStr, uid } from '../utils/date'
import { sm2Schedule, today as spacedToday } from '../utils/spaced'
import { tasksApi, errorsApi, flashcardsApi, studyApi } from '../api/client'
import { SEED } from '../mocks/seed'
import { ukey } from '../utils/userKeys'

/* 后端 id（数字）判断：纯数字字符串才可同步，uid 仅为本地离线占位 */
const isBackendId = (id) => /^\d+$/.test(String(id || ''))

/* 同步状态跟踪 + 失败队列（V3.0 改进：不再静默吞掉错误） */
const syncState = {
  status: 'idle', // idle / syncing / synced / error
  lastError: null,
  failedQueue: [], // 失败的操作队列，恢复网络后可重试
  listeners: [],
  inflight: 0, // 在飞的同步操作数：并发时决定「已同步」能不能报
}

function notifySyncStatus(status, error = null) {
  syncState.status = status
  syncState.lastError = error
  syncState.listeners.forEach((fn) => fn(status, error))
}

/* 改进版同步：本地即时更新 UI，后端异步持久化；失败时记录错误并提示，不静默 */
/* V3.0 修复：接受工厂函数（返回Promise的函数），确保失败队列重试时能重新发起请求 */
function syncTask(promiseOrFn, operationName = 'unknown') {
  notifySyncStatus('syncing')
  syncState.inflight += 1
  // 支持传入Promise或工厂函数；工厂函数确保重试时能重新发起请求
  const getPromise = typeof promiseOrFn === 'function' ? promiseOrFn : () => promiseOrFn
  getPromise()
    .then(() => {
      syncState.inflight -= 1
      // 并发时先返回的那个不能把还在跑、甚至已失败的操作冒充成「已同步」：
      // 只有在飞请求清零、失败队列也为空时才报 synced。
      if (syncState.inflight === 0 && syncState.failedQueue.length === 0) notifySyncStatus('synced')
      // 同步成功后，尝试重试失败队列中的操作
      retryFailedQueue()
    })
    .catch((err) => {
      syncState.inflight -= 1
      console.error(`[sync] ${operationName} 失败:`, err)
      notifySyncStatus('error', err)
      // 加入失败队列，存工厂函数确保重试时能重新发起请求
      syncState.failedQueue.push({ fn: getPromise, operationName, time: Date.now() })
      // 显示用户可感知的提示（通过自定义事件）
      window.dispatchEvent(new CustomEvent('sync-error', { detail: { operationName, error: err } }))
    })
}

/* 重试失败队列中的操作 */
function retryFailedQueue() {
  if (syncState.failedQueue.length === 0) return
  console.log(`[sync] 重试 ${syncState.failedQueue.length} 个失败操作`)
  const queue = [...syncState.failedQueue]
  syncState.failedQueue = []
  queue.forEach(({ fn, operationName }) => {
    // 调用工厂函数获取新的Promise，确保重新发起请求
    syncTask(fn, operationName)
  })
}

/* 订阅同步状态变化 */
function subscribeSyncStatus(fn) {
  syncState.listeners.push(fn)
  return () => {
    syncState.listeners = syncState.listeners.filter((f) => f !== fn)
  }
}

/* V3.0 修复：双ID竞态条件 - uid状态下的操作缓存到adoptId后执行 */
/* 问题：创建操作返回前，用户快速修改/删除，isBackendId(uid)=false导致操作不同步 */
/* 方案：uid状态下的操作加入pendingOps队列，adoptId后按顺序执行 */
const pendingOps = {} // { [uid]: [fn1, fn2, ...] }

function queuePendingOp(localId, fn) {
  if (!pendingOps[localId]) pendingOps[localId] = []
  pendingOps[localId].push(fn)
}

function flushPendingOps(localId, backendId) {
  const ops = pendingOps[localId]
  if (!ops || ops.length === 0) return
  console.log(`[sync] 执行 ${ops.length} 个待处理操作 (${localId} -> ${backendId})`)
  delete pendingOps[localId]
  ops.forEach((fn) => {
    try {
      fn(backendId)
    } catch (e) {
      console.error('[sync] 待处理操作执行失败:', e)
    }
  })
}

/* 同步成功后，将本地 uid 记录替换为后端返回 id，保证后续更新/删除命中同一后端记录 */
function adoptId(listKey, localId, backendId, idKey = 'id') {
  if (backendId == null) return
  const next = useStore.getState()[listKey].map((x) =>
    x[idKey] === localId ? { ...x, [idKey]: String(backendId) } : x
  )
  useStore.setState({ [listKey]: next })
  // V3.0 修复：执行uid状态下缓存的所有待处理操作
  flushPendingOps(localId, String(backendId))
}

/* 批次2-6（P2-3 安全）：从 AI 服务商配置中剔除 apiKey，避免明文密钥持久化到 localStorage。
   只在落盘（partialize）时剔除；内存中仍保留用户本次填写的密钥以正常调用 AI。 */
function stripApiKeys(providers) {
  if (!Array.isArray(providers)) return providers
  return providers.map((p) => {
    if (!p || typeof p !== 'object') return p
    const { apiKey, ...rest } = p
    return rest
  })
}

/* P3（用户数据隔离）：persist 落盘键按登录账号区分。
 * 实际读写键为 `kaoyan-archive-v1:{uid}`（uid 来自 utils/userKeys 的全局状态）；
 * uid 未设置（未登录）时「不读不写、空存储语义」—— getItem 返回 null（zustand
 * 视为无持久化数据），setItem/removeItem 跳过，避免把种子态写到全局键上。
 * 登录/恢复会话后由 AuthContext 调 useStore.persist.rehydrate() 读回该账号的落盘。 */
const userArchiveStorage = {
  getItem: (name) => {
    const key = ukey(name)
    if (key === name) return null // uid 未设置：不读
    try { return localStorage.getItem(key) } catch { return null }
  },
  setItem: (name, value) => {
    const key = ukey(name)
    if (key === name) return     // uid 未设置：不写
    try { localStorage.setItem(key, value) } catch { /* 隐私模式 / 配额满 */ }
  },
  removeItem: (name) => {
    const key = ukey(name)
    if (key === name) return
    try { localStorage.removeItem(key) } catch { /* 同上 */ }
  },
}

const useStore = create(
  persist(
    (set, get) => ({
      /* 后端连通状态（hydrate 后更新） */
      backendOnline: false,

      /* 后端 /dashboard/countdown 原样缓存：全站倒计时的单一日期来源 */
      countdown: null,

      /* ---------- 设置 ---------- */
      settings: SEED.settings,
      updateSettings: (patch) => set((s) => ({ settings: { ...s.settings, ...patch } })),

      /* ---------- 全局展示：当前学科（'' = 全部） ---------- */
      globalSubject: '',
      setGlobalSubject: (subject) => set({ globalSubject: subject || '' }),

      /* ---------- 任务 ---------- */
      tasks: SEED.tasks,
      addTask: (task) => {
        const local = { id: uid(), done: false, createdAt: todayStr(), ...task }
        set((s) => ({ tasks: [local, ...s.tasks] }))
        syncTask(() =>
          tasksApi.create({ title: local.title, subject: local.subject, due_date: local.due, priority: local.priority || 0 })
            .then((r) => adoptId('tasks', local.id, r?.id)),
          '任务新增',
        )
      },
      updateTask: (id, patch) => {
        set((s) => ({ tasks: s.tasks.map((t) => (t.id === id ? { ...t, ...patch } : t)) }))
        const body = {}
        if (patch.title != null) body.title = patch.title
        if (patch.due != null) body.due_date = patch.due
        if (!isBackendId(id)) {
          // V3.0 修复：uid状态下缓存操作，adoptId后执行
          queuePendingOp(id, (backendId) => syncTask(() => tasksApi.update(backendId, body), '任务更新'))
          return
        }
        syncTask(() => tasksApi.update(id, body), '任务更新')
      },
      removeTask: (id) => {
        set((s) => ({ tasks: s.tasks.filter((t) => t.id !== id) }))
        if (!isBackendId(id)) {
          // V3.0 修复：uid状态下缓存操作，adoptId后执行
          queuePendingOp(id, (backendId) => syncTask(() => tasksApi.remove(backendId), '任务删除'))
          return
        }
        syncTask(() => tasksApi.remove(id), '任务删除')
      },
      toggleTask: (id) => {
        set((s) => {
          const done = !(s.tasks.find((t) => t.id === id)?.done)
          if (isBackendId(id)) {
            syncTask(() => (done ? tasksApi.complete(id) : tasksApi.uncomplete(id)), '任务打卡')
          } else {
            // V3.0 修复：uid状态下缓存操作，adoptId后执行
            queuePendingOp(id, (backendId) => syncTask(() => (done ? tasksApi.complete(backendId) : tasksApi.uncomplete(backendId)), '任务打卡'))
          }
          return { tasks: s.tasks.map((t) => (t.id === id ? { ...t, done } : t)) }
        })
      },
      importTasks: (list) => {
        const items = list.map((t) => ({ id: uid(), done: false, createdAt: todayStr(), ...t }))
        set((s) => ({ tasks: [...items, ...s.tasks] }))
        items.forEach((t) =>
          syncTask(() =>
            tasksApi.create({ title: t.title, subject: t.subject, due_date: t.due })
              .then((r) => adoptId('tasks', t.id, r?.id))
          )
        )
      },
      clearDone: () => {
        const done = get().tasks.filter((t) => t.done)
        set((s) => ({ tasks: s.tasks.filter((t) => !t.done) }))
        done.filter((t) => isBackendId(t.id)).forEach((t) => syncTask(() => tasksApi.remove(t.id)))
      },

      /* ---------- 学习时长记录 ----------
         番茄钟已移除；这里保留手动登记学习时长的能力（任务完成时调用），
         数据落到后端 study_sessions，供仪表盘的时长/趋势/打卡统计消费。 */
      logStudySession: (duration, subject, taskType = 'manual') => {
        if (!duration || duration <= 0) return
        // 统一走 client（自带超时与错误处理），此处保持原有"静默失败不阻塞"语义
        studyApi
          .addSession({
            duration: Math.round(duration),
            subject: subject || '',
            task_type: taskType,
            remark: subject || '',
          })
          .catch(() => { /* 后端不可用时静默失败，不阻塞任务操作 */ })
      },

      /* ---------- 错题本 ---------- */
      notebook: SEED.notebook,
      addNote: (n) => {
        const local = { id: uid(), mastery: 0, reviews: [], createdAt: todayStr(), lastReview: null, ...n }
        set((s) => ({ notebook: [local, ...s.notebook] }))
        syncTask(() =>
          errorsApi.create({
            subject: local.subject,
            content: local.question,
            correct_answer: local.answer,
            analysis: local.analysis,
            error_reason: local.reason
          }).then((r) => adoptId('notebook', local.id, r?.id))
        )
      },
      updateNote: (id, patch) => {
        set((s) => ({ notebook: s.notebook.map((n) => (n.id === id ? { ...n, ...patch } : n)) }))
        if (!isBackendId(id)) return
        const body = {}
        if (patch.question != null) body.content = patch.question
        if (patch.answer != null) body.correct_answer = patch.answer
        if (patch.analysis != null) body.analysis = patch.analysis
        if (patch.mastery != null) body.accuracy = patch.mastery / 7
        syncTask(() => errorsApi.update(id, body))
      },
      removeNote: (id) => {
        set((s) => ({ notebook: s.notebook.filter((n) => n.id !== id) }))
        if (!isBackendId(id)) return
        syncTask(() => errorsApi.remove(id))
      },
      reviewNote: (id, correct) => {
        set((s) => ({
          notebook: s.notebook.map((n) => {
            if (n.id !== id) return n
            const mastery = correct ? Math.min(n.mastery + 1, 7) : Math.max(n.mastery - 1, 0)
            return {
              ...n,
              mastery,
              lastReview: todayStr(),
              reviews: [...n.reviews, { date: todayStr(), correct }]
            }
          })
        }))
        if (isBackendId(id)) syncTask(() => errorsApi.update(id, { accuracy: (get().notebook.find((n) => n.id === id)?.mastery || 0) / 7 }))
      },

      /* ---------- 网盘 ---------- */
      pan: SEED.pan,
      addPan: (p) => set((s) => ({ pan: [{ id: uid(), synced: false, date: todayStr(), ...p }, ...s.pan] })),
      removePan: (id) => set((s) => ({ pan: s.pan.filter((p) => p.id !== id) })),
      updatePan: (id, patch) => set((s) => ({ pan: s.pan.map((p) => (p.id === id ? { ...p, ...patch } : p)) })),

      /* ---------- AI 助手 ---------- */
      ai: SEED.ai,
      sendAi: (msg) => set((s) => ({ ai: { ...s.ai, messages: [...s.ai.messages, { role: 'user', content: msg }] } })),
      replyAi: (msg) => set((s) => ({ ai: { ...s.ai, messages: [...s.ai.messages, { role: 'bot', content: msg }] } })),
      setAiPersona: (persona) => set((s) => ({ ai: { ...s.ai, persona } })),
      clearAi: () => set((s) => ({ ai: { ...s.ai, messages: [] } })),

      /* ---------- AI 服务配置（多服务商管理） ---------- */
      addProvider: (p) =>
        set((s) => {
          const id = uid()
          const isFirst = !(s.settings.aiProviders || []).some((x) => x.enabled)
          return {
            settings: {
              ...s.settings,
              aiProviders: [...(s.settings.aiProviders || []), { id, enabled: true, default: isFirst, test: null, vision: false, ...p }]
            }
          }
        }),
      updateProvider: (id, patch) =>
        set((s) => ({
          settings: { ...s.settings, aiProviders: (s.settings.aiProviders || []).map((p) => (p.id === id ? { ...p, ...patch } : p)) }
        })),
      removeProvider: (id) =>
        set((s) => {
          const list = (s.settings.aiProviders || []).filter((p) => p.id !== id)
          // 若删除的是默认/唯一启用项，重新指定默认
          const anyEnabled = list.some((p) => p.enabled)
          const hasDefault = list.some((p) => p.default && p.enabled)
          if (!hasDefault && anyEnabled) {
            const first = list.find((p) => p.enabled)
            if (first) list[list.indexOf(first)] = { ...first, default: true }
          }
          return { settings: { ...s.settings, aiProviders: list } }
        }),
      setDefaultProvider: (id) =>
        set((s) => ({
          settings: {
            ...s.settings,
            aiProviders: (s.settings.aiProviders || []).map((p) => ({ ...p, default: p.id === id }))
          }
        })),
      recordAiUsage: (usage, providerId) =>
        set((s) => ({
          settings: {
            ...s.settings,
            aiUsage: {
              calls: (s.settings.aiUsage?.calls || 0) + 1,
              promptTokens: (s.settings.aiUsage?.promptTokens || 0) + (usage?.prompt_tokens || 0),
              completionTokens: (s.settings.aiUsage?.completionTokens || 0) + (usage?.completion_tokens || 0)
            }
          }
        })),
      recordTest: (providerId, result) =>
        set((s) => ({
          settings: {
            ...s.settings,
            aiProviders: (s.settings.aiProviders || []).map((p) => (p.id === providerId ? { ...p, test: result } : p))
          }
        })),

      /* ---------- 单词本（SM-2 调度） ---------- */
      words: SEED.words,
      decks: SEED.decks,
      addWord: (w) =>
        set((s) => ({
          words: [
            {
              id: uid(), status: 'new', ef: 2.5, interval: 0, reps: 0, lapses: 0,
              due: spacedToday(), lastReview: null, history: [], deck: s.decks[0]?.id || 'core',
              ...w
            },
            ...s.words
          ]
        })),
      importWords: (list) =>
        set((s) => {
          const now = spacedToday()
          const items = list.map((w) => ({
            id: uid(), status: 'new', ef: 2.5, interval: 0, reps: 0, lapses: 0,
            due: now, lastReview: null, history: [], deck: s.decks[0]?.id || 'core', ...w
          }))
          return {
            words: [...items, ...s.words],
            decks: s.decks.map((d) => (d.id === 'core' ? { ...d, count: s.words.length + items.length, source: d.source } : d))
          }
        }),
      reviewWord: (id, grade) =>
        set((s) => ({
          words: s.words.map((w) => {
            if (w.id !== id) return w
            const next = sm2Schedule(w, grade)
            return {
              ...w, ...next,
              history: [...(w.history || []), { date: spacedToday(), grade }]
            }
          })
        })),
      removeWord: (id) => set((s) => ({ words: s.words.filter((w) => w.id !== id) })),
      addDeck: (name) =>
        set((s) => ({ decks: [...s.decks, { id: uid(), name, count: 0, source: '自定义' }] })),
      // 从后端批量设置单词和词库（支持传入数组或 (prev)=>next 更新函数，便于按条刷新）
      setWords: (newWords) => set((s) => ({ words: typeof newWords === 'function' ? newWords(s.words) : newWords })),
      setDecks: (newDecks) => set({ decks: newDecks }),

      /* ---------- 记忆卡片（SM-2） ---------- */
      cards: SEED.cards,
      packs: SEED.packs,
      addCard: (c) => {
        const local = { id: uid(), status: 'new', ef: 2.5, interval: 0, reps: 0, lapses: 0, due: spacedToday(), lastReview: null, ...c }
        set((s) => ({
          cards: [local, ...s.cards],
          packs: s.packs.map((p) => (p.id === c.packId ? { ...p, count: (p.count || 0) + 1 } : p))
        }))
        syncTask(() =>
          flashcardsApi.create({ front: local.front, back: local.back })
            .then((r) => adoptId('cards', local.id, r?.id))
        )
      },
      reviewCard: (id, grade) => {
        set((s) => ({
          cards: s.cards.map((c) => {
            if (c.id !== id) return c
            const next = sm2Schedule(c, grade)
            return { ...c, ...next }
          })
        }))
        if (isBackendId(id)) syncTask(() => flashcardsApi.review(id, { quality: grade }))
      },
      removeCard: (id) => {
        const c = get().cards.find((x) => x.id === id)
        set((s) => ({
          cards: s.cards.filter((x) => x.id !== id),
          packs: c ? s.packs.map((p) => (p.id === c.packId ? { ...p, count: Math.max(0, (p.count || 0) - 1) } : p)) : s.packs
        }))
        if (isBackendId(id)) syncTask(() => flashcardsApi.remove(id)) // 调用后端真正的删除接口
      },
      addPack: (name, subject, color) =>
        set((s) => ({ packs: [...s.packs, { id: uid(), name, subject, color: color ?? 0, count: 0 }] })),
      removePack: (id) =>
        set((s) => ({ packs: s.packs.filter((p) => p.id !== id), cards: s.cards.filter((c) => c.packId !== id) })),
      // 从后端批量回填卡片/卡包（约定同 setWords：支持直接传数组或 (prev)=>next 函数）
      setCards: (newCards) => set((s) => ({ cards: typeof newCards === 'function' ? newCards(s.cards) : newCards })),
      setPacks: (newPacks) => set((s) => ({ packs: typeof newPacks === 'function' ? newPacks(s.packs) : newPacks })),

      /* ---------- 数据管理 ---------- */
      resetAll: () => set({ ...seedState() })
    }),
    {
      name: 'kaoyan-archive-v1',
      /* P3：存储层换成按 uid 的自定义 storage（见上方 userArchiveStorage），
         name 保留为基名，真实键由 userKeys.ukey() 追加 `:{uid}` 后缀。
         批次2-6（P2-3）：persist 加固
         ① version + migrate：后续 store 结构变更时在此迁移老用户数据；当前为 v1，
            结构与无版本老数据一致，migrate 仅原样透传（保留迁移扩展点，不丢数据）。
         ② partialize：不再整体落盘，只挑选需要持久化的键——
            - 安全：剔除 settings.aiProviders[].apiKey，避免明文密钥进 localStorage；
            - 完整保留 ai slice（含批次1 的 localSessions / activeSessionId / messages），
              用户的 AI 会话不被丢弃。 */
      version: 1,
      migrate: (persistedState) => persistedState,
      storage: createJSONStorage(() => userArchiveStorage),
      partialize: (state) => ({
        backendOnline: state.backendOnline,
        settings: { ...state.settings, aiProviders: stripApiKeys(state.settings.aiProviders) },
        globalSubject: state.globalSubject,
        tasks: state.tasks,
        notebook: state.notebook,
        pan: state.pan,
        ai: state.ai,
        words: state.words,
        decks: state.decks,
        cards: state.cards,
        packs: state.packs,
      }),
    }
  )
)

/* reset 时重建初始值：只恢复配置和内置词库，
   用户数据（任务/错题/网盘/卡片）清空后由 api/sync.js 从后端重新回填 */
function seedState() {
  const clone = JSON.parse(JSON.stringify(SEED))
  return {
    settings: clone.settings,
    tasks: [],
    notebook: [],
    pan: [],
    ai: clone.ai,
    words: clone.words,
    decks: clone.decks,
    cards: [],
    packs: clone.packs,
  }
}

export default useStore
