import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 刷题中心（M0 重构）回归测试
 *
 * 锁定三条用户诉求的关键契约：
 *   ① 真题 / 教材题**分页隔离**：默认 source_kind='exam'，切「教材题」→ 'textbook'，
 *      两类题不混在同一列表里；
 *   ② 科目严格隔离：请求 subject=X 时，返回体里 subject≠X 的题被前端二次剔除；
 *   ③ 空选项题**不渲染空白选项按钮**：options 全为空白的题显示「本题无选项」标记，
 *      页面上不存在可点击的空白 .qopt 按钮。
 * ------------------------------------------------------------------ */

const QUIZ_QUESTIONS = [
  // 空选项题（options 非空数组但元素全空白）→ 归一化后应视为无选项
  { id: 1, content: '数电·空选项题', options: ['', '  ', null], answer: 'A', subject: '数电', question_type: 'single' },
  { id: 2, content: '数电·正常单选题', options: ['甲', '乙', '丙', '丁'], answer: 'B', subject: '数电', question_type: 'single' },
  // 脏数据：科目不符，必须被隔离
  { id: 3, content: '政治·串科目脏题', options: ['甲', '乙'], answer: 'A', subject: '政治', question_type: 'single' },
]

const quizApiMock = {
  stats: vi.fn().mockResolvedValue({ total_questions: 10, total_attempts: 1, accuracy_rate: 0, active_errors: 0 }),
  questions: vi.fn(),
  submit: vi.fn().mockResolvedValue({ correct: true, correct_answer: 'B', analysis: '' }),
  papersIndex: vi.fn().mockResolvedValue({ papers: [] }),
  years: vi.fn().mockResolvedValue({ years: [] }),
  subjects: vi.fn().mockResolvedValue({ total: 1, items: [{ subject: '数电', question_count: 3, answerable_count: 2, error_count: 0 }] }),
}
const taxonomyApiMock = {
  subjects: vi.fn().mockResolvedValue({ subjects: [{ subject: '数电', question_count: 3, error_count: 0 }] }),
  tree: vi.fn().mockResolvedValue({ tree: [{ title: '数电', chapters: [] }] }),
}
const errorsApiMock = { list: vi.fn().mockResolvedValue({ items: [] }) }
const goalsApiMock = { subjects: vi.fn().mockResolvedValue({ exam_subjects: [], support_subjects: [] }) }
const quizSectionApiMock = {
  weakPoints: vi.fn().mockResolvedValue({ items: [] }),
  wrongReasons: vi.fn().mockResolvedValue({ items: [] }),
  reviewStats: vi.fn().mockResolvedValue({}),
  reviews: vi.fn().mockResolvedValue({ items: [] }),
  submitReview: vi.fn().mockResolvedValue({}),
}

vi.mock('../api/client', async (importOriginal) => ({
  // 派生真实模块的导出清单：client.js 新增导出（如 fetchAllPages）不必再回来补枚举，
  // 否则页面一 import 就报 "No export is defined on the mock"。
  ...(await importOriginal()),
  request: vi.fn().mockResolvedValue({}),
  DEFAULT_TIMEOUT: 30000,
  favoritesApi: {
    list: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    add: vi.fn().mockResolvedValue({ ok: true, id: 1 }),
    check: vi.fn().mockResolvedValue({ favorited: false, id: null }),
    toggle: vi.fn().mockResolvedValue({ favorited: false }),
    remove: vi.fn().mockResolvedValue({ ok: true }),
  },
  quizApi: quizApiMock,
  taxonomyApi: taxonomyApiMock,
  errorsApi: errorsApiMock,
  goalsApi: goalsApiMock,
  quizSectionApi: quizSectionApiMock,
}))

