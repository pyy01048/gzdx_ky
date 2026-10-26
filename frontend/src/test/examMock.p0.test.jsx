import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * ExamMock 模考中心 P0 功能回归测试
 *
 * 覆盖主链路：
 *   ① 发起视图：加载 blueprints → 按科目分组展示 → 点击「开始模考」
 *   ② 配置弹窗：选择模式 → 点击「开始模考」→ examApi.build 被调用
 *   ③ 答题视图：选择题点击选项 → 主观题输入 → 交卷 → examApi.submit 被调用
 *   ④ 报告视图：展示 overview 得分 / 薄弱知识点 / 错题回顾
 *   ⑤ 历史记录：sessions 列表渲染 + 查看报告
 * ------------------------------------------------------------------ */

const BLUEPRINTS = [
  {
    id: 1,
    subject: '数学',
    paper: '2024 数学一',
    year: 2024,
    section: '高数',
    question_type: 'single',
    count: 3,
    score_per_question: 5,
    sort_order: 1,
    is_active: true,
  },
  {
    id: 2,
    subject: '英语',
    paper: '2024 英语一',
    year: 2024,
    section: '阅读',
    question_type: 'single',
    count: 2,
    score_per_question: 2,
    sort_order: 1,
    is_active: true,
  },
]

const BUILT_SESSION = {
  session_id: 'sess-101',
  blueprint_key: 'math-2024',
  subject: '数学',
  paper: '2024 数学一',
  mode: 'normal',
  total_count: 3,
  total_score: 15,
  status: 'ongoing',
  expires_at: new Date(Date.now() + 3600 * 1000).toISOString(),
  time_limit_minutes: 60,
  sections: [
    {
      title: '高数',
      questions: [
        {
          id: 'q1',
          content: '极限 lim(x→0) sinx/x = ?',
          options: ['0', '1', '∞', '不存在'],
          question_type: 'single',
          subject: '数学',
          answer: 'B',
          score_per_question: 5,
        },
        {
          id: 'q2',
          content: '微分方程 y\' = y 的通解是？',
          options: ['y = Ce^x', 'y = x^2', 'y = sinx', 'y = 1/x'],
          question_type: 'single',
          subject: '数学',
          answer: 'A',
          score_per_question: 5,
        },
        {
          id: 'q3',
          content: '请简述中值定理在工程中的应用。',
          question_type: 'essay',
          subject: '数学',
          answer: '中值定理用于估计函数变化。',
          score_per_question: 5,
        },
      ],
    },
  ],
}

const SESSIONS = [
  {
    id: 'sess-101',
    blueprint_key: 'math-2024',
    subject: '数学',
    paper: '2024 数学一',
    mode: 'normal',
    total_count: 3,
    total_score: 15,
    correct_count: 2,
    score: 10,
    status: 'submitted',
    started_at: '2026-10-20T10:00:00Z',
    submitted_at: '2026-10-20T10:45:00Z',
    expires_at: '2026-10-20T11:00:00Z',
    report_available: true,
    max_score: 15,
    earned_score: 10,
  },
]

const REPORT = {
  overview: {
    session_id: 'sess-101',
    total_count: 3,
    correct_count: 2,
    wrong_count: 1,
    max_score: 15,
    earned_score: 10,
    score: 10,
    accuracy: 66.7,
    duration_minutes: 45,
  },
  section_scores: [
    { title: '高数', earned_score: 10, max_score: 15 },
  ],
  knowledge_weakness: [
    { name: '中值定理', error_count: 1 },
  ],
  time_analysis: {
    total_minutes: 45,
    per_question_avg_seconds: 900,
  },
  wrong_questions: [
    {
      question_id: 'q3',
      content: '请简述中值定理在工程中的应用。',
      user_answer: '中值定理用于估计函数变化。',
      correct_answer: '中值定理用于估计函数变化。',
      analysis: '中值定理是微分学核心定理。',
      knowledge_point: '中值定理',
    },
  ],
}

const examApiMock = {
  blueprints: vi.fn(),
  build: vi.fn(),
  sessions: vi.fn(),
  session: vi.fn(),
  report: vi.fn(),
  submit: vi.fn(),
}

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  request: vi.fn().mockResolvedValue({}),
  DEFAULT_TIMEOUT: 30000,
  examApi: examApiMock,
}))

beforeEach(() => {
  for (const fn of Object.values(examApiMock)) if (fn?.mockReset) fn.mockReset()
  examApiMock.blueprints.mockResolvedValue(BLUEPRINTS)
  examApiMock.build.mockResolvedValue(BUILT_SESSION)
  examApiMock.sessions.mockResolvedValue(SESSIONS)
  examApiMock.report.mockResolvedValue(REPORT)
  examApiMock.submit.mockResolvedValue({
    session_id: 'sess-101',
    status: 'submitted',
    correct_count: 2,
    score: 10,
    stats_count: 3,
    total_count: 3,
    wrong_count: 1,
    ai_unverified_count: 1,
    scored_at: '2026-10-20T10:45:00Z',
  })
})

afterEach(() => { cleanup(); localStorage.clear() })

async function renderMock() {
  const ExamMock = (await import('../v3/pages/ExamMock')).default
  const utils = render(
    <MemoryRouter initialEntries={['/exam-mock']}>
      <ExamMock />
    </MemoryRouter>,
  )
  // 等待蓝图加载完成
  await act(async () => { await new Promise((r) => setTimeout(r, 80)) })
  return utils
}

