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
        },
      ],
    },
  ],
}

const points = [
  { id: 1, name: '极限存在', subject: '数学', chapter: '极限', mastery: 80, review_count: 2, question_types: ['single'] },
  { id: 2, name: '左右极限', subject: '数学', chapter: '极限', mastery: 30, review_count: 1, question_types: ['single'] },
]

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
    knowledgePoints: vi.fn(({ keyword, page = 1, page_size = 50 } = {}) => {
      const matched = keyword ? points.filter((p) => p.name.includes(keyword)) : points
      return Promise.resolve({
        items: matched.slice((page - 1) * page_size, page * page_size),
        total: matched.length,
        page,
        page_size,
        total_pages: Math.ceil(matched.length / page_size),
      })
    }),
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

let taxonomyApi

beforeEach(async () => {
  localStorage.clear()
  vi.clearAllMocks()
  taxonomyApi = (await import('../api/client')).taxonomyApi
  taxonomyApi.subjects.mockReset().mockResolvedValue({ subjects: [{ subject: '数学', question_count: 2 }] })
  taxonomyApi.tree.mockReset().mockResolvedValue(tree)
  taxonomyApi.knowledgePoints.mockReset().mockImplementation(({ keyword, page = 1, page_size = 50 } = {}) => {
    const matched = keyword ? points.filter((p) => p.name.includes(keyword)) : points
    return Promise.resolve({
      items: matched.slice((page - 1) * page_size, page * page_size),
      total: matched.length,
      page,
      page_size,
      total_pages: Math.ceil(matched.length / page_size),
    })
  })
})
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
    expect(container.querySelector('.v3-kb-point'), '首屏不预载知识点').toBeFalsy()
    expect(taxonomyApi.knowledgePoints).not.toHaveBeenCalled()
    expect(taxonomyApi.tree).toHaveBeenCalledWith(undefined, true, false, false)

    fireEvent.click(screen.getByRole('button', { name: /极限2 个/ }))
    await settle(100)
    expect(container.querySelector('.v3-kb-point'), '中栏应有知识点卡片').toBeTruthy()

    /* 普通进入不再默认点开第一个知识点（详情会多发 2 个请求），
       点「在右栏查看详情」才加载；详情面板此时才出现「关联题量」。 */
    fireEvent.click(screen.getAllByRole('button', { name: '在右栏查看详情' })[0])
    await settle(200)
    expect(container.querySelector('.v3-kb-detail'), '右栏应有详情面板').toBeTruthy()
    expect(screen.getByText('关联题量')).toBeInTheDocument()
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
    fireEvent.click(screen.getByRole('button', { name: /极限2 个/ }))
    await settle(100)

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

  it('章节按 200 条逐页取全，并在切科目后复用缓存', async () => {
    const first = Array.from({ length: 200 }, (_, i) => ({ ...points[0], id: i + 1, name: `知识点-${i + 1}` }))
    const last = { ...points[1], id: 201, name: '最后一条' }
    taxonomyApi.knowledgePoints
      .mockImplementationOnce(({ page, page_size }) => Promise.resolve({ items: first, total: 201, page, page_size, total_pages: 2 }))
      .mockImplementationOnce(({ page, page_size }) => Promise.resolve({ items: [last], total: 201, page, page_size, total_pages: 2 }))

    const { container } = await renderKbMap('/kbmap')
    await settle(100)
    fireEvent.click(screen.getByRole('button', { name: /极限2 个/ }))
    await settle(150)
    expect(container.querySelectorAll('.v3-kb-point')).toHaveLength(201)
    expect(taxonomyApi.knowledgePoints.mock.calls.map(([p]) => p.page)).toEqual([1, 2])
    expect(taxonomyApi.knowledgePoints.mock.calls.every(([p]) => p.page_size === 200)).toBe(true)
    expect(taxonomyApi.knowledgePoints.mock.calls[0][0]).toMatchObject({ subject: '数学', chapter: '极限' })

    fireEvent.click(screen.getByRole('button', { name: /^全部/ }))
    await settle(80)
    fireEvent.click(screen.getByRole('button', { name: /^数学/ }))
    await settle(80)
    fireEvent.click(screen.getByRole('button', { name: /极限2 个/ }))
    await settle(80)
    expect(taxonomyApi.knowledgePoints).toHaveBeenCalledTimes(2)
    expect(container.querySelectorAll('.v3-kb-point')).toHaveLength(201)
  })

  it('章节失败显示错误与重试，不冒充暂无资料', async () => {
    taxonomyApi.knowledgePoints.mockRejectedValueOnce(new Error('章节接口 503'))
    const { container } = await renderKbMap('/kbmap')
    await settle(100)
    fireEvent.click(screen.getByRole('button', { name: /极限2 个/ }))
    await settle(100)

    expect(screen.getByText('章节知识点加载失败')).toBeInTheDocument()
    expect(screen.getByText('章节接口 503')).toBeInTheDocument()
    expect(screen.queryByText('该章节暂无知识点')).toBeNull()
    expect(screen.getByRole('button', { name: /加载失败/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await settle(100)
    expect(container.querySelectorAll('.v3-kb-point')).toHaveLength(2)
    expect(taxonomyApi.knowledgePoints).toHaveBeenCalledTimes(2)
  })

  it('快速切章会取消旧请求，旧响应不能覆盖当前章节', async () => {
    let resolveOld
    let oldSignal
    taxonomyApi.tree.mockResolvedValueOnce({
      tree: [{
        ...tree.tree[0],
        chapters: [...tree.tree[0].chapters, { title: '导数', knowledge_point_count: 1, learned_avg_mastery: 40 }],
      }],
    })
    taxonomyApi.knowledgePoints
      .mockImplementationOnce((_params, options) => {
        oldSignal = options.signal
        return new Promise((resolve) => { resolveOld = resolve })
      })
      .mockResolvedValueOnce({ items: [{ ...points[0], id: 20, name: '导数存在', chapter: '导数' }], total: 1, total_pages: 1 })

    const { container } = await renderKbMap('/kbmap')
    await settle(100)
    fireEvent.click(screen.getByRole('button', { name: /极限2 个/ }))
    fireEvent.click(screen.getByRole('button', { name: /导数1 个/ }))
    await settle(80)
    expect(oldSignal.aborted).toBe(true)
    expect(container.querySelector('.v3-kb-point__name').textContent).toBe('导数存在')

    await act(async () => {
      resolveOld({ items: points, total: 2, total_pages: 1 })
      await Promise.resolve()
    })
    await settle(50)
    expect(container.querySelector('.v3-kb-point__name').textContent).toBe('导数存在')
    expect(container.querySelectorAll('.v3-kb-point')).toHaveLength(1)
  })

  it('快速切科目时旧树晚返回不覆盖当前科目', async () => {
    let resolveEnglish
    const englishTree = {
      tree: [{ subject: '英语', chapters: [{ title: '英语章节', knowledge_point_count: 1 }] }],
    }
    const mathTree = {
      tree: [{ ...tree.tree[0], chapters: [{ title: '导数', knowledge_point_count: 1, learned_avg_mastery: 40 }] }],
    }
    taxonomyApi.subjects.mockResolvedValue({ subjects: [{ subject: '数学' }, { subject: '英语' }] })
    taxonomyApi.tree
      .mockResolvedValueOnce(tree)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveEnglish = resolve }))
      .mockResolvedValueOnce(mathTree)

    await renderKbMap('/kbmap')
    await settle(100)
    fireEvent.click(screen.getByRole('button', { name: /^英语/ }))
    fireEvent.click(screen.getByRole('button', { name: /^数学/ }))
    await settle(80)
    expect(screen.getByRole('button', { name: /导数1 个/ })).toBeInTheDocument()

    await act(async () => {
      resolveEnglish(englishTree)
      await Promise.resolve()
    })
    await settle(50)
    expect(screen.getByRole('button', { name: /导数1 个/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /英语章节/ })).toBeNull()
  })

  it('全库搜索走服务端 keyword，保留防抖且旧代响应不覆盖新词', async () => {
    let resolveOld
    let oldSignal
    taxonomyApi.knowledgePoints
      .mockImplementationOnce((_params, options) => {
        oldSignal = options.signal
        return new Promise((resolve) => { resolveOld = resolve })
      })
      .mockResolvedValueOnce({
        items: [{ ...points[0], id: 9, name: '全库新结果', subject: '408', chapter: '数据结构' }],
        total: 1,
        total_pages: 1,
      })

    const { container } = await renderKbMap('/kbmap')
    await settle(100)
    const input = screen.getByLabelText('搜索知识点')
    fireEvent.change(input, { target: { value: '左' } })
    expect(taxonomyApi.knowledgePoints).not.toHaveBeenCalled()
    await settle(350)
    expect(taxonomyApi.knowledgePoints.mock.calls[0][0]).toMatchObject({ keyword: '左', page: 1, page_size: 60 })

    fireEvent.change(input, { target: { value: '全库' } })
    expect(oldSignal.aborted).toBe(true)
    await settle(400)
    expect(container.querySelector('.v3-kb-point__name').textContent).toBe('全库新结果')
    await act(async () => {
      resolveOld({ items: [{ ...points[0], name: '旧搜索结果' }], total: 1, total_pages: 1 })
      await Promise.resolve()
    })
    await settle(50)
    expect(container.querySelector('.v3-kb-point__name').textContent).toBe('全库新结果')
    expect(screen.queryByText('旧搜索结果')).toBeNull()
  })
})
