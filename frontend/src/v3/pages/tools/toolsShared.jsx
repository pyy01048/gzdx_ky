/**
 * 站内计算工具 · 共享 UI 组件
 * ToolShell：统一的工具外壳（卡片 + 关闭按钮）；Tex：KaTeX 行内/独立渲染；
 * Steps：可折叠步骤块（details/summary）；Row/NumInput：紧凑表单行。
 */
import { useMemo, useState } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { Card, CardHead, IconButton } from '../../ui'
import { X } from '../../icons'

/** 渲染 LaTeX → HTML；throwOnError 打开以如实展示解析错误（仅本文件内部使用） */
function renderTex(tex, { display = false, macros } = {}) {
  try {
    return {
      html: katex.renderToString(String(tex ?? ''), {
        displayMode: display,
        throwOnError: true,
        strict: false,
        trust: false,
        macros: macros || undefined,
      }),
      error: '',
    }
  } catch (err) {
    return { html: '', error: err?.message || 'LaTeX 解析失败' }
  }
}

/** 一段 LaTeX 的渲染结果（错误时降级为等宽原文 + 红色提示） */
export function Tex({ tex, display = false, className = '' }) {
  const r = useMemo(() => renderTex(tex, { display }), [tex, display])
  if (r.error) {
    return <code className={`v3-tex-error ${className}`} title={r.error}>{String(tex)}</code>
  }
  return (
    <span
      className={`v3-tex${display ? ' v3-tex--block' : ''} ${className}`}
      dangerouslySetInnerHTML={{ __html: r.html }}
    />
  )
}

/** 可折叠步骤块：默认收起，标题带数量提示 */
export function Steps({ title = '推导步骤', count, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`v3-tsteps${open ? ' is-open' : ''}`}>
      <button type="button" className="v3-tsteps__head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="v3-tsteps__caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
        <span>{title}</span>
        {count != null ? <span className="v3-tsteps__count">{count} 项</span> : null}
      </button>
      {open ? <div className="v3-tsteps__body">{children}</div> : null}
    </div>
  )
}

/** 工具外壳：卡片 + 标题 + 关闭按钮，内容溢出横向滚动兜底 */
export function ToolShell({ icon, title, sub, onClose, children, className = '' }) {
  return (
    <Card className={`v3-tool-shell ${className}`.trim()}>
      <CardHead
        icon={icon}
        title={title}
        sub={sub}
        actions={<IconButton label="关闭工具" icon={<X size={16} />} onClick={onClose} />}
      />
      <div className="v3-tool-shell__body">{children}</div>
    </Card>
  )
}

/** 标签 + 控件的紧凑表单行（移动优先，自动换行） */
export function FieldRow({ label, children, hint }) {
  return (
    <label className="v3-tfield">
      <span className="v3-tfield__label">{label}</span>
      <span className="v3-tfield__ctrl">{children}</span>
      {hint ? <span className="v3-tfield__hint">{hint}</span> : null}
    </label>
  )
}
