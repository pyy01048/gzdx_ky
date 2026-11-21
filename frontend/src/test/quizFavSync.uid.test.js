/**
 * 收藏待重试队列的 uid 维度（P2）：
 * A 账号推送失败的 qid 不得在切号后被补推进 B 账号的 favorites。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const hoisted = vi.hoisted(() => ({
  add: vi.fn(),
  remove: vi.fn(),
  list: vi.fn(),
}))

vi.mock('../api/client', () => ({
  favoritesApi: { add: hoisted.add, remove: hoisted.remove, list: hoisted.list },
}))

import { pushFav, migrateLocalFavs, __resetFavCache } from '../api/quizFavSync'
import { setUser } from '../utils/userKeys'

const flush = () => new Promise((res) => setTimeout(res, 0))

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  setUser(null)
  __resetFavCache()
})

describe('quizFavSync pending 按账号隔离', () => {
  it('A 的失败 qid 在 B 账号迁移时不会被补推（即使 B 本地恰好也有同一 qid）', async () => {
    setUser(1)
    hoisted.add.mockRejectedValueOnce(new Error('网络抖动'))
    pushFav('101', { content: 'A 收藏的题' })
    await flush() /* 失败进入 A 的 pending */

    /* B 账号本地也有 qid 101，且已同步过（synced 标记在案） */
    setUser(2)
    localStorage.setItem('quiz_favorites_v9:2', JSON.stringify({ 101: { content: 'B 自己的收藏' } }))
    localStorage.setItem('quiz_favorites_v9_synced:2', JSON.stringify({ 101: 1 }))

    hoisted.add.mockClear()
    const r = await migrateLocalFavs()
    /* 旧 bug：pending 不分账号，has('101') 命中 → 把 A 的失败重试混进 B 的迁移 */
    expect(r.total).toBe(0)
    expect(hoisted.add).not.toHaveBeenCalled()
  })

  it('同一账号内失败 qid 仍会被补推（不误伤正常重试）', async () => {
    setUser(1)
    localStorage.setItem('quiz_favorites_v9:1', JSON.stringify({ 101: { content: '题' } }))
    localStorage.setItem('quiz_favorites_v9_synced:1', JSON.stringify({ 101: 1 }))
    hoisted.add.mockRejectedValueOnce(new Error('网络抖动'))
    pushFav('101', { content: '题' })
    await flush()

    hoisted.add.mockClear()
    hoisted.add.mockResolvedValue({ ok: true })
    const r = await migrateLocalFavs()
    expect(r.total).toBe(1)
    expect(r.migrated).toBe(1)
    expect(hoisted.add).toHaveBeenCalledTimes(1)
  })
})
