import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const api = vi.hoisted(() => ({
  schools: vi.fn(),
  trend: vi.fn(),
}))

vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: {
    schools: api.schools,
    trend: api.trend,
  },
}))

import KaoyanAnalysis from '../v3/pages/KaoyanAnalysis'

beforeEach(() => {
  vi.clearAllMocks()
  api.schools.mockResolvedValue({
    items: [{ id: 1, name: '测试院校' }],
    total: 1,
  })
  api.trend.mockImplementation(({ metric }) => Promise.resolve({
    data: metric === 'enroll_count'
      ? [
        { year: 2025, value: 10 },
        { year: 2025, value: 20 },
        { year: 2024, value: 5 },
      ]
      : [
        { year: 2025, value: 350 },
        { year: 2025, value: 330 },
        { year: 2024, value: 360 },
        { year: 2024, value: 320 },
      ],
  }))
})

afterEach(cleanup)

describe('KaoyanAnalysis 年度口径', () => {
  it('同年多专业先聚合为一年，分数线取最低、招生人数取合计', async () => {
    render(<MemoryRouter><KaoyanAnalysis /></MemoryRouter>)
    const schoolSelect = await screen.findByRole('combobox', { name: '选择院校' })
    fireEvent.click(schoolSelect)
    fireEvent.click(await screen.findByRole('option', { name: '测试院校' }))

    const table = await screen.findByRole('table')
    await waitFor(() => expect(within(table).getAllByText('2025')).toHaveLength(1))
    expect(within(table).getByText('330 分')).toBeInTheDocument()
    expect(within(table).getByText('320 分')).toBeInTheDocument()
    expect(within(table).getAllByText('当年有效专业总分线的最低值')).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: '招生人数' }))
    await waitFor(() => expect(within(screen.getByRole('table')).getByText('30 人')).toBeInTheDocument())
    const enrollmentTable = screen.getByRole('table')
    expect(within(enrollmentTable).getAllByText('2025')).toHaveLength(1)
    expect(within(enrollmentTable).getAllByText('当年各专业拟招生人数之和')).toHaveLength(2)
  })
})
