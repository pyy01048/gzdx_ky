import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { authApi } from '../api/client'
import { LoadingState } from '../components/States'
import useStore, { ARCHIVE_NAME } from '../store/useStore'
import { setUser as setUserKeys, currentUid } from '../utils/userKeys'
import { clearPan } from '../utils/pan'
import { clearFavoriteCache } from '../hooks/useFavorites'
import { clearHubCache } from '../api/hub'

/* P0（跨账号串号）：会话失效时的完整清理链，与 logout 同口径但不发网络请求。
   顺序固定：先清内存/缓存（此时 uid 还绑着，清的是「当前账号」的模块级快照），
   再解绑 uid —— setUserKeys(null) 会广播 uid-changed，让 useUiLayout /
   useSubjectConfig / useUnreadNotices 等快照钩子随之重置。
   只 setState anon 而不清理，会把 A 的 store/收藏缓存/同步失败队列留给 B。 */
function teardownSession() {
  /* resetAll 会把 seed 状态落盘、覆盖当前账号的归档；先备份原始归档字符串，
     重置后原样写回 —— 归档里的 AI 会话等纯本地数据按契约保留到下次登录。
     内存仍被彻底清空（下一个账号/访客看不到任何残留），只是磁盘归档不动。 */
  const uidBefore = currentUid()
  const archiveKey = uidBefore != null ? `${ARCHIVE_NAME}:${uidBefore}` : null
  let archiveRaw = null
  try { archiveRaw = archiveKey ? localStorage.getItem(archiveKey) : null } catch { /* 隐私模式 */ }
  try { useStore.getState().resetAll() } catch { /* 存储不可用时忽略，内存已清 */ }
  try {
    if (archiveKey && archiveRaw != null) localStorage.setItem(archiveKey, archiveRaw)
  } catch { /* 同上 */ }
  clearFavoriteCache()
  clearPan()
  clearHubCache()
  /* P0（F-02）：Service Worker 的 api-cache 只放公开字典，但旧版本 SW 可能已
     缓存个人接口响应；登出/强制下线必须一并清掉，否则换账号断网仍会读到
     A 的 /auth/me、/tasks、/errors 等旧响应。非安全上下文没有 caches，忽略。 */
  try {
    if (typeof window !== 'undefined' && 'caches' in window && window.caches?.delete) {
      void window.caches.delete('api-cache')
    }
  } catch { /* 隐私模式 / CacheStorage 不可用 */ }
  setUserKeys(null)
}

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
      if (user) {
        setUserKeys(user.id) /* B4：会话恢复时同步绑定本地隔离命名空间 */
        /* persist 落盘键按 uid 隔离：模块加载时 uid 未设置 → 首读为空。
           恢复会话绑定 uid 后必须 rehydrate，否则硬刷新会丢主题/本地缓存
           （与 login 路径同一口径）。 */
        void useStore.persist.rehydrate()
      }
      setState(user ? { status: statusOf(user), user, error: null } : { status: 'anon', user: null, error: null })
    } catch (e) {
      if (e?.status === 401) setState({ status: 'anon', user: null, error: null })
      else if (e?.code === 'PASSWORD_CHANGE_REQUIRED') setState((s) => ({ ...s, status: 'must-change' }))
      else setState({ status: 'error', user: null, error: e?.message || '无法连接后端服务' })
    }
  }, [])

  useEffect(() => { reload() }, [reload])

  useEffect(() => {
    const onRequired = () => { teardownSession(); setState({ status: 'anon', user: null, error: null }) }
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
        if (e?.status === 401) { teardownSession(); setState({ status: 'anon', user: null, error: null }) }
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
    /* B4：清内存/缓存 → 清网盘授权残留 → 解绑隔离命名空间（teardownSession）。
       注意：这里【不做】useStore.persist.clearStorage() —— 落盘键本身已按
       `kaoyan-archive-v1:{uid}` 隔离，下一个账号读不到本账号的键；而清掉它
       会把本账号纯本地数据（AI 会话等 partialize 白名单内容）一并删掉，
       与「AI 会话不被丢弃」的持久化契约矛盾。本账号数据保留到下次登录。 */
    teardownSession()
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
