import React, {
  useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState,
} from 'react'
import { createPortal } from 'react-dom'
import {
  AlertCircle, AlertTriangle, Bot, CheckCircle2, InfoCircle, Sparkles, X,
} from '../icons'

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */
export const cx = (...parts) => parts.filter(Boolean).join(' ')

const prefersReduced = () => {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

export function useMedia(query) {
  const [matches, setMatches] = useState(() => {
    try {
      return window.matchMedia(query).matches
    } catch {
      return false
    }
  })
  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    mql.addEventListener('change', onChange)
    onChange()
    return () => mql.removeEventListener('change', onChange)
  }, [query])
  return matches
}

export function useClickOutside(ref, handler, active = true) {
  useEffect(() => {
    if (!active) return undefined
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) handler(e)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [ref, handler, active])
}

/* -------------------------------------------------------------------------- */
/* Button                                                                     */
/* -------------------------------------------------------------------------- */
function spawnRipple(e) {
  const el = e.currentTarget
  if (!el || prefersReduced()) return
  const rect = el.getBoundingClientRect()
  const size = Math.max(rect.width, rect.height) * 1.1
  const span = document.createElement('span')
  span.className = 'v3-ripple'
  span.style.width = `${size}px`
  span.style.height = `${size}px`
  span.style.left = `${e.clientX - rect.left - size / 2}px`
  span.style.top = `${e.clientY - rect.top - size / 2}px`
  el.appendChild(span)
  window.setTimeout(() => span.remove(), 700)
}

export function Button({
  variant = 'filled',
  size,
  icon,
  trailingIcon,
  loading = false,
  block = false,
  className = '',
  children,
  disabled,
  type = 'button',
  ...props
}) {
  const sizeClass = size ? `v3-btn--${size}` : ''
  return (
    <button
      type={type}
      className={cx('v3-btn', `v3-btn--${variant}`, sizeClass, block && 'v3-btn--block', className)}
      onPointerDown={spawnRipple}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <span className="v3-btn__spinner" aria-hidden="true" /> : icon}
      {children != null && children !== '' ? <span>{children}</span> : null}
      {trailingIcon}
    </button>
  )
}

export function IconButton({
  label,
  size,
  variant,
  icon,
  className = '',
  tip = true,
  ...props
}) {
  return (
    <span className={tip ? 'v3-tip' : undefined} data-tip={tip ? label : undefined}>
      <button
        type="button"
        aria-label={label}
        className={cx('v3-iconbtn', size && `v3-iconbtn--${size}`, variant && `v3-iconbtn--${variant}`, className)}
        onPointerDown={spawnRipple}
        {...props}
      >
        {icon}
      </button>
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* Surfaces                                                                   */
/* -------------------------------------------------------------------------- */
export function Card({ variant, interactive, glow, className = '', children, as: As = 'div', ...props }) {
  return (
    <As
      className={cx(
        'v3-card',
        variant && `v3-card--${variant}`,
        interactive && 'v3-card--interactive',
        glow && 'v3-card--glow',
        className,
      )}
      {...(interactive && As === 'div' ? { role: 'button', tabIndex: 0 } : {})}
      {...props}
    >
      {children}
    </As>
  )
}

export function Tile({ span = 12, variant, interactive, className = '', children, as: As = 'div', ...props }) {
  return (
    <As
      className={cx('v3-tile', `v3-span-${span}`, variant && `v3-tile--${variant}`, interactive && 'v3-tile--interactive', className)}
      {...(interactive && As === 'div' ? { role: 'button', tabIndex: 0 } : {})}
      {...props}
    >
      {children}
    </As>
  )
}

export function CardHead({ icon, title, sub, actions }) {
  return (
    <div className="v3-card__head">
      <div>
        <div className="v3-card__title">
          {icon}
          {title}
        </div>
        {sub ? <div className="v3-card__sub">{sub}</div> : null}
      </div>
      {actions ? <div className="v3-row">{actions}</div> : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Chips / badges / avatars                                                   */
/* -------------------------------------------------------------------------- */
export function Chip({ active, gradient, icon, children, className = '', as: As = 'button', ...props }) {
  return (
    <As
      type={As === 'button' ? 'button' : undefined}
      className={cx('v3-chip', active && 'v3-chip--active', gradient && 'v3-chip--gradient', className)}
      {...props}
    >
      {icon}
      {children}
    </As>
  )
}

export function Badge({ tone, className = '', children, ...props }) {
  return (
    <span className={cx('v3-badge', tone && `v3-badge--${tone}`, className)} {...props}>
      {children}
    </span>
  )
}

export function Avatar({ name = '', size, className = '', src, ...props }) {
  const initial = String(name || '?').trim().slice(0, 1).toUpperCase()
  return (
    <span className={cx('v3-avatar', size && `v3-avatar--${size}`, className)} title={name} {...props}>
      {src ? <img src={src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} /> : initial}
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* Form controls                                                              */
/* -------------------------------------------------------------------------- */
export function Field({ label, hint, error, htmlFor, children, className = '' }) {
  return (
    <label className={cx('v3-field', className)} htmlFor={htmlFor}>
      {label ? <span className="v3-label">{label}</span> : null}
      {children}
      {error ? <span className="v3-field__error">{error}</span> : hint ? <span className="v3-field__hint">{hint}</span> : null}
    </label>
  )
}

export const Input = React.forwardRef(function Input({ icon, className = '', ...props }, ref) {
  if (icon) {
    return (
      <span className="v3-input-group">
        <span className="v3-input-group__icon">{icon}</span>
        <input ref={ref} className={cx('v3-input', className)} {...props} />
      </span>
    )
  }
  return <input ref={ref} className={cx('v3-input', className)} {...props} />
})

export const Textarea = React.forwardRef(function Textarea({ className = '', ...props }, ref) {
  return <textarea ref={ref} className={cx('v3-textarea', className)} {...props} />
})

export function Select({ options = [], className = '', children, ...props }) {
  return (
    <select className={cx('v3-select', className)} {...props}>
      {children || options.map((o) => {
        const value = typeof o === 'string' ? o : o.value
        const label = typeof o === 'string' ? o : o.label
        return <option key={value} value={value}>{label}</option>
      })}
    </select>
  )
}

export function Switch({ checked, onChange, label, ...props }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={!!checked}
      aria-label={label}
      className="v3-switch"
      onClick={() => onChange?.(!checked)}
      {...props}
    />
  )
}

/* Segmented control with a sliding indicator */
export function Segmented({ options = [], value, onChange, className = '', ariaLabel = '视图切换' }) {
  const wrapRef = useRef(null)
  const btnRefs = useRef(new Map())
  const [indicator, setIndicator] = useState({ left: 4, width: 0, ready: false })
  const normalized = options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o))

  const sync = useCallback(() => {
    const el = btnRefs.current.get(value)
    const wrap = wrapRef.current
    if (!el || !wrap) return
    const wr = wrap.getBoundingClientRect()
    const er = el.getBoundingClientRect()
    setIndicator({ left: er.left - wr.left, width: er.width, ready: true })
  }, [value])

  useLayoutEffect(() => {
    sync()
  }, [sync, normalized.length])

  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(sync)
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [sync])

  return (
    <div ref={wrapRef} role="tablist" aria-label={ariaLabel} className={cx('v3-seg', className)}>
      {indicator.ready ? (
        <span className="v3-seg__indicator" style={{ left: indicator.left, width: indicator.width }} aria-hidden="true" />
      ) : null}
      {normalized.map((o) => (
        <button
          key={o.value}
          ref={(el) => {
            if (el) btnRefs.current.set(o.value, el)
            else btnRefs.current.delete(o.value)
          }}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          className="v3-seg__btn"
          onClick={() => onChange?.(o.value)}
        >
          {o.icon ? <span style={{ display: 'inline-flex', marginRight: 6, verticalAlign: '-4px' }}>{o.icon}</span> : null}
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Tabs({ options = [], value, onChange, className = '', ariaLabel = '标签页' }) {
  return (
    <div role="tablist" aria-label={ariaLabel} className={cx('v3-tabs', className)}>
      {options.map((o) => {
        const opt = typeof o === 'string' ? { value: o, label: o } : o
        return (
          <button
            key={opt.value}
            type="button"
            role="tab"
            aria-selected={value === opt.value}
            className="v3-tab"
            onClick={() => onChange?.(opt.value)}
          >
            {opt.icon ? <span style={{ display: 'inline-flex', marginRight: 6, verticalAlign: '-4px' }}>{opt.icon}</span> : null}
            {opt.label}
            {opt.count != null ? <span className="v3-badge" style={{ marginLeft: 6 }}>{opt.count}</span> : null}
          </button>
        )
      })}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Feedback                                                                   */
/* -------------------------------------------------------------------------- */
export function Progress({ value = 0, gradient = false, indeterminate = false, className = '', height }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div
      className={cx('v3-progress', indeterminate && 'v3-progress--indeterminate', className)}
      role="progressbar"
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      style={height ? { height } : undefined}
    >
      <div className={cx('v3-progress__bar', gradient && 'v3-progress__bar--gradient')} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Ring({ value = 0, size = 72, stroke = 7, gradient = false, children, className = '' }) {
  const gid = useId().replace(/:/g, '')
  const radius = (size - stroke) / 2
  const c = 2 * Math.PI * radius
  const pct = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div className={cx('v3-ring', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} aria-hidden="true">
        <defs>
          <linearGradient id={`ring-${gid}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#4285F4" />
            <stop offset="52%" stopColor="#9B72CB" />
            <stop offset="100%" stopColor="#D96570" />
          </linearGradient>
        </defs>
        <circle className="v3-ring__track" cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke} />
        <circle
          className="v3-ring__value"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          stroke={gradient ? `url(#ring-${gid})` : undefined}
          strokeDasharray={c}
          strokeDashoffset={c - (pct / 100) * c}
        />
      </svg>
      <div className="v3-ring__center">{children}</div>
    </div>
  )
}

export function Skeleton({ width = '100%', height = 14, radius, className = '', style }) {
  return (
    <span
      className={cx('v3-skeleton', className)}
      style={{ display: 'block', width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
    />
  )
}

export function Empty({ icon, title, text, action, className = '' }) {
  return (
    <div className={cx('v3-empty', className)}>
      <div className="v3-empty__orb" aria-hidden="true">{icon || <Sparkles size={26} />}</div>
      {title ? <h3 className="v3-empty__title">{title}</h3> : null}
      {text ? <p className="v3-empty__text">{text}</p> : null}
      {action}
    </div>
  )
}

export function Spinner({ size = 22 }) {
  return <span className="v3-spinner" style={{ width: size, height: size }} aria-label="加载中" role="status" />
}

export function LoadingState({ text = '加载中…' }) {
  return (
    <div className="v3-loading-page" role="status">
      <div className="v3-loading-page__orb" aria-hidden="true" />
      <span>{text}</span>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Toast + LiveRegion                                                         */
/* -------------------------------------------------------------------------- */
/* R3：播报只走一条通道 —— 常驻 LiveRegion（polite / assertive 各一个，
   aria-atomic 整句播报）。可视 Toast 本身不再带 role=status，避免双重朗读。 */
const toastSubs = new Set()
const liveSubs = new Set()
let toastSeq = 0

function emitToast(message, { type = '', duration = 3000 } = {}) {
  const item = { id: ++toastSeq, message, type }
  toastSubs.forEach((fn) => fn(item))
  liveSubs.forEach((fn) => fn({ message, assertive: type === 'err' }))
  if (duration > 0) {
    window.setTimeout(() => {
      toastSubs.forEach((fn) => fn({ id: item.id, dismiss: true }))
    }, duration)
  }
  return item.id
}

export function toast(message, duration = 3000, type = '') {
  return emitToast(message, { type, duration })
}

export function toastOk(message, duration = 3000) {
  return emitToast(message, { type: 'ok', duration })
}

export function toastErr(message, duration = 3400) {
  return emitToast(message, { type: 'err', duration })
}

export function toastWarn(message, duration = 3000) {
  return emitToast(message, { type: 'warn', duration })
}

/** 只播报、不弹可视 Toast（用于进度/状态类一次性说明）。 */
export function announce(message, { assertive = false } = {}) {
  liveSubs.forEach((fn) => fn({ message, assertive }))
}

const TOAST_ICON = {
  ok: <CheckCircle2 size={18} />,
  err: <AlertCircle size={18} />,
  warn: <AlertTriangle size={18} />,
  info: <InfoCircle size={18} />,
}

export function ToastHost() {
  const [items, setItems] = useState([])
  const [polite, setPolite] = useState('')
  const [assertive, setAssertive] = useState('')
  useEffect(() => {
    const fn = (item) => {
      setItems((prev) => {
        if (item.dismiss) return prev.filter((x) => x.id !== item.id)
        return [...prev.slice(-3), item]
      })
    }
    const live = ({ message, assertive: isAssertive }) => {
      /* 先清空再写入：相同文案连续播报时也能被读屏器感知 */
      if (isAssertive) {
        setAssertive('')
        window.setTimeout(() => setAssertive(message), 30)
      } else {
        setPolite('')
        window.setTimeout(() => setPolite(message), 30)
      }
    }
    toastSubs.add(fn)
    liveSubs.add(live)
    return () => {
      toastSubs.delete(fn)
      liveSubs.delete(live)
    }
  }, [])
  const dismiss = (id) => setItems((prev) => prev.filter((x) => x.id !== id))
  return createPortal(
    <div className="v3-toast-host v3-portal">
      {/* 常驻 live region：没有 Toast 时也存在于 DOM 中 */}
      <div className="v3-sr-only" role="status" aria-live="polite" aria-atomic="true">{polite}</div>
      <div className="v3-sr-only" role="alert" aria-live="assertive" aria-atomic="true">{assertive}</div>
      {items.map((item) => (
        <div key={item.id} className={cx('v3-toast', item.type && `v3-toast--${item.type}`)}>
          {item.type ? <span className="v3-toast__icon" aria-hidden="true">{TOAST_ICON[item.type] || TOAST_ICON.info}</span> : null}
          <span className="v3-toast__msg">{item.message}</span>
          <button type="button" className="v3-toast__close" aria-label="关闭通知" onClick={() => dismiss(item.id)}>
            <X size={14} />
          </button>
        </div>
      ))}
    </div>,
    document.body,
  )
}

/* -------------------------------------------------------------------------- */
/* Dialog / sheet / menu                                                      */
/* -------------------------------------------------------------------------- */
export function Dialog({ open, title, sub, onClose, children, footer, wide, full, className = '' }) {
  const panelRef = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
      if (e.key === 'Tab' && panelRef.current) {
        const nodes = panelRef.current.querySelectorAll('a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])')
        if (!nodes.length) return
        const first = nodes[0]
        const last = nodes[nodes.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey)
    const t = window.setTimeout(() => {
      const node = panelRef.current?.querySelector('input, textarea, select, button')
      node?.focus?.()
    }, 60)
    return () => {
      document.body.style.overflow = prevOverflow
      document.removeEventListener('keydown', onKey)
      window.clearTimeout(t)
    }
  }, [open, onClose])

  if (!open) return null
  return createPortal(
    <div
      className="v3-backdrop v3-portal"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.()
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        className={cx('v3-dialog', wide && 'v3-dialog--wide', full && 'v3-dialog--full', className)}
      >
        {(title || onClose) ? (
          <div className="v3-dialog__head">
            <div>
              {title ? <div className="v3-dialog__title">{title}</div> : null}
              {sub ? <div className="v3-dialog__sub">{sub}</div> : null}
            </div>
            {onClose ? <IconButton label="关闭" size="sm" icon={<X size={18} />} onClick={onClose} /> : null}
          </div>
        ) : null}
        <div className="v3-dialog__body">{children}</div>
        {footer ? <div className="v3-dialog__foot">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  )
}

/* Compatibility wrapper for legacy call sites */
export function Modal({ open, title, onClose, children, footer, width }) {
  return (
    <Dialog open={open} title={title} onClose={onClose} footer={footer} wide={width === 'wide' || width > 640}>
      {children}
    </Dialog>
  )
}

export function Sheet({ open, title, onClose, children, footer }) {
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="v3-portal">
      <div className="v3-sheet-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }} />
      <div className="v3-sheet" role="dialog" aria-modal="true" aria-label={title}>
        <div className="v3-sheet__handle" />
        <div className="v3-dialog__head" style={{ paddingTop: 8 }}>
          <div className="v3-dialog__title">{title}</div>
          <IconButton label="关闭" size="sm" icon={<X size={18} />} onClick={onClose} />
        </div>
        <div className="v3-sheet__body">{children}</div>
        {footer ? <div className="v3-dialog__foot">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  )
}

export function Menu({ open, anchorRef, onClose, align = 'end', children, width = 220 }) {
  const menuRef = useRef(null)
  const [pos, setPos] = useState(null)

  useLayoutEffect(() => {
    if (!open || !anchorRef?.current) return
    const r = anchorRef.current.getBoundingClientRect()
    const left = align === 'end' ? Math.max(8, r.right - width) : Math.min(window.innerWidth - width - 8, r.left)
    setPos({ left, top: r.bottom + 8, width, flipped: false })
  }, [open, anchorRef, align, width])

  /* 先渲染再量真实高度：下方放不下就翻到锚点上方。
     只把 top 压到 innerHeight-40 会让高菜单整体掉出屏幕，点不到任何一项。 */
  useLayoutEffect(() => {
    if (!open || !pos || pos.flipped || !menuRef.current) return
    const h = menuRef.current.getBoundingClientRect().height
    if (pos.top + h <= window.innerHeight - 8) return
    if (!anchorRef?.current) return
    const r = anchorRef.current.getBoundingClientRect()
    const above = r.top - h - 8
    setPos((p) => ({
      ...p,
      top: above >= 8 ? above : Math.max(8, window.innerHeight - h - 8),
      flipped: true,
    }))
  }, [open, pos, anchorRef])

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => {
      if (menuRef.current?.contains(e.target)) return
      if (anchorRef?.current?.contains(e.target)) return
      onClose?.()
    }
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose, anchorRef])

  if (!open || !pos) return null
  return createPortal(
    <div ref={menuRef} className="v3-menu v3-portal" style={{ left: pos.left, top: pos.top, width: pos.width }} role="menu">
      {children}
    </div>,
    document.body,
  )
}

export function MenuItem({ icon, danger, children, ...props }) {
  return (
    <button type="button" role="menuitem" className="v3-menu__item" style={danger ? { color: 'var(--v3-danger)' } : undefined} {...props}>
      {icon}
      <span>{children}</span>
    </button>
  )
}

/* -------------------------------------------------------------------------- */
/* Numbers / headers / stats                                                  */
/* -------------------------------------------------------------------------- */
export function AnimatedNumber({ value, duration = 720, format = (n) => Math.round(n), className = '' }) {
  const target = Number(value)
  const safeTarget = Number.isFinite(target) ? target : 0
  const [display, setDisplay] = useState(safeTarget)
  const prev = useRef(safeTarget)
  useEffect(() => {
    const from = prev.current
    prev.current = safeTarget
    if (from === safeTarget || prefersReduced()) {
      setDisplay(safeTarget)
      return undefined
    }
    let raf = 0
    const start = performance.now()
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setDisplay(from + (safeTarget - from) * eased)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [safeTarget, duration])
  return <span className={cx('v3-num', className)}>{format(display)}</span>
}

export const CountUp = AnimatedNumber

export function PageHeader({ eyebrow, title, sub, actions, icon }) {
  return (
    <header className="v3-page-head">
      <div className="v3-page-head__main">
        {eyebrow ? <div className="v3-eyebrow" style={{ marginBottom: 8 }}>{eyebrow}</div> : null}
        <h1 className="v3-page-head__title">
          {icon ? <span style={{ color: 'var(--v3-primary)', display: 'inline-flex' }}>{icon}</span> : null}
          {title}
        </h1>
        {sub ? <div className="v3-page-head__sub">{sub}</div> : null}
      </div>
      {actions ? <div className="v3-page-head__actions">{actions}</div> : null}
    </header>
  )
}

export function SectionHead({ title, icon, actions, sub }) {
  return (
    <div className="v3-section-head">
      <div>
        <div className="v3-section-title">{icon}{title}</div>
        {sub ? <div className="v3-caption" style={{ marginTop: 2 }}>{sub}</div> : null}
      </div>
      {actions ? <div className="v3-row">{actions}</div> : null}
    </div>
  )
}

export function Stat({ label, value, hint, delta, deltaDown, icon, format }) {
  return (
    <div className="v3-stat">
      <span className="v3-stat__label">{icon}{label}</span>
      <span className="v3-stat__value">
        <AnimatedNumber value={value} format={format} />
      </span>
      {delta != null ? (
        <span className={cx('v3-stat__delta', deltaDown && 'v3-stat__delta--down')}>{delta}</span>
      ) : hint ? <span className="v3-caption">{hint}</span> : null}
    </div>
  )
}

export function Alert({ tone = 'info', icon, children, className = '' }) {
  return (
    <div className={cx('v3-alert', `v3-alert--${tone}`, className)} role="status">
      {icon || (tone === 'danger' ? <AlertCircle size={18} /> : tone === 'success' ? <CheckCircle2 size={18} /> : <InfoCircle size={18} />)}
      <div>{children}</div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Confirm dialog (legacy-compatible [confirm, dialog] pair)                  */
/* -------------------------------------------------------------------------- */
export function useConfirm() {
  const [state, setState] = useState(null)
  const confirm = useCallback((opts) => new Promise((resolve) => {
    const o = typeof opts === 'string' ? { text: opts } : (opts || {})
    setState({ ...o, resolve })
  }), [])
  const close = (v) => {
    state?.resolve(v)
    setState(null)
  }
  const dialog = (
    <Dialog
      open={!!state}
      title={state?.title || '请确认'}
      sub={state?.text || state?.message}
      onClose={() => close(false)}
      footer={(
        <>
          <Button variant="text" onClick={() => close(false)}>{state?.cancelText || '取消'}</Button>
          <Button variant={state?.danger ? 'danger' : 'filled'} onClick={() => close(true)}>
            {state?.confirmText || state?.okText || '确定'}
          </Button>
        </>
      )}
    >
      {state?.content || null}
    </Dialog>
  )
  return [confirm, dialog]
}

/* -------------------------------------------------------------------------- */
/* Pager                                                                      */
/* -------------------------------------------------------------------------- */
/* 与后端 utils/response.py MAX_PAGE_SIZE 同一口径 */
export const PAGER_MAX_PAGE_SIZE = 200

const PAGER_WINDOW = 7

/* 编号页码窗口（沿用 KaoyanSchools 的实现）：最多 7 个连续页码 */
function pageWindow(cur, total) {
  if (total <= PAGER_WINDOW) return Array.from({ length: total }, (_, i) => i + 1)
  const start = Math.min(Math.max(1, cur - 3), total - (PAGER_WINDOW - 1))
  return Array.from({ length: PAGER_WINDOW }, (_, i) => start + i)
}

/**
 * 通用编号分页：« 1 … k-1 k k+1 … n » + 「第x/y页」+ 可选「每页 N 条」Select。
 * 换页后自动滚回 containerRef 指向的列表容器顶部（focusAndScroll 现成工具）。
 */
export function Pager({
  page,
  pageSize = 20,
  total,
  totalPages,
  onChange,
  onPageSizeChange,
  pageSizeOptions = [20, 50, 100, 200],
  unit = '条',
  label = '分页',
  disabled = false,
  containerRef,
  className = '',
}) {
  const size = Number(pageSize) > 0 ? Number(pageSize) : 20
  const pages = Math.max(1, Number(totalPages) || Math.ceil((Number(total) || 0) / size) || 1)
  const cur = Math.min(Math.max(1, Number(page) || 1), pages)

  const scrollToTop = () => {
    if (containerRef?.current) focusAndScroll(containerRef.current, 96)
  }

  const goto = (p) => {
    const next = Math.min(Math.max(1, p), pages)
    if (next === cur || disabled) return
    onChange?.(next)
    scrollToTop()
  }

  const pickPageSize = (e) => {
    const n = Math.min(Math.max(1, Number(e.target.value) || size), PAGER_MAX_PAGE_SIZE)
    if (n === size) return
    onPageSizeChange?.(n)
    scrollToTop()
  }

  const numbers = pageWindow(cur, pages)
  const sizeChoices = [...new Set([...pageSizeOptions, size])]
    .filter((n) => n >= 1 && n <= PAGER_MAX_PAGE_SIZE)
    .sort((a, b) => a - b)

  if (pages <= 1 && !onPageSizeChange) return null

  return (
    <nav className={cx('v3-pager', className)} aria-label={label}>
      <button type="button" aria-label="上一页" disabled={disabled || cur <= 1} onClick={() => goto(cur - 1)}>«</button>
      {numbers[0] > 1 ? (
        <>
          <button type="button" onClick={() => goto(1)}>1</button>
          {numbers[0] > 2 ? <span className="v3-pager__gap" aria-hidden="true">…</span> : null}
        </>
      ) : null}
      {numbers.map((n) => (
        <button key={n} type="button" className={n === cur ? 'is-current' : ''} aria-current={n === cur ? 'page' : undefined} onClick={() => goto(n)}>
          {n}
        </button>
      ))}
      {numbers[numbers.length - 1] < pages ? (
        <>
          {numbers[numbers.length - 1] < pages - 1 ? <span className="v3-pager__gap" aria-hidden="true">…</span> : null}
          <button type="button" onClick={() => goto(pages)}>{pages}</button>
        </>
      ) : null}
      <button type="button" aria-label="下一页" disabled={disabled || cur >= pages} onClick={() => goto(cur + 1)}>»</button>
      <span className="v3-pager__info">
        第 {cur}/{pages} 页
        {total != null ? ` · 共 ${total} ${unit}` : ''}
      </span>
      {onPageSizeChange ? (
        <Select
          className="v3-pager__size"
          aria-label="每页条数"
          value={String(size)}
          onChange={pickPageSize}
          disabled={disabled}
          options={sizeChoices.map((n) => ({ value: String(n), label: `每页 ${n} 条` }))}
        />
      ) : null}
    </nav>
  )
}

/* -------------------------------------------------------------------------- */
/* Misc                                                                       */
/* -------------------------------------------------------------------------- */
export function focusAndScroll(el, offset = 96) {
  if (!el) return
  const top = el.getBoundingClientRect().top + window.scrollY - offset
  window.scrollTo({ top, behavior: prefersReduced() ? 'auto' : 'smooth' })
  window.setTimeout(() => {
    try {
      el.focus?.({ preventScroll: true })
    } catch {
      el.focus?.()
    }
  }, 320)
}

export function Kbd({ children }) {
  return <kbd className="v3-kbd">{children}</kbd>
}

export function SparkleBadge({ children }) {
  return (
    <span className="v3-badge v3-badge--gradient">
      <Sparkles size={12} />
      {children}
    </span>
  )
}

export function BotHint({ children }) {
  return (
    <span className="v3-caption" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <Bot size={14} />
      {children}
    </span>
  )
}
