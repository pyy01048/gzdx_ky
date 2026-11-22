/* ============================================================
   useProfilePrefs —— 个人资料与服务端偏好的唯一读取入口（W6）
   ------------------------------------------------------------
   为什么单独成 hook：偏好（减少动效 / 字号密度 / 紧凑布局）要挂在
   <html data-*> 上才能全局生效，Settings 页根部挂一次即可；
   设置页的「个人资料」分区与将来的中枢组件都复用同一份数据，
   避免两个组件各自 fetch /api/profile 出现两份不同步的偏好。

   诚实约定：这里只管**真被 CSS/组件消费**的键（见 gamification-v3.css
   与 v3-pref-row 清单）。加一个没人读的开关 = 造一个死控件，不要加。
   ============================================================ */

import { useCallback, useEffect, useRef, useState } from 'react'
import { profileApi } from '../api/gamification'

export function applyProfilePrefs(prefs) {
  if (typeof document === 'undefined' || !prefs) return
  const root = document.documentElement
  root.dataset.reduceMotion = prefs.reduce_motion ? '1' : '0'
  root.dataset.fontScale = prefs.font_scale || 'md'
  root.dataset.compact = prefs.compact_mode ? '1' : '0'
}

export function useProfile() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const alive = useRef(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const d = await profileApi.get()
      if (alive.current) {
        setData(d)
        setError('')
      }
      return d
    } catch (e) {
      if (alive.current) setError(e?.message || '个人资料加载失败')
      return null
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    alive.current = true
    reload()
    return () => {
      alive.current = false
    }
  }, [reload])

  // 偏好落到全局：<html data-reduce-motion / data-font-scale / data-compact>
  useEffect(() => {
    applyProfilePrefs(data?.profile?.prefs)
  }, [data])

  return {
    data,
    loading,
    error,
    reload,
    setData,
  }
}

export default useProfile
