/**
 * 菜单定位回归：锚点贴近视口底部时，菜单必须翻到锚点上方。
 *
 * 旧实现只做 `top = min(innerHeight - 40, anchor.bottom + 8)`：菜单高 392px 时
 * top 被压到 920，整块掉出 960 高的视口，用户视觉上看到菜单、实际一项都点不到
 * （documents 卡片「更多操作」实测复现）。这里用 jsdom 的 rect 桩锁住翻转行为。
 */
import React, { useRef } from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { Menu } from '../v3/ui'

const MENU_H = 392
let anchorRect = { top: 885, bottom: 920, left: 597, right: 631, width: 34, height: 35 }

const rect = (o) => ({ ...o, x: o.left, y: o.top, toJSON() {} })

beforeEach(() => {
  vi.stubGlobal('innerHeight', 960)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function () {
    if (this.classList?.contains('v3-menu')) {
      const top = parseFloat(this.style.top) || 0
      return rect({ top, bottom: top + MENU_H, left: 435, right: 635, width: 200, height: MENU_H })
    }
    if (this.dataset?.testid === 'menu-anchor') return rect(anchorRect)
    return rect({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 })
  })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function Harness() {
  const ref = useRef(null)
  return (
    <>
      <span ref={ref} data-testid="menu-anchor">anchor</span>
      <Menu open anchorRef={ref} width={200}>
        <button type="button" role="menuitem">一项</button>
      </Menu>
    </>
  )
}

describe('Menu 定位', () => {
  it('下方放不下时翻到锚点上方，且整块留在视口内', async () => {
    render(<Harness />)
    await waitFor(() => expect(screen.getByRole('menu')).toBeInTheDocument())
    const menu = screen.getByRole('menu')
    // above = 885 - 392 - 8 = 485
    await waitFor(() => expect(parseFloat(menu.style.top)).toBe(485))
    expect(parseFloat(menu.style.top) + MENU_H).toBeLessThanOrEqual(960)
  })

  it('下方空间充足时保持锚点下方，不做无谓翻转', async () => {
    anchorRect = { top: 100, bottom: 135, left: 40, right: 74, width: 34, height: 35 }
    render(<Harness />)
    await waitFor(() => expect(screen.getByRole('menu')).toBeInTheDocument())
    const menu = screen.getByRole('menu')
    await waitFor(() => expect(parseFloat(menu.style.top)).toBe(143))
  })
})
