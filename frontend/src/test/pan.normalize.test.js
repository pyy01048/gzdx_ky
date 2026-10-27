import { describe, it, expect, vi, beforeEach } from 'vitest'

/* ------------------------------------------------------------------ *
 * listPanFiles 字段归一（#26 网盘打通）
 *
 * 回归点：后端两个来源字段名不同 —— 百度 api_files 是 server_filename /
 * server_mtime（秒），本地 local_files 是 file_name 且没有 mtime。
 * 旧代码把 server_filename 原样透传，页面却吃 f.name / f.mtime，
 * 于是 fmtDateCN(undefined * 1000) → "s.split is not a function"，
 * 目录里一有文件整个网盘面板就崩。
 * ------------------------------------------------------------------ */

const requestMock = vi.fn()
vi.mock('../api/client', async (importOriginal) => ({
  // 派生真实模块的导出清单：client.js 新增导出（如 fetchAllPages）不必再回来补枚举，
  // 否则页面一 import 就报 "No export is defined on the mock"。
  ...(await importOriginal()),
  request: (...a) => requestMock(...a),
  favoritesApi: { list: vi.fn(), add: vi.fn(), check: vi.fn(), toggle: vi.fn(), remove: vi.fn() },
  growthApi: { timeline: vi.fn() },
}))

beforeEach(() => requestMock.mockReset())

describe('listPanFiles 字段归一', () => {
  it('百度字段转成页面吃的 name / size_kb / YYYY-MM-DD', async () => {
    requestMock.mockResolvedValue({
      api_files: [{
        fs_id: 123, server_filename: '数电真题.pdf', path: '/a/数电真题.pdf',
        size: 2097152, server_mtime: 1767139200, isdir: 0, category: 4,
      }],
      local_files: [{ id: 9, file_name: '本地缓存.docx', path: '/b', size: 10240 }],
    })
    const { listPanFiles } = await import('../utils/pan')
    const { fmtDateCN, fmtFileSize } = await import('../utils/date')

    const out = await listPanFiles('tok', '/')
    expect(out.map((f) => f.name)).toEqual(['数电真题.pdf', '本地缓存.docx'])
    // 百度给字节，展示函数吃 KB
    expect(out[0].size_kb).toBe(2048)
    expect(fmtFileSize(out[0].size_kb)).toBe('2.0 MB')
    // 页面直接喂给 fmtDateCN，不能再抛
    expect(out[0].date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(() => fmtDateCN(out[0].date)).not.toThrow()
  })

  it('本地记录没有 mtime 时给空串，而不是 NaN 让页面崩', async () => {
    requestMock.mockResolvedValue({ api_files: [], local_files: [{ id: 1, file_name: 'x.pdf', size: 0 }] })
    const { listPanFiles } = await import('../utils/pan')
    const out = await listPanFiles('tok', '/')
    expect(out[0].date).toBe('')
    expect(out[0].path).toBe('/')
  })

  it('同一 fs_id 在 api 与 local 都出现时只留一条（api 优先）', async () => {
    requestMock.mockResolvedValue({
      api_files: [{ fs_id: 55, server_filename: '来自百度.pdf', size: 1024 }],
      // 后端 local_files 直出真 fs_id（routers/netdisk.py 本轮补的字段）
      local_files: [{ id: 900, fs_id: 55, file_name: '本地同名.pdf', size: 1024 }],
    })
    const { listPanFiles } = await import('../utils/pan')
    const out = await listPanFiles('tok', '/')
    expect(out.length).toBe(1)
    expect(out[0].name).toBe('来自百度.pdf')
  })

  it('本地行没有 fs_id 时不得拿数据库主键冒充（否则取流链接必 404）', async () => {
    requestMock.mockResolvedValue({
      api_files: [],
      local_files: [{ id: 7, file_name: '未同步.pdf', path: '/x', size: 2048 }],
    })
    const { listPanFiles } = await import('../utils/pan')
    const out = await listPanFiles('tok', '/')
    expect(out[0].fs_id).toBeNull()
  })

  it('本地行的 created_at 会转成 YYYY-MM-DD，缺失才留空', async () => {
    requestMock.mockResolvedValue({
      api_files: [],
      local_files: [{ id: 8, fs_id: '1065450778599627', file_name: '有日期.pdf', size: 10,
        created_at: '2026-10-06 13:31:09.454706' }],
    })
    const { listPanFiles } = await import('../utils/pan')
    const out = await listPanFiles('tok', '/')
    expect(out[0].date).toBe('2026-10-06')
  })
})
