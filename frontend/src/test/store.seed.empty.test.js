import { describe, it, expect } from 'vitest'
import { SEED } from '../mocks/seed'

/* ------------------------------------------------------------------ *
 * 全新用户（库里一条数据都没有）的 store 初始态
 *
 * 已批口径：宁可空也不要假数据。曾经这里预置过假任务/假错题/假网盘文件，
 * 以及「随应用分发的内置词表」20 词 + 2 个词库骨架。词表这一批最隐蔽：
 * 它看起来像产品自带内容，但 Dashboard 用 dueCards(words) 算「待复习单词」，
 * 全新用户一开机就被提示去复习 20 个自己从未背过的词；而且 api/sync.js 没有
 * words 域，这份数据不会被后端空结果覆盖，会永久留着。
 * 内置词表现在只在单词页作为**显式导入**入口存在。
 * ------------------------------------------------------------------ */

const DATA_KEYS = ['tasks', 'notebook', 'pan', 'words', 'decks', 'cards', 'packs']

describe('store 初始态：用户数据域一律为空', () => {
  it.each(DATA_KEYS)('SEED.%s 是空数组', (key) => {
    expect(Array.isArray(SEED[key]), `SEED.${key} 不再是数组`).toBe(true)
    expect(SEED[key], `SEED.${key} 预置了内容，会伪装成真实学习记录`).toHaveLength(0)
  })

  it('SEED.ai.messages 为空', () => {
    expect(SEED.ai.messages).toHaveLength(0)
  })

  it('没有任何数据域被漏出这张表（新增域必须一起断言）', async () => {
    const { default: useStore } = await import('../store/useStore')
    const state = useStore.getState()
    const seededNonEmpty = DATA_KEYS.filter((k) => (state[k] || []).length > 0)
    expect(seededNonEmpty, `这些域在 store 里非空：${seededNonEmpty.join(', ')}`).toEqual([])
  })
})
