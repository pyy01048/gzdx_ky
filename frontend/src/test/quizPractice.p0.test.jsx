import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * QuizPractice P0 功能回归测试
 *
 * 覆盖两条新增入口：
 *   ① 英语题判分后，揭示区出现「加入生词本」按钮：
 *      - 点击后调用 quizApi.extractWords 提取候选词
 *      - 过滤 exists=true 的词（已在词库的不再提交）
 *      - 确认后调用 wordsApi.batchImport，仅提交未存在的词，并带 source_label
 *   ② 文本题作答区「AI 批改」按钮：
 *      - 输入答案后可点击，调用 quizApi.gradeSubjective
 *      - 展示 AI 建议分 / max_score 与点评
 * ------------------------------------------------------------------ */

const QUIZ_QUESTIONS = [
  // 英语单选题（P0-1 生词提取入口）
  {
    id: 1,
    content: 'The ubiquitous smartphone has transformed modern life.',
    options: ['ubiquitous', 'rare', 'common', 'invisible'],
    answer: 'A',
    subject: '英语',
    question_type: 'single',
  },
  // 主观题（P0-2 AI 批改入口）
  {
    id: 2,
    content: '请论述微积分在工程中的应用。',
    answer: '微积分是研究变化的数学工具，广泛应用于工程优化与建模。',
    subject: '英语',
    question_type: 'essay',
    answer_type: 'subjective',
  },
]

const quizApiMock = {
  stats: vi.fn().mockResolvedValue({ total_questions: 0, total_attempts: 0, accuracy_rate: 0, active_errors: 0 }),
  questions: vi.fn(),
  submit: vi.fn().mockResolvedValue({ correct: true, correct_answer: 'A', analysis: '' }),
  papersIndex: vi.fn().mockResolvedValue({ papers: [] }),
  years: vi.fn().mockResolvedValue({ years: [] }),
  subjects: vi.fn().mockResolvedValue({ total: 1, items: [{ subject: '英语', question_count: 2, answerable_count: 2, error_count: 0 }] }),
  // P0-1 / P0-2
  extractWords: vi.fn(),
  gradeSubjective: vi.fn(),
}
const taxonomyApiMock = {
  subjects: vi.fn().mockResolvedValue({ subjects: [{ subject: '英语', question_count: 2, error_count: 0 }] }),
  tree: vi.fn().mockResolvedValue({ tree: [{ title: '英语', chapters: [] }] }),
}
const errorsApiMock = { list: vi.fn().mockResolvedValue({ items: [] }) }
const goalsApiMock = { subjects: vi.fn().mockResolvedValue({ exam_subjects: ['数学', '英语', '政治'], support_subjects: [] }) }
const wordsApiMock = { batchImport: vi.fn().mockResolvedValue({ ok: true, imported: 1 }) }

vi.mock('../api/client', async (importOriginal) => ({
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
  wordsApi: wordsApiMock,
}))

beforeEach(() => {
  for (const g of [quizApiMock, taxonomyApiMock, errorsApiMock, goalsApiMock, wordsApiMock]) {
    for (const fn of Object.values(g)) if (fn?.mockReset) fn.mockReset()
  }
  quizApiMock.stats.mockResolvedValue({ total_questions: 0, total_attempts: 0, accuracy_rate: 0, active_errors: 0 })
  quizApiMock.questions.mockResolvedValue({ questions: QUIZ_QUESTIONS, total: 2, total_count: 2, answerable_count: 2 })
  quizApiMock.submit.mockResolvedValue({ correct: true, correct_answer: 'A', analysis: '' })
  quizApiMock.papersIndex.mockResolvedValue({ papers: [] })
  quizApiMock.years.mockResolvedValue({ years: [] })
  quizApiMock.subjects.mockResolvedValue({ total: 1, items: [{ subject: '英语', question_count: 2, answerable_count: 2, error_count: 0 }] })
  taxonomyApiMock.subjects.mockResolvedValue({ subjects: [{ subject: '英语', question_count: 2, error_count: 0 }] })
  taxonomyApiMock.tree.mockResolvedValue({ tree: [{ title: '英语', chapters: [] }] })
  errorsApiMock.list.mockResolvedValue({ items: [] })
  goalsApiMock.subjects.mockResolvedValue({ exam_subjects: ['数学', '英语', '政治'], support_subjects: [] })
  wordsApiMock.batchImport.mockResolvedValue({ ok: true, imported: 1 })
})

afterEach(() => { cleanup(); localStorage.clear() })

async function renderQuiz(route = '/quiz') {
  const Quiz = (await import('../v3/pages/Quiz')).default
  const utils = render(<MemoryRouter initialEntries={[route]}><Quiz /></MemoryRouter>)
  await act(async () => { await new Promise((r) => setTimeout(r, 60)) })
  return utils
}

async function enterPractice() {
  const utils = await renderQuiz()
  await waitFor(() => expect(screen.getByRole('button', { name: /整科练习/ })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: /整科练习/ }))
  await act(async () => { await new Promise((r) => setTimeout(r, 60)) })
  return utils
}

/** 点击当前英语单选题的第一个选项（A ubiquitous）判分 */
function clickOptionA(container) {
  const opt = container.querySelector('.v3-quiz-opt')
  expect(opt).toBeTruthy()
  fireEvent.click(opt)
}

