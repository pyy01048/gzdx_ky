import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 学习文库页（Library）链路测试
 *
 * 目标：证明「打开 /library → 按 初试/复试 + 科目 + 知识/试题/单词 筛选」
 *       这条链路是通的，而不只是"页面能渲染"。
 *
 * 策略：不连真后端，而是让 documentsApi.list 按参数对固定数据集做过滤
 *       （与后端 routers/documents.py:87-101 的过滤语义一致），
 *       然后断言：① 下发的参数正确 ② 渲染出的资料正是该组合的结果。
 * ------------------------------------------------------------------ */

// 固定数据集：初试 3 条（数模电/408/公共课-英语），复试 1 条
const DATA = [
  {
    id: 1, file_name: '模电第三章-放大电路.pdf', file_type: 'pdf', size: 2 * 1024 * 1024,
    subject: '数模电', doc_type: 'raw', structure_level: 2, ocr_used: false,
    stage: '初试', content_type: '知识', subject_source: 'ima',
    folder_path: '/IMA/专业课/数模电', ima_media_id: 'm1', summary: '放大电路基础',
    content_length: 12000, chunk_count: 8, created_at: '2026-01-01T00:00:00',
  },
  {
    id: 2, file_name: '408真题-2019.pdf', file_type: 'pdf', size: 900 * 1024,
    subject: '408', doc_type: 'raw', structure_level: 2, ocr_used: false,
    stage: '初试', content_type: '试题', subject_source: 'ima',
    folder_path: '/IMA/专业课/408', ima_media_id: 'm2', summary: '2019 统考真题',
    content_length: 8000, chunk_count: 5, created_at: '2026-01-02T00:00:00',
  },
  {
    id: 3, file_name: '考研核心词汇.xlsx', file_type: 'xlsx', size: 120 * 1024,
    subject: '公共课-英语', doc_type: 'note', structure_level: 1, ocr_used: false,
    stage: '初试', content_type: '单词', subject_source: 'ima',
    folder_path: '/IMA/公共课/英语', ima_media_id: 'm3', summary: '核心词汇表',
    content_length: 5000, chunk_count: 0, created_at: '2026-01-03T00:00:00',
  },
  {
    id: 4, file_name: '复试面试手册.docx', file_type: 'docx', size: 60 * 1024,
    subject: '其他', doc_type: 'index', structure_level: 1, ocr_used: false,
    stage: '复试', content_type: '知识', subject_source: 'ima',
    folder_path: '/IMA/复试', ima_media_id: 'm4', summary: '面试常见问题',
    content_length: 3000, chunk_count: 2, created_at: '2026-01-04T00:00:00',
  },
]

/** 与后端一致的参数过滤；空值参数视为"不下发" */
function filterDocs(params = {}) {
  return DATA.filter((d) => (
    (!params.subject_source || d.subject_source === params.subject_source) &&
    (!params.stage || d.stage === params.stage) &&
    (!params.subject || d.subject === params.subject) &&
    (!params.content_type || d.content_type === params.content_type)
  ))
}

const listMock = vi.fn(async (params) => filterDocs(params))
const getContentMock = vi.fn(async (id) => ({
  id, file_name: '模电第三章-放大电路.pdf', content_length: 12, content: '共射放大电路的静态工作点…', truncated: false,
}))

vi.mock('../api/client', () => ({
  documentsApi: {
    list: (...args) => listMock(...args),
    getContent: (...args) => getContentMock(...args),
  },
}))

beforeEach(() => {
  listMock.mockClear()
  listMock.mockImplementation(async (params) => filterDocs(params))
  getContentMock.mockClear()
  getContentMock.mockImplementation(async (id) => ({
    id, file_name: 'x', content_length: 12, content: '共射放大电路的静态工作点…', truncated: false,
  }))
})

afterEach(() => { cleanup() })

/** 渲染页面并等待首屏数据落地 */
async function renderLibrary() {
  const Library = (await import('../pages/Library')).default
  const utils = render(
    <MemoryRouter initialEntries={['/library']}>
      <Library />
    </MemoryRouter>
  )
  await waitFor(() => expect(listMock).toHaveBeenCalled())
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
  return utils
}

/** 点击一个 chip（chip 的可访问名含条数角标，故用正则匹配） */
async function clickChip(re) {
  const btn = screen.getAllByRole('button').find((b) => re.test(b.textContent || ''))
  expect(btn, `未找到匹配 ${re} 的按钮`).toBeTruthy()
  await act(async () => { fireEvent.click(btn) })
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
}

