import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'

const mocks = vi.hoisted(() => ({
  schools: vi.fn(),
  compare: vi.fn(),
  radarOptions: [],
}))

vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: { schools: mocks.schools, compare: mocks.compare },
}))

vi.mock('../components/EChart', () => ({
  default: ({ option }) => {
    mocks.radarOptions.push(option)
    return <div data-testid="radar-chart" />
  },
}))

vi.mock('../v3/ui', async (importOriginal) => ({
  ...await importOriginal(),
  AnimatedNumber: ({ value, format = (number) => number }) => <span>{format(value)}</span>,
}))

import KaoyanCompare from '../v3/pages/KaoyanCompare'

const compareResult = {
  items: [
    {
      id: 1,
      name: '甲校',
      level: '985',
      province: '北京',
      recent_scores: [
        { year: 2025, total_line: 501 },
        { year: 2024, total_line: 401 },
        { year: 2023, total_line: 390 },
      ],
      recent_admissions: [{ year: 2024, enroll_count: 601, admit_avg_score: 431 }],
    },
    {
      id: 2,
      name: '乙校',
      level: '211',
      province: '上海',
      recent_scores: [
        { year: 2025, total_line: null },
        { year: 2024, total_line: 351 },
      ],
      recent_admissions: [{ year: 2025, enroll_count: 601, admit_avg_score: 441 }],
    },
  ],
}

const latestRadar = () => mocks.radarOptions[mocks.radarOptions.length - 1]
const rowCells = (name) => within(screen.getByRole('link', { name }).closest('tr')).getAllByRole('cell')

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.search}</output>
}

async function renderCompared() {
  render(<MemoryRouter><KaoyanCompare /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '开始对比（已选 2）' }))
  await screen.findByRole('link', { name: '甲校' })
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.radarOptions.length = 0
  localStorage.clear()
  localStorage.setItem('ky_compare_school_ids', JSON.stringify([1, 2]))
  mocks.schools.mockResolvedValue({
    items: [{ id: 1, name: '甲校' }, { id: 2, name: '乙校' }],
  })
  mocks.compare.mockResolvedValue(compareResult)
})

afterEach(cleanup)

