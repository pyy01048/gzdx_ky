import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 55号 DeepTutor 升级方案 · 前端配套测试
 *
 * 覆盖：
 * ① client.js 的 recommendApi.weakPoints/variants/masteryGate
 *    与 quizApi.orchestratedTutoring 已导出且签名正确（契约风格）
 * ② QuizResult 渲染「AI 协作讲解」按钮，点击后展示 answer 与四阶段 trace 时间线
 * ③ QuizPractice 评分卡：verification 存在时渲染 verified_score 与维度；
 *    verification 缺失时不报错
 * ④ QuizResult 薄弱点区块渲染 weak-points 列表，点击「生成变式题」
 *    调用 recommendApi.variants 并 toast
 * ------------------------------------------------------------------ */

const QUIZ_QUESTIONS = [
  {
    id: 1,
    content: 'The ubiquitous smartphone has transformed modern life.',
    options: ['ubiquitous', 'rare', 'common', 'invisible'],
    answer: 'A',
    subject: '英语',
    question_type: 'single',
  },
  {
    id: 2,
    content: '请论述微积分在工程中的应用。',
    answer: '微积分是研究变化的数学工具，广泛应用于工程优化与建模。',
    subject: '英语',
    question_type: 'essay',
    answer_type: 'subjective',
  },
]

/* ---- 薄弱点 mock 数据（三信号融合） ---- */
const WEAK_POINTS = [
  { kp_id: 101, name: '不定积分', weak_score: 0.72, sources: ['quiz', 'error'] },
  { kp_id: 102, name: '极限', weak_score: 0.55, sources: ['review'] },
]

const quizApiMock = {
  stats: vi.fn().mockResolvedValue({ total_questions: 0, total_attempts: 0, accuracy_rate: 0, active_errors: 0 }),
  questions: vi.fn(),
  submit: vi.fn().mockResolvedValue({ correct: true, correct_answer: 'A', analysis: '' }),
  papersIndex: vi.fn().mockResolvedValue({ papers: [] }),
  years: vi.fn().mockResolvedValue({ years: [] }),
  subjects: vi.fn().mockResolvedValue({ total: 1, items: [{ subject: '英语', question_count: 2, answerable_count: 2, error_count: 0 }] }),
  extractWords: vi.fn(),
  gradeSubjective: vi.fn(),
  // P1-E 多 Agent 编排答疑
  orchestratedTutoring: vi.fn(),
}
const recommendApiMock = {
  weakPoints: vi.fn(),
  variants: vi.fn(),
  masteryGate: vi.fn(),
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
  recommendApi: recommendApiMock,
  taxonomyApi: taxonomyApiMock,
  errorsApi: errorsApiMock,
  goalsApi: goalsApiMock,
  wordsApi: wordsApiMock,
}))

beforeEach(() => {
  for (const g of [quizApiMock, recommendApiMock, taxonomyApiMock, errorsApiMock, goalsApiMock, wordsApiMock]) {
    for (const fn of Object.values(g)) if (fn?.mockReset) fn.mockReset()
  }
  quizApiMock.stats.mockResolvedValue({ total_questions: 0, total_attempts: 0, accuracy_rate: 0, active_errors: 0 })
  quizApiMock.questions.mockResolvedValue({ questions: QUIZ_QUESTIONS, total: 2, total_count: 2, answerable_count: 2 })
  quizApiMock.submit.mockResolvedValue({ correct: true, correct_answer: 'A', analysis: '' })
  quizApiMock.papersIndex.mockResolvedValue({ papers: [] })
  quizApiMock.years.mockResolvedValue({ years: [] })
  quizApiMock.subjects.mockResolvedValue({ total: 1, items: [{ subject: '英语', question_count: 2, answerable_count: 2, error_count: 0 }] })
  recommendApiMock.weakPoints.mockResolvedValue({ items: WEAK_POINTS })
  recommendApiMock.variants.mockResolvedValue({ created: 3, kp_id: 101 })
  recommendApiMock.masteryGate.mockResolvedValue({ kp_id: 101, passed: true, consecutive_required: 3, current_streak: 3 })
  taxonomyApiMock.subjects.mockResolvedValue({ subjects: [{ subject: '英语', question_count: 2, error_count: 0 }] })
  taxonomyApiMock.tree.mockResolvedValue({ tree: [{ title: '英语', chapters: [] }] })
  errorsApiMock.list.mockResolvedValue({ items: [] })
  goalsApiMock.subjects.mockResolvedValue({ exam_subjects: ['数学', '英语', '政治'], support_subjects: [] })
  wordsApiMock.batchImport.mockResolvedValue({ ok: true, imported: 1 })
})

