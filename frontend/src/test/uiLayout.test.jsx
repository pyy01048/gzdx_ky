/**
 * #25 界面自定义（仪表盘/导航显隐与排序）单测。
 *
 * 覆盖三层：偏好读写与容错（hook 本体）、偏好驱动的重新渲染（订阅）、
 * 设置页控件真的把偏好写进去（UiCustomize）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react'

vi.mock('../api/client', () => ({
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
import UiCustomize from '../components/UiCustomize'

beforeEach(() => {
  localStorage.clear()
  resetUiLayout()
})
afterEach(cleanup)

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
    expect(JSON.parse(localStorage.getItem(UI_LAYOUT_KEY)).dashHidden).toEqual(['hero'])

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
    moveInOrder('statsOrder', 'streak', 'up', ['minutes', 'tasks', 'review', 'streak'])
    moveInOrder('statsOrder', 'streak', 'up', ['minutes', 'tasks', 'review', 'streak'])
    expect(getUiLayout().statsOrder).toEqual(['minutes', 'streak', 'tasks', 'review'])
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
    expect(getUiLayout().statsHidden).toEqual([])
  })
})

describe('UiCustomize 设置页控件', () => {
  it('渲染五类可配置列表的真实条目名', () => {
    render(<UiCustomize />)
    expect(screen.getByText('侧边导航分组')).toBeInTheDocument()
    expect(screen.getByText('学习文库')).toBeInTheDocument()
    expect(screen.getByText('顶部倒计时横幅')).toBeInTheDocument()
    expect(screen.getByText('院校数据中心')).toBeInTheDocument()
  })

  it('取消勾选导航分组 → 写入 navHidden', () => {
    render(<UiCustomize />)
    fireEvent.click(screen.getByLabelText('院校数据中心 显示'))
    expect(getUiLayout().navHidden).toEqual(['kaoyan'])
  })

  it('恢复默认布局按钮清空隐藏项', () => {
    toggleHidden('dashHidden', 'notice')
    render(<UiCustomize />)
    fireEvent.click(screen.getByText('恢复默认布局'))
    expect(getUiLayout().dashHidden).toEqual([])
  })
})
