import { describe, it, expect } from 'vitest'
import {
  ADMISSION_FIELDS,
  SCORE_FIELDS,
  TRUSTED_TREND_METRICS,
  examSubjects,
  examSubjectNames,
  examSubjectText,
  resolveSourceType,
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
    expect(examSubjects(raw)).toEqual(raw)
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

  it('JSON 字符串按对象数组解析，label 兼容且保留对象 code', () => {
    const raw = JSON.stringify([
      { code: '857', name: '电子技术基础' },
      { label: '信号与系统' },
    ])
    expect(examSubjects(raw)).toEqual([
      { code: '857', name: '电子技术基础' },
      { code: null, name: '信号与系统' },
    ])
    expect(examSubjects(JSON.stringify({ code: '301', label: '数学（一）' }))).toEqual([
      { code: '301', name: '数学（一）' },
    ])
  })

  it('对象自身 code 优先于名称中的行内编号', () => {
    expect(examSubjects([{ code: '857', name: '(999)电子技术基础' }])).toEqual([
      { code: '857', name: '电子技术基础' },
    ])
    expect(examSubjects([{ name: '(302)数学（二）' }])).toEqual([
      { code: '302', name: '数学（二）' },
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

describe('择校字段语义', () => {
  it('来源分档识别官方名单，并优先采信后端分档', () => {
    expect(resolveSourceType('notice:school:2025:list')).toBe('官方')
    expect(resolveSourceType('txkyer_2027:school.edu.cn')).toBe('聚合')
    expect(resolveSourceType('notice:school:2025:list', '聚合')).toBe('聚合')
    expect(resolveSourceType('school_official', '官方')).toBe('官方')
  })

  it('分数线列名与数据库模型定义一致', () => {
    expect(SCORE_FIELDS.map((field) => [field.key, field.label])).toEqual([
      ['total_line', '总分'],
      ['politics_line', '政治'],
      ['english_line', '外语'],
      ['math_line', '数学'],
      ['major_line', '专业课'],
    ])
  })

  it('招生列名使用拟招生、进复试、拟录取和专业课均分', () => {
    expect(ADMISSION_FIELDS.map((field) => [field.key, field.label])).toEqual([
      ['enroll_count', '拟招生人数'],
      ['retest_count', '进复试人数'],
      ['admit_avg_score', '录取均分'],
      ['major_avg_score', '专业课均分'],
      ['retest_ratio', '复录比'],
    ])
  })

  it('趋势指标不复用旧的错误口径', () => {
    expect(TRUSTED_TREND_METRICS.map((metric) => [metric.value, metric.label])).toEqual([
      ['total_line', '总分线'],
      ['major_avg_score', '专业课均分'],
      ['admit_avg_score', '录取均分'],
      ['enroll_count', '拟招生人数'],
      ['retest_count', '进复试人数'],
      ['retest_ratio', '复录比'],
    ])
  })
})
