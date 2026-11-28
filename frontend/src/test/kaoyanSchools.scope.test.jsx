import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'

const mocks = vi.hoisted(() => ({
  schools: vi.fn(),
  hot: vi.fn(),
  schoolMajors: vi.fn(),
  dashboardAnalysis: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: null, status: 'ready' }),
}))
vi.mock('../api/client', () => ({ request: vi.fn() }))
vi.mock('../store/useStore', () => ({
  default: (selector) => selector({ countdown: null, settings: { examDate: null } }),
}))
vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: {
    schools: mocks.schools,
    hot: mocks.hot,
    schoolMajors: mocks.schoolMajors,
    dashboardAnalysis: mocks.dashboardAnalysis,
  },
}))

import KaoyanSchools, { invalidateSchoolsCache } from '../v3/pages/KaoyanSchools'

const schoolRow = {
  id: 1,
  name: '口径测试校',
  level: '985',
  province: '广东',
  metric_scope: 'school',
  admit_count: 999,
  retest_count: 1998,
  retest_ratio: 2,
  admit_avg_score: 420,
  major_count: 8,
  direction_count: 20,
}
const majorRow = {
  ...schoolRow,
  metric_scope: 'major',
  subject_code: '0854',
  admit_count: 10,
  retest_count: 20,
  retest_ratio: 2,
  admit_avg_score: 350,
  major_count: 1,
  direction_count: 2,
}

function admitStat(card, label) {
  return within(card).getByText(label).parentElement.querySelector('b').textContent
}

function RouterProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <output data-testid="location">{location.search}</output>
      <button type="button" onClick={() => navigate(-1)}>后退</button>
    </>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  invalidateSchoolsCache()
  localStorage.clear()
  mocks.schools.mockImplementation(async (params) => ({
    total: 1,
    items: [params.subject_code === '0854' ? majorRow : schoolRow],
  }))
  mocks.hot.mockResolvedValue({ items: [] })
  mocks.schoolMajors.mockResolvedValue([{ id: 11, code: '085400', name: '电子信息' }])
  mocks.dashboardAnalysis.mockResolvedValue({})
})

afterEach(cleanup)

