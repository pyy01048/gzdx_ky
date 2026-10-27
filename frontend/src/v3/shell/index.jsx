import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import useStore from '../../store/useStore'
import { useAuth } from '../../auth/AuthContext'
import { useResolvedTheme } from '../../components/UI'
import { examDaysLeft, resolveExamDate } from '../../utils/exam'
import { chatCompletion, defaultProvider, hasAiConfigured } from '../../utils/api'
import { taxonomyApi } from '../../api/client'
import {
  MODULES, NAV_OTHER, NAV_ADMIN, MOBILE_TABS, crumbName, visibleModules, visibleModulesFor,
  visibleOther,
} from '../../nav/navConfig'
import { useUiLayout } from '../../hooks/useUiLayout'
import {
  Activity, ArrowRight, BarChart3, Bell, BookOpen, CalendarClock, ChevronRight, Clock,
  Cloud, Command, Cpu, Database, FileText, Flag, FolderOpen, Gauge, Globe, Home, Layers,
  Library, ListChecks, LogOut, Map, Menu, Moon, NotebookPen, PanelLeftClose, PanelLeftOpen,
  School, Search, Send, Settings, Sparkles, Star, Sun, Target, Type, User, Wand, X, Zap,
} from '../icons'
import {
  Avatar, Badge, Button, Dialog, IconButton, Kbd, MenuItem, Select, Segmented, Sheet, ToastHost, cx, toast,
} from '../ui'

/* -------------------------------------------------------------------------- */
/* Navigation icons                                                           */
/* -------------------------------------------------------------------------- */
const ICON_BY_PATH = {
  '/': Home,
  '/hub': Sparkles,
  '/tasks': ListChecks,
  '/planner': CalendarClock,
  '/profile': User,
  '/library': Library,
  '/documents': FileText,
  '/textbooks': BookOpen,
  '/pan': Cloud,
  '/knowledge': Map,
  '/quiz': Target,
  '/exam': FileText,
  '/cards': Layers,
  '/words': Type,
  '/codebank': Cpu,
  '/error-review': Activity,
  '/notebook': NotebookPen,
  '/insights': BarChart3,
  '/favorites': Star,
  '/timeline': Clock,
  '/kaoyan': School,
  '/kaoyan/notices': Bell,
  '/kaoyan/plan': Flag,
  '/glass': Wand,
  '/assistant': Sparkles,
  '/settings': Settings,
  '/admin/overview': Database,
  '/admin/users': User,
  '/admin/subjects': Layers,
  '/admin/quiz-bank': BookOpen,
  '/admin/quality': Gauge,
  '/admin/schools': School,
  '/admin/crawl-sources': Globe,
  '/admin/kb-import': FolderOpen,
  '/admin/model': Cpu,
}

const navIcon = (to) => ICON_BY_PATH[to] || BookOpen

