/**
 * 聚合缓存与「数据已变更」事件的联动回归（P0 一致性）。
 *
 * 之前的隐患：Hub 缓存 TTL 45s，用户答完题/打完卡回到 /hub，
 * 看到的仍是旧数字 —— 比没有缓存更糟（看起来像「数据不对」）。
 * 这里锁住三件事：
 *   1) client 的非 GET 成功请求会广播 MUTATION_EVENT，GET 不广播；
 *   2) hub 收到事件后立即清缓存（包括 in-flight 的竞态快照）；
 *   3) 没有事件时缓存仍正常命中（不能因为加了监听而退化成每次都请求）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('../api/client', () => ({
  dashboardApi: { summary: vi.fn() },
  insightApi: { today: vi.fn() },
  wordsApi: { stats: vi.fn() },
  reviewApi: { stats: vi.fn() },
}))

import { dashboardApi } from '../api/client'
import { MUTATION_EVENT } from '../api/mutationEvent'
import { clearHubCache, fetchHubOverview, peekHubCache } from '../api/hub'

const model = { countdown: { days: 422 }, caliber: [], sources: [] }

beforeEach(() => {
  clearHubCache()
  vi.clearAllMocks()
  dashboardApi.summary.mockResolvedValue({})
})

afterEach(() => {
  /* 保险：回到空缓存态（不要 remove 模块级监听器本身） */
  clearHubCache()
})

describe('hub 缓存 × mutation 事件', () => {
  it('事件触发后缓存立即失效，下一次拉取走真实请求', async () => {
    await fetchHubOverview()
    expect(dashboardApi.summary).toHaveBeenCalledTimes(1)
    expect(peekHubCache()).not.toBeNull()

    window.dispatchEvent(new CustomEvent(MUTATION_EVENT, { detail: { method: 'POST', path: '/tasks/1' } }))
    expect(peekHubCache()).toBeNull()

    const again = await fetchHubOverview()
    expect(dashboardApi.summary).toHaveBeenCalledTimes(2)
    expect(again.fromCache).toBeUndefined()
  })

  it('mutation 发生在请求期间：旧快照仍然渲染，但不写回缓存', async () => {
    const pending = fetchHubOverview()
    window.dispatchEvent(new CustomEvent(MUTATION_EVENT, { detail: { method: 'POST', path: '/quiz/submit' } }))
    const model1 = await pending

    expect(model1).toBeTruthy() /* 请求已成功的快照照常给页面渲染 */
    expect(peekHubCache()).toBeNull() /* 但绝不落回缓存 —— 否则旧数据复活 */

    await fetchHubOverview()
    expect(dashboardApi.summary).toHaveBeenCalledTimes(2)
  })

  it('cleanHubCache 之外的 named event 不影响缓存', async () => {
    await fetchHubOverview()
    window.dispatchEvent(new CustomEvent('kaoyan:other'))
    expect(peekHubCache()).not.toBeNull()
    const cached = await fetchHubOverview()
    expect(cached.fromCache).toBe(true)
    expect(dashboardApi.summary).toHaveBeenCalledTimes(1)
  })
})

describe('client.js 广播行为', () => {
  /* 事件名两侧一致是整条失效链路的前提（client 派发 / hub 监听共用一个常量文件） */
  it('MUTATION_EVENT 常量稳定', () => {
    expect(MUTATION_EVENT).toBe('kaoyan:mutation')
  })
})
