import React from 'react'
import fs from 'node:fs'
import nodePath from 'node:path'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ADMIN_LEGACY_REDIRECTS, ALL_ENTRIES, KAOYAN_TABS, MODULES, MOBILE_TABS, NAV_ADMIN, RELATED, crumbName, crumbParent, isAdminPath } from '../nav/navConfig'
import { toggleHidden, resetUiLayout } from '../hooks/useUiLayout'

/* 侧栏偏好测试验证的是「登录用户」的界面自定义：提供登录态，避免被访客导航过滤当成访客 */
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'tester', display_name: '测试用户', role: 'user' }, isAdmin: false, logout: vi.fn() }),
}))

/* 按行跟踪嵌套父路由：子路由的相对 path 拼到父级（/kaoyan、/admin）上 */
function appRoutes() {
  const app = fs.readFileSync(nodePath.resolve(process.cwd(), 'src', 'App.jsx'), 'utf8')
  const routes = new Set()
  let parent = ''
  for (const line of app.split('\n')) {
    const m = line.match(/<Route path="([^"]+)"/)
    if (m) {
      routes.add(m[1].startsWith('/') ? m[1] : `${parent}/${m[1]}`)
      const tail = line.trimEnd()
      if (m[1].startsWith('/') && tail.endsWith('>') && !tail.endsWith('/>')) parent = m[1]
    }
    if (line.includes('</Route>')) parent = ''
  }
  for (const [from] of ADMIN_LEGACY_REDIRECTS) routes.add(from)
  return routes
}

describe('navConfig 单一导航源', () => {
  it('每个导航入口都指向 App.jsx 里真实存在的路由', () => {
    const routes = appRoutes()
    const targets = [...ALL_ENTRIES.map((e) => e.to), ...MOBILE_TABS.map((t) => t.to), ...Object.values(RELATED).flat()]
    const dead = targets.map((to) => to.split('?')[0]).filter((p) => !routes.has(p))
    expect(dead).toEqual([])
  })

  it('入口路径不重复，且每条都带可搜索的描述与关键词', () => {
    const tos = ALL_ENTRIES.map((e) => e.to)
    expect(new Set(tos).size).toBe(tos.length)
    expect(ALL_ENTRIES.filter((e) => !e.desc || !e.kw?.length).map((e) => e.to)).toEqual([])
  })

  it('面包屑由同一份清单派生，动态路径走前缀规则', () => {
    /* 2026-10-19 信息架构精简：择校 AI 问答等 8 项退出导航（路由保留），面包屑改查仍在导航的子页 */
    expect(crumbName('/kaoyan/plan')).toBe('考研规划')
    expect(crumbName('/kaoyan/schools/42')).toBe('院校详情')
    expect(crumbName('/exam/2024/math1')).toBe('真题中心')
    expect(crumbName('/admin/subjects')).toBe('科目管理')
    expect(crumbName('/admin')).toBe('管理后台')
    expect(crumbParent('/admin/quality')).toEqual({ to: '/admin', label: '管理后台' })
    expect(crumbParent('/admin')).toBeNull()
    expect(crumbParent('/quiz')).toBeNull()
  })

  it('管理端入口全部落在 /admin 命名空间，且每条都有旧路径重定向', () => {
    expect(NAV_ADMIN.every((e) => isAdminPath(e.to) && e.roles?.includes('admin'))).toBe(true)
    expect(ADMIN_LEGACY_REDIRECTS.length).toBe(NAV_ADMIN.length)
    const studentTargets = MODULES.flatMap((m) => m.items.map((it) => it.to))
    expect(studentTargets.filter(isAdminPath)).toEqual([])
  })

  it('择校模块 Tab 与顶栏「择校」下拉同源', () => {
    const school = MODULES.find((m) => m.key === 'school').items
    expect(KAOYAN_TABS).toEqual(school.map((it) => ({ value: it.to, label: it.label })))
  })
})

describe('侧栏消费「界面自定义」偏好', () => {
  beforeEach(() => {
    resetUiLayout()
    vi.stubGlobal('scrollTo', vi.fn())
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  async function renderShell() {
    const { default: AppShell } = await import('../v3/shell')
    render(<MemoryRouter><AppShell><div /></AppShell></MemoryRouter>)
  }

  it('隐藏分组后侧栏不再渲染该分组', async () => {
    await renderShell()
    expect(screen.getByText('择校', { selector: '.v3-nav-group__label' })).toBeInTheDocument()
    act(() => { toggleHidden('navHidden', 'school') })
    expect(screen.queryByText('择校', { selector: '.v3-nav-group__label' })).toBeNull()
    expect(screen.queryByText('院校库')).toBeNull()
  })

  it('默认渲染全部分组', async () => {
    await renderShell()
    const labels = [...document.querySelectorAll('.v3-nav-group__label')].map((el) => el.textContent)
    for (const m of MODULES) expect(labels).toContain(m.title)
  })
})
