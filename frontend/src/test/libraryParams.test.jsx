/**
 * 学习文库「资料来源」维度回归（P0-F01 / QA-01）。
 *
 * 线上全库 2666 条中绝大多数 subject_source=null，旧实现固定下发
 * subject_source=ima → 清单/统计卡全 0。这里锁死：
 *   ① 默认请求不带 subject_source（展示全部来源）；
 *   ② 用户主动选 IMA 才带 subject_source=ima；
 *   ③ IMA 命中 0 时有可见的「切换全部来源」回落出口（不是死路 CTA）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { buildParams } from '../v3/pages/Library'

/* 全部来源样本：subject_source=null（线上主体）+ 少量 ima */
const DATA = [
  {
    id: 1, file_name: '本地资料-电路.pdf', file_type: 'pdf', size: 1024,
    subject: '数模电', doc_type: 'raw', stage: '初试', content_type: '知识',
    subject_source: null, folder_path: '/资料/专业课', content_length: 100, chunk_count: 1,
  },
  {
    id: 2, file_name: 'IMA 资料-真题.pdf', file_type: 'pdf', size: 2048,
    subject: '408', doc_type: 'raw', stage: '复试', content_type: '试题',
    subject_source: null, folder_path: '/资料/408', content_length: 200, chunk_count: 2,
  },
]

function filterDocs(params = {}) {
  return DATA.filter((d) => (
    (!params.subject_source || d.subject_source === params.subject_source) &&
    (!params.stage || d.stage === params.stage) &&
    (!params.subject || d.subject === params.subject) &&
    (!params.content_type || d.content_type === params.content_type)
  ))
}

/** 与后端 /documents 同形：{items,total,facets.groups} */
function envelope(params) {
  const list = filterDocs(params)
  const page = Number(params.page) || 1
  const pageSize = Number(params.page_size) || 50
  const groups = []
  for (const d of list) {
    const key = `${d.subject}||${d.content_type}`
    let g = groups.find((x) => `${x.subject}||${x.content_type}` === key)
    if (!g) {
      g = { subject: d.subject, content_type: d.content_type, count: 0, parsed_count: 0 }
      groups.push(g)
    }
    g.count += 1
    if (d.content_length > 0) g.parsed_count += 1
  }
  return {
    items: list.slice((page - 1) * pageSize, page * pageSize),
    total: list.length,
    facets: { groups },
  }
}

const listMock = vi.fn(async (params) => envelope(params))
const subjectsMock = vi.fn(async () => ({ subjects: [{ name: '数模电' }, { name: '408' }] }))
const getContentMock = vi.fn(async (id) => ({ id, content: '正文', content_length: 2 }))

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  documentsApi: {
    list: (...args) => listMock(...args),
    getContent: (...args) => getContentMock(...args),
    subjects: (...args) => subjectsMock(...args),
  },
}))

beforeEach(() => {
  listMock.mockClear()
  listMock.mockImplementation(async (params) => envelope(params))
  subjectsMock.mockClear()
  subjectsMock.mockImplementation(async () => ({ subjects: [{ name: '数模电' }, { name: '408' }] }))
})

afterEach(() => { cleanup() })

async function settle() {
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
}

describe('buildParams 资料来源参数（P0-F01 / QA-01）', () => {
  it('默认不下发 subject_source 与 stage（全部来源 + 全部阶段）', () => {
    expect(buildParams('', '', '')).toEqual({})
    expect(buildParams('初试', '', '')).toEqual({ stage: '初试' })
    expect(buildParams('', '数学', '知识')).toEqual({ subject: '数学', content_type: '知识' })
    expect(buildParams('', '', '').subject_source).toBeUndefined()
  })

  it('主动选 ima / manual 才下发 subject_source', () => {
    expect(buildParams('', '', '', 'ima')).toEqual({ subject_source: 'ima' })
    expect(buildParams('初试', '', '', 'manual')).toEqual({ stage: '初试', subject_source: 'manual' })
  })

  it('清单与计数请求使用同一套来源口径', async () => {
    const Library = (await import('../v3/pages/Library')).default
    render(<MemoryRouter initialEntries={['/library']}><Library /></MemoryRouter>)
    await settle()
    const params = listMock.mock.calls.map((c) => c[0])
    expect(params.length).toBeGreaterThan(1)
    expect(params.every((p) => p.subject_source === undefined && p.stage === undefined)).toBe(true)
  })
})

describe('IMA 命中 0 的回落提示（P0-F01 / 死路 CTA）', () => {
  it('筛 ima 无结果时显示可见回落出口，切回全部来源后数据恢复', async () => {
    const Library = (await import('../v3/pages/Library')).default
    render(<MemoryRouter initialEntries={['/library']}><Library /></MemoryRouter>)
    await settle()
    expect(screen.getByText('本地资料-电路.pdf')).toBeTruthy()

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'IMA' })) })
    await settle()

    // 样本全部是 subject_source=null（线上主体），筛 IMA = 0 → 回落提示出现
    expect(screen.getByText(/IMA 来源下暂无资料，可切换到「全部来源」查看/)).toBeTruthy()
    expect(listMock.mock.calls.some((c) => c[0].subject_source === 'ima')).toBe(true)
    // 回落提示不能把访客引向无权访问的导入页
    expect(screen.queryByText(/导入由管理员/)).toBeNull()

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '查看全部来源' })) })
    await settle()
    expect(screen.getByText('本地资料-电路.pdf')).toBeTruthy()
  })
})
