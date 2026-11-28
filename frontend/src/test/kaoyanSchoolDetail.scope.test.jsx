import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const mocks = vi.hoisted(() => ({
  schoolDetail: vi.fn(),
  schoolMajors: vi.fn(),
  schoolScores: vi.fn(),
  schoolAdmissions: vi.fn(),
  schoolEnrollmentPlan: vi.fn(),
  schoolNotices: vi.fn(),
  reforms: vi.fn(),
  scoreDetail: vi.fn(),
  schoolAdmissionDetails: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ isAdmin: false }),
}))
vi.mock('../api/kaoyanApi', () => ({ kaoyanApi: mocks }))
vi.mock('../components/EChart', () => ({ default: () => null }))

import KaoyanSchoolDetail from '../v3/pages/KaoyanSchoolDetail'

const school = {
  id: 1,
  name: '专业口径测试校',
  province: '广东',
  metric_scope: 'major',
  subject_code: '0854',
  major_count: 1,
  direction_count: 2,
  admit_count: 10,
  heat: 999,
  coverage_items: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.schoolDetail.mockResolvedValue(school)
  mocks.schoolMajors.mockResolvedValue([
    { id: 11, code: '085400', major_code: '0854', name: '电子信息', subject_code: null },
  ])
  mocks.schoolScores.mockResolvedValue([])
  mocks.schoolAdmissions.mockResolvedValue([])
  mocks.schoolEnrollmentPlan.mockResolvedValue({ items: [] })
  mocks.schoolNotices.mockResolvedValue([])
  mocks.reforms.mockResolvedValue([])
  mocks.scoreDetail.mockResolvedValue(null)
  mocks.schoolAdmissionDetails.mockResolvedValue([])
})

afterEach(cleanup)

