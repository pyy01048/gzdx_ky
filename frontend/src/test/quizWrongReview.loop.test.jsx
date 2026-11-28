import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const quizApiMock = vi.hoisted(() => ({
  createSession: vi.fn(),
  getSession: vi.fn(),
  latestSession: vi.fn(),
  patchSession: vi.fn(),
  completeSession: vi.fn(),
  submit: vi.fn(),
  questionDetail: vi.fn(),
  questions: vi.fn().mockResolvedValue({ total_count: 0 }),
  stats: vi.fn().mockResolvedValue({ total_questions: 0, total_attempts: 0 }),
}))
const errorsApiMock = vi.hoisted(() => ({ list: vi.fn() }))
const reviewApiMock = vi.hoisted(() => ({ weakPoints: vi.fn(), wrongReasons: vi.fn(), reviewStats: vi.fn(), reviews: vi.fn(), submitReview: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  request: vi.fn().mockResolvedValue({}),
  quizApi: quizApiMock,
  errorsApi: errorsApiMock,
  quizSectionApi: reviewApiMock,
}))
vi.mock('../api/quizFavSync', async (importOriginal) => ({
  ...(await importOriginal()),
  hydrateFavs: vi.fn().mockResolvedValue({}), migrateLocalFavs: vi.fn(),
}))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 7 } }) }))
vi.mock('../v3/pages/QuizResult', () => ({ default: () => <div>结果报告</div> }))

import Quiz from '../v3/pages/Quiz'
import QuizPractice from '../v3/pages/QuizPractice'

const wrongQuestion = {
  id: 31, content: '错题原题', options: ['甲', '乙'], answer: 'A', analysis: '原题解析',
  subject: '数电', chapter: '逻辑电路', question_type: 'single',
}
const wrong = {
  id: 91, question_id: 31, content: '错题快照题干', my_answer: 'B', correct_answer: 'A',
  analysis: '快照解析', subject: '数电', status: 'active', accuracy: 0.2, review_count: 1,
  mastery_state: 'weak', next_review: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  window.scrollTo = vi.fn()
  localStorage.clear()
  quizApiMock.latestSession.mockResolvedValue(null)
  quizApiMock.submit.mockResolvedValue({ question_id: 31, correct: true, correct_answer: 'A', analysis: '原题解析', my_answer: 'A' })
  quizApiMock.questionDetail.mockImplementation(async (id) => ({ ...wrongQuestion, id }))
  quizApiMock.createSession.mockImplementation(async (body) => ({
    session_id: 77, title: body.title, mode: body.mode, no_answer: body.no_answer, basis: body.basis,
    filters: body.filters, knowledge_point_ids: [], question_ids: body.question_ids,
    questions: body.question_ids.map((id) => ({ ...wrongQuestion, id, answer: null, analysis: null })),
    current_index: body.start_index || 0, version: 1, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    duration_seconds: 0, status: 'in_progress', answered_count: 0, correct_count: 0, records: {},
  }))
  quizApiMock.patchSession.mockImplementation(async (_id, body) => ({ ...body, version: (body.version || 1) + 1 }))
  quizApiMock.completeSession.mockResolvedValue({ status: 'completed' })
  errorsApiMock.list.mockResolvedValue({ errors: [wrong], total: 1, total_pages: 1 })
  reviewApiMock.weakPoints.mockResolvedValue({ items: [] })
  reviewApiMock.wrongReasons.mockResolvedValue({ items: [] })
  reviewApiMock.reviewStats.mockResolvedValue({ today_reviews: 0, total_reviews: 0 })
  reviewApiMock.reviews.mockResolvedValue({ items: [] })
  reviewApiMock.submitReview.mockResolvedValue({ message: '复习已记录' })
})
afterEach(cleanup)

