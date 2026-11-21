/**
 * 访客（anon）持久化命名空间（P2）：
 * uid 未设置时归档落 `kaoyan-archive-v1:anon`，不再写全局裸键；
 * 登录 rehydrate 读的是 `:{uid}` 键，anon 数据不会混入任何账号命名空间。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

beforeEach(() => {
  localStorage.clear()
})

async function freshStore(uidVal) {
  vi.resetModules()
  const { setUser } = await import('../utils/userKeys')
  setUser(uidVal)
  const mod = await import('../store/useStore')
  return { store: mod.default, setUser }
}

describe('anon 持久化隔离', () => {
  it('未登录时写 :anon 独立键，不写全局裸键', async () => {
    const { store } = await freshStore(null)
    store.setState({ globalSubject: 'anon-subject' })
    expect(localStorage.getItem('kaoyan-archive-v1:anon')).toContain('anon-subject')
    expect(localStorage.getItem('kaoyan-archive-v1')).toBeNull()
  })

  it('登录 rehydrate 读 uid 键；anon 数据不混入 uid 命名空间', async () => {
    /* 账号 5 已有自己的归档 */
    localStorage.setItem('kaoyan-archive-v1:5', JSON.stringify({
      state: { globalSubject: 'five-subject' }, version: 1,
    }))
    const { store, setUser } = await freshStore(null)
    store.setState({ globalSubject: 'anon-subject' })
    expect(localStorage.getItem('kaoyan-archive-v1:anon')).toContain('anon-subject')

    setUser(5)
    await store.persist.rehydrate()
    expect(store.getState().globalSubject).toBe('five-subject')
    /* anon 归档原样保留，uid 归档没有被 anon 数据污染 */
    expect(localStorage.getItem('kaoyan-archive-v1:anon')).toContain('anon-subject')
    expect(localStorage.getItem('kaoyan-archive-v1:5')).not.toContain('anon-subject')
  })

  it('登出回访客态后，新的写入落 :anon，不覆盖刚才账号的归档', async () => {
    const { store, setUser } = await freshStore(5)
    store.setState({ globalSubject: 'five-subject' })
    expect(localStorage.getItem('kaoyan-archive-v1:5')).toContain('five-subject')

    setUser(null)
    store.setState({ globalSubject: 'guest-again' })
    expect(localStorage.getItem('kaoyan-archive-v1:anon')).toContain('guest-again')
    expect(localStorage.getItem('kaoyan-archive-v1:5')).toContain('five-subject')
    expect(localStorage.getItem('kaoyan-archive-v1:5')).not.toContain('guest-again')
  })
})
