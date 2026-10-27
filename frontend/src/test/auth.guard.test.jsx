import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ALL_ENTRIES, NAV_ADMIN, entriesFor, isAdminPath } from '../nav/navConfig'
import { authApi } from '../api/client'
import { AuthProvider, RequireAdmin, RequireAuth } from '../auth/AuthContext'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  authApi: { me: vi.fn(), refresh: vi.fn(), logout: vi.fn(), login: vi.fn(), changePassword: vi.fn() },
}))

const fail = (props) => Object.assign(new Error(props.message || 'x'), props)
const user = (role, extra = {}) => ({ id: 1, username: 'u', role, must_change_password: false, ...extra })

describe('角色可见导航', () => {
  it('普通用户看不到任何管理入口，管理员看到全部', () => {
    const userEntries = entriesFor(false)
    expect(userEntries.some((e) => isAdminPath(e.to))).toBe(false)
    expect(userEntries.length).toBe(ALL_ENTRIES.length - NAV_ADMIN.length)
    expect(entriesFor(true)).toEqual(ALL_ENTRIES)
  })
})

const renderGuarded = (inner) =>
  render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/x']}>
        <Routes>
          <Route path="/login" element={<div>登录页</div>} />
          <Route path="/force-change-password" element={<div>改密页</div>} />
          <Route path="/403" element={<div>无权限页</div>} />
          <Route path="/x" element={<RequireAuth>{inner}</RequireAuth>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  )

describe('路由守卫', () => {

  it('未登录（401）跳转登录页', async () => {
    authApi.me.mockImplementation(async () => { throw fail({ status: 401 }) })
    renderGuarded(<div>内页</div>)
    expect(await screen.findByText('登录页')).toBeTruthy()
  })

  it('/auth/me 200 空 body（null）按未登录处理，不放行', async () => {
    authApi.me.mockResolvedValue(null)
    renderGuarded(<div>内页</div>)
    expect(await screen.findByText('登录页')).toBeTruthy()
    expect(screen.queryByText('内页')).toBeNull()
  })

  it('须改密时跳转改密页', async () => {
    authApi.me.mockResolvedValue(user('user', { must_change_password: true }))
    renderGuarded(<div>内页</div>)
    expect(await screen.findByText('改密页')).toBeTruthy()
  })

  it('后端不可达显示重试卡片而非登录页', async () => {
    authApi.me.mockImplementation(async () => { throw fail({ message: '网络错误' }) })
    renderGuarded(<div>内页</div>)
    expect(await screen.findByText('无法连接后端服务')).toBeTruthy()
    expect(screen.queryByText('登录页')).toBeNull()
  })

  it('普通用户访问管理页进 403', async () => {
    authApi.me.mockResolvedValue(user('user'))
    renderGuarded(<RequireAdmin><div>管理页</div></RequireAdmin>)
    expect(await screen.findByText('无权限页')).toBeTruthy()
  })

  it('管理员可进入管理页', async () => {
    authApi.me.mockResolvedValue(user('admin'))
    renderGuarded(<RequireAdmin><div>管理页</div></RequireAdmin>)
    expect(await screen.findByText('管理页')).toBeTruthy()
  })
})
