import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import useStore from '../../store/useStore'
import { useAuth } from '../../auth/AuthContext'
import { useResolvedTheme } from '../../components/UI'
import { chatCompletion, defaultProvider, hasAiConfigured } from '../../utils/api'
import { authApi, taxonomyApi } from '../../api/client'
import { ukey, migrateKey } from '../../utils/userKeys'
import {
  MODULES, NAV_OTHER, NAV_ADMIN, MOBILE_TABS, crumbName, visibleModules, visibleModulesFor,
  visibleOther,
} from '../../nav/navConfig'
import { useUiLayout } from '../../hooks/useUiLayout'
import {
  Activity, ArrowRight, BarChart3, Bell, BookOpen, CalendarClock, ChevronRight, Clock,
  Cloud, Command, Cpu, Database, FileText, Flag, FolderOpen, Gauge, Globe, Home, Layers,
  Library, ListChecks, LogOut, Mail, Map, Menu, Moon, NotebookPen, PanelLeftClose, PanelLeftOpen,
  School, Search, Send, Settings, Sparkles, Star, Sun, Target, Type, User, Wand, X, Zap,
} from '../icons'
import {
  Avatar, Badge, Button, IconButton, Kbd, MenuItem, Select, ToastHost, cx, toastOk, toastErr,
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
      aria-label={collapsed ? item.label : undefined}
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

  /* P1-1：分组可折叠，默认只展开当前所在分组；分组标题始终渲染（可点击展开）。
     收起为 76px 导轨时不折叠分组 —— 图标 + 短标签必须全部可见（R1）。
     768–1023 断点由 CSS 强制成导轨，这里同步感知，保证分组在该档始终展开。 */
  const [rail, setRail] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia('(min-width: 768px) and (max-width: 1023px)').matches
  ))
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px) and (max-width: 1023px)')
    const fn = (e) => setRail(e.matches)
    mq.addEventListener('change', fn)
    return () => mq.removeEventListener('change', fn)
  }, [])
  const groupOfPath = useCallback((path) => {
    const hit = groups.find((g) => g.items.some((it) => (it.to === '/' ? path === '/' : path === it.to || path.startsWith(`${it.to}/`))))
    return hit?.key || null
  }, [groups])
  const [openKeys, setOpenKeys] = useState(() => new Set())
  useEffect(() => {
    const key = groupOfPath(location.pathname)
    if (key) setOpenKeys((prev) => (prev.has(key) ? prev : new Set([...prev, key])))
  }, [location.pathname, groupOfPath])
  const toggleGroup = (key) => setOpenKeys((prev) => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })

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
        {groups.map((group) => {
          const open = collapsed || rail || openKeys.has(group.key)
          return (
            <div key={group.key} className="v3-nav-group" data-open={open}>
              <button
                type="button"
                className="v3-nav-group__label"
                aria-expanded={open}
                onClick={() => toggleGroup(group.key)}
              >
                <span>{group.title}</span>
                <ChevronRight size={12} className="v3-nav-group__chev" aria-hidden="true" />
              </button>
              {/* 条目始终渲染，显隐交给 CSS（data-open）：导轨断点才能强制全量可见 */}
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
          )
        })}
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
/* Top bar                                                                    */
/* -------------------------------------------------------------------------- */
/* P1-8 事实唯一：考研倒计时只在「今日中枢」出现一次，顶栏不再重复展示。
   P2-3 顶栏 ≤5 个控件：学科选择 / 搜索 / 通知 / 主题 / 账号；
   板块切换与侧栏分组重复，移除（命令面板 ⌘K 仍可直达任何页面）。 */
