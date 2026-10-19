/* 选项归一化：题库里 options 可能是字符串，也可能是 {key,text} 对象。
 * 统一取可读文本，避免前端把对象渲染成 "[object Object]"。
 */
export function optionText(opt) {
  if (opt == null) return ''
  if (typeof opt === 'string') return opt
  if (typeof opt === 'number' || typeof opt === 'boolean') return String(opt)
  if (typeof opt === 'object') {
    const textKeys = ['text', 'label', 'value', 'content', 'option']
    if (textKeys.some((k) => k in opt)) {
      const text = opt.text ?? opt.label ?? opt.value ?? opt.content ?? opt.option
      return text == null ? '' : String(text)
    }
    const key = opt.key ?? opt.letter ?? opt.id
    return key == null ? '' : String(key)
  }
  return String(opt)
}

export function imageList(raw) {
  let list = raw
  if (typeof list === 'string') {
    try {
      const parsed = JSON.parse(list)
      list = Array.isArray(parsed) ? parsed : [list]
    } catch {
      list = [list]
    }
  }
  if (!Array.isArray(list)) return []
  return list
    .map((item) => {
      if (typeof item === 'string') return item.trim() ? { url: item.trim() } : null
      if (item && typeof item === 'object') {
        const url = item.url || item.path || item.src || item.image || item.image_url
        return url ? { ...item, url: String(url) } : null
      }
      return null
    })
    .filter(Boolean)
}

export function normalizeOptions(raw) {
  let list = raw
  if (typeof list === 'string') {
    try {
      const parsed = JSON.parse(list)
      list = Array.isArray(parsed) ? parsed : [list]
    } catch {
      list = list.split(/\r?\n/)
    }
  }
  if (!Array.isArray(list)) return []
  return list.map(optionText).map((s) => s.trim()).filter(Boolean)
}
