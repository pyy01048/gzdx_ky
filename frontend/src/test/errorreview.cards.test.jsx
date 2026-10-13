import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, act, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 错题本 / 记忆卡片对接整改回归（docx/22 F2/F3）
 *
 * 锁死四件事：
 *  1. 错题学科筛选**来自科目 API**，且只列"有错题的科目"（error_count>0）；
 *  2. 掌握度是后端下发的**三态**（未学/薄弱/已掌握），筛选走后端 mastery_state；
 *  3. 知识点关联按**实际链路**展示（题目关联 question_link 优先、标"已校验"）；
 *  4. 记忆卡片能正确解析后端 {items:[...]}，科目下拉来自 API（无硬编码科目）。
 * ------------------------------------------------------------------ */

vi.mock('../api/client', () => {
  const errorsApi = {
    list: vi.fn(() => Promise.resolve({
      total: 1,
      page: 1,
      total_pages: 1,
      items: [{
        id: 11, question_id: 1869, content: '构成一个 7 进制计数器需要几个触发器',
        my_answer: 'A', correct_answer: 'C', error_reason: '概念不清',
        subject: '数字电子技术', accuracy: 0.0, review_count: 0,
        last_review: null, next_review: '2026-10-08T09:12:34',
        status: 'active', mastery_state: 'unlearned', mastery_label: '未学',
        tags: [], analysis: null, created_at: '2026-10-01T00:00:00',
      }],
    })),
    stats: vi.fn(() => Promise.resolve({
      total: 39, active_errors: 38, due_errors: 38, graduated_errors: 1,
      unlearned: 34, weak: 4, mastered: 1,
      labels: { unlearned: '未学', weak: '薄弱', mastered: '已掌握' },
    })),
    knowledgePoints: vi.fn(() => Promise.resolve({
      error_id: 11,
      items: [
        {
          link_id: null, knowledge_point_id: 110, name: '计数器', subject: '数字电子技术',
          chapter: '第6章 时序逻辑电路', mastery: 0, state: 'weak', state_label: '薄弱',
          relevance: 1.0, source: 'question_link', role: 'primary', verified: true,
        },
        {
          link_id: 64, knowledge_point_id: 111, name: '进制', subject: '数字电子技术',
          chapter: '第1章', mastery: 0, state: 'weak', state_label: '薄弱',
          relevance: 0.5, source: 'keyword_match', role: null, verified: false,
        },
      ],
    })),
    linkKnowledge: vi.fn(() => Promise.resolve({ id: 1 })),
    unlinkKnowledge: vi.fn(() => Promise.resolve({ message: 'ok' })),
    aiAnalyze: vi.fn(() => Promise.resolve({ analysis: 'x' })),
    update: vi.fn(() => Promise.resolve({})),
    create: vi.fn(() => Promise.resolve({})),
    remove: vi.fn(() => Promise.resolve({})),
    ocr: vi.fn(() => Promise.resolve({})),
    graduate: vi.fn(() => Promise.resolve({})),
  }

  const taxonomyApi = {
    subjects: vi.fn(() => Promise.resolve({
      subjects: [
        { subject: '数字电子技术', error_count: 37, question_count: 3608, chapters: [], question_types: [], is_custom: false, unregistered: false },
        { subject: '数学', error_count: 1, question_count: 100, chapters: [], question_types: [], is_custom: false, unregistered: false },
        { subject: '英语', error_count: 0, question_count: 500, chapters: [], question_types: [], is_custom: false, unregistered: false },
      ],
    })),
    knowledgePoints: vi.fn(() => Promise.resolve({
      total: 2,
      items: [
        { id: 110, name: '计数器', subject: '数字电子技术', chapter: '第6章 时序逻辑电路' },
        { id: 111, name: '触发器', subject: '数字电子技术', chapter: '第6章 时序逻辑电路' },
      ],
    })),
  }

  const quizApi = { wrongReasons: vi.fn(() => Promise.resolve({ total: 0, items: [] })) }

  const flashcardsApi = {
    list: vi.fn(() => Promise.resolve({
      total: 2, page: 1, page_size: 500, total_pages: 1,
      items: [
        { id: 1, front: '正面A', back: '背面A', knowledge_point_id: 110, next_review: '2026-10-01T00:00:00', review_count: 2, interval: 3, ease_factor: 2.6, mastery: 'review' },
        { id: 2, front: '正面B', back: '背面B', knowledge_point_id: null, next_review: null, review_count: 0, interval: 1, ease_factor: 2.5, mastery: 'new' },
      ],
    })),
    create: vi.fn(() => Promise.resolve({})),
    review: vi.fn(() => Promise.resolve({})),
    remove: vi.fn(() => Promise.resolve({})),
  }

  return {
    request: vi.fn(() => Promise.resolve(null)),
    DEFAULT_TIMEOUT: 30000,
    ApiError: class ApiError extends Error {},
    fileUrl: (p) => p,
    errorsApi, taxonomyApi, quizApi, flashcardsApi,
  }
})

import { errorsApi, taxonomyApi, flashcardsApi } from '../api/client'
import useStore from '../store/useStore'

function Wrapper({ children, route = '/' }) {
  return <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
}

async function settle(ms = 250) {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}

