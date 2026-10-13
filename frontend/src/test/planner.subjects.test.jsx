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

vi.mock('../api/client', () => ({
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

import Planner from '../pages/Planner'

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

  it('渲染配置科目 + 历史键，字符串任务不拆成单字，分母按科目数算', async () => {
    renderPlanner()

    // 配置科目（数电/模电/数学）与存量历史键「专一」都要在
    expect(await screen.findByText('数电')).toBeInTheDocument()
    expect(screen.getByText('模电')).toBeInTheDocument()
    expect(screen.getByText('数学')).toBeInTheDocument()
    expect(screen.getByText('专一')).toBeInTheDocument()

    // 分母 = 4 科 × 4 格 = 16；已填 = 数电 1 + 数学 1 + 专一 1 = 3
    expect(await screen.findByText('任务 3/16')).toBeInTheDocument()

    // 数电是字符串值：整串落在第 1 格，其余 3 格为空（而不是"教/材/精/读"）
    const inputs = screen.getAllByPlaceholderText(/^任务 \d/)
    expect(inputs).toHaveLength(16)
    expect(inputs.slice(0, 4).map((i) => i.value)).toEqual(['教材精读 + 课后题', '', '', ''])
  })
})
