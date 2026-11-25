import { useState } from 'react'
import { cx, Ic } from './lib'
import { ChevronDown } from '../v3/icons'

/**
 * 可复用收起展开组件。
 * - label: 标题（ReactNode）
 * - meta: 标题右侧附加信息（题数 / 难度等）
 * - leading: 标题前导图标
 * - defaultOpen / open + onOpenChange（受控）
 * 高度动画走 CSS grid-template-rows 0fr→1fr，克制动效。
 */
export default function Disclosure({
  label, meta, leading, children, defaultOpen = false, open: openProp, onOpenChange,
  className = '', triggerClassName = '', bodyClassName = '', id,
}) {
  const [innerOpen, setInnerOpen] = useState(defaultOpen)
  const controlled = openProp !== undefined
  const isOpen = controlled ? openProp : innerOpen

  const toggle = () => {
    const next = !isOpen
    if (!controlled) setInnerOpen(next)
    onOpenChange?.(next)
  }

  return (
    <section className={cx('im-disclosure', isOpen && 'is-open', className)} id={id}>
      <button
        type="button"
        className={cx('im-disclosure__trigger', triggerClassName)}
        onClick={toggle}
        aria-expanded={isOpen}
      >
        {leading ? <span className="im-disclosure__leading">{leading}</span> : null}
        <span className="im-disclosure__label">{label}</span>
        {meta ? <span className="im-disclosure__meta">{meta}</span> : null}
        <Ic of={ChevronDown} className="im-disclosure__chevron" />
      </button>
      <div className="im-disclosure__content">
        <div className="im-disclosure__inner">
          {isOpen ? <div className={cx('im-disclosure__body', bodyClassName)}>{children}</div> : null}
        </div>
      </div>
    </section>
  )
}