afterEach(() => { cleanup(); localStorage.clear() })

/* ========================================================================= */
/* 二、QuizResult：多 Agent 协作答疑 + 薄弱点强化                              */
/* ========================================================================= */
async function renderResult() {
  const Quiz = (await import('../v3/pages/Quiz')).default
  const utils = render(<MemoryRouter initialEntries={['/quiz']}><Quiz /></MemoryRouter>)
  // 等待所有异步 useEffect（科目加载 / sourceCounts 探测）settle，DOM 稳定后再点击
  await act(async () => { await new Promise((r) => setTimeout(r, 300)) })
  const startBtn = screen.getByRole('button', { name: /整科练习/ })
  await act(async () => {
    fireEvent.click(startBtn)
    await new Promise((r) => setTimeout(r, 150))
  })
  // 第一题单选：点 B（错误选项）→ 产生错题，结果页才会渲染「智能 AI 讲题」卡片
  const opts = utils.container.querySelectorAll('.v3-quiz-opt')
  if (!opts.length) {
    // eslint-disable-next-line no-console
    console.log('DEBUG questions calls:', JSON.stringify(quizApiMock.questions.mock.calls))
    console.log('DEBUG body:', document.body.textContent.slice(0, 800))
    throw new Error('未找到 .v3-quiz-opt，可能未进入练习')
  }
  fireEvent.click(opts[1]) // 第二个选项 B
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
  // 下一题（文本题）：输入并自评答错，保持错题存在
  fireEvent.click(await screen.findByRole('button', { name: /下一题/ }))
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
  const textarea = screen.getByLabelText('作答输入框')
  fireEvent.change(textarea, { target: { value: '微积分在工程优化中有广泛应用。' } })
  await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
  fireEvent.click(screen.getByRole('button', { name: '对照答案' }))
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
  fireEvent.click(screen.getByRole('button', { name: /我答错了/ }))
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
  // 交卷按钮在答题卡与底部操作区各有一个，取第一个
  const finishBtns = await screen.findAllByRole('button', { name: /交卷并查看报告/ })
  fireEvent.click(finishBtns[0])
  await act(async () => { await new Promise((r) => setTimeout(r, 60)) })
  return utils
}

describe('P1-E 多 Agent 协作答疑（QuizResult）', () => {
  it('展示「AI 协作讲解」按钮，点击后展示 answer 与四阶段 trace 时间线', async () => {
    await renderResult()

    // 协作讲解按钮存在
    const btn = await screen.findByRole('button', { name: 'AI 协作讲解' })
    expect(btn).toBeInTheDocument()

    // mock orchestrated 返回 answer + trace + confidence + degraded
    quizApiMock.orchestratedTutoring.mockResolvedValue({
      answer: '这道题考察微积分基本定理。',
      confidence: 'high',
      degraded: false,
      trace: [
        { stage: 'retrieve', status: 'ok', elapsed_ms: 120, data: { hits: [{ id: 1 }, { id: 2 }] } },
        { stage: 'solve', status: 'ok', elapsed_ms: 340, data: { answer: '微积分基本定理' } },
        { stage: 'verify', status: 'ok', elapsed_ms: 210, data: { verification: { verified_score: 8 } } },
        { stage: 'remedy', status: 'ok', elapsed_ms: 150, data: { suggestions: ['重做例题', '复习定理'] } },
      ],
    })

    fireEvent.click(btn)
    await waitFor(() => expect(quizApiMock.orchestratedTutoring).toHaveBeenCalled())

    // 校验请求体：renderResult 中第一题单选点 B 被判对（submit mock correct:true），
    // 第二题文本题自评「我答错了」→ wrong 列表只有第二题（id=2），
    // 因此第一个「AI 协作讲解」按钮对应 question_id: 2，my_answer 为用户输入的文本
    const [body] = quizApiMock.orchestratedTutoring.mock.calls[0]
    expect(body).toMatchObject({ question_id: 2, my_answer: '微积分在工程优化中有广泛应用。' })

    // answer 展示
    await waitFor(() => expect(screen.getByText(/这道题考察微积分基本定理/)).toBeInTheDocument())
    // confidence 徽标（high → 高置信）
    expect(screen.getByText('高置信')).toBeInTheDocument()
    // 四阶段轨迹时间线
    expect(screen.getByText('retrieve')).toBeInTheDocument()
    expect(screen.getByText('solve')).toBeInTheDocument()
    expect(screen.getByText('verify')).toBeInTheDocument()
    expect(screen.getByText('remedy')).toBeInTheDocument()
    // 阶段 data 摘要
    expect(screen.getByText(/检索命中 2 条/)).toBeInTheDocument()
    expect(screen.getByText(/验证得分 8/)).toBeInTheDocument()
    expect(screen.getByText(/补救建议 2 条/)).toBeInTheDocument()
  })

  it('orchestrated 调用失败时显示错误信息且不影响页面其它功能', async () => {
    await renderResult()

    const btn = await screen.findByRole('button', { name: 'AI 协作讲解' })
    quizApiMock.orchestratedTutoring.mockRejectedValue(new Error('AI 服务暂时不可用'))

    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByText(/AI 服务暂时不可用/)).toBeInTheDocument())
    // 页面其它功能仍在（薄弱点区块正常渲染）
    expect(screen.getByText('薄弱点强化')).toBeInTheDocument()
  })
})

