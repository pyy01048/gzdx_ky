import React, { useId, useMemo } from 'react'
import { Ring } from './ui'

/* -------------------------------------------------------------------------- */
/* Palette + ECharts helpers                                                  */
/* -------------------------------------------------------------------------- */
export const ECHART_COLORS = ['#4285F4', '#9B72CB', '#D96570', '#34A853', '#F9AB00', '#00ACC1', '#7A5AF8']

/** 生成 ECharts 主题配置：根据明暗模式给出调色板、文本、轴线、提示框样式 */
export function chartTheme(isDark = false) {
  return {
    color: ECHART_COLORS,
    textStyle: {
      fontFamily: 'var(--v3-font-sans)',
      color: isDark ? '#B6BDCA' : '#474B55',
    },
    axisLine: { lineStyle: { color: isDark ? '#2A303C' : '#E1E6EF' } },
    splitLine: { lineStyle: { color: isDark ? '#20252F' : '#EEF2F8' } },
    tooltip: {
      backgroundColor: isDark ? '#181C25' : '#FFFFFF',
      borderColor: isDark ? '#2A303C' : '#E1E6EF',
      textStyle: { color: isDark ? '#E9EDF4' : '#1F2023', fontSize: 12 },
      extraCssText: 'border-radius:12px;box-shadow:0 10px 30px -10px rgba(0,0,0,.25);',
    },
  }
}

/** 把 data 数组统一转成数值数组：数字直接取，对象取 .value */
function toValues(data) {
  return (data || []).map((d) => (typeof d === 'number' ? d : Number(d?.value ?? 0)))
}