function renderDetail(entry) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/kaoyan/schools/:id" element={<KaoyanSchoolDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('KaoyanSchoolDetail 专业范围', () => {
  it('0854 深链将范围传给所有专业数据请求，并隐藏全校热度', async () => {
    renderDetail('/kaoyan/schools/1?subject_code=0854')
    await screen.findByText('专业口径测试校')

    await waitFor(() => {
      expect(mocks.schoolDetail).toHaveBeenCalledWith('1', { subject_code: '0854' })
      expect(mocks.schoolMajors).toHaveBeenCalledWith('1', { subject_code: '0854' })
      expect(mocks.schoolScores).toHaveBeenCalledWith('1', { subject_code: '0854' })
      expect(mocks.schoolAdmissions).toHaveBeenCalledWith('1', { subject_code: '0854' })
      expect(mocks.schoolEnrollmentPlan).toHaveBeenCalledWith('1', { subject_code: '0854' })
      expect(mocks.scoreDetail).toHaveBeenCalledWith('1', { subject_code: '0854' })
    })
    expect(screen.getByText(/0854 专业口径/)).toBeInTheDocument()
    expect(screen.queryByText('热度')).toBeNull()
    expect(screen.getByText('专业')).toBeInTheDocument()
    expect(screen.getByText('方向')).toBeInTheDocument()
    expect(screen.queryByText('专业方向', { exact: true })).toBeNull()
    expect(screen.getAllByRole('link', { name: '返回院校库' })[0]).toHaveAttribute(
      'href', '/kaoyan/schools?subject_code=0854',
    )

    fireEvent.click(screen.getByRole('tab', { name: /^招生数据/ }))
    await waitFor(() => expect(mocks.schoolAdmissionDetails).toHaveBeenCalledWith(
      '1', { limit: 200, subject_code: '0854' },
    ))
  })

  it('招生与逐人明细优先采用后端来源分档，不显示矛盾的聚合口径', async () => {
    mocks.schoolAdmissions.mockResolvedValue([{
      year: 2025,
      major_code: '085400',
      major_name: '电子信息',
      enroll_count: 30,
      retest_count: 40,
      admit_count: 30,
      admit_avg_score: 366.7,
      major_avg_score: null,
      retest_ratio: 1.33,
      data_source: null,
      source_type: 'school_official',
      extra: { enter_min: 340 },
    }])
    mocks.schoolAdmissionDetails.mockResolvedValue([{
      year: 2025, major_name: '电子信息', score_total: 366, source_type: 'school_official',
    }])
    renderDetail('/kaoyan/schools/1?subject_code=0854')
    await screen.findByText('专业口径测试校')
    fireEvent.click(screen.getByRole('tab', { name: /^招生数据/ }))
    await waitFor(() => expect(mocks.schoolAdmissionDetails).toHaveBeenCalled())
    expect(await screen.findByText('官方来源', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(await screen.findByText(/逐人明细来源：官方来源/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByText(/均为第三方聚合口径/)).toBeNull()
    expect(screen.queryByText(/来源于 27 考研择校宝典/)).toBeNull()
  })

  it('0854 徽标只按权威专业代码派生，不使用 subject_code', async () => {
    mocks.schoolDetail.mockResolvedValue({ ...school, metric_scope: 'school', subject_code: null })
    mocks.schoolMajors.mockResolvedValue([
      { id: 12, code: '080900', major_code: '0809', name: '电子科学与技术', subject_code: '0854' },
    ])
    renderDetail('/kaoyan/schools/1')
    await screen.findByText('专业口径测试校')
    await waitFor(() => expect(mocks.schoolMajors).toHaveBeenCalled())
    expect(screen.queryByText('0854 电子信息')).toBeNull()
  })

  it('权威代码为 0854 时即使 subject_code 为空也显示徽标', async () => {
    mocks.schoolDetail.mockResolvedValue({ ...school, metric_scope: 'school', subject_code: null })
    renderDetail('/kaoyan/schools/1')
    expect(await screen.findByText('0854 电子信息')).toBeInTheDocument()
  })

  it('官方分数行按实际来源标注，不再硬编码为掌上考研', async () => {
    mocks.schoolScores.mockResolvedValue([{
      year: 2025,
      major_code: '085400',
      major_name: '电子信息',
      total_line: 350,
      national_line: 300,
      diff_total: 50,
      data_source: 'https://example.edu.cn/admit',
      source_type: 'school_official',
    }])
    renderDetail('/kaoyan/schools/1?subject_code=0854')
    await screen.findByText('专业口径测试校')
    fireEvent.click(screen.getByRole('tab', { name: /^历年分数/ }))

    expect(await screen.findByText(/数据来源：官方来源/)).toBeInTheDocument()
    expect(screen.queryByText(/掌上考研（聚合）/)).toBeNull()
    expect(screen.queryByText(/掌上考研暂未收录/)).toBeNull()
  })

  it('分数接口失败时保留专业与招生成功数据，并显示部分失败提示', async () => {
    mocks.schoolScores.mockRejectedValue(new Error('score unavailable'))
    mocks.schoolAdmissions.mockResolvedValue([{
      year: 2025,
      major_code: '085400',
      major_name: '电子信息',
      admit_count: 10,
      source_type: 'school_official',
    }])
    renderDetail('/kaoyan/schools/1?subject_code=0854')
    await screen.findByText('专业口径测试校')
    expect(await screen.findByText(/部分择校数据加载失败/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: /^招生计划/ }))
    expect((await screen.findAllByText('电子信息')).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('tab', { name: /^招生数据/ }))
    expect(await screen.findByText('官方来源')).toBeInTheDocument()
    expect(mocks.schoolAdmissionDetails).toHaveBeenCalled()
  })

  it('真实零值保留展示，全校口径仍显示热度', async () => {
    mocks.schoolDetail.mockResolvedValue({
      ...school, metric_scope: 'school', subject_code: null, admit_count: 0, direction_count: 0,
    })
    renderDetail('/kaoyan/schools/1')
    await screen.findByText('专业口径测试校')
    const admitStat = screen.getByText('拟录取').parentElement
    const directionStat = screen.getByText('方向').parentElement
    await waitFor(() => expect(admitStat.querySelector('.kyv3-hero-stat__value')).toHaveTextContent('0'))
    expect(directionStat.querySelector('.kyv3-hero-stat__value')).toHaveTextContent('0')
    expect(screen.getByText('热度')).toBeInTheDocument()
    expect(screen.queryByText(/专业口径：统计/)).toBeNull()
  })
})