beforeEach(() => {
  for (const g of [quizApiMock, taxonomyApiMock, errorsApiMock, quizSectionApiMock]) {
    for (const fn of Object.values(g)) if (fn?.mockReset) fn.mockReset()
  }
  quizApiMock.stats.mockResolvedValue({ total_questions: 10, total_attempts: 1, accuracy_rate: 0, active_errors: 0 })
  quizApiMock.questions.mockResolvedValue({
    questions: QUIZ_QUESTIONS,
    total: 3, total_count: 3, answerable_count: 2, source_kind: 'exam',
  })
  quizApiMock.submit.mockResolvedValue({ correct: true, correct_answer: 'B', analysis: '' })
  quizApiMock.papersIndex.mockResolvedValue({ papers: [] })
  quizApiMock.years.mockResolvedValue({ years: [] })
  quizApiMock.subjects.mockResolvedValue({ total: 1, items: [{ subject: '数电', question_count: 3, answerable_count: 2, error_count: 0 }] })
  taxonomyApiMock.subjects.mockResolvedValue({ subjects: [{ subject: '数电', question_count: 3, error_count: 0 }] })
  taxonomyApiMock.tree.mockResolvedValue({ tree: [{ title: '数电', chapters: [] }] })
  errorsApiMock.list.mockResolvedValue({ items: [] })
  goalsApiMock.subjects.mockResolvedValue({ exam_subjects: [], support_subjects: [] })
  quizSectionApiMock.weakPoints.mockResolvedValue({ items: [] })
  quizSectionApiMock.wrongReasons.mockResolvedValue({ items: [] })
  quizSectionApiMock.reviewStats.mockResolvedValue({})
  quizSectionApiMock.reviews.mockResolvedValue({ items: [] })
})

afterEach(() => { cleanup(); localStorage.clear() })

async function renderQuiz(route = '/quiz') {
  const Quiz = (await import('../v3/pages/Quiz')).default
  const utils = render(<MemoryRouter initialEntries={[route]}><Quiz /></MemoryRouter>)
  await act(async () => { await new Promise((r) => setTimeout(r, 60)) })
  return utils
}

/** 取 quizApi.questions 最近一次调用的参数 */
function lastQuestionsArg() {
  expect(quizApiMock.questions).toHaveBeenCalled()
  const calls = quizApiMock.questions.mock.calls
  return calls[calls.length - 1][0]
}

describe('刷题中心：真题 / 教材题分页隔离', () => {
  it('默认「历年真题」：取题请求带 source_kind=exam（真题与教材题不混排）', async () => {
    await renderQuiz()
    // 科目列表就绪后点「整科练习」进入会话
    await waitFor(() => expect(screen.getByRole('button', { name: /整科练习/ })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /整科练习/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 60)) })

    expect(lastQuestionsArg().source_kind).toBe('exam')
    // 科目严格隔离：请求 subject=数电
    expect(lastQuestionsArg().subject).toBe('数电')
  })

  it('切到「教材题」后，取题请求带 source_kind=textbook', async () => {
    await renderQuiz()
    fireEvent.click(screen.getByRole('tab', { name: '教材题' }))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    await waitFor(() => expect(screen.getByRole('button', { name: /整科练习/ })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /整科练习/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 60)) })

    expect(lastQuestionsArg().source_kind).toBe('textbook')
  })
})

describe('刷题中心：科目严格隔离（前端二次校验）', () => {
  it('返回体含 subject≠请求科目的脏题时，脏题被隔离，不出现在会话中', async () => {
    await renderQuiz()
    await waitFor(() => expect(screen.getByRole('button', { name: /整科练习/ })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /整科练习/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 60)) })

    // 请求科目=数电 → 政治脏题必须被剔除（不出现在页面上）
    expect(screen.queryByText(/政治·串科目脏题/)).not.toBeInTheDocument()
    // 数电题正常进入会话
    expect(screen.getByText(/数电·空选项题/)).toBeInTheDocument()
  })
})

describe('刷题中心：空选项题不渲染空白选项按钮', () => {
  it('options 全为空白的题显示「本题无选项」标记，且无可点击的 .qopt 选项按钮', async () => {
    const { container } = await renderQuiz()
    await waitFor(() => expect(screen.getByRole('button', { name: /整科练习/ })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /整科练习/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 60)) })

    // 首题（idx 0）即空选项题
    expect(screen.getByText(/数电·空选项题/)).toBeInTheDocument()
    expect(screen.getByText(/本题无选项/)).toBeInTheDocument()
    // 关键：不渲染任何选项按钮
    expect(container.querySelectorAll('.qopt').length).toBe(0)
  })
})
