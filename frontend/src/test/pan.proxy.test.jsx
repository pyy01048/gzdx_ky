import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent, act, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 网盘取流走后端代理（#26 网盘打通）
 *
 * 背景缺陷：Pan.jsx 的「下载」按钮原先 window.open(百度 dlink)，
 * 而 dlink 强制要求 `User-Agent: pan.baidu.com`，浏览器直连必 403；
 * 更糟的是它调的 getFileMetas 返回 {list:[...]} 却按数组取 arr[0]，
 * 所以那个按钮 100% 只会弹「无法获取下载链接」。
 *
 * 这里锁两件事：
 *   ① 预览/下载都改成后端代理 URL（带 fs_id 与 disposition）
 *   ② 后端自己没授权百度网盘时，按钮是禁用 + 说明原因，而不是点开一个新标签报错
 * ------------------------------------------------------------------ */

/* listPanFiles 的产物形状（已由 utils/pan.js 归一：name / size_kb / date） */
const REMOTE = [
  { fs_id: '7001', name: '834 真题 2025.pdf', isdir: false, size_kb: 2048, date: '2026-01-05', path: '/考研/834 真题 2025.pdf' },
  { fs_id: '7002', name: '模电讲义.docx', isdir: false, size_kb: 512, date: '', path: '/考研/模电讲义.docx' },
]

let panState = { pan: [], addPan: vi.fn(), removePan: vi.fn(), updatePan: vi.fn() }
let baiduConfigured = true

vi.mock('../store/useStore', () => ({ default: () => panState }))
vi.mock('../hooks/useSubjectConfig', () => ({
  useSubjectConfig: () => ({ exam: [], support: [], all: [] }),
  subjectLabel: (s) => s,
}))
vi.mock('../utils/pan', () => ({
  getStoredPan: () => ({ access_token: 'tok', refresh_token: 'rtk' }),
  clearPan: vi.fn(),
  storePan: vi.fn(),
  getStatus: () => Promise.resolve({ configured: baiduConfigured }),
  getAuthUrl: vi.fn(),
  exchangeToken: vi.fn(),
  refreshPanToken: vi.fn(),
  listPanFiles: () => Promise.resolve(REMOTE),
}))
vi.mock('../api/client', () => ({
  request: vi.fn().mockResolvedValue({}),
  netdiskApi: {
    contentUrlByFsid: (fsId, disposition = 'inline') =>
      `/api/netdisk/content?fs_id=${fsId}&disposition=${disposition}`,
    // 页面挂载即读后端平台配置（平台列表/密钥不再写死）。mock 少给一个方法
    // 就是「面板一挂载就抛 TypeError」，本文件 4 个用例全红——留这行注释是因为
    // 这个红是真的：它证明页面确实依赖这个接口，不能假装可以省。
    platformConfigs: () => Promise.resolve({
      configs: { baidu: { display_name: '百度网盘', token: '', sync_enabled: true } },
    }),
    updatePlatformConfig: vi.fn().mockResolvedValue({}),
  },
}))

beforeEach(() => {
  panState = { pan: [], addPan: vi.fn(), removePan: vi.fn(), updatePan: vi.fn() }
  baiduConfigured = true
  vi.stubGlobal('open', vi.fn())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** 远端行结构：row > (icon, div[name + meta], buttons)，所以名字往上两层才是行 */
const rowOf = (name) => screen.getByText(name).parentElement.parentElement
const lastBtn = (name) => rowOf(name).querySelector('button:last-child')
const btnTexts = (name) => [...rowOf(name).querySelectorAll('button')].map((b) => b.textContent)

describe('网盘文件的预览/下载走后端代理', () => {
  it('pdf 给「预览」和「下载」，两者都指向 /api/netdisk/content', async () => {
    const Comp = (await import('../pages/Pan')).default
    render(<MemoryRouter><Comp /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('834 真题 2025.pdf')).toBeInTheDocument())

    fireEvent.click(lastBtn('834 真题 2025.pdf'))
    expect(window.open).toHaveBeenCalledWith('/api/netdisk/content?fs_id=7001&disposition=attachment', '_blank')

    const previewBtn = [...rowOf('834 真题 2025.pdf').querySelectorAll('button')]
      .find((b) => b.textContent === '预览')
    expect(previewBtn, 'pdf 应有一个预览入口').toBeTruthy()
    fireEvent.click(previewBtn)
    expect(window.open).toHaveBeenCalledWith('/api/netdisk/content?fs_id=7001&disposition=inline', '_blank')
  })

  it('docx 浏览器渲染不了，只给下载不给预览', async () => {
    const Comp = (await import('../pages/Pan')).default
    render(<MemoryRouter><Comp /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('模电讲义.docx')).toBeInTheDocument())
    expect(btnTexts('模电讲义.docx')).toEqual(['登记', '下载'])
  })

  it('后端未完成百度网盘授权时按钮禁用并说明原因，不弹新标签', async () => {
    baiduConfigured = false
    const Comp = (await import('../pages/Pan')).default
    render(<MemoryRouter><Comp /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('834 真题 2025.pdf')).toBeInTheDocument())

    const dl = lastBtn('834 真题 2025.pdf')
    expect(dl.disabled).toBe(true)
    expect(dl.title).toContain('后端未完成百度网盘授权')
    fireEvent.click(dl)
    expect(window.open).not.toHaveBeenCalled()
  })

  it('本地资料条目的「在网盘中打开」按 fs_id 取流，没有 fs_id 时只提示', async () => {
    panState.pan = [
      { id: 'p1', name: '网盘来的.pdf', type: 'pdf', cat: '真题', size: 10, date: '2026-01-01', remote: true, fsId: '8888' },
      { id: 'p2', name: '手登记的.pdf', type: 'pdf', cat: '真题', size: 10, date: '2026-01-02' },
    ]
    const Comp = (await import('../pages/Pan')).default
    const { container } = render(<MemoryRouter><Comp /></MemoryRouter>)
    // 同名条目也会出现在「最近同步」里，所以只在资料列表内查
    const resList = within(container.querySelector('.res-list'))

    fireEvent.click(resList.getByText('网盘来的.pdf'))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    fireEvent.click(screen.getByText('在网盘中打开'))
    expect(window.open).toHaveBeenCalledWith('/api/netdisk/content?fs_id=8888&disposition=inline', '_blank')

    vi.mocked(window.open).mockClear()
    fireEvent.click(resList.getByText('手登记的.pdf'))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    fireEvent.click(screen.getByText('在网盘中打开'))
    expect(window.open).not.toHaveBeenCalled()
  })
})