function TopBar({ collapsed, onOpenMobile, onOpenCommand }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, isAdmin, logout } = useAuth()
  const themePref = useStore((s) => s.settings?.theme || 'light')
  const updateSettings = useStore((s) => s.updateSettings)
  const resolved = useResolvedTheme(themePref)
  const [menuOpen, setMenuOpen] = useState(false)
  const avatarRef = useRef(null)
  const displayName = user?.display_name || user?.username || '同学'

  const toggleTheme = () => updateSettings({ theme: resolved === 'dark' ? 'light' : 'dark' })

  return (
    <header className="v3-topbar" data-collapsed={collapsed}>
      <IconButton className="v3-topbar__mobile-only" label="打开导航" icon={<Menu size={20} />} onClick={onOpenMobile} />

      <div className="v3-topbar__crumbs">
        <Link to="/" aria-label="首页">硕途</Link>
        <ChevronRight size={13} className="v3-topbar__sep" />
        <strong>{crumbName(location.pathname)}</strong>
      </div>

      {/* 全局学科选择器（P2-1：独立于面包屑，不混在 crumbs 里） */}
      <GlobalSubjectSwitcher />

      <button type="button" className="v3-search v3-topbar__search" onClick={onOpenCommand}>
        <Search size={17} />
        <span className="v3-search__label">搜索页面、功能与命令…</span>
        <Kbd><Command size={11} style={{ display: 'inline', verticalAlign: '-1px' }} /> K</Kbd>
      </button>

      <div className="v3-topbar__actions">
        {/* P2-2：窄屏搜索入口（桌面搜索条隐藏时仍可达 ⌘K 命令面板） */}
        <IconButton className="v3-topbar__mobile-only" label="搜索页面与功能" icon={<Search size={19} />} onClick={onOpenCommand} />
        <IconButton className="v3-topbar__bell" label="通知中心" icon={<Bell size={19} />} onClick={() => navigate('/kaoyan/notices')} />
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
/* P1-1：底部 Tab 与桌面侧栏分组同一套词（今日/学习/练习/复盘/择校），
   清单来自 navConfig.MOBILE_TABS 单一导航源；完整导航走顶栏抽屉。 */
function MobileNav() {
  const location = useLocation()
  return (
    <nav className="v3-mobile-nav" aria-label="移动端导航">
      <div className="v3-mobile-nav__inner">
        {MOBILE_TABS.map((t) => {
          const active = t.to === '/'
            ? location.pathname === '/' || location.pathname === '/hub'
            : location.pathname === t.to || location.pathname.startsWith(`${t.to}/`)
          const Icon = navIcon(t.to)
          return (
            <Link key={t.to} to={t.to} className={cx('v3-mobile-nav__item', active && 'is-active')} aria-current={active ? 'page' : undefined}>
              <Icon size={20} data-active={active || undefined} />
              <span>{t.label}</span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}

/* -------------------------------------------------------------------------- */
/* App shell                                                                  */
/* -------------------------------------------------------------------------- */
const ShellCtx = createContext({ openCommand: () => {} })
export const useShell = () => useContext(ShellCtx)

const SIDEBAR_KEY = 'v3.sidebar.collapsed'
/* 本机偏好按账号隔离（P2）：裸键一次性迁移到 uid 命名空间 */
const readCollapsed = () => {
  try {
    migrateKey(SIDEBAR_KEY)
    return localStorage.getItem(ukey(SIDEBAR_KEY)) === '1'
  } catch { return false }
}

/* -------------------------------------------------------------------------- */
/* 邮箱未验证横幅（P1）：仅登录用户且 email_verified === false 时显示。          */
/* 注意用严格 === false —— /auth/me 旧响应可能缺该字段，缺失时不打扰。           */
/* -------------------------------------------------------------------------- */
function VerifyEmailBanner({ user }) {
  const dismissKey = ukey('v3.verify-banner.dismissed')
  const [dismissed, setDismissed] = useState(() => {
    try { return sessionStorage.getItem(dismissKey) === '1' } catch { return false }
  })
  const [sending, setSending] = useState(false)

  if (!user || user.email_verified !== false || dismissed) return null

  const resend = async () => {
    if (sending) return
    setSending(true)
    try {
      await authApi.resendVerification(user.email)
      toastOk('验证邮件已发送，请查收邮箱')
    } catch (e) {
      toastErr(e?.message || '发送失败，请稍后再试')
    } finally {
      setSending(false)
    }
  }
  const dismiss = () => {
    setDismissed(true)
    try { sessionStorage.setItem(dismissKey, '1') } catch { /* 隐私模式 */ }
  }

  return (
    <div className="v3-verify-banner" role="status">
      <Mail size={16} aria-hidden="true" />
      <span className="v3-verify-banner__text">
        邮箱 {user.email} 尚未验证，验证后可使用全部功能。
      </span>
      <Button size="sm" variant="glass" loading={sending} onClick={resend}>重发验证邮件</Button>
      <IconButton label="本次会话内关闭提示" icon={<X size={15} />} onClick={dismiss} />
    </div>
  )
}

export default function AppShell({ children }) {
  const location = useLocation()
  const { user } = useAuth()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)

  useEffect(() => {
    try { localStorage.setItem(ukey(SIDEBAR_KEY), collapsed ? '1' : '0') } catch { /* ignore */ }
  }, [collapsed])

  /* 切账号时重读该账号的折叠偏好（含登出回访客态） */
  useEffect(() => {
    const onUid = () => setCollapsed(readCollapsed())
    window.addEventListener('userkeys:uid-changed', onUid)
    return () => window.removeEventListener('userkeys:uid-changed', onUid)
  }, [])

  useEffect(() => {
    setMobileOpen(false)
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

  /* 跳转链接（P0-5）：hash 路由下原生 #anchor 会改路由，
     必须 preventDefault 后手动 focus 主内容区。 */
  const skipToMain = (e) => {
    e.preventDefault()
    const el = document.getElementById('hub-main')
    if (!el) return
    el.focus({ preventScroll: true })
    el.scrollIntoView({ block: 'start' })
  }

  return (
    <ShellCtx.Provider value={{ openCommand }}>
      <div className="v3-root">
        <a href="#hub-main" className="v3-skip-link" onClick={skipToMain}>跳到主要内容</a>
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
            <VerifyEmailBanner key={user?.id ?? 'anon'} user={user} />
            <main id="hub-main" className="v3-main__inner" tabIndex={-1}>
              <div className="v3-page" key={location.pathname}>{children}</div>
            </main>
          </div>
          <MobileNav />
          {user ? <AiOrb /> : null}
        </div>

        <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} />
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
        {/* 口径体检：今日中枢迁出的调试/对账页，仅管理员可见（/admin/caliber） */}
        <Link
          to="/admin/caliber"
          className={cx('v3-admin-nav__item', location.pathname === '/admin/caliber' && 'is-active')}
        >
          <Gauge size={15} />
          数据口径
        </Link>
      </nav>
      <div>{children}</div>
    </div>
  )
}

export { Sidebar, TopBar, CommandPalette, AiOrb, MobileNav }
