import { describe, it, expect } from 'vitest'
import { kpItems } from '../v3/pages/documentsV3Shared'

/* ============================================================
 * GET /documents/{doc_id}/knowledge-points 的响应形状（裸数组）。
 *
 * 为什么单独锁这个函数：这里曾经读 `r.knowledge_points || r.points`，
 * 两个键后端都不存在（routers/documents.py 的 get_knowledge_points 直接
 * return 一个 list），于是「知识点图谱」永远是空的 —— 页面把这个显示成
 * 「这篇文档没抽取出知识点」，看不出是界面 bug，而接口其实回来了 20 条。
 * 认不出的形状现在抛错，由调用方 catch 弹「获取知识点失败」，
 * 不再用空数组冒充"真的没有"。
 * ============================================================ */
const two = [{ id: 1, name: '极限存在准则' }, { id: 2, name: '中值定理' }]

describe('kpItems：知识点响应形状归一', () => {
  it('裸数组（后端当前形状）原样采用', () => {
    expect(kpItems(two)).toEqual(two)
  })

  it('{items:[…]} 也认，给 #19 统一分页壳留位置', () => {
    expect(kpItems({ items: two, total: 2 })).toEqual(two)
  })

  it('200 无响应体（client.js resolve(null)）→ 空数组，不让 .length 崩', () => {
    expect(kpItems(null)).toEqual([])
    expect(kpItems(undefined)).toEqual([])
  })

  it('真没有（[]）与形状不对（抛错）不再混成同一句话', () => {
    expect(kpItems([])).toHaveLength(0)
    expect(() => kpItems({ knowledge_points: two })).toThrow(/不认识/)
    expect(() => kpItems({ points: two })).toThrow(/不认识/)
    expect(() => kpItems({ chunks: two })).toThrow(/不认识/)
    expect(() => kpItems({})).toThrow(/空对象/)
  })
})
