/**
 * 函数图像生成器（浏览器本地真实计算，不联网）
 * - 多条 y=f(x) 叠加绘制；参数滑块 a/b/c/d 实时联动
 * - 数值方法自动标注：零点（变号扫描+二分）、极值（数值导数变号+二分）、交点（差函数变号）
 * - 取值表按当前视窗自动生成；拖拽平移、滚轮/双指缩放
 * - 表达式解析与求值基于 mathjs；极点/断点（tan、1/x）不冒充零点极值，超出数量上限如实提示截断
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as math from 'mathjs'
import { Button, Chip, IconButton, Input, toastErr } from '../../ui'
import { Maximize2, Minimize2, Plus, RotateCcw, SlidersHorizontal, Trash, Eye, X } from '../../icons'
import { ToolShell } from './toolsShared'
import '../../styles/tools-suite-v3.css'
import {
  clamp, compileWith, findLocalExtrema, findSignChangeRoots, fmt, niceStep,
} from './toolUtils'

const PALETTE = ['#5b6cf0', '#e07a3f', '#2f9e6e', '#b05cc9', '#d1495b', '#2f8fb8']
const PRESETS = [
  { label: 'x²−2', expr: 'x^2 - 2' },
  { label: 'sin(x)+x/4', expr: 'sin(x) + x/4' },
  { label: 'a·sin(b·x)+c', expr: 'a*sin(b*x) + c' },
  { label: 'e^(−a·x²)', expr: 'exp(-a*x^2)' },
  { label: 'x³/8−2x', expr: 'x^3/8 - 2*x' },
  { label: 'tan(x)', expr: 'tan(x)' },
  { label: '1/x', expr: '1/x' },
  { label: 'ln(x)', expr: 'ln(x)' },
]
const DEFAULT_VIEW = { x0: -10, x1: 10, y0: -6, y1: 6 }
const PARAM_KEYS = ['a', 'b', 'c', 'd']
let nextId = 1

function makeFun(expr) {
  return { id: nextId++, expr, color: PALETTE[(nextId * 7) % PALETTE.length], visible: true }
}

export default function FunctionPlot({ onClose }) {
  const [funs, setFuns] = useState(() => [makeFun('x^3/8 - 2*x'), makeFun('a*sin(b*x) + c')])
  const [params, setParams] = useState({ a: 1, b: 1, c: 0, d: 1 })
  const [showParams, setShowParams] = useState(true)
  const [view, setView] = useState(DEFAULT_VIEW)
  const [flags, setFlags] = useState({ zeros: true, extrema: true, cross: true, table: false })
  const [size, setSize] = useState({ w: 640, h: 360 })

  const wrapRef = useRef(null)
  const canvasRef = useRef(null)
  const gestureRef = useRef(null)

  /* 容器尺寸跟随（含旋屏 / 分栏变化） */
  useEffect(() => {
    const el = wrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect
      setSize({ w: Math.max(240, Math.round(r.width)), h: Math.max(220, Math.round(r.height)) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const compiled = useMemo(
    () => funs.map((f) => ({ ...f, c: compileWith(math, f.expr) })),
    [funs],
  )

  const evaluable = useMemo(
    () => compiled.filter((f) => f.visible && f.c.ok).map((f) => ({
      id: f.id, color: f.color, expr: f.expr,
      f: (x) => f.c.evaluate({ x, ...params }),
    })),
    [compiled, params],
  )

  const spanX = view.x1 - view.x0
  const spanY = view.y1 - view.y0

  /* 采样（每条曲线约每 CSS 像素一个点，封顶 1600） */
  const samples = useMemo(() => evaluable.map((ef) => {
    const n = clamp(size.w, 320, 1600)
    const ys = new Float64Array(n + 1)
    for (let i = 0; i <= n; i += 1) ys[i] = ef.f(view.x0 + (spanX * i) / n)
    return { ...ef, ys, n }
  }), [evaluable, size.w, view.x0, spanX])

  /* 数值分析：零点 / 极值 / 交点（基于当前视窗） */
  const analysis = useMemo(() => {
    const cap = Math.abs(spanY) * 50
    const zeros = []
    const extrema = []
    const crosses = []
    let truncated = false
    if (flags.zeros || flags.extrema) {
      for (const ef of evaluable) {
        if (flags.zeros) {
          const r = findSignChangeRoots(ef.f, view.x0, view.x1, { cap, max: 30 })
          r.roots.forEach((x) => zeros.push({ id: ef.id, color: ef.color, x }))
          truncated = truncated || r.truncated
        }
        if (flags.extrema) {
          const r = findLocalExtrema(ef.f, view.x0, view.x1, { cap, max: 30 })
          r.points.forEach((p) => extrema.push({ id: ef.id, color: ef.color, ...p }))
          truncated = truncated || r.truncated
        }
      }
    }
    if (flags.cross && evaluable.length > 1) {
      outer: for (let i = 0; i < evaluable.length; i += 1) {
        for (let j = i + 1; j < evaluable.length; j += 1) {
          const diff = (x) => evaluable[i].f(x) - evaluable[j].f(x)
          const r = findSignChangeRoots(diff, view.x0, view.x1, { cap: cap * 0.2, max: 24 })
          r.roots.forEach((x) => crosses.push({ a: evaluable[i].id, b: evaluable[j].id, color: evaluable[i].color, x, y: evaluable[i].f(x) }))
          truncated = truncated || r.truncated
          if (crosses.length >= 40) { truncated = true; break outer }
        }
      }
    }
    return { zeros, extrema, crosses, truncated }
  }, [evaluable, flags, view.x0, view.x1, spanY])

  /* ---------------- 绘制 ---------------- */
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5)
    const { w, h } = size
    canvas.width = Math.round(w * dpr)
    canvas.height = Math.round(h * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)

    const css = getComputedStyle(document.documentElement)
    const tok = (name, fallback) => css.getPropertyValue(name).trim() || fallback
    const cGrid = tok('--v3-outline', '#e2e8f0')
    const cAxis = tok('--v3-text-3', '#64748b')
    const cText = tok('--v3-text', '#0f172a')
    const cSurface = tok('--v3-surface', '#ffffff')

    const sx = (x) => ((x - view.x0) / spanX) * w
    const sy = (y) => h - ((y - view.y0) / spanY) * h

    /* 网格 + 刻度 */
    ctx.lineWidth = 1
    ctx.font = '11px ui-monospace, monospace'
    ctx.fillStyle = cAxis
    const gx = niceStep(spanX, Math.max(4, Math.round(w / 90)))
    const gy = niceStep(spanY, Math.max(3, Math.round(h / 70)))
    ctx.strokeStyle = cGrid
    ctx.beginPath()
    for (let x = Math.ceil(view.x0 / gx) * gx; x <= view.x1; x += gx) {
      const px = Math.round(sx(x)) + 0.5
      ctx.moveTo(px, 0); ctx.lineTo(px, h)
    }
    for (let y = Math.ceil(view.y0 / gy) * gy; y <= view.y1; y += gy) {
      const py = Math.round(sy(y)) + 0.5
      ctx.moveTo(0, py); ctx.lineTo(w, py)
    }
    ctx.stroke()

    /* 坐标轴 */
    ctx.strokeStyle = cAxis
    ctx.beginPath()
    if (view.y0 <= 0 && view.y1 >= 0) { ctx.moveTo(0, sy(0)); ctx.lineTo(w, sy(0)) }
    if (view.x0 <= 0 && view.x1 >= 0) { ctx.moveTo(sx(0), 0); ctx.lineTo(sx(0), h) }
    ctx.stroke()
    /* 刻度数字 */
    for (let x = Math.ceil(view.x0 / gx) * gx; x <= view.x1; x += gx) {
      if (Math.abs(x) < gx / 1e6) continue
      const label = fmt(x, 4)
      ctx.fillText(label, sx(x) + 3, clamp(sy(0) + 13, 12, h - 4))
    }
    for (let y = Math.ceil(view.y0 / gy) * gy; y <= view.y1; y += gy) {
      if (Math.abs(y) < gy / 1e6) continue
      ctx.fillText(fmt(y, 4), clamp(sx(0) + 4, 4, w - 34), sy(y) - 3)
    }

    /* 曲线：断点/极点处抬笔，不画假的竖线 */
    for (const s of samples) {
      ctx.strokeStyle = s.color
      ctx.lineWidth = 2
      ctx.beginPath()
      let pen = false
      let prevY = NaN
      for (let i = 0; i <= s.n; i += 1) {
        const x = view.x0 + (spanX * i) / s.n
        const y = s.ys[i]
        const jump = Number.isFinite(prevY) && Number.isFinite(y)
          && Math.abs(y - prevY) > Math.abs(spanY) * 4 && y * prevY < 0
        if (!Number.isFinite(y) || jump) { pen = false; prevY = y; continue }
        const px = sx(x)
        const py = clamp(sy(y), -2000, h + 2000)
        if (!pen) { ctx.moveTo(px, py); pen = true } else ctx.lineTo(px, py)
        prevY = y
      }
      ctx.stroke()
    }

    /* 标注：零点 / 极值 / 交点 */
    const drawMark = (px, py, color, label, dy) => {
      ctx.beginPath()
      ctx.arc(px, py, 3.6, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
      ctx.strokeStyle = cSurface
      ctx.lineWidth = 1.4
      ctx.stroke()
      ctx.font = '10.5px ui-monospace, monospace'
      const tw = ctx.measureText(label).width
      const lx = clamp(px - tw / 2, 2, w - tw - 3)
      const ly = clamp(py + dy, 12, h - 4)
      ctx.fillStyle = cSurface
      ctx.globalAlpha = 0.82
      ctx.fillRect(lx - 2, ly - 10, tw + 4, 13)
      ctx.globalAlpha = 1
      ctx.fillStyle = cText
      ctx.fillText(label, lx, ly)
    }
    for (const z of analysis.zeros) drawMark(sx(z.x), sy(0), z.color, `0(${fmt(z.x, 4)})`, -8)
    for (const p of analysis.extrema) {
      if (p.y < view.y0 || p.y > view.y1) continue
      drawMark(sx(p.x), sy(p.y), p.color, `${p.kind === 'max' ? '极大' : '极小'}(${fmt(p.x, 4)}, ${fmt(p.y, 4)})`, p.kind === 'max' ? -8 : 16)
    }
    for (const c of analysis.crosses) {
      if (c.y < view.y0 || c.y > view.y1 || !Number.isFinite(c.y)) continue
      drawMark(sx(c.x), sy(c.y), '#0ea5e9', `∩(${fmt(c.x, 4)}, ${fmt(c.y, 4)})`, -8)
    }
  }, [samples, analysis, size, view, spanX, spanY])

  /* ---------------- 手势：拖拽平移 / 双指捏合 / 滚轮缩放 ---------------- */
  const zoomAt = useCallback((factor, anchorPx, anchorPy) => {
    setView((v) => {
      const nx = (anchorPx / size.w) * (v.x1 - v.x0) + v.x0
      const ny = ((size.h - anchorPy) / size.h) * (v.y1 - v.y0) + v.y0
      const sSpan = clamp((v.x1 - v.x0) / factor, 1e-9, 1e12)
      const sSpanY = clamp((v.y1 - v.y0) / factor, 1e-9, 1e12)
      return {
        x0: nx - (anchorPx / size.w) * sSpan,
        x1: nx + (1 - anchorPx / size.w) * sSpan,
        y0: ny - ((size.h - anchorPy) / size.h) * sSpanY,
        y1: ny + (anchorPy / size.h) * sSpanY,
      }
    })
  }, [size])

  /* 手势状态：pointers 实时位置；进入 pan/pinch 时快照起点与视窗，move 全部从快照推导，避免误差累积 */
  const onPointerDown = (e) => {
    e.currentTarget.setPointerCapture?.(e.pointerId)
    const g = gestureRef.current || { pointers: new Map() }
    g.pointers.set(e.pointerId, { x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })
    if (g.pointers.size === 1) {
      g.mode = 'pan'
      g.start = [{ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY }]
      g.view0 = view
    } else if (g.pointers.size === 2) {
      g.mode = 'pinch'
      g.start = Array.from(g.pointers.values())
      g.view0 = view
    }
    gestureRef.current = g
  }
  const onPointerMove = (e) => {
    const g = gestureRef.current
    if (!g || !g.pointers.has(e.pointerId)) return
    g.pointers.set(e.pointerId, { x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })
    const v0 = g.view0
    if (g.mode === 'pan' && g.pointers.size === 1) {
      const dx = (e.nativeEvent.offsetX - g.start[0].x) / size.w * (v0.x1 - v0.x0)
      const dy = (e.nativeEvent.offsetY - g.start[0].y) / size.h * (v0.y1 - v0.y0)
      setView({ x0: v0.x0 - dx, x1: v0.x1 - dx, y0: v0.y0 + dy, y1: v0.y1 + dy })
    } else if (g.mode === 'pinch' && g.pointers.size >= 2) {
      const cur = Array.from(g.pointers.values()).slice(0, 2)
      const d0 = Math.hypot(g.start[0].x - g.start[1].x, g.start[0].y - g.start[1].y)
      const d1 = Math.hypot(cur[0].x - cur[1].x, cur[0].y - cur[1].y)
      if (!(d0 > 4) || !(d1 > 0)) return
      const factor = clamp(d1 / d0, 0.05, 20)
      const mid0 = { x: (g.start[0].x + g.start[1].x) / 2, y: (g.start[0].y + g.start[1].y) / 2 }
      const mid1 = { x: (cur[0].x + cur[1].x) / 2, y: (cur[0].y + cur[1].y) / 2 }
      /* 捏合起点中点下的数据点，在捏合后落到当前中点下 */
      const anchorX = v0.x0 + (mid0.x / size.w) * (v0.x1 - v0.x0)
      const anchorY = v0.y0 + ((size.h - mid0.y) / size.h) * (v0.y1 - v0.y0)
      const spanXn = clamp((v0.x1 - v0.x0) / factor, 1e-9, 1e12)
      const spanYn = clamp((v0.y1 - v0.y0) / factor, 1e-9, 1e12)
      setView({
        x0: anchorX - (mid1.x / size.w) * spanXn,
        x1: anchorX + (1 - mid1.x / size.w) * spanXn,
        y0: anchorY - ((size.h - mid1.y) / size.h) * spanYn,
        y1: anchorY + (mid1.y / size.h) * spanYn,
      })
    }
  }
  const onPointerUp = (e) => {
    const g = gestureRef.current
    if (!g) return
    g.pointers.delete(e.pointerId)
    if (g.pointers.size === 0) gestureRef.current = null
    else if (g.pointers.size === 1) {
      /* 双指剩一指：以剩余手指为新 pan 起点 */
      const only = Array.from(g.pointers.values())[0]
      g.mode = 'pan'
      g.start = [only]
      g.view0 = viewRef.current
    }
  }
  const viewRef = useRef(view)
  useEffect(() => { viewRef.current = view }, [view])

  const onWheel = (e) => {
    e.preventDefault()
    zoomAt(Math.exp(-e.deltaY * 0.0016), e.nativeEvent.offsetX, e.nativeEvent.offsetY)
  }

  const fitY = () => {
    const vals = []
    for (const s of samples) for (let i = 0; i <= s.n; i += 1) if (Number.isFinite(s.ys[i])) vals.push(s.ys[i])
    if (!vals.length) { toastErr('当前视窗内没有可绘制的有限取值'); return }
    vals.sort((a, b) => a - b)
    const lo = vals[Math.floor(vals.length * 0.02)]
    const hi = vals[Math.floor(vals.length * 0.98)] ?? lo
    const pad = Math.max((hi - lo) * 0.12, 1e-6)
    setView((v) => ({ ...v, y0: lo - pad, y1: hi + pad }))
  }

  const toggleFlag = (k) => setFlags((f) => ({ ...f, [k]: !f[k] }))
  const addFun = (expr) => setFuns((fs) => (fs.length >= 6 ? (toastErr('最多叠加 6 条曲线'), fs) : [...fs, makeFun(expr || 'x')]))
  const setExpr = (id, expr) => setFuns((fs) => fs.map((f) => (f.id === id ? { ...f, expr } : f)))
  const delFun = (id) => setFuns((fs) => (fs.length === 1 ? (toastErr('至少保留一条曲线'), fs) : fs.filter((f) => f.id !== id)))

  /* 取值表：当前 x 视窗均分 15 行 */
  const tableRows = useMemo(() => {
    if (!flags.table) return []
    const n = 15
    return Array.from({ length: n }, (_, i) => {
      const x = view.x0 + (spanX * (i + 0.5)) / n
      return { x, ys: evaluable.map((ef) => ef.f(x)) }
    })
  }, [flags.table, evaluable, view.x0, spanX])

  const markCount = analysis.zeros.length + analysis.extrema.length + analysis.crosses.length

  return (
    <ToolShell
      icon={<Maximize2 size={16} />}
      title="函数图像生成器"
      sub="mathjs 本地求值 · 零点/极值/交点数值标注 · 拖拽平移、滚轮与双指缩放 · 不联网"
      onClose={onClose}
      className="v3-tool-graph"
    >
      <div className="v3-tg-funs">
        {compiled.map((f) => (
          <div key={f.id} className="v3-tg-fun">
            <button
              type="button"
              className="v3-tg-swatch"
              style={{ background: f.visible ? f.color : 'transparent', borderColor: f.color }}
              aria-label={`切换曲线显示（${f.expr || '空'}）`}
              title={f.visible ? '隐藏曲线' : '显示曲线'}
              onClick={() => setFuns((fs) => fs.map((q) => (q.id === f.id ? { ...q, visible: !q.visible } : q)))}
            >
              {f.visible ? <Eye size={12} /> : <X size={12} />}
            </button>
            <span className="v3-tg-fx">y =</span>
            <Input
              className="v3-tools-mono"
              value={f.expr}
              spellCheck={false}
              autoComplete="off"
              aria-label="函数表达式"
              onChange={(e) => setExpr(f.id, e.target.value)}
            />
            <IconButton size="sm" label="删除曲线" icon={<Trash size={14} />} onClick={() => delFun(f.id)} />
            {!f.c.ok ? <div className="v3-tools-error">{f.expr.trim() ? `解析失败：${f.c.message}` : '请输入表达式，如 sin(x) + a'}</div> : null}
          </div>
        ))}
        <div className="v3-tg-presets">
          <Button size="sm" variant="tonal" icon={<Plus size={14} />} onClick={() => addFun()}>添加曲线</Button>
          {PRESETS.map((p) => (
            <Chip key={p.expr} as="button" type="button" onClick={() => addFun(p.expr)}>{p.label}</Chip>
          ))}
        </div>
      </div>

      <div className="v3-tg-toolbar">
        <IconButton size="sm" label="放大" icon={<Plus size={14} />} onClick={() => zoomAt(1.4, size.w / 2, size.h / 2)} />
        <IconButton size="sm" label="缩小" icon={<Minimize2 size={14} />} onClick={() => zoomAt(1 / 1.4, size.w / 2, size.h / 2)} />
        <IconButton size="sm" label="适应 Y 范围（2%–98% 分位）" icon={<Maximize2 size={14} />} onClick={fitY} />
        <IconButton size="sm" label="重置视窗" icon={<RotateCcw size={14} />} onClick={() => setView(DEFAULT_VIEW)} />
        <span className="v3-tg-sep" aria-hidden="true" />
        <Chip as="button" type="button" active={flags.zeros} onClick={() => toggleFlag('zeros')}>零点</Chip>
        <Chip as="button" type="button" active={flags.extrema} onClick={() => toggleFlag('extrema')}>极值</Chip>
        <Chip as="button" type="button" active={flags.cross} onClick={() => toggleFlag('cross')}>交点</Chip>
        <Chip as="button" type="button" active={flags.table} onClick={() => toggleFlag('table')}>取值表</Chip>
        <span className="v3-tg-sep" aria-hidden="true" />
        <Chip as="button" type="button" gradient={showParams} icon={<SlidersHorizontal size={12} />} onClick={() => setShowParams((v) => !v)}>参数滑块</Chip>
      </div>

      {showParams ? (
        <div className="v3-tg-params">
          {PARAM_KEYS.map((k) => (
            <label key={k} className="v3-tg-param">
              <span className="v3-tg-param__name">{k}</span>
              <input
                type="range"
                min={-5}
                max={5}
                step={0.01}
                value={params[k]}
                aria-label={`参数 ${k}`}
                onChange={(e) => setParams((p) => ({ ...p, [k]: Number(e.target.value) }))}
                onDoubleClick={() => setParams((p) => ({ ...p, [k]: k === 'a' || k === 'b' ? 1 : 0 }))}
              />
              <code className="v3-tg-param__val">{fmt(params[k], 4)}</code>
            </label>
          ))}
        </div>
      ) : null}

      <div className="v3-tg-canvas-wrap" ref={wrapRef}>
        <canvas
          ref={canvasRef}
          className="v3-tg-canvas"
          aria-label="函数图像画布：按住拖动平移，滚轮或双指缩放"
          style={{ touchAction: 'none' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onWheel={onWheel}
        />
      </div>

      <div className="v3-tg-status">
        视窗 x∈[{fmt(view.x0, 5)}, {fmt(view.x1, 5)}] · y∈[{fmt(view.y0, 5)}, {fmt(view.y1, 5)}] ·
        {' '}当前标注：零点 {analysis.zeros.length} · 极值 {analysis.extrema.length} · 交点 {analysis.crosses.length}
        {analysis.truncated ? '（已达标注上限，视窗内可能还有未标注的点）' : ''}
        {!analysis.truncated && markCount === 0 && evaluable.length ? '（视窗内未发现零点/极值/交点，可平移缩放再看）' : ''}
      </div>
      <p className="v3-tg-note">
        零点/极值/交点为数值搜索结果（采样 {clamp(size.w, 320, 1600)} 点 + 二分细化，精度约 1e-10），
        仅覆盖当前 x 视窗；极点（如 tan、1/x 的跳变）已被连续性校验排除，不作为零点。
      </p>

      {flags.table ? (
        <div className="v3-tg-table-wrap">
          <table className="v3-tg-table">
            <thead>
              <tr>
                <th>x</th>
                {evaluable.map((ef, i) => <th key={ef.id} style={{ color: ef.color }}>f{i + 1} = {ef.expr}</th>)}
              </tr>
            </thead>
            <tbody>
              {tableRows.map((r) => (
                <tr key={r.x}>
                  <td>{fmt(r.x, 6)}</td>
                  {r.ys.map((y, i) => <td key={i}>{fmt(y, 6)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="v3-tg-note">「—」表示该点无定义（实数域）；表按当前 x 视窗均分 15 行取值。</p>
        </div>
      ) : null}
    </ToolShell>
  )
}