describe('P0-1 刷题生词一键进词库（英语题揭示区）', () => {
  it('判分后显示「加入生词本」，点击后过滤 exists=true 的词并只提交新词', async () => {
    const { container } = await enterPractice()

    // 首题为英语单选：点选项 A 判分
    clickOptionA(container)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    // 揭示区出现「加入生词本」按钮
    const addBtn = await screen.findByRole('button', { name: '加入生词本' })
    expect(addBtn).toBeInTheDocument()

    // mock 生词提取：ubiquitous 新词、smartphone 已在词库
    quizApiMock.extractWords.mockResolvedValue({
      question_id: 1,
      words: [
        { word: 'ubiquitous', exists: false, source: '题干' },
        { word: 'smartphone', exists: true, source: '题干' },
      ],
    })

    fireEvent.click(addBtn)
    // 确认弹窗出现（含预览词）
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    expect(screen.getByText(/将 1 个生词加入词库/)).toBeInTheDocument()
    expect(screen.getByText(/1 个已在词库，自动跳过/)).toBeInTheDocument()

    // 点击「加入」确认
    fireEvent.click(screen.getByRole('button', { name: '加入' }))
    await waitFor(() => expect(wordsApiMock.batchImport).toHaveBeenCalled())

    // 只提交 exists=false 的词，deck_id 为 null，并带 source_label
    expect(wordsApiMock.batchImport).toHaveBeenCalledTimes(1)
    const [body] = wordsApiMock.batchImport.mock.calls[0]
    expect(body.deck_id).toBeNull()
    expect(body.words).toHaveLength(1)
    expect(body.words[0]).toMatchObject({
      word: 'ubiquitous',
      source_label: expect.stringContaining('真题刷题'),
    })
    expect(body.words[0].meaning).toBeTruthy()
    expect(body.words[0].example).toContain('ubiquitous')
  })

  it('候选词全部已在词库时提示「已在词库」，不弹确认、不调 batchImport', async () => {
    const { container } = await enterPractice()
    clickOptionA(container)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    const addBtn = await screen.findByRole('button', { name: '加入生词本' })
    quizApiMock.extractWords.mockResolvedValue({
      question_id: 1,
      words: [{ word: 'ubiquitous', exists: true, source: '题干' }],
    })

    fireEvent.click(addBtn)
    await waitFor(() => expect(wordsApiMock.batchImport).not.toHaveBeenCalled())
    // 确认弹窗不应出现
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('P0-2 主观题 AI 批改', () => {
  it('文本题输入答案后可点「AI 批改」，展示建议分与点评', async () => {
    const { container } = await enterPractice()

    // 英语单选判分后切到下一题（文本题）
    clickOptionA(container)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    fireEvent.click(await screen.findByRole('button', { name: /下一题/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    // 文本题输入框出现
    const textarea = screen.getByLabelText('作答输入框')
    expect(textarea).toBeInTheDocument()

    // 未输入时 AI 批改按钮禁用
    const aiBtn = screen.getByRole('button', { name: 'AI 批改' })
    expect(aiBtn).toBeDisabled()

    // 输入答案后可点
    fireEvent.change(textarea, { target: { value: '微积分在工程优化中有广泛应用。' } })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(aiBtn).not.toBeDisabled()

    // mock AI 批改返回
    quizApiMock.gradeSubjective.mockResolvedValue({
      question_id: 2,
      score: 7.5,
      max_score: 10,
      evaluation: '思路清晰，论述充分。',
      reference_answer: '微积分是研究变化的数学工具。',
    })

    fireEvent.click(aiBtn)
    await waitFor(() => expect(quizApiMock.gradeSubjective).toHaveBeenCalled())

    expect(quizApiMock.gradeSubjective).toHaveBeenCalledWith({
      question_id: 2,
      my_answer: '微积分在工程优化中有广泛应用。',
      max_score: 10,
    })

    // 展示 AI 建议分与点评
    await waitFor(() => expect(screen.getByText(/AI 建议分：7\.5 \/ 10/)).toBeInTheDocument())
    expect(screen.getByText(/思路清晰，论述充分/)).toBeInTheDocument()
  })

  it('AI 批改 score 为 null 时展示兜底提示', async () => {
    const { container } = await enterPractice()
    clickOptionA(container)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    fireEvent.click(await screen.findByRole('button', { name: /下一题/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    const textarea = screen.getByLabelText('作答输入框')
    fireEvent.change(textarea, { target: { value: '不会。' } })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    quizApiMock.gradeSubjective.mockResolvedValue({
      question_id: 2,
      score: null,
      max_score: 10,
      evaluation: 'AI 暂不可用，请参考标准答案自评。',
      reference_answer: '微积分是研究变化的数学工具。',
    })

    fireEvent.click(screen.getByRole('button', { name: 'AI 批改' }))
    await waitFor(() => expect(quizApiMock.gradeSubjective).toHaveBeenCalled())
    // score=null 时展示兜底提示；evaluation 可能与之相同，故用 getAllByText 断言至少一个
    await waitFor(() => expect(screen.getAllByText(/AI 暂不可用，请参考标准答案自评/).length).toBeGreaterThan(0))
  })
})