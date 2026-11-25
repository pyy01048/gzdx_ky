/* eslint-disable react-refresh/only-export-components */
import { useEffect, useState } from 'react'
import {
  AlertCircle, ChevronDown, ChevronLeft, ChevronRight, X,
} from '../v3/icons'

export const cx = (...parts) => parts.filter(Boolean).join(' ')

/** 媒体查询 hook（自包含，不依赖 v3/ui 脏文件） */
export function useMedia(query) {
  const [matches, setMatches] = useState(() => {
    try { return window.matchMedia(query).matches } catch { return false }
  })
  useEffect(() => {
    let mql
    try { mql = window.matchMedia(query) } catch { return undefined }
    const onChange = () => setMatches(mql.matches)
    mql.addEventListener('change', onChange)
    onChange()
    return () => mql.removeEventListener('change', onChange)
  }, [query])
  return matches
}

/** 统一图标渲染：给所有图标加 .ic 尺寸类 */
export function Ic({ of: Cmp, size = 16, className = '', ...rest }) {
  if (!Cmp) return null
  return <Cmp className={cx('ic', className)} width={size} height={size} {...rest} />
}

/* ---------------- Skeleton ---------------- */
export function Skeleton({ className = '', style }) {
  return <div className={cx('im-skeleton', className)} style={{ height: 14, ...style }} />
}

/* ---------------- Empty ---------------- */
export function Empty({ icon: IconCmp = AlertCircle, title = '暂无数据', hint, action }) {
  return (
    <div className="im-empty">
      <Ic of={IconCmp} size={40} />
      <h4>{title}</h4>
      {hint && <p>{hint}</p>}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  )
}

/* ---------------- Chip ---------------- */
export function Chip({ tone, children, className = '' }) {
  return <span className={cx('im-chip', tone && `im-chip--${tone}`, className)}>{children}</span>
}

/* ---------------- Progress ---------------- */
export function Progress({ value = 0, className = '' }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div className={cx('im-progress', className)} role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${v}%` }} />
    </div>
  )
}

/* ---------------- Stat ---------------- */
export function Stat({ value, label, tone }) {
  return (
    <div className="im-stat">
      <b style={tone ? { color: `var(--im-${tone})` } : undefined}>{value}</b>
      <span>{label}</span>
    </div>
  )
}

/* ---------------- Spinner ---------------- */
export function Spinner({ size = 18 }) {
  return (
    <span className="im-spinner" style={{ width: size, height: size }} aria-label="加载中" />
  )
}

/* ---------------- 确认无值 ---------------- */
export const isEmpty = (v) => v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)

export { ChevronLeft, ChevronRight, ChevronDown, X }
