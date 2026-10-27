/**
 * #25 界面自定义（仪表盘/导航显隐与排序）单测。
 *
 * 覆盖三层：偏好读写与容错（hook 本体）、偏好驱动的重新渲染（订阅）、
 * 设置页控件真的把偏好写进去（UiCustomize）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react'

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
  DEFAULT_TIMEOUT: 30000,
  dashboardApi: { get: vi.fn(), stats: vi.fn(), weakness: vi.fn() },
  goalsApi: { subjects: vi.fn().mockResolvedValue({}) },
  kaoyanApi: { notices: vi.fn().mockResolvedValue([]) },
}))
vi.mock('../api/sync', () => ({
  default: { hydrate: vi.fn().mockResolvedValue(undefined), syncTask: vi.fn() },
  syncTask: vi.fn(),
  hydrate: vi.fn().mockResolvedValue(undefined),
}))

import {
  applyOrder, getUiLayout, toggleHidden, moveInOrder, resetUiLayout,
  useUiLayout, UI_LAYOUT_KEY,
} from '../hooks/useUiLayout'
import { UiCustomizeV3 } from '../v3/pages/Settings'
import { ukey, setUser } from '../utils/userKeys'

/* B4：布局键按 uid 隔离后，用例统一跑在 uid=1 命名空间里 */
beforeEach(() => {
  localStorage.clear()
  setUser(1)
  resetUiLayout()
})
afterEach(() => { cleanup(); setUser(null) })

function Probe() {
  const layout = useUiLayout()
  return <div data-testid="probe">{layout.dashHidden.join(',')}</div>
}

describe('useUiLayout 偏好读写', () => {
  it('applyOrder 按 order 排序，未登记的 id 保持原序追加在末尾', () => {
    const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
    expect(applyOrder(items, ['c', 'a']).map((i) => i.id)).toEqual(['c', 'a', 'b'])
    // 空 order 表示"用户没排过序"，绝不能把项打没
    expect(applyOrder(items, []).map((i) => i.id)).toEqual(['a', 'b', 'c'])
  })

  it('隐藏/恢复走同一开关，并即时落盘', () => {
    toggleHidden('dashHidden', 'hero')
    expect(getUiLayout().dashHidden).toEqual(['hero'])
    expect(JSON.parse(localStorage.getItem(ukey(UI_LAYOUT_KEY))).dashHidden).toEqual(['hero'])

    toggleHidden('dashHidden', 'hero')
    expect(getUiLayout().dashHidden).toEqual([])
  })

  it('排序表为空时 moveInOrder 先按完整清单补表再挪位', () => {
    const all = ['/tasks', '/quiz', '/kbmap']
    moveInOrder('modsOrder', '/kbmap', 'up', all)
    // 补表后 /kbmap 在第 3 位，上移一位 → 第 2 位（不是直接置顶）
    expect(getUiLayout().modsOrder).toEqual(['/tasks', '/kbmap', '/quiz'])
  })

  it('已到边界不动，且不会为无效操作写出一张冗余排序表', () => {
    moveInOrder('modsOrder', '/tasks', 'up', ['/tasks', '/quiz'])
    expect(getUiLayout().modsOrder).toEqual([])
    moveInOrder('modsOrder', '/quiz', 'down', ['/tasks', '/quiz'])
    expect(getUiLayout().modsOrder).toEqual([])

    toggleHidden('modsHidden', '/pan')
    toggleHidden('modsHidden', '/pan')
    expect(getUiLayout().modsHidden).toEqual([])
  })

  it('已有排序表时按表内位置交换', () => {
    const all = ['/tasks', '/quiz', '/kbmap']
    // 空表先按完整清单补全：kbmap 从第 3 位挪到第 2 位
    moveInOrder('modsOrder', '/kbmap', 'up', all)
    expect(getUiLayout().modsOrder).toEqual(['/tasks', '/kbmap', '/quiz'])
    // 第二条命令走「已有排序表」分支：kbmap 再上移一位到表头，其余相对顺序不变
    moveInOrder('modsOrder', '/kbmap', 'up', all)
    expect(getUiLayout().modsOrder).toEqual(['/kbmap', '/tasks', '/quiz'])
  })

  it('订阅者随偏好变化重渲染', () => {
    render(<Probe />)
    expect(screen.getByTestId('probe').textContent).toBe('')
    act(() => { toggleHidden('dashHidden', 'hero') })
    expect(screen.getByTestId('probe').textContent).toBe('hero')
  })

  it('resetUiLayout 清掉全部偏好', () => {
    toggleHidden('navHidden', 'kaoyan')
    resetUiLayout()
    expect(getUiLayout().navHidden).toEqual([])
    expect(getUiLayout().dashHidden).toEqual([])
  })

  it('userkeys:uid-changed 触发内存 prefs 重建（切号不串布局）', () => {
    toggleHidden('dashHidden', 'hero')
    expect(getUiLayout().dashHidden).toEqual(['hero']) // uid=1 的布局
    setUser(2) // 切账号：AuthContext.setUser 会广播该事件，这里直接模拟
    expect(getUiLayout().dashHidden).toEqual([]) // 账号 2 没有自己的隐藏项，不能沿用账号 1 的快照
    localStorage.setItem(ukey(UI_LAYOUT_KEY), JSON.stringify({ dashHidden: ['notice'] }))
    setUser(2) // userKeys 约定：重设同一 uid 也会广播，用于模拟存储侧变化后的重读
    expect(getUiLayout().dashHidden).toEqual(['notice'])
  })
})

describe('UiCustomizeV3 设置页控件', () => {
  it('渲染三类可配置列表的真实条目名', () => {
    render(<UiCustomizeV3 />)
    expect(screen.getByText('顶部导航分组')).toBeInTheDocument()
    expect(screen.getByText('导航「其他」入口')).toBeInTheDocument()
    expect(screen.getByText('仪表盘区块')).toBeInTheDocument()
    expect(screen.getByText('今日')).toBeInTheDocument()
    expect(screen.getByText('择校')).toBeInTheDocument()
    expect(screen.getByText('顶部倒计时横幅')).toBeInTheDocument()
    expect(screen.getByText('AI 助手')).toBeInTheDocument()
  })

  it('关闭导航分组开关 → 写入 navHidden', () => {
    render(<UiCustomizeV3 />)
    fireEvent.click(screen.getByLabelText('择校 显示'))
    expect(getUiLayout().navHidden).toEqual(['school'])
  })

  it('恢复默认布局按钮清空隐藏项', () => {
    toggleHidden('dashHidden', 'notice')
    render(<UiCustomizeV3 />)
    fireEvent.click(screen.getByText('恢复默认布局'))
    expect(getUiLayout().dashHidden).toEqual([])
  })
})
