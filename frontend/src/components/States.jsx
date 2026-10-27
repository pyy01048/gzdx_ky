import React from 'react'

/** 统一加载态：行内文案 + 骨架行数可调 */
export function LoadingState({ text = '加载中…', rows = 3 }) {
  return (
    <div className="empty-state">
      <div className="loading-inline">{text}</div>
      {rows > 0 && (
        <div style={{ width: '100%', maxWidth: 420, display: 'grid', gap: 'var(--space-3)' }}>
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="skeleton sk-line" style={{ width: `${90 - i * 15}%` }} />
          ))}
        </div>
      )}
    </div>
  )
}
