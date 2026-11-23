import { Suspense } from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup, fireEvent, waitFor } from '@testing-library/react'
import FunctionPlot from '../v3/pages/tools/FunctionPlot'
import FormulaVerify from '../v3/pages/tools/FormulaVerify'
import LatexStudio from '../v3/pages/tools/LatexStudio'
import DiagramStudio from '../v3/pages/tools/DiagramStudio'

/* ------------------------------------------------------------------ *
 * 站内计算工具套件冒烟测试（工具波交付）
 *  只验证「真在算」：函数图像默认曲线在 [-10,10] 应有 3 个零点；
 *  恒等式 sin²x+cos²x=1 应判「成立」；矩阵行列式应给出精确 -3；
 *  KaTeX 应渲染出 .katex 节点；框图编辑器应能挂载出源码/预览双栏。
 * ------------------------------------------------------------------ */

afterEach(cleanup)

const shell = (ui) => render(<Suspense fallback={null}>{ui}</Suspense>)

describe('函数图像生成器', () => {
  it('默认两条曲线在 [-10,10]：零点 10（3+7）· 极值 8（2+6）· 有交点', async () => {
    const { container } = shell(<FunctionPlot onClose={() => {}} />)
    expect(container.querySelector('canvas')).toBeTruthy()
    await waitFor(() => {
      const status = container.querySelector('.v3-tg-status')?.textContent || ''
      expect(status).toContain('零点 10')
      expect(status).toContain('极值 8')
      expect(status).toContain('交点 3')
    }, { timeout: 10000 })
  })
})

describe('公式验算器', () => {
  it('恒等核验：sin^2+cos^2=1 判为在随机点上成立', async () => {
    const { container } = shell(<FormulaVerify onClose={() => {}} />)
    await waitFor(() => {
      expect(container.textContent).toContain('随机点上左右两边数值一致')
    }, { timeout: 10000 })
  })

  it('矩阵：det([[1,2,3],[4,5,6],[7,8,10]]) 精确等于 -3', async () => {
    const { container, getByText } = shell(<FormulaVerify onClose={() => {}} />)
    fireEvent.click(getByText('矩阵'))
    fireEvent.click(getByText('行列式'))
    await waitFor(() => {
      expect(container.textContent).toContain('det(A) = -3')
    })
  })
})

describe('LaTeX 工作台', () => {
  it('默认公式经 KaTeX 实时渲染', async () => {
    const { container } = shell(<LatexStudio onClose={() => {}} />)
    await waitFor(() => {
      expect(container.querySelector('.katex')).toBeTruthy()
    })
  })

  it('mhchem 化学式可渲染', async () => {
    const { container } = shell(<LatexStudio onClose={() => {}} />)
    const ta = container.querySelector('.v3-tl-ta')
    fireEvent.change(ta, { target: { value: '\\ce{H2O}' } })
    await waitFor(() => {
      expect(container.querySelector('.v3-tl-render .katex')).toBeTruthy()
      expect(container.querySelector('.v3-tools-error')).toBeNull()
    })
  })
})

describe('框图编辑器', () => {
  it('挂载源码 + 预览双栏与模板条', () => {
    const { container } = shell(<DiagramStudio onClose={() => {}} />)
    expect(container.querySelector('.v3-td-ta')).toBeTruthy()
    expect(container.querySelector('.v3-td-preview')).toBeTruthy()
    expect(container.querySelectorAll('.v3-td-templates .v3-chip').length).toBeGreaterThan(3)
  })
})
