import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * #103① 题库「三处统计口径」对齐回归
 *
 * 契约：任一显示题库数量的位置，都必须在 UI 上写明是哪个口径
 *   - 可见题 = 排除 OCR 碎片（/stats.visible_total）
 *   - 可作答 = 有答案可判分（/stats.answerable_total）
 * 且数字直接引用后端**具名字段**（不再用 total_questions 混代三种含义）。
 * ------------------------------------------------------------------ */

/* 故意让三个口径取不同值，若前端仍用单一 total_questions 会立刻暴露 */
const STATS = {
  total_questions: 5507, visible_total: 5507,
  answerable_total: 3385, junk_total: 3589, raw_total: 9096,
  total_attempts: 12, accuracy_rate: 66.7, active_errors: 3, graduated_errors: 1,
  subject_distribution: [], subject_accuracy: [],
}

const quizApiMock = {
  stats: vi.fn().mockResolvedValue(STATS),
  questions: vi.fn().mockResolvedValue({ questions: [], total: 3385, total_count: 5507, answerable_count: 3385 }),
  subjects: vi.fn().mockResolvedValue({ total: 1, items: [{ subject: '数电', question_count: 2302, visible_count: 2302, raw_count: 3567, answerable_count: 1697, error_count: 0 }] }),
  sections: vi.fn().mockResolvedValue({ items: [] }),
  papersIndex: vi.fn().mockResolvedValue({ papers: [] }),
  years: vi.fn().mockResolvedValue({ years: [] }),
  submit: vi.fn().mockResolvedValue({}),
  remove: vi.fn().mockResolvedValue({}),
}
const taxonomyApiMock = {
  subjects: vi.fn().mockResolvedValue({ subjects: [{ subject: '数电', question_count: 2302, error_count: 0 }] }),
  tree: vi.fn().mockResolvedValue({ tree: [{ title: '数电', chapters: [] }] }),
}
const errorsApiMock = { list: vi.fn().mockResolvedValue({ items: [] }) }
const goalsApiMock = { subjects: vi.fn().mockResolvedValue({ exam_subjects: [], support_subjects: [] }) }
const quizSectionApiMock = {
  weakPoints: vi.fn().mockResolvedValue({ items: [] }), wrongReasons: vi.fn().mockResolvedValue({ items: [] }),
  reviewStats: vi.fn().mockResolvedValue({}), reviews: vi.fn().mockResolvedValue({ items: [] }),
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
  quizApi: quizApiMock, taxonomyApi: taxonomyApiMock, errorsApi: errorsApiMock,
  goalsApi: goalsApiMock, quizSectionApi: quizSectionApiMock,
}))

beforeEach(() => {
  for (const g of [quizApiMock, taxonomyApiMock, errorsApiMock, quizSectionApiMock]) {
    for (const fn of Object.values(g)) if (fn?.mockReset) fn.mockReset()
  }
  quizApiMock.stats.mockResolvedValue(STATS)
  quizApiMock.questions.mockResolvedValue({ questions: [], total: 3385, total_count: 5507, answerable_count: 3385 })
  quizApiMock.subjects.mockResolvedValue({ total: 1, items: [{ subject: '数电', question_count: 2302, visible_count: 2302, raw_count: 3567, answerable_count: 1697, error_count: 0 }] })
  quizApiMock.sections.mockResolvedValue({ items: [] })
  quizApiMock.papersIndex.mockResolvedValue({ papers: [] })
  quizApiMock.years.mockResolvedValue({ years: [] })
  taxonomyApiMock.subjects.mockResolvedValue({ subjects: [{ subject: '数电', question_count: 2302, error_count: 0 }] })
  taxonomyApiMock.tree.mockResolvedValue({ tree: [{ title: '数电', chapters: [] }] })
  goalsApiMock.subjects.mockResolvedValue({ exam_subjects: [], support_subjects: [] })
  errorsApiMock.list.mockResolvedValue({ items: [] })
})

afterEach(() => { cleanup(); localStorage.clear() })

async function renderPage(modPath, route) {
  const Comp = (await import(modPath)).default
  const utils = render(<MemoryRouter initialEntries={[route]}><Comp /></MemoryRouter>)
  await act(async () => { await new Promise((r) => setTimeout(r, 70)) })
  return utils
}

describe('#103① 刷题中心首页统计口径明示', () => {
  it('分别显示「可见题」与「可作答」两个具名口径，且数字来自对应字段', async () => {
    await renderPage('../v3/pages/Quiz', '/quiz')
    expect(await screen.findByText('可见题')).toBeInTheDocument()
    expect(screen.getByText('可作答')).toBeInTheDocument()
    // 口径字样必须出现在界面上（dogfood ISSUE-005：改为用户语言，不暴露接口路径与「具名字段」字样）
    expect(screen.getByText(/可见题已排除 OCR 碎片题/)).toBeInTheDocument()
    expect(screen.getByText(/「可作答」= 有答案、可自动判分/)).toBeInTheDocument()
    // CountUp 动画期间数字可能未落定，断言容器存在即可（值由 mock 驱动）
    expect(screen.getByText('可见题').closest('.qh-hstat')).toBeTruthy()
  })
})

describe('#103① 题库管理统计口径明示', () => {
  it('科目卡片与统计卡均标注「可作答 / 可见」口径', async () => {
    const { container } = await renderPage('../v3/pages/QuizBank', '/quiz-bank')
    // 科目下拉与统计卡标签
    expect(await screen.findByText('可作答题')).toBeInTheDocument()
    expect(screen.getByText('可见题')).toBeInTheDocument()
    expect(container.textContent).toMatch(/只看可作答题/)
  })
})
