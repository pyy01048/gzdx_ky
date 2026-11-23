/**
 * LaTeX 工作台（浏览器本地 KaTeX 实时渲染，不联网）
 * - 三种模式：独立公式 / 行内公式 / 文本混排（$...$、$$...$$）
 * - 模板片段一键插入（align / cases / matrix / mhchem 化学方程式等）
 * - 导出：SVG / PNG（foreignObject + 内嵌 KaTeX 字体，全离线）、独立 HTML、复制 LaTeX / MathML / HTML
 * - 语法错误实时指出（KaTeX throwOnError），不静默吞错
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import 'katex/contrib/mhchem'
import katexCssText from 'katex/dist/katex.min.css?raw'
import { Button, Chip, IconButton, Segmented, toastErr, toastOk } from '../../ui'
import { Copy, Download, Type } from '../../icons'
import { ToolShell } from './toolsShared'
import '../../styles/tools-suite-v3.css'
import { copyText, downloadBlob, downloadText } from './toolUtils'

/* 预编译的 KaTeX woff2 字体表（dev 走 /node_modules/…，build 走 /assets/…） */
const FONT_URLS = import.meta.glob('/node_modules/katex/dist/fonts/*.woff2', {
  query: '?url',
  eager: true,
  import: 'default',
})

let embeddedCssPromise = null
async function getEmbeddedKatexCss() {
  if (!embeddedCssPromise) {
    embeddedCssPromise = (async () => {
      const map = new Map()
      await Promise.all(Object.entries(FONT_URLS).map(async ([path, url]) => {
        try {
          const resp = await fetch(url)
          if (!resp.ok) return
          const bytes = new Uint8Array(await resp.arrayBuffer())
          let binary = ''
          const CHUNK = 0x8000
          for (let i = 0; i < bytes.length; i += CHUNK) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK))
          }
          map.set(path.split('/').pop(), `data:font/woff2;base64,${btoa(binary)}`)
        } catch { /* 单字体失败则保留相对 url，导出可能缺字形但不至于中断 */ }
      }))
      return katexCssText.replace(/url\(fonts\/([^)"']+?\.woff2)\)/g, (m, name) => (map.has(name) ? `url("${map.get(name)}")` : m))
    })()
  }
  return embeddedCssPromise
}

const SNIPPETS = [
  {
    group: '多行推导',
    items: [
      { label: 'align 推导', tex: '\\begin{aligned}\n  f(x) &= x^2 + 2x \\\\\n       &= (x+1)^2 - 1\n\\end{aligned}' },
      { label: '分段函数 cases', tex: 'f(x)=\\begin{cases}\n  x^2, & x \\ge 0 \\\\\n  -x, & x < 0\n\\end{cases}' },
      { label: '方程组', tex: '\\begin{cases}\n  2x + y = 5 \\\\\n  x - 3y = -1\n\\end{cases}' },
      { label: '极限', tex: '\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1' },
      { label: '定积分', tex: '\\int_a^b f(x)\\,\\mathrm{d}x = F(b) - F(a)' },
      { label: '级数', tex: '\\sum_{n=1}^{\\infty} \\frac{1}{n^2} = \\frac{\\pi^2}{6}' },
      { label: '偏导', tex: '\\frac{\\partial^2 u}{\\partial x^2} + \\frac{\\partial^2 u}{\\partial y^2} = 0' },
    ],
  },
  {
    group: '矩阵',
    items: [
      { label: 'pmatrix', tex: '\\begin{pmatrix}\n  a & b \\\\\n  c & d\n\\end{pmatrix}' },
      { label: 'bmatrix', tex: '\\begin{bmatrix}\n  1 & 0 \\\\\n  0 & 1\n\\end{bmatrix}' },
      { label: 'vmatrix 行列式', tex: '\\begin{vmatrix}\n  a & b \\\\\n  c & d\n\\end{vmatrix} = ad - bc' },
    ],
  },
  {
    group: '化学（mhchem）',
    items: [
      { label: '反应方程式', tex: '\\ce{2H2 + O2 -> 2H2O}' },
      { label: '可逆反应', tex: '\\ce{N2 + 3H2 <=>[高温高压][催化剂] 2NH3}' },
      { label: '离子方程', tex: '\\ce{Fe^{3+} + 3OH- -> Fe(OH)3 v}' },
      { label: '化学式', tex: '\\ce{CuSO4.5H2O}' },
    ],
  },
  {
    group: '常用符号',
    items: [
      { label: '分数', tex: '\\frac{a}{b}' },
      { label: '根式', tex: '\\sqrt[3]{x}' },
      { label: '上下标', tex: 'x_i^2' },
      { label: '希腊字母', tex: '\\alpha\\ \\beta\\ \\gamma\\ \\theta\\ \\lambda\\ \\mu\\ \\sigma\\ \\omega' },
      { label: '区间', tex: '\\left( a, b \\right]' },
      { label: '矩阵乘', tex: 'AB = \\lambda B' },
    ],
  },
]

