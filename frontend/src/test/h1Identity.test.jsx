/**
 * P1 导航 / 首屏体验回归（批次 B）。
 * 覆盖：QA-08 H1 身份、QA-30 首屏稳定标题、QA-03 移动 Tab 访客过滤、
 *       QA-20 路由级错误边界、QA-21 RELATED 语义、QA-22 Tab 高亮、
 *       QA-18 首帧主题、QA-15 工具按需加载。
 */
import fs from 'node:fs'
import nodePath from 'node:path'
import { describe, it, expect } from 'vitest'
import {
  ADMIN_LEGACY_REDIRECTS, KAOYAN_TABS, MODULES, MOBILE_TABS, RELATED, ROUTE_META,
  routeMeta, visibleModules, visibleModulesFor,
} from '../nav/navConfig'

const read = (rel) => fs.readFileSync(nodePath.resolve(process.cwd(), rel), 'utf8')

function sourceFiles(dir, out = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === 'node_modules' || ent.name === 'test') continue
    const full = nodePath.join(dir, ent.name)
    if (ent.isDirectory()) sourceFiles(full, out)
    else if (/\.(js|jsx)$/.test(ent.name)) out.push(full)
  }
  return out
}

describe('ROUTE_META 单一事实源（QA-08 / QA-30）', () => {
  const CORE = {
    '/quiz': '刷题中心',
    '/hub': '今日中枢',
    '/words': '单词记忆',
    '/cards': '记忆卡片',
    '/kaoyan/plan': '考研规划',
    '/kaoyan/schools': '院校库',
  }

  it('6 条核心路由的 H1 身份映射逐一相等', () => {
    for (const [path, h1] of Object.entries(CORE)) {
      expect(ROUTE_META[path].h1, path).toBe(h1)
      expect(routeMeta(path).h1, path).toBe(h1)
    }
  })

  it('/quiz 不再有真题文案串页，H1 固定为刷题中心', () => {
    const src = read('src/v3/pages/QuizHome.jsx')
    expect(src).not.toContain('历年真题，按知识点、按年份精准刷')
    expect(src).toContain("title={isExamRoute ? '真题中心' : '刷题中心'}")
  })

  it('Hub 的 H1 固定「今日中枢」，问候语降级为副信息', () => {
    const src = read('src/v3/pages/Hub.jsx')
    expect(src).toContain('<h1 className="hub-hero__title">今日中枢</h1>')
    expect(src).toContain('{greeting()}，{providerName}')
  })

  it('/tools 初始视口有稳定 H1（页头 sticky），标题与 ROUTE_META 一致', () => {
    const page = read('src/v3/pages/Tools.jsx')
    const css = read('src/v3/styles/tools-v3.css')
    expect(page).toContain('title="学习工具箱"')
    expect(ROUTE_META['/tools'].h1).toBe('学习工具箱')
    expect(css).toContain('.v3-tools > .v3-page-head')
    expect(css).toContain('position: sticky')
  })

  it('登录页双分支 H1 语义统一且都从 routeMeta 派生，ScrambleText 双节点未破坏', () => {
    const src = read('src/v3/pages/Login.jsx')
    expect(src).toContain("{routeMeta('/login').h1}")
    expect(src).toContain('<ScrambleText text="放在同一张地图上。"')
    expect(src).not.toContain('欢迎来到硕途')
  })

  it('document.title 散落点收敛为 0（仅 App.RouteTitle 一处）', () => {
    const files = sourceFiles(nodePath.resolve(process.cwd(), 'src'))
    const hits = files.filter((f) => /document\.title\s*=/.test(fs.readFileSync(f, 'utf8')))
    expect(hits).toHaveLength(1)
    expect(nodePath.basename(hits[0])).toBe('App.jsx')
  })
})

