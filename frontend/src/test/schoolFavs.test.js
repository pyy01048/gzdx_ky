/**
 * 院校收藏双键统一（P2）：
 * 列表页旧键 ky_fav_school_ids（id 数组）与详情页 kaoyan-fav-schools（map）
 * 统一到后者，读时一次性并集迁移旧键；两页同源、按账号隔离。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { readSchoolFavs, writeSchoolFavs, SCHOOL_FAV_KEY } from '../utils/schoolFavs'
import { setUser, ukey } from '../utils/userKeys'

beforeEach(() => {
  localStorage.clear()
  setUser(null)
})

describe('schoolFavs 双键迁移', () => {
  it('旧 id 数组与新 map 并集合并，旧键随后删除', () => {
    localStorage.setItem('ky_fav_school_ids', JSON.stringify([1, 2]))
    localStorage.setItem('kaoyan-fav-schools', JSON.stringify({ 3: { name: '清华', level: '985' } }))

    const map = readSchoolFavs()
    expect(map).toEqual({ 1: {}, 2: {}, 3: { name: '清华', level: '985' } })
    /* 迁移结果已落盘到新键，旧键删除（一次性） */
    expect(JSON.parse(localStorage.getItem('kaoyan-fav-schools'))).toEqual(map)
    expect(localStorage.getItem('ky_fav_school_ids')).toBeNull()
    /* 再读一次不重复迁移、结果稳定 */
    expect(readSchoolFavs()).toEqual(map)
  })

  it('登录态下旧全局裸键一次性迁给当前账号，其他账号读不到', () => {
    localStorage.setItem('ky_fav_school_ids', JSON.stringify([7]))
    setUser(9)
    const map = readSchoolFavs()
    expect(map).toEqual({ 7: {} })
    expect(localStorage.getItem(ukey(SCHOOL_FAV_KEY))).toContain('7')
    expect(localStorage.getItem('ky_fav_school_ids')).toBeNull()

    /* 切到账号 10：收藏为空，不串号 */
    setUser(10)
    expect(readSchoolFavs()).toEqual({})
  })

  it('旧键里已有的 id 不覆盖新 map 的名称信息', () => {
    localStorage.setItem('ky_fav_school_ids', JSON.stringify([3, 4]))
    localStorage.setItem('kaoyan-fav-schools', JSON.stringify({ 3: { name: '清华' } }))
    const map = readSchoolFavs()
    expect(map[3]).toEqual({ name: '清华' })
    expect(map[4]).toEqual({})
  })

  it('writeSchoolFavs 按当前账号落盘（两页同源的写口）', () => {
    setUser(9)
    writeSchoolFavs({ 5: { name: '贵大' } })
    expect(JSON.parse(localStorage.getItem('kaoyan-fav-schools:9'))).toEqual({ 5: { name: '贵大' } })
    expect(localStorage.getItem('kaoyan-fav-schools')).toBeNull()
    setUser(10)
    expect(readSchoolFavs()).toEqual({})
  })

  it('坏 JSON 不炸：按空收藏处理', () => {
    localStorage.setItem('kaoyan-fav-schools', '{bad json')
    localStorage.setItem('ky_fav_school_ids', 'not json either')
    expect(readSchoolFavs()).toEqual({})
  })
})
