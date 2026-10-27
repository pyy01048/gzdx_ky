import { useEffect, useState } from 'react'
import '../styles/toast.css'

/* ---------- Toast 轻提示 ----------
 * type 为空时保持旧行为（中性灰左边框）；'success' / 'error' 走 tokens.css
 * 的语义色（绿 / 红），用于「刷新 / 保存」这类需要明确成败的操作反馈。
 */
export function toast(msg, dur = 2200, type = '') {
  let box = document.getElementById('toastRoot')
  if (!box) {
    box = document.createElement('div')
    box.id = 'toastRoot'
    document.body.appendChild(box)
  }
  // 固定定位容器：此前只建了 #toastRoot 却没挂 .toast-container，
  // 提示会按普通文档流追加到 body 末尾（页面底部），用户容易看不到。
  if (!box.classList.contains('toast-container')) box.classList.add('toast-container')
  const el = document.createElement('div')
  el.className = type ? `toast toast-${type}` : 'toast'
  el.setAttribute('role', type === 'error' ? 'alert' : 'status')
  el.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite')
  el.textContent = msg
  box.appendChild(el)
  setTimeout(() => {
    el.classList.add('out')
    setTimeout(() => el.remove(), 300)
  }, dur)
}

/** 成功提示（绿色） */
export function toastOk(msg, dur = 1800) {
  return toast(msg, dur, 'success')
}

/** 失败提示（红色，停留更久，便于看清原因） */
export function toastErr(msg, dur = 3200) {
  return toast(msg, dur, 'error')
}

/* ---------- 主题系统（唯一负责把 data-theme 写到 <html> 的地方） ----------

 * V7.0 P0-1 修复：此前同一个 HTML 属性 `data-theme` 有 4 处写入路径
 * （App.jsx / Layout.jsx 的空依赖 effect / Layout.jsx 的 toggleTheme /
 *   Settings.jsx 的 saveSettings），且 Layout 用 `settings.theme === 'dark'`
 *   判断深浅，导致 theme 为 'system' 时按钮显示与实际渲染不一致、
 *   点击 toggle 后视觉上「什么都没变」。
 *
 * 现在统一为：theme（'light' | 'dark' | 'system'）→ resolvedTheme
 * （'light' | 'dark'）→ 唯一的 DOM 写入点。
 * -------------------------------------------------------------------- */

/** 读取系统是否偏好深色；对不支持 matchMedia 的环境降级为浅色 */
function readSystemDark() {
  const mql = getDarkMedia()
  return mql ? mql.matches : false
}

/** 获取 prefers-color-scheme: dark 的 MediaQueryList；环境不支持时返回 null */
function getDarkMedia() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  try {
    return window.matchMedia('(prefers-color-scheme: dark)')
  } catch (e) {
    return null
  }
}

/**
 * 把设置里的 theme 解析为实际生效的 'light' | 'dark'。
 * 非法值与 'system' 一律走系统偏好，保证调用方永远拿到合法值。
 *
 * @param {string} theme 设置中的主题偏好
 * @param {boolean} systemDark 系统是否偏好深色（仅 'system' 时使用）
 * @returns {'light'|'dark'} 实际生效主题
 */
export function resolveTheme(theme, systemDark = readSystemDark()) {
  if (theme === 'dark') return 'dark'
  if (theme === 'light') return 'light'
  return systemDark ? 'dark' : 'light'
}

/* ---------- 模块级主题单例 ----------
 * 多个组件（App / Layout）都会读主题。若每个组件各自 useEffect 写 DOM、
 * 各自 addEventListener('change')，就会重复写、重复订阅。这里用单例收敛：
 * 全应用只有一处 matchMedia 监听 + 一处 DOM 写入，组件只负责订阅状态。 */
let currentPref = null      // 上次收到的 theme 偏好
let currentResolved = null  // 上次解析出的实际主题
const themeSubscribers = new Set()

/** 把解析结果写入 <html data-theme>（全应用唯一 DOM 写入点） */
function writeToDOM(resolved) {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute('data-theme', resolved)
}

/** 应用一次主题偏好：解析 → 写 DOM → 通知订阅者（幂等，重复调用无副作用） */
function applyTheme(theme) {
  const resolved = resolveTheme(theme)
  currentPref = theme
  if (resolved !== currentResolved) {
    currentResolved = resolved
    writeToDOM(resolved)
  }
  themeSubscribers.forEach((fn) => fn(resolved))
}

/** 系统主题变化时重新应用（仅在偏好为 'system' 时才有实际影响） */
function handleSystemChange() {
  if (currentPref === 'system') applyTheme('system')
}

/**
 * 主题解析 + 应用 hook（组件侧唯一入口）。
 *
 * 副作用：把 resolvedTheme 写入 `document.documentElement[data-theme]`；
 * theme === 'system' 时实时响应系统亮/暗切换。
 * 多个组件同时调用是安全的——DOM 写入与媒体查询监听都是单例。
 *
 * @param {string} theme 设置中的主题偏好（'light' | 'dark' | 'system'）
 * @returns {'light'|'dark'} 实际生效主题，供按钮文案/图标等判断使用
 */
export function useResolvedTheme(theme) {
  /* 首帧同步写 DOM（与 index.html 内联防闪脚本双保险），但**不改 currentPref**：
     一旦在渲染期把 currentPref 改成新值，下面的 effect 就会误判「偏好没变」而
     跳过 applyTheme → 订阅者拿不到通知，主题按钮图标与 ECharts 配色会停在旧值。 */
  const immediate = resolveTheme(theme)
  if (currentResolved !== immediate) writeToDOM(immediate)

  const [resolved, setResolved] = useState(() => (currentResolved === null ? immediate : currentResolved))

  useEffect(() => {
    // 挂载时先对齐一次（applyTheme 幂等），保证 resolved 与 DOM 一致
    applyTheme(theme)
    setResolved(currentResolved ?? resolveTheme(theme))
    const onResolved = (next) => setResolved(next)
    themeSubscribers.add(onResolved)
    // 系统主题监听同样是单例：仅首个订阅者注册，最后一个退订时移除
    const isFirst = themeSubscribers.size === 1
    const mql = getDarkMedia()
    if (isFirst && mql) mql.addEventListener('change', handleSystemChange)
    return () => {
      themeSubscribers.delete(onResolved)
      if (themeSubscribers.size === 0 && mql) mql.removeEventListener('change', handleSystemChange)
    }
  }, [])

  // 偏好变化（含 store 被别处改写，如导入备份）时重新解析、写 DOM 并通知所有订阅者
  useEffect(() => {
    applyTheme(theme)
    setResolved(currentResolved ?? resolveTheme(theme))
  }, [theme])

  return resolved
}

/**
 * 兼容旧调用点：只需要副作用、不需要返回值的场景直接用它。
 * 内部完全委托给 useResolvedTheme，不重复实现任何写入逻辑。
 *
 * @param {string} theme 设置中的主题偏好
 */
export function useTheme(theme) {
  useResolvedTheme(theme)
}
