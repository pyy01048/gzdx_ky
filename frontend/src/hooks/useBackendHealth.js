import { useEffect, useState } from 'react'
import { getBackendState, subscribeBackendState, isBackendOnline } from '../api/client'

/**
 * C5：后端健康状态的唯一消费出口。
 *
 * 所有页面都通过本 hook 读取三态与派生的 backendOnline，禁止各自直接订阅
 * getBackendState / subscribeBackendState —— 那样同一时刻会出现两套解释
 * （例如一个 500 接口被某页说成「离线」，另一页仍说「在线」）。
 *
 * 三态口径（来自 api/client.js）：
 *   online   —— health 可达且窗口内无失败接口
 *   degraded —— health 可达但窗口内有失败接口（仍算后端在线）
 *   offline  —— health 本身不可达
 */
export function useBackendHealth() {
  const [backend, setBackend] = useState(() => {
    try {
      const s = getBackendState()
      if (s && s.state) return s
    } catch { /* 读不到状态按未知处理 */ }
    return { state: 'unknown', failures: [], checkedAt: 0 }
  })

  useEffect(() => {
    let alive = true
    let unsub = () => {}
    const onStatus = (s) => {
      if (!alive || !s || !s.state) return
      setBackend(s)
    }
    try {
      const ret = subscribeBackendState(onStatus)
      if (typeof ret === 'function') unsub = ret
    } catch { /* 忽略订阅异常 */ }
    return () => { alive = false; unsub() }
  }, [])

  const state = String(backend?.state || 'unknown')
  /* 测试桩可能未实现该导出，非函数时按 unknown 处理，不让页面崩掉 */
  const derivedOnline = typeof isBackendOnline === 'function' ? isBackendOnline(backend) : null
  return {
    state,
    failures: Array.isArray(backend?.failures) ? backend.failures : [],
    checkedAt: backend?.checkedAt || 0,
    online: typeof derivedOnline === 'boolean' ? derivedOnline : null,
    isOnline: state === 'online',
    isDegraded: state === 'degraded',
    isOffline: state === 'offline',
  }
}

export default useBackendHealth
