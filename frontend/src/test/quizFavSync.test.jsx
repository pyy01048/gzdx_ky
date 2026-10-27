import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/* ------------------------------------------------------------------ *
 * 题目收藏统一（localStorage ↔ 后端 favorites）
 *
 * 锁住三条最容易出错、且出错代价最大的语义：
 *  1. hydrate 必须是**并集**，不能覆盖 —— 覆盖式写入会把"本地有、后端无"
 *     的历史收藏抹掉，用户感知为"我的收藏凭空消失"；
 *  2. migrate 只推「本地有、后端无」，且不重复推已同步的（幂等）；
 *  3. toggle 后本地态立即生效（UI 即时反馈），后端失败不回滚本地 ——
 *     网络抖动不该打断刷题节奏。
 * ------------------------------------------------------------------ */

const FAV_KEY = 'quiz_favorites_v9'
const SYNCED_KEY = 'quiz_favorites_v9_synced'

let calls = []

function stubFetch(handler) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, opts = {}) => {
      const method = (opts.method || 'GET').toUpperCase()
      calls.push({ url: String(url), method })
      const body = handler(String(url), method) ?? {}
      return { ok: true, status: 200, json: async () => body }
    })
  )
}

/* B4：散键按 uid 隔离后，用例统一跑在 uid=1 命名空间里。
   注意 vi.resetModules() 会重置 userKeys 模块（uid 归零），所以必须在
   resetModules 之后动态导入，让本文件持有与 quizFavSync 同一个实例 ——
   静态 import 拿到的是旧实例，setUser(1) 不会作用到被测模块上。 */
let userKeys
beforeEach(async () => {
  localStorage.clear()
  vi.resetModules()
  userKeys = await import('../utils/userKeys')
  userKeys.setUser(1)
})

afterEach(() => {
  if (userKeys) userKeys.setUser(null)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function load() {
  return import('../api/quizFavSync')
}

describe('hydrateFavs：并集合并，绝不覆盖', () => {
  it('后端有新收藏 → 补进本地缓存', async () => {
    localStorage.setItem(userKeys.ukey(FAV_KEY), JSON.stringify({ 1: { content: '本地题1' } }))
    stubFetch(() => ({
      total: 2,
      items: [
        { id: 10, item_type: 'question', item_id: 1, title: '后端题1', meta: { subject: '数学' } },
        { id: 11, item_type: 'question', item_id: 2, title: '后端题2', meta: { subject: '英语' } },
      ],
    }))
    const m = await load()
    m.__resetFavCache()
    const res = await m.hydrateFavs()

    const favs = m.loadFavs()
    expect(Object.keys(favs).sort()).toEqual(['1', '2'])
    expect(favs['2'].subject).toBe('英语')
    expect(res.serverCount).toBe(2)
  })

  it('本地有、后端无的收藏必须保留（覆盖式写入会抹掉用户数据）', async () => {
    localStorage.setItem(
      userKeys.ukey(FAV_KEY),
      JSON.stringify({ 1: { content: '本地题1' }, 99: { content: '仅本地' } })
    )
    // 后端只有 1 条（id=1），99 尚未同步
    stubFetch(() => ({
      total: 1,
      items: [{ id: 10, item_type: 'question', item_id: 1, title: '后端题1', meta: {} }],
    }))
    const m = await load()
    m.__resetFavCache()
    const res = await m.hydrateFavs()

    const favs = m.loadFavs()
    expect(favs['99']).toBeTruthy()
    expect(favs['99'].content).toBe('仅本地')
    // 99 本地有后端无 → 应被计为待迁移
    expect(res.localOnly).toBeGreaterThanOrEqual(1)
  })

  it('后端不可用时保留本地态（纯离线可用）', async () => {
    localStorage.setItem(userKeys.ukey(FAV_KEY), JSON.stringify({ 7: { content: '离线题' } }))
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down') }))
    const m = await load()
    m.__resetFavCache()
    const res = await m.hydrateFavs()

    expect(res.serverCount).toBe(0)
    expect(m.loadFavs()['7'].content).toBe('离线题')
  })
})

describe('migrateLocalFavs：历史收藏补齐，幂等', () => {
  it('只推「本地有、后端无」，已同步的不重复推', async () => {
    localStorage.setItem(
      userKeys.ukey(FAV_KEY),
      JSON.stringify({ 1: { content: 'A' }, 2: { content: 'B' }, 3: { content: 'C' } })
    )
    // 1、2 已同步过；只有 3 需要迁移
    localStorage.setItem(userKeys.ukey(SYNCED_KEY), JSON.stringify({ 1: 1, 2: 1 }))
    stubFetch(() => ({ ok: true }))

    const m = await load()
    m.__resetFavCache()
    const res = await m.migrateLocalFavs()

    expect(res.total).toBe(1)
    expect(res.migrated).toBe(1)
    const posts = calls.filter((c) => c.method === 'POST' && c.url.includes('/favorites'))
    expect(posts).toHaveLength(1)
  })

  it('推送成功后写入 synced 标记，二次调用不再推（幂等）', async () => {
    localStorage.setItem(userKeys.ukey(FAV_KEY), JSON.stringify({ 5: { content: 'X' } }))
    stubFetch(() => ({ ok: true }))

    const m = await load()
    m.__resetFavCache()
    await m.migrateLocalFavs()
    const first = calls.length
    await m.migrateLocalFavs()

    expect(calls.length).toBe(first) // 第二次无新增请求
    expect(JSON.parse(localStorage.getItem(userKeys.ukey(SYNCED_KEY)))['5']).toBe(1)
  })

  it('推送失败进入 pending，下次重试', async () => {
    localStorage.setItem(userKeys.ukey(FAV_KEY), JSON.stringify({ 8: { content: 'Y' } }))
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down') }))

    const m = await load()
    m.__resetFavCache()
    const r1 = await m.migrateLocalFavs()
    expect(r1.migrated).toBe(0)

    // 网络恢复后重试应成功
    stubFetch(() => ({ ok: true }))
    const r2 = await m.migrateLocalFavs()
    expect(r2.migrated).toBe(1)
  })
})

describe('saveFavs：本地即时生效 + 差集推送', () => {
  it('新增与删除分别推送 add / remove', async () => {
    stubFetch(() => ({ favorited: true }))
    const m = await load()
    m.__resetFavCache()

    m.saveFavs({ 1: { content: 'A' } })          // 新增 1
    await new Promise((r) => setTimeout(r, 0))
    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/favorites'))).toBe(true)

    m.saveFavs({})                                // 删除 1
    await new Promise((r) => setTimeout(r, 0))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true)
  })

  it('未变化的 id 不产生请求（避免每次全量推）', async () => {
    stubFetch(() => ({ ok: true }))
    const m = await load()
    m.__resetFavCache()

    m.saveFavs({ 1: { content: 'A' }, 2: { content: 'B' } })
    await new Promise((r) => setTimeout(r, 0))
    const after1 = calls.length

    m.saveFavs({ 1: { content: 'A' }, 2: { content: 'B' } }) // 内容变了但收藏态没变
    await new Promise((r) => setTimeout(r, 0))
    expect(calls.length).toBe(after1)
  })

  it('本地态立即生效，后端失败也不回滚（网络抖动不打断刷题）', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down') }))
    const m = await load()
    m.__resetFavCache()

    m.saveFavs({ 3: { content: 'C' } })
    // 同步读立刻可见
    expect(m.loadFavs()['3']).toBeTruthy()
    await new Promise((r) => setTimeout(r, 10))
    // 后端挂了，本地仍然是收藏态
    expect(m.loadFavs()['3']).toBeTruthy()
  })
})
