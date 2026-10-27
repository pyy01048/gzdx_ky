import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 角色可见性矩阵（2026-10-21）
 *
 * 后端 access_policy 已按「访客 / 登录用户 / 管理员」集中鉴权；本文件锁定
 * 前端不得再把管理员动作摆给普通用户（点了必 403 的入口 = 假功能）。
 *
 * 约定：useAuth 由本文件 mock，角色通过 currentRole 切换；
 * api/client 全量打桩，避免任何真实网络请求。
 * ------------------------------------------------------------------ */

let currentRole = 'user'
// 身份对象必须是稳定引用：KbMap 的 useCallback/useEffect 依赖 user 对象，
// 每次渲染新建对象会让 loadAll 无限重跑（act 永不结束）。
const USERS = {
  user: { id: 1, username: 'tester', display_name: '测试用户', role: 'user' },
  admin: { id: 1, username: 'admin', display_name: '管理员', role: 'admin' },
}
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    status: 'ready',
    user: USERS[currentRole],
    isAdmin: currentRole === 'admin',
    login: vi.fn(),
    logout: vi.fn(),
    reload: vi.fn(),
  }),
}))

const clientStub = {}

function group() {
  const cache = new Map()
  return new Proxy({}, {
    get: (target, prop) => {
      if (typeof prop !== 'string') return undefined
      if (prop in target) return target[prop]
      if (!cache.has(prop)) cache.set(prop, vi.fn().mockResolvedValue(null))
      return cache.get(prop)
    },
  })
}

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  for (const name of Object.keys(actual)) {
    if (name === 'DEFAULT_TIMEOUT' || name === 'MAX_PAGE_SIZE') {
      clientStub[name] = actual[name]
    } else if (name === 'fetchAllPages') {
      clientStub[name] = vi.fn().mockResolvedValue([])
    } else if (name === 'request') {
      clientStub[name] = vi.fn().mockResolvedValue(null)
    } else if (name === 'fileUrl') {
      clientStub[name] = vi.fn((p) => `http://test${p}`)
    } else if (name === 'getBackendState') {
      clientStub[name] = vi.fn(() => ({ state: 'ok', failures: [], checkedAt: 0 }))
    } else if (name === 'subscribeBackendState') {
      clientStub[name] = vi.fn(() => () => {})
    } else {
      clientStub[name] = group()
    }
  }
  return clientStub
})

