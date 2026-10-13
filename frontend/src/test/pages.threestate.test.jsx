import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * 主要数据页三态回归（白屏整改验证）
 *
 * 覆盖页面：学习文库(Library) / 知识地图(KbMap) / 题库(Quiz+QuizBank) / 错题(ErrorReview)
 *   （仪表盘 Dashboard 的同类场景已在 pages.smoke.test.jsx 覆盖）
 *
 * 每个页面测两种后端故障形态：
 *   ① 接口 500（ApiError，形状与 api/client.js 一致）→ 必须显示错误态 + 重试按钮；
 *   ② 接口 200 但无 JSON 体（client.js resolve(null)）→ 不崩、不白屏。
 * ① 对应任务里的「接口异常降级」，② 对应更隐蔽的「空数据白屏」。
 * ------------------------------------------------------------------ */

/* ---------------------------------------------------------------- *
 * api/client 全故障 mock
 * 任何 api.xxxMethod() 一律 reject / resolve(null（按模式切换），
 * 不枚举方法——漏一个方法就意味着测试漏一条故障路径。
 * 注：导出名必须显式列出（vitest 会校验 mock 的导出清单），
 *     与 api/client.js 的实际导出保持同步。
 * ---------------------------------------------------------------- */
let mode = 'reject' // 'reject' | 'null'

function fail(name) {
  const err = new Error(`HTTP 500：${name}（测试模拟故障）`)
  err.name = 'ApiError'
  err.code = 'http_error'
  err.status = 500
  return () => (mode === 'reject' ? Promise.reject(err) : Promise.resolve(null))
}

function group() {
  const cache = new Map()
  return new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (typeof prop !== 'string') return undefined
        if (!cache.has(prop)) cache.set(prop, fail(prop))
        return cache.get(prop)
      },
    },
  )
}

const CLIENT_EXPORTS = [
  'request', 'ApiError', 'fileUrl',
  'dashboardApi', 'insightApi', 'tasksApi', 'goalsApi', 'quizApi', 'errorsApi',
  'flashcardsApi', 'documentsApi', 'kbImportApi', 'netdiskApi', 'importsApi',
  'aiApi', 'customizationApi', 'plannerApi', 'wordsApi', 'studyApi',
  'taxonomyApi', 'reviewApi', 'kbApi', 'systemApi', 'analysisApi',
  'quizSectionApi', 'paperApi', 'planningApi', 'qualityApi',
]

const clientStub = { DEFAULT_TIMEOUT: 30000 }
for (const name of CLIENT_EXPORTS) clientStub[name] = group()

vi.mock('../api/client', () => clientStub)

/* fire-and-forget 的 reject 不进入页面渲染路径，避免污染用例结果 */
beforeEach(() => {
  mode = 'reject'
  window.addEventListener('unhandledrejection', (e) => e.preventDefault?.())
})
afterEach(() => {
  cleanup()
  localStorage.clear()
})

function renderPage(Comp, route = '/') {
  const crashes = []
  const onError = (e) => crashes.push(e?.message || String(e))
  window.addEventListener('error', onError)
  const utils = render(
    <MemoryRouter initialEntries={[route]}>
      <Comp />
    </MemoryRouter>,
  )
  window.removeEventListener('error', onError)
  return { ...utils, crashes }
}

async function settle(ms = 300) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms))
  })
}

/* ========================================================================= *
 * 一、接口 500 → 错误态 + 重试按钮（不能白屏）
 * ========================================================================= */
describe('主要数据页：接口 500 时显示错误态而非白屏', () => {
  it('学习文库 Library：显示「资料加载失败」与重新加载按钮', async () => {
    const Library = (await import('../pages/Library')).default
    const { crashes, container } = renderPage(Library, '/library')
    await settle()

    expect(await screen.findByText('资料加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重新加载/ })).toBeInTheDocument()
    expect(container.firstChild, 'Library 在接口 500 时 DOM 为空 = 白屏').toBeTruthy()
    expect(crashes).toEqual([])
  })

  it('知识地图 KbMap：显示「知识地图加载失败」与重新加载按钮', async () => {
    const KbMap = (await import('../pages/KbMap')).default
    const { crashes, container } = renderPage(KbMap, '/kbmap')
    await settle()

    expect(await screen.findByText('知识地图加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重新加载/ })).toBeInTheDocument()
    expect(container.firstChild, 'KbMap 在接口 500 时 DOM 为空 = 白屏').toBeTruthy()
    expect(crashes).toEqual([])
  })

  it('题库 Quiz：显示「统计数据加载失败」与重试按钮', async () => {
    const Quiz = (await import('../pages/Quiz')).default
    const { crashes, container } = renderPage(Quiz, '/quiz')
    await settle()

    expect(await screen.findByText('统计数据加载失败')).toBeInTheDocument()
    // Quiz 页同时存在「暂无科目」空态的重试按钮，这里只要求存在可用重试入口
    expect(screen.getAllByRole('button', { name: '重试' }).length).toBeGreaterThan(0)
    expect(container.firstChild, 'Quiz 在接口 500 时 DOM 为空 = 白屏').toBeTruthy()
    expect(crashes).toEqual([])
  })

  it('题库管理 QuizBank：显示「题目列表加载失败」与重试按钮', async () => {
    const QuizBank = (await import('../pages/QuizBank')).default
    const { crashes, container } = renderPage(QuizBank, '/quiz-bank')
    await settle()

    expect(await screen.findByText('题目列表加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    expect(container.firstChild, 'QuizBank 在接口 500 时 DOM 为空 = 白屏').toBeTruthy()
    expect(crashes).toEqual([])
  })

  it('错题复盘 ErrorReview：显示「错题列表加载失败」与重新加载按钮', async () => {
    const ErrorReview = (await import('../pages/ErrorReview')).default
    const { crashes, container } = renderPage(ErrorReview, '/error-review')
    await settle()

    expect(await screen.findByText('错题列表加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重新加载/ })).toBeInTheDocument()
    expect(container.firstChild, 'ErrorReview 在接口 500 时 DOM 为空 = 白屏').toBeTruthy()
    expect(crashes).toEqual([])
  })
})

/* ========================================================================= *
 * 二、接口 200 但无 JSON 体（client.js resolve(null)）→ 不崩、不白屏
 *    比 500 更隐蔽：Promise fulfilled，页面的 .catch 兜底完全不会触发。
 * ========================================================================= */
describe('主要数据页：接口返回 null 时不崩不白屏', () => {
  beforeEach(() => {
    mode = 'null'
  })

  it.each([
    ['学习文库', '../pages/Library', '/library'],
    ['知识地图', '../pages/KbMap', '/kbmap'],
    ['刷题中心', '../pages/Quiz', '/quiz'],
    ['题库管理', '../pages/QuizBank', '/quiz-bank'],
    ['错题复盘', '../pages/ErrorReview', '/error-review'],
  ])('%s 收到 null 时仍渲染出页面', async (_name, modPath, route) => {
    const Comp = (await import(modPath)).default
    const { crashes, container } = renderPage(Comp, route)
    await settle(400)

    expect(container.firstChild, `${_name} 收到 null 时 DOM 为空 = 白屏`).toBeTruthy()
    expect(crashes, `${_name} 收到 null 时抛出了未捕获异常`).toEqual([])
    // 页面骨架仍在：页头标题可见（各页 page-title 不会因数据为空而消失）
    expect(container.textContent.length).toBeGreaterThan(0)
  })
})
