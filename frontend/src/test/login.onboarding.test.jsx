/**
 * 首跑初始化触发（P1）：登录成功后拉 GET /goals，
 * goal.configured === false → /onboarding；must_change_password 优先；
 * 目标接口失败不阻塞登录。全部 mock，不触网。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, cleanup, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const hoisted = vi.hoisted(() => ({
  login: vi.fn(),
  goalsList: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  authApi: {
    login: vi.fn(), register: vi.fn(), forgotPassword: vi.fn(),
    resendVerification: vi.fn(), me: vi.fn(), refresh: vi.fn(), logout: vi.fn(),
  },
  goalsApi: { list: hoisted.goalsList },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ status: 'anon', login: hoisted.login }),
}))

/* Login 从壳里只拿 BrandMark；壳模块太重（导航/图表/AI 悬浮球），mock 掉 */
vi.mock('../v3/shell', () => ({
  BrandMark: () => null,
}))

import Login from '../v3/pages/Login'

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/onboarding" element={<div>初始化向导页</div>} />
        <Route path="/force-change-password" element={<div>强制改密页</div>} />
        <Route path="/hub" element={<div>今日中枢页</div>} />
        <Route path="/" element={<div>首页</div>} />
      </Routes>
    </MemoryRouter>
  )
}

async function submitLogin() {
  fireEvent.change(screen.getByLabelText('用户名 / 邮箱'), { target: { value: 'alice' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'Passw0rd!' } })
  await act(async () => {
    fireEvent.submit(screen.getByRole('button', { name: /登录/ }).closest('form'))
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  hoisted.login.mockResolvedValue({ must_change_password: false, user: { id: 1 } })
})

afterEach(cleanup)

describe('Login 首跑分流', () => {
  it('goal.configured === false 时进入 /onboarding', async () => {
    hoisted.goalsList.mockResolvedValue([{ configured: false }])
    renderLogin()
    await submitLogin()
    expect(await screen.findByText('初始化向导页')).toBeInTheDocument()
  })

  it('已配置目标（configured: true）按原目的地进入，不打扰', async () => {
    hoisted.goalsList.mockResolvedValue([{ configured: true }])
    renderLogin()
    await submitLogin()
    expect(await screen.findByText('首页')).toBeInTheDocument()
    expect(screen.queryByText('初始化向导页')).toBeNull()
  })

  it('响应缺 configured 字段时不误判为首跑', async () => {
    hoisted.goalsList.mockResolvedValue([{ university: '某大学' }])
    renderLogin()
    await submitLogin()
    expect(await screen.findByText('首页')).toBeInTheDocument()
  })

  it('must_change_password 优先于首跑判断，且不拉目标接口', async () => {
    hoisted.login.mockResolvedValue({ must_change_password: true, user: { id: 1 } })
    renderLogin()
    await submitLogin()
    expect(await screen.findByText('强制改密页')).toBeInTheDocument()
    expect(hoisted.goalsList).not.toHaveBeenCalled()
  })

  it('目标接口失败不阻塞登录，仍按原目的地进入', async () => {
    hoisted.goalsList.mockRejectedValue(new Error('后端不可达'))
    renderLogin()
    await submitLogin()
    expect(await screen.findByText('首页')).toBeInTheDocument()
  })

  it('登录失败停留在登录页并显示错误', async () => {
    hoisted.login.mockRejectedValue(new Error('用户名或密码错误'))
    renderLogin()
    await submitLogin()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('用户名或密码错误'))
    expect(hoisted.goalsList).not.toHaveBeenCalled()
  })
})
