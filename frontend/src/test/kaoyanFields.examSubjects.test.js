import { describe, it, expect } from 'vitest'
import {
  examSubjects,
  examSubjectNames,
  examSubjectText,
} from '../utils/kaoyanFields'

/**
 * V8.0 P0-2：「院校招生计划初试科目」渲染事故回归。
 *
 * 事故两种形态：
 *   1) 来源是结构化数组 [{code, name}]，前端直接 {item} 渲染 → 输出 "[object Object]"
 *   2) 来源是库内竖线文本 "(302)数学（二） | (204)英语（二）"，前端不拆分
 *      → 整串挤成一个巨大徽标
 */
describe('examSubjects 归一化', () => {
  it('库内竖线文本 → 结构化数组（方案1：拆成多个科目）', () => {
    const raw = '(302)数学（二） | (204)英语（二） | (857)电子技术基础'
    expect(examSubjects(raw)).toEqual([
      { code: '302', name: '数学（二）' },
      { code: '204', name: '英语（二）' },
      { code: '857', name: '电子技术基础' },
    ])
  })

  it('结构化数组不再渲染出 [object Object]', () => {
    const raw = [
      { code: '301', name: '数学（一）' },
      { code: null, name: '专业综合' },
    ]
    expect(examSubjectNames(raw)).toEqual(['数学（一）', '专业综合'])
    expect(examSubjectText(raw)).toBe('数学（一） · 专业综合')
  })

  it('混合形态（对象里带竖线）也能拆开', () => {
    const raw = [{ code: null, name: '数学 | 英语' }]
    expect(examSubjectNames(raw)).toEqual(['数学', '英语'])
  })

  it('兼容中文分号与换行分隔', () => {
    expect(examSubjectNames('数学；英语\n政治')).toEqual(['数学', '英语', '政治'])
  })

  it('全角/半角括号编号均被剥离', () => {
    expect(examSubjects('（101）思想政治理论')).toEqual([
      { code: '101', name: '思想政治理论' },
    ])
    expect(examSubjects('201英语（一）')).toEqual([
      { code: '201', name: '英语（一）' },
    ])
  })

  it('空值 / 空串 / 重复项处理', () => {
    expect(examSubjects(null)).toEqual([])
    expect(examSubjects('')).toEqual([])
    expect(examSubjects('  |  |  ')).toEqual([])
    expect(examSubjects('数学 | 数学')).toEqual([{ code: null, name: '数学' }])
  })

  it('纯字符串数组（旧契约）仍可用', () => {
    expect(examSubjectNames(['数学', '英语'])).toEqual(['数学', '英语'])
  })

  it('真实库形态：ORM 返回的竖线文本（后端 JSON 列反序列化后的值）', () => {
    // GET /api/kaoyan/schools/3/majors 实测返回
    const raw = '(301)数学（一） | (201)英语（一） | (857)电子技术基础（含数字与模拟电路）'
    expect(examSubjects(raw)).toEqual([
      { code: '301', name: '数学（一）' },
      { code: '201', name: '英语（一）' },
      { code: '857', name: '电子技术基础（含数字与模拟电路）' },
    ])
  })

  it('过滤占位值（后端数据缺失时会给出 "-"）', () => {
    // GET /api/kaoyan/schools/3/enrollment-plan 实测含 [{code: null, name: '-'}]
    expect(examSubjects([{ code: null, name: '-' }])).toEqual([])
    expect(examSubjectNames('无 | 数学')).toEqual(['数学'])
  })
})