describe('移动端 Tab 访客过滤与文案（QA-03）', () => {
  it('Tab 文案等于落点 H1（登录态用 ROUTE_META 派生）', () => {
    for (const t of MOBILE_TABS) {
      expect(t.label, t.to).toBe(routeMeta(t.to).h1)
    }
    expect(MOBILE_TABS).toHaveLength(5)
  })

  it('访客经 visibleModulesFor 过滤后 ≤3 个 Tab，且不含 /quiz、/error-review', () => {
    const groups = visibleModulesFor(visibleModules({}), true)
    const tabs = MOBILE_TABS.filter((t) => groups.some((g) => g.key === t.group && g.items.some((it) => it.to === t.to)))
    expect(tabs.length).toBeLessThanOrEqual(3)
    expect(tabs.map((t) => t.to)).not.toContain('/quiz')
    expect(tabs.map((t) => t.to)).not.toContain('/error-review')
  })

  it('Sidebar 与 MobileNav 共用 visibleModulesFor（源码级门禁）', () => {
    const shell = read('src/v3/shell/index.jsx')
    const sidebar = shell.slice(shell.indexOf('function Sidebar'), shell.indexOf('function GlobalSubjectSwitcher'))
    const mobile = shell.slice(shell.indexOf('function MobileNav'), shell.indexOf('export default function AppShell'))
    expect(sidebar).toContain('visibleModulesFor(visibleModules(layout), isGuest)')
    expect(mobile).toContain('visibleModulesFor(visibleModules(layout), !user)')
  })
})

describe('路由级错误边界（QA-20）', () => {
  it('AppShell 的 Outlet 外层包路由级 ErrorBoundary，全局边界仍保留', () => {
    const src = read('src/App.jsx')
    expect(src).toContain('<ErrorBoundary>\n          <Outlet />')
    expect(src.match(/<ErrorBoundary>/g)).toHaveLength(2)
  })

  it('componentStack 单独上报一次，重试 2 次出现转人工', () => {
    const src = read('src/components/ErrorBoundary.jsx')
    expect(src).toContain("console.warn('[ErrorBoundary] componentStack:'")
    expect(src).toContain('请转人工')
  })
})

describe('RELATED 语义与 Tab 高亮（QA-21 / QA-22）', () => {
  it('RELATED 目标不在重定向集合内', () => {
    const app = read('src/App.jsx')
    const redirects = new Set(ADMIN_LEGACY_REDIRECTS.map(([from]) => from))
    for (const m of app.matchAll(/<Route path="([^"]+)" element=\{<Navigate/g)) redirects.add(m[1])
    const targets = Object.values(RELATED).flat().map((to) => to.split('?')[0])
    expect(targets.filter((to) => redirects.has(to))).toEqual([])
  })

  it('择校 Tab 数量与导航源绑定，/kaoyan/guide 有身份元信息', () => {
    const school = MODULES.find((m) => m.key === 'school').items
    expect(KAOYAN_TABS).toHaveLength(school.length)
    expect(ROUTE_META['/kaoyan/guide'].h1).toBe('择校数据中心')
    expect(read('src/App.jsx')).not.toContain('11 个 tab')
  })
})

describe('首帧主题（QA-18）', () => {
  function runThemeScript(storage) {
    const html = read('index.html')
    const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
      .map((m) => m[1]).find((s) => s.includes('kaoyan-archive-v1'))
    expect(script).toBeTruthy()
    const attrs = []
    const fakeWindow = {
      localStorage: { getItem: (k) => (Object.prototype.hasOwnProperty.call(storage, k) ? storage[k] : null) },
      matchMedia: () => ({ matches: false }),
    }
    const fakeDocument = {
      documentElement: { setAttribute: (k, v) => attrs.push([k, v]) },
      querySelector: () => ({ setAttribute: () => {} }),
    }
    new Function('window', 'document', script)(fakeWindow, fakeDocument)
    return attrs.find(([k]) => k === 'data-theme')?.[1]
  }

  const dark = JSON.stringify({ state: { settings: { theme: 'dark' } } })

  it('登录态按 uid 归档键在首帧写入 dark', () => {
    expect(runThemeScript({ 'kaoyan-active-uid': '7', 'kaoyan-archive-v1:7': dark })).toBe('dark')
  })

  it('访客回落 :anon 键；裸键不再被误读', () => {
    expect(runThemeScript({ 'kaoyan-archive-v1:anon': dark })).toBe('dark')
    expect(runThemeScript({ 'kaoyan-archive-v1': dark })).toBe('light')
  })
})

describe('工具箱按需加载（QA-15）', () => {
  it('4 个重库工具只在 TOOL_LOADERS 里二次 dynamic import，没有顶层 lazy 常量', () => {
    const src = read('src/v3/pages/Tools.jsx')
    expect(src).toContain('const TOOL_LOADERS')
    for (const name of ['FunctionPlot', 'FormulaVerify', 'LatexStudio', 'DiagramStudio']) {
      expect(src).toContain(`() => import('./tools/${name}')`)
      expect(src).not.toContain(`const ${name} = lazy(`)
    }
    expect(fs.existsSync(nodePath.resolve(process.cwd(), 'scripts/check-tool-chunks.mjs'))).toBe(true)
  })
})
