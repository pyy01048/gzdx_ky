import React from 'react'
import { AlertCircle, RefreshCw } from './Icon'
import { Empty } from './UI'

/**
 * 统一三态组件：loading / error / empty。
 *
 * 与 hooks/useApiData 配套使用，把「接口挂了怎么办」收敛成同一套 UI：
 *   <ErrorState message={error} onRetry={reload} />
 * 空态直接复用 UI.jsx 的 Empty（.empty-state 样式体系），保证全站视觉一致。
 */

/** 统一加载态：行内文案 + 骨架行数可调 */
export function LoadingState({ text = '加载中…', rows = 3 }) {
  return (
    <div className="empty-state">
      <div className="loading-inline">{text}</div>
      {rows > 0 && (
        <div style={{ width: '100%', maxWidth: 420, display: 'grid', gap: 10 }}>
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="skeleton sk-line" style={{ width: `${90 - i * 15}%` }} />
          ))}
        </div>
      )}
    </div>
  )
}

/** 统一错误态：就地提示 + 重试按钮（白屏克星：接口 500 时用户有路可走） */
export function ErrorState({ message, onRetry, retryText = '重试', title = '加载失败' }) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon"><AlertCircle size={40} /></div>
      <div className="empty-state-title">{title}</div>
      <div className="empty-state-desc">{message || '请确认后端服务已启动后重试。'}</div>
      {onRetry && (
        <div className="empty-state-action">
          <button className="btn primary" onClick={onRetry}>
            <RefreshCw size={14} /> {retryText}
          </button>
        </div>
      )}
    </div>
  )
}

/** 统一空态：转发到 UI.jsx 的 Empty（icon/title/desc/action 全兼容） */
export function EmptyState(props) {
  return <Empty {...props} />
}
