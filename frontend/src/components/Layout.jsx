import React, { useState, useEffect } from 'react'
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import useStore from '../store/useStore'
import { daysBetween, todayStr } from '../utils/date'
import GlobalAI from './GlobalAI'
import CommandPalette from './CommandPalette'
import { useResolvedTheme } from './UI'
import {
  Home, Clock, Calendar, Book, Folder, Target,
  Settings, Sun, Moon, Plus, Brain, FileText, GraduationCap,
  MessageSquare, ChevronDown, Search, Cloud, ChevronRight, Map, Filter, CheckCircle, Activity
} from './Icon'

/* 侧边栏考研初试倒计时（27 考研初试：2026-12-19）——借鉴 gitgraduate 导航倒计时细节 */
const EXAM_DATE = new Date(2026, 11, 19) // 2026-12-19 00:00 本地时间
function ExamCountdown() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const diff = EXAM_DATE.getTime() - now
  const done = diff <= 0
  const abs = Math.max(0, diff)
  const days = Math.floor(abs / 86400000)
  const hours = Math.floor(abs / 3600000) % 24
  const mins = Math.floor(abs / 60000) % 60
  const secs = Math.floor(abs / 1000) % 60
  const pad = (n) => String(n).padStart(2, '0')
  return (
    <div className="exam-cd">
      <span className="ecd-label">考研初试倒计时</span>
      <div className="ecd-main">
        {done ? <span className="ecd-days">已开考</span> : (
          <>
            <span className="ecd-days">{days}</span>
            <span className="ecd-unit">天</span>
            <span className="ecd-hms">{pad(hours)}:{pad(mins)}:{pad(secs)}</span>
          </>
        )}
      </div>
    </div>
  )
}

// 分组导航配置（桌面端）
const NAV_GROUPS = [
  {
    title: '今日',
    items: [
      { to: '/', label: '仪表盘', icon: Home, exact: true },
      { to: '/tasks', label: '任务打卡', icon: Target },
      { to: '/kbmap', label: '知识地图', icon: Map },
    ]
  },
  {
    title: '学习',
    items: [
      { to: '/quiz', label: '刷题中心', icon: Book },
      { to: '/quiz-section', label: '分项刷题', icon: Filter },
      { to: '/quiz-bank', label: '题库', icon: Book },
      { to: '/analysis', label: '题目分析', icon: Brain },
      { to: '/profile', label: '学习画像', icon: Activity },
      { to: '/notebook', label: '错题本', icon: FileText },
      { to: '/words', label: '单词记忆', icon: GraduationCap },
      { to: '/cards', label: '记忆卡片', icon: Brain },
      { to: '/subjects', label: '科目管理', icon: Settings },
    ]
  },
  {
    title: '资源与计划',
    items: [
      { to: '/documents', label: '文档知识库', icon: Folder },
      { to: '/pan', label: '网盘联动', icon: Cloud },
      { to: '/planner', label: '学习计划', icon: Calendar },
      { to: '/settings', label: '设置', icon: Settings },
    ]
  },
  // D8: 择校类目归组 —— "择校中心"等考研择校入口统一归入"考研择校"类目（考研数据侧），
  // 不再挂在 AI 分组下；AI 分组仅保留通用 AI 助手
  {
    title: '考研择校',
    items: [
      { to: '/kaoyan', label: '择校中心', icon: GraduationCap },
      { to: '/kaoyan/schools', label: '院校库', icon: Book },
      { to: '/kaoyan/compare', label: '院校对比', icon: Filter },
      { to: '/kaoyan/analysis', label: '分数分析', icon: Brain },
      { to: '/kaoyan/map', label: '区域热力图', icon: Map },
      { to: '/kaoyan/scatter', label: '招生散点图', icon: Search },
      { to: '/kaoyan/recommend', label: '智能择校', icon: Target },
      { to: '/kaoyan/plan', label: '考研规划', icon: Calendar },
      { to: '/kaoyan/growth', label: '成长体系', icon: CheckCircle },
      { to: '/kaoyan/assistant', label: '择校 AI 问答', icon: MessageSquare },
      { to: '/kaoyan/import', label: '数据管理', icon: FileText },
    ]
  },
  {
    title: 'AI',
    items: [
      { to: '/assistant', label: 'AI 助手', icon: MessageSquare },
    ]
  }
]

// 移动端底部导航（7 个，覆盖手机高频场景；批次1-1：补「择校」出口，解决移动端进择校模块出不来）
// 手机主要用途：拍错题、看考点进度、刷题、问 AI。
// 「资源」「我的」放进去是因为移动端没有侧边栏，必须有入口。
const BOTTOM_NAV = [
  { to: '/', label: '今日', icon: Home, exact: true },
  { to: '/notebook', label: '错题', icon: FileText },
  { to: '/kbmap', label: '考点', icon: Map },
  { to: '/quiz', label: '刷题', icon: Book },
  { to: '/kaoyan', label: '择校', icon: GraduationCap },
  { to: '/assistant', label: 'AI', icon: Brain },
  { to: '/settings', label: '我的', icon: Settings },
]

