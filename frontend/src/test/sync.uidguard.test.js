/**
 * hydrate 代际守卫（P0 跨账号串号）：
 * A 账号发起的回填请求还在途时切到 B，响应回来必须整批丢弃 ——
 * 既不写 store，也不回写 backendOnline。全部 mock，不触网。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const hoisted = vi.hoisted(() => ({
  tasksList: vi.fn(),
  errorsList: vi.fn(),
  cardsList: vi.fn(),
  wordsList: vi.fn(),
  panFiles: vi.fn(),
  goalsList: vi.fn(),
  providers: vi.fn(),
  countdown: vi.fn(),
}))

vi.mock('../api/client', () => ({
  tasksApi: { list: hoisted.tasksList },
  errorsApi: { list: hoisted.errorsList },
  flashcardsApi: { list: hoisted.cardsList },
  wordsApi: { list: hoisted.wordsList },
  netdiskApi: { files: hoisted.panFiles, contentUrl: (id) => `/netdisk/${id}` },
  goalsApi: { list: hoisted.goalsList },
  aiApi: { providers: hoisted.providers },
  dashboardApi: { countdown: hoisted.countdown },
  studyApi: { addSession: vi.fn() },
  /* C5：三态桩保持 unknown —— hydrate 尚未探测时用成功数兜底，维持本文件原有语义 */
  getBackendState: () => ({ state: 'unknown', failures: [], checkedAt: 0 }),
  isBackendOnline: () => null,
  /* 分页壳简化：取第一页，按 keys 顺序找数组字段 */
  fetchAllPages: async (fn, { keys, signal }) => {
    const r = await fn({ page: 1, page_size: 200 }, signal)
    for (const k of keys) if (Array.isArray(r?.[k])) return r[k]
    return []
  },
}))

import { hydrate } from '../api/sync'
import useStore from '../store/useStore'
import { setUser } from '../utils/userKeys'

const A_TASK = { id: 11, title: 'A 的任务', status: 'pending', subject: '数学', due_date: '2026-11-20' }

function mockEmptyDomains() {
  hoisted.tasksList.mockResolvedValue({ tasks: [] })
  hoisted.errorsList.mockResolvedValue({ errors: [] })
  hoisted.cardsList.mockResolvedValue({ cards: [] })
  hoisted.wordsList.mockResolvedValue({ items: [] })
  hoisted.panFiles.mockResolvedValue({ local_files: [] })
  hoisted.goalsList.mockResolvedValue([])
  hoisted.providers.mockResolvedValue({ providers: [] })
  hoisted.countdown.mockResolvedValue({})
}

