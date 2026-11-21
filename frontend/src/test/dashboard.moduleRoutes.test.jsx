import fs from 'node:fs'
import nodePath from 'node:path'
import { describe, it, expect } from 'vitest'
import { ALL_ENTRIES, KAOYAN_TABS, MOBILE_TABS, RELATED } from '../nav/navConfig'

/**
 * 仪表盘宫格 → 路由一致性（完善方案 13 §3.5）。
 *
 * 背景：Dashboard 里的 MODULE_ROUTE 是"宫格点击去哪"的第二份路由表，
 * 与 navConfig 漂移时用户点了会 404 或落到旧路径（历史上有过）。
 * 这里把两份表钉在一起：MODULE_ROUTE 的每个值必须能在 navConfig 里找到。
 */
function moduleRoutes() {
  const src = fs.readFileSync(nodePath.resolve(process.cwd(), 'src', 'v3', 'pages', 'Dashboard.jsx'), 'utf8')
  const line = src.split('\n').find((l) => l.includes('const MODULE_ROUTE'))
  if (!line) throw new Error('Dashboard.jsx 未找到 MODULE_ROUTE')
  const body = line.slice(line.indexOf('{') + 1, line.lastIndexOf('}'))
  const out = {}
  for (const part of body.split(',')) {
    const m = part.match(/(\w+)\s*:\s*'([^']+)'/)
    if (m) out[m[1]] = m[2]
  }
  return out
}

describe('Dashboard MODULE_ROUTE', () => {
  it('每个宫格目标都在 navConfig 单一导航源中', () => {
    const targets = new Set([
      ...ALL_ENTRIES.map((e) => e.to),
      ...MOBILE_TABS.map((t) => t.to),
      ...KAOYAN_TABS.map((t) => t.to),
      ...Object.values(RELATED).flat(),
    ])
    const missing = Object.entries(moduleRoutes())
      .filter(([, to]) => !targets.has(to.split('?')[0]))
      .map(([key, to]) => `${key} → ${to}`)
    expect(missing).toEqual([])
  })
})
