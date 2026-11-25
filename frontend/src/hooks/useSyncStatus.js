import { useEffect, useState } from 'react'
import { getFailedCount, retrySyncQueue, subscribeSyncStatus } from '../store/useStore'

/**
 * 全局同步失败状态（P0-F03）。
 *
 * 失败写队列曾经只在 useStore 模块级内存里，且 sync-error 事件只有任务页监听，
 * 弱网/5xx 后用户看不到任何提示，刷新即静默丢失。这个瘦 hook 把两路信号
 * （subscribeSyncStatus 状态变更 + sync-error 事件）合并成「待同步条数」，
 * 供应用壳层的轻量提示条消费。
 *
 * @returns {{failedCount: number, retry: () => void}}
 */
export function useSyncStatus() {
  const [failedCount, setFailedCount] = useState(() => getFailedCount())

  useEffect(() => {
    const refresh = () => setFailedCount(getFailedCount())
    // notifySyncStatus('error') 先于入队触发，sync-error 在入队后触发 —— 两路
    // 都刷新一次，以最后一次读到的队列长度为准。
    const unsubscribe = subscribeSyncStatus(refresh)
    window.addEventListener('sync-error', refresh)
    refresh()
    return () => {
      unsubscribe()
      window.removeEventListener('sync-error', refresh)
    }
  }, [])

  return { failedCount, retry: retrySyncQueue }
}

export default useSyncStatus