async function hydrateAndCancel() {
  const controller = new AbortController()
  try {
    return await hydrate(controller.signal)
  } finally {
    controller.abort()
  }
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  setUser(null)
  useStore.getState().resetAll()
  mockEmptyDomains()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('hydrate 代际守卫', () => {
  it('请求在途时切号：A 的响应不落进 B 的 store，backendOnline 也不回写', async () => {
    let resolveTasks
    hoisted.tasksList.mockImplementation(() => new Promise((res) => { resolveTasks = res }))
    hoisted.goalsList.mockImplementation(() => new Promise((res) => {
      // goals 也在途，稍后与 tasks 一起返回
      resolveTasks.goals = res
    }))

    setUser(1)
    const p = hydrateAndCancel()
    setUser(2) /* 响应回来之前切号 */

    resolveTasks({ tasks: [A_TASK] })
    resolveTasks.goals([{ university: 'A 的大学', major: 'A 的专业' }])
    const r = await p

    expect(r.ok).toBeGreaterThan(0) /* 请求本身成功，但结果属于旧账号 */
    expect(useStore.getState().tasks).toEqual([])
    expect(useStore.getState().settings.school || '').not.toBe('A 的大学')
    expect(useStore.getState().backendOnline).toBe(false)
  })

  it('uid 未变时正常回填（对照组：守卫不误伤正常路径）', async () => {
    hoisted.tasksList.mockResolvedValue({ tasks: [A_TASK] })
    setUser(2)
    const r = await hydrateAndCancel()
    expect(r.online).toBe(true)
    expect(useStore.getState().tasks.map((t) => t.title)).toEqual(['A 的任务'])
    expect(useStore.getState().backendOnline).toBe(true)
  })

  it('应用壳卸载时取消失屏加载，4 秒兜底不再触发重域请求', async () => {
    vi.useFakeTimers()
    const addListener = vi.spyOn(window, 'addEventListener')
    const removeListener = vi.spyOn(window, 'removeEventListener')
    const controller = new AbortController()

    await hydrate(controller.signal)
    const pointerdownHandler = addListener.mock.calls.find(([type]) => type === 'pointerdown')?.[1]
    expect(pointerdownHandler).toEqual(expect.any(Function))
    expect(hoisted.wordsList).not.toHaveBeenCalled()
    controller.abort()
    await vi.advanceTimersByTimeAsync(4000)

    expect(hoisted.wordsList).not.toHaveBeenCalled()
    expect(hoisted.cardsList).not.toHaveBeenCalled()
    expect(hoisted.panFiles).not.toHaveBeenCalled()
    expect(removeListener).toHaveBeenCalledWith('pointerdown', pointerdownHandler)
    expect(removeListener).toHaveBeenCalledWith('keydown', expect.any(Function))
    expect(removeListener).toHaveBeenCalledWith('scroll', expect.any(Function), true)
    expect(addListener).toHaveBeenCalledWith('pointerdown', pointerdownHandler, { passive: true, once: true })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('首次交互触发后移除兜底定时器并只加载一次重域', async () => {
    vi.useFakeTimers()
    const addListener = vi.spyOn(window, 'addEventListener')
    const removeListener = vi.spyOn(window, 'removeEventListener')
    const controller = new AbortController()
    await hydrate(controller.signal)
    const pointerdownHandler = addListener.mock.calls.find(([type]) => type === 'pointerdown')?.[1]

    window.dispatchEvent(new Event('pointerdown'))
    await vi.advanceTimersByTimeAsync(4000)

    expect(hoisted.wordsList).toHaveBeenCalledTimes(1)
    expect(hoisted.cardsList).toHaveBeenCalledTimes(1)
    expect(hoisted.panFiles).toHaveBeenCalledTimes(1)
    expect(removeListener).toHaveBeenCalledWith('pointerdown', pointerdownHandler)
    expect(removeListener).toHaveBeenCalledWith('scroll', expect.any(Function), true)
    expect(vi.getTimerCount()).toBe(0)
    controller.abort()
  })

  it('全部即时域请求在途时卸载：取消信号且各域迟到响应均不回写', async () => {
    const resolvers = {}
    const signals = {}
    const hold = (key, mock, optionsIndex) => mock.mockImplementation((...args) => {
      signals[key] = args[optionsIndex]?.signal
      return new Promise((resolve) => { resolvers[key] = resolve })
    })
    hold('tasks', hoisted.tasksList, 1)
    hold('notebook', hoisted.errorsList, 1)
    hold('countdown', hoisted.countdown, 0)
    hold('settings', hoisted.goalsList, 0)
    hold('aiProviders', hoisted.providers, 0)

    const localTasks = [{ id: 'local-task', title: '本地任务' }]
    const localNotebook = [{ id: 'local-note', question: '本地错题' }]
    const localCountdown = { exam_date: '2026-12-01' }
    const localSettings = {
      ...useStore.getState().settings,
      school: '本地院校',
      major: '本地专业',
      aiProviders: [{ id: 'local-provider', name: '本地模型' }],
    }
    useStore.setState({
      tasks: localTasks,
      notebook: localNotebook,
      countdown: localCountdown,
      settings: localSettings,
      backendOnline: false,
    })

    const controller = new AbortController()
    const pending = hydrate(controller.signal)
    expect(Object.keys(signals).sort()).toEqual(['aiProviders', 'countdown', 'notebook', 'settings', 'tasks'])

    controller.abort()
    Object.values(signals).forEach((signal) => expect(signal?.aborted).toBe(true))
    resolvers.tasks({ tasks: [A_TASK] })
    resolvers.notebook({ errors: [{ id: 91, content: '迟到错题' }] })
    resolvers.countdown({ exam_date: '2027-01-01' })
    resolvers.settings([{ university: '迟到院校', major: '迟到专业', exam_date: '2027-02-01', total_score_target: 420 }])
    resolvers.aiProviders({ providers: [{ id: 92, name: '迟到模型', provider_type: 'custom' }] })
    await pending

    expect(useStore.getState().tasks).toBe(localTasks)
    expect(useStore.getState().notebook).toBe(localNotebook)
    expect(useStore.getState().countdown).toBe(localCountdown)
    expect(useStore.getState().settings).toBe(localSettings)
    expect(useStore.getState().backendOnline).toBe(false)
  })

  it('重域加载期间保留 abort 监听，全部完成后移除', async () => {
    vi.useFakeTimers()
    let resolveWords
    hoisted.wordsList.mockImplementation(() => new Promise((resolve) => { resolveWords = resolve }))
    const controller = new AbortController()
    const addListener = vi.spyOn(controller.signal, 'addEventListener')
    const removeListener = vi.spyOn(controller.signal, 'removeEventListener')

    await hydrate(controller.signal)
    const abortHandler = addListener.mock.calls.filter(([type]) => type === 'abort').at(-1)?.[1]
    expect(abortHandler).toEqual(expect.any(Function))
    expect(addListener).toHaveBeenCalledWith('abort', abortHandler, { once: true })

    window.dispatchEvent(new Event('pointerdown'))
    await vi.advanceTimersByTimeAsync(0)
    expect(hoisted.wordsList).toHaveBeenCalledTimes(1)
    expect(removeListener).not.toHaveBeenCalledWith('abort', abortHandler)

    resolveWords({ items: [] })
    await vi.advanceTimersByTimeAsync(0)
    expect(hoisted.cardsList).toHaveBeenCalledTimes(1)
    expect(hoisted.panFiles).toHaveBeenCalledTimes(1)
    expect(removeListener).toHaveBeenCalledWith('abort', abortHandler)
    controller.abort()
  })

  it('重域请求在途时卸载：取消请求、阻止回写并停止后续重域', async () => {
    vi.useFakeTimers()
    let resolveWords
    let wordSignal
    hoisted.wordsList.mockImplementation((params, options) => {
      wordSignal = options?.signal
      return new Promise((resolve) => { resolveWords = resolve })
    })
    const controller = new AbortController()
    await hydrate(controller.signal)
    window.dispatchEvent(new Event('pointerdown'))
    await vi.advanceTimersByTimeAsync(0)
    expect(hoisted.wordsList).toHaveBeenCalledTimes(1)

    controller.abort()
    expect(wordSignal?.aborted).toBe(true)
    resolveWords({ items: [{ id: 'late-word' }] })
    await vi.advanceTimersByTimeAsync(0)

    expect(useStore.getState().words).toEqual([])
    expect(hoisted.cardsList).not.toHaveBeenCalled()
    expect(hoisted.panFiles).not.toHaveBeenCalled()
  })
})