describe('P0-C 薄弱点强化（QuizResult）', () => {
  it('渲染 weak-points 列表，点击「生成变式题」调用 recommendApi.variants 并 toast', async () => {
    await renderResult()

    // 薄弱点列表展示
    await waitFor(() => expect(screen.getByText('不定积分')).toBeInTheDocument())
    expect(screen.getByText('极限')).toBeInTheDocument()
    expect(screen.getByText(/薄弱度 0.72/)).toBeInTheDocument()
    // 来源标签
    expect(screen.getByText('答题信号')).toBeInTheDocument()
    expect(screen.getByText('错题信号')).toBeInTheDocument()

    // 点击「生成变式题」
    fireEvent.click(screen.getAllByRole('button', { name: '生成变式题' })[0])
    await waitFor(() => expect(recommendApiMock.variants).toHaveBeenCalled())
    expect(recommendApiMock.variants).toHaveBeenCalledWith({ kp_id: 101, count: 3 })
    // toast 展示生成数量（toast 通过 createPortal 渲染到 document.body）
    await waitFor(() => {
      expect(document.body.textContent).toContain('已生成 3 道变式题')
    })
  })

  it('点击「掌握门控」调用 recommendApi.masteryGate 并展示通过状态', async () => {
    await renderResult()

    await waitFor(() => expect(screen.getByText('不定积分')).toBeInTheDocument())
    fireEvent.click(screen.getAllByRole('button', { name: '掌握门控' })[0])
    await waitFor(() => expect(recommendApiMock.masteryGate).toHaveBeenCalled())
    expect(recommendApiMock.masteryGate).toHaveBeenCalledWith({ kp_id: 101, consecutive_required: 3 })
    // 通过态展示
    await waitFor(() => expect(screen.getByText(/已连续答对 3 题，达到掌握阈值/)).toBeInTheDocument())
  })

  it('weakPoints 返回空时显示空态，不影响页面其它功能', async () => {
    recommendApiMock.weakPoints.mockResolvedValue({ items: [] })
    await renderResult()

    await waitFor(() => expect(screen.getByText(/暂无薄弱知识点/)).toBeInTheDocument())
    expect(screen.getByText('薄弱点强化')).toBeInTheDocument()
  })
})

/* ========================================================================= */
/* 三、QuizPractice：verification 评分卡                                      */
/* ========================================================================= */
async function renderPractice() {
  const Quiz = (await import('../v3/pages/Quiz')).default
  const utils = render(<MemoryRouter initialEntries={['/quiz']}><Quiz /></MemoryRouter>)
  // 等待所有异步 useEffect（科目加载 / sourceCounts 探测）settle，DOM 稳定后再点击
  await act(async () => { await new Promise((r) => setTimeout(r, 300)) })
  const startBtn = screen.getByRole('button', { name: /整科练习/ })
  await act(async () => {
    fireEvent.click(startBtn)
    await new Promise((r) => setTimeout(r, 150))
  })
  const probe = utils.container.querySelector('.v3-quiz-opt')
  if (!probe) {
    // eslint-disable-next-line no-console
    console.log('DEBUG practice questions calls:', JSON.stringify(quizApiMock.questions.mock.calls))
    console.log('DEBUG body:', document.body.textContent.slice(0, 800))
  }
  return utils
}