beforeEach(() => {
  vi.clearAllMocks()
  useStore.setState({ cards: [], packs: [], notebook: [] })
  localStorage.clear()
})

afterEach(() => { cleanup(); localStorage.clear() })

/* ============================ 错题复盘 ============================ */
describe('ErrorReview：学科来自 API、掌握度三态、知识点按实际链路', () => {
  it('学科筛选只列有错题的科目（英语 error_count=0 不出现）', async () => {
    const ErrorReview = (await import('../pages/ErrorReview')).default
    render(<Wrapper route="/error-review"><ErrorReview /></Wrapper>)
    await settle()

    // 学科条里出现"数字电子技术"（37 题）与"数学"（1 题）
    const subjFilter = screen.getByRole('group', { name: '学科筛选' })
    expect(within(subjFilter).getByRole('button', { name: /数字电子技术/ })).toBeInTheDocument()
    expect(within(subjFilter).getByRole('button', { name: /^数学/ })).toBeInTheDocument()
    // 0 错题的科目不得出现
    expect(within(subjFilter).queryByRole('button', { name: /英语/ })).toBeNull()
  })

  it('掌握度是三态（未学/薄弱/已掌握），点击后按 mastery_state 请求后端', async () => {
    const ErrorReview = (await import('../pages/ErrorReview')).default
    render(<Wrapper route="/error-review"><ErrorReview /></Wrapper>)
    await settle()

    const masteryFilter = screen.getByRole('group', { name: '掌握度筛选' })
    const weakChip = within(masteryFilter).getByRole('button', { name: /薄弱/ })
    expect(within(masteryFilter).getByRole('button', { name: /未学/ })).toBeInTheDocument()
    expect(within(masteryFilter).getByRole('button', { name: /已掌握/ })).toBeInTheDocument()

    fireEvent.click(weakChip)
    await settle()

    expect(errorsApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ mastery_state: 'weak' })
    )
  })

  it('知识点关联展示实际链路：题目关联优先且标"已校验"，启发式标"自动"', async () => {
    const ErrorReview = (await import('../pages/ErrorReview')).default
    render(<Wrapper route="/error-review"><ErrorReview /></Wrapper>)
    await settle()

    // 权威链路
    expect(await screen.findByText('计数器')).toBeInTheDocument()
    expect(screen.getByText('已校验')).toBeInTheDocument()
    // "题目关联" 在说明文案里也出现，故用 AllBy 断言存在
    expect(screen.getAllByText(/题目关联/).length).toBeGreaterThan(0)
    // 启发式链路如实标注，不冒充权威
    expect(screen.getByText(/自动·关键词命中/)).toBeInTheDocument()
    // question_link 没有 link_id → 不可解除，显示"题目侧"
    expect(screen.getByText('题目侧')).toBeInTheDocument()
  })
})

/* ============================ 记忆卡片 ============================ */
describe('Cards：正确解析后端 {items}、科目下拉来自 API', () => {
  it('卡片总数 = 后端 items.length（不再把 {items} 当数组用）', async () => {
    const Cards = (await import('../pages/Cards')).default
    render(<Wrapper route="/cards"><Cards /></Wrapper>)
    await settle()

    // 卡片总数 tile 值应为 2（后端 items 长度）
    expect(screen.getByText('卡片总数')).toBeInTheDocument()
    const tiles = screen.getAllByText('2')
    expect(tiles.length).toBeGreaterThan(0)
  })

  /* 回归核心：此前这一路径是**白屏**——flashcardsApi.list 返回 {items:[...]}
     却被当裸数组用（cards.filter is not a function），且 setCards 在 store 里
     根本不存在（调用即抛 TypeError 被 catch 吞掉）→ 后端 649 张卡永远加载不出来。 */
  it('加载成功路径：{items} 写入 store 且卡片真的渲染出来（不再是白屏）', async () => {
    const Cards = (await import('../pages/Cards')).default
    render(<Wrapper route="/cards"><Cards /></Wrapper>)
    await settle()

    // 1) store 里的 cards 被正式 setCards 正确写入（长度 + 字段映射）
    const stored = useStore.getState().cards
    expect(stored).toHaveLength(2)
    expect(stored.map((c) => c.id)).toEqual([1, 2])
    expect(stored[0].reps).toBe(2)                      // review_count → reps
    expect(stored[0].status).toBe('reviewing')          // mastery 'review' → reviewing
    expect(stored[1].status).toBe('new')                // mastery 'new' → new

    // 2) 切到「列表」视图，正反面文本真的渲染（曾经整页白屏 / 只有空态）
    fireEvent.click(screen.getByRole('button', { name: /列表/ }))
    await settle()
    expect(screen.getByText('正面A')).toBeInTheDocument()
    expect(screen.getByText('正面B')).toBeInTheDocument()
  })

  it('新建卡包科目下拉来自科目 API，且不含硬编码的"专业课"', async () => {
    const Cards = (await import('../pages/Cards')).default
    render(<Wrapper route="/cards"><Cards /></Wrapper>)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: '新建卡包' }))
    await settle()

    expect(screen.getByRole('option', { name: '数字电子技术' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '数学' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '专业课' })).toBeNull()
  })
})
