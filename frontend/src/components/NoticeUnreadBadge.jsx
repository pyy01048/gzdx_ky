/* 未读角标 —— 全局可见的「我还有 N 条通知没读」
 *
 * 用户最怕错过院校研究生院的重要通知，因此未读数必须**在任何页面都可见**，
 * 而不只是通知列表页。本组件挂在 Layout 侧边栏「院校数据中心」模块标题上，
 * 数据源 useUnreadNotices（单一快照，跨组件一致）。
 *
 * 角标分级（用户快速判断紧迫度）：
 *   0        → 不渲染（避免"0"的视觉噪音）
 *   1-99     → 常规红点
 *   100-999  → 显示具体数字，便于感知规模
 *   ≥1000    → 显示「999+」，防止撑破导航栏
 */
import React from 'react'
import { useUnreadNotices } from '../hooks/useUnreadNotices'

/** 把未读数格式化为角标文案（空/0 返回空串表示不显示）。 */
function badgeText(n) {
  if (!n || n <= 0) return ''
  if (n >= 1000) return '999+'
  return String(n)
}

export default function NoticeUnreadBadge({ className = '' }) {
  const { unread } = useUnreadNotices()
  const text = badgeText(unread)
  if (!text) return null
  return (
    <span
      className={`notice-unread-badge ${className}`.trim()}
      title={`有 ${unread} 条院校通知未读，点击进入院校数据中心查看`}
      aria-label={`${unread} 条未读通知`}
    >
      {text}
    </span>
  )
}
