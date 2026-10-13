import React from 'react'
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, act, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 知识地图 V9 重构（docx/22 D2）· 三栏成功路径回归
 *
 * 既有测试只覆盖 KbMap 的「接口 500 / 返回 null」降级路径，成功路径零覆盖。
 * 本文件锁定重构后的信息架构契约：
 *   ① 顶部居中置顶导航（知识地图 / 知识点全景 / 考频分析）渲染；
 *   ② 三栏：左「章节」/ 中「知识点」/ 右「例题·方法」都渲染出数据；
 *   ③ 中栏每张知识点卡片的「开始练习」跳 /quiz?subject=&chapter=&kp_id=（知识点级精确出题）；
 *   ④ 点中栏卡片的选中区 → 右栏切到该知识点的例题/方法；
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

vi.mock('../api/client', () => ({
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
  const KbMap = (await import('../pages/KbMap')).default
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
  it('渲染顶部导航 + 三栏，且点知识点「开始练习」跳 /quiz?kp_id=', async () => {
    const { container } = await renderKbMap('/kbmap')
    await settle(500)

    // ① 顶部居中置顶导航
    expect(screen.getByRole('navigation', { name: '知识地图模块导航' })).toBeInTheDocument()
    expect(screen.getByText('知识点全景')).toBeInTheDocument()
    expect(screen.getByText('考频分析')).toBeInTheDocument()

    // ② 三栏
    expect(screen.getByText('章节')).toBeInTheDocument()
    expect(screen.getByText('极限')).toBeInTheDocument()
    expect(screen.getByText('例题 / 方法')).toBeInTheDocument()
    expect(screen.getByText('方法 / 要点')).toBeInTheDocument()
    expect(container.querySelector('.kb3-kp-card'), '中栏应有知识点卡片').toBeTruthy()

    // 右栏默认选中第一个知识点
    expect(container.querySelector('.kb3-detail-card .kb-drawer-name').textContent).toBe('极限存在')
    expect(screen.getByText('方法说明-1')).toBeInTheDocument()
    expect(screen.getByText('例题原文-1')).toBeInTheDocument()
    expect(screen.getByText('5 题')).toBeInTheDocument()

    // ③ 中栏「开始练习」→ 知识点级精确刷题
    const practiceBtns = screen.getAllByRole('button', { name: /开始练习/ })
    fireEvent.click(practiceBtns[0])
    await settle(60)
    const loc = screen.getByTestId('loc').textContent
    expect(loc).toContain('/quiz?')
    expect(loc).toContain('kp_id=1')
    expect(loc).toContain('subject=' + encodeURIComponent('数学'))
    expect(loc).toContain('chapter=' + encodeURIComponent('极限'))
  })

  it('点中栏第二个知识点的选中区 → 右栏切到该知识点的例题/方法', async () => {
    const { container } = await renderKbMap('/kbmap')
    await settle(500)
    expect(container.querySelector('.kb3-detail-card .kb-drawer-name').textContent).toBe('极限存在')

    const selects = container.querySelectorAll('.kb3-kp-select')
    expect(selects.length).toBe(2)
    fireEvent.click(selects[1])   // 「左右极限」
    await settle(200)

    expect(container.querySelector('.kb3-detail-card .kb-drawer-name').textContent).toBe('左右极限')
    expect(screen.getByText('方法说明-2')).toBeInTheDocument()
    expect(screen.getByText('例题原文-2')).toBeInTheDocument()
  })

  it('支持 ?subject&chapter&kp_id 深链定位（知识点全景回跳）', async () => {
    const { container } = await renderKbMap(
      '/kbmap?subject=' + encodeURIComponent('数学') +
      '&chapter=' + encodeURIComponent('极限') + '&kp_id=2'
    )
    await settle(500)

    expect(container.querySelector('.kb3-detail-card .kb-drawer-name').textContent).toBe('左右极限')
    expect(screen.getByText('方法说明-2')).toBeInTheDocument()
  })
})