// ========================================================================= //
describe('学习文库 Library 页面', () => {
  it('打开即以 subject_source=ima + stage=初试 拉取 IMA 资料', async () => {
    await renderLibrary()

    // 首屏至少一次带 ima 来源 + 初试 阶段的请求
    const first = listMock.mock.calls[0][0]
    expect(first).toMatchObject({ subject_source: 'ima', stage: '初试' })

    // 初试的 3 条都在，复试的 1 条不在
    expect(screen.getByText('模电第三章-放大电路.pdf')).toBeTruthy()
    expect(screen.getByText('408真题-2019.pdf')).toBeTruthy()
    expect(screen.getByText('考研核心词汇.xlsx')).toBeTruthy()
    expect(screen.queryByText('复试面试手册.docx')).toBeNull()
  })

  it('切到「复试」后按 stage=复试 重新拉数据', async () => {
    await renderLibrary()
    await clickChip(/^复试$/)

    const params = listMock.mock.calls.map((c) => c[0])
    expect(params.some((p) => p && p.stage === '复试')).toBe(true)

    // 复试只有 1 条资料
    expect(screen.getByText('复试面试手册.docx')).toBeTruthy()
    expect(screen.queryByText('模电第三章-放大电路.pdf')).toBeNull()
  })

  it('点科目 chip 后按 subject 过滤（数模电）', async () => {
    await renderLibrary()
    await clickChip(/数模电/)

    const params = listMock.mock.calls.map((c) => c[0])
    expect(params.some((p) => p && p.subject === '数模电')).toBe(true)
    expect(screen.getByText('模电第三章-放大电路.pdf')).toBeTruthy()
    expect(screen.queryByText('408真题-2019.pdf')).toBeNull()
  })

  it('点内容性质 chip 后按 content_type 过滤（单词）', async () => {
    await renderLibrary()
    await clickChip(/单词/)

    const params = listMock.mock.calls.map((c) => c[0])
    expect(params.some((p) => p && p.content_type === '单词')).toBe(true)
    expect(screen.getByText('考研核心词汇.xlsx')).toBeTruthy()
    expect(screen.queryByText('408真题-2019.pdf')).toBeNull()
  })

  it('筛选组合无结果时显示友好空态，而不是白屏', async () => {
    await renderLibrary()
    await clickChip(/^复试$/)   // 切到复试（仅 1 条：其他 / 知识）
    await clickChip(/单词/)     // 复试 + 单词 = 数据本身为 0 条

    expect(screen.getByText(/暂无资料/)).toBeTruthy()
    expect(screen.queryByText('复试面试手册.docx')).toBeNull()
  })

  it('展示 IMA 来源标记、科目徽标与格式化体积', async () => {
    await renderLibrary()
    expect(screen.getAllByText('IMA').length).toBeGreaterThan(0)
    // 体积与 doc_type 同在一个 .lb-meta 节点里，用正则局部匹配
    expect(screen.getByText(/2\.0 MB/)).toBeTruthy()      // fmtSize：2MB
    expect(screen.getByText('/IMA/专业课/数模电')).toBeTruthy() // IMA 原始目录
  })

  it('点击文件名展开正文预览（GET /documents/{id}/content）', async () => {
    await renderLibrary()
    await act(async () => { fireEvent.click(screen.getByText('模电第三章-放大电路.pdf')) })
    await waitFor(() => expect(getContentMock).toHaveBeenCalled())
    expect(getContentMock.mock.calls[0][0]).toBe(1)
    await waitFor(() => expect(screen.getByText(/共射放大电路/)).toBeTruthy())
  })

  it('后端返回 null（2xx 无响应体）时不白屏', async () => {
    listMock.mockImplementation(async () => null)
    const Library = (await import('../pages/Library')).default
    const { container } = render(
      <MemoryRouter initialEntries={['/library']}><Library /></MemoryRouter>
    )
    await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
    expect(container.firstChild).toBeTruthy()
  })

  it('后端报错时显示错误态与重试入口，不崩溃', async () => {
    listMock.mockImplementation(async () => { throw new Error('backend offline') })
    const Library = (await import('../pages/Library')).default
    render(<MemoryRouter initialEntries={['/library']}><Library /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('资料加载失败')).toBeTruthy())
    expect(screen.getByText(/backend offline/)).toBeTruthy()
  })
})