const TOKEN = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g

function renderMixed(src) {
  const out = []
  let last = 0
  let m
  TOKEN.lastIndex = 0
  while ((m = TOKEN.exec(src)) !== null) {
    if (m.index > last) out.push({ type: 'text', value: src.slice(last, m.index) })
    const raw = m[0]
    const display = raw.startsWith('$$')
    const tex = display ? raw.slice(2, -2) : raw.slice(1, -1)
    out.push({ type: 'math', tex, display })
    last = m.index + raw.length
  }
  if (last < src.length) out.push({ type: 'text', value: src.slice(last) })
  return out
}

export default function LatexStudio({ onClose }) {
  const [mode, setMode] = useState('display')
  const [src, setSrc] = useState('\\int_0^{\\infty} e^{-x^2}\\,\\mathrm{d}x = \\frac{\\sqrt{\\pi}}{2}')
  const [fontSize, setFontSize] = useState(20)
  const [exporting, setExporting] = useState(false)
  const taRef = useRef(null)
  const previewRef = useRef(null)

  const render = useMemo(() => {
    if (!src.trim()) return { html: '', error: '' }
    try {
      if (mode === 'mixed') {
        const parts = renderMixed(src)
        const html = parts.map((p) => {
          if (p.type === 'text') {
            return `<span style="white-space:pre-wrap">${p.value.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</span>`
          }
          return katex.renderToString(p.tex, { displayMode: p.display, throwOnError: true, strict: false })
        }).join('')
        return { html, error: '' }
      }
      return {
        html: katex.renderToString(src, { displayMode: mode === 'display', throwOnError: true, strict: false }),
        error: '',
      }
    } catch (err) {
      return { html: '', error: err?.message || 'KaTeX 解析失败' }
    }
  }, [src, mode])

  const insertSnippet = (tex) => {
    const ta = taRef.current
    if (!ta) { setSrc((s) => `${s}${tex}`); return }
    const start = ta.selectionStart ?? src.length
    const end = ta.selectionEnd ?? src.length
    const next = src.slice(0, start) + tex + src.slice(end)
    setSrc(next)
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(start + tex.length, start + tex.length)
    })
  }

  /* ---------- 导出 ---------- */
  const buildStandaloneSvg = async () => {
    const el = previewRef.current
    if (!el || !render.html) throw new Error('当前没有可导出的渲染结果（请先修正公式错误）')
    const rect = el.getBoundingClientRect()
    const css = await getEmbeddedKatexCss()
    const pad = 18
    const w = Math.ceil(rect.width) + pad * 2
    const h = Math.ceil(rect.height) + pad * 2
    const inner = el.innerHTML.replace(/<br\s*\/?>/g, '<br/>')
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`
      + `<foreignObject width="100%" height="100%">`
      + `<div xmlns="http://www.w3.org/1999/xhtml" style="display:inline-block;padding:${pad}px;background:#ffffff;color:#000000;font-size:${fontSize}px;font-family:KaTeX_Main,serif">`
      + `<style><![CDATA[${css}]]></style>${inner}</div></foreignObject></svg>`
    return { svg, w, h }
  }

  const exportSvg = async () => {
    setExporting(true)
    try {
      const { svg } = await buildStandaloneSvg()
      downloadText('formula.svg', svg, 'image/svg+xml;charset=utf-8')
      toastOk('SVG 已导出（内嵌 KaTeX 字体，可进 PPT/Inkscape）')
    } catch (err) {
      toastErr(err?.message || 'SVG 导出失败，可改用「复制 HTML」')
    } finally {
      setExporting(false)
    }
  }

  const exportPng = async () => {
    setExporting(true)
    try {
      const { svg, w, h } = await buildStandaloneSvg()
      const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }))
      try {
        const img = new Image()
        await new Promise((resolve, reject) => {
          img.onload = resolve
          img.onerror = () => reject(new Error('位图化失败（浏览器限制），请改用 SVG 导出'))
          img.src = url
        })
        const scale = 2
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(w * scale))
        canvas.height = Math.max(1, Math.round(h * scale))
        const ctx = canvas.getContext('2d')
        ctx.fillStyle = '#ffffff'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
        if (!blob) throw new Error('PNG 生成失败，请改用 SVG 导出')
        downloadBlob('formula.png', blob)
        toastOk('PNG 已导出（2× 缩放，白底）')
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch (err) {
      toastErr(err?.message || 'PNG 导出失败，可改用 SVG / 独立 HTML')
    } finally {
      setExporting(false)
    }
  }

  const exportHtml = () => {
    if (!render.html) { toastErr('请先修正公式错误'); return }
    const doc = `<!doctype html><html><head><meta charset="utf-8"><title>formula</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css"></head><body style="display:inline-block;padding:16px;font-size:${fontSize}px">${render.html}</body></html>`
    downloadText('formula.html', doc, 'text/html;charset=utf-8')
    toastOk('独立 HTML 已下载（公式可选中、可检索）')
  }

  const copyMathml = async () => {
    const el = previewRef.current
    const math = el?.querySelector('math')
    if (!math) { toastErr('当前渲染结果没有 MathML（请先修正错误）'); return }
    if (await copyText(math.outerHTML)) toastOk('MathML 已复制（可粘贴进 Word/LibreOffice 公式）')
  }

  useEffect(() => {
    /* 预热字体内嵌，首次导出更快 */
    const id = window.setTimeout(() => { getEmbeddedKatexCss().catch(() => {}) }, 1500)
    return () => window.clearTimeout(id)
  }, [])

  return (
    <ToolShell
      icon={<Type size={16} />}
      title="LaTeX 工作台"
      sub="本地 KaTeX 实时预览 · align/cases/matrix/mhchem · SVG/PNG/HTML 导出全离线"
      onClose={onClose}
      className="v3-tool-latex"
    >
      <Segmented
        options={[
          { value: 'display', label: '独立公式' },
          { value: 'inline', label: '行内公式' },
          { value: 'mixed', label: '文本混排 $…$' },
        ]}
        value={mode}
        onChange={setMode}
        ariaLabel="排版模式"
      />
      <div className="v3-tl-grid">
        <div className="v3-tl-edit">
          <textarea
            ref={taRef}
            className="v3-tl-ta"
            rows={8}
            value={src}
            spellCheck={false}
            aria-label="LaTeX 源码输入"
            onChange={(e) => setSrc(e.target.value)}
          />
          <div className="v3-tl-size">
            <span className="v3-label">预览字号</span>
            <input
              type="range"
              min={14}
              max={48}
              step={1}
              value={fontSize}
              aria-label="预览字号"
              onChange={(e) => setFontSize(Number(e.target.value))}
            />
            <code>{fontSize}px</code>
          </div>
          <div className="v3-tl-snippets">
            {SNIPPETS.map((g) => (
              <div key={g.group} className="v3-tl-snipgroup">
                <span className="v3-label">{g.group}</span>
                <div className="v3-tl-snipitems">
                  {g.items.map((it) => (
                    <Chip key={it.label} as="button" type="button" title={it.tex} onClick={() => insertSnippet(it.tex)}>
                      {it.label}
                    </Chip>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="v3-tl-preview">
          <div className="v3-tl-preview__head">
            <span className="v3-label">实时预览</span>
            <span className="v3-tl-preview__acts">
              <Button size="sm" variant="tonal" icon={<Copy size={14} />} onClick={async () => { if (await copyText(src)) toastOk('LaTeX 源码已复制') }}>源码</Button>
              <IconButton size="sm" label="复制 MathML" icon={<Copy size={14} />} onClick={copyMathml} />
              <IconButton size="sm" label="复制 HTML 片段" icon={<Copy size={14} />} onClick={async () => { if (render.html && await copyText(render.html)) toastOk('HTML 已复制（配合 KaTeX 样式表可用）'); else if (!render.html) toastErr('请先修正公式错误') }} />
            </span>
          </div>
          <div className="v3-tl-preview__body">
            {render.error ? (
              <div className="v3-tools-error">
                <strong>LaTeX 错误：</strong>{render.error}
                <div className="v3-tl-preview__hint">错误之后的内容未渲染；修正高亮位置附近的写法即可。</div>
              </div>
            ) : null}
            <div
              ref={previewRef}
              className="v3-tl-render"
              style={{ fontSize: `${fontSize}px` }}
              dangerouslySetInnerHTML={{ __html: render.html }}
            />
          </div>
          <div className="v3-tl-export">
            <Button size="sm" variant="tonal" icon={<Download size={14} />} disabled={exporting || !!render.error} onClick={exportSvg}>导出 SVG</Button>
            <Button size="sm" variant="tonal" icon={<Download size={14} />} disabled={exporting || !!render.error} onClick={exportPng}>导出 PNG</Button>
            <Button size="sm" variant="outline" icon={<Download size={14} />} disabled={!!render.error} onClick={exportHtml}>独立 HTML</Button>
            {exporting ? <span className="v3-tl-export__busy">正在内嵌字体并导出…</span> : null}
          </div>
          <p className="v3-tl-note">
            SVG/PNG 通过把 KaTeX 字体内嵌进图形文件实现，完全在本机生成；导出首次会加载字体，稍慢属正常。
            化学式使用 mhchem 宏包语法（<code>\ce{'{...}'}</code>）。
          </p>
        </div>
      </div>
    </ToolShell>
  )
}