// 面包屑映射（当前路由 → 中文名）
const CRUMB_MAP = {
  '/': '首页',
  '/tasks': '任务打卡',
  '/kbmap': '知识地图',
  '/quiz': '刷题中心',
  '/quiz-bank': '题库管理',
  '/analysis': '题目分析',
  '/profile': '学习画像',
  '/notebook': '错题本',
  '/subjects': '科目管理',
  '/words': '单词记忆',
  '/cards': '记忆卡片',
  '/documents': '文档知识库',
  '/pan': '网盘联动',
  '/planner': '学习计划',
  '/assistant': 'AI 助手',
  '/settings': '设置',
  // 择校中心（/kaoyan 系列）
  '/kaoyan': '择校中心',
  '/kaoyan/guide': '择校中心',
  '/kaoyan/schools': '院校库',
  '/kaoyan/compare': '院校对比',
  '/kaoyan/analysis': '分数分析',
  '/kaoyan/recommend': '智能择校',
  '/kaoyan/assistant': '择校 AI 问答',
  '/kaoyan/plan': '考研规划',
  '/kaoyan/growth': '成长体系',
  '/kaoyan/map': '区域热力图',
  '/kaoyan/scatter': '招生散点图',
  '/kaoyan/import': '数据管理',
}

// 面包屑名称解析：优先精确匹配，动态路由（如 /kaoyan/schools/:id）按前缀回退
const crumbName = (path) => {
  if (CRUMB_MAP[path]) return CRUMB_MAP[path]
  if (path.startsWith('/kaoyan/schools/')) return '院校详情'
  return '页面'
}

// 相关功能（上下文相关跳转，仿大平台"相关推荐"）
const RELATED = {
  '/tasks': ['/kbmap', '/planner', '/notebook'],
  '/kbmap': ['/documents', '/notebook', '/quiz'],
  '/quiz': ['/notebook', '/words', '/cards'],
  '/notebook': ['/quiz', '/kbmap', '/planner'],
  '/words': ['/cards', '/quiz', '/notebook'],
  '/cards': ['/words', '/quiz', '/notebook'],
  '/documents': ['/kbmap', '/pan', '/assistant'],
  '/pan': ['/documents', '/assistant', '/settings'],
  '/planner': ['/tasks', '/kbmap', '/notebook'],
  '/assistant': ['/documents', '/kbmap', '/notebook'],
  '/settings': ['/pan', '/assistant', '/documents'],
}

// 快捷操作面板
const QUICK_ACTIONS = [
  { label: '添加任务', icon: Target, action: '/tasks' },
  { label: '拍错题', icon: FileText, action: '/notebook' },
  { label: '看考点', icon: Map, action: '/kbmap' },
  { label: '问 AI', icon: Brain, action: '/assistant' },
]