/* -------------------------------------------------------------------------- */
/* Logo                                                                       */
/* -------------------------------------------------------------------------- */
export function BrandMark({ size = 38 }) {
  return (
    <span className="v3-brand__mark" style={{ width: size, height: size }}>
      <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M12 2.4 14.3 9l6.6 2.3-6.6 2.3L12 20.2l-2.3-6.6L3.1 11.3 9.7 9z"
          fill="#fff"
          fillOpacity="0.96"
        />
        <circle cx="19.2" cy="4.6" r="1.4" fill="#fff" fillOpacity="0.85" />
      </svg>
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* Sidebar                                                                    */
/* -------------------------------------------------------------------------- */
function NavItem({ item, active, onNavigate, collapsed }) {
  const Icon = navIcon(item.to)
  const isAI = item.to === '/assistant'
  return (
    <Link
      to={item.to}
      className={cx('v3-nav-item', active && 'is-active', isAI && 'v3-nav-item--ai')}
      onClick={onNavigate}
      title={collapsed ? item.label : undefined}
      aria-current={active ? 'page' : undefined}
    >
      <span className="v3-nav-item__icon" data-idle={active ? 'breathe' : undefined}>
        <Icon size={19} data-active={active || undefined} />
      </span>
      <span className="v3-nav-item__text">{item.label}</span>
      {item.badge ? <span className="v3-nav-item__badge">{item.badge}</span> : null}
    </Link>
  )
}

function Sidebar({ collapsed, setCollapsed, mobileOpen, setMobileOpen }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, isAdmin, logout } = useAuth()
  const layout = useUiLayout()
  const isGuest = !user

  const groups = useMemo(() => {
    const modules = visibleModulesFor(visibleModules(layout), isGuest)
      .map((m) => ({ key: m.key, title: m.title, items: m.items }))
    const extras = isGuest ? [] : [{ key: 'other', title: '通用', items: visibleOther(layout) }]
    const admin = isAdmin ? [{ key: 'admin', title: '管理后台', items: NAV_ADMIN }] : []
    return [...modules, ...extras, ...admin]
  }, [layout, isGuest, isAdmin])

  const isActive = (to) => (to === '/' ? location.pathname === '/' : location.pathname === to || location.pathname.startsWith(`${to}/`))

  const onLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const displayName = user?.display_name || user?.username || '同学'
  const role = isAdmin ? 'ADMIN' : '学习者'

  return (
    <aside className={cx('v3-sidebar', mobileOpen && 'is-open')} data-collapsed={collapsed} aria-label="主导航">
      <Link to="/" className="v3-brand" onClick={() => setMobileOpen(false)}>
        <BrandMark />
        <span className="v3-brand__word">
          <strong>硕途</strong>
          <span>Study OS</span>
        </span>
      </Link>

      <nav className="v3-nav">
        {groups.map((group) => (
          <div key={group.key} className="v3-nav-group">
            <div className="v3-nav-group__label">{group.title}</div>
            {group.items.map((item) => (
              <NavItem
                key={item.to}
                item={item}
                active={isActive(item.to)}
                collapsed={collapsed}
                onNavigate={() => setMobileOpen(false)}
              />
            ))}
          </div>
        ))}
      </nav>

      <div className="v3-sidebar__footer">
        {user ? (
          <Link to="/profile" className="v3-user-card" onClick={() => setMobileOpen(false)}>
            <Avatar name={displayName} />
            <span className="v3-user-card__meta">
              <span className="v3-user-card__name">{displayName}</span>
              <span className="v3-user-card__role">{role}</span>
            </span>
          </Link>
        ) : (
          <Link to="/login" className="v3-user-card" onClick={() => setMobileOpen(false)}>
            <Avatar name="访" />
            <span className="v3-user-card__meta">
              <span className="v3-user-card__name">访客模式</span>
              <span className="v3-user-card__role">登录后同步数据</span>
            </span>
          </Link>
        )}
        {user ? (
          <button type="button" className="v3-sidebar__collapse" onClick={onLogout}>
            <LogOut size={17} />
            <span className="v3-sidebar__collapse-label">退出登录</span>
          </button>
        ) : null}
        <button
          type="button"
          className="v3-sidebar__collapse"
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
        >
          {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          <span className="v3-sidebar__collapse-label">{collapsed ? '展开侧栏' : '收起侧栏'}</span>
        </button>
      </div>
    </aside>
  )
}

/* -------------------------------------------------------------------------- */
/* Global subject switcher（全局学科选择器）                                    */
/* -------------------------------------------------------------------------- */
function GlobalSubjectSwitcher() {
  const navigate = useNavigate()
  const location = useLocation()
  const globalSubject = useStore((s) => s.globalSubject)
  const setGlobalSubject = useStore((s) => s.setGlobalSubject)
  const [options, setOptions] = useState([])

  /* 学科列表来源：taxonomy 科目接口（兼容 {subjects:[...]} 与裸数组） */
  useEffect(() => {
    let alive = true
    taxonomyApi.subjects()
      .then((d) => {
        const items = Array.isArray(d) ? d : (d?.subjects || d?.core || [])
        const list = items
          .map((s) => ({ value: s.subject || s.name, label: s.subject || s.name }))
          .filter((s) => s.value)
        if (alive) setOptions(list)
      })
      .catch(() => { /* 离线/未配置时保持「全部学科」 */ })
    return () => { alive = false }
  }, [])

  /* 切换学科：记录全局选择，并跳转到当前板块对应页面的 ?subject= 深链 */
  const applySubject = (sub) => {
    setGlobalSubject(sub)
    const path = location.pathname
    const q = sub ? `?subject=${encodeURIComponent(sub)}` : ''
    if (path.startsWith('/quiz')) navigate('/quiz' + q)
    else if (path.startsWith('/exam')) navigate('/exam' + q)
    else if (path.startsWith('/library')) navigate('/library' + q)
    else if (path.startsWith('/knowledge')) navigate('/knowledge' + q)
    else if (path.startsWith('/words')) navigate('/words' + q)
  }

  return (
    <div className="v3-subject-switcher" title="切换学科（联动刷题/真题/文库/知识图谱）">
      <Select
        className="v3-subject-switcher__select"
        value={globalSubject}
        aria-label="切换学科"
        onChange={(e) => applySubject(e.target.value)}
        options={[{ value: '', label: '全部学科' }, ...options]}
      />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Module switcher（全局板块快速切换）                                         */
/* -------------------------------------------------------------------------- */
function ModuleSwitcher() {
  const navigate = useNavigate()
  const location = useLocation()
  const groups = MODULES.filter((m) => m.items.length)
  const current = groups.find((g) =>
    g.items.some((it) => location.pathname === it.to || location.pathname.startsWith(`${it.to}/`))
  )?.key || ''

  return (
    <div className="v3-module-switcher" title="快速切换板块">
      <Segmented
        className="v3-module-switcher__seg"
        ariaLabel="切换板块"
        value={current}
        options={groups.map((g) => ({ value: g.key, label: g.title }))}
        onChange={(key) => {
          const g = groups.find((x) => x.key === key)
          if (g?.items?.[0]) navigate(g.items[0].to)
        }}
      />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Top bar                                                                    */
/* -------------------------------------------------------------------------- */
function useCountdown() {
  const countdown = useStore((s) => s.countdown)
  const settingDate = useStore((s) => s.settings?.examDate)
  const effective = settingDate || countdown?.exam_date
  return examDaysLeft(resolveExamDate(effective, null))
}

function TopBar({ collapsed, onOpenMobile, onOpenCommand }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, isAdmin, logout } = useAuth()
  const themePref = useStore((s) => s.settings?.theme || 'light')
  const updateSettings = useStore((s) => s.updateSettings)
  const resolved = useResolvedTheme(themePref)
  const days = useCountdown()
  const [menuOpen, setMenuOpen] = useState(false)
  const avatarRef = useRef(null)
  const displayName = user?.display_name || user?.username || '同学'

  const toggleTheme = () => updateSettings({ theme: resolved === 'dark' ? 'light' : 'dark' })

  return (
    <header className="v3-topbar" data-collapsed={collapsed}>
      <IconButton className="v3-show-mobile" label="打开导航" icon={<Menu size={20} />} onClick={onOpenMobile} />

      <div className="v3-topbar__crumbs">
        <Link to="/" aria-label="首页">硕途</Link>
        <ChevronRight size={13} className="v3-topbar__sep" />
        <strong>{crumbName(location.pathname)}</strong>
      </div>

      {/* 全局学科选择 + 板块快速切换（2026-10-24 全新展示） */}
      <GlobalSubjectSwitcher />
      <ModuleSwitcher />

      <button type="button" className="v3-search v3-topbar__search" onClick={onOpenCommand}>
        <Search size={17} />
        <span className="v3-search__label">搜索页面、功能与命令…</span>
        <Kbd><Command size={11} style={{ display: 'inline', verticalAlign: '-1px' }} /> K</Kbd>
      </button>

      <div className="v3-topbar__actions">
        <div className="v3-countdown" title="距离初试">
          <Clock size={15} />
          {days == null ? <Link to="/settings">设置初试日期</Link> : <><strong>{Math.max(0, days)}</strong> 天</>}
        </div>
        <IconButton label="通知中心" icon={<Bell size={19} />} onClick={() => navigate('/kaoyan/notices')} />
        <IconButton
          label={resolved === 'dark' ? '切换到浅色' : '切换到深色'}
          icon={resolved === 'dark' ? <Sun size={19} /> : <Moon size={19} />}
          onClick={toggleTheme}
        />
        {user ? (
          <>
            <span ref={avatarRef} className="v3-topbar__avatar">
              <button type="button" className="v3-iconbtn" aria-label="账号菜单" onClick={() => setMenuOpen((v) => !v)}>
                <Avatar name={displayName} size="sm" />
              </button>
            </span>
            {menuOpen ? (
              <div className="v3-menu v3-portal" style={{ top: 62, right: 20, position: 'fixed' }} role="menu">
                <MenuItem icon={<User size={16} />} onClick={() => { setMenuOpen(false); navigate('/profile') }}>学习画像</MenuItem>
                <MenuItem icon={<Settings size={16} />} onClick={() => { setMenuOpen(false); navigate('/settings') }}>设置</MenuItem>
                {isAdmin ? <MenuItem icon={<Database size={16} />} onClick={() => { setMenuOpen(false); navigate('/admin/overview') }}>管理后台</MenuItem> : null}
                <div className="v3-menu__sep" />
                <MenuItem danger icon={<LogOut size={16} />} onClick={async () => { setMenuOpen(false); await logout(); navigate('/login') }}>退出登录</MenuItem>
              </div>
            ) : null}
          </>
        ) : (
          <Button size="sm" onClick={() => navigate('/login')}>登录</Button>
        )}
      </div>
    </header>
  )
}

/* -------------------------------------------------------------------------- */
/* Command palette                                                            */
/* -------------------------------------------------------------------------- */
function CommandPalette({ open, onClose }) {
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState(0)
  const inputRef = useRef(null)

  const entries = useMemo(() => {
    const base = [
      ...MODULES.flatMap((m) => m.items.map((it) => ({ ...it, group: m.title }))),
      ...NAV_OTHER.map((it) => ({ ...it, group: '通用' })),
      ...(isAdmin ? NAV_ADMIN.map((it) => ({ ...it, group: '管理' })) : []),
    ]
    const seen = new Set()
    return base.filter((e) => {
      if (seen.has(e.to)) return false
      seen.add(e.to)
      return true
    })
  }, [isAdmin])

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase()
    if (!query) return entries
    return entries.filter((e) => {
      const hay = [e.label, e.desc, e.group, ...(e.kw || [])].join(' ').toLowerCase()
      return hay.includes(query)
    })
  }, [q, entries])

  useEffect(() => {
    if (open) {
      setQ('')
      setSelected(0)
      window.setTimeout(() => inputRef.current?.focus(), 80)
    }
  }, [open])

  useEffect(() => { setSelected(0) }, [q])

  const go = (entry) => {
    if (!entry) return
    onClose()
    navigate(entry.to)
  }

  const onKey = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelected((s) => Math.min(filtered.length - 1, s + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelected((s) => Math.max(0, s - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      go(filtered[selected])
    } else if (e.key === 'Escape') {
      onClose()
    }
  }

  if (!open) return null
  let lastGroup = ''
  return (
    <div className="v3-command v3-portal" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="v3-command__panel" role="dialog" aria-modal="true" aria-label="命令面板">
        <div className="v3-command__input-row">
          <Search size={20} />
          <input
            ref={inputRef}
            className="v3-command__input"
            placeholder="输入页面名、功能或关键词…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
          />
          <Kbd>ESC</Kbd>
        </div>
        <div className="v3-command__list">
          {filtered.length === 0 ? <div className="v3-command__empty">没有找到匹配的页面</div> : null}
          {filtered.map((entry, i) => {
            const showGroup = entry.group !== lastGroup
            lastGroup = entry.group
            const Icon = navIcon(entry.to)
            return (
              <React.Fragment key={entry.to}>
                {showGroup ? <div className="v3-command__group">{entry.group}</div> : null}
                <button
                  type="button"
                  className={cx('v3-command__item', i === selected && 'is-selected')}
                  onMouseEnter={() => setSelected(i)}
                  onClick={() => go(entry)}
                >
                  <Icon size={18} />
                  <span>{entry.label}</span>
                  <small>{entry.desc}</small>
                </button>
              </React.Fragment>
            )
          })}
        </div>
        <div className="v3-command__foot">
          <span>↑↓ 选择</span>
          <span>↵ 打开</span>
          <span>esc 关闭</span>
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* AI orb                                                                     */
/* -------------------------------------------------------------------------- */
const QUICK_PROMPTS = [
  { icon: <Zap size={15} />, text: '帮我规划今天的学习' },
  { icon: <Target size={15} />, text: '根据我的薄弱点给一组练习' },
  { icon: <BookOpen size={15} />, text: '解释当前页面能做什么' },
]

function AiOrb() {
  const location = useLocation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState([])
  const listRef = useRef(null)
  const pageName = crumbName(location.pathname)
  const configured = hasAiConfigured()

  useEffect(() => {
    if (open && messages.length === 0) {
      setMessages([{
        role: 'assistant',
        content: `你好，我是硕途 AI。当前在「${pageName}」页面，可以问我学习规划、题目讲解或页面用法。`,
      }])
    }
  }, [open, pageName, messages.length])

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages, busy])

  const send = async (text) => {
    const content = String(text || '').trim()
    if (!content || busy) return
    const next = [...messages, { role: 'user', content }]
    setMessages(next)
    setInput('')
    setBusy(true)

    if (!configured) {
      window.setTimeout(() => {
        setMessages((m) => [...m, {
          role: 'assistant',
          content: '还没有配置 AI 服务。请到「设置 → AI 服务」填写 API Key，我就能为你答疑与规划。',
        }])
        setBusy(false)
      }, 380)
      return
    }

    try {
      const provider = defaultProvider()
      const system = `你是考研学习平台「硕途」的 AI 学习助手。用户当前在「${pageName}」页面。回答要简洁、具体、可执行，使用简体中文。需要公式时使用 LaTeX。`
      const reply = await chatCompletion(provider, [
        { role: 'system', content: system },
        ...next.slice(-8).map((m) => ({ role: m.role, content: m.content })),
      ], { temperature: 0.6, maxTokens: 900 })
      setMessages((m) => [...m, { role: 'assistant', content: reply?.content || reply?.text || '（没有返回内容）' }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', content: `调用失败：${e?.message || '未知错误'}。可以到设置页检查 AI 配置。` }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button
        type="button"
        className="v3-orb"
        aria-label="打开 AI 助手"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="v3-orb__core">
          <Sparkles size={20} className="v3-orb__spark v3-orb__spark--a" />
          <span className="v3-orb__spark v3-orb__spark--b" style={{ width: 5, height: 5, borderRadius: '50%', background: '#fff' }} />
        </span>
      </button>

      {open ? (
        <section className="v3-orb__panel" aria-label="AI 助手面板">
          <div className="v3-orb__head">
            <span className="v3-orb__title">
              <Sparkles size={17} />
              硕途 AI
              <Badge tone={configured ? 'success' : 'warning'}>{configured ? '在线' : '未配置'}</Badge>
            </span>
            <span style={{ marginLeft: 'auto' }} className="v3-row">
              <IconButton label="打开完整助手" size="sm" icon={<ArrowRight size={17} />} onClick={() => { setOpen(false); navigate('/assistant') }} />
              <IconButton label="关闭" size="sm" icon={<X size={17} />} onClick={() => setOpen(false)} />
            </span>
          </div>
          <div ref={listRef} className="v3-orb__body">
            {messages.map((m, i) => (
              <div key={i} className={cx('v3-chat-msg', m.role === 'user' ? 'v3-chat-msg--user' : 'v3-chat-msg--ai')}>
                {m.content}
              </div>
            ))}
            {busy ? (
              <div className="v3-chat-msg v3-chat-msg--ai v3-chat-msg--typing" aria-label="AI 正在思考">
                <i /><i /><i />
              </div>
            ) : null}
          </div>
          {messages.length <= 1 ? (
            <div className="v3-orb__prompts">
              {QUICK_PROMPTS.map((p) => (
                <button key={p.text} type="button" className="v3-orb__prompt" onClick={() => send(p.text)}>
                  {p.icon}
                  {p.text}
                </button>
              ))}
            </div>
          ) : null}
          <form
            className="v3-orb__composer"
            onSubmit={(e) => { e.preventDefault(); send(input) }}
          >
            <textarea
              value={input}
              placeholder="问点什么…（Enter 发送）"
              rows={1}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(input)
                }
              }}
            />
            <IconButton
              label="发送"
              variant="filled"
              size="sm"
              icon={<Send size={17} />}
              onClick={() => send(input)}
              disabled={busy || !input.trim()}
            />
          </form>
        </section>
      ) : null}
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* Mobile navigation                                                          */
/* -------------------------------------------------------------------------- */
function MobileNav({ onOpenMore }) {
  const location = useLocation()
  const tabs = [
    { to: '/', label: '今日', icon: Home },
    { to: '/knowledge', label: '知识', icon: Map },
    { to: '/quiz', label: '刷题', icon: Target },
    { to: '/error-review', label: '复盘', icon: Activity },
  ]
  return (
    <nav className="v3-mobile-nav" aria-label="移动端导航">
      <div className="v3-mobile-nav__inner">
        {tabs.map((t) => {
          const active = t.to === '/' ? location.pathname === '/' : location.pathname.startsWith(t.to)
          const Icon = t.icon
          return (
            <Link key={t.to} to={t.to} className={cx('v3-mobile-nav__item', active && 'is-active')}>
              <Icon size={20} data-active={active || undefined} />
              <span>{t.label}</span>
            </Link>
          )
        })}
        <button type="button" className="v3-mobile-nav__item" onClick={onOpenMore}>
          <Menu size={20} />
          <span>更多</span>
        </button>
      </div>
    </nav>
  )
}

/* -------------------------------------------------------------------------- */
/* App shell                                                                  */
/* -------------------------------------------------------------------------- */
const ShellCtx = createContext({ openCommand: () => {} })
export const useShell = () => useContext(ShellCtx)

export default function AppShell({ children }) {
  const location = useLocation()
  const { user } = useAuth()
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('v3.sidebar.collapsed') === '1' } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)

  useEffect(() => {
    try { localStorage.setItem('v3.sidebar.collapsed', collapsed ? '1' : '0') } catch { /* ignore */ }
  }, [collapsed])

  useEffect(() => {
    setMobileOpen(false)
    setMoreOpen(false)
    window.scrollTo({ top: 0, behavior: 'auto' })
    /* P1 页面标题：每个路由设置 document.title，tab 可区分 */
    const name = crumbName(location.pathname)
    document.title = (name && name !== '页面' && name !== '首页')
      ? `${name} · 硕途考研`
      : '硕途 · 考研学习平台'
  }, [location.pathname])

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCommandOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const openCommand = useCallback(() => setCommandOpen(true), [])

  const moreEntries = useMemo(() => [
    ...MODULES.flatMap((m) => m.items.map((it) => ({ ...it, group: m.title }))),
    ...NAV_OTHER.map((it) => ({ ...it, group: '通用' })),
  ].filter((e, i, arr) => arr.findIndex((x) => x.to === e.to) === i), [])

  return (
    <ShellCtx.Provider value={{ openCommand }}>
      <div className="v3-root">
        <div className="v3-shell">
          <Sidebar
            collapsed={collapsed}
            setCollapsed={setCollapsed}
            mobileOpen={mobileOpen}
            setMobileOpen={setMobileOpen}
          />
          {mobileOpen ? <div className="v3-mobile-mask" onClick={() => setMobileOpen(false)} /> : null}
          <div className="v3-main" data-collapsed={collapsed}>
            <TopBar collapsed={collapsed} onOpenMobile={() => setMobileOpen(true)} onOpenCommand={openCommand} />
            <main className="v3-main__inner">
              <div className="v3-page" key={location.pathname}>{children}</div>
            </main>
          </div>
          <MobileNav onOpenMore={() => setMoreOpen(true)} />
          {user ? <AiOrb /> : null}
        </div>

        <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} />
        <Sheet open={moreOpen} title="全部功能" onClose={() => setMoreOpen(false)}>
          <div className="v3-stack" style={{ gap: 18 }}>
            {Object.entries(moreEntries.reduce((acc, e) => {
              ;(acc[e.group] = acc[e.group] || []).push(e)
              return acc
            }, {})).map(([group, items]) => (
              <div key={group}>
                <div className="v3-nav-group__label" style={{ padding: '0 4px 8px' }}>{group}</div>
                <div className="v3-grid v3-grid-2" style={{ gap: 8 }}>
                  {items.map((it) => {
                    const Icon = navIcon(it.to)
                    return (
                      <Link key={it.to} to={it.to} className="v3-list-item" style={{ border: '1px solid var(--v3-outline)' }} onClick={() => setMoreOpen(false)}>
                        <Icon size={18} />
                        <span className="v3-list-item__main">
                          <span className="v3-list-item__title">{it.label}</span>
                        </span>
                      </Link>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </Sheet>
        <ToastHost />
      </div>
    </ShellCtx.Provider>
  )
}

/* -------------------------------------------------------------------------- */
/* Admin layout                                                               */
/* -------------------------------------------------------------------------- */
export function AdminLayout({ children }) {
  const location = useLocation()
  return (
    <div className="v3-stack" style={{ gap: 20 }}>
      <div>
        <div className="v3-eyebrow" style={{ marginBottom: 8 }}>ADMIN CONSOLE</div>
        <h1 className="v3-h1">管理后台</h1>
        <p className="v3-body" style={{ marginTop: 6 }}>数据、题库、院校采集与模型训练的统一工作台。</p>
      </div>
      <nav className="v3-admin-nav" aria-label="管理导航">
        {NAV_ADMIN.map((item) => {
          const Icon = navIcon(item.to)
          const active = location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)
          return (
            <Link key={item.to} to={item.to} className={cx('v3-admin-nav__item', active && 'is-active')}>
              <Icon size={15} />
              {item.label}
            </Link>
          )
        })}
      </nav>
      <div>{children}</div>
    </div>
  )
}

export { Sidebar, TopBar, CommandPalette, AiOrb, MobileNav }
