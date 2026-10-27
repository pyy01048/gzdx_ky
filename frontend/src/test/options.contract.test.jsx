import React from 'react'
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { optionText, normalizeOptions } from '../utils/optionText'
import { stripOptLabel, isChoiceQ, isChoiceWithoutOptions, isChoiceLike } from '../v3/pages/quizShared'

/* ------------------------------------------------------------------ *
 * P0-4 · 选项契约回归测试
 *
 * 背景：后端 canonical 形态是**对象数组** [{key,text}]（对齐 services/
 * content_sanitizer 的 DB is_canonical_options），历史数据却是**字符串数组**
 * ["A. 全0"]。前端只要有一处用 String(opt) / {opt} 直接渲染对象，页面上
 * 就会印出 "[object Object]" —— 本题 isotopes 为三种都复现的显示级 bug。
 *
 * 锁定契约：**两种形态必须产出同一份可读文本**，且绝不出现 [object Object]。
 * ------------------------------------------------------------------ */

/* 新形态（后端 canonical）与旧形态（历史字符串数组），语义等价 */
const OBJ_OPTS = [{ key: 'A', text: '全0' }, { key: 'B', text: '全1' }, { key: 'C', text: '互补' }, { key: 'D', text: '无关' }]
const STR_OPTS = ['A. 全0', 'B. 全1', 'C. 互补', 'D. 无关']

describe('optionText —— 单个选项必须总落到可读文本', () => {
  it('对象形态取 text', () => {
    expect(optionText({ key: 'A', text: '全0' })).toBe('全0')
  })

  it('字符串形态原样返回', () => {
    expect(optionText('A. 全0')).toBe('A. 全0')
  })

  it('对象缺 text 时退到 key，绝不吐 [object Object]', () => {
    expect(optionText({ key: 'A' })).toBe('A')
    expect(optionText({})).toBe('')
  })

  it('null / undefined / 数字不炸且不产生 [object Object]', () => {
    expect(optionText(null)).toBe('')
    expect(optionText(undefined)).toBe('')
    expect(optionText(3)).toBe('3')
    expect(optionText({ nope: 1 })).toBe('')
  })
})

describe('normalizeOptions —— 两种形态归一到同一份文本数组', () => {
  it('对象数组 → 文本数组', () => {
    expect(normalizeOptions(OBJ_OPTS)).toEqual(['全0', '全1', '互补', '无关'])
  })

  it('字符串数组 → 文本数组（保留自带的 A. 前缀，去前后空格）', () => {
    expect(normalizeOptions(STR_OPTS)).toEqual(['A. 全0', 'B. 全1', 'C. 互补', 'D. 无关'])
  })

  it('两种形态都不含 [object Object]', () => {
    for (const out of [normalizeOptions(OBJ_OPTS), normalizeOptions(STR_OPTS)]) {
      expect(out.join('|')).not.toContain('[object Object]')
      expect(out.every((s) => typeof s === 'string')).toBe(true)
    }
  })

  it('脏数据（全空数组 / JSON 字符串 / null / 非数组）落到空数组', () => {
    expect(normalizeOptions(['', '  ', null])).toEqual([])
    expect(normalizeOptions('[{"key":"A","text":"全0"}]')).toEqual(['全0'])
    expect(normalizeOptions(null)).toEqual([])
    expect(normalizeOptions(undefined)).toEqual([])
    expect(normalizeOptions({ key: 'A' })).toEqual([])
  })
})

describe('stripOptLabel —— 剥掉自带序号，两种形态都能渲染', () => {
  it('对象形态', () => {
    expect(OBJ_OPTS.map(stripOptLabel)).toEqual(['全0', '全1', '互补', '无关'])
  })

  it('字符串形态（剥掉 "A." / "A、" / "（A）" 等前缀）', () => {
    expect(STR_OPTS.map(stripOptLabel)).toEqual(['全0', '全1', '互补', '无关'])
    expect(stripOptLabel('A、全0')).toBe('全0')
    expect(stripOptLabel('（A）全0')).toBe('全0')
  })

  it('两种形态输出完全一致（这是「统一选项契约」的可观测定义）', () => {
    expect(OBJ_OPTS.map(stripOptLabel)).toEqual(STR_OPTS.map(stripOptLabel))
  })
})

