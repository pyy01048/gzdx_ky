/**
 * Glass Lab（/glass · 毛玻璃交互式页面）回归：
 * 页面是纯前端动效页（后端零依赖），这里锁住四件事——
 *   1) 骨架完整渲染（调参台 / 追光卡 / 展台 / 翻转卡 / 迷你柱状图）；
 *   2) 预设芯片与滑杆联动（「磨砂」→ blur=36、CSS 变量跟写）；
 *   3) 课程胶囊多选与翻转卡状态；
 *   4) 调参台拖拽（指针事件驱动 translate，且合成事件缺坐标时不产生 NaN）。
 */
import React from 'react'
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import GlassLab from '../v3/pages/GlassLab'

beforeEach(() => {
  /* jsdom 无 PointerEvent：fireEvent.pointerDown 落到原生 Event，这里不 mock，正好验证降级路径 */
  document.documentElement.removeAttribute('data-theme')
})

afterEach(cleanup)

/* 用 act 包裹的原生 Event：可精确控制 clientX/Y 缺省（jsdom 的 PointerEvent 不存在，
   MouseEvent 回退会把缺省坐标赋 0，语义变成「指针在原点」而非「缺坐标」） */
import { act } from '@testing-library/react'
const fire = (el, type, props = {}) => {
  act(() => {
    const ev = new Event(type, { bubbles: true, cancelable: true })
    Object.assign(ev, { pointerId: 7, isPrimary: true, button: 0 }, props)
    el.dispatchEvent(ev)
  })
}

describe('GlassLab 毛玻璃交互实验室', () => {
  it('骨架完整：hero / 调参台 / 4 追光卡 / 3 环 / 3 玻璃分层 / 迷你柱状图 / 翻转卡', () => {
    render(<GlassLab />)
    expect(screen.getByText('毛玻璃交互实验室')).toBeInTheDocument()
    expect(screen.getByText('玻璃调参台')).toBeInTheDocument()
    expect(screen.getAllByText(/今日专注|掌握度|连续打卡|词句积累/)).toHaveLength(4)
    expect(document.querySelectorAll('.glab-rings__item')).toHaveLength(3)
    expect(document.querySelectorAll('.glab-layer')).toHaveLength(3)
    expect(document.querySelectorAll('.glab-weekbars__bar')).toHaveLength(7)
    expect(document.querySelector('.glab-flip')).not.toBeNull()
    /* 4 个滑杆 + 默认「标准」预设参数 */
    expect(document.querySelectorAll('.glab-slider')).toHaveLength(4)
    expect(document.querySelector('.glab-slider').value).toBe('16')
  })

  it('「磨砂」预设联动滑杆与 CSS 变量，「复原」回到标准', () => {
    render(<GlassLab />)
    fireEvent.click(screen.getByText('磨砂'))
    expect(document.querySelector('.glab-slider').value).toBe('36')
    const root = document.querySelector('.glab')
    expect(root.style.getPropertyValue('--gl-blur')).toBe('36px')
    expect(root.style.getPropertyValue('--gl-alpha')).toBe('0.82')
    expect(screen.getByText('磨砂').className).toContain('is-active')

    fireEvent.click(screen.getByText('复原'))
    expect(document.querySelector('.glab-slider').value).toBe('16')
    expect(root.style.getPropertyValue('--gl-blur')).toBe('16px')
  })

  it('课程胶囊可多选，翻转卡点击后翻面', () => {
    render(<GlassLab />)
    const eng = screen.getByText('考研英语').closest('button')
    const pol = screen.getByText('思想政治').closest('button')
    fireEvent.click(eng)
    fireEvent.click(pol)
    expect(eng.className).toContain('is-active')
    expect(pol.className).toContain('is-active')
    expect(eng.getAttribute('aria-pressed')).toBe('true')

    const flip = document.querySelector('.glab-flip')
    expect(flip.className).not.toContain('is-flipped')
    fireEvent.click(flip)
    expect(flip.className).toContain('is-flipped')
    expect(flip.getAttribute('aria-pressed')).toBe('true')
  })

  it('调参台拖拽：指针移动写 translate，缺坐标的合成事件不产生 NaN', () => {
    render(<GlassLab />)
    const panel = document.querySelector('.glab-panel')
    const head = document.querySelector('.glab-panel__head')
    expect(panel.style.translate).toBe('0px 0px')

    /* down 在 (100,100)，move 到 (160,124)：translate = 60px 24px */
    fire(head, 'pointerdown', { clientX: 100, clientY: 100 })
    fire(head, 'pointermove', { clientX: 160, clientY: 124 })
    expect(panel.style.translate).toBe('60px 24px')
    expect(panel.className).toContain('is-dragging')
    fire(head, 'pointerup', { clientX: 160, clientY: 124 })
    expect(panel.className).not.toContain('is-dragging')

    /* 新一轮 down 后 move 缺坐标（真实场景不存在，主要防合成事件/异常数据）：保持原位且无 NaN */
    fire(head, 'pointerdown', { clientX: 10, clientY: 10 })
    fire(head, 'pointermove')
    expect(panel.style.translate).toBe('60px 24px')
    expect(panel.style.translate).not.toMatch(/NaN/)

    /* 键盘微调（无障碍路径）：shift+← 步长 24 */
    fireEvent.keyDown(head, { key: 'ArrowLeft', shiftKey: true })
    expect(panel.style.translate).toBe('36px 24px')
    fire(head, 'pointerup', { clientX: 0, clientY: 0 })
  })
})
