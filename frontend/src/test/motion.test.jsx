import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import {
  Reveal, Typewriter, ScrambleText, Marquee, PointerFx, ReadingProgress, useMagnetic,
} from '../v3/motion'
import { Button } from '../v3/ui'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const mockMedia = (matchFn) => {
  vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
    matches: matchFn(query),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }))
}

describe('motion primitives · 静态降级', () => {
  it('Reveal：无 IntersectionObserver 时内容直接可见', () => {
    render(<Reveal data-testid="rv">内容</Reveal>)
    const el = screen.getByTestId('rv')
    expect(el.className).toContain('is-revealed')
    expect(el.textContent).toBe('内容')
  })

  it('Typewriter：读屏始终拿到全文，ghost 占位全文', () => {
    render(<Typewriter text="一个账号打通备考全过程。" />)
    expect(screen.getByText('一个账号打通备考全过程。', { selector: '.v3-sr-only' })).toBeTruthy()
    expect(document.querySelector('.v3-typewriter__ghost').textContent).toBe('一个账号打通备考全过程。')
  })

  it('reduced-motion：Typewriter 立即显示全文，Reveal 立即显现', () => {
    mockMedia((q) => q.includes('prefers-reduced-motion'))
    render(
      <>
        <Typewriter text="降级全文" />
        <Reveal data-testid="rv2">区块</Reveal>
      </>,
    )
    expect(document.querySelector('.v3-typewriter__live').textContent).toBe('降级全文')
    expect(screen.getByTestId('rv2').className).toContain('is-revealed')
  })

  it('Marquee：复制组对读屏隐藏', () => {
    const { container } = render(<Marquee><span>清华大学</span></Marquee>)
    const groups = container.querySelectorAll('.v3-marquee__group')
    expect(groups.length).toBe(2)
    expect(groups[1].getAttribute('aria-hidden')).toBe('true')
  })

  it('ReadingProgress：渲染进度条元素', () => {
    const { container } = render(<ReadingProgress />)
    expect(container.querySelector('.v3-read-progress')).toBeTruthy()
  })
})

describe('motion primitives · 指针交互', () => {
  it('粗指针（默认 mock）：PointerFx 不写入任何变量', () => {
    render(<PointerFx data-testid="fx">卡片</PointerFx>)
    const el = screen.getByTestId('fx')
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 50, right: 100, bottom: 50 })
    fireEvent.pointerMove(el, { clientX: 50, clientY: 25 })
    expect(el.style.getPropertyValue('--mx')).toBe('')
  })

  it('fine pointer：Spotlight/Tilt/Magnetic 变量随指针写入，离开即清空', () => {
    mockMedia((q) => q === '(pointer: fine)')
    render(<PointerFx tilt={2} magnetic={4} data-testid="fx2">卡片</PointerFx>)
    const el = screen.getByTestId('fx2')
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 50, right: 100, bottom: 50 })
    fireEvent.pointerMove(el, { clientX: 100, clientY: 0 })
    expect(el.style.getPropertyValue('--mx')).toBe('100.0px')
    expect(el.style.getPropertyValue('--my')).toBe('0.0px')
    expect(el.style.getPropertyValue('--tilt-x')).toBe('2.00deg')
    expect(el.style.getPropertyValue('--tilt-y')).toBe('2.00deg')
    expect(el.style.getPropertyValue('--mag-x')).toBe('4.0px')
    fireEvent.pointerLeave(el)
    expect(el.style.getPropertyValue('--mx')).toBe('')
    expect(el.style.getPropertyValue('--tilt-x')).toBe('')
    expect(el.style.getPropertyValue('--mag-x')).toBe('')
  })

  it('useMagnetic：className 可被 Button 合并', () => {
    function Demo() {
      const mag = useMagnetic(4)
      return <Button {...mag}>登录</Button>
    }
    render(<Demo />)
    const btn = screen.getByRole('button', { name: '登录' })
    expect(btn.className).toContain('v3-btn')
    expect(btn.className).toContain('v3-magnetic')
  })
})

describe('motion primitives · 时间轴效果', () => {
  it('ScrambleText：解码结束后落回原文', async () => {
    render(<ScrambleText text="放在同一张地图上。" duration={120} />)
    await waitFor(
      () => {
        expect(document.querySelector('[aria-hidden="true"]').textContent).toBe('放在同一张地图上。')
      },
      { timeout: 2000 },
    )
    expect(screen.getByText('放在同一张地图上。', { selector: '.v3-sr-only' })).toBeTruthy()
  })

  it('Typewriter：逐字打出并最终完成', async () => {
    render(<Typewriter text="逐字出现" speed={10} />)
    await waitFor(
      () => {
        expect(document.querySelector('.v3-typewriter__live').textContent).toBe('逐字出现')
      },
      { timeout: 2000 },
    )
  })
})
