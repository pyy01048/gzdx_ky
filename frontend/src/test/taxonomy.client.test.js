import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => vi.unstubAllGlobals())

function mockFetch() {
  const spy = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [] }) })
  vi.stubGlobal('fetch', spy)
  return spy
}

describe('taxonomyApi 轻量树与知识点请求', () => {
  it('tree 默认保持 include_points=true，显式轻量档为 false', async () => {
    const spy = mockFetch()
    const { taxonomyApi } = await import('../api/client')

    await taxonomyApi.tree('数学')
    expect(spy.mock.calls[0][0]).toContain('include_points=true')

    await taxonomyApi.tree('数学', true, false, false)
    const url = new URL(spy.mock.calls[1][0], 'http://localhost')
    expect(url.searchParams.get('include_points')).toBe('false')
    expect(url.searchParams.get('subject')).toBe('数学')
  })

  it('knowledgePoints 透传分页参数与取消信号', async () => {
    const spy = mockFetch()
    const { taxonomyApi } = await import('../api/client')
    const controller = new AbortController()

    await taxonomyApi.knowledgePoints({ subject: '数学', chapter: '极限', page: 2, page_size: 200 }, { signal: controller.signal })

    const [url, init] = spy.mock.calls[0]
    expect(url).toContain('chapter=' + encodeURIComponent('极限'))
    expect(url).toContain('page=2')
    expect(url).toContain('page_size=200')
    controller.abort()
    expect(init.signal.aborted).toBe(true)
  })
})