describe('错题重练闭环', () => {
  it('单题重练回取完整原题，并按真实 question_id 与 error_id 提交', async () => {
    render(<MemoryRouter initialEntries={['/quiz?tab=review']}><Quiz /></MemoryRouter>)
    const item = (await screen.findAllByText('错题快照题干')).at(-1).closest('.v3-quiz-item')
    fireEvent.click(item.querySelector('.v3-quiz-item__head'))
    fireEvent.click(await screen.findByRole('button', { name: '重练本题' }))
    const option = await screen.findByRole('button', { name: /A.*甲/ })
    expect(quizApiMock.questionDetail).toHaveBeenCalledWith(31)
    expect(quizApiMock.createSession).toHaveBeenCalledWith(expect.objectContaining({
      question_ids: [31], no_answer: false,
      basis: expect.objectContaining({ kind: 'error_review', question_error_ids: { 31: 91 } }),
    }))
    fireEvent.click(option)
    await waitFor(() => expect(quizApiMock.submit).toHaveBeenCalledWith(expect.objectContaining({
      session_id: 77, question_id: 31, error_id: 91, my_answer: 'A',
    })))
  })

  it('全部重练保留逐题错题归属，恢复会话后仍能回写原错题', async () => {
    let savedSession
    quizApiMock.createSession.mockImplementationOnce(async (body) => {
      savedSession = {
        session_id: 77, title: body.title, mode: body.mode, no_answer: body.no_answer, basis: body.basis,
        filters: body.filters, knowledge_point_ids: [], question_ids: body.question_ids,
        questions: body.question_ids.map((id) => ({ ...wrongQuestion, id, answer: null, analysis: null })),
        current_index: body.start_index || 0, version: 1, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
        duration_seconds: 0, status: 'in_progress', answered_count: 0, correct_count: 0, records: {},
      }
      return savedSession
    })
    const view = render(<MemoryRouter initialEntries={['/quiz?tab=review']}><Quiz /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: '全部重练' }))
    expect(await screen.findByRole('button', { name: /A.*甲/ })).toBeInTheDocument()

    view.unmount()
    quizApiMock.getSession.mockResolvedValue(savedSession)
    render(<MemoryRouter initialEntries={['/quiz?session_id=77']}><Quiz /></MemoryRouter>)
    expect(await screen.findByRole('button', { name: /A.*甲/ })).toBeInTheDocument()
    expect(quizApiMock.getSession).toHaveBeenCalledWith(77)

    fireEvent.click(screen.getByRole('button', { name: /A.*甲/ }))
    await waitFor(() => expect(quizApiMock.submit).toHaveBeenCalledWith(expect.objectContaining({
      session_id: 77, error_id: 91, question_id: 31,
    })))
  })

  it('原题缺失或无权访问时不创建伪题会话', async () => {
    quizApiMock.questionDetail.mockRejectedValue(new Error('题目 31 不存在'))
    render(<MemoryRouter initialEntries={['/quiz?tab=review']}><Quiz /></MemoryRouter>)
    const item = (await screen.findAllByText('错题快照题干')).at(-1).closest('.v3-quiz-item')
    fireEvent.click(item.querySelector('.v3-quiz-item__head'))
    fireEvent.click(await screen.findByRole('button', { name: '重练本题' }))
    await waitFor(() => expect(quizApiMock.questionDetail).toHaveBeenCalledWith(31))
    expect(quizApiMock.createSession).not.toHaveBeenCalled()
    expect(await screen.findByText(/重练失败/)).toBeInTheDocument()
  })

  it('待复习结果使用后端返回的真实 id，不能读取不存在的 item_id', async () => {
    reviewApiMock.reviews.mockResolvedValue({ items: [{ id: 91, item_type: 'error', name: '到期错题', subject: '数电' }] })
    render(<MemoryRouter initialEntries={['/quiz?tab=review']}><Quiz /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: '掌握' }))
    await waitFor(() => expect(reviewApiMock.submitReview).toHaveBeenCalledWith(expect.objectContaining({
      item_type: 'error', item_id: 91, result: 'mastered',
    })))
  })

  it('错题会话创建失败时不退化成丢失错题归属的本地练习', async () => {
    quizApiMock.createSession.mockRejectedValue(new Error('会话服务不可用'))
    render(<MemoryRouter initialEntries={['/quiz?tab=review']}><Quiz /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: '全部重练' }))
    expect(await screen.findByText(/重练失败/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '提交答案' })).not.toBeInTheDocument()
  })

  it('个人题库提交仍不携带错题或会话字段', async () => {
    const submitAnswer = vi.fn().mockResolvedValue({ correct: true })
    const session = {
      session_id: null, questions: [wrongQuestion], records: {}, noAnswer: false,
      drafts: {}, text_drafts: {}, self_scores: {}, marked: {}, version: 1, duration_seconds: 0,
    }
    const { container } = render(<MemoryRouter><QuizPractice
      session={session} records={{}} basis={null} favs={{}} kpFilter={null} backendOk tutorMode="auto"
      setTutorMode={vi.fn()} submitting={false} setSubmitting={vi.fn()} submitAnswer={submitAnswer}
      onRecord={vi.fn()} onToggleFav={vi.fn()} onGoHome={vi.fn()} onFinish={vi.fn()}
    /></MemoryRouter>)
    fireEvent.click(container.querySelector('.v3-quiz-opt'))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    await waitFor(() => expect(submitAnswer).toHaveBeenCalled())
    expect(submitAnswer.mock.calls[0][0]).not.toHaveProperty('session_id')
    expect(submitAnswer.mock.calls[0][0]).not.toHaveProperty('error_id')
  })
})