export default function Layout({ children }) {
  const settings = useStore((s) => s.settings)
  // 批次1-3：store 实际键为 backendOnline（useStore.js:107，由 sync.js 在 hydrate 结束后写入）；
  // 原 backendOk/syncing 是 store 里不存在的键，读取恒为 undefined（静默失效，红点从不亮）。
  const backendOnline = useStore((s) => s.backendOnline)
  const updateSettings = useStore((s) => s.updateSettings)
  const [quickOpen, setQuickOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  const days = daysBetween(todayStr(), settings.examDate || todayStr())
  // V7.0 P0-1：用解析后的主题判断深浅，theme='system' 时按钮显示才与实际渲染一致
  const resolvedTheme = useResolvedTheme(settings.theme)
  const isDark = resolvedTheme === 'dark'

  const isActive = (to, exact = false) => {
    if (exact) return location.pathname === to
    return location.pathname.startsWith(to) && to !== '/'
  }

  const go = (to) => {
    navigate(to)
    setQuickOpen(false)
  }

  // V7.0 P0-1：只更新 store，不再绕过 store 直写 DOM（DOM 由 useResolvedTheme 统一接管）
  const toggleTheme = () => {
    updateSettings({ theme: isDark ? 'light' : 'dark' })
  }

  // 键盘快捷键：Ctrl+K 打开命令面板
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setCommandOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className="app-shell">
      {/* 桌面侧边栏 - 分组导航 */}
      <aside className="sidebar" aria-label="主导航">
        <div className="brand">
          <div className="brand-mark">考</div>
          <div className="brand-text">
            <strong>考研档案</strong>
            <span>KAOYAN ARCHIVE</span>
          </div>
        </div>

        <ExamCountdown />

        <nav className="side-nav">
          {NAV_GROUPS.map((group, gi) => (
            <div key={group.title} className="nav-group">
              {gi > 0 && <div className="nav-divider" />}
              <div className="nav-group-title">{group.title}</div>
              {group.items.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.exact}
                  className={({ isActive: a }) => `nav-item ${a ? 'active' : ''}`}
                  aria-label={n.label}
                >
                  <n.icon size={18} className="nav-ico" />
                  <span className="nav-label">{n.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="side-foot">
          <button
            className="side-theme-btn"
            onClick={toggleTheme}
            aria-label={isDark ? '切换到浅色模式' : '切换到深色模式'}
          >
            {isDark ? <Sun size={16} /> : <Moon size={16} />}
            <span>{isDark ? '浅色' : '深色'}</span>
          </button>
          <div className="side-countdown">
            <span className="sc-label">距考试</span>
            <span className="sc-num">{days > 0 ? days : 0}</span>
            <span className="sc-label">天</span>
          </div>
        </div>
      </aside>

      {/* 移动端顶栏 */}
      <header className="mobile-top">
        <div className="mt-brand">
          <div className="brand-mark" style={{ width: 32, height: 32, fontSize: 16 }}>考</div>
          <strong>考研档案</strong>
        </div>
        <div className="mt-right">
          <button
            className="mt-icon-btn"
            onClick={() => setCommandOpen(true)}
            aria-label="搜索"
          >
            <Search size={18} />
          </button>
          <span className="mt-count">倒计时 {days > 0 ? days : 0} 天</span>
        </div>
      </header>

      {/* 主内容 */}
      <main className="main-area" key={location.pathname}>
        <nav className="breadcrumb" aria-label="面包屑">
          <Link to="/">首页</Link>
          {location.pathname !== '/' && (
            <>
              <span className="crumb-sep">/</span>
              {/* 择校模块子路由补二级层级：首页 / 择校中心 / 当前页 */}
              {location.pathname.startsWith('/kaoyan') && location.pathname !== '/kaoyan' && (
                <>
                  <Link to="/kaoyan">择校中心</Link>
                  <span className="crumb-sep">/</span>
                </>
              )}
              <span className="crumb-current">{crumbName(location.pathname)}</span>
            </>
          )}
        </nav>
        <div className="view-enter">{children}</div>
        {/* 批次1-3：后端状态指示器。复用 global.css 已有 .sync-status / .sync-status-dot（此前 0 引用），不新增样式 */}
        <div className="sync-status"><span className={'sync-status-dot ' + (backendOnline ? 'online' : 'offline')} />{backendOnline ? '后端已连接' : '后端未连接 — 数据可能未加载'}</div>
        {RELATED[location.pathname] && (
          <nav className="related-bar" aria-label="相关功能">
            <span className="related-title">相关功能</span>
            <div className="rel-chips">
              {RELATED[location.pathname].map((to) => (
                <Link key={to} to={to} className="rel-chip">
                  {CRUMB_MAP[to]}
                  <ChevronRight size={13} />
                </Link>
              ))}
            </div>
          </nav>
        )}
      </main>

      {/* 移动端底部导航 - 5栏 + 中央快捷按钮 */}
      <nav className="bottom-nav" aria-label="底部导航">
        {BOTTOM_NAV.slice(0, 2).map((n) => (
          <button
            key={n.to}
            className={`bn-item ${isActive(n.to, n.exact) ? 'active' : ''}`}
            onClick={() => go(n.to)}
            aria-label={n.label}
          >
            <n.icon size={20} />
            <span>{n.label}</span>
          </button>
        ))}

        {/* 中央快捷按钮 */}
        <button
          className={`bn-fab ${quickOpen ? 'open' : ''}`}
          onClick={() => setQuickOpen((v) => !v)}
          aria-label="快捷操作"
          aria-expanded={quickOpen}
        >
          <Plus size={24} />
        </button>

        {BOTTOM_NAV.slice(2).map((n) => (
          <button
            key={n.to}
            className={`bn-item ${isActive(n.to, n.exact) ? 'active' : ''}`}
            onClick={() => go(n.to)}
            aria-label={n.label}
          >
            <n.icon size={20} />
            <span>{n.label}</span>
          </button>
        ))}
      </nav>

      {/* 快捷操作面板 */}
      {quickOpen && (
        <div className="quick-actions-overlay" onClick={() => setQuickOpen(false)}>
          <div className="quick-actions-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="qa-handle" />
            <h3 className="qa-title">快捷操作</h3>
            <div className="qa-grid">
              {QUICK_ACTIONS.map((action) => (
                <button
                  key={action.label}
                  className="qa-item"
                  onClick={() => go(action.action)}
                >
                  <div className="qa-icon">
                    <action.icon size={24} />
                  </div>
                  <span>{action.label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 命令面板（Ctrl+K / 移动端搜索触发，全局跳转） */}
      {commandOpen && <CommandPalette onClose={() => setCommandOpen(false)} />}

      {/* 全局 AI 悬浮入口 */}
      <GlobalAI />
    </div>
  )
}
