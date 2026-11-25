import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: { scatter: vi.fn() },
}))

import { kaoyanApi } from '../api/kaoyanApi'
import KaoyanScatter, { formatCount, niceScale } from '../v3/pages/KaoyanScatter'

const SCHOOL = {
  id: 42,
  name: '测试院校',
  level: '985',
  province: '贵州',
  enroll: 1234.6,
  admit_avg: 350,
  retest_ratio: 1.2,
}

function Location() {
  const { pathname } = useLocation()
  return <output data-testid="location">{pathname}</output>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/kaoyan/scatter']}>
      <Location />
      <Routes>
        <Route path="/kaoyan/scatter" element={<KaoyanScatter />} />
        <Route path="/kaoyan/schools/:id" element={<div>院校详情</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  kaoyanApi.scatter.mockResolvedValue({ items: [SCHOOL], year: 2026, available_years: [2026] })
})

afterEach(cleanup)

describe('散点页数值与尺度', () => {
  it('人数按整数四舍五入并添加千分位，缺失值显示 —', () => {
    expect(formatCount(4671.000000000001)).toBe('4,671')
    expect(formatCount(1234.6)).toBe('1,235')
    expect(formatCount(null)).toBe('—')
    expect(formatCount(undefined)).toBe('—')
    expect(formatCount(Infinity)).toBe('—')
  })

  it('niceScale 对零值、极小跨度和单点保持有限且非负', () => {
    for (const [min, max] of [[0, 0], [0, 1e-12], [0, Number.MIN_VALUE * 2], [100, 100]]) {
      const scale = niceScale(min, max, 6, true)
      expect(Number.isFinite(scale.min)).toBe(true)
      expect(Number.isFinite(scale.max)).toBe(true)
      expect(scale.min).toBeGreaterThanOrEqual(0)
      expect(scale.max).toBeGreaterThan(scale.min)
      expect(scale.ticks.length).toBeGreaterThan(1)
      expect(scale.ticks.every((tick) => Number.isFinite(tick) && tick >= 0)).toBe(true)
    }
  })

  it('纵轴单点使用合理窄范围', () => {
    expect(niceScale(350, 350, 5)).toEqual({ min: 340, max: 360, ticks: [340, 345, 350, 355, 360] })
  })
})

describe('散点页统计与明细', () => {
  it('格式化人数，并在图例筛选后同步统计与明细', async () => {
    kaoyanApi.scatter.mockResolvedValue({
      year: 2026,
      available_years: [2026],
      items: [
        { ...SCHOOL, id: 1, name: '甲校', enroll: 4671.000000000001 },
        { ...SCHOOL, id: 2, name: '乙校', level: '211', enroll: 2000.4 },
      ],
    })
    renderPage()

    expect(await screen.findByText('2 所院校 · 专业均值合计 6,671 人 · 气泡大小表示复录比')).toBeInTheDocument()
    expect(screen.getByText('招生规模估算（专业均值合计）').parentElement.querySelector('b')).toHaveTextContent('6,671')
    expect(screen.getByRole('table')).toHaveTextContent('4,671')
    expect(screen.getByRole('table')).toHaveTextContent('2,000')

    fireEvent.click(screen.getByRole('button', { name: /^211/ }))

    expect(await screen.findByText('1 所院校 · 专业均值合计 4,671 人 · 气泡大小表示复录比')).toBeInTheDocument()
    expect(screen.getByText('招生规模估算（专业均值合计）').parentElement.querySelector('b')).toHaveTextContent('4,671')
    expect(screen.getByText('院校数').parentElement.querySelector('b')).toHaveTextContent('1')
    expect(screen.queryByText('乙校')).not.toBeInTheDocument()
  })

  it('只绘制有限正数招生人数', async () => {
    kaoyanApi.scatter.mockResolvedValue({
      year: 2026,
      available_years: [2026],
      items: [
        SCHOOL,
        { ...SCHOOL, name: '零值', enroll: 0 },
        { ...SCHOOL, name: '负值', enroll: -1 },
        { ...SCHOOL, name: '无穷', enroll: Infinity },
        { ...SCHOOL, name: '缺失', enroll: null },
      ],
    })
    const { container } = renderPage()
    await screen.findByRole('button', { name: /测试院校/ })
    expect(container.querySelectorAll('.v3-ky-scatter__point')).toHaveLength(1)
  })
})

describe('散点页院校下钻', () => {
  it.each(['click', 'Enter', ' '])('%s 可进入院校详情', async (action) => {
    renderPage()
    const bubble = await screen.findByRole('button', { name: /测试院校/ })
    if (action === 'click') fireEvent.click(bubble)
    else fireEvent.keyDown(bubble, { key: action })

    expect(await screen.findByText('院校详情')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/kaoyan/schools/42')
  })

  it('没有 id 时不制造链接，悬停提示仍可用', async () => {
    kaoyanApi.scatter.mockResolvedValue({
      year: 2026,
      available_years: [2026],
      items: [{ ...SCHOOL, id: undefined }],
    })
    const { container } = renderPage()
    const bubble = await screen.findByRole('img', { name: /测试院校/ })
    fireEvent.mouseEnter(bubble)
    expect(container.querySelector('.v3-ky-scatter__tip')).toHaveTextContent('专业均值招生')
    expect(container.querySelector('.v3-ky-scatter__tip')).toHaveTextContent('1,235 人')

    fireEvent.click(bubble)
    fireEvent.keyDown(bubble, { key: 'Enter' })
    fireEvent.keyDown(bubble, { key: ' ' })
    expect(screen.getByTestId('location')).toHaveTextContent('/kaoyan/scatter')
  })
})

describe('散点页既有状态', () => {
  it('保留空态', async () => {
    kaoyanApi.scatter.mockResolvedValue({ items: [], year: null, available_years: [] })
    renderPage()
    expect(await screen.findByText('院校库还没有招生数据')).toBeInTheDocument()
  })

  it('保留错误态与重试入口', async () => {
    kaoyanApi.scatter.mockRejectedValue(new Error('测试失败'))
    renderPage()
    expect(await screen.findByRole('heading', { name: '招生分布数据加载失败' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument()
  })
})
