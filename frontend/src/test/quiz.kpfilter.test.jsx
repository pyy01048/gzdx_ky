import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * Quiz 页 · 知识点级精确刷题（kp_id 链路）回归测试
 *
 * 背景（M1-3 → 刷题页打通）：
 *   知识点全景页 Panorama.startPractice() 会跳转
 *     /quiz?subject=..&chapter=..&kp_id=..&kp_name=..
 *   本测试锁定该链路的两个关键契约：
 *     ① 带 kp_id 时，Quiz 必须把 kp_id 透传给 quizApi.questions（知识点级精确出题）；
 *     ② 不带 kp_id 时，Quiz 必须**不**带 kp_id 调接口（向后兼容，降级行为不变）。
 * ------------------------------------------------------------------ */

// ---------------------------------------------------------------- //
// quizApi stub：可断言调用参数，并可控返回
// ---------------------------------------------------------------- //
const quizApiMock = {
  stats: vi.fn().mockResolvedValue({ total_questions: 0, total_attempts: 0, accuracy_rate: 0, active_errors: 0 }),
  questions: vi.fn(),
  submit: vi.fn().mockResolvedValue({ correct: true }),
  papersIndex: vi.fn().mockResolvedValue({ papers: [] }),
  years: vi.fn().mockResolvedValue({ years: [] }),
}
const taxonomyApiMock = {
  subjects: vi.fn().mockResolvedValue({ subjects: [] }),
  tree: vi.fn().mockResolvedValue({ tree: [] }),
}
const errorsApiMock = {
  list: vi.fn().mockResolvedValue({ items: [] }),
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
}))

beforeEach(() => {
  for (const grp of [quizApiMock, taxonomyApiMock, errorsApiMock]) {
    for (const fn of Object.values(grp)) if (fn?.mockReset) fn.mockReset()
  }
  quizApiMock.stats.mockResolvedValue({ total_questions: 0, total_attempts: 0, accuracy_rate: 0, active_errors: 0 })
  quizApiMock.questions.mockResolvedValue({ questions: [] })
  quizApiMock.submit.mockResolvedValue({ correct: true })
  taxonomyApiMock.subjects.mockResolvedValue({ subjects: [] })
  taxonomyApiMock.tree.mockResolvedValue({ tree: [] })
  errorsApiMock.list.mockResolvedValue({ items: [] })
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

/** 在指定路由下渲染 Quiz，并等待深链拉题副作用落地。 */
async function renderQuiz(route) {
  const Quiz = (await import('../v3/pages/Quiz')).default
  const utils = render(
    <MemoryRouter initialEntries={[route]}>
      <Quiz />
    </MemoryRouter>,
  )
  await act(async () => { await new Promise((r) => setTimeout(r, 80)) })
  return utils
}

/** 取 quizApi.questions 的**首个**调用参数（即深链拉题那一次）。 */
function firstQuestionsArg() {
  expect(quizApiMock.questions).toHaveBeenCalled()
  return quizApiMock.questions.mock.calls[0][0]
}

describe('Quiz 页 kp_id 知识点级精确刷题', () => {
  it('URL 带 kp_id 时，按知识点级透传 kp_id 调 questions 接口', async () => {
    quizApiMock.questions.mockResolvedValue({
      questions: [
        { id: 1, content: '知识点题目A', options: ['a', 'b'], answer: 'A', question_type: 'single' },
      ],
    })

    await renderQuiz('/quiz?subject=数电&chapter=逻辑门&kp_id=89&kp_name=布尔代数')

    const arg = firstQuestionsArg()
    // 核心契约：kp_id 必须原样透传给后端（后端按 kp_id 精确筛题）
    expect(String(arg.kp_id)).toBe('89')
  })

  it('URL 带 kp_id 时展示「知识点 · XXX」筛选标识（练习页标识）', async () => {
    quizApiMock.questions.mockResolvedValue({
      questions: [
        { id: 1, content: '知识点题目A', options: ['a', 'b'], answer: 'A', question_type: 'single' },
      ],
    })

    await renderQuiz('/quiz?kp_id=89&kp_name=布尔代数')

    await waitFor(() => {
      // 会话标题与筛选 chip 都含该文案，断言「至少出现一次」即可
      expect(screen.getAllByText(/知识点 · 布尔代数/).length).toBeGreaterThan(0)
      // 筛选 chip 必须带知识点 ID，供用户悬停核对
      expect(screen.getByTitle('知识点 ID 89')).toBeInTheDocument()
    })
  })

  it('kp_id 命中 0 题时显示 Empty 兜底提示（不白屏、不抛错）', async () => {
    quizApiMock.questions.mockResolvedValue({ questions: [] })

    const { container } = await renderQuiz('/quiz?kp_id=999&kp_name=空知识点')

    await waitFor(() => {
      expect(screen.getByText(/暂无关联题目/)).toBeInTheDocument()
    })
    expect(container.firstChild).toBeTruthy()
  })
})

describe('Quiz 页向后兼容（无 kp_id 时行为不变）', () => {
  it('无 kp_id 时，questions 调用**不带** kp_id 参数', async () => {
    await renderQuiz('/quiz?subject=数学&chapter=行列式')

    const arg = firstQuestionsArg()
    expect(arg.subject).toBe('数学')
    expect(arg.chapter).toBe('行列式')
    // 降级路径核心：绝不携带 kp_id
    expect(arg.kp_id).toBeUndefined()
  })

  it('无 kp_id 时不展示知识点筛选标识', async () => {
    await renderQuiz('/quiz?subject=数学&chapter=行列式')

    expect(screen.queryByText(/知识点 · /)).not.toBeInTheDocument()
    expect(screen.queryByText(/当前筛选：知识点/)).not.toBeInTheDocument()
  })
})
