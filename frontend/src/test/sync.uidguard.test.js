/**
 * hydrate 代际守卫（P0 跨账号串号）：
 * A 账号发起的回填请求还在途时切到 B，响应回来必须整批丢弃 ——
 * 既不写 store，也不回写 backendOnline。全部 mock，不触网。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

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
  fetchAllPages: async (fn, { keys }) => {
    const r = await fn({ page: 1, page_size: 200 })
    for (const k of keys) if (Array.isArray(r?.[k])) return r[k]
    return []
  },
}))

import { hydrate } from '../api/sync'
import useStore from '../store/useStore'
import { setUser } from '../utils/userKeys'

const A_TASK = { id: 11, title: 'A 的任务', status: 'pending', subject: '数学', due_date: '2026-11-20' }

function mockEmptyDomains() {
  hoisted.errorsList.mockResolvedValue({ errors: [] })
  hoisted.cardsList.mockResolvedValue({ cards: [] })
  hoisted.wordsList.mockResolvedValue({ items: [] })
  hoisted.panFiles.mockResolvedValue({ local_files: [] })
  hoisted.goalsList.mockResolvedValue([])
  hoisted.providers.mockResolvedValue({ providers: [] })
  hoisted.countdown.mockResolvedValue({})
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  setUser(null)
  useStore.getState().resetAll()
  mockEmptyDomains()
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
    const p = hydrate()
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
    const r = await hydrate()
    expect(r.online).toBe(true)
    expect(useStore.getState().tasks.map((t) => t.title)).toEqual(['A 的任务'])
    expect(useStore.getState().backendOnline).toBe(true)
  })
})
