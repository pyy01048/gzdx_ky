import { useMemo, useState } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const quizApiMock = vi.hoisted(() => ({ submit: vi.fn() }))

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  quizApi: quizApiMock,
}))

import QuizPractice from '../v3/pages/QuizPractice'
import { ToastHost } from '../v3/ui'

const choiceQuestion = {
  id: '101',
  content: '单选题',
  options: ['正确选项', '错误选项'],
  answer: 'A',
  analysis: '选择 A',
  question_type: 'single',
  subject: '数学',
}

const textQuestion = {
  id: '202',
  content: '请简述理由',
  answer: '参考答案',
  analysis: '参考解析',
  question_type: 'essay',
  answer_type: 'subjective',
  max_score: 20,
  subject: '数学',
}

function Harness({ question }) {
  const [records, setRecords] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const session = useMemo(() => ({ questions: [question], noAnswer: false, startIdx: 0 }), [question])
  return (
    <QuizPractice
      session={session}
      records={records}
      basis={null}
      favs={{}}
      kpFilter={null}
      backendOk
      tutorMode="exam"
      setTutorMode={() => {}}
      submitting={submitting}
      setSubmitting={setSubmitting}
      onRecord={(qid, entry) => setRecords((prev) => ({ ...prev, [qid]: entry }))}
      onToggleFav={() => {}}
      onGoHome={() => {}}
      onFinish={() => {}}
    />
  )
}

const renderPractice = (question) => render(
  <MemoryRouter><Harness question={question} /><ToastHost /></MemoryRouter>,
)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

describe('QuizPractice 提交失败语义', () => {
  it('选择题提交失败时不本地判分、不写错题本，并保留选择供重试', async () => {
    quizApiMock.submit.mockRejectedValue(new Error('网络断开'))
    renderPractice(choiceQuestion)

    fireEvent.click(screen.getByRole('button', { name: /错误选项/ }))

    expect(await screen.findByText('网络断开')).toBeInTheDocument()
    expect(screen.queryByText(/答错已计入错题本/)).not.toBeInTheDocument()
    expect(screen.queryByText('选择 A')).not.toBeInTheDocument()
    expect(quizApiMock.submit).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('quiz_wrong')).toBeNull()
    expect(screen.getByRole('button', { name: /错误选项/ })).toHaveClass('is-sel')
  })

  it('文本题自评提交失败时保留对照结果，但不写判分记录或错题本', async () => {
    quizApiMock.submit.mockRejectedValue(new Error('提交超时'))
    renderPractice(textQuestion)

    fireEvent.change(screen.getByLabelText('作答输入框'), { target: { value: '我的答案' } })
    fireEvent.click(screen.getByRole('button', { name: '对照答案' }))
    expect(quizApiMock.submit).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '我答错了' }))

    expect(await screen.findByText('提交超时')).toBeInTheDocument()
    expect(screen.queryByText(/答错已计入错题本/)).not.toBeInTheDocument()
    expect(quizApiMock.submit).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('quiz_wrong')).toBeNull()
  })
})

describe('QuizPractice 主观题自评提交契约', () => {
  it('对照答案不提交；自评时仅提交一次并携带 self_score/max_score', async () => {
    quizApiMock.submit.mockResolvedValue({
      record_id: 77,
      correct: false,
      correct_answer: '参考答案',
      analysis: '参考解析',
      is_subjective: true,
      self_score: 0,
      max_score: 20,
    })
    renderPractice(textQuestion)

    fireEvent.change(screen.getByLabelText('作答输入框'), { target: { value: '我的答案' } })
    fireEvent.click(screen.getByRole('button', { name: '对照答案' }))
    expect(quizApiMock.submit).not.toHaveBeenCalled()

    const wrongButton = screen.getByRole('button', { name: '我答错了' })
    fireEvent.click(wrongButton)
    fireEvent.click(wrongButton)

    await waitFor(() => expect(quizApiMock.submit).toHaveBeenCalledTimes(1))
    expect(quizApiMock.submit).toHaveBeenCalledWith({
      question_id: 202,
      my_answer: '我的答案',
      self_score: 0,
      max_score: 20,
    })
    expect(await screen.findByText(/答错已计入错题本/)).toBeInTheDocument()
    expect(screen.queryByText(/本地判分，后端未同步/)).not.toBeInTheDocument()
  })

  it('自评通过时提交满分 self_score，并采用后端判分结果', async () => {
    quizApiMock.submit.mockResolvedValue({ correct: true, self_score: 20, max_score: 20 })
    renderPractice(textQuestion)

    fireEvent.change(screen.getByLabelText('作答输入框'), { target: { value: '完整答案' } })
    fireEvent.click(screen.getByRole('button', { name: '对照答案' }))
    fireEvent.click(screen.getByRole('button', { name: '我答对了' }))

    await waitFor(() => expect(quizApiMock.submit).toHaveBeenCalledWith({
      question_id: 202,
      my_answer: '完整答案',
      self_score: 20,
      max_score: 20,
    }))
    await waitFor(() => expect(
      screen.getAllByRole('status').some((node) => node.textContent.includes('回答正确')),
    ).toBe(true))
  })
})