beforeEach(() => {
  currentRole = 'user'
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

async function settle(ms = 250) {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}

function renderWithRouter(node) {
  return render(<MemoryRouter initialEntries={['/']}>{node}</MemoryRouter>)
}

/* ------------------------------------------------------------------ *
 * 文档知识库
 * ------------------------------------------------------------------ */
describe('Documents：共享文档库按角色收敛动作', () => {
  async function renderDocuments() {
    const Documents = (await import('../v3/pages/Documents')).default
    clientStub.documentsApi.list.mockResolvedValue([])
    clientStub.documentsApi.subjects.mockResolvedValue({ subjects: [] })
    renderWithRouter(<Documents />)
    await settle()
  }

  it('普通用户：只读提示可见，上传/解析/科目维护等管理动作全部隐藏', async () => {
    await renderDocuments()
    expect(screen.getByText(/共享文档库为只读/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '批量上传' })).toBeNull()
    expect(screen.queryByText('题目识别')).toBeNull()
    expect(screen.queryByText('科目维护')).toBeNull()
    expect(screen.queryByText(/批量解析未入库/)).toBeNull()
    expect(screen.queryByText(/扫描归档根目录/)).toBeNull()
    expect(screen.queryByText(/识别当前列表/)).toBeNull()
    expect(screen.queryByText('全选当前')).toBeNull()
  })

  it('管理员：管理动作与批量栏可见，只读提示不出现', async () => {
    currentRole = 'admin'
    await renderDocuments()
    expect(screen.queryByText(/共享文档库为只读/)).toBeNull()
    expect(screen.getByRole('button', { name: '批量上传' })).toBeInTheDocument()
    expect(screen.getByText('题目识别')).toBeInTheDocument()
    expect(screen.getByText('科目维护')).toBeInTheDocument()
    expect(screen.getByText(/批量解析未入库/)).toBeInTheDocument()
    expect(screen.getByText(/扫描归档根目录/)).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ *
 * 文档详情抽屉
 * ------------------------------------------------------------------ */
describe('DocumentsDetail：题目预览与管理动作仅管理员可见', () => {
  const doc = {
    id: '7',
    filename: '讲义.pdf',
    subject: '数学',
    status: 'parsed',
    content_length: 1200,
    chunk_count: 3,
    has_local_file: true,
  }

  async function renderDetail() {
    const DocumentsDetail = (await import('../v3/pages/DocumentsDetail')).default
    clientStub.request.mockResolvedValue(null)
    renderWithRouter(
      <DocumentsDetail
        open
        doc={doc}
        tab="overview"
        onTab={() => {}}
        onClose={() => {}}
        backendOk
        onParse={() => {}}
        onAnalyze={() => {}}
        onGenerateQuiz={() => {}}
        onArchive={() => {}}
      />,
    )
    await settle()
  }

  it('普通用户：无「题目预览」页签，只有下载原文件', async () => {
    await renderDetail()
    expect(screen.queryByRole('tab', { name: /题目预览/ })).toBeNull()
    expect(screen.getByText(/只读预览：解析、智能分析与出题由管理员执行/)).toBeInTheDocument()
    expect(screen.getByText('下载原文件')).toBeInTheDocument()
    expect(screen.queryByText('智能分析')).toBeNull()
    expect(screen.queryByText('出题（5 道）')).toBeNull()
    expect(screen.queryByText('归档源文件')).toBeNull()
  })

  it('管理员：题目预览页签与分析/出题/归档动作可见', async () => {
    currentRole = 'admin'
    await renderDetail()
    expect(screen.getByRole('tab', { name: /题目预览/ })).toBeInTheDocument()
    expect(screen.getByText('智能分析')).toBeInTheDocument()
    expect(screen.getByText('出题（5 道）')).toBeInTheDocument()
    expect(screen.getByText('归档源文件')).toBeInTheDocument()
    expect(screen.queryByText(/只读预览/)).toBeNull()
  })
})

/* ------------------------------------------------------------------ *
 * 网盘联动
 * ------------------------------------------------------------------ */
describe('Pan：网盘授权与 API 配置仅管理员可见', () => {
  async function renderPan() {
    const Pan = (await import('../v3/pages/Pan')).default
    renderWithRouter(<Pan />)
    await settle()
  }

  it('普通用户：看不到 API 配置 / 去授权 / 退出授权，显示只读说明', async () => {
    await renderPan()
    expect(screen.getByText(/网盘凭据由管理员维护/)).toBeInTheDocument()
    expect(screen.queryByText('API 配置')).toBeNull()
    expect(screen.queryByText('去授权')).toBeNull()
    expect(screen.queryByText('退出授权')).toBeNull()
    expect(screen.queryByText(/^配置$|配置地址/)).toBeNull()
  })

  it('管理员：API 配置与去授权仍可见', async () => {
    currentRole = 'admin'
    await renderPan()
    expect(screen.queryByText(/网盘凭据由管理员维护/)).toBeNull()
    expect(screen.getByText('API 配置')).toBeInTheDocument()
    expect(screen.getByText('去授权')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ *
 * 设置 · AI 与模型
 * ------------------------------------------------------------------ */
describe('Settings：AI 与模型分区仅管理员可见', () => {
  async function renderSettings() {
    const Settings = (await import('../v3/pages/Settings')).default
    clientStub.goalsApi.examCalendar.mockResolvedValue({})
    renderWithRouter(<Settings />)
    await settle()
  }

  it('普通用户：AI 分区隐藏，且不探测本地模型状态', async () => {
    await renderSettings()
    expect(screen.queryByText('AI 与模型')).toBeNull()
    expect(clientStub.aiApi.localStatus).not.toHaveBeenCalled()
  })

  it('管理员：AI 分区可见并探测本地模型', async () => {
    currentRole = 'admin'
    await renderSettings()
    expect(screen.getByText('AI 与模型')).toBeInTheDocument()
    expect(clientStub.aiApi.localStatus).toHaveBeenCalled()
  })
})

/* ------------------------------------------------------------------ *
 * 知识地图 · 质量叠加层
 * ------------------------------------------------------------------ */
describe('KbMap：质量叠加接口只给管理员调用', () => {
  const tree = {
    tree: [{
      subject: '数学', knowledge_point_count: 1, outline_chapter_count: 1,
      chapters: [{ title: '极限', knowledge_point_count: 1, knowledge_points: [{ id: 1, name: '极限存在' }] }],
    }],
  }

  async function renderKbMap() {
    const KbMap = (await import('../v3/pages/KbMap')).default
    clientStub.taxonomyApi.subjects.mockResolvedValue({ subjects: [{ subject: '数学', question_count: 1 }] })
    clientStub.taxonomyApi.tree.mockResolvedValue(tree)
    clientStub.taxonomyApi.coverage.mockResolvedValue(null)
    clientStub.taxonomyApi.knowledgePoint.mockResolvedValue({ id: 1, name: '极限存在', subject: '数学' })
    clientStub.reviewApi.progress.mockResolvedValue(null)
    clientStub.reviewApi.due.mockResolvedValue({ items: [] })
    clientStub.quizApi.questions.mockResolvedValue({ total: 0 })
    renderWithRouter(<KbMap />)
    await settle(400)
  }

  it('普通用户：不请求 /quality 质量叠加层', { timeout: 15000 }, async () => {
    await renderKbMap()
    expect(clientStub.qualityApi.treeOverlay).not.toHaveBeenCalled()
  })

  it('管理员：请求质量叠加层', { timeout: 15000 }, async () => {
    currentRole = 'admin'
    await renderKbMap()
    expect(clientStub.qualityApi.treeOverlay).toHaveBeenCalled()
  })
})

/* ------------------------------------------------------------------ *
 * 择校推荐 · 专业覆盖面板
 * ------------------------------------------------------------------ */
describe('KaoyanRecommend：专业覆盖统计仅管理员请求', () => {
  async function renderRecommend() {
    const KaoyanRecommend = (await import('../v3/pages/KaoyanRecommend')).default
    renderWithRouter(<KaoyanRecommend />)
    await settle()
  }

  it('普通用户：不请求专业覆盖统计', async () => {
    await renderRecommend()
    expect(clientStub.qualityApi.majorCoverage).not.toHaveBeenCalled()
  })

  it('管理员：请求专业覆盖统计', async () => {
    currentRole = 'admin'
    await renderRecommend()
    expect(clientStub.qualityApi.majorCoverage).toHaveBeenCalled()
  })
})
