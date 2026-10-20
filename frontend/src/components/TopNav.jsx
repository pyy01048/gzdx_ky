import React, { useEffect, useRef, useState } from 'react'
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import useStore from '../store/useStore'
import CommandPalette from './CommandPalette'
import NoticeUnreadBadge from './NoticeUnreadBadge'
import SubjectSwitcher from './SubjectSwitcher'
import { Settings, Search, Brain, ChevronDown, Moon, Sun, User, LogOut, Shield } from './Icon'
import { useResolvedTheme } from './UI'
import { useUiLayout } from '../hooks/useUiLayout'
import { ADMIN_ROOT, visibleModules, visibleModulesFor, visibleOther } from '../nav/navConfig'
import { useAuth } from '../auth/AuthContext'
import { getBackendState, probeBackend, subscribeBackendState } from '../api/client'
import '../styles/nav.css'

function isRouteActive(pathname, item) {
  return item.exact ? pathname === item.to : pathname === item.to || pathname.startsWith(`${item.to}/`)
}

export default function TopNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const settings = useStore((s) => s.settings)
  const updateSettings = useStore((s) => s.updateSettings)
  /* 后端三态（P2-2）：online 不打扰；degraded 只说「部分服务异常」；
     只有 health 不可达（offline）才说「离线：数据来自本地缓存」。 */
  const [backend, setBackend] = useState(() => {
    try {
      const s = getBackendState?.()
      if (s && s.state) return s
      // 测试/异常环境里若拿到 thenable，吞掉拒绝，顶栏退回静态（不显示状态）
      if (s && typeof s.catch === 'function') s.catch(() => {})
    } catch { /* 兜底：无状态可读时不显示提示 */ }
    return { state: 'unknown', failures: [], checkedAt: 0 }
  })
  const [open, setOpen] = useState(null)
  const [scrolled, setScrolled] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const ref = useRef(null)
  const resolvedTheme = useResolvedTheme(settings.theme)
  const dark = resolvedTheme === 'dark'
  const layout = useUiLayout()
  const { user, isAdmin, logout } = useAuth()
  /* 访客模式：只展示公开模块；右上角放「登录」入口，登录后恢复完整导航 */
  const isGuest = !user
  const modules = visibleModulesFor(visibleModules(layout), isGuest)
  const showSettings = visibleOther(layout).some((n) => n.to === '/settings') && !isGuest
  const showAssistant = visibleOther(layout).some((n) => n.to === '/assistant') && !isGuest

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    const onKey = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(true)
      }
      if (event.key === 'Escape') setOpen(null)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('keydown', onKey)
    }
  }, [])

  useEffect(() => {
    const close = (event) => { if (!ref.current?.contains(event.target)) setOpen(null) }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [])

  useEffect(() => {
    let alive = true
    const onStatus = (s) => { if (alive && s && s.state) setBackend(s) }
    let unsub = () => {}
    try {
      const ret = subscribeBackendState(onStatus)
      if (typeof ret === 'function') unsub = ret
      else if (ret && typeof ret.catch === 'function') ret.catch(() => {})
    } catch { /* 订阅失败不影响导航本身 */ }
    const probe = () => {
      try {
        const p = probeBackend?.()
        if (p && typeof p.catch === 'function') p.catch(() => {})
      } catch { /* 探测失败保持上一次状态 */ }
    }
    probe()
    // 定时重探：接口恢复后顶栏能自己退回 online，不必等用户刷新
    const timer = setInterval(probe, 60000)
    return () => {
      alive = false
      unsub()
      clearInterval(timer)
    }
  }, [])

  const toggleTheme = () => updateSettings({ theme: dark ? 'light' : 'dark' })
  const activeModule = modules.find((module) => module.items.some((item) => isRouteActive(location.pathname, item)))?.key

  return (
    <>
      <header ref={ref} className={`topbar ${scrolled ? 'is-scrolled' : ''}`} aria-label="主导航">
        <div className="topbar-inner">
          <Link className="topbar-brand" to="/" aria-label="硕途 · 返回仪表盘">
            <span className="brand-mark" aria-hidden="true">硕</span>
            <strong className="brand-name">硕途</strong>
          </Link>
          <nav className="topbar-nav">
            {modules.map((module) => {
              const Icon = module.icon
              const expanded = open === module.key
              return (
                <div className="nav-dd" key={module.key}>
                  <button className={`nav-item ${activeModule === module.key ? 'is-active' : ''}`} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : module.key)}>
                    <Icon size={16} /><span>{module.title}</span><ChevronDown size={14} className="caret" />
                    {module.key === 'school' && !isGuest && <NoticeUnreadBadge className="nav-badge" />}
                  </button>
                  {expanded && <div className="nav-dd-panel"><div className="nav-dd-menu" role="menu">
                    {module.items.map((item) => <NavLink key={item.to} to={item.to} end={item.exact} role="menuitem" className={({ isActive }) => `nav-row ${isActive ? 'is-active' : ''}`} onClick={() => setOpen(null)}><span className="nav-row-icon"><Icon size={17} /></span><span>{item.label}</span></NavLink>)}
                  </div></div>}
                </div>
              )
            })}
            {showSettings && <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'is-active' : ''}`}><Settings size={16} /><span>设置</span></NavLink>}
            {isAdmin && <NavLink to={ADMIN_ROOT} className={({ isActive }) => `nav-item ${isActive ? 'is-active' : ''}`}><Shield size={16} /><span>管理后台</span></NavLink>}
          </nav>
          <div className="topbar-actions">
            {!isGuest && <SubjectSwitcher />}
            {/* 后端状态：online 不打扰；degraded 与 offline 用可解释的文案区分，
                避免个别 5xx 把整站说成「离线」 */}
            {backend.state === 'offline' && (
              <span className="topbar-status is-offline" role="status" title="后端不可达：页面展示本地缓存数据">
                <span className="dot offline" /> 离线：数据来自本地缓存
              </span>
            )}
            {backend.state === 'degraded' && (
              <span
                className="topbar-status is-offline"
                role="status"
                title={`${backend.failures.length} 项接口异常，不影响浏览：${backend.failures.map((f) => f.path).join('、')}`}
              >
                <span className="dot offline" /> 部分服务异常
              </span>
            )}
            <button className="topbar-icon-btn" onClick={() => setCommandOpen(true)} aria-label="搜索"><Search size={18} /></button>
            <button className="topbar-icon-btn" onClick={toggleTheme} aria-label={dark ? '切换到浅色模式' : '切换到深色模式'}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button>
            {showAssistant && <Link className="topbar-icon-btn" to="/assistant" aria-label="AI 助手"><Brain size={18} /></Link>}
            {user ? (
              <div className="nav-dd">
                <button className="topbar-icon-btn" aria-label="账号" aria-expanded={open === 'user'} onClick={() => setOpen(open === 'user' ? null : 'user')}><User size={18} /></button>
                {open === 'user' && <div className="nav-dd-panel is-end"><div className="nav-dd-menu" role="menu">
                  <div className="nav-row" aria-disabled="true"><span className="nav-row-icon"><User size={17} /></span><span>{user.display_name || user.username}{user.role === 'admin' ? ' · 管理员' : ''}</span></div>
                  <button className="nav-row" role="menuitem" onClick={() => { setOpen(null); logout() }}><span className="nav-row-icon"><LogOut size={17} /></span><span>退出登录</span></button>
                </div></div>}
              </div>
            ) : (
              /* 访客入口：登录收进右上角，不打断浏览 */
              <Link className="btn primary sm topbar-login" to="/login">登录</Link>
            )}
          </div>
        </div>
      </header>
      {commandOpen && <CommandPalette onClose={() => setCommandOpen(false)} />}
    </>
  )
}
