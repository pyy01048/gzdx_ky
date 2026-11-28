import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'

const quizApiMock = vi.hoisted(() => ({
  stats: vi.fn(), latestSession: vi.fn(), subjects: vi.fn(), questions: vi.fn(), papersIndex: vi.fn(), years: vi.fn(), questionDetail: vi.fn(),
}))
const errorsApiMock = vi.hoisted(() => ({ list: vi.fn() }))
const engineering08ApiMock = vi.hoisted(() => ({
  catalog: vi.fn().mockResolvedValue({ disciplines: [], schools: [], majors: [], subjects: [] }),
  questions: vi.fn().mockResolvedValue({ items: [], total: 0, total_pages: 0 }),
}))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  quizApi: quizApiMock,
  engineering08Api: engineering08ApiMock,
  taxonomyApi: { subjects: vi.fn().mockResolvedValue({ subjects: [] }), tree: vi.fn().mockResolvedValue({ tree: [] }) },
  goalsApi: { subjects: vi.fn().mockResolvedValue({ exam_subjects: [], support_subjects: [] }) },
  errorsApi: errorsApiMock,
}))
vi.mock('../auth/AuthContext', () => {
  const user = { id: 7 }
  return { useAuth: () => ({ user }) }
})
vi.mock('../v3/pages/QuizYear', () => ({ default: () => null }))
vi.mock('../v3/pages/QuizWrongReview', () => ({ default: () => null }))

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

import QuizHome from '../v3/pages/QuizHome'

beforeEach(() => {
  vi.clearAllMocks()
  quizApiMock.stats.mockResolvedValue({ total_questions: 10, answerable_total: 8 })
  quizApiMock.subjects.mockResolvedValue({ items: [] })
  quizApiMock.questions.mockResolvedValue({ total_count: 0 })
  errorsApiMock.list.mockResolvedValue({ items: [] })
  quizApiMock.latestSession.mockResolvedValue(null)
})
afterEach(cleanup)

function renderHome(onBeginSession = vi.fn()) {
  const onContinueSession = vi.fn()
  render(<MemoryRouter initialEntries={['/quiz']}><QuizHome visible mode="practice" setMode={vi.fn()} sourceKind="exam" setSourceKind={vi.fn()} kpFilter={null} kpEmpty={null} favs={{}} submitting={false} onBeginSession={onBeginSession} onStartWithFilter={vi.fn()} onClearKp={vi.fn()} onContinueSession={onContinueSession} /><LocationProbe /></MemoryRouter>)
  return { onContinueSession, onBeginSession }
}

describe('刷题首页继续上次', () => {
  it('提供工科08独立入口，点击后写入 tab URL', async () => {
    renderHome()
    fireEvent.click(await screen.findByRole('tab', { name: '工科08' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/quiz?tab=engineering08'))
    expect(screen.queryByText('自定义练习')).not.toBeInTheDocument()
    expect(screen.queryByRole('tablist', { name: '题目来源' })).not.toBeInTheDocument()
  })

  it('展示进行中会话的标题与进度，并把同一会话交回容器', async () => {
    const latest = { session_id: 91, title: '信号与系统', answered_count: 3, total_questions: 10, status: 'in_progress' }
    quizApiMock.latestSession.mockResolvedValue(latest)
    const { onContinueSession } = renderHome()
    fireEvent.click(await screen.findByRole('button', { name: '继续作答' }))
    expect(screen.getByText(/信号与系统 · 已作答 3\/10 题/)).toBeInTheDocument()
    expect(onContinueSession).toHaveBeenCalledWith(latest)
  })

  it('latest 为空或已结束时隐藏入口', async () => {
    quizApiMock.latestSession.mockResolvedValue(null)
    const { onContinueSession } = renderHome()
    await screen.findByTestId('location')
    await waitFor(() => expect(quizApiMock.latestSession).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: '继续作答' })).not.toBeInTheDocument()
    expect(onContinueSession).not.toHaveBeenCalled()
    cleanup()
    quizApiMock.latestSession.mockResolvedValue({ session_id: 92, status: 'completed' })
    renderHome()
    await waitFor(() => expect(quizApiMock.latestSession).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('button', { name: '继续作答' })).not.toBeInTheDocument()
  })

  it('自定义只练错题回取完整原题并保留错题归属，不使用快照浏览', async () => {
    errorsApiMock.list.mockResolvedValue({ errors: [{ id: 91, question_id: 31, content: '错题快照', subject: '数电' }], total: 1, total_pages: 1 })
    quizApiMock.questionDetail.mockResolvedValue({
      id: 31, content: '完整原题', options: ['甲', '乙'], answer: 'A', analysis: '完整解析', subject: '数电', question_type: 'single',
    })
    const { onBeginSession } = renderHome()
    fireEvent.click(screen.getByText('只练错题'))
    expect(screen.getByText(/候选池为全部活跃错题/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '开始练习' }))
    await waitFor(() => expect(errorsApiMock.list).toHaveBeenCalled())
    await waitFor(() => expect(quizApiMock.questionDetail).toHaveBeenCalledWith(31))
    await waitFor(() => expect(onBeginSession).toHaveBeenCalled())
    expect(quizApiMock.questionDetail).toHaveBeenCalledWith(31)
    expect(onBeginSession).toHaveBeenCalledWith(
      expect.stringContaining('错题'),
      [expect.objectContaining({ id: '31', content: '完整原题', error_id: 91 })],
      'practice', 0, false,
      expect.objectContaining({ kind: 'error_review', question_error_ids: { 31: 91 } }),
    )
  })

  it('创建会话期间不重复请求最新会话', async () => {
    let resolveLatest
    quizApiMock.latestSession.mockImplementation(() => new Promise((resolve) => { resolveLatest = resolve }))
    renderHome()
    await waitFor(() => expect(resolveLatest).toBeTypeOf('function'))
    resolveLatest(null)
    await waitFor(() => expect(screen.queryByRole('button', { name: '继续作答' })).not.toBeInTheDocument())
    expect(quizApiMock.latestSession).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('location')).toHaveTextContent('/quiz')
  })
})
