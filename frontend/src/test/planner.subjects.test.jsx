import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 学习计划表的科目行 = 配置科目 ∪ 存量计划里的历史科目
 *
 * 两件事必须同时成立：
 *   ① 科目来自 /api/goals/subjects（新增科目不用改代码）；
 *   ② 存量 tasks 里的历史键（如"专一"）必须继续渲染 —— 后端 tasks 是自由 JSON，
 *      少渲染一行就等于用户已写的任务看不见，再点保存就被整体覆盖掉。
 * 另外锁住字符串型任务值的处理：库里存的是 "教材精读 + 课后题" 整串，
 * 若按字符下标拆成 4 格，用户改一格保存后整条任务就只剩一个字。
 * ------------------------------------------------------------------ */

const apiMocks = vi.hoisted(() => ({
  getDaily: vi.fn(),
  subjects: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => ({
  // 派生真实模块的导出清单：client.js 新增导出（如 fetchAllPages）不必再回来补枚举，
  // 否则页面一 import 就报 "No export is defined on the mock"。
  ...(await importOriginal()),
  favoritesApi: {
    list: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    add: vi.fn().mockResolvedValue({ ok: true, id: 1 }),
    check: vi.fn().mockResolvedValue({ favorited: false, id: null }),
    toggle: vi.fn().mockResolvedValue({ favorited: false }),
    remove: vi.fn().mockResolvedValue({ ok: true }),
  },
  growthApi: { timeline: vi.fn().mockResolvedValue({ days: 30, streak_days: 0, active_days: 0, timeline: [], subject_breakdown: [] }) },
  plannerApi: {
    getDaily: apiMocks.getDaily,
    saveDaily: vi.fn(),
    listEbbinghaus: vi.fn().mockResolvedValue([]),
    listEarlyBird: vi.fn().mockResolvedValue([]),
    listPhase: vi.fn().mockResolvedValue([]),
    getPhaseReviews: vi.fn().mockResolvedValue([]),
  },
  goalsApi: { subjects: apiMocks.subjects },
}))

import Planner from '../v3/pages/Planner'

const SUBJECTS = ['数字电子技术', '模拟电子技术', '数学', '专一']

function renderPlanner() {
  return render(
    <MemoryRouter initialEntries={['/planner']}>
      <Planner />
    </MemoryRouter>
  )
}

describe('Planner 日计划科目行', () => {
  beforeEach(() => {
    cleanup()
    apiMocks.getDaily.mockReset()
    apiMocks.subjects.mockReset()
    apiMocks.subjects.mockResolvedValue({
      exam_subjects: ['数字电子技术', '模拟电子技术', '数学'],
      support_subjects: [],
      all_known: SUBJECTS,
      using_default: false,
    })
    apiMocks.getDaily.mockResolvedValue({
      exists: true,
      days_to_exam: 400,
      tasks: {
        数字电子技术: '教材精读 + 课后题',
        数学: ['章节习题', '', '', ''],
        专一: '834 冲刺卷',
      },
      timeline: [],
      score: 0,
      summary: '',
    })
  })

  it('历史 {科目: 任务} 结构迁移为任务列表，字符串任务不拆成单字', async () => {
    renderPlanner()

    // V2 计划表已改为「任务列表」：旧版 {科目: 字符串/数组} 会迁移成独立任务，
    // 科目以完整名称显示（不再缩写成"数电"）。
    expect((await screen.findAllByText('数字电子技术')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('数学').length).toBeGreaterThan(0)
    expect(screen.getByText('专一')).toBeInTheDocument()

    // 字符串任务必须整串保留，不能被按字符拆成"教/材/精/读"
    expect(screen.getByText('教材精读 + 课后题')).toBeInTheDocument()
    expect(screen.getByText('章节习题')).toBeInTheDocument()
    expect(screen.getByText('834 冲刺卷')).toBeInTheDocument()
    expect(screen.queryByText('教')).not.toBeInTheDocument()

    // 迁移后共 3 个任务，分母按任务数算
    expect(await screen.findByText('任务 0/3')).toBeInTheDocument()
    expect(screen.queryAllByPlaceholderText(/^任务 \d/)).toHaveLength(0)
  })
})

/* 未配置科目时的日计划：以前靠 useSubjectConfig 的内置兜底长出 6 行"你的科目"，
   那是一位考数电的人的科目表，不是这位用户的。空配置就该是空表 + 引导。 */
describe('Planner 日计划：尚未配置科目', () => {
  beforeEach(() => {
    cleanup()
    apiMocks.getDaily.mockReset()
    apiMocks.subjects.mockReset()
    apiMocks.subjects.mockResolvedValue({
      exam_subjects: [],
      support_subjects: [],
      all_known: [],
      core_defaults: ['数字电子技术', '数学'],
      using_default: true,
    })
    apiMocks.getDaily.mockResolvedValue({ exists: false, days_to_exam: null, tasks: {}, timeline: [], score: 0, summary: '' })
  })

  it('科目为空时给空态引导，不凭空长出科目行', async () => {
    // 科目快照是模块级单例：不重置模块就会继承上一个用例的 CONFIG
    vi.resetModules()
    const { default: FreshPlanner } = await import('../v3/pages/Planner')
    render(
      <MemoryRouter initialEntries={['/planner']}>
        <FreshPlanner />
      </MemoryRouter>
    )
    expect(await screen.findByText(/还没有备考科目|正在读取科目配置/)).toBeInTheDocument()
    expect(screen.queryAllByPlaceholderText(/^任务 \d/)).toHaveLength(0)
    expect(screen.queryByText('数电')).not.toBeInTheDocument()
  })
})
