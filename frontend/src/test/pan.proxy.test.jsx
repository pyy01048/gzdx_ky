import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 网盘页重构回归（#netdisk-refactor）
 *
 * 旧缺陷：门禁信 localStorage 残留 token，且 /netdisk/files 把本地同步
 * 缓存混进列表——"还没正常连接网盘就能显示文件夹目录"。
 *
 * 新交互契约（本文件锁定）：
 *   ① 未授权（后端 token-status.authorized=false）只渲染平台选择卡，
 *      禁止出现任何目录/文件；
 *   ② 授权成功才进入文件浏览器，文件夹逐级进入 + 面包屑；
 *   ③ 文件点击后右侧预览：图片 <img> / PDF <iframe> / 视频 <video>，
 *      地址一律走后端代理 /api/netdisk/content（百度 dlink 直连必 403）；
 *   ④ 下载走 disposition=attachment 代理 URL；
 *   ⑤ docx 等浏览器渲染不了的类型只给下载 + 入库，不给内嵌预览；
 *   ⑥ 授权失效（401）时回到平台选择页，而不是拿缓存冒充目录。
 * ------------------------------------------------------------------ */

const FILES_ROOT = [
  { fs_id: '8001', name: '考研数学', isdir: true, path: '/考研数学', size_kb: 0, date: '' },
  { fs_id: '8002', name: '834 真题 2025.pdf', isdir: false, path: '/834 真题 2025.pdf', size_kb: 2048, date: '2026-01-05' },
]
const FILES_SUB = [
  { fs_id: '8003', name: '张宇1000题.mp4', isdir: false, path: '/考研数学/张宇1000题.mp4', size_kb: 512000, date: '2026-02-01' },
  { fs_id: '8004', name: '错题截图.png', isdir: false, path: '/考研数学/错题截图.png', size_kb: 300, date: '' },
]
const FILES_DOCX = [
  { fs_id: '8005', name: '模电讲义.docx', isdir: false, path: '/模电讲义.docx', size_kb: 512, date: '' },
]

let tokenStatusState = { authorized: false }
/* P0-SEC 后 platform-configs 只回 has_* 状态位，凭据原值永不出接口。
   默认「密钥已配、尚未授权」，个别用例临时改写。
   app_key/secret_key 故意放哨兵值：即使有人把字段重新塞进响应，页面也绝不能把它渲染出来。 */
const CFG_CONFIGURED = {
  configs: {
    baidu: {
      has_app_key: true, has_secret_key: true, has_token: false, app_id: 'APPID-1',
      app_key: 'SENTINEL-APPKEY', secret_key: 'SENTINEL-SECRET',
      extra: { refresh_token: 'SENTINEL-REFRESH' },
    },
    quark: { web_view_url: 'https://pan.quark.cn/' },
  },
}
let cfgState = CFG_CONFIGURED
let remoteByDir = { '/': FILES_ROOT, '/考研数学': FILES_SUB }
let remoteImpl = (dir) => Promise.resolve(remoteByDir[dir] || [])

vi.mock('../store/useStore', () => ({
  default: () => ({ pan: [], addPan: vi.fn(), removePan: vi.fn(), updatePan: vi.fn() }),
}))
// v3 网盘页把授权 / API 配置 / 入库收敛为管理员操作，这里以管理员身份验证完整链路
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ status: 'ready', user: { id: 1, role: 'admin' }, isAdmin: true, reload: vi.fn() }),
}))
vi.mock('../utils/pan', () => ({
  getStoredPan: () => null,
  clearPan: vi.fn(),
  storePan: vi.fn(),
  getStatus: () => Promise.resolve({ configured: true }),
  getAuthUrl: () => Promise.resolve('https://openapi.baidu.com/oauth/2.0/authorize?x=1'),
  exchangeToken: vi.fn(async () => ({ access_token: 'tok' })),
  refreshPanToken: vi.fn(),
  listPanFiles: () => Promise.resolve([]),
  // 授权状态唯一事实来源 = 后端 token-status
  getTokenStatus: () => Promise.resolve(tokenStatusState),
  fetchRemoteFiles: (dir) => remoteImpl(dir),
  logoutPan: vi.fn(async () => ({})),
  getQuarkView: () => Promise.resolve({ url: 'https://pan.quark.cn/', configured: false, defaulted: true }),
}))
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
  request: vi.fn().mockResolvedValue({}),
  netdiskApi: {
    contentUrlByFsid: (fsId, disposition = 'inline') =>
      `/api/netdisk/content?fs_id=${fsId}&disposition=${disposition}`,
    platformConfigs: () => Promise.resolve(cfgState),
    updatePlatformConfig: vi.fn().mockResolvedValue({}),
    ingest: vi.fn().mockResolvedValue({ success: true, message: '已入库' }),
  },
}))

