import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const favoritesApi = vi.hoisted(() => ({
  add: vi.fn(),
  remove: vi.fn(),
  list: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  favoritesApi,
}))

import {
  hydrateFavs,
  loadFavs,
  removeFav,
  __resetFavCache,
} from '../api/quizFavSync'
import { setUser, ukey } from '../utils/userKeys'

const FAV_KEY = 'quiz_favorites_v9'
const SYNCED_KEY = 'quiz_favorites_v9_synced'
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  setUser(1)
  __resetFavCache()
})

afterEach(() => {
  setUser(null)
  localStorage.clear()
})

describe('removeFav 失败保留 synced 标记', () => {
  it.each([
    ['500 服务异常', { status: 500 }],
    ['断网', new Error('network down')],
  ])('%s 不清除 synced', async (_label, error) => {
    localStorage.setItem(ukey(SYNCED_KEY), JSON.stringify({ 7: 1 }))
    favoritesApi.remove.mockRejectedValue(error)

    removeFav('7')
    await flush()

    expect(JSON.parse(localStorage.getItem(ukey(SYNCED_KEY)))['7']).toBe(1)
  })

  it.each([
    ['DELETE 成功', null],
    ['明确 404', { status: 404 }],
  ])('%s 才清除 synced', async (_label, error) => {
    localStorage.setItem(ukey(SYNCED_KEY), JSON.stringify({ 7: 1 }))
    if (error) favoritesApi.remove.mockRejectedValue(error)
    else favoritesApi.remove.mockResolvedValue({ ok: true })

    removeFav('7')
    await flush()

    expect(JSON.parse(localStorage.getItem(ukey(SYNCED_KEY)))['7']).toBeUndefined()
  })

  it('同一 uid 重新登录也使旧 DELETE 响应失效', async () => {
    localStorage.setItem(ukey(SYNCED_KEY), JSON.stringify({ 7: 1 }))
    const request = deferred()
    favoritesApi.remove.mockReturnValue(request.promise)

    removeFav('7')
    setUser(1)
    request.resolve({ ok: true })
    await flush()

    expect(JSON.parse(localStorage.getItem(ukey(SYNCED_KEY)))['7']).toBe(1)
  })
})

describe('hydrateFavs 分页与账号代际', () => {
  it('按 limit/offset 逐页取全量，不止 200 条', async () => {
    const rows = Array.from({ length: 201 }, (_, index) => ({
      item_id: index + 1,
      title: `题目${index + 1}`,
      meta: { subject: '数学' },
    }))
    favoritesApi.list.mockImplementation(({ limit, offset }) => Promise.resolve({
      total: rows.length,
      limit,
      offset,
      items: rows.slice(offset, offset + limit),
    }))

    const result = await hydrateFavs()

    expect(favoritesApi.list).toHaveBeenCalledTimes(2)
    expect(favoritesApi.list).toHaveBeenNthCalledWith(1, { item_type: 'question', limit: 200, offset: 0 })
    expect(favoritesApi.list).toHaveBeenNthCalledWith(2, { item_type: 'question', limit: 200, offset: 200 })
    expect(result.serverCount).toBe(201)
    expect(Object.keys(loadFavs())).toHaveLength(201)
    expect(loadFavs()['201'].content).toBe('题目201')
  })

  it('A 账号未完成的分页响应不得合并进 B 账号收藏', async () => {
    localStorage.setItem(ukey(FAV_KEY), JSON.stringify({ 1: { content: 'A 的收藏' } }))
    const request = deferred()
    favoritesApi.list.mockReturnValue(request.promise)

    const pending = hydrateFavs()
    setUser(2)
    localStorage.setItem(`${FAV_KEY}:2`, JSON.stringify({ 2: { content: 'B 的收藏' } }))
    request.resolve({ total: 1, items: [{ item_id: 99, title: 'A 后端收藏', meta: {} }] })

    expect(await pending).toEqual({ serverCount: 0, localOnly: 0 })
    expect(loadFavs()).toEqual({ 2: { content: 'B 的收藏' } })
  })
})
