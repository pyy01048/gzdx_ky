import React, { useState, useEffect, useMemo } from 'react'
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import useStore from '../store/useStore'
import { examDeadline, examDaysLeft, resolveExamDate } from '../utils/exam'
import GlobalAI from './GlobalAI'
import CommandPalette from './CommandPalette'
import NoticeUnreadBadge from './NoticeUnreadBadge'
import SubjectSwitcher from './SubjectSwitcher'
import { useResolvedTheme } from './UI'
import { useUiLayout, applyOrder } from '../hooks/useUiLayout'
import {
  Home, Book, Folder, Target,
  Settings, Sun, Moon, Plus, Brain, FileText, GraduationCap,
  MessageSquare, ChevronDown, Search, ChevronRight, Map
} from './Icon'

/* 侧边栏考研初试倒计时：日期取统一配置（utils/exam.js），未设置时给出设置入口 */
function useExamDate() {
  const cd = useStore((s) => s.countdown)
  const settingDate = useStore((s) => s.settings.examDate)
  return { examDate: resolveExamDate(cd?.exam_date, settingDate), estimated: !!cd?.is_default }
}

function ExamCountdown() {
  const { examDate, estimated } = useExamDate()
  const deadline = examDeadline(examDate)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const pad = (n) => String(n).padStart(2, '0')
  if (deadline == null) {
    return (
      <div className="exam-cd">
        <span className="ecd-label">考研初试倒计时</span>
        <div className="ecd-main">
          <Link className="ecd-unset" to="/settings">设置初试日期</Link>
        </div>
      </div>
    )
  }
  const diff = deadline - now
  const done = diff <= 0
  const abs = Math.max(0, diff)
  const days = Math.floor(abs / 86400000)
  const hours = Math.floor(abs / 3600000) % 24
  const mins = Math.floor(abs / 60000) % 60
  const secs = Math.floor(abs / 1000) % 60
  return (
    <div className="exam-cd">
      <span className="ecd-label">{estimated ? '考研初试倒计时（12/21 预估）' : '考研初试倒计时'}</span>
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

/* ==========================================================================
   主导航：分组下拉结构（docx/22 G2）
   --------------------------------------------------------------------------
   页面文件一个都没动，只重组导航层级。每个分组是一个可点击展开的「下拉」，
   分组首项即该模块主页（defaultTo），展开后在组内列出全部子入口，
   保证任何页面都能从侧边栏点到，不产生死链。

   分组（下拉）清单：
     仪表盘（任务打卡 / 学习计划 / 学习画像 已划归此处）
     学习文库 / 知识地图 / 题库 / 单词记忆 / 错题复盘 / 院校数据中心
   未分组的通用入口（AI 助手 / 设置）以「单列」形式直接呈现，设置不再并入分组。
   ========================================================================== */
export const NAV_MODULES = [
  {
    key: 'home',
    title: '仪表盘',
    icon: Home,
    defaultTo: '/',
    items: [
      // 用户诉求：任务打卡 / 学习计划 / 学习画像 全部划归仪表盘
      { to: '/', label: '仪表盘总览', exact: true },
      { to: '/tasks', label: '任务打卡' },
      { to: '/planner', label: '学习计划' },
      { to: '/profile', label: '学习画像' },
    ],
  },
  {
    key: 'library',
    title: '学习文库',
    icon: Folder,
    defaultTo: '/library',
    items: [
      { to: '/library', label: '学习文库' },
      { to: '/documents', label: '文档知识库' },
      { to: '/pan', label: '网盘联动' },
      { to: '/subjects', label: '科目管理' },
    ],
  },
  {
    key: 'kbmap',
    title: '知识地图',
    icon: Map,
    defaultTo: '/kbmap',
    items: [
      { to: '/kbmap', label: '知识地图' },
      { to: '/panorama', label: '知识点全景' },
      // 数据质量：识别口径/答疑评测的历史运行与语料体检，知识地图同源的置信层
      { to: '/quality', label: '评测与数据质量' },
    ],
  },
  {
    key: 'quiz',
    title: '题库',
    icon: Book,
    defaultTo: '/quiz-bank',
    items: [
      { to: '/quiz-bank', label: '题库管理' },
      { to: '/quiz', label: '刷题中心' },
      { to: '/cards', label: '记忆卡片' },
      // 复试代码题库（/codebank）：此前仅首页「全部模块」可达，主入口补进导航
      { to: '/codebank', label: '复试代码题库' },
    ],
  },
  {
    key: 'words',
    title: '单词记忆',
    icon: GraduationCap,
    defaultTo: '/words',
    items: [{ to: '/words', label: '单词记忆' }],
  },
  {
    key: 'review',
    title: '错题复盘',
    icon: FileText,
    defaultTo: '/error-review',
    items: [
      { to: '/error-review', label: '错题复盘' },
      { to: '/notebook', label: '错题本' },
    ],
  },
  {
    key: 'kaoyan',
    title: '院校数据中心',
    icon: Target,
    defaultTo: '/kaoyan',
    items: [
      { to: '/kaoyan', label: '择校中心', exact: true },
      { to: '/kaoyan/notices', label: '通知中心' },
      { to: '/kaoyan/schools', label: '院校库' },
      { to: '/kaoyan/compare', label: '院校对比' },
      { to: '/kaoyan/analysis', label: '分数分析' },
      { to: '/kaoyan/map', label: '区域热力图' },
      { to: '/kaoyan/scatter', label: '招生散点图' },
      { to: '/kaoyan/recommend', label: '智能择校' },
      { to: '/kaoyan/plan', label: '考研规划' },
      { to: '/kaoyan/growth', label: '成长体系' },
      { to: '/kaoyan/assistant', label: '择校 AI 问答' },
      { to: '/kaoyan/import', label: '数据管理' },
    ],
  },
]

/* 未分组的通用入口（以单列形式直接呈现；设置单列，不并入任何下拉） */
export const NAV_OTHER = [
  { to: '/assistant', label: 'AI 助手', icon: MessageSquare },
  { to: '/settings', label: '设置', icon: Settings },
]

/* 模块 → 展开状态。默认全部收起，用户点开一个模块后保持展开（localStorage 记忆）。 */
const NAV_OPEN_KEY = 'nav_modules_open'

function loadNavOpen() {
  try {
    const raw = localStorage.getItem(NAV_OPEN_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

// 移动端底部导航（覆盖手机高频场景；与 5+1 模块结构对齐）
// 手机主要用途：拍错题、看考点进度、刷题、问 AI。
const BOTTOM_NAV = [
  { to: '/', label: '今日', icon: Home, exact: true },
  { to: '/error-review', label: '复盘', icon: FileText },
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
  '/library': '学习文库',
  '/quiz': '刷题中心',
  '/quiz-bank': '题库管理',
  '/panorama': '知识点全景',
  '/profile': '学习画像',
  '/error-review': '错题复盘',
  '/notebook': '错题本',
  '/subjects': '科目管理',
  '/words': '单词记忆',
  '/cards': '记忆卡片',
  '/documents': '文档知识库',
  '/pan': '网盘联动',
  '/planner': '学习计划',
  '/assistant': 'AI 助手',
  '/codebank': '复试代码题库',
  '/settings': '设置',
  // 择校中心（/kaoyan 系列）
  '/kaoyan': '择校中心',
  '/kaoyan/guide': '择校中心',
  '/kaoyan/notices': '通知中心',
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
  '/tasks': ['/kbmap', '/planner', '/error-review'],
  '/kbmap': ['/documents', '/error-review', '/quiz'],
  '/library': ['/kbmap', '/documents', '/quiz'],
  '/quiz': ['/error-review', '/words', '/cards'],
  '/quiz-bank': ['/quiz', '/panorama', '/error-review'],
  '/panorama': ['/quiz', '/kbmap', '/quality'],
  '/error-review': ['/notebook', '/quiz', '/kbmap'],
  '/notebook': ['/quiz', '/kbmap', '/error-review'],
  '/words': ['/cards', '/quiz', '/error-review'],
  '/cards': ['/words', '/quiz', '/error-review'],
  '/documents': ['/kbmap', '/pan', '/assistant'],
  '/pan': ['/documents', '/assistant', '/settings'],
  '/planner': ['/tasks', '/kbmap', '/error-review'],
  '/assistant': ['/documents', '/kbmap', '/error-review'],
  '/settings': ['/pan', '/assistant', '/documents'],
}

// 快捷操作面板
const QUICK_ACTIONS = [
  { label: '添加任务', icon: Target, action: '/tasks' },
  { label: '错题复盘', icon: FileText, action: '/error-review' },
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

  const { examDate, estimated } = useExamDate()
  const days = examDaysLeft(examDate)
  // V7.0 P0-1：用解析后的主题判断深浅，theme='system' 时按钮显示才与实际渲染一致
  const resolvedTheme = useResolvedTheme(settings.theme)
  const isDark = resolvedTheme === 'dark'

  const isActive = (to, exact = false) => {
    if (exact) return location.pathname === to
    return location.pathname.startsWith(to) && to !== '/'
  }

  /* 侧边栏显隐/排序偏好（设置 → 界面自定义）。只影响渲染：路由表、CRUMB_MAP、
     模块展开判定仍读完整的 NAV_MODULES，所以藏掉一个模块不会让它的路径变成死链。 */
  const layout = useUiLayout()
  const navGroups = useMemo(
    () => applyOrder(NAV_MODULES.filter((m) => !layout.navHidden.includes(m.key)), layout.navOrder),
    [layout.navHidden, layout.navOrder],
  )
  const otherItems = useMemo(
    () => NAV_OTHER.filter((n) => !layout.otherHidden.includes(n.to)),
    [layout.otherHidden],
  )

  /* 5+1 模块展开状态：初始取 localStorage，若当前路由落在某模块下则强制展开该模块 */
  const [openModules, setOpenModules] = useState(() => {
    const saved = loadNavOpen()
    const activeKeys = NAV_MODULES.filter((m) =>
      m.items.some((n) => (n.exact ? location.pathname === n.to : location.pathname.startsWith(n.to)))
    ).map((m) => m.key)
    return Array.from(new Set([...saved, ...activeKeys]))
  })

  /* 分组标题行为（下拉开关）：
     - 单项分组（如「单词记忆」）：标题即入口，直接跳转，省一次点击；
     - 多项分组：点击展开/收起下拉，组内首项即模块主页。
     展开状态记忆在 localStorage，当前路由落在组内时强制展开。 */
  const toggleModule = (key) => {
    const mod = NAV_MODULES.find((m) => m.key === key)
    if (!mod) return
    if (mod.items.length === 1) { navigate(mod.items[0].to); return }
    const wasOpen = openModules.includes(key)
    const next = wasOpen ? openModules.filter((k) => k !== key) : [...openModules, key]
    try { localStorage.setItem(NAV_OPEN_KEY, JSON.stringify(next)) } catch { /* 隐私模式忽略 */ }
    setOpenModules(next)
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
          {/* 分组下拉导航：点分组标题展开/收起，组内为子入口 */}
          {navGroups.map((mod) => {
            const open = openModules.includes(mod.key)
            // 当前路由落在该模块下 → 强制展开（用户手动收起时不记忆，状态以展开为准）
            const containsActive = mod.items.some((n) => isActive(n.to, n.exact))
            const expanded = open || containsActive
            return (
              <div key={mod.key} className={`nav-mod ${expanded ? 'open' : ''}`}>
                <button
                  className={`nav-mod-head ${containsActive ? 'active' : ''}`}
                  onClick={() => toggleModule(mod.key)}
                  aria-expanded={mod.items.length > 1 ? expanded : undefined}
                  title={mod.items.length > 1 ? `${mod.title}（点击展开下拉）` : `${mod.title}（点击进入）`}
                >
                  <mod.icon size={17} className="nav-ico" />
                  <span className="nav-mod-title">{mod.title}</span>
                  {/* 未读通知角标：院校数据中心挂在模块标题上，全局可见 */}
                  {mod.key === 'kaoyan' && <NoticeUnreadBadge className="nav-mod-badge" />}
                  {mod.items.length > 1 && (
                    <ChevronDown size={14} className={`nav-mod-caret ${expanded ? 'open' : ''}`} />
                  )}
                </button>
                {expanded && (
                  <div className="nav-mod-items">
                    {mod.items.map((n) => (
                      <NavLink
                        key={n.to}
                        to={n.to}
                        end={n.exact}
                        className={({ isActive: a }) => `nav-item nav-sub ${a ? 'active' : ''}`}
                        aria-label={n.label}
                      >
                        <span className="nav-label">{n.label}</span>
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            )
          })}

          <div className="nav-group">
            <div className="nav-divider" />
            <div className="nav-group-title">其他</div>
            {otherItems.map((n) => (
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
            {days == null ? (
              <Link className="sc-unset" to="/settings">未设置初试日期</Link>
            ) : (
              <>
                <span className="sc-label">{estimated ? '距考试（预估）' : '距考试'}</span>
                <span className="sc-num">{days > 0 ? days : 0}</span>
                <span className="sc-label">天</span>
              </>
            )}
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
          {days != null && <span className="mt-count">倒计时 {days > 0 ? days : 0} 天</span>}
        </div>
      </header>

      {/* 主内容 */}
      <main className="main-area" key={location.pathname}>
        {/* 顶部科目切换器（可收缩）：全站统一科目入口，科目来自后端 /api/goals/subjects */}
        <SubjectSwitcher />
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
