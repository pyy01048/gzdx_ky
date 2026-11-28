import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, act, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const quizApiMock = vi.hoisted(() => ({
  createSession: vi.fn(),
  getSession: vi.fn(),
  latestSession: vi.fn(),
  patchSession: vi.fn(),
  completeSession: vi.fn(),
  submit: vi.fn(),
  stats: vi.fn().mockResolvedValue({ total_questions: 0, total_attempts: 0 }),
}))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  request: vi.fn().mockResolvedValue({}),
  quizApi: quizApiMock,
}))

vi.mock('../api/quizFavSync', async (importOriginal) => ({
  ...(await importOriginal()),
  hydrateFavs: vi.fn().mockResolvedValue({}), migrateLocalFavs: vi.fn(),
}))
vi.mock('../v3/pages/QuizHome', () => ({
  default: function MockQuizHome({ onContinueSession, onBeginSession }) {
    const [latest, setLatest] = React.useState(null)
    React.useEffect(() => { let alive = true; quizApiMock.latestSession().then((value) => { if (alive) setLatest(value) }); return () => { alive = false } }, [])
    return (
      <>
        {latest ? <button onClick={() => onContinueSession(latest)}>继续上次</button> : null}
        <button onClick={() => onBeginSession(
          '工科08测试', questions, 'practice', 0, false,
          { kind: 'engineering08', engineering08: true, facets: {} },
        ).catch(() => {})}>创建工科08会话</button>
      </>
    )
  },
}))
vi.mock('../v3/pages/QuizResult', () => ({ default: () => <div>结果报告</div> }))

import Quiz from '../v3/pages/Quiz'
import QuizPractice from '../v3/pages/QuizPractice'
import { setUser as setPendingUser } from '../utils/userKeys'

const questions = [
  { id: 11, content: '第一题', options: ['甲', '乙'], answer: 'A', analysis: '第一解析', subject: '数电', question_type: 'single' },
  { id: 12, content: '第二题', options: ['甲', '乙'], answer: 'B', analysis: '第二解析', subject: '数电', question_type: 'single' },
]
const restored = {
  session_id: 77, title: '数电续做', mode: 'practice', noAnswer: false,
  basis: null, questions: questions.map((q) => q.id === 12 ? { ...q, question_type: 'essay', answer: null, analysis: null } : q), current_index: 1, version: 4,
  drafts: {}, text_drafts: { 12: '未提交答案' }, self_scores: {}, marked: { 11: true },
  duration_seconds: 30, status: 'in_progress',
  records: { 11: { question_id: 11, correct: true, my_answer: 'A', correct_answer: 'A', analysis: '第一解析' } },
}

beforeEach(() => {
  vi.clearAllMocks()
  window.scrollTo = vi.fn()
  localStorage.clear()
  quizApiMock.createSession.mockResolvedValue({ ...restored, session_id: 77, current_index: 0, duration_seconds: 0, records: {} })
  quizApiMock.getSession.mockResolvedValue(restored)
  quizApiMock.latestSession.mockResolvedValue(null)
  quizApiMock.patchSession.mockImplementation(async (_id, body) => ({ ...restored, ...body, version: (body.version || 1) + 1 }))
  quizApiMock.completeSession.mockResolvedValue({ ...restored, status: 'completed' })
  quizApiMock.submit.mockResolvedValue({ question_id: 12, correct: true, correct_answer: 'B', analysis: '第二解析', my_answer: 'B' })
})
afterEach(() => { cleanup(); setPendingUser(null); vi.useRealTimers() })

function renderQuiz(route = '/quiz') {
  return render(<MemoryRouter initialEntries={[route]}><Quiz /></MemoryRouter>)
}

function practiceProps(overrides = {}) {
  return {
    session: restored, records: restored.records, basis: null, favs: {}, kpFilter: null,
    backendOk: true, tutorMode: 'auto', setTutorMode: vi.fn(), submitting: false,
    setSubmitting: vi.fn(), onRecord: vi.fn(), onToggleFav: vi.fn(), onGoHome: vi.fn(), onFinish: vi.fn(),
    ...overrides,
  }
}

