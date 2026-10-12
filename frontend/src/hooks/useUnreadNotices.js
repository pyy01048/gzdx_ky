/* 通知未读状态 —— 全局共享 Hook（单一数据源 + 跨组件广播）
 *
 * 用户诉求：「每一个通知都要有一个已读标记，这样防止我错过消息」。
 * 未读数需要出现在**任何页面**（侧边导航角标、首页公告栏、院校详情页），
 * 若每个组件各自请求，会出现「角标 5、列表 3」这类不一致，
 * 故这里用极简发布订阅：一份状态 + 一个自增版本号广播。
 *
 * 后端为单用户设计（kaoyan_notices 上直接加 is_read/is_starred 列），
 * 故无需按用户维度拉取，一次 /api/notices/unread-stats 即为全量。
 */
import { useCallback, useEffect, useState } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'

/** 全局状态（模块级，非 React state）：所有调用方共享同一份快照。 */
let snapshot = {
  total: 0,
  unread: 0,
  read: 0,
  starred: 0,
  important_unread: 0,
  important_total: 0,
  urgent_unread: 0,
  by_type: {},
  by_school: {},
}
let loading = false
/** 版本号：任何一次成功刷新都自增，订阅者据此重新渲染。 */
let version = 0
const listeners = new Set()

/** 立即把新快照广播给所有订阅者。 */
function publish() {
  listeners.forEach((fn) => fn())
}

/** 拉取未读统计。并发调用会复用同一个 in-flight Promise，避免重复请求。 */
let inflight = null
export async function refreshUnread() {
  if (inflight) return inflight
  loading = true
  inflight = kaoyanApi
    .noticeUnreadStats()
    .then((d) => {
      if (d && typeof d.unread === 'number') {
        snapshot = {
          total: d.total ?? 0,
          unread: d.unread ?? 0,
          read: d.read ?? 0,
          starred: d.starred ?? 0,
          important_unread: d.important_unread ?? 0,
          important_total: d.important_total ?? 0,
          urgent_unread: d.urgent_unread ?? 0,
          by_type: d.by_type || {},
          by_school: d.by_school || {},
        }
        version += 1
        publish()
      }
      return snapshot
    })
    .catch(() => snapshot)
    .finally(() => {
      loading = false
      inflight = null
    })
  return inflight
}

/**
 * 订阅未读状态。
 * @returns 当前快照 + refresh（标记后调用以同步角标）
 */
export function useUnreadNotices() {
  // 用版本号做 state：快照是模块级同一引用，只有版本号变化才能触发重渲染
  const [tick, setTick] = useState(version)

  useEffect(() => {
    const fn = () => setTick(version)
    listeners.add(fn)
    return () => {
      listeners.delete(fn)
    }
  }, [])

  // 首次订阅时拉取一次（若已有数据则复用，避免切页面重复请求）
  useEffect(() => {
    if (version === 0) refreshUnread()
  }, [])

  const refresh = useCallback(async () => {
    await refreshUnread()
  }, [])

  return { ...snapshot, loading, refresh, version: tick }
}

export default useUnreadNotices
