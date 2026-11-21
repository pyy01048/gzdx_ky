/* 通知未读状态 —— 全局共享 Hook（单一数据源 + 跨组件广播）
 *
 * 用户诉求：「每一个通知都要有一个已读标记，这样防止我错过消息」。
 * 未读数需要出现在**任何页面**（侧边导航角标、首页公告栏、院校详情页），
 * 若每个组件各自请求，会出现「角标 5、列表 3」这类不一致，
 * 故这里用极简发布订阅：一份状态 + 一个自增版本号广播。
 *
 * 后端按登录会话返回该账号的未读统计（/api/notices/unread-stats），
 * 一次请求即为该账号全量；换账号必须重置快照（见下方 uid-changed 监听），
 * 否则「version===0 才拉取」的短路会让新账号一直显示旧账号的角标。
 */
import { useCallback, useEffect, useState } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import { currentUid } from '../utils/userKeys'

/** 全局状态（模块级，非 React state）：所有调用方共享同一份快照。 */
const emptySnapshot = () => ({
  total: 0,
  unread: 0,
  read: 0,
  starred: 0,
  important_unread: 0,
  important_total: 0,
  urgent_unread: 0,
  by_type: {},
  by_school: {},
})
let snapshot = emptySnapshot()
let loading = false
/** 版本号：任何一次成功刷新都自增，订阅者据此重新渲染。 */
let version = 0
const listeners = new Set()

/** 立即把新快照广播给所有订阅者。 */
function publish() {
  listeners.forEach((fn) => fn())
}

/** 拉取未读统计。并发调用会复用同一个 in-flight Promise，避免重复请求。
 *  P0（跨账号串号）：发起时记录 uid，切号后回来的响应丢弃。 */
let inflight = null
export async function refreshUnread() {
  if (inflight) return inflight
  loading = true
  const uidAtStart = currentUid()
  const p = kaoyanApi
    .noticeUnreadStats()
    .then((d) => {
      if (currentUid() !== uidAtStart) return snapshot
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
      if (inflight === p) inflight = null
    })
  inflight = p
  return p
}

/* B4（用户数据隔离，范本 useUiLayout）：切号/登出时重置快照与版本号。
   version 归零让「version===0 才拉取」的首拉条件对新账号重新成立；
   仍挂载的订阅者在收到广播后替新账号重拉（见 hook 内 fn）。 */
function resetOnUidChanged() {
  snapshot = emptySnapshot()
  loading = false
  inflight = null
  version = 0
  publish()
}
if (typeof window !== 'undefined') {
  window.addEventListener('userkeys:uid-changed', resetOnUidChanged)
}

/**
 * 订阅未读状态。
 * @param {{ enabled?: boolean }} options enabled=false 时不发起请求（访客没有个人未读）
 * @returns 当前快照 + refresh（标记后调用以同步角标）
 */
export function useUnreadNotices({ enabled = true } = {}) {
  // 用版本号做 state：快照是模块级同一引用，只有版本号变化才能触发重渲染
  const [tick, setTick] = useState(version)

  useEffect(() => {
    const fn = () => {
      setTick(version)
      /* 切号重置（version 归零）后，登录态下立即替新账号重拉角标；
         登出（uid=null）不拉，访客没有个人未读。 */
      if (enabled && version === 0 && currentUid() != null) refreshUnread()
    }
    listeners.add(fn)
    return () => {
      listeners.delete(fn)
    }
  }, [enabled])

  // 首次订阅时拉取一次（若已有数据则复用，避免切页面重复请求）
  useEffect(() => {
    if (enabled && version === 0) refreshUnread()
  }, [enabled])

  const refresh = useCallback(async () => {
    await refreshUnread()
  }, [])

  return { ...snapshot, loading, refresh, version: tick }
}

export default useUnreadNotices
