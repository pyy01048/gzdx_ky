import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 学科词表对齐上屏（docx/16 §1.5-D/E）
 *
 * 锁两件「页面会不会骗人」的事：
 *  ① 资料页科目磁贴的篇数必须是**点这一科实际能拿到的篇数**。后端把
 *     「公共课-数学」折进「数学」后，只报 document_count 就是少报 31 篇，
 *     用户会觉得筛选坏了；所以有 merged_document_count 就用它。
 *  ② 质量看板的对齐表数字全部来自接口；接口失败时明确说「未加载」，
 *     不许退化成一张 0 的表（0 看起来像「没有脏数据」，那是最坏的假数）。
 *
 * 附带价值：本文件首次让 Documents.jsx 进入测试覆盖 —— 它就抓到过一次真崩：
 * 原文件 Modal 的 footer 里 `documentsApi.downloadUrl(fileDoc.id)` 没判空，
 * 而 footer 这段 JSX 每次渲染都会构造（Modal 的 open 只管内容挂不挂载），
 * fileDoc 初始为 null ⇒ 资料页整页抛 TypeError。
 * ------------------------------------------------------------------ */

/* jsdom 没有 canvas，QualityDashboard 里的 EChart 依赖 echarts —— 与
   pages.smoke.test.jsx 用同一套 stub，只为让模块能导入，不测图。 */
