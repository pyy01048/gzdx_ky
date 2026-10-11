/**
 * 键盘快捷键 Hook V3.0
 *
 * 使用方式：
 * useHotkeys('ctrl+k', () => openCommandPalette())
 * useHotkeys('n', () => addTask(), { enableOnFormTags: true })
 * useHotkeys(['1','2','3','4'], (e) => grade(e.key))
 */
import { useEffect, useCallback, useRef } from 'react'

/**
 * 解析快捷键字符串
 * 支持：ctrl+k, cmd+k, shift+a, alt+b, 单个字母/数字
 */
function parseHotkey(hotkey) {
  const parts = hotkey.toLowerCase().split('+')
  const modifiers = {
    ctrl: parts.includes('ctrl') || parts.includes('control'),
    meta: parts.includes('cmd') || parts.includes('command') || parts.includes('meta'),
    shift: parts.includes('shift'),
    alt: parts.includes('alt') || parts.includes('option'),
  }
  const key = parts.find((p) => !['ctrl', 'control', 'cmd', 'command', 'meta', 'shift', 'alt', 'option'].includes(p))
  return { modifiers, key }
}

/**
 * 匹配快捷键
 */
function matchHotkey(event, hotkey) {
  const { modifiers, key } = parseHotkey(hotkey)
  const eventKey = event.key.toLowerCase()

  // 检查修饰键
  if (modifiers.ctrl !== event.ctrlKey) return false
  if (modifiers.meta !== event.metaKey) return false
  if (modifiers.shift !== event.shiftKey) return false
  if (modifiers.alt !== event.altKey) return false

  // 检查主键
  if (key === 'space') return eventKey === ' ' || event.code === 'Space'
  if (key === 'esc') return eventKey === 'escape'
  if (key === 'enter') return eventKey === 'enter'
  if (key === 'backspace') return eventKey === 'backspace'
  if (key === 'tab') return eventKey === 'tab'
  if (key.length === 1) return eventKey === key

  return eventKey === key
}

/**
 * 键盘快捷键 Hook
 * @param {string|string[]} hotkeys - 快捷键或快捷键数组
 * @param {Function} callback - 触发回调
 * @param {Object} options - 配置选项
 */
export function useHotkeys(hotkeys, callback, options = {}) {
  const {
    enableOnFormTags = false, // 是否在表单元素中启用
    preventDefault = true, // 是否阻止默认行为
    enabled = true, // 是否启用
  } = options

  const callbackRef = useRef(callback)
  callbackRef.current = callback

  const handler = useCallback(
    (event) => {
      if (!enabled) return

      // 检查是否在表单元素中
      const target = event.target
      const isFormTag = ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable
      if (isFormTag && !enableOnFormTags) return

      const hotkeyList = Array.isArray(hotkeys) ? hotkeys : [hotkeys]
      for (const hotkey of hotkeyList) {
        if (matchHotkey(event, hotkey)) {
          if (preventDefault) event.preventDefault()
          callbackRef.current(event, hotkey)
          return
        }
      }
    },
    [hotkeys, enableOnFormTags, preventDefault, enabled]
  )

  useEffect(() => {
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handler])
}

/**
 * 全局快捷键列表（用于显示帮助）
 */
export const GLOBAL_HOTKEYS = [
  { keys: ['ctrl+k', 'cmd+k'], description: '打开命令面板', category: '全局' },
  { keys: ['ctrl+/', 'cmd+/'], description: '显示快捷键帮助', category: '全局' },
  { keys: ['esc'], description: '关闭弹窗/抽屉', category: '全局' },
  { keys: ['n'], description: '新建（任务/错题/卡片）', category: '列表页' },
  { keys: ['/'], description: '聚焦搜索框', category: '列表页' },
  { keys: ['1', '2', '3', '4'], description: '复习评分（又忘/忘记/想起/简单）', category: '复习页' },
]

export default useHotkeys