describe('P0-B 批改评分卡（QuizPractice）', () => {
  it('verification 存在时渲染 verified_score 与四维评分卡、沙箱验算', async () => {
    const { container } = await renderPractice()

    // 第一题单选判分 → 下一题（文本题）
    const opt = container.querySelector('.v3-quiz-opt')
    expect(opt).toBeTruthy()
    fireEvent.click(opt)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    fireEvent.click(await screen.findByRole('button', { name: /下一题/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    const textarea = screen.getByLabelText('作答输入框')
    fireEvent.change(textarea, { target: { value: '微积分在工程优化中有广泛应用。' } })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    // mock gradeSubjective 返回 verification
    quizApiMock.gradeSubjective.mockResolvedValue({
      question_id: 2,
      score: 8,
      max_score: 10,
      evaluation: '思路清晰。',
      reference_answer: '微积分是研究变化的数学工具。',
      verification: {
        verified_score: 8,
        max_score: 10,
        dimensions: {
          accuracy: { score: 8, comment: '要点覆盖准确' },
          logic: { score: 9, reason: '推理链条完整' },
          format: { score: 7, comment: '书写规范' },
          completeness: { score: 8, reason: '论述完整' },
        },
        sandbox: { verified: true, usable: true, value: 9, expr: '(1+2)*3' },
        summary: '复核后得分与初评一致。',
      },
    })

    fireEvent.click(screen.getByRole('button', { name: 'AI 批改' }))
    await waitFor(() => expect(quizApiMock.gradeSubjective).toHaveBeenCalled())

    // 评分卡头部：复核得分
    await waitFor(() => expect(screen.getByText(/复核得分：8 \/ 10/)).toBeInTheDocument())
    // 验证摘要
    expect(screen.getByText(/复核后得分与初评一致/)).toBeInTheDocument()
    // 四维评分卡（comment 与 reason 两种键名都兼容）
    expect(screen.getByText('准确性')).toBeInTheDocument()
    expect(screen.getByText('逻辑性')).toBeInTheDocument()
    expect(screen.getByText('规范性')).toBeInTheDocument()
    expect(screen.getByText('完整性')).toBeInTheDocument()
    expect(screen.getByText('要点覆盖准确')).toBeInTheDocument()
    expect(screen.getByText('推理链条完整')).toBeInTheDocument()
    // 沙箱验算（文本可能被拆分为多个节点，用函数匹配器）
    await waitFor(() => {
      const found = screen.getAllByText((content, node) => {
        if (!node) return false
        return node.textContent && /沙箱验算通过/.test(node.textContent) && /9/.test(node.textContent)
      })
      expect(found.length).toBeGreaterThan(0)
    })
  })

  it('verification 缺失时不报错、不渲染评分卡', async () => {
    const { container } = await renderPractice()

    const opt = container.querySelector('.v3-quiz-opt')
    expect(opt).toBeTruthy()
    fireEvent.click(opt)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    fireEvent.click(await screen.findByRole('button', { name: /下一题/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    const textarea = screen.getByLabelText('作答输入框')
    fireEvent.change(textarea, { target: { value: '微积分在工程优化中有广泛应用。' } })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    // 不带 verification 的旧响应
    quizApiMock.gradeSubjective.mockResolvedValue({
      question_id: 2,
      score: 7.5,
      max_score: 10,
      evaluation: '思路清晰。',
      reference_answer: '微积分是研究变化的数学工具。',
    })

    fireEvent.click(screen.getByRole('button', { name: 'AI 批改' }))
    await waitFor(() => expect(quizApiMock.gradeSubjective).toHaveBeenCalled())

    // 原有 evaluation 正常展示，评分卡不渲染
    await waitFor(() => expect(screen.getAllByText('思路清晰。').length).toBeGreaterThan(0))
    expect(screen.queryByText('批改评分卡')).not.toBeInTheDocument()
  })

  it('verification 降级（dimensions 为空对象）时不渲染评分卡，不报错', async () => {
    const { container } = await renderPractice()

    const opt = container.querySelector('.v3-quiz-opt')
    expect(opt).toBeTruthy()
    fireEvent.click(opt)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    fireEvent.click(await screen.findByRole('button', { name: /下一题/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    const textarea = screen.getByLabelText('作答输入框')
    fireEvent.change(textarea, { target: { value: '微积分在工程优化中有广泛应用。' } })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    quizApiMock.gradeSubjective.mockResolvedValue({
      question_id: 2,
      score: 8,
      max_score: 10,
      evaluation: '思路清晰。',
      reference_answer: '微积分是研究变化的数学工具。',
      verification: { verified_score: null, dimensions: {}, sandbox: null, summary: '' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'AI 批改' }))
    await waitFor(() => expect(quizApiMock.gradeSubjective).toHaveBeenCalled())
    await waitFor(() => expect(screen.getAllByText('思路清晰。').length).toBeGreaterThan(0))
    expect(screen.queryByText('批改评分卡')).not.toBeInTheDocument()
  })
})