import React, { useState, useEffect, useCallback, useRef } from 'react'
import { X } from './Icon'
import '../styles/toast.css'

/* ---------- Toast 轻提示 ----------
 * type 为空时保持旧行为（中性灰左边框）；'success' / 'error' 走 tokens.css
 * 的语义色（绿 / 红），用于「刷新 / 保存」这类需要明确成败的操作反馈。
 */
let toastSeq = 0
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

/**
 * 把焦点移到第一个未填/出错的字段，并保证它在视口内。
 * 用于表单空提交：既给文字提示，也让用户立刻看到该填哪里。
 * @param {HTMLElement|null} el
 * @returns {boolean} 是否成功聚焦
 */
export function focusAndScroll(el) {
  if (!el || typeof el.focus !== 'function') return false
  try {
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  } catch (e) {
    /* 老浏览器不支持 smooth，退化为默认滚动 */
    try { el.scrollIntoView() } catch (e2) { /* ignore */ }
  }
  el.focus({ preventScroll: true })
  return true
}

/* ---------- 弹窗（含焦点陷阱） ----------
 * 无障碍修复：弹层打开时键盘用户必须被「困」在弹层内。
 *   ① 打开时把焦点移入弹层首个可聚焦元素（记录触发元素，关闭后还原）；
 *   ② Tab / Shift+Tab 在弹层内循环，不允许焦点跑到背后的页面；
 *   ③ Escape 触发 onClose（沿用原有行为）。
 * 实现只用 useRef + useEffect，不引第三方库。
 */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function Modal({ open, title, onClose, children, footer }) {
  const panelRef = useRef(null)
  const triggerRef = useRef(null)

  useEffect(() => {
    if (!open) return
    // 背景滚动锁：弹层打开期间锁定 body 滚动（移动端防穿透滚动），关闭时还原
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    // 记录打开前的焦点元素（通常是触发弹窗的按钮），关闭后还原
    triggerRef.current = document.activeElement
    const panel = panelRef.current
    const focusables = () =>
      Array.from(panel?.querySelectorAll(FOCUSABLE_SELECTOR) || []).filter(
        (el) => el.offsetParent !== null || el === document.activeElement
      )
    // 聚焦首个可聚焦元素（无则聚焦弹层自身）
    const first = focusables()[0]
    ;(first || panel)?.focus?.()

    const onKey = (e) => {
      if (e.key === 'Escape') {
        onClose && onClose()
        return
      }
      if (e.key !== 'Tab') return
      const els = focusables()
      if (els.length === 0) {
        e.preventDefault()
        panel?.focus?.()
        return
      }
      const active = document.activeElement
      const idx = els.indexOf(active)
      if (e.shiftKey) {
        // Shift+Tab 在首个元素上 → 回到最后一个
        if (idx <= 0) { e.preventDefault(); els[els.length - 1].focus() }
      } else {
        // Tab 在最后一个元素上 → 回到第一个
        if (idx === els.length - 1) { e.preventDefault(); els[0].focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      // 关闭后把焦点还原给触发元素
      const t = triggerRef.current
      if (t && typeof t.focus === 'function' && document.contains(t)) {
        try { t.focus() } catch { /* 元素可能已卸载，忽略 */ }
      }
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" ref={panelRef} tabIndex={-1} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>{title}</b>
          <button className="modal-close" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

/**
 * useConfirm：基于 Modal 的 Promise 风格确认框，替代 window.confirm。
 *
 * 用法：
 *   const confirm = useConfirm()
 *   ...
 *   if (!(await confirm({ title: '删除科目', message: tip, danger: true }))) return
 *   // 确认后才执行
 *
 * @returns {(opts:{title?:string,message:string,confirmText?:string,cancelText?:string,danger?:boolean})=>Promise<boolean>}
 *          resolve(true) = 用户点击确认；resolve(false) = 取消 / 关闭 / 遮罩点击。
 */
export function useConfirm() {
  const [state, setState] = useState(null) // { title, message, confirmText, cancelText, danger, resolve }

  const confirm = useCallback(
    (opts = {}) =>
      new Promise((resolve) => {
        setState({
          title: opts.title || '请确认',
          message: opts.message || '',
          confirmText: opts.confirmText || '确认',
          cancelText: opts.cancelText || '取消',
          danger: !!opts.danger,
          resolve,
        })
      }),
    []
  )

  const close = (ok) => {
    setState((s) => {
      s?.resolve?.(ok)
      return null
    })
  }

  const dialog = state ? (
    <Modal
      open
      title={state.title}
      onClose={() => close(false)}
      footer={
        <>
          <button className="btn" onClick={() => close(false)}>{state.cancelText}</button>
          <button
            className={`btn ${state.danger ? 'danger' : 'primary'}`}
            onClick={() => close(true)}
          >
            {state.confirmText}
          </button>
        </>
      }
    >
      <div style={{ whiteSpace: 'pre-wrap' }}>{state.message}</div>
    </Modal>
  ) : null

  return [confirm, dialog]
}

/* ---------- 分段选择器 ---------- */
/**
 * 分段控件（Tab / 视图切换）。
 *
 * @param {object} props
 * @param {Array<{value:string,label:React.ReactNode,icon?:React.ReactNode}>} props.options
 *        选项列表。`icon` 为可选的 SVG 图标节点 ——
 *        旧代码习惯把图标写成文字前缀（如 "清单 题库列表"），
 *        那是「文字模拟图标」，观感差且容易写成 "卡包 卡包" 这种重复。
 *        统一改用真图标 + 纯文字标签。
 */
export function Segmented({ options, value, onChange }) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          className={`seg-btn ${value === o.value ? 'active' : ''}`}
          onClick={() => onChange(o.value)}
        >
          {o.icon && <span className="seg-ico">{o.icon}</span>}
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