describe('isChoiceQ —— 先归一化再判断', () => {
  const wrap = (options) => ({ id: 1, content: '题面', options, answer: 'A', question_type: 'single' })

  it('对象形态与字符串形态都判「有选项」', () => {
    expect(isChoiceQ(wrap(OBJ_OPTS))).toBe(true)
    expect(isChoiceQ(wrap(STR_OPTS))).toBe(true)
  })

  it('空 / 全空 / 缺失都判「无选项」', () => {
    expect(isChoiceQ(wrap([]))).toBe(false)
    expect(isChoiceQ(wrap(['', '  ', null]))).toBe(false)
    expect(isChoiceQ(wrap(null))).toBe(false)
  })

  it('与 isChoiceWithoutOptions 口径一致，不打架', () => {
    for (const opts of [OBJ_OPTS, STR_OPTS, [], ['', '  '], null]) {
      const q = wrap(opts)
      expect(isChoiceQ(q)).toBe(!isChoiceWithoutOptions(q))
    }
  })

  it('JSON 字符串形态（后端偶发）也能判出有选项', () => {
    expect(isChoiceQ(wrap(JSON.stringify(OBJ_OPTS)))).toBe(true)
  })
})

describe('P0-4 端到端：渲染到 DOM 的文本不得是 [object Object]', () => {
  /* 对照组：不归一化就转字符串渲染——线上坏掉的就是这条路径
     （MathText text={String(o)} / 模板串拼接 ${o}）。注意 React 不接受裸对象
     作 children，所以故障形态是 String 转换后的字面量 "[object Object"]。 */
  it('对照组 —— 直接 String(opt) 会印出 [object Object]', () => {
    const { container } = render(<ul>{OBJ_OPTS.map((o, i) => <li key={i}>{String(o)}</li>)}</ul>)
    expect(container.textContent).toContain('[object Object]')
  })

  /* 实验组：走 stripOptLabel（QuizPractice 的实际渲染路径） */
  it('对象数组 → 正常文本', () => {
    const { container } = render(
      <ul>{normalizeOptions(OBJ_OPTS).map((o, i) => <li key={i}>{stripOptLabel(o)}</li>)}</ul>
    )
    const text = container.textContent
    expect(text).not.toContain('[object Object]')
    expect(text).toBe('全0全1互补无关')
  })

  it('字符串数组 → 正常文本', () => {
    const { container } = render(
      <ul>{normalizeOptions(STR_OPTS).map((o, i) => <li key={i}>{stripOptLabel(o)}</li>)}</ul>
    )
    const text = container.textContent
    expect(text).not.toContain('[object Object]')
    expect(text).toBe('全0全1互补无关')
  })
})

describe('normQ —— 入库对象整体归一化后 options 恒为字符串数组', () => {
  it('对象数组与字符串数组都归一到字符串数组', async () => {
    // 动态 import：normQ 依赖 localStorage 工具，放在函数内取
    const { normQ } = await import('../v3/pages/quizShared')
    const base = { id: 7, content: '题面', answer: 'A', question_type: 'single' }
    const a = normQ({ ...base, options: OBJ_OPTS })
    const b = normQ({ ...base, options: STR_OPTS })
    expect(a.options).toEqual(['全0', '全1', '互补', '无关'])
    expect(b.options).toEqual(['A. 全0', 'B. 全1', 'C. 互补', 'D. 无关'])
    expect(JSON.stringify(a.options)).not.toContain('[object Object]')
    expect(JSON.stringify(b.options)).not.toContain('[object Object]')
  })

  it('答案为纯字母 → 仍判为选择题语义（不受形态影响）', () => {
    expect(isChoiceLike({ question_type: 'single', answer: 'A' })).toBe(true)
  })
})
