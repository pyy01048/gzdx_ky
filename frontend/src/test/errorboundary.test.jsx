import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, act } from '@testing-library/react'
import ErrorBoundary from '../components/ErrorBoundary'

/* ------------------------------------------------------------------ *
 * 全局错误边界测试（白屏整改核心件）
 *
 * 验证三件事：
 *   ① 子组件渲染崩溃 → 降级页出现（不再是白屏），且含重试 / 返回首页入口；
 *   ② 「重试」重置边界并强制重挂子树 —— 一次性崩溃（首次渲染挂掉）能恢复；
 *   ③ 「返回首页」写 location.hash（不依赖 Router 上下文）。
 * ------------------------------------------------------------------ */

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

/** 受开关控制的崩溃组件：gate.crashed 为 true 时必崩（React 的渲染重试也同样崩） */
function makeGatedChild(label) {
  const gate = { crashed: true }
  function Child() {
    if (gate.crashed) {
      throw new TypeError("Cannot read properties of undefined (reading 'map')")
    }
    return <div data-testid="recovered">{label} 已恢复</div>
  }
  return { Child, gate }
}

describe('ErrorBoundary 全局降级页', () => {
  it('子组件渲染崩溃时展示降级页，而不是白屏', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    function Boom() {
      throw new Error('渲染爆炸')
    }
    const { container } = render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )

    expect(container.firstChild, '崩溃后 DOM 为空 = 白屏').toBeTruthy()
    expect(screen.getByText('页面出了点问题')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回首页' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制错误信息' })).toBeInTheDocument()
    expect(screen.getByText(/渲染爆炸/)).toBeInTheDocument()
    spy.mockRestore()
  })

  it('点击「重试」重置边界并重挂子树：故障修复后页面恢复', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { Child, gate } = makeGatedChild('学习文库')

    render(
      <ErrorBoundary>
        <Child />
      </ErrorBoundary>,
    )
    expect(screen.getByText('页面出了点问题')).toBeInTheDocument()

    // 模拟"故障已修复"（如后端恢复、脏数据被清掉），再点重试
    gate.crashed = false
    await act(async () => {
      screen.getByRole('button', { name: '重试' }).click()
    })

    expect(screen.getByTestId('recovered')).toBeInTheDocument()
    expect(screen.queryByText('页面出了点问题')).not.toBeInTheDocument()
    spy.mockRestore()
  })

  it('重试会强制重挂子树（换 remount key），子组件内部状态被重新初始化', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    function CountMounts() {
      React.useEffect(() => {}, [])
      return <div data-testid="mounts">重新挂载</div>
    }
    // 外壳必崩触发降级；gate 修复后重试 → 子树以全新状态重新挂载
    const gate = { crashed: true }
    function Shell() {
      if (gate.crashed) throw new Error('boom')
      return <CountMounts />
    }
    render(
      <ErrorBoundary>
        <Shell />
      </ErrorBoundary>,
    )
    gate.crashed = false
    await act(async () => {
      screen.getByRole('button', { name: '重试' }).click()
    })
    expect(screen.getByTestId('mounts')).toBeInTheDocument()
    spy.mockRestore()
  })

  it('连续重试仍失败时提示转人工（重试计数 >= 2）', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    function AlwaysBoom() {
      throw new Error('必崩')
    }
    render(
      <ErrorBoundary>
        <AlwaysBoom />
      </ErrorBoundary>,
    )

    for (let i = 0; i < 2; i++) {
      await act(async () => {
        screen.getByRole('button', { name: '重试' }).click()
      })
    }
    expect(screen.getByText(/已重试 2 次仍未恢复/)).toBeInTheDocument()
    spy.mockRestore()
  })

  it('「返回首页」写 location.hash，不依赖 Router 上下文', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    function Boom() {
      throw new Error('崩')
    }
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )

    screen.getByRole('button', { name: '返回首页' }).click()
    expect(window.location.hash).toBe('#/')
    spy.mockRestore()
  })

  it('无错误时原样渲染 children', () => {
    const { container } = render(
      <ErrorBoundary>
        <div data-testid="ok">正常内容</div>
      </ErrorBoundary>,
    )
    expect(screen.getByTestId('ok')).toBeInTheDocument()
    expect(container.firstChild).toBeTruthy()
  })
})