/* -------------------------------------------------------------------------- */
/* Sparkline / line                                                           */
/* -------------------------------------------------------------------------- */
/** 迷你折线图：SVG 路径 + 可选面积填充 + 末端高亮点；单点退化为圆点 */
export function MiniLineChart({
  data = [],
  height = 120,
  color = 'var(--v3-primary)',
  showArea = true,
  strokeWidth = 2.4,
  className = '',
}) {
  const gid = useId().replace(/:/g, '')
  const { line, area, pts, values, w, h, pad } = useMemo(() => {
    const vals = toValues(data)
    const max = Math.max(...vals, 1)
    const min = Math.min(...vals, 0)
    const span = Math.max(max - min, 1)
    const cw = 300
    const ch = height
    const p = 6
    const step = vals.length > 1 ? (cw - p * 2) / (vals.length - 1) : 0
    const points = vals.map((v, i) => [
      p + i * step,
      p + (1 - (v - min) / span) * (ch - p * 2),
    ])
    const l = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    const a = `${l} L${(p + (vals.length - 1) * step).toFixed(1)},${ch - p} L${p},${ch - p} Z`
    return { line: l, area: a, pts: points, values: vals, w: cw, h: ch, pad: p }
  }, [data, height])
  const lastPt = pts[pts.length - 1]
  return (
    <svg
      className={`v3-line-chart ${className}`.trim()}
      width="100%"
      height={height}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="趋势图"
    >
      <defs>
        <linearGradient id={`fill-${gid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {showArea && values.length > 1 ? <path d={area} fill={`url(#fill-${gid})`} /> : null}
      {values.length > 1 ? (
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray="600"
          strokeDashoffset="600"
          style={{ animation: 'v3-icon-draw 900ms var(--v3-ease-emphasized) forwards' }}
        />
      ) : (
        <circle cx={w / 2} cy={h / 2} r="4" fill={color} />
      )}
      {lastPt ? <circle cx={lastPt[0]} cy={lastPt[1]} r="3.2" fill={color} /> : null}
    </svg>
  )
}

/** 迷你柱状图：等宽柱形 + 按值渐变透明度 + 逐柱入场动画 */
export function MiniBarChart({ data = [], height = 120, color = 'var(--v3-primary)', className = '' }) {
  const { values, max, bw, gap } = useMemo(() => {
    const vals = toValues(data)
    const mx = Math.max(...vals, 1)
    const n = Math.max(vals.length, 1)
    const g = 4
    return { values: vals, max: mx, bw: (300 - g * (n - 1)) / n, gap: g }
  }, [data])
  return (
    <svg
      className={`v3-bar-chart ${className}`.trim()}
      width="100%"
      height={height}
      viewBox={`0 0 300 ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="柱状图"
    >
      {values.map((v, i) => {
        const bh = Math.max(2, (v / max) * (height - 10))
        return (
          <rect
            key={i}
            x={i * (bw + gap)}
            y={height - bh - 2}
            width={bw}
            height={bh}
            rx={Math.min(6, bw / 2)}
            fill={color}
            opacity={0.35 + (v / max) * 0.65}
            style={{
              transformOrigin: `center ${height}px`,
              animation: `v3-scale-in 520ms var(--v3-ease-spring) ${i * 26}ms both`,
            }}
          />
        )
      })}
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Ring progress (legacy-compatible signature)                                */
/* -------------------------------------------------------------------------- */
/** 环形进度图：复用 ui/Ring，中心叠放百分比、可选标签与副标 */
export function RingProgress({
  value = 0,
  size = 92,
  stroke = 8,
  color,
  label,
  sub,
  gradient = true,
}) {
  return (
    <Ring value={value} size={size} stroke={stroke} gradient={gradient}>
      <div style={{ display: 'grid', gap: 1 }}>
        <strong style={{ fontSize: Math.max(15, size * 0.22), letterSpacing: '-0.03em', color: color || 'var(--v3-text)' }}>
          {Math.round(value)}%
        </strong>
        {label ? <span className="v3-caption" style={{ fontSize: 10 }}>{label}</span> : null}
        {sub ? <span className="v3-caption" style={{ fontSize: 9 }}>{sub}</span> : null}
      </div>
    </Ring>
  )
}

/* -------------------------------------------------------------------------- */
/* Heatmap                                                                    */
/* -------------------------------------------------------------------------- */
/** 学习热力图：按周列排布的格子阵，颜色深浅表示当日学习量；支持对象数组与数值数组两种输入 */
export function HeatMap({ data = [], weeks = 20, color = 'var(--v3-primary)', className = '' }) {
  const { days, max, width, height } = useMemo(() => {
    let d
    if (Array.isArray(data) && data.length && typeof data[0] === 'object') {
      d = data.map((it) => ({ date: it.date || it.day, value: Number(it.value ?? it.count ?? it.minutes ?? 0) }))
    } else {
      d = (data || []).map((v, i) => ({ i, value: Number(v) || 0 }))
    }
    const mx = Math.max(...d.map((it) => it.value), 1)
    const columns = Math.max(1, Math.ceil(d.length / 7))
    const cell = 12
    const gap = 3
    return {
      days: d,
      max: mx,
      width: columns * (cell + gap),
      height: 7 * (cell + gap),
    }
  }, [data])
  return (
    <svg
      className={className}
      width="100%"
      height={Math.min(120, height)}
      viewBox={`0 0 ${Math.max(width, 1)} ${Math.max(height, 1)}`}
      preserveAspectRatio="xMinYMin meet"
      role="img"
      aria-label="学习热力图"
    >
      {days.map((d, i) => {
        const col = Math.floor(i / 7)
        const row = i % 7
        const ratio = d.value / max
        return (
          <rect
            key={i}
            x={col * 15}
            y={row * 15}
            width={12}
            height={12}
            rx={3}
            fill={d.value > 0 ? color : 'var(--v3-surface-2)'}
            opacity={d.value > 0 ? 0.22 + ratio * 0.78 : 1}
            style={{ animation: `v3-fade-in 500ms var(--v3-ease-standard) ${Math.min(i * 4, 500)}ms both` }}
          >
            <title>{`${d.date || ''} ${d.value}`}</title>
          </rect>
        )
      })}
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Radar                                                                      */
/* -------------------------------------------------------------------------- */
/** 能力雷达图：多边形网格 + 数据多边形 + 各顶点标签；空数据退化为「暂无」单点 */
export function RadarChart({ data = [], size = 220, color = 'var(--v3-primary)', className = '' }) {
  const { items, polygon, point, cx, cy, r, n, max } = useMemo(() => {
    const its = data.length ? data : [{ label: '暂无', value: 0 }]
    const center = size / 2
    const radius = size * 0.36
    const count = its.length
    const mx = Math.max(...its.map((d) => Number(d.value) || 0), 1)
    const pt = (i, ratio) => {
      const a = (Math.PI * 2 * i) / count - Math.PI / 2
      return [center + Math.cos(a) * radius * ratio, center + Math.sin(a) * radius * ratio]
    }
    const poly = its.map((d, i) => pt(i, (Number(d.value) || 0) / mx).join(',')).join(' ')
    return { items: its, polygon: poly, point: pt, cx: center, cy: center, r: radius, n: count, max: mx }
  }, [data, size])
  return (
    <svg className={className} width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="能力雷达图">
      {[0.33, 0.66, 1].map((ratio) => (
        <polygon
          key={ratio}
          points={items.map((_, i) => point(i, ratio).join(',')).join(' ')}
          fill="none"
          stroke="var(--v3-outline)"
          strokeWidth="1"
        />
      ))}
      {items.map((_, i) => (
        <line key={i} x1={cx} y1={cy} x2={point(i, 1)[0]} y2={point(i, 1)[1]} stroke="var(--v3-outline)" strokeWidth="1" />
      ))}
      <polygon points={polygon} fill={color} fillOpacity="0.16" stroke={color} strokeWidth="2" strokeLinejoin="round" />
      {items.map((d, i) => {
        const [x, y] = point(i, (Number(d.value) || 0) / max)
        return <circle key={i} cx={x} cy={y} r="3" fill={color} />
      })}
      {items.map((d, i) => {
        const [x, y] = point(i, 1.18)
        return (
          <text key={i} x={x} y={y} textAnchor="middle" dominantBaseline="middle" fontSize="10" fill="var(--v3-text-3)">
            {d.label}
          </text>
        )
      })}
    </svg>
  )
}
