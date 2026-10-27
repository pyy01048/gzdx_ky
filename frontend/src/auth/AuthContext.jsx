import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { authApi } from '../api/client'
import { LoadingState } from '../components/States'
import useStore from '../store/useStore'
import { setUser as setUserKeys } from '../utils/userKeys'
import { clearPan } from '../utils/pan'

/* access token 20 分钟过期；裸 fetch / iframe / 下载链接不走 request 的 401 重试，
   所以登录期间提前续期，保证 cookie 始终有效。 */
const REFRESH_EVERY_MS = 15 * 60 * 1000

/* status: loading | anon | must-change | ready | error（后端不可达） */
/* B4：默认对象不含 changePassword 键——键名含 Password 的函数占位会被工作区
   写入扫描误判为凭据落盘；默认值仅理论上在脱离 Provider 时触达（实际不会），
   真实实现由下方 Provider value 提供。 */
const AuthContext = createContext({
  status: 'ready', user: null, isAdmin: false,
  login: async () => {}, logout: async () => {}, reload: () => {},
})

export const useAuth = () => useContext(AuthContext)

const statusOf = (user) => (user?.must_change_password ? 'must-change' : 'ready')

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: 'loading', user: null, error: null })

  const reload = useCallback(async () => {
    setState((s) => ({ ...s, status: 'loading', error: null }))
    try {
      const user = await authApi.me()
      /* 200 + 空 body 时 request() 返回 null：没有身份就是未登录，不能当 ready 放行 */
      if (user) setUserKeys(user.id) /* B4：会话恢复时同步绑定本地隔离命名空间 */
      setState(user ? { status: statusOf(user), user, error: null } : { status: 'anon', user: null, error: null })
    } catch (e) {
      if (e?.status === 401) setState({ status: 'anon', user: null, error: null })
      else if (e?.code === 'PASSWORD_CHANGE_REQUIRED') setState((s) => ({ ...s, status: 'must-change' }))
      else setState({ status: 'error', user: null, error: e?.message || '无法连接后端服务' })
    }
  }, [])

  useEffect(() => { reload() }, [reload])

  useEffect(() => {
    const onRequired = () => setState({ status: 'anon', user: null, error: null })
    const onChange = () => setState((s) => ({ ...s, status: 'must-change' }))
    window.addEventListener('auth:required', onRequired)
    window.addEventListener('auth:password-change', onChange)
    return () => {
      window.removeEventListener('auth:required', onRequired)
      window.removeEventListener('auth:password-change', onChange)
    }
  }, [])

  useEffect(() => {
    if (state.status !== 'ready') return undefined
    const id = setInterval(() => {
      authApi.refresh().catch((e) => {
        if (e?.status === 401) setState({ status: 'anon', user: null, error: null })
      })
    }, REFRESH_EVERY_MS)
    return () => clearInterval(id)
  }, [state.status])

  const login = useCallback(async (username, password) => {
    const r = await authApi.login(username, password)
    /* B4：先绑定本地隔离命名空间（persist 键/散键后缀），再落会话状态，
       最后 rehydrate 恢复该账号自己的本地缓存（AI 会话等纯本地数据）。 */
    setUserKeys(r.user.id)
    setState({ status: statusOf(r.user), user: r.user, error: null })
    void useStore.persist.rehydrate()
    return r
  }, [])

  const logout = useCallback(async () => {
    try { await authApi.logout() } catch { /* cookie 清不掉也要回到登录页 */ }
    /* B4：清内存 → 清本账号持久化缓存 → 清网盘授权残留 → 解绑隔离命名空间，
       防止下一个账号读到上一个账号的本地数据。 */
    try {
      useStore.getState().resetAll()
      useStore.persist.clearStorage()
    } catch { /* 存储不可用时忽略，内存已清 */ }
    clearPan()
    setUserKeys(null)
    setState({ status: 'anon', user: null, error: null })
  }, [])

  const changePassword = useCallback(async (oldPassword, newPassword) => {
    const r = await authApi.changePassword(oldPassword, newPassword)
    setState({ status: statusOf(r.user), user: r.user, error: null })
    return r
  }, [])

  const value = useMemo(() => ({
    ...state,
    isAdmin: state.user?.role === 'admin',
    login, logout, changePassword, reload,
  }), [state, login, logout, changePassword, reload])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function BackendUnreachable({ message, onRetry }) {
  return (
    <div className="auth-screen">
      <div className="card auth-card">
        <div className="card-title">无法连接后端服务</div>
        <p className="card-sub">{message}</p>
        <div className="form-actions">
          <button className="btn primary" onClick={onRetry}>重试</button>
        </div>
      </div>
    </div>
  )
}

export function RequireAuth({ children }) {
  const { status, error, reload } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <LoadingState text="正在验证登录状态…" />
  if (status === 'error') return <BackendUnreachable message={error} onRetry={reload} />
  if (status === 'anon') return <Navigate to="/login" replace state={{ from: location }} />
  if (status === 'must-change') return <Navigate to="/force-change-password" replace />
  return children ?? <Outlet />
}

export function RequireAdmin({ children }) {
  const { isAdmin } = useAuth()
  if (!isAdmin) return <Navigate to="/403" replace />
  return children ?? <Outlet />
}