describe('KaoyanCompare 同年对比', () => {
  it('StrictMode 双挂载后仍展示接口返回的院校库', async () => {
    localStorage.clear()
    render(<StrictMode><MemoryRouter><KaoyanCompare /></MemoryRouter></StrictMode>)

    await waitFor(() => {
      const tile = [...document.querySelectorAll('.kyv3-stat-tile')]
        .find((node) => node.textContent.includes('院校库'))
      expect(within(tile).getByText('2')).toBeInTheDocument()
    })
  })

  it('0854 空态说明使用专业最低线与人数加权均分口径', async () => {
    localStorage.clear()
    render(<MemoryRouter><KaoyanCompare /></MemoryRouter>)

    await screen.findByText('支持名称、数字 ID，或「清华 北大」批量添加')
    expect(screen.getByText('专业最低线')).toBeInTheDocument()
    expect(screen.getByText('看实际竞争强度，按录取人数加权')).toBeInTheDocument()
    expect(screen.queryByText('取各专业录取均分均值')).toBeNull()
  })

  it('分数 2025、招生 2024 不串年，默认最新年份并动态扩展雷达上限', async () => {
    await renderCompared()

    expect(screen.getByRole('combobox', { name: '对比年份' })).toHaveTextContent('2025 年')
    expect(latestRadar().series[0].data.map((item) => item.value)).toEqual([
      [501, null, null],
      [null, 601, 441],
    ])
    expect(latestRadar().radar.indicator.map((indicator) => indicator.max)).toEqual([550, 700, 460])

    const cells = rowCells('甲校')
    expect(cells[3]).toHaveTextContent('2025')
    expect(cells[4].querySelector('.kyv3-compare-value')).toHaveTextContent('501')
    expect(cells[5]).toHaveTextContent('—')
    expect(cells[6]).toHaveTextContent('—')
    expect(mocks.compare).toHaveBeenCalledWith('1,2', { subject_code: '0854' })
  })

  it('深链恢复对比清单、专业与年份，详情链接保留专业范围', async () => {
    render(
      <MemoryRouter initialEntries={['/kaoyan/compare?ids=1,2&subject_code=0808&year=2024']}>
        <KaoyanCompare />
        <LocationProbe />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('link', { name: '甲校' })).toHaveAttribute(
      'href', '/kaoyan/schools/1?subject_code=0808',
    )
    expect(screen.getByLabelText('专业代码')).toHaveValue('0808')
    expect(screen.getByRole('combobox', { name: '对比年份' })).toHaveTextContent('2024 年')
    expect(mocks.compare).toHaveBeenCalledWith('1,2', { subject_code: '0808' })

    fireEvent.click(screen.getByRole('combobox', { name: '对比年份' }))
    fireEvent.click(screen.getByRole('option', { name: '2025 年' }))
    await waitFor(() => {
      const params = new URLSearchParams(screen.getByTestId('location').textContent)
      expect(params.get('ids')).toBe('1,2')
      expect(params.get('subject_code')).toBe('0808')
      expect(params.get('year')).toBe('2025')
    })
  })

  it('修改专业代码后清空旧结果并按新代码重新对比', async () => {
    await renderCompared()
    fireEvent.change(screen.getByLabelText('专业代码'), { target: { value: '0808' } })

    expect(screen.queryByRole('link', { name: '甲校' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '开始对比（已选 2）' }))
    await screen.findByRole('link', { name: '甲校' })
    expect(mocks.compare).toHaveBeenLastCalledWith('1,2', { subject_code: '0808' })
  })

  it('缺失指标在表格显示 —、雷达为 null，不补 0', async () => {
    await renderCompared()

    const schoolA = rowCells('甲校')
    const schoolB = rowCells('乙校')
    expect(schoolA[5]).toHaveTextContent('—')
    expect(schoolA[6]).toHaveTextContent('—')
    expect(schoolB[4].querySelector('.kyv3-compare-value')).toHaveTextContent('—')
    expect(latestRadar().series[0].data[0].value).toEqual([501, null, null])
    expect(latestRadar().series[0].data[1].value).toEqual([null, 601, 441])
  })

  it('切换年份后雷达、表格、历史分数与数据年份 stat 同步更新', async () => {
    await renderCompared()
    fireEvent.click(screen.getByRole('combobox', { name: '对比年份' }))
    fireEvent.click(screen.getByRole('option', { name: '2024 年' }))

    await waitFor(() => {
      expect(latestRadar().series[0].data.map((item) => item.value)).toEqual([
        [401, 601, 431],
        [351, null, null],
      ])
    })
    expect(screen.getByRole('combobox', { name: '对比年份' })).toHaveTextContent('2024 年')

    const schoolA = rowCells('甲校')
    const schoolB = rowCells('乙校')
    expect(schoolA[3]).toHaveTextContent('2024')
    expect(schoolA[4].querySelector('.kyv3-compare-value')).toHaveTextContent('401')
    expect(schoolA[5]).toHaveTextContent('601')
    expect(schoolA[6]).toHaveTextContent('431')
    expect(schoolA[4].querySelector('.kyv3-older-scores')).toHaveTextContent('2023: 390')
    expect(schoolA[4].querySelector('.kyv3-older-scores')).not.toHaveTextContent('2024:')
    expect(schoolB[3]).toHaveTextContent('2024')
    expect(schoolB[4].querySelector('.kyv3-compare-value')).toHaveTextContent('351')
    expect(schoolB[5]).toHaveTextContent('—')
    expect(schoolB[6]).toHaveTextContent('—')

    const dataYearTile = [...document.querySelectorAll('.kyv3-stat-tile')]
      .find((tile) => tile.textContent.includes('数据年份'))
    await waitFor(() => expect(within(dataYearTile).getByText('2,024')).toBeInTheDocument())
  })
})
