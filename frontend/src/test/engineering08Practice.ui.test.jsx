import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within, act } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'

const authState = vi.hoisted(() => ({ user: null }))
const engineering08ApiMock = vi.hoisted(() => ({
  catalog: vi.fn(),
  questions: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  engineering08Api: engineering08ApiMock,
}))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => authState }))

import Engineering08Practice from '../v3/pages/Engineering08Practice'

const CATALOG = {
  disciplines: [{ id: 8, code: '0812', name: '计算机科学与技术' }],
  schools: [
    { id: 1, name: '甲大学', question_count: 3 },
    { id: 2, name: '乙大学', question_count: 1 },
  ],
  majors: [
    { id: 11, school_id: 1, code: '0812', name: '计算机', question_count: 3 },
    { id: 21, school_id: 2, code: '0803', name: '光学', question_count: 1 },
  ],
  subjects: [
    { id: 101, name: '数学一', question_count: 2 },
    { id: 102, name: '信号与系统', question_count: 1 },
  ],
}

const QUESTION = {
  id: 9001,
  content: '某离散系统的单位冲激响应为 h[n]，求其频率响应。',
  subject_id: 101,
  year: 2025,
  question_type: 'single',
  source_kind: 'past_exam',
  source: '2025 年统考',
  difficulty: 4,
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function renderPractice(route = '/quiz?tab=engineering08', props = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Engineering08Practice visible mode="practice" onBeginSession={vi.fn()} {...props} />
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

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('工科08学习空间：URL 与用户隔离', () => {
  it('从 URL 恢复学习空间与五轴筛选，并展示完整空间条', async () => {
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101&year=2025&question_type=single&source_kind=past_exam&difficulty=4')

    expect(await screen.findByText('甲大学 · 0812 计算机 · 数学一')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '切换' }))
    expect(screen.getByRole('combobox', { name: '院校' })).toHaveTextContent('甲大学')
    expect(screen.getByRole('combobox', { name: '专业' })).toHaveTextContent('0812 计算机')
    expect(screen.getByRole('combobox', { name: '考试科目' })).toHaveTextContent('数学一')
    expect(screen.getByRole('combobox', { name: '科目' })).toHaveTextContent('数学一')
    expect(screen.getByRole('combobox', { name: '年份' })).toHaveTextContent('2025')
    expect(screen.getByRole('combobox', { name: '题型' })).toHaveTextContent('单选')
    expect(screen.getByRole('combobox', { name: '来源' })).toHaveTextContent('历年真题')
    expect(screen.getByRole('combobox', { name: '难度' })).toHaveTextContent('难度 4 · 较难')
  })

  it('匿名学习空间从 anonymous 键恢复，用户切换时读取各自命名空间', async () => {
    localStorage.setItem('engineering08_learning_space:anonymous', JSON.stringify({
      school_id: 1, major_id: 11, subject_id: 101,
    }))
    localStorage.setItem('engineering08_learning_space:2', JSON.stringify({
      school_id: 2, major_id: 21, subject_id: 102,
    }))
    authState.user = { id: 2 }
    const view = renderPractice()

    expect(await screen.findByText('乙大学 · 0803 光学 · 信号与系统')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('engineering08_learning_space:anonymous'))).toEqual({
      school_id: 1, major_id: 11, subject_id: 101,
    })

    authState.user = null
    view.rerender(
      <MemoryRouter initialEntries={['/quiz?tab=engineering08']}>
        <Engineering08Practice visible mode="practice" onBeginSession={vi.fn()} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('甲大学 · 0812 计算机 · 数学一')).toBeInTheDocument()
  })

  it('存储读取或写入失败时仍可手动选择学习空间', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage blocked') })
    renderPractice()

    fireEvent.click(await screen.findByRole('combobox', { name: '院校' }))
    fireEvent.click(screen.getByRole('option', { name: '甲大学' }))
    fireEvent.click(await screen.findByRole('combobox', { name: '专业' }))
    fireEvent.click(screen.getByRole('option', { name: '0812 计算机' }))
    fireEvent.click(await screen.findByRole('combobox', { name: '考试科目' }))
    fireEvent.click(screen.getByRole('option', { name: '数学一' }))

    expect(await screen.findByText('甲大学 · 0812 计算机 · 数学一')).toBeInTheDocument()
  })
})