vi.mock('echarts/core', () => ({
  use: vi.fn(),
  init: vi.fn(() => ({
    setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(),
    on: vi.fn(), off: vi.fn(), clear: vi.fn(),
    showLoading: vi.fn(), hideLoading: vi.fn(),
  })),
}))
vi.mock('echarts/charts', () => ({
  BarChart: {}, LineChart: {}, ScatterChart: {}, PieChart: {},
  RadarChart: {}, MapChart: {}, GaugeChart: {}, HeatmapChart: {},
}))
vi.mock('echarts/components', () => ({
  TitleComponent: {}, TooltipComponent: {}, LegendComponent: {}, GridComponent: {},
  PolarComponent: {}, RadarComponent: {}, GeoComponent: {}, VisualMapComponent: {},
  DatasetComponent: {}, TransformComponent: {},
}))
vi.mock('echarts/features', () => ({ LabelLayout: {}, UniversalTransition: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const docsPayload = [
  { id: 1, file_name: '数学讲义.pdf', file_type: 'pdf', size: 2048, index_status: 'indexed', subject: '数学', doc_type: 'raw', structure_level: 1, ocr_used: false, chunk_count: 12, created_at: '2026-10-01T08:00:00', has_local_file: false, local_file_note: '没有路径', summary: '', content_length: 0 },
  { id: 2, file_name: '公共课数学.pdf', file_type: 'pdf', size: 1024, index_status: 'pending', subject: '公共课-数学', doc_type: 'raw', structure_level: 1, ocr_used: false, chunk_count: 0, created_at: '', has_local_file: false, local_file_note: '没有路径', summary: '', content_length: 0 },
]

const subjectsPayload = {
  total_documents: 2,
  total_chunks: 12,
  merged_count_note: 'merged_document_count 含别名/合并口径折叠，跨行相加会重复计数',
  subjects: [
    { name: '数学', document_count: 1, chunk_count: 5559, aliases: ['公共课-数学'], alias_of: null, merged_document_count: 2 },
    { name: '公共课-数学', document_count: 1, chunk_count: 0, aliases: [], alias_of: '数学', merged_document_count: 1 },
  ],
}

vi.mock('../api/client', () => ({
  request: vi.fn().mockResolvedValue({}),
  documentsApi: {
    list: vi.fn().mockResolvedValue(docsPayload),
    subjects: vi.fn().mockResolvedValue(subjectsPayload),
    remove: vi.fn(),
    parse: vi.fn(),
    parseAll: vi.fn(),
    upload: vi.fn(),
    getContent: vi.fn(),
    knowledgePoints: vi.fn(),
    chunks: vi.fn(),
    rawUrl: (id) => `/api/documents/${id}/raw`,
    downloadUrl: (id) => `/api/documents/${id}/download`,
  },
  aiApi: { ragSearch: vi.fn() },
  kbImportApi: { scan: vi.fn(), confirm: vi.fn() },
  qualityApi: {
    evalRuns: vi.fn().mockResolvedValue({ items: [] }),
    corpus: vi.fn().mockResolvedValue({ total_chunks: 0, subjects: [], ghost_index: { indexed_without_chunks: 0 } }),
    subjectAlignment: vi.fn(),
    evalRun: vi.fn(),
  },
}))
vi.mock('../components/KbHealthPanel', () => ({ default: () => null }))
vi.mock('../store/useStore', () => ({ default: (sel) => sel({ addCard: vi.fn() }) }))

const alignPayload = {
  document_subjects: 25,
  unaligned_labels: 2,
  unaligned_documents: 217,
  foldable_documents: 31,
  not_indexed_documents: 217,
  note: '归一只发生在查询/聚合层，documents.subject 未改动',
  rows: [
    { subject: '公共课-数学', documents: 31, own_chunks: 0, documents_with_chunks: 0, not_indexed: 31, targets: ['数学'], target_chunks: [{ subject: '数学', chunks: 5559 }], kind: 'alias_folded', reason: '前缀/缩写写法，折入规范名「数学」' },
    { subject: '真题综合', documents: 76, own_chunks: 660, documents_with_chunks: 63, not_indexed: 0, targets: [], target_chunks: [], kind: 'not_aliased', reason: '综合卷本就跨多学科' },
  ],
}

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => { cleanup() })

describe('资料页科目篇数', () => {
  it('用折叠后的 merged_document_count，而不是少报的 document_count', async () => {
    const Documents = (await import('../pages/Documents')).default
    const { container } = render(<MemoryRouter><Documents /></MemoryRouter>)

    const labelOf = (name) => [...container.querySelectorAll('.stat-tile .st-label')]
      .find((el) => el.textContent.startsWith(name))
    // 科目磁贴是异步拉的，先等它出现；选「数学」实际能拿到 2 篇
    // （1 篇规范名 + 1 篇「公共课-数学」），报 document_count=1 就是少报。
    await waitFor(() => expect(labelOf('数学')).toBeTruthy())
    const tile = labelOf('数学').closest('.stat-tile')
    expect(tile.querySelector('.st-val').textContent.trim()).toBe('2')
    expect(labelOf('数学').textContent).toContain('含 公共课-数学')
    // 别名那一行自己只有 1 篇，不能被母科目的数字带高
    expect(labelOf('公共课-数学').closest('.stat-tile').querySelector('.st-val').textContent.trim()).toBe('1')
  })
})

describe('质量看板词表对齐表', () => {
  it('数字直接来自接口，并区分可折叠与需人批', async () => {
    const { qualityApi } = await import('../api/client')
    qualityApi.subjectAlignment.mockResolvedValueOnce(alignPayload)
    const QualityDashboard = (await import('../pages/QualityDashboard')).default
    render(<MemoryRouter><QualityDashboard /></MemoryRouter>)

    const row = await waitFor(() => screen.getByText('公共课-数学'))
    expect(row.closest('tr').textContent).toContain('别名折叠')
    expect(row.closest('tr').textContent).toContain('5,559')
    const other = screen.getByText('真题综合').closest('tr')
    expect(other.textContent).toContain('明确不归一')
    expect(other.textContent).toContain('综合卷本就跨多学科')
    // 汇总口径点名两个数：可折叠 31 / 还没块 217
    expect(document.body.textContent).toContain('可按口径折叠 31 篇')
    expect(document.body.textContent).toContain('217 篇还没有可检索的分块')
  })

  it('接口失败时说明未加载，绝不退化成一张空表冒充「一切正常」', async () => {
    const { qualityApi } = await import('../api/client')
    qualityApi.subjectAlignment.mockRejectedValueOnce(new Error('后端未重启'))
    const QualityDashboard = (await import('../pages/QualityDashboard')).default
    render(<MemoryRouter><QualityDashboard /></MemoryRouter>)

    await waitFor(() => expect(screen.getByText('词表对齐数据未加载')).toBeInTheDocument())
    expect(screen.queryByText('文档侧写法')).not.toBeInTheDocument()
  })

  it('没有词表分裂时给明确的空状态', async () => {
    const { qualityApi } = await import('../api/client')
    qualityApi.subjectAlignment.mockResolvedValueOnce({ document_subjects: 18, unaligned_labels: 0, unaligned_documents: 0, foldable_documents: 0, not_indexed_documents: 0, note: '', rows: [] })
    const QualityDashboard = (await import('../pages/QualityDashboard')).default
    render(<MemoryRouter><QualityDashboard /></MemoryRouter>)

    await waitFor(() => expect(screen.getByText('没有词表分裂')).toBeInTheDocument())
  })
})