describe('模考中心：发起 → 答题 → 交卷 → 报告 主链路', () => {
  it('加载蓝图并按科目分组展示，点击「开始模考」弹出配置', async () => {
    const { container } = await renderMock()

    // 两个科目分组标题
    expect(await screen.findByText('数学', { selector: 'h3' })).toBeInTheDocument()
    expect(screen.getByText('英语', { selector: 'h3' })).toBeInTheDocument()
    // 蓝图卡展示试卷名
    expect(screen.getByText('2024 数学一')).toBeInTheDocument()
    expect(screen.getByText('2024 英语一')).toBeInTheDocument()

    // 点击「开始模考」弹出配置弹窗
    const startButtons = screen.getAllByRole('button', { name: /开始模考/ })
    expect(startButtons.length).toBeGreaterThan(0)
    fireEvent.click(startButtons[0])
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

    // 弹窗出现，展示三种模式
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('标准模考')).toBeInTheDocument()
    expect(screen.getByText('薄弱优先')).toBeInTheDocument()
    expect(screen.getByText('随机抽题')).toBeInTheDocument()

    // 选择「薄弱优先」模式
    fireEvent.click(screen.getByText('薄弱优先'))
    // 点击「开始模考」按钮（弹窗 footer 中的）
    const confirmBtn = screen.getAllByRole('button', { name: /开始模考/ })
      .find((b) => b.closest('.v3-dialog__foot'))
    expect(confirmBtn).toBeTruthy()
    fireEvent.click(confirmBtn)

    // build 被调用，参数含 subject/mode
    await waitFor(() => expect(examApiMock.build).toHaveBeenCalledTimes(1))
    const [body] = examApiMock.build.mock.calls[0]
    expect(body.subject).toBe('数学')
    expect(body.mode).toBe('weakest')
    expect(body.question_source).toBe('all')
    expect(body.exclude_recent_days).toBe(14)

    // 进入答题视图
    expect(await screen.findByText(/模考中/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(container.querySelector('.exam-mock-timer')).toBeTruthy()
  })

  it('答题：选择题点击选项、主观题输入、交卷后调用 submit 并展示报告', async () => {
    const { container } = await renderMock()

    // 发起模考（标准模式）
    fireEvent.click(screen.getAllByRole('button', { name: /开始模考/ })[0])
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    fireEvent.click(screen.getAllByRole('button', { name: /开始模考/ })
      .find((b) => b.closest('.v3-dialog__foot')))

    await waitFor(() => expect(screen.getByText(/模考中/, {}, { timeout: 3000 })).toBeInTheDocument())

    // 第 1 题：选择题，点击选项 B（1）
    const opts = container.querySelectorAll('.exam-mock-opt')
    expect(opts.length).toBeGreaterThan(0)
    fireEvent.click(opts[1])
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    // 下一题
    fireEvent.click(screen.getByRole('button', { name: /下一题/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    // 第 2 题：选择题，点击选项 A
    const opts2 = container.querySelectorAll('.exam-mock-opt')
    expect(opts2.length).toBeGreaterThan(0)
    fireEvent.click(opts2[0])
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    // 下一题 → 第 3 题：主观题 textarea
    fireEvent.click(screen.getByRole('button', { name: /下一题/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    const textarea = screen.getByLabelText('作答输入框')
    expect(textarea).toBeInTheDocument()
    fireEvent.change(textarea, { target: { value: '中值定理用于估计函数变化。' } })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    // 交卷
    const submitBtn = screen.getByRole('button', { name: '交卷' })
    expect(submitBtn).toBeInTheDocument()
    fireEvent.click(submitBtn)

    // 无未答时直接调 submit（无 window.confirm 弹窗，全部已答）
    await waitFor(() => expect(examApiMock.submit).toHaveBeenCalledTimes(1), { timeout: 3000 })
    const [sid, payload] = examApiMock.submit.mock.calls[0]
    expect(sid).toBe('sess-101')
    expect(payload.answers).toHaveLength(3)
    // 选择题答案用字母，主观题用文本
    expect(payload.answers[0].user_answer).toBe('B')
    expect(payload.answers[1].user_answer).toBe('A')
    expect(payload.answers[2].user_answer).toBe('中值定理用于估计函数变化。')

    // 进入报告视图
    await waitFor(() => expect(screen.getByText('考后报告', {}, { timeout: 3000 })).toBeInTheDocument())

    // 报告展示得分（可能出现在总览和分题型得分中，至少一处即可）
    const scoreTexts = await screen.findAllByText(/10\s*\/\s*15/, {}, { timeout: 3000 })
    expect(scoreTexts.length).toBeGreaterThan(0)
    // 薄弱知识点
    expect(screen.getByText('中值定理')).toBeInTheDocument()
    expect(screen.getByText(/错 1 次/)).toBeInTheDocument()
    // 错题回顾
    expect(screen.getByText('错题回顾')).toBeInTheDocument()
  })
})

describe('模考中心：历史记录', () => {
  it('历史视图展示会话列表，点击「查看报告」进入报告', async () => {
    const { container } = await renderMock()

    // 切到历史记录
    fireEvent.click(screen.getByRole('tab', { name: /历史记录/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 80)) })

    expect(examApiMock.sessions).toHaveBeenCalled()
    // 会话卡片
    expect(await screen.findByText('2024 数学一', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(container.querySelector('.exam-mock-history-card')).toBeTruthy()

    // 查看报告
    fireEvent.click(screen.getByRole('button', { name: /查看报告/ }))
    await act(async () => { await new Promise((r) => setTimeout(r, 80)) })

    expect(examApiMock.report).toHaveBeenCalledWith('sess-101')
    expect(await screen.findByText('考后报告', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('错题回顾')).toBeInTheDocument()
  })
})