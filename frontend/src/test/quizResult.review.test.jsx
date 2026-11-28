import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import QuizResult from '../v3/pages/QuizResult'

const { quizApi, recommendApi, request } = vi.hoisted(() => ({
  quizApi: { orchestratedTutoring: vi.fn() },
  recommendApi: {
    weakPoints: vi.fn(),
    variants: vi.fn(),
    masteryGate: vi.fn(),
  },
  request: vi.fn(),
}))

vi.mock('../api/client', () => ({ quizApi, recommendApi, request }))

const QUESTIONS = [
  { id: 1, content: '已确认正确题', subject: '数学', chapter: '极限', answer: 'A' },
  { id: 2, content: '待确认题', subject: '数学', chapter: '极限', answer: 'B' },
  { id: 3, content: '未作答题', subject: '数学', chapter: '连续', answer: 'C' },
]

function renderResult() {
  return render(
    <QuizResult
      session={{ title: '答题能力回归', mode: 'practice', questions: QUESTIONS }}
      records={{
        1: { correct: true, selected: 'A', correctAnswer: 'A', analysis: '正确解析' },
        2: { correct: null, needsReview: true, selected: 'A', correctAnswer: 'B', analysis: '置信度不足，待核对' },
      }}
      startedFromRef={{ current: { mode: 'practice', title: '答题能力回归', questions: QUESTIONS } }}
      tutorMode="auto"
      setTutorMode={vi.fn()}
      onBeginSession={vi.fn()}
      onGoHome={vi.fn()}
    />,
  )
}

beforeEach(() => {
  recommendApi.weakPoints.mockResolvedValue({ items: [] })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('QuizResult 三态判分', () => {
  it('待确认题不计入答错、正确率分母和错题重练，并在明细中中性展示', async () => {
    renderResult()
    await act(async () => { await Promise.resolve() })

    const graded = screen.getByText('已判分').closest('.v3-quiz-result-stat')
    const correct = screen.getByText('答对').closest('.v3-quiz-result-stat')
    const wrong = screen.getByText('答错').closest('.v3-quiz-result-stat')
    const review = document.querySelector('.v3-quiz-result-stat.is-review')
    expect(graded).toHaveTextContent('1')
    expect(correct).toHaveTextContent('1')
    expect(wrong).toHaveTextContent('0')
    expect(review).toHaveTextContent('1')
    expect(document.querySelector('.v3-quiz-ring-center strong')).toHaveTextContent('100%')
    expect(screen.queryByRole('button', { name: /重练错题/ })).not.toBeInTheDocument()

    const reviewRow = document.querySelector('.v3-quiz-sheet-row.is-review')
    expect(reviewRow).toHaveTextContent('待确认')
    expect(reviewRow).not.toHaveClass('is-bad')
    expect(document.querySelector('.v3-quiz-chapter-stat')).toHaveTextContent('1/1')
    expect(document.querySelector('.v3-quiz-chapter-stat')).not.toHaveTextContent('1/2')
  })
})
