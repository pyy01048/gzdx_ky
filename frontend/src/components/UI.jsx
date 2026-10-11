import React, { useState, useEffect, useCallback } from 'react'

/* ---------- Toast 轻提示 ---------- */
let toastSeq = 0
export function toast(msg, dur = 2200) {
  const root = document.getElementById('toastRoot') || document.body
  let box = document.getElementById('toastRoot')
  if (!box) {
    box = document.createElement('div')
    box.id = 'toastRoot'
    document.body.appendChild(box)
  }
  const el = document.createElement('div')
  el.className = 'toast'
  el.textContent = msg
  box.appendChild(el)
  setTimeout(() => {
    el.classList.add('out')
    setTimeout(() => el.remove(), 300)
  }, dur)
}

/* ---------- 弹窗 ---------- */
export function Modal({ open, title, onClose, children, footer }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>{title}</b>
          <button className="modal-close" onClick={onClose} aria-label="关闭">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

/* ---------- 分段选择器 ---------- */
export function Segmented({ options, value, onChange }) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          className={`seg-btn ${value === o.value ? 'active' : ''}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* ---------- 空状态 ---------- */
/* 批次0-2 修复：
   ① 旧签名 ({icon,title,desc,action}) 不接收 text，导致 6 处 <Empty text="..."/> 全空白；
      这里把 text 作为 title 的别名（兼容），同时补 desc 缺省，避免二次踩坑。
   ② 旧图标类名（拼写错误，全项目未定义；真实类名是 global.css:1000 的 .empty-state-icon）；
   ③ 裸 <b>/<span> 未挂 .empty-state-title/-desc，字号/颜色/间距全失。
   注意：不要改 .empty（v2-design.css:558 另一套样式），只对齐 global.css:996-1003 已有的类。 */
export function Empty({ icon, title, text, desc, action }) {
  const heading = title ?? text
  return (
    <div className="empty-state">
      {icon && <div className="empty-state-icon">{icon}</div>}
      {heading && <div className="empty-state-title">{heading}</div>}
      {desc && <div className="empty-state-desc">{desc}</div>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  )
}

/* ---------- 科目标签 ---------- */
export const SUBJECT_MAP = {
  math: { name: '数学', cls: 'math' },
  english: { name: '英语', cls: 'english' },
  politics: { name: '政治', cls: 'politics' },
  major: { name: '专业课', cls: 'major' }
}
export function SubTag({ subject }) {
  const s = SUBJECT_MAP[subject] || { name: subject || '其他', cls: 'math' }
  return <span className={`tag ${s.cls}`}>{s.name}</span>
}

/* ---------- 数字动画（滚动递增） ---------- */
export function CountUp({ value, duration = 600 }) {
  const [disp, setDisp] = useState(0)
  useEffect(() => {
    let raf
    const start = performance.now()
    const from = disp
    const step = (t) => {
      const p = Math.min((t - start) / duration, 1)
      const eased = 1 - Math.pow(1 - p, 3)
      setDisp(Math.round(from + (value - from) * eased))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  return <>{disp}</>
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
  // 渲染期同步应用：保证首帧 DOM 已是目标主题（与 index.html 内联防闪脚本双保险）
  if (theme !== currentPref) {
    currentPref = theme
    currentResolved = resolveTheme(theme)
    writeToDOM(currentResolved)
  }

  const [resolved, setResolved] = useState(
    () => (currentResolved === null ? resolveTheme(theme) : currentResolved)
  )

  useEffect(() => {
    setResolved(currentResolved)
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

  // 偏好变化（含 store 被别处改写，如导入备份）时重新解析并写 DOM
  useEffect(() => {
    if (theme !== currentPref) applyTheme(theme)
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
