import { describe, it, expect } from 'vitest'
import { LETTERS, letterOf, answerIndexes, isCorrectOption } from '../v3/pages/quizShared'

/* 库内存在 7~8 个选项的选择题（答案为 G 的已实测存在）。前端曾只定义 A-F，
   第 7 个选项会被提交成 "7"，后端按字母比对永远判错。 */
describe('选项字母映射', () => {
  it('覆盖到 H，足够覆盖库内 8 选项题', () => {
    expect(LETTERS).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])
    expect(letterOf(0)).toBe('A')
    expect(letterOf(6)).toBe('G')
    expect(letterOf(7)).toBe('H')
  })

  it('8 选项全选提交为连续字母串，而不是混入数字', () => {
    const submitted = [0, 1, 2, 3, 4, 5, 6, 7].map(letterOf).join('')
    expect(submitted).toBe('ABCDEFGH')
  })

  it('答案 G 能解析并命中第 7 个选项', () => {
    expect(answerIndexes('G')?.has('G')).toBe(true)
    expect(isCorrectOption(6, 'G')).toBe(true)
    expect(isCorrectOption(5, 'G')).toBe(false)
  })
})
