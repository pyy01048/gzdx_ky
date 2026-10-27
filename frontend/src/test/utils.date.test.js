import { describe, expect, it } from 'vitest'
import { fmtDateTime, humanDate } from '../utils/date'

/**
 * 时间展示的口径守卫。
 *
 * 后端把时间列统一存成 naive UTC，出参由 `UtcZJSONResponse` 补 `Z`
 * （backend-main-fastapi/utils/response.py）。前端必须 `new Date()` 解析后按本地
 * 时区渲染——历史上这里是 `String(x).slice(0, 16)`，等于把 UTC 墙钟当北京时间显示。
 */
describe('fmtDateTime', () => {
  it('空值与非法值一律返回空串（由调用点显示「—」，不猜时间）', () => {
    expect(fmtDateTime('')).toBe('')
    expect(fmtDateTime(null)).toBe('')
    expect(fmtDateTime(undefined)).toBe('')
    expect(fmtDateTime('不是时间')).toBe('')
  })

  it('带 Z 的 UTC 串按本地时区渲染，不再直接截字符串', () => {
    const iso = '2026-10-16T16:30:00Z'
    const d = new Date(iso)
    const p = (n) => String(n).padStart(2, '0')
    expect(fmtDateTime(iso)).toBe(
      `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`,
    )
    // 只有非 UTC 时区（本机/北京 +08:00）才能区分「按本地渲染」与「截原始串」
    if (new Date().getTimezoneOffset() !== 0) {
      expect(fmtDateTime(iso)).not.toBe('2026-10-16 16:30')
    }
  })

  it('输出宽度固定 16，表格列不会因缺位而抖动', () => {
    expect(fmtDateTime('2026-10-16T16:30:00Z')).toHaveLength(16)
  })
})

describe('humanDate（全站唯一实现，NoticeBoard 与 NoticeCenter 共用）', () => {
  const shift = (days) => {
    const d = new Date()
    d.setHours(12, 0, 0, 0)
    d.setDate(d.getDate() + days)
    const p = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  }

  it('今天 / 昨天 / N 天前 / 未来各归其位', () => {
    expect(humanDate(shift(0))).toBe('今天')
    expect(humanDate(shift(-1))).toBe('昨天')
    expect(humanDate(shift(-6))).toBe('6 天前')
    expect(humanDate(shift(3))).toBe('即将')
  })

  it('30 天以上退回具体日期，缺失与非日期串不渲染成 NaN', () => {
    expect(humanDate(shift(-40))).toBe(shift(-40))
    expect(humanDate('')).toBe('')
    expect(humanDate(null)).toBe('')
    expect(humanDate('abc')).toBe('abc')
  })
})