beforeEach(() => {
  tokenStatusState = { authorized: false }
  cfgState = CFG_CONFIGURED
  remoteByDir = { '/': FILES_ROOT, '/考研数学': FILES_SUB }
  remoteImpl = (dir) => Promise.resolve(remoteByDir[dir] || [])
  vi.stubGlobal('open', vi.fn())
  // 预览文本/docx 时会 fetch 代理地址；jsdom 无网，统一打桩
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, text: async () => '', arrayBuffer: async () => new ArrayBuffer(0) })))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const loadPage = async () => {
  const Comp = (await import('../v3/pages/Pan')).default
  return render(<MemoryRouter><Comp /></MemoryRouter>)
}

describe('网盘页：未授权时只显示平台选择，禁止展示目录', () => {
  it('后端未授权时不渲染任何文件/目录，只有平台卡与授权按钮', async () => {
    const { container } = await loadPage()
    await waitFor(() => expect(screen.getByText('百度网盘')).toBeInTheDocument())

    expect(screen.getByText('夸克网盘')).toBeInTheDocument()
    expect(screen.getByText('去授权')).toBeInTheDocument()
    // 浏览器面板/文件行一律不许出现
    expect(screen.queryByText('百度网盘文件')).toBeNull()
    expect(screen.queryByText('834 真题 2025.pdf')).toBeNull()
    expect(screen.queryByText('考研数学')).toBeNull()
    expect(container.querySelector('.pan-file-list')).toBeNull()
  })
})

/* ------------------------------------------------------------------ *
 * P0-SEC：凭据只写不回显
 * 后端 PUT 把「留空」解释为「保持原值不变」，所以前端必须：
 *   ① 表单一律留空（GET 已拿不到原值）；
 *   ② 用 has_* 状态位判断是否可授权，缺任一即禁用「去授权」；
 *   ③ 提交空表单时不得把任何密钥写进 DOM 或响应体。
 * ------------------------------------------------------------------ */
describe('网盘页：凭据只写不回显（P0-SEC）', () => {
  it('has_app_key + has_secret_key 齐备时「去授权」可用', async () => {
    await loadPage()
    const go = await screen.findByText('去授权')
    expect(go.closest('button')).not.toBeDisabled()
    expect(screen.queryByText(/尚未配置 API 密钥/)).toBeNull()
  })

  it('缺任一状态位时「去授权」禁用并说明原因', async () => {
    cfgState = { configs: { baidu: { has_app_key: true, has_secret_key: false }, quark: {} } }
    await loadPage()
    const go = await screen.findByText('去授权')
    expect(go.closest('button')).toBeDisabled()
    expect(screen.getByText(/尚未配置 API 密钥/)).toBeInTheDocument()
  })

  it('API 配置弹窗不回显已存密钥', async () => {
    const { container } = await loadPage()
    fireEvent.click(await screen.findByText('API 配置'))

    const inputs = await screen.findAllByPlaceholderText(/已配置，留空则不修改/)
    expect(inputs).toHaveLength(2)
    inputs.forEach((el) => expect(el.value).toBe(''))
    expect(screen.getByText(/密钥是只写字段/)).toBeInTheDocument()
    expect(screen.getByText(/留空提交表示保持原值不变/)).toBeInTheDocument()
    // 响应里即便混进凭据原值，页面也不得渲染（文本与属性都算外泄）
    expect(container.textContent).not.toMatch(/SENTINEL/)
    expect(container.innerHTML).not.toMatch(/SENTINEL/)
  })

  it('留空提交只上送空串，服务端原值不变', async () => {
    const { netdiskApi } = await import('../api/client')
    const before = netdiskApi.updatePlatformConfig.mock.calls.length
    await loadPage()
    fireEvent.click(await screen.findByText('API 配置'))
    fireEvent.click(await screen.findByText('保存'))

    await waitFor(() => expect(netdiskApi.updatePlatformConfig.mock.calls.length).toBeGreaterThan(before))
    const [platform, payload] = netdiskApi.updatePlatformConfig.mock.calls.at(-1)
    expect(platform).toBe('baidu')
    expect(payload.app_key).toBe('')
    expect(payload.secret_key).toBe('')
    expect(Object.keys(payload).sort()).toEqual(['app_key', 'redirect_uri', 'secret_key'])
  })
})

