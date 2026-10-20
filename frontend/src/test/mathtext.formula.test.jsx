import React from 'react'
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import MathText from '../components/MathText'

/* ============================================================
   MathText 的四种渲染分支
   - LaTeX（$...$ / $$...$$ / \(...\) / \[...\]）→ KaTeX
   - 行内公式图 ![alt](url)                  → <img>
   - 未回填占位符 [[F:n]]                    → 可见标记
   - 普通文本                                → 原样
   公式是 Word 题库的核心信息，任何一条分支退化成「什么都不显示」
   都等于丢数据，所以逐条锁住。
   ============================================================ */

describe('MathText：LaTeX 渲染', () => {
  it('行内 $...$ 渲染成 katex', () => {
    const { container } = render(<MathText text="设 $x^2+1$ 恒大于零" />)
    expect(container.querySelector('.katex')).toBeTruthy()
    expect(container.textContent).toContain('设')
    expect(container.textContent).toContain('恒大于零')
  })

  it('块级 $$...$$ 用 math-block 容器', () => {
    const { container } = render(<MathText text={'$$\\frac{a}{b}$$'} />)
    const block = container.querySelector('.math-block')
    expect(block).toBeTruthy()
    expect(block.querySelector('.katex')).toBeTruthy()
  })

  it('支持 \\(...\\) 与 \\[...\\]', () => {
    const a = render(<MathText text={'\\(a+b\\)'} />)
    expect(a.container.querySelector('.katex')).toBeTruthy()
    const b = render(<MathText text={'\\[a+b\\]'} />)
    expect(b.container.querySelector('.math-block')).toBeTruthy()
  })
})

describe('MathText：公式图（图片兜底路线）', () => {
  it('渲染 ![](url) 为 img，且补 /media/images 前缀', () => {
    const { container } = render(
      <MathText text="因为![公式](docx_formula/35/formula_00001.gif)所以" />
    )
    const img = container.querySelector('img.math-formula-img')
    expect(img).toBeTruthy()
    expect(img.getAttribute('src')).toBe('/media/images/docx_formula/35/formula_00001.gif')
    expect(img.getAttribute('alt')).toBe('公式')
    // 前后文本不能丢
    expect(container.textContent).toContain('因为')
    expect(container.textContent).toContain('所以')
  })

  it('已经带 / 的绝对路径不重复加前缀', () => {
    const { container } = render(
      <MathText text="![f](/media/images/a/b.png)" />
    )
    const img = container.querySelector('img.math-formula-img')
    expect(img.getAttribute('src')).toBe('/media/images/a/b.png')
  })

  it('http 外链保持原样', () => {
    const { container } = render(
      <MathText text="![f](https://cdn.example.com/x.png)" />
    )
    expect(container.querySelector('img').getAttribute('src')).toBe(
      'https://cdn.example.com/x.png'
    )
  })

  it('同一段里公式图与 LaTeX 可以混排', () => {
    const { container } = render(
      <MathText text="由图 ![f](q.png) 得 $a=1$" />
    )
    expect(container.querySelector('img.math-formula-img')).toBeTruthy()
    expect(container.querySelector('.katex')).toBeTruthy()
  })
})

describe('MathText：未回填占位符', () => {
  it('[[F:3]] 渲染成可见标记而不是被吞掉', () => {
    const { container } = render(<MathText text="设函数[[F:3]]在区间内" />)
    const ph = container.querySelector('.math-formula-placeholder')
    expect(ph).toBeTruthy()
    expect(ph.getAttribute('title')).toContain('3')
    // 关键：占位符不能被静默删除，也不能把原文里的 [[F:3]] 原样吐给用户
    expect(container.textContent).not.toContain('[[F:')
    expect(container.textContent).toContain('设函数')
  })
})

describe('MathText：安全退化', () => {
  it('坏 LaTeX 退回原文，不返回空白', () => {
    const { container } = render(<MathText text="前 $\\frac{1$ 后" />)
    // 要么渲染成功，要么保留原文；绝不能整段消失
    expect(container.textContent.length).toBeGreaterThan(0)
  })

  it('空文本不报错', () => {
    const { container } = render(<MathText text="" />)
    expect(container).toBeTruthy()
  })

  it('纯文本原样输出', () => {
    const { container } = render(<MathText text="这是一段没有公式的普通文字" />)
    expect(container.textContent).toBe('这是一段没有公式的普通文字')
    expect(container.querySelector('.katex')).toBeNull()
  })
})
