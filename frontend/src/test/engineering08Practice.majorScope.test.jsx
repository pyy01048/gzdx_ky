import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'

const authState = vi.hoisted(() => ({ user: null }))
const engineering08ApiMock = vi.hoisted(() => ({ catalog: vi.fn(), questions: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  engineering08Api: engineering08ApiMock,
}))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => authState }))

import Engineering08Practice, { subjectsForMajor } from '../v3/pages/Engineering08Practice'

const CATALOG = {
  disciplines: [{ id: 8, code: '0812', name: '计算机科学与技术' }],
  schools: [{ id: 1, name: '甲大学' }],
  majors: [{ id: 11, school_id: 1, code: '0812', name: '计算机' }],
  subjects: [
    { id: 101, name: '数学一', short_name: '数一' },
    { id: 102, name: '信号与系统', short_name: '信号' },
  ],
  major_subjects: [
    { major_id: 11, subject_id: 101 },
    { major_id: 99, subject_id: 102 },
  ],
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function renderPractice(route) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Engineering08Practice visible mode="practice" onBeginSession={vi.fn()} />
      <LocationProbe />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  authState.user = null
  engineering08ApiMock.catalog.mockResolvedValue(CATALOG)
  engineering08ApiMock.questions.mockResolvedValue({ items: [], total: 0, total_pages: 0 })
})

afterEach(() => cleanup())

describe('工科08专业 matched 科目约束', () => {
  it('纯函数只返回该专业在 207 中 matched 的科目', () => {
    expect(subjectsForMajor(CATALOG.majors[0], CATALOG).map((row) => row.id)).toEqual([101])
    expect(subjectsForMajor({ id: 100 }, CATALOG)).toEqual([])
    expect(subjectsForMajor(null, CATALOG)).toEqual([])
  })

  it('两个科目下拉都收窄，并可从练习进入保留实体 ID 的专业页', async () => {
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101')

    expect(await screen.findByText('甲大学 · 0812 计算机 · 数一')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '专业详情' })).toHaveAttribute(
      'href', '/kaoyan/majors/11?school_id=1&major_id=11&subject_id=101',
    )
    fireEvent.click(screen.getByRole('button', { name: '切换' }))
    fireEvent.click(await screen.findByRole('combobox', { name: '考试科目' }))
    expect(screen.getByRole('option', { name: '数学一（数一）' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '信号与系统（信号）' })).not.toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('combobox', { name: '考试科目' }), { key: 'Escape' })
    fireEvent.click(screen.getByRole('combobox', { name: '科目' }))
    expect(screen.getByRole('option', { name: '数学一' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '信号与系统' })).not.toBeInTheDocument()
  })

  it('深链中的非 matched subject_id 会被清除且不请求题目', async () => {
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=102')

    await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('subject_id=102'))
    expect(engineering08ApiMock.questions).not.toHaveBeenCalled()
    expect(screen.getByText('工科08 · 选择院校/专业')).toBeInTheDocument()
  })
})
