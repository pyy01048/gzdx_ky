import React, { useMemo } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

/* ============================================================
   题干/选项/解析的统一公式渲染

   支持四种写法：
   1. $...$、$$...$$、\(...\)、\[...\]  → KaTeX 渲染（LaTeX 路线，公式可被检索/LLM 读懂）
   2. ![alt](url)                        → 行内公式图（图片回填路线，只对人眼可见）
   3. [[F:12]]                           → 尚未回填的公式占位符，渲染成醒目标记
   4. 其余                                → 原样文本

   为什么要有第 2、3 条
   --------------------
   Word 题库里的公式是以图片形式嵌在段落里的（见后端 services/docx_formula.py）。
   在 LaTeX 识别完成前，回填出来的是 `![公式](/media/images/...)`，
   必须能显示，题干才不会长成「设函数具有二阶导数，，则在上（　）」这种残句。
   `[[F:n]]` 是尚未回填的占位符——显示成一个小标记而不是吞掉，
   让「这里本该有公式」这件事对人可见，不静默丢失。

   渲染失败一律退回原文，绝不把整题变成空白。
   全站只在这里引 KaTeX，避免每页各造一套。
   ============================================================ */

// 数学公式 | 行内图片 | 未回填占位符
const TOKEN = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|!\[[^\]\n]*\]\([^)\s]+\)|\[\[F:\d+\]\])/g

const IMAGE_RE = /^!\[([^\]\n]*)\]\(([^)\s]+)\)$/
const PLACEHOLDER_RE = /^\[\[F:(\d+)\]\]$/

function stripDelimiter(raw) {
  if (raw.startsWith('$$')) return { tex: raw.slice(2, -2), display: true }
  if (raw.startsWith('\\[')) return { tex: raw.slice(2, -2), display: true }
  if (raw.startsWith('\\(')) return { tex: raw.slice(2, -2), display: false }
  return { tex: raw.slice(1, -1), display: false }
}

/** 公式图地址归一。
 *  后端存的通常是 `/media/images/<相对路径>`，可直接用；
 *  历史数据里也有 `data/storage/images/xxx` 或纯文件名，兜底补前缀。 */
function normalizeImageSrc(src) {
  const s = String(src || '').trim()
  if (!s) return ''
  if (/^(https?:)?\/\//.test(s) || s.startsWith('/') || s.startsWith('data:')) return s
  if (s.startsWith('data/storage/images/')) {
    return '/media/images/' + s.slice('data/storage/images/'.length)
  }
  return '/media/images/' + s.replace(/^\.?\//, '')
}

export default function MathText({ text, className = '' }) {
  const parts = useMemo(() => {
    const src = String(text ?? '')
    if (!src) return []
    const out = []
    let last = 0
    let m
    TOKEN.lastIndex = 0
    while ((m = TOKEN.exec(src)) !== null) {
      if (m.index > last) out.push({ type: 'text', value: src.slice(last, m.index) })
      const raw = m[0]

      // 1) 行内公式图
      const im = IMAGE_RE.exec(raw)
      if (im) {
        out.push({ type: 'image', src: normalizeImageSrc(im[2]), alt: im[1] || '公式' })
        last = m.index + raw.length
        continue
      }

      // 2) 尚未回填的占位符
      const ph = PLACEHOLDER_RE.exec(raw)
      if (ph) {
        out.push({ type: 'placeholder', index: ph[1] })
        last = m.index + raw.length
        continue
      }

      // 3) LaTeX
      const { tex, display } = stripDelimiter(raw)
      let html = ''
      try {
        html = katex.renderToString(tex, {
          displayMode: display,
          throwOnError: false,
          strict: false,
          trust: false,
        })
      } catch {
        html = ''
      }
      out.push(html ? { type: 'math', value: html, display } : { type: 'text', value: raw })
      last = m.index + raw.length
    }
    if (last < src.length) out.push({ type: 'text', value: src.slice(last) })
    return out
  }, [text])

  if (!parts.length) return <span className={className}>{text}</span>
  return (
    <span className={className}>
      {parts.map((p, i) => {
        if (p.type === 'math') {
          return (
            <span
              key={i}
              className={p.display ? 'math-block' : 'math-inline'}
              dangerouslySetInnerHTML={{ __html: p.value }}
            />
          )
        }
        if (p.type === 'image') {
          return (
            <img
              key={i}
              src={p.src}
              alt={p.alt}
              className="math-formula-img"
              loading="lazy"
              /* 公式图原始高度多在 17–47px，放大到可读但不破坏行高 */
              style={{ height: '1.55em', width: 'auto', verticalAlign: '-0.35em', margin: '0 1px' }}
              onError={(e) => {
                // 图挂了就露出「[公式]」，别留一个破图图标
                const el = e.currentTarget
                el.style.display = 'none'
                const span = document.createElement('span')
                span.className = 'math-formula-missing'
                span.title = p.src
                span.textContent = '[公式]'
                if (el.parentNode) el.parentNode.insertBefore(span, el.nextSibling)
              }}
            />
          )
        }
        if (p.type === 'placeholder') {
          return (
            <span
              key={i}
              className="math-formula-placeholder"
              title={`公式占位符 #${p.index}（尚未回填）`}
              style={{
                display: 'inline-block',
                minWidth: '1.2em',
                padding: '0 3px',
                margin: '0 1px',
                border: '1px dashed currentColor',
                borderRadius: 3,
                opacity: 0.55,
                fontSize: '0.85em',
                lineHeight: 1.2,
                textAlign: 'center',
              }}
            >
              ƒ
            </span>
          )
        }
        return <React.Fragment key={i}>{p.value}</React.Fragment>
      })}
    </span>
  )
}