describe('KaoyanSchools 专业指标口径', () => {
  it('0854 筛选请求专业口径，展开专业不串全校数据，关闭后恢复全校口径', async () => {
    render(<MemoryRouter><KaoyanSchools /></MemoryRouter>)

    const link = await screen.findByRole('link', { name: '口径测试校' })
    expect(admitStat(link.closest('article'), '拟录取')).toBe('999')
    expect(screen.getByText(/汇总仅纳入明确官方招生来源/)).toBeInTheDocument()
    expect(screen.queryByText(/均为第三方聚合数据/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '0854 电子信息' }))

    const majorLink = await screen.findByRole('link', { name: '口径测试校' })
    const majorCard = majorLink.closest('article')
    await waitFor(() => expect(admitStat(majorCard, '拟录取')).toBe('10'))
    expect(admitStat(majorCard, '进复试')).toBe('20')
    expect(admitStat(majorCard, '录取均分')).toBe('350')
    expect(majorCard.querySelector('a[href="/kaoyan/schools/1?subject_code=0854"]')).toBeTruthy()
    expect(within(majorCard).getByRole('link', { name: '查看详情' })).toHaveAttribute(
      'href', '/kaoyan/schools/1?subject_code=0854',
    )
    expect(mocks.schools).toHaveBeenCalledWith(expect.objectContaining({ subject_code: '0854' }))
    expect(screen.getByText(/0854 专业口径/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '展开数据看板' })).toBeNull()

    fireEvent.click(within(majorCard).getByRole('button', { name: '专业方向' }))
    await waitFor(() => expect(mocks.schoolMajors).toHaveBeenCalledWith(1, { subject_code: '0854' }))

    fireEvent.click(screen.getByRole('button', { name: '0854 电子信息' }))
    const schoolLink = await screen.findByRole('link', { name: '口径测试校' })
    await waitFor(() => expect(admitStat(schoolLink.closest('article'), '拟录取')).toBe('999'))
    expect(screen.getByRole('button', { name: '展开数据看板' })).toBeInTheDocument()
  })

  it('切换范围时先隐藏旧口径，响应完成后才展示', async () => {
    const row = { ...schoolRow, id: 2 }
    let resolveMajor
    let majorCalls = 0
    mocks.schools.mockImplementation((params) => {
      if (params.subject_code === '0854') {
        majorCalls += 1
        if (majorCalls === 1) return Promise.resolve({ total: 1, items: [majorRow] })
        return new Promise((resolve) => { resolveMajor = resolve })
      }
      return Promise.resolve({ total: 1, items: [row] })
    })
    render(<MemoryRouter><KaoyanSchools /></MemoryRouter>)
    await screen.findByRole('link', { name: '口径测试校' })
    invalidateSchoolsCache()

    fireEvent.click(screen.getByRole('button', { name: '0854 电子信息' }))
    expect(screen.queryByText('999')).toBeNull()
    expect(screen.queryByRole('link', { name: '口径测试校' })).toBeNull()

    resolveMajor({ total: 1, items: [majorRow] })
    await waitFor(() => expect(admitStat(screen.getByRole('link', { name: '口径测试校' }).closest('article'), '拟录取')).toBe('10'))
  })

  it('关闭范围时先隐藏专业指标，旧请求晚到不能覆盖新范围', async () => {
    const row = { ...schoolRow, id: 3 }
    let resolveMajor
    let resolveSchool
    let majorCalls = 0
    mocks.schools.mockImplementation((params) => {
      if (params.subject_code === '0854') {
        majorCalls += 1
        if (majorCalls === 1) return Promise.resolve({ total: 1, items: [majorRow] })
        return new Promise((resolve) => { resolveMajor = resolve })
      }
      return new Promise((resolve) => { resolveSchool = resolve })
    })
    render(<MemoryRouter><KaoyanSchools /></MemoryRouter>)
    resolveSchool({ total: 1, items: [row] })
    await screen.findByRole('link', { name: '口径测试校' })
    invalidateSchoolsCache()

    fireEvent.click(screen.getByRole('button', { name: '0854 电子信息' }))
    resolveMajor({ total: 1, items: [majorRow] })
    await screen.findByText('10')

    fireEvent.click(screen.getByRole('button', { name: '0854 电子信息' }))
    expect(screen.queryByText('10')).toBeNull()
    expect(screen.queryByRole('link', { name: '口径测试校' })).toBeNull()
    resolveSchool({ total: 1, items: [schoolRow] })
    await waitFor(() => expect(admitStat(screen.getByRole('link', { name: '口径测试校' }).closest('article'), '拟录取')).toBe('999'))
  })

  it('同一院校展开专业时按范围隔离缓存', async () => {
    const row = { ...schoolRow, id: 4 }
    mocks.schools.mockImplementation(async (params) => ({
      total: 1,
      items: [params.subject_code ? { ...majorRow, id: 4 } : row],
    }))
    mocks.schoolMajors.mockImplementation(async (_id, params) => [{
      id: params.subject_code ? 41 : 40,
      code: params.subject_code ? '085400' : '080900',
      name: params.subject_code ? '0854方向' : '全校方向',
    }])
    render(<MemoryRouter><KaoyanSchools /></MemoryRouter>)
    await screen.findByRole('button', { name: '专业方向' })
    fireEvent.click(screen.getByRole('button', { name: '专业方向' }))
    await screen.findByText('全校方向')

    fireEvent.click(screen.getByRole('button', { name: '0854 电子信息' }))
    await screen.findByText('10')
    fireEvent.click(screen.getByRole('button', { name: '专业方向' }))
    await screen.findByText('0854方向')
    expect(mocks.schoolMajors).toHaveBeenCalledTimes(2)

    fireEvent.click(screen.getByRole('button', { name: '0854 电子信息' }))
    await screen.findByText('999')
    fireEvent.click(screen.getByRole('button', { name: '专业方向' }))
    await screen.findByText('全校方向')
    expect(mocks.schoolMajors).toHaveBeenCalledTimes(2)
  })

  it('从专业详情返回时按 URL 恢复 0854 口径', async () => {
    render(<MemoryRouter initialEntries={['/kaoyan/schools?subject_code=0854']}><KaoyanSchools /></MemoryRouter>)

    expect(await screen.findByText(/0854 专业口径/)).toBeInTheDocument()
    await waitFor(() => expect(admitStat(screen.getByRole('link', { name: '口径测试校' }).closest('article'), '拟录取')).toBe('10'))
    expect(mocks.schools).toHaveBeenCalledWith(expect.objectContaining({ subject_code: '0854' }))
    expect(screen.queryByRole('button', { name: '展开数据看板' })).toBeNull()
  })

  it('筛选与排序写入 URL，清空省份和浏览器后退都能恢复状态', async () => {
    render(
      <MemoryRouter initialEntries={['/kaoyan/schools?province=广东&level=985&sort=avg']}>
        <KaoyanSchools />
        <RouterProbe />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('link', { name: '口径测试校' })).toBeInTheDocument()
    expect(new URLSearchParams(screen.getByTestId('location').textContent).get('province')).toBe('广东')
    const province = screen.getByRole('combobox', { name: '按省份筛选' })
    expect(province).toHaveTextContent('广东')
    expect(screen.getByRole('tab', { name: '录取均分', exact: true })).toHaveAttribute('aria-selected', 'true')

    fireEvent.click(province)
    fireEvent.click(screen.getByRole('option', { name: '全部省份' }))
    await waitFor(() => expect(screen.getByTestId('location').textContent).not.toContain('province='))
    expect(screen.getByTestId('location').textContent).toContain('level=985')
    expect(screen.getByTestId('location').textContent).toContain('sort=avg')

    fireEvent.click(screen.getByRole('button', { name: '后退' }))
    await waitFor(() => expect(screen.getByRole('combobox', { name: '按省份筛选' })).toHaveTextContent('广东'))
  })

  it('数值排序把缺失值固定排末尾，真实零值保留', async () => {
    const rows = [
      { ...schoolRow, id: 51, name: '缺失校', admit_count: null },
      { ...schoolRow, id: 52, name: '零值校', admit_count: 0 },
      { ...schoolRow, id: 53, name: '正值校', admit_count: 5 },
    ]
    mocks.schools.mockResolvedValue({ total: rows.length, items: rows })
    render(<MemoryRouter><KaoyanSchools /></MemoryRouter>)
    await screen.findByRole('link', { name: '缺失校' })
    fireEvent.click(screen.getByRole('tab', { name: '拟录取', exact: true }))

    await waitFor(() => {
      const names = screen.getAllByRole('link').filter((node) => /校$/.test(node.textContent)).map((node) => node.textContent)
      expect(names).toEqual(['正值校', '零值校', '缺失校'])
    })
  })
})
