import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 考研规划页的届数来源（#20 去硬编码）
 *
 * 这里曾写死 useState(2027) + [2026,2027,2028]：后端刚把「届数」收口成
 * 单一权威出口（Goal → default_exam_year），前端却又把年份钉死，
 * 于是用户改了届页面仍停在旧年份。现在候选与当前届一律由接口下发。
 * ------------------------------------------------------------------ */
const roadmapMock = {
  year: 2028,
  exam_date: '2027-12-25',
  exam_date_is_official: false,
  days_to_exam: 400,
  available_years: [2028, 2027],
  goal: {},
  stages: [],
}
const milestonesMock = { milestones: [] }

const kaoyanApi = {
  roadmap: vi.fn().mockResolvedValue(roadmapMock),
  milestones: vi.fn().mockResolvedValue(milestonesMock),
  generatePlan: vi.fn().mockResolvedValue({ year: 2028, total: 18 }),
}

vi.mock('../api/kaoyanApi', () => ({ kaoyanApi }))

describe('PlanPage 届数由接口下发', () => {
  beforeEach(() => {
    cleanup()
    vi.clearAllMocks()
    kaoyanApi.roadmap.mockResolvedValue(roadmapMock)
    kaoyanApi.milestones.mockResolvedValue(milestonesMock)
  })

  it('下拉候选取 available_years，不再写死 2026/2027/2028', async () => {
    const PlanPage = (await import('../v3/pages/PlanPage')).default
    render(<MemoryRouter><PlanPage /></MemoryRouter>)

    const select = await screen.findByRole('combobox', { name: '选择届数' })
    const options = [...select.querySelectorAll('option')].map((o) => o.textContent)
    expect(options).toEqual(['2028 考研', '2027 考研'])
    expect(options.some((t) => t.includes('2026'))).toBe(false)
  })

  it('首屏不传年份，让后端按 Goal 配置的届推导', async () => {
    const PlanPage = (await import('../v3/pages/PlanPage')).default
    render(<MemoryRouter><PlanPage /></MemoryRouter>)
    await screen.findByRole('combobox', { name: '选择届数' })

    // null 会被 client.js 的 params 序列化丢掉 → 请求里不带 year，由后端推导
    expect(kaoyanApi.roadmap).toHaveBeenLastCalledWith(null)
    expect(kaoyanApi.milestones).toHaveBeenLastCalledWith(null)
  })

  it('切换届数后带着所选年份重新请求', async () => {
    const PlanPage = (await import('../v3/pages/PlanPage')).default
    render(<MemoryRouter><PlanPage /></MemoryRouter>)
    const select = await screen.findByRole('combobox', { name: '选择届数' })

    await act(async () => { fireEvent.change(select, { target: { value: '2027' } }) })
    expect(kaoyanApi.roadmap).toHaveBeenLastCalledWith(2027)
  })

  it('未公布的届标「预估」，不把推导值当官方日期', async () => {
    const PlanPage = (await import('../v3/pages/PlanPage')).default
    render(<MemoryRouter><PlanPage /></MemoryRouter>)

    expect(await screen.findByText('（预估）')).toBeInTheDocument()

    vi.resetModules()
    cleanup()
    kaoyanApi.roadmap.mockResolvedValue({ ...roadmapMock, exam_date_is_official: true })
    const Fresh = (await import('../v3/pages/PlanPage')).default
    render(<MemoryRouter><Fresh /></MemoryRouter>)
    await screen.findByRole('combobox', { name: '选择届数' })
    expect(screen.queryByText('（预估）')).not.toBeInTheDocument()
  })
})
