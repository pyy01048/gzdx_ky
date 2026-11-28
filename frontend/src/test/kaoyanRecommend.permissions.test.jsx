import React from 'react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

let currentRole = 'user'
const users = {
  user: { id: 1, username: 'learner', role: 'user' },
  admin: { id: 2, username: 'admin', role: 'admin' },
}
const api = vi.hoisted(() => ({
  majorCoverage: vi.fn(),
  dataYears: vi.fn(),
  recommend: vi.fn(),
  autoAdjust: vi.fn(),
  setGoal: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: users[currentRole], isAdmin: currentRole === 'admin' }),
}))
vi.mock('../api/client', () => ({
  qualityApi: { majorCoverage: api.majorCoverage },
}))
vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: {
    dataYears: api.dataYears,
    recommend: api.recommend,
    autoAdjust: api.autoAdjust,
    setGoal: api.setGoal,
  },
}))

import KaoyanRecommend from '../v3/pages/KaoyanRecommend'

function renderPage() {
  return render(<MemoryRouter><KaoyanRecommend /></MemoryRouter>)
}

beforeEach(() => {
  currentRole = 'user'
  vi.clearAllMocks()
  api.majorCoverage.mockResolvedValue(null)
  api.dataYears.mockResolvedValue({ items: [2025] })
  api.recommend.mockResolvedValue({ recommendations: [], algorithm: '' })
  api.autoAdjust.mockResolvedValue({ coverage: 0, buckets: {} })
  api.setGoal.mockResolvedValue({})
})

afterEach(cleanup)

describe('KaoyanRecommend：自动调整权限与手动设置', () => {
  it('普通用户看不到自动调整入口，仍可提交手动条件并设置目标', async () => {
    api.recommend.mockResolvedValue({
      algorithm: '手动权重',
      recommendations: [{ school_id: 1, name: '目标院校', gap: 12, safety: '稳妥', score: 80 }],
    })
    renderPage()
    await screen.findByRole('combobox', { name: '参考年份' })

    expect(screen.queryByRole('heading', { name: '快速一键自动调整' })).toBeNull()
    expect(screen.queryByRole('button', { name: /自动调整/ })).toBeNull()
    expect(api.majorCoverage).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('预估总分'), { target: { value: '350' } })
    fireEvent.change(screen.getByLabelText('目标录取均分'), { target: { value: '365' } })
    fireEvent.change(screen.getByLabelText('最大复录比'), { target: { value: '1.2' } })
    fireEvent.click(screen.getByRole('button', { name: '开始推荐' }))

    await screen.findByRole('link', { name: '目标院校' })
    expect(api.recommend).toHaveBeenCalledWith(expect.objectContaining({
      score: 350,
      target_avg_score: '365',
      max_retest_ratio: '1.2',
      year: 2025,
    }))

    fireEvent.click(screen.getByRole('button', { name: '设为目标院校' }))
    await waitFor(() => expect(api.setGoal).toHaveBeenCalledWith(1, 350))
  })

  it('编辑表单后旧推荐仍冻结原分数与详情参数', async () => {
    api.recommend.mockResolvedValue({
      recommendations: [{ school_id: 1, name: '目标院校', gap: 12, safety: '稳妥', score: 80 }],
    })
    renderPage()
    await screen.findByRole('combobox', { name: '参考年份' })
    fireEvent.change(screen.getByLabelText('预估总分'), { target: { value: '350' } })
    fireEvent.click(screen.getByRole('button', { name: '开始推荐' }))
    const detail = await screen.findByRole('link', { name: /查看推荐依据/ })
    expect(new URL(detail.getAttribute('href'), 'https://local.test').searchParams.get('score')).toBe('350')

    fireEvent.change(screen.getByLabelText('预估总分'), { target: { value: '370' } })
    expect(detail.getAttribute('href')).toContain('score=350')
    expect(detail.getAttribute('href')).not.toContain('score=370')
    fireEvent.click(screen.getByRole('button', { name: '设为目标院校' }))
    await waitFor(() => expect(api.setGoal).toHaveBeenCalledWith(1, 350))
  })

  it('管理员保留自动调整入口并可调用', async () => {
    currentRole = 'admin'
    renderPage()
    await screen.findByRole('combobox', { name: '参考年份' })

    expect(screen.getByRole('heading', { name: '快速一键自动调整' })).toBeInTheDocument()
    expect(api.majorCoverage).toHaveBeenCalledOnce()
    fireEvent.change(screen.getByLabelText('预估总分'), { target: { value: '380' } })
    fireEvent.click(screen.getByRole('button', { name: '按 380 分自动调整' }))

    await waitFor(() => expect(api.autoAdjust).toHaveBeenCalledWith({
      user_score: 380,
      subject_code: undefined,
      province: undefined,
      level: undefined,
    }))
  })
  it('管理员自动调整展示分数位置与证据完整度，不误称录取信心', async () => {
    currentRole = 'admin'
    api.autoAdjust.mockResolvedValue({
      coverage: 1,
      year_window: [2024, 2025],
      method: '分数位置为正态经验估算，非录取概率',
      buckets: {
        safe: [{
          school_id: 1,
          school_name: '目标院校',
          avg3: 350,
          gap: 30,
          score_position: 0.8,
          position: '高于历年录取均分',
          evidence_confidence: 0.67,
          evidence_label: '一般',
          years_used: 2,
          reasons: ['近2个数据年度录取均分 350'],
        }],
      },
    })
    renderPage()
    await screen.findByRole('combobox', { name: '参考年份' })
    fireEvent.change(screen.getByLabelText('预估总分'), { target: { value: '380' } })
    fireEvent.click(screen.getByRole('button', { name: '按 380 分自动调整' }))

    expect(await screen.findByText('分数位置 80%')).toBeInTheDocument()
    expect(screen.getByText('证据完整度 67%')).toBeInTheDocument()
    expect(screen.queryByText(/信心 \d+%/)).toBeNull()
  })
})

describe('KaoyanRecommend：分差格式化', () => {
  it('正数、负数、零与缺失值均不产生 +-N', async () => {
    const gaps = [
      { school_id: 1, name: '正分差院校', gap: 12 },
      { school_id: 2, name: '负分差院校', gap: -12 },
      { school_id: 3, name: '零分差院校', gap: 0 },
      { school_id: 4, name: '缺失分差院校', gap: null },
    ]
    api.recommend.mockResolvedValue({
      recommendations: gaps.map((item) => ({ ...item, safety: '稳妥', score: 80 })),
    })
    renderPage()
    await screen.findByRole('combobox', { name: '参考年份' })
    fireEvent.change(screen.getByLabelText('预估总分'), { target: { value: '350' } })
    fireEvent.click(screen.getByRole('button', { name: '开始推荐' }))
    await screen.findByRole('link', { name: '正分差院校' })

    const readGap = (name) => within(screen.getByRole('link', { name }).closest('article'))
      .getByText('分差').parentElement.querySelector('b').textContent
    expect(readGap('正分差院校')).toBe('+12')
    expect(readGap('负分差院校')).toBe('-12')
    expect(readGap('零分差院校')).toBe('±0')
    expect(readGap('缺失分差院校')).toBe('—')
    expect(document.body.textContent).not.toContain('+-12')
  })
})
