/**
 * 框图编辑器（浏览器本地 Mermaid 渲染，不联网、无假数据）
 * - 源码 ↔ 预览双栏（移动端上下分栏），实时渲染 + 语法错误如实显示
 * - 内置考研复试常用模板：控制系统框图（含反馈回路）、信号流、流水线、时序图、状态机、结构图
 * - 导出 SVG / PNG（本地光栅化，2× 缩放）
 * - mermaid 走按需动态 import，只有打开本工具才加载
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Chip, IconButton, toastErr, toastOk } from '../../ui'
import { Download, Layers, Maximize2, Minimize2, RotateCcw } from '../../icons'
import { ToolShell } from './toolsShared'
import '../../styles/tools-suite-v3.css'
import { downloadBlob } from './toolUtils'

const TEMPLATES = [
  {
    label: '控制框图（反馈）',
    src: `flowchart LR
  r((+)) --> G1["G1(s)"] --> G2["G2(s)"] --> c
  G2 --> H["H(s)"]
  H -->|负反馈| r
  r -->|"r(t)"| G1
  c["c(t) 输出"]`,
  },
  {
    label: '开环传递函数',
    src: `flowchart LR
  u["输入 u(t)"] --> sum(("Σ")) --> G["G(s) = 10 / (s(s+1))"] --> y["输出 y(t)"]
  G --> H["H(s) = 1"] --> sum`,
  },
  {
    label: '信号流图',
    src: `flowchart LR
  x0((x0)) -->|"G1"| x1((x1)) -->|"G2"| x2((x2)) -->|"G3"| x3((x3))
  x1 -->|"H1"| x0
  x2 -->|"H2"| x1`,
  },
  {
    label: '流水线',
    src: `flowchart LR
  IF["取指"] --> ID["译码"] --> EX["执行"] --> MEM["访存"] --> WB["写回"]
  EX -.->|数据冒险转发| ID`,
  },
  {
    label: '时序图',
    src: `sequenceDiagram
  participant U as 用户
  participant A as App
  participant S as 服务端
  U->>A: 提交答题
  A->>S: POST /answers
  S-->>A: 200 + 判题结果
  A-->>U: 展示解析
  Note over S: 本地 Mermaid 渲染，无网络请求`,
  },
  {
    label: '状态机',
    src: `stateDiagram-v2
  [*] --> 初试备考
  初试备考 --> 复试准备: 过线
  复试准备 --> 拟录取: 复试通过
  复试准备 --> 调剂: 复试未过
  调剂 --> 拟录取: 调剂成功
  拟录取 --> [*]`,
  },
  {
    label: '知识结构图',
    src: `flowchart TD
  M["数学一"] --> A["高等数学"]
  M --> B["线性代数"]
  M --> C["概率论"]
  A --> A1["极限与连续"]
  A --> A2["一元微分/积分"]
  B --> B1["矩阵与特征值"]
  C --> C1["多维随机变量"]`,
  },
]

let renderSeq = 0

export default function DiagramStudio({ onClose }) {
  const [src, setSrc] = useState(TEMPLATES[0].src)
  const [svg, setSvg] = useState('')
  const [error, setError] = useState('')
  const [zoom, setZoom] = useState(1)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const libRef = useRef(null)
  const previewRef = useRef(null)

  /* mermaid 动态加载 + 初始化（本地包，不联网） */
  useEffect(() => {
    let alive = true
    import('mermaid').then((mod) => {
      const mermaid = mod.default
      mermaid.initialize({
        startOnLoad: false,
        theme: 'base',
        securityLevel: 'strict',
        fontFamily: 'ui-sans-serif, system-ui, "PingFang SC", "Microsoft YaHei", sans-serif',
        themeVariables: {
          primaryColor: '#eef0ff',
          primaryBorderColor: '#5b6cf0',
          primaryTextColor: '#1c2033',
          lineColor: '#7c86a8',
          fontSize: '14px',
        },
      })
      libRef.current = mermaid
      if (alive) setLoading(false)
    }).catch(() => {
      if (alive) {
        setLoading(false)
        setError('mermaid 库加载失败（打包资源缺失），请重新构建前端后重试')
      }
    })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!libRef.current) return undefined
    let alive = true
    setBusy(true)
    const id = window.setTimeout(async () => {
      const mermaid = libRef.current
      renderSeq += 1
      try {
        const { svg: out } = await mermaid.render(`v3-diagram-${renderSeq}`, src)
        if (!alive) return
        setSvg(out)
        setError('')
      } catch (err) {
        if (!alive) return
        setSvg('')
        setError(String(err?.message || err).slice(0, 400) || 'Mermaid 解析失败')
      } finally {
        if (alive) setBusy(false)
      }
    }, 300)
    return () => { alive = false; window.clearTimeout(id) }
  }, [src, loading])

  const lineError = useMemo(() => {
    const m = /line (\d+)/i.exec(error)
    return m ? Number(m[1]) : null
  }, [error])

  const buildSvgText = () => {
    const host = previewRef.current
    const node = host?.querySelector('svg')
    if (!node) throw new Error('当前没有可导出的图（请先修正语法错误）')
    const clone = node.cloneNode(true)
    clone.removeAttribute('style')
    const box = node.getBoundingClientRect()
    const w = Math.max(1, Math.round(box.width))
    const h = Math.max(1, Math.round(box.height))
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    clone.setAttribute('width', String(w))
    clone.setAttribute('height', String(h))
    return { text: new XMLSerializer().serializeToString(clone), w, h }
  }

  const exportSvg = () => {
    try {
      const { text } = buildSvgText()
      downloadBlob('diagram.svg', new Blob([text], { type: 'image/svg+xml;charset=utf-8' }))
      toastOk('SVG 已导出（矢量，可进 PPT / Inkscape 微调）')
    } catch (err) {
      toastErr(err?.message || 'SVG 导出失败')
    }
  }

  const exportPng = async () => {
    try {
      const { text, w, h } = buildSvgText()
      const url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml;charset=utf-8' }))
      try {
        const img = new Image()
        await new Promise((resolve, reject) => {
          img.onload = resolve
          img.onerror = () => reject(new Error('位图化失败，请改用 SVG 导出'))
          img.src = url
        })
        const scale = 2
        const canvas = document.createElement('canvas')
        canvas.width = Math.round(w * scale)
        canvas.height = Math.round(h * scale)
        const ctx = canvas.getContext('2d')
        ctx.fillStyle = '#ffffff'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
        if (!blob) throw new Error('PNG 生成失败，请改用 SVG')
        downloadBlob('diagram.png', blob)
        toastOk('PNG 已导出（2× 缩放，白底）')
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch (err) {
      toastErr(err?.message || 'PNG 导出失败')
    }
  }

  return (
    <ToolShell
      icon={<Layers size={16} />}
      title="框图编辑器"
      sub="Mermaid 源码 + 实时预览双模式 · 控制框图/信号流/时序/状态机模板 · 本地渲染与导出"
      onClose={onClose}
      className="v3-tool-diagram"
    >
      <div className="v3-td-templates">
        <span className="v3-label">模板</span>
        {TEMPLATES.map((t) => (
          <Chip key={t.label} as="button" type="button" active={t.src === src} onClick={() => setSrc(t.src)}>{t.label}</Chip>
        ))}
      </div>
      <div className="v3-td-grid">
        <div className="v3-td-edit">
          <div className="v3-td-pane-head">
            <span className="v3-label">Mermaid 源码</span>
            {lineError != null ? <span className="v3-td-errline">错误位于第 {lineError} 行附近</span> : null}
          </div>
          <textarea
            className="v3-td-ta"
            rows={14}
            value={src}
            spellCheck={false}
            aria-label="Mermaid 源码"
            onChange={(e) => setSrc(e.target.value)}
          />
          <details className="v3-td-help">
            <summary>语法速查（移动优先，点开看）</summary>
            <ul>
              <li><code>A --&gt; B</code> 实线箭头；<code>A -.&gt; B</code> 虚线；<code>A ==&gt; B</code> 粗线</li>
              <li><code>A["文字"]</code> 矩形，<code>A{"(( ))"}</code> 圆形，<code>A{"{ }"}</code> 菱形判断</li>
              <li><code>flowchart LR / TD</code> 横向 / 纵向；<code>subgraph 名称 ... end</code> 分组</li>
              <li><code>|标签|</code> 边文字；<code>sequenceDiagram</code> 中 <code>-&gt;&gt;</code> 请求、<code>--&gt;&gt;</code> 返回</li>
            </ul>
          </details>
        </div>
        <div className="v3-td-preview">
          <div className="v3-td-pane-head">
            <span className="v3-label">实时预览 {busy ? '· 渲染中…' : ''}</span>
            <span className="v3-td-zoom">
              <IconButton size="sm" label="缩小" icon={<Minimize2 size={14} />} onClick={() => setZoom((z) => Math.max(0.4, z / 1.25))} />
              <code>{Math.round(zoom * 100)}%</code>
              <IconButton size="sm" label="放大" icon={<Maximize2 size={14} />} onClick={() => setZoom((z) => Math.min(3, z * 1.25))} />
              <IconButton size="sm" label="重置缩放" icon={<RotateCcw size={14} />} onClick={() => setZoom(1)} />
            </span>
          </div>
          <div className="v3-td-preview__body">
            {loading ? <div className="v3-td-status">正在本地加载 mermaid…</div> : null}
            {!loading && error ? (
              <div className="v3-tools-error">
                <strong>Mermaid 语法错误：</strong>{error}
                <div className="v3-td-status">预览保留上一版之前的状态为空；修正源码高亮行后自动重渲。</div>
              </div>
            ) : null}
            {!loading && !error && !busy && !svg ? <div className="v3-td-status">输入合法源码后这里会实时出图。</div> : null}
            <div
              ref={previewRef}
              className="v3-td-svg"
              style={{ transform: `scale(${zoom})`, transformOrigin: 'top left', display: svg && !error ? 'block' : 'none' }}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          </div>
          <div className="v3-td-actions">
            <Button size="sm" variant="tonal" icon={<Download size={14} />} disabled={!svg || !!error} onClick={exportSvg}>导出 SVG</Button>
            <Button size="sm" variant="tonal" icon={<Download size={14} />} disabled={!svg || !!error} onClick={exportPng}>导出 PNG</Button>
            <span className="v3-td-note">渲染与导出均在本机完成（mermaid 随应用打包），不发送任何数据。</span>
          </div>
        </div>
      </div>
    </ToolShell>
  )
}
