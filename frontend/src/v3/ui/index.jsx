import React, {
  useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState,
} from 'react'
import { createPortal } from 'react-dom'
import {
  AlertCircle, AlertTriangle, Bot, Check, CheckCircle2, ChevronDown, InfoCircle, Search,
  Sparkles, X,
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

/** 主按钮，支持 variant/size/icon/loading/ripple 动效。 */
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

/** 图标按钮，带 tooltip 与 ripple 动效。 */
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
/** 表单字段容器：label + 控件 + hint/error。点 label 文字会转发点击到自定义下拉。 */
export function Field({ label, hint, error, htmlFor, children, className = '' }) {
  /* W5-1：label 的 for 只能代理原生表单控件。自定义下拉是 button，
     点标题文字不会打开面板 —— 这里手动转发一次点击，保持既有的标签点按习惯。 */
  const onLabelClick = useCallback((e) => {
    const ctl = e.currentTarget.querySelector?.('.v3-xsel')
    if (ctl && !ctl.contains(e.target)) {
      e.preventDefault()
      ctl.click()
    }
  }, [])
  return (
    <label className={cx('v3-field', className)} htmlFor={htmlFor} onClick={onLabelClick}>
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

/* -------------------------------------------------------------------------- */
/* Select · 主题化下拉（W5-1 · 全站通病整改）                                   */
/* -------------------------------------------------------------------------- */
/* 原生 <select> 的展开面板由操作系统绘制，与 v3 主题（含暗色）脱节，手机端还是
   滚轮选择器，没有 44px 触控热区可言。这里按设计系统通用的 Combobox 重做：
   · 配色/圆角/阴影/字阶全部只取 tokens.css 变量，暗色自动跟随 [data-theme="dark"]；
   · 移动优先：≤767px 自动切成底部 Sheet（大热区 + 可搜索），桌面用固定定位浮层，
     放不下自动向上翻，超出一屏在面板内滚动；
   · 键盘可达：Enter/Space/↑/↓ 打开，↑↓/Home/End 移动焦点项，Enter 选中，
     Esc 关闭，无搜索框时支持首字母 typeahead；aria-activedescendant 单向播报；
   · props 契约与原生保持一致（value / onChange(e.target.value) / options /
     <option> 子元素混写），因此既有 60+ 处调用点无需改动即整体换装；
   · 遇到无法安全解析的子元素（<optgroup>、非 option 节点）自动回落原生实现，
     不改变行为、不吞选项。 */

function selPlainText(node) {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(selPlainText).join('')
  if (React.isValidElement(node)) return selPlainText(node.props?.children)
  return ''
}

function toSelOption(o) {
  if (o == null) return null
  if (typeof o === 'string' || typeof o === 'number') return { value: String(o), label: String(o) }
  const raw = o.value ?? o.id ?? ''
  const label = o.label ?? o.name ?? o.text ?? String(raw)
  return {
    value: String(raw),
    label: String(label),
    disabled: !!o.disabled,
    title: o.title || undefined,
  }
}

/* 返回 null 表示「解析不了，请用原生 select」 */
function parseSelOptions({ options, children }) {
  if (Array.isArray(options) && options.length) {
    return options.map(toSelOption).filter(Boolean)
  }
  if (children == null || children === false) return Array.isArray(options) ? [] : null
  const out = []
  let unsupported = false
  React.Children.forEach(children, (c) => {
    if (c == null || c === false) return
    if (React.isValidElement(c)) {
      if (c.type === 'option') {
        const label = selPlainText(c.props?.children)
        const raw = c.props?.value
        out.push({
          value: raw === undefined ? label : String(raw),
          label: label || String(raw ?? ''),
          disabled: !!c.props?.disabled,
          title: c.props?.title || undefined,
        })
        return
      }
      unsupported = true
      return
    }
    if (typeof c === 'string' || typeof c === 'number') {
      out.push({ value: String(c), label: String(c) })
      return
    }
    unsupported = true
  })
  if (unsupported) return null
  return out
}

function selStep(list, from, dir) {
  if (!list.length) return from
  let i = from
  for (let n = 0; n < list.length; n += 1) {
    i = (i + dir + list.length) % list.length
    if (!list[i].disabled) return i
  }
  return from
}

/* 回落实现：保持升级前的原生行为 */
function NativeSelect({ options = [], className = '', children, ...props }) {
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

export function Select(props) {
  const parsed = parseSelOptions(props)
  if (parsed === null) return <NativeSelect {...props} />
  return <DropdownSelect {...props} options={parsed} />
}

function DropdownSelect({
  options = [],
  className = '',
  style,
  value,
  defaultValue,
  onChange,
  disabled = false,
  id,
  placeholder = '请选择',
  searchable,
  size,
  title,
  name,
  children: _children,
  'aria-label': ariaLabel,
  ...rest
}) {
  const isMobile = useMedia('(max-width: 767px)')
  const uid = useId().replace(/:/g, '')
  const listId = `v3-sel-list-${uid}`
  const wrapRef = useRef(null)
  const triggerRef = useRef(null)
  const popRef = useRef(null)
  const sheetRef = useRef(null)
  const listRef = useRef(null)
  const searchRef = useRef(null)
  const typeRef = useRef('')
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [inner, setInner] = useState(defaultValue ?? '')
  const [pos, setPos] = useState(null)

  const controlled = value !== undefined
  const current = String(controlled ? (value ?? '') : inner)
  const all = options
  const searchableNow = (searchable === undefined ? all.length > 10 : !!searchable) && all.length > 4
  const norm = query.trim().toLowerCase()
  const list = useMemo(
    () => (norm
      ? all.filter((o) => o.label.toLowerCase().includes(norm) || o.value.toLowerCase().includes(norm))
      : all),
    [all, norm],
  )
  const activeIdx = list.length ? Math.min(Math.max(0, active), list.length - 1) : 0
  const picked = all.find((o) => o.value === current)
  const shown = current === '' ? placeholder : (picked ? picked.label : current)

  const emit = useCallback((v) => {
    if (!controlled) setInner(v)
    const ev = { target: { value: v }, currentTarget: { value: v } }
    onChange?.(ev)
  }, [controlled, onChange])

  const place = useCallback(() => {
    const el = triggerRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const w = Math.max(r.width, 176)
    const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8))
    const roomBelow = window.innerHeight - r.bottom - 20
    const roomAbove = r.top - 20
    const flip = roomBelow < 176 && roomAbove > roomBelow
    setPos({
      left,
      width: w,
      top: flip ? undefined : r.bottom + 6,
      bottom: flip ? Math.max(8, window.innerHeight - r.top + 6) : undefined,
      maxH: Math.max(160, flip ? roomAbove : roomBelow),
    })
  }, [])

  const openList = useCallback(() => {
    if (disabled || open) return
    const idx = all.findIndex((o) => o.value === current)
    setActive(idx < 0 ? 0 : idx)
    setQuery('')
    setOpen(true)
    if (!isMobile) {
      triggerRef.current?.focus?.()
      place()
    }
  }, [disabled, open, all, current, isMobile, place])

  const closeList = useCallback((refocus = true) => {
    setOpen(false)
    setPos(null)
    setQuery('')
    if (refocus) window.setTimeout(() => triggerRef.current?.focus?.(), 0)
  }, [])

  const pick = useCallback((o) => {
    if (!o || o.disabled) return
    emit(o.value)
    closeList()
  }, [emit, closeList])

  /* 打开后：搜索框抢焦点（长列表），并把当前项滚进视野 */
  useEffect(() => {
    if (!open) return undefined
    if (searchableNow) {
      const t = window.setTimeout(() => searchRef.current?.focus?.(), 30)
      return () => window.clearTimeout(t)
    }
    const el = listRef.current?.querySelector('[data-active="1"]')
    el?.scrollIntoView?.({ block: 'nearest' })
    return undefined
  }, [open, searchableNow, activeIdx])

  /* 浮层跟随滚动/缩放重新定位（Sheet 模式不需要） */
  useEffect(() => {
    if (!open || isMobile) return undefined
    const onMove = () => place()
    window.addEventListener('scroll', onMove, true)
    window.addEventListener('resize', onMove)
    return () => {
      window.removeEventListener('scroll', onMove, true)
      window.removeEventListener('resize', onMove)
    }
  }, [open, isMobile, place])

  /* 点外部 / Esc 关闭 */
  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => {
      if (wrapRef.current?.contains(e.target)) return
      if (popRef.current?.contains(e.target)) return
      if (sheetRef.current?.contains(e.target)) return
      closeList(false)
    }
    const onKey = (e) => {
      if (e.key === 'Escape') closeList()
    }
    document.addEventListener('pointerdown', onDown, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, closeList])

  const navKeys = (e) => {
    if (!open) return
    const k = e.key
    if (k === 'ArrowDown' || k === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => selStep(list, Math.min(a, list.length - 1), k === 'ArrowDown' ? 1 : -1))
      return
    }
    if (k === 'Home') {
      e.preventDefault()
      setActive(0)
      return
    }
    if (k === 'End') {
      e.preventDefault()
      setActive(list.length - 1)
      return
    }
    if (k === 'Enter' || (k === ' ' && e.target?.tagName !== 'INPUT')) {
      if (k === 'Enter') e.preventDefault()
      pick(list[activeIdx])
      return
    }
    if (k === 'Tab') closeList(false)
  }

  /* 无搜索框时的首字母跳转（成熟下拉的标配） */
  const typeahead = (e) => {
    if (searchableNow) return
    const k = e.key
    if (k === 'ArrowDown' || k === 'ArrowUp' || k === 'Enter' || k === 'Home' || k === 'End') return
    if (k.length !== 1 || /\s/.test(k)) return
    e.preventDefault()
    const buf = `${typeRef.current}${k}`
    typeRef.current = buf
    const needle = buf.trim().toLowerCase()
    const hit = list.findIndex((o) => o.label.toLowerCase().startsWith(needle))
    if (hit >= 0) {
      /* 顺序要紧：openList 会把 active 复位到当前选中项，先开再定位 */
      if (!open) {
        setQuery('')
        setOpen(true)
        if (!isMobile) place()
      }
      setActive(hit)
    }
    window.setTimeout(() => { typeRef.current = '' }, 600)
  }

  const onTriggerKeyDown = (e) => {
    if (disabled) return
    if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault()
      openList()
      return
    }
    navKeys(e)
  }

  const optionsNode = (
    <div
      className={cx('v3-xsel__list', isMobile && 'v3-xsel__list--sheet')}
      role="listbox"
      id={listId}
      ref={listRef}
      aria-label={ariaLabel || undefined}
    >
      {list.length ? null : <div className="v3-xsel__empty">没有匹配项</div>}
      {list.map((o, i) => (
        <button
          key={`${o.value}#${i}`}
          type="button"
          role="option"
          id={`${listId}-${i}`}
          tabIndex={-1}
          disabled={o.disabled}
          aria-selected={o.value === current}
          data-active={i === activeIdx && open ? '1' : undefined}
          title={o.title}
          className={cx('v3-xsel__opt', o.value === current && 'is-selected', i === activeIdx && open && 'is-active')}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => pick(o)}
        >
          <span className="v3-xsel__opt-label">{o.label}</span>
          {o.value === current ? <Check size={16} className="v3-xsel__check" /> : null}
        </button>
      ))}
    </div>
  )

  const searchNode = searchableNow ? (
    <div className="v3-xsel__search">
      <Search size={15} />
      <input
        ref={searchRef}
        type="search"
        className="v3-xsel__search-input"
        placeholder="搜索…"
        aria-label="搜索选项"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setActive(0) }}
        onKeyDown={navKeys}
      />
    </div>
  ) : null

  return (
    <span
      ref={wrapRef}
      className={cx('v3-xselw', className)}
      style={style}
      data-open={open || undefined}
      data-disabled={disabled || undefined}
      {...(name ? { 'data-name': name } : {})}
    >
      <button
        ref={triggerRef}
        type="button"
        id={id}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && list.length ? `${listId}-${activeIdx}` : undefined}
        aria-label={ariaLabel || undefined}
        disabled={disabled}
        title={title || (picked ? picked.label : undefined)}
        className={cx('v3-select', 'v3-xsel', size && `v3-xsel--${size}`, open && 'is-open', className)}
        onClick={() => (open ? closeList() : openList())}
        onKeyDown={onTriggerKeyDown}
        onKeyUp={typeahead}
        {...rest}
      >
        <span className={cx('v3-xsel__text', current === '' && 'is-placeholder')}>{shown}</span>
        <ChevronDown size={16} className={cx('v3-xsel__arrow', open && 'is-open')} />
      </button>

      {open && !isMobile && pos ? (
        createPortal(
          <div
            ref={popRef}
            className="v3-xsel__pop v3-portal"
            style={{
              left: pos.left,
              top: pos.top,
              bottom: pos.bottom,
              width: pos.width,
              maxHeight: pos.maxH,
            }}
          >
            {searchNode}
            {optionsNode}
          </div>,
          document.body,
        )
      ) : null}

      {open && isMobile ? (
        createPortal(
          <div className="v3-portal">
            <div
              className="v3-sheet-backdrop"
              onMouseDown={(e) => { if (e.target === e.currentTarget) closeList() }}
            />
            <div
              className="v3-sheet v3-xsel__sheet"
              role="dialog"
              aria-modal="true"
              aria-label={ariaLabel || placeholder}
              ref={sheetRef}
              tabIndex={-1}
              onKeyDown={navKeys}
            >
              <div className="v3-sheet__handle" />
              <div className="v3-xsel__sheet-head">
                <span className="v3-dialog__title">{ariaLabel || placeholder}</span>
                <IconButton label="关闭" size="sm" icon={<X size={18} />} onClick={() => closeList()} />
              </div>
              {searchNode}
              {optionsNode}
            </div>
          </div>,
          document.body,
        )
      ) : null}
    </span>
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
/** 分段控制器，带滑动指示条。 */
export function Segmented({ options = [], value, onChange, className = '', ariaLabel = '视图切换' }) {
  const wrapRef = useRef(null)
  const btnRefs = useRef(new Map())
  const [indicator, setIndicator] = useState({ left: 4, width: 0, ready: false })
  const normalized = useMemo(() => options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o)), [options])

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
export function Progress({ value = 0, gradient = false, indeterminate = false, className = '', height, ariaLabel = '进度' }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div
      className={cx('v3-progress', indeterminate && 'v3-progress--indeterminate', className)}
      role="progressbar"
      aria-label={ariaLabel}
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
  const dismiss = useCallback((id) => setItems((prev) => prev.filter((x) => x.id !== id)), [])
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

  const scrollToTop = useCallback(() => {
    if (containerRef?.current) focusAndScroll(containerRef.current, 96)
  }, [containerRef])

  const goto = useCallback((p) => {
    const next = Math.min(Math.max(1, p), pages)
    if (next === cur || disabled) return
    onChange?.(next)
    scrollToTop()
  }, [pages, cur, disabled, onChange, scrollToTop])

  const pickPageSize = useCallback((e) => {
    const n = Math.min(Math.max(1, Number(e.target.value) || size), PAGER_MAX_PAGE_SIZE)
    if (n === size) return
    onPageSizeChange?.(n)
    scrollToTop()
  }, [size, onPageSizeChange, scrollToTop])

  const numbers = useMemo(() => pageWindow(cur, pages), [cur, pages])
  const sizeChoices = useMemo(() => [...new Set([...pageSizeOptions, size])]
    .filter((n) => n >= 1 && n <= PAGER_MAX_PAGE_SIZE)
    .sort((a, b) => a - b), [pageSizeOptions, size])

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

/* -------------------------------------------------------------------------- */
/* Countdown · 倒计时（W5-2 重做）                                             */
/* -------------------------------------------------------------------------- */
/* 旧的「环形总计倒计时」两处问题：环表达的是「一年走了多少」，与「还剩几天」
   混在一个视觉单元里互相干扰；字号与配色在首页/计划页各写一套。这里改成信息
   分层清爽的卡片：主数字只剩「剩余天」，可选秒级到分钟的到钟读数（只在明确
   设置了初试日期时才走表），进度与里程碑降级为说明行，可整块嵌进首页 Hero、
   计划页 Tile 或任意窄容器（variant=inline 时收成一行）。                    */

const cdPad = (n) => String(Math.max(0, n)).padStart(2, '0')

/* 倒计时里的「去核对/去设置」要跟随各页的导航方式：页面传 react-router 的
   Link 就用 to（SPA 内跳转），不传则退化成普通 a[href]。 */
function CdLink({ as: As, href, className, children }) {
  if (!As) return <a className={className} href={href}>{children}</a>
  return <As className={className} to={href}>{children}</As>
}

export function Countdown({
  days = null,
  examDate = '',
  examYear = null,
  label,
  phaseLabel = '',
  isDefault = false,
  progress = null,
  progressNote = '',
  milestones = [],
  showClock = false,
  variant = 'card',
  link = '/settings',
  linkAs,
  className = '',
}) {
  const [now, setNow] = useState(() => Date.now())
  const target = useMemo(() => {
    if (!examDate) return null
    const t = new Date(`${examDate}T00:00:00`).getTime()
    return Number.isFinite(t) ? t : null
  }, [examDate])
  const needClock = showClock && target != null && days != null && variant !== 'inline'
  useEffect(() => {
    if (!needClock) return undefined
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [needClock])

  const diff = needClock ? Math.max(0, target - now) : 0
  const clock = needClock
    ? `${cdPad(Math.floor(diff / 3600000))}:${cdPad(Math.floor((diff % 3600000) / 60000))}:${cdPad(Math.floor((diff % 60000) / 1000))}`
    : ''
  const title = label || (examYear ? `距离 ${examYear} 考研` : '距离初试')
  const next = (milestones || []).slice(0, 2)

  return (
    <div className={cx('v3-cdown', `v3-cdown--${variant}`, className)}>
      <div className="v3-cdown__head">
        <span className="v3-cdown__label">{title}</span>
        {phaseLabel ? <span className="v3-badge v3-badge--primary">{phaseLabel}</span> : null}
      </div>

      {days == null ? (
        <div className="v3-cdown__unset">
          <span className="v3-cdown__unset-text">还没有初试日期</span>
          <CdLink as={linkAs} href={link} className="v3-cdown__link">去设置目标与日期</CdLink>
        </div>
      ) : (
        <div className="v3-cdown__figure">
          <span className="v3-cdown__num">{new Intl.NumberFormat('zh-CN').format(days)}</span>
          <span className="v3-cdown__unit">天</span>
          {days <= 0 ? <span className="v3-cdown__zero">今天开考</span> : null}
        </div>
      )}

      {needClock && clock ? (
        <div className="v3-cdown__clock">
          <span className="v3-cdown__clock-num">{clock}</span>
          <span className="v3-cdown__clock-note">距 {examDate} 开考（按当日 00:00 计）</span>
        </div>
      ) : null}

      {days != null ? (
        <div className="v3-cdown__meta">
          <span className="v3-cdown__date">{examDate || '未设置初试日期'}</span>
          {isDefault ? (
            <CdLink as={linkAs} href={link} className="v3-cdown__link">日期为系统估算 · 去核对</CdLink>
          ) : null}
        </div>
      ) : null}

      {progress != null ? (
        <div className="v3-cdown__prog">
          <Progress value={progress} />
          <span className="v3-cdown__prog-note">
            {progressNote || `备考时间轴已走过 ${Math.round(progress)}%`}
          </span>
        </div>
      ) : null}

      {next.length ? (
        <ul className="v3-cdown__miles">
          {next.map((m) => (
            <li key={`${m.title}-${m.date || ''}`}>
              <span className="v3-cdown__mile-title">{m.title}</span>
              <span className="v3-cdown__mile-when">
                {m.days == null ? (m.date || '待定') : `还剩 ${m.days} 天`}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* StudyHeatmap · 自适应学习热力（W5-3）                                       */
/* -------------------------------------------------------------------------- */
/* 旧实现是定死 12px 单元格的 SVG，两处问题：一是被 viewBox 缩放，首页与仪表盘
   同一个组件渲出两种大小；二是 <title> 提示在触屏上等于没有。改成按容器宽度
   自适应排布的 DOM 网格：格子尺寸随宽度算（窄屏自动缩到能放下整周），hover
   与 tap 都会把当天明细写在下方说明行（aria-live 同时播报），色阶用 tokens
   主色与表面色 color-mix 得到，暗色自动跟随。                                 */

const HEAT_WEEK_CN = ['一', '二', '三', '四', '五', '六', '日']

export function StudyHeatmap({
  days = [],
  weeks = 12,
  valueOf = (d) => d.focus,
  detailOf = null,
  unit = '分钟',
  color = 'var(--v3-primary)',
  className = '',
}) {
  const wrapRef = useRef(null)
  const [boxW, setBoxW] = useState(0)
  const [sel, setSel] = useState(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect
      if (cr) setBoxW(cr.width)
    })
    ro.observe(el)
    setBoxW(el.getBoundingClientRect().width)
    return () => ro.disconnect()
  }, [])

  const cells = useMemo(() => {
    const src = Array.isArray(days) ? days : []
    const sliced = weeks > 0 ? src.slice(-weeks * 7) : src
    return sliced.map((d) => ({ day: d, value: Math.max(0, Number(valueOf(d)) || 0) }))
  }, [days, weeks, valueOf])

  /* 首列对齐真实星期：把 1 月 1 日落在周三这种偏移补成空格 */
  const lead = useMemo(() => {
    if (!cells.length) return 0
    const first = cells[0].day?.date
    if (!first) return 0
    const dt = new Date(`${first}T00:00:00`)
    if (Number.isNaN(dt.getTime())) return 0
    return (dt.getDay() + 6) % 7
  }, [cells])

  const max = useMemo(() => Math.max(...cells.map((c) => c.value), 0), [cells])
  const cols = Math.max(1, Math.ceil((lead + cells.length) / 7))
  const gap = cols > 26 ? 2 : 3
  const labelW = 24
  const cell = Math.max(8, Math.min(30, Math.floor(((boxW || 320) - labelW - (cols - 1) * gap) / cols)))

  const levelOf = (v) => {
    if (!v || !max) return 0
    const r = v / max
    if (r >= 0.75) return 4
    if (r >= 0.5) return 3
    if (r >= 0.25) return 2
    return 1
  }

  const grid = useMemo(() => {
    const out = []
    for (let i = 0; i < lead; i += 1) out.push(null)
    cells.forEach((c) => out.push(c))
    while (out.length % 7) out.push(null)
    return out
  }, [cells, lead])

  const detail = useMemo(() => {
    if (!sel) return ''
    if (detailOf) return detailOf(sel.day)
    const d = sel.day || {}
    const bits = [d.date ? `${String(d.date).slice(5)} ·` : '', `专注 ${Math.round(sel.value)} ${unit}`]
    if (d.questions != null) bits.push(`答题 ${d.questions}`)
    if (d.words != null) bits.push(`单词 ${d.words}`)
    return bits.filter(Boolean).join(' · ')
  }, [sel, detailOf, unit])

  return (
    <div className={cx('v3-heat', className)} ref={wrapRef} style={{ '--v3-heat-color': color }}>
      <div className="v3-heat__body">
        <div className="v3-heat__days" aria-hidden="true" style={{ gap }}>
          {HEAT_WEEK_CN.map((w, i) => (
            <span key={w} style={{ height: cell, fontSize: cell >= 12 ? 10 : 9 }}>
              {i % 2 === 0 ? w : ''}
            </span>
          ))}
        </div>
        <div className="v3-heat__cols" style={{ gap }}>
          {Array.from({ length: cols }).map((_, c) => (
            <div className="v3-heat__col" key={c} style={{ gap }}>
              {Array.from({ length: 7 }).map((__, r) => {
                const item = grid[c * 7 + r]
                if (!item) return <span className="v3-heat__pad" key={r} style={{ width: cell, height: cell }} />
                const lv = levelOf(item.value)
                const d = item.day || {}
                return (
                  <button
                    key={r}
                    type="button"
                    className={cx('v3-heat__cell', `lv-${lv}`, sel?.day?.date === d.date && 'is-sel')}
                    style={{ width: cell, height: cell }}
                    aria-label={`${d.date || ''} 专注 ${Math.round(item.value)} ${unit}`}
                    title={`${d.date || ''} ${Math.round(item.value)} ${unit}`}
                    onMouseEnter={() => setSel(item)}
                    onFocus={() => setSel(item)}
                    onClick={() => setSel(item)}
                  />
                )
              })}
            </div>
          ))}
        </div>
      </div>

      <div className="v3-heat__foot">
        <span className="v3-heat__detail" role="status" aria-live="polite">
          {detail || '把鼠标移到或点一下格子，看当天学了什么'}
        </span>
        <span className="v3-heat__legend" aria-hidden="true">
          <span className="v3-caption">少</span>
          {[1, 2, 3, 4].map((lv) => (
            <i key={lv} className={`v3-heat__sw lv-${lv}`} style={{ '--v3-heat-color': color }} />
          ))}
          <span className="v3-caption">多</span>
        </span>
      </div>
    </div>
  )
}