describe('普通刷题持久会话前端', () => {
  it('工科08会话持久化失败时不退回本地伪造会话', async () => {
    quizApiMock.createSession.mockRejectedValue(new Error('持久化失败'))
    renderQuiz()
    fireEvent.click(screen.getByRole('button', { name: '创建工科08会话' }))

    await waitFor(() => expect(quizApiMock.createSession).toHaveBeenCalledWith(
      expect.objectContaining({ basis: expect.objectContaining({ kind: 'engineering08', engineering08: true }) }),
    ))
    expect(screen.queryByText('第一题')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建工科08会话' })).toBeInTheDocument()
  })

  it('深链恢复后端快照、题号、草稿、标记和已判分记录，不重新取题', async () => {
    renderQuiz('/quiz?session_id=77')
    expect(await screen.findByText('第二题')).toBeInTheDocument()
    expect(quizApiMock.getSession).toHaveBeenCalledWith(77)
    expect(screen.queryByText('第一题')).not.toBeInTheDocument()
    expect(screen.getByDisplayValue('未提交答案')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '第 1 题，正确' })).toBeInTheDocument()
    expect(screen.queryByText('第二解析')).not.toBeInTheDocument()
  })

  it('继续上次恢复同一会话；完成后 latest 为空则隐藏入口', async () => {
    quizApiMock.latestSession.mockResolvedValue(restored)
    const view = renderQuiz()
    fireEvent.click(await screen.findByRole('button', { name: '继续上次' }))
    expect(await screen.findByText('第二题')).toBeInTheDocument()
    expect(quizApiMock.latestSession).toHaveBeenCalled()
    quizApiMock.latestSession.mockResolvedValue(null)
    view.unmount()
    renderQuiz()
    await act(async () => {})
    expect(screen.queryByRole('button', { name: '继续上次' })).not.toBeInTheDocument()
  })

  it('提交携带会话与幂等标识，双击不会发出第二次请求', async () => {
    let resolveSubmit
    quizApiMock.submit.mockImplementation(() => new Promise((resolve) => { resolveSubmit = resolve }))
    const onRecord = vi.fn()
    const { container } = render(<MemoryRouter><QuizPractice {...practiceProps({ session: { ...restored, current_index: 0 }, records: {}, onRecord })} /></MemoryRouter>)
    const option = container.querySelector('.v3-quiz-opt')
    fireEvent.click(option)
    fireEvent.click(option)
    expect(quizApiMock.submit).toHaveBeenCalledTimes(1)
    const [body] = quizApiMock.submit.mock.calls[0]
    expect(body).toMatchObject({ session_id: 77, question_id: 11, my_answer: 'A' })
    expect(body.client_attempt_id).toBeTruthy()
    await act(async () => { resolveSubmit({ question_id: 11, correct: true, correct_answer: 'A', analysis: '第一解析', my_answer: 'A' }) })
    expect(onRecord).toHaveBeenCalled()
  })

  it('选择题提交失败不本地判分，保留选择并用同一幂等标识重试', async () => {
    quizApiMock.submit
      .mockRejectedValueOnce(new Error('网络中断'))
      .mockResolvedValueOnce({ question_id: 11, correct: false, correct_answer: 'A', analysis: '第一解析', my_answer: 'B' })
    const onRecord = vi.fn()
    const { container } = render(<MemoryRouter><QuizPractice {...practiceProps({ session: { ...restored, current_index: 0 }, records: {}, onRecord })} /></MemoryRouter>)
    const options = container.querySelectorAll('.v3-quiz-opt')
    fireEvent.click(options[1])
    expect(await screen.findByRole('alert')).toHaveTextContent('网络中断')
    expect(onRecord).not.toHaveBeenCalled()
    expect(options[1]).toHaveClass('is-sel')
    const firstAttemptId = quizApiMock.submit.mock.calls[0][0].client_attempt_id

    fireEvent.click(options[1])
    await waitFor(() => expect(onRecord).toHaveBeenCalledWith(11, expect.objectContaining({ correct: false, selected: 'B', syncStatus: 'synced' })))
    expect(quizApiMock.submit).toHaveBeenCalledTimes(2)
    expect(quizApiMock.submit.mock.calls[1][0].client_attempt_id).toBe(firstAttemptId)
  })

  it('文本题自评提交失败保留对照结果，重试后才写入判分', async () => {
    quizApiMock.submit
      .mockRejectedValueOnce(new Error('网络中断'))
      .mockResolvedValueOnce({ question_id: 12, correct: false, correct_answer: 'B', analysis: '第二解析', my_answer: '未提交答案' })
    const onRecord = vi.fn()
    render(<MemoryRouter><QuizPractice {...practiceProps({ records: {}, onRecord })} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '对照答案' }))
    fireEvent.click(screen.getByRole('button', { name: '我答错了' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('网络中断')
    expect(onRecord).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '我答错了' })).toBeInTheDocument()
    const firstAttemptId = quizApiMock.submit.mock.calls[0][0].client_attempt_id

    fireEvent.click(screen.getByRole('button', { name: '我答错了' }))
    await waitFor(() => expect(onRecord).toHaveBeenCalledWith(12, expect.objectContaining({ correct: false, syncStatus: 'synced' })))
    expect(quizApiMock.submit.mock.calls[1][0].client_attempt_id).toBe(firstAttemptId)
  })

  it('自动保存携带题号与版本，保存失败不阻断切题', async () => {
    vi.useFakeTimers()
    quizApiMock.patchSession.mockRejectedValue(new Error('离线'))
    render(<MemoryRouter><QuizPractice {...practiceProps()} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '上一题' }))
    expect(screen.getByText('第一题')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(700) })
    expect(quizApiMock.patchSession).toHaveBeenCalledWith(77, expect.objectContaining({ current_index: 0, version: 4, marked: { 11: true } }))
  })

  it('保存遇到 409 时读取服务端快照、合并草稿并用新版本重试', async () => {
    vi.useFakeTimers()
    quizApiMock.patchSession
      .mockRejectedValueOnce(Object.assign(new Error('进度版本已变化'), { status: 409 }))
      .mockResolvedValueOnce({ ...restored, current_index: 0, version: 8 })
    quizApiMock.getSession.mockResolvedValue({
      ...restored, current_index: 0, version: 7, drafts: { 99: 1 }, updated_at: new Date().toISOString(),
    })
    render(<MemoryRouter><QuizPractice {...practiceProps()} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '上一题' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(700) })
    expect(quizApiMock.getSession).toHaveBeenCalledWith(77)
    expect(quizApiMock.patchSession).toHaveBeenCalledTimes(2)
    expect(quizApiMock.patchSession.mock.calls[1][1]).toMatchObject({
      version: 7, current_index: 0, drafts: { 99: 1 }, marked: { 11: true },
    })
  })

  it('退出前把未同步进度写入当前用户本地待保存区', async () => {
    setPendingUser(501)
    const onGoHome = vi.fn()
    quizApiMock.patchSession.mockRejectedValue(new Error('离线'))
    const view = render(<MemoryRouter><QuizPractice {...practiceProps({ onGoHome })} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '返回题库' }))
    await waitFor(() => expect(onGoHome).toHaveBeenCalled())
    const pending = JSON.parse(localStorage.getItem('quiz-session-pending:501') || '{}')
    expect(pending['77']).toMatchObject({ current_index: 1, version: 4, marked: { 11: true } })
    expect(localStorage.getItem('quiz-session-pending')).toBeNull()
    view.unmount()
  })

  it('恢复会话时合并更新的本地待保存进度', async () => {
    setPendingUser(502)
    localStorage.setItem('quiz-session-pending:502', JSON.stringify({
      77: {
        current_index: 0, version: 4, drafts: { 11: 1 }, text_drafts: { 12: '本地新草稿' },
        self_scores: { 12: '8' }, marked: { 11: false }, duration_seconds: 66,
        saved_at: new Date(Date.now() + 60_000).toISOString(),
      },
    }))
    render(<MemoryRouter><QuizPractice {...practiceProps()} /></MemoryRouter>)
    expect(screen.getByText('第一题')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '下一题' }))
    expect(screen.getByDisplayValue('本地新草稿')).toBeInTheDocument()
  })

  it('交卷完成会话，完成接口失败仍可查看报告', async () => {
    const onFinish = vi.fn()
    quizApiMock.completeSession.mockRejectedValue(new Error('离线'))
    render(<MemoryRouter><QuizPractice {...practiceProps({ onFinish })} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '交卷并查看报告' }))
    await waitFor(() => expect(quizApiMock.completeSession).toHaveBeenCalledWith(77))
    expect(onFinish).toHaveBeenCalled()
  })

  it('个人题库沿用原提交适配器，不携带普通会话字段', async () => {
    const submitAnswer = vi.fn().mockResolvedValue({ correct: true })
    const { container } = render(<MemoryRouter><QuizPractice {...practiceProps({ session: { ...restored, current_index: 0 }, records: {}, submitAnswer })} /></MemoryRouter>)
    fireEvent.click(container.querySelector('.v3-quiz-opt'))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    await waitFor(() => expect(submitAnswer).toHaveBeenCalled())
    const [body] = submitAnswer.mock.calls[0]
    expect(body).not.toHaveProperty('session_id')
    expect(body).not.toHaveProperty('client_attempt_id')
  })
})
