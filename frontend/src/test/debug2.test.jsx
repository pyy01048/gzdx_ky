import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const QUIZ_QUESTIONS = [
  { id: 1, content: 'The ubiquitous smartphone has transformed modern life.', options: ['ubiquitous', 'rare', 'common', 'invisible'], answer: 'A', subject: '英语', question_type: 'single' },
  { id: 2, content: '请论述微积分在工程中的应用。', answer: '微积分', subject: '英语', question_type: 'essay', answer_type: 'subjective' },
]
const quizApiMock = {
  stats: vi.fn().mockResolvedValue({ total_questions: 0, total_attempts: 0, accuracy_rate: 0, active_errors: 0 }),
  questions: vi.fn(), submit: vi.fn().mockResolvedValue({ correct: true, correct_answer: 'A', analysis: '' }),
  papersIndex: vi.fn().mockResolvedValue({ papers: [] }), years: vi.fn().mockResolvedValue({ years: [] }),
  subjects: vi.fn().mockResolvedValue({ total: 1, items: [{ subject: '英语', question_count: 2, answerable_count: 2, error_count: 0 }] }),
  extractWords: vi.fn(), gradeSubjective: vi.fn(), orchestratedTutoring: vi.fn(),
}
const recommendApiMock = { weakPoints: vi.fn(), variants: vi.fn(), masteryGate: vi.fn() }
const taxonomyApiMock = { subjects: vi.fn().mockResolvedValue({ subjects: [{ subject: '英语', question_count: 2, error_count: 0 }] }), tree: vi.fn().mockResolvedValue({ tree: [{ title: '英语', chapters: [] }] }) }
const errorsApiMock = { list: vi.fn().mockResolvedValue({ items: [] }) }
const goalsApiMock = { subjects: vi.fn().mockResolvedValue({ exam_subjects: ['数学', '英语', '政治'], support_subjects: [] }) }
const wordsApiMock = { batchImport: vi.fn().mockResolvedValue({ ok: true, imported: 1 }) }

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  request: vi.fn().mockResolvedValue({}),
  DEFAULT_TIMEOUT: 30000,
  favoritesApi: { list: vi.fn().mockResolvedValue({ total: 0, items: [] }), add: vi.fn().mockResolvedValue({ ok: true, id: 1 }), check: vi.fn().mockResolvedValue({ favorited: false, id: null }), toggle: vi.fn().mockResolvedValue({ favorited: false }), remove: vi.fn().mockResolvedValue({ ok: true }) },
  quizApi: quizApiMock, recommendApi: recommendApiMock, taxonomyApi: taxonomyApiMock, errorsApi: errorsApiMock, goalsApi: goalsApiMock, wordsApi: wordsApiMock,
}))

beforeEach(() => {
  quizApiMock.stats.mockResolvedValue({ total_questions: 0, total_attempts: 0, accuracy_rate: 0, active_errors: 0 })
  quizApiMock.questions.mockResolvedValue({ questions: QUIZ_QUESTIONS, total: 2, total_count: 2, answerable_count: 2 })
  quizApiMock.submit.mockResolvedValue({ correct: true, correct_answer: 'A', analysis: '' })
  quizApiMock.papersIndex.mockResolvedValue({ papers: [] })
  quizApiMock.years.mockResolvedValue({ years: [] })
  quizApiMock.subjects.mockResolvedValue({ total: 1, items: [{ subject: '英语', question_count: 2, answerable_count: 2, error_count: 0 }] })
  recommendApiMock.weakPoints.mockResolvedValue({ items: [] })
  taxonomyApiMock.subjects.mockResolvedValue({ subjects: [{ subject: '英语', question_count: 2, error_count: 0 }] })
  taxonomyApiMock.tree.mockResolvedValue({ tree: [{ title: '英语', chapters: [] }] })
  errorsApiMock.list.mockResolvedValue({ items: [] })
  goalsApiMock.subjects.mockResolvedValue({ exam_subjects: ['数学', '英语', '政治'], support_subjects: [] })
  wordsApiMock.batchImport.mockResolvedValue({ ok: true, imported: 1 })
})

describe('debug2', () => {
  it('dump home after waitFor', async () => {
    const Quiz = (await import('../v3/pages/Quiz')).default
    render(<MemoryRouter initialEntries={['/quiz']}><Quiz /></MemoryRouter>)
    try {
      await waitFor(() => expect(screen.getByRole('button', { name: /整科练习/ })).toBeInTheDocument(), { timeout: 3000 })
      console.log('FOUND 整科练习')
    } catch (e) {
      console.log('NOT FOUND, current buttons:')
      const btns = screen.getAllByRole('button').map((b) => b.textContent)
      console.log(JSON.stringify(btns))
      const selSubject = document.querySelector('.v3-quiz-know__main h2')?.textContent
      console.log('active h2:', selSubject)
      throw e
    }
  })
})
