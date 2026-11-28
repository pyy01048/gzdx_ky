import { afterEach, describe, expect, it, vi } from 'vitest'
import { engineering08Api } from '../api/client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('工科08 API 客户端', () => {
  it('目录与题目请求使用后端契约路径，并保留五轴筛选参数', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await engineering08Api.catalog()
    await engineering08Api.questions({
      school_id: 3,
      major_id: 8,
      subject_id: 12,
      year: 2025,
      question_type: 'single',
      source_kind: 'past_exam',
      difficulty: 4,
      page: 2,
      page_size: 20,
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/kaoyan/engineering-08/catalog')
    const url = new URL(fetchMock.mock.calls[1][0], 'http://localhost')
    expect(url.pathname).toBe('/api/kaoyan/engineering-08/questions')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      school_id: '3',
      major_id: '8',
      subject_id: '12',
      year: '2025',
      question_type: 'single',
      source_kind: 'past_exam',
      difficulty: '4',
      page: '2',
      page_size: '20',
    })
  })
})