describe('工科08学习空间：同屏题目结果', () => {
  it('筛选变化写回 URL、重置页码并立即按新参数请求', async () => {
    engineering08ApiMock.questions.mockResolvedValue({ items: [QUESTION], total: 21, total_pages: 2 })
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101&page=2')

    await waitFor(() => expect(engineering08ApiMock.questions).toHaveBeenCalledWith(
      expect.objectContaining({ page: 2, page_size: 20 }), expect.any(Object),
    ))
    fireEvent.click(screen.getByRole('combobox', { name: '年份' }))
    fireEvent.click(screen.getByRole('option', { name: '2024' }))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('year=2024'))
    expect(screen.getByTestId('location')).not.toHaveTextContent('page=2')
    await waitFor(() => expect(engineering08ApiMock.questions).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, year: 2024, school_id: 1, major_id: 11, subject_id: 101 }),
      expect.any(Object),
    ))
  })

  it('按 URL 五轴参数请求结果，并显示题干与完整元数据', async () => {
    engineering08ApiMock.questions.mockResolvedValue({ items: [QUESTION], total: 1, total_pages: 1 })
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101&year=2025&question_type=single&source_kind=past_exam&difficulty=4')

    await waitFor(() => expect(engineering08ApiMock.questions).toHaveBeenCalledWith({
      school_id: 1,
      major_id: 11,
      subject_id: 101,
      year: 2025,
      question_type: 'single',
      source_kind: 'past_exam',
      difficulty: 4,
      page: 1,
      page_size: 20,
    }, expect.any(Object)))

    expect(await screen.findByText('共 1 道题')).toBeInTheDocument()
    const row = within(screen.getByRole('list', { name: '工科08题目结果' })).getByRole('listitem')
    expect(row).toHaveTextContent(QUESTION.content)
    expect(row).toHaveTextContent('数学一')
    expect(row).toHaveTextContent('2025')
    expect(row).toHaveTextContent('单选')
    expect(row).toHaveTextContent('历年真题')
    expect(row).toHaveTextContent('难度 4 · 较难')
  })

  it('开始前拉取全部页并按 ID 去重，再携带 engineering08 facets 创建会话', async () => {
    let resolveSecondPage
    const secondPage = new Promise((resolve) => { resolveSecondPage = resolve })
    engineering08ApiMock.questions.mockImplementation((params) => {
      if (params.page === 2) return secondPage
      return Promise.resolve({ items: [QUESTION], total: 2, total_pages: 2 })
    })
    const onBeginSession = vi.fn().mockResolvedValue(undefined)
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101&year=2025&question_type=single&source_kind=past_exam&difficulty=4', { onBeginSession })

    const startButton = await screen.findByRole('button', { name: '开始练习' })
    await waitFor(() => expect(startButton).toBeEnabled())
    engineering08ApiMock.questions.mockClear()
    fireEvent.click(startButton)

    await waitFor(() => expect(engineering08ApiMock.questions).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 20, year: 2025, source_kind: 'past_exam' }),
    ))
    expect(onBeginSession).not.toHaveBeenCalled()
    resolveSecondPage({ items: [{ ...QUESTION, id: 9002 }, { ...QUESTION, id: 9001 }], total: 2, total_pages: 2 })

    await waitFor(() => expect(onBeginSession).toHaveBeenCalledTimes(1))
    const [title, questions, usedMode, startIndex, noAnswer, basis] = onBeginSession.mock.calls[0]
    expect(title).toContain('工科08')
    expect(questions.map((question) => question.id)).toEqual(['9001', '9002'])
    expect(usedMode).toBe('practice')
    expect(startIndex).toBe(0)
    expect(noAnswer).toBe(false)
    expect(basis).toMatchObject({
      kind: 'engineering08',
      engineering08: true,
      school_id: 1,
      major_id: 11,
      subject_id: 101,
      facets: {
        subject_id: 101,
        year: 2025,
        question_type: 'single',
        source_kind: 'past_exam',
        difficulty: 4,
      },
    })
    expect(engineering08ApiMock.questions).toHaveBeenCalledWith(
      expect.objectContaining({ page: 2, page_size: 20 }),
    )
  })

  it('开始拉取期间切换筛选时，旧请求结果不能创建会话', async () => {
    let resolveStartedFetch
    const startedFetch = new Promise((resolve) => { resolveStartedFetch = resolve })
    engineering08ApiMock.questions
      .mockResolvedValueOnce({ items: [QUESTION], total: 1, total_pages: 1 })
      .mockImplementationOnce(() => startedFetch)
      .mockResolvedValue({ items: [QUESTION], total: 1, total_pages: 1 })
    const onBeginSession = vi.fn()
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101&year=2025', { onBeginSession })

    const startButton = await screen.findByRole('button', { name: '开始练习' })
    await waitFor(() => expect(startButton).toBeEnabled())
    fireEvent.click(startButton)
    await waitFor(() => expect(engineering08ApiMock.questions).toHaveBeenCalledTimes(2))

    fireEvent.click(screen.getByRole('combobox', { name: '年份' }))
    fireEvent.click(screen.getByRole('option', { name: '2024' }))
    await waitFor(() => expect(engineering08ApiMock.questions).toHaveBeenLastCalledWith(
      expect.objectContaining({ year: 2024, page: 1 }), expect.any(Object),
    ))
    await waitFor(() => expect(startButton).toBeEnabled())
    await act(async () => {
      resolveStartedFetch({ items: [QUESTION], total: 1, total_pages: 1 })
      await startedFetch
    })
    expect(onBeginSession).not.toHaveBeenCalled()
  })

  it.each([
    ['空结果', { items: [], total: 0, total_pages: 0 }, '当前筛选下没有可开始练习的题目'],
    ['拉取失败', null, '分页加载失败'],
  ])('全部题拉取遇到%s时不伪造会话', async (_label, response, message) => {
    let callCount = 0
    engineering08ApiMock.questions.mockImplementation(() => {
      callCount += 1
      if (callCount === 1) return Promise.resolve({ items: [QUESTION], total: 1, total_pages: 1 })
      return response
        ? Promise.resolve(response)
        : Promise.reject(new Error('分页加载失败'))
    })
    const onBeginSession = vi.fn()
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101', { onBeginSession })

    const startButton = await screen.findByRole('button', { name: '开始练习' })
    await waitFor(() => expect(startButton).toBeEnabled())
    fireEvent.click(startButton)

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(onBeginSession).not.toHaveBeenCalled()
  })

  it('列表空态与列表加载失败均不提供可执行的练习入口', async () => {
    const onBeginSession = vi.fn()
    engineering08ApiMock.questions.mockResolvedValueOnce({ items: [], total: 0, total_pages: 0 })
    const view = renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101', { onBeginSession })

    expect(await screen.findByText('没有符合条件的题目')).toBeInTheDocument()
    const startButton = screen.getByRole('button', { name: '开始练习' })
    expect(startButton).toBeDisabled()
    fireEvent.click(startButton)
    expect(onBeginSession).not.toHaveBeenCalled()

    view.unmount()
    engineering08ApiMock.questions.mockRejectedValueOnce(new Error('列表加载失败'))
    renderPractice('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101', { onBeginSession })
    expect(await screen.findByText('题目加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始练习' })).toBeDisabled()
    expect(onBeginSession).not.toHaveBeenCalled()
  })
})
