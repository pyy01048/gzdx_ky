import React from 'react'
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, act, fireEvent, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 知识地图 v3 三栏成功路径回归
 *
 * 本文件锁定信息架构契约：
 *   ① 顶部导航由应用壳提供，模块内不再重复「知识点全景 / 考频分析」入口；
 *   ② 三栏：左「章节」/ 中「知识点」/ 右「例题·方法」都渲染出数据；
 *   ③ 右栏「开始练习」跳 /quiz?subject=&chapter=&kp_id=（知识点级精确出题）；
 *   ④ 点中栏知识点卡片主区 → 进入该知识点阅读页（/knowledge/{id}）；
 *   ⑤ 支持 ?subject&chapter&kp_id 深链定位（供「知识点全景」回跳）。
 * ------------------------------------------------------------------ */

const tree = {
  tree: [
    {
      subject: '数学', is_core: true, knowledge_point_count: 2, outline_chapter_count: 1,
      learned_avg_mastery: 55,
      chapters: [
        {
          title: '极限', knowledge_point_count: 2, learned_avg_mastery: 55,
          question_types: ['single'],
          knowledge_points: [
            { id: 1, name: '极限存在', mastery: 80, review_count: 2, question_types: ['single'] },
            { id: 2, name: '左右极限', mastery: 30, review_count: 1, question_types: ['single'] },
          ],
        },
      ],
    },
  ],
}

function detailOf(id) {
  const n = Number(id)
  return {
    id: n,
    name: n === 2 ? '左右极限' : '极限存在',
    subject: '数学',
    chapter: '极限',
    mastery: n === 2 ? 30 : 80,
    question_types: ['single'],
    description: `方法说明-${n}`,
    related_chunks: [{ chunk_id: 'c1', doc_name: '教材', text: `例题原文-${n}` }],
    related_errors: [],
    review_count: 2,
    next_review: '2026-11-01',
  }
}

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
  request: vi.fn().mockResolvedValue(null),
  DEFAULT_TIMEOUT: 30000,
  taxonomyApi: {
    subjects: vi.fn().mockResolvedValue({ subjects: [{ subject: '数学', question_count: 2 }] }),
    tree: vi.fn().mockResolvedValue(tree),
    knowledgePoint: vi.fn((id) => Promise.resolve(detailOf(id))),
    coverage: vi.fn().mockResolvedValue(null),
  },
  reviewApi: {
    progress: vi.fn().mockResolvedValue({
      total_knowledge_points: 2, mastered_count: 1, weak_count: 1, reviewed_count: 2,
      reviews_last_7_days: 3, learned_avg_mastery: 55, weak_points: [],
    }),
    due: vi.fn().mockResolvedValue({ items: [] }),
    submit: vi.fn().mockResolvedValue({ mastery_before: 30, mastery_after: 40, interval: 2 }),
  },
  quizApi: { questions: vi.fn().mockResolvedValue({ total: 5 }) },
  qualityApi: { treeOverlay: vi.fn().mockResolvedValue(null) },
}))

beforeEach(() => { localStorage.clear() })
afterEach(cleanup)

/** 常驻 location 探针：始终挂载，导航后仍可读到最新路由 */
function Loc() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname + loc.search}</div>
}

async function settle(ms = 400) {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}

async function renderKbMap(entry = '/kbmap') {
  const KbMap = (await import('../v3/pages/KbMap')).default
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Loc />
      <Routes>
        <Route path="/kbmap" element={<KbMap />} />
        <Route path="*" element={null} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('KbMap 三栏成功路径', () => {
  it('渲染三栏，且右栏点「开始练习」跳 /quiz?kp_id=', async () => {
    const { container } = await renderKbMap('/kbmap')
    await settle(500)

    // 「知识点全景」已与知识地图合并为同一数据源（docx/25 §D），模块内不再有重复胶囊
    expect(screen.queryByText('知识点全景')).toBeNull()
    // 考频分析页已删除（docx/22 D3）：残留入口不得复现
    expect(screen.queryByText('考频分析')).toBeNull()
    expect(screen.queryByRole('button', { name: /考频分析/ })).toBeNull()

    // 三栏：左章节 / 中知识点 / 右例题·方法
    expect(screen.getByText('极限')).toBeInTheDocument()
    expect(screen.getByText('例题 / 方法')).toBeInTheDocument()
    expect(screen.getByText('关联题量')).toBeInTheDocument()
    expect(container.querySelector('.v3-kb-point'), '中栏应有知识点卡片').toBeTruthy()
    expect(container.querySelector('.v3-kb-detail'), '右栏应有详情面板').toBeTruthy()

    // 右栏默认选中第一个知识点
    expect(container.querySelector('.v3-kb-detail__name').textContent).toBe('极限存在')
    expect(screen.getByText('方法说明-1')).toBeInTheDocument()
    expect(screen.getByText('例题原文-1')).toBeInTheDocument()
    // 访客不请求题库接口，题量必须显示「—」而不是伪造 0
    expect(within(container.querySelector('.v3-kb-detail')).getAllByText('—').length).toBeGreaterThan(0)

    // 右栏「开始练习」→ 知识点级精确刷题
    fireEvent.click(screen.getByRole('button', { name: /开始练习/ }))
    await settle(60)
    const loc = screen.getByTestId('loc').textContent
    expect(loc).toContain('/quiz?')
    expect(loc).toContain('kp_id=1')
    expect(loc).toContain('subject=' + encodeURIComponent('数学'))
    expect(loc).toContain('chapter=' + encodeURIComponent('极限'))
  })

  it('点中栏知识点卡片主区 → 进入该知识点阅读页（/knowledge/{id}）', async () => {
    const { container } = await renderKbMap('/kbmap')
    await settle(500)
    // 默认已定位到首个有知识点的章节的首个知识点
    expect(container.querySelector('.v3-kb-detail__name').textContent).toBe('极限存在')

    // 中栏卡片主区是「进阅读页读概念」这一复习主线动作
    const mains = container.querySelectorAll('.v3-kb-point__main')
    expect(mains.length).toBe(2)
    fireEvent.click(mains[1])   // 第二个知识点「左右极限」(id=2)
    await settle(60)
    expect(screen.getByTestId('loc').textContent).toContain('/knowledge/2')
  })

  it('支持 ?subject&chapter&kp_id 深链定位（知识点全景回跳）', async () => {
    const { container } = await renderKbMap(
      '/kbmap?subject=' + encodeURIComponent('数学') +
      '&chapter=' + encodeURIComponent('极限') + '&kp_id=2'
    )
    await settle(500)

    expect(container.querySelector('.v3-kb-detail__name').textContent).toBe('左右极限')
    expect(screen.getByText('方法说明-2')).toBeInTheDocument()
  })
})
