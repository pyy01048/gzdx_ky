import { useMemo } from 'react'
import { useResolvedTheme } from './UI'

/**
 * 主题令牌解析（供 Canvas 渲染的场景使用）
 * ---------------------------------------------------------------------------
 * ECharts 走 Canvas 2D 上下文，`fillStyle = 'var(--accent)'` 是**非法值**
 * （Canvas 不解析 CSS 自定义属性），会静默渲染成黑色/透明。
 * 因此图表配色必须先从 CSSOM 读出真实色值再喂给 ECharts。
 *
 * 本 hook 读取 `document.documentElement` 上已计算的设计令牌，
 * 并随 resolvedTheme 变化重新解析，从而让**图表也能跟随明暗主题**。
 */

/** 需要在 Canvas 场景取用的令牌清单 */
const TOKEN_NAMES = [
  'bg',
  'surface',
  'surface-2',
  'surface-3',
  'ink',
  'ink-2',
  'ink-3',
  'line',
  'line-strong',
  'accent',
  'accent-soft',
  'accent-strong',
  'red',
  'red-soft',
  'green',
  'green-soft',
  'gold',
  'gold-soft',
  'violet',
  'violet-soft',
]

/**
 * 读取当前主题下所有设计令牌的真实色值。
 *
 * @param {string} [theme] 主题偏好（'light' | 'dark' | 'system'）；不传则跟随 store 订阅
 * @returns {Record<string, string>} 令牌名 → 真实色值（如 `{ accent: '#2f4b6e' }`）
 */
export function useThemeTokens(theme) {
  // 订阅主题变化：resolvedTheme 变化即触发下方 useMemo 重算
  const resolvedTheme = useResolvedTheme(theme)

  return useMemo(() => {
    const tokens = {}
    if (typeof window === 'undefined' || typeof document === 'undefined') return tokens
    const styles = getComputedStyle(document.documentElement)
    TOKEN_NAMES.forEach((name) => {
      tokens[name] = styles.getPropertyValue(`--${name}`).trim()
    })
    return tokens
  }, [resolvedTheme])
}

export default useThemeTokens
