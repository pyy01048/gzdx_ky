import { describe, it, expect } from 'vitest'
import { normalizeOptions, optionText, imageList } from '../utils/optionText'

describe('optionText / normalizeOptions', () => {
  it('字符串选项保持原样', () => {
    expect(optionText('A. 甲')).toBe('A. 甲')
    expect(normalizeOptions(['A. 甲', 'B. 乙'])).toEqual(['A. 甲', 'B. 乙'])
  })

  it('{key,text} 选项取 text，不出现 [object Object]', () => {
    expect(optionText({ key: 'A', text: '甲' })).toBe('甲')
    expect(normalizeOptions([{ key: 'A', text: '甲' }, { key: 'B', text: '乙' }]))
      .toEqual(['甲', '乙'])
  })

  it('JSON 字符串选项可解析', () => {
    expect(normalizeOptions('[{"key":"A","text":"甲"},{"key":"B","text":"乙"}]'))
      .toEqual(['甲', '乙'])
  })

  it('空值/空字符串被过滤', () => {
    expect(normalizeOptions([null, '', '  ', { key: 'C', text: '' }])).toEqual([])
  })
})

describe('imageList', () => {
  it('字符串与对象都能归一', () => {
    expect(imageList(['/a.png', { url: '/b.png', page: 2 }]))
      .toEqual([{ url: '/a.png' }, { url: '/b.png', page: 2 }])
  })

  it('过滤空值', () => {
    expect(imageList([null, '', { page: 1 }])).toEqual([])
  })
})
