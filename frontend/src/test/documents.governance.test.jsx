/* C 批次1：未结构化标注与可用资料量口径（评估报告 #10） */
import { describe, expect, it } from 'vitest'
import { docStateOf, normalizeDoc } from '../v3/pages/documentsV3Shared'

describe('documents governance (C batch1)', () => {
  it('normalizeDoc 透传 is_structured 与知识点数', () => {
    const d = normalizeDoc({
      id: 1, file_name: 'a.md', index_status: 'indexed',
      knowledge_point_count: 0, is_structured: false, content_length: 100,
    })
    expect(d.is_structured).toBe(false)
    expect(d.knowledge_point_count).toBe(0)
    expect(d.status).toBe('parsed')
  })

  it('已索引但未挂知识点 → 未结构化（warning），不冒充已入库', () => {
    const d = normalizeDoc({
      id: 1, file_name: 'a.md', index_status: 'indexed',
      is_structured: false, content_length: 100,
    })
    const st = docStateOf(d)
    expect(st.label).toBe('未结构化')
    expect(st.tone).toBe('warning')
  })

  it('挂到知识点后 → 已入库（success）', () => {
    const d = normalizeDoc({
      id: 1, file_name: 'a.md', index_status: 'indexed',
      is_structured: true, knowledge_point_count: 5, content_length: 100,
    })
    expect(docStateOf(d).label).toBe('已入库')
  })

  it('失败/空正文口径不变', () => {
    expect(docStateOf(normalizeDoc({ index_status: 'failed', content_length: 10 })).label).toBe('入库失败')
    expect(docStateOf(normalizeDoc({ index_status: 'indexed', content_length: 0 })).label).toBe('正文缺失')
  })
})