describe('网盘页：授权后进入文件浏览器', () => {
  beforeEach(() => { tokenStatusState = { authorized: true, expired: false } })

  it('渲染真实目录列表，文件夹可逐级进入并更新面包屑', async () => {
    await loadPage()
    await waitFor(() => expect(screen.getByText('834 真题 2025.pdf')).toBeInTheDocument())

    // 根目录：文件夹 + 文件
    expect(screen.getByText('考研数学')).toBeInTheDocument()

    // 进入子目录
    fireEvent.click(screen.getByText('考研数学'))
    await waitFor(() => expect(screen.getByText('张宇1000题.mp4')).toBeInTheDocument())

    // 面包屑出现当前目录名，且上级按钮可用
    expect(screen.getByText('考研数学', { selector: '.pan-crumb-item.current' })).toBeInTheDocument()
    const up = screen.getByText('⬆ 上级')
    expect(up.disabled).toBe(false)

    // 返回根目录
    fireEvent.click(up)
    await waitFor(() => expect(screen.getByText('834 真题 2025.pdf')).toBeInTheDocument())
    expect(screen.queryByText('张宇1000题.mp4')).toBeNull()
  })

  it('视频文件用播放器播放，地址走后端代理', async () => {
    const { container } = await loadPage()
    await waitFor(() => expect(screen.getByText('834 真题 2025.pdf')).toBeInTheDocument())
    fireEvent.click(screen.getByText('考研数学'))
    await waitFor(() => expect(screen.getByText('张宇1000题.mp4')).toBeInTheDocument())

    fireEvent.click(screen.getByText('张宇1000题.mp4'))
    await waitFor(() => expect(container.querySelector('video')).toBeInTheDocument())
    const video = container.querySelector('video')
    expect(video.getAttribute('src')).toBe('/api/netdisk/content?fs_id=8003&disposition=inline')
    expect(video.hasAttribute('controls')).toBe(true)
  })

  it('PDF 用 iframe 预览，下载走 attachment 代理 URL', async () => {
    const { container } = await loadPage()
    await waitFor(() => expect(screen.getByText('834 真题 2025.pdf')).toBeInTheDocument())

    fireEvent.click(screen.getByText('834 真题 2025.pdf'))
    await waitFor(() => expect(container.querySelector('.pv-frame')).toBeInTheDocument())
    expect(container.querySelector('.pv-frame').getAttribute('src'))
      .toBe('/api/netdisk/content?fs_id=8002&disposition=inline')

    fireEvent.click(screen.getByText('下载'))
    expect(window.open).toHaveBeenCalledWith(
      '/api/netdisk/content?fs_id=8002&disposition=attachment', '_blank')
  })

  it('docx 不给内嵌预览，只给下载与入库', async () => {
    remoteByDir = { '/': FILES_DOCX }
    const { container } = await loadPage()
    await waitFor(() => expect(screen.getByText('模电讲义.docx')).toBeInTheDocument())

    fireEvent.click(screen.getByText('模电讲义.docx'))
    const preview = await waitFor(() => container.querySelector('.pan2-preview'))
    // 浏览器渲染不了 docx：不得出现 iframe / video / img 预览
    expect(preview.querySelector('iframe')).toBeNull()
    expect(preview.querySelector('video')).toBeNull()
    expect(preview.querySelector('img')).toBeNull()
    expect(within(preview).getByText('下载')).toBeInTheDocument()
    expect(within(preview).getByText('入库到知识库')).toBeInTheDocument()
  })

  it('目录读取返回 401（授权失效）时回到平台选择页', async () => {
    remoteImpl = () => Promise.reject({ status: 401, message: '身份验证失败，请重新授权' })
    await loadPage()
    await waitFor(() => expect(screen.getByText('去授权')).toBeInTheDocument())
    // 缓存目录不得出现
    expect(screen.queryByText('834 真题 2025.pdf')).toBeNull()
    expect(screen.queryByText('百度网盘文件')).toBeNull()
  })
})
