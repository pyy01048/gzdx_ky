import React, { useId, useMemo } from 'react'
import { Ring } from './ui'

/* -------------------------------------------------------------------------- */
/* Palette + ECharts helpers                                                  */
/* -------------------------------------------------------------------------- */
export const ECHART_COLORS = ['#4285F4', '#9B72CB', '#D96570', '#34A853', '#F9AB00', '#00ACC1', '#7A5AF8']

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

/* -------------------------------------------------------------------------- */
/* Sparkline / line                                                           */
/* -------------------------------------------------------------------------- */
export function MiniLineChart({
  data = [],
  height = 120,
  color = 'var(--v3-primary)',
  showArea = true,
  strokeWidth = 2.4,
  className = '',
}) {
  const gid = useId().replace(/:/g, '')
  const values = data.map((d) => (typeof d === 'number' ? d : Number(d?.value ?? 0)))
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const span = Math.max(max - min, 1)
  const w = 300
  const h = height
  const pad = 6
  const step = values.length > 1 ? (w - pad * 2) / (values.length - 1) : 0
  const pts = values.map((v, i) => [
    pad + i * step,
    pad + (1 - (v - min) / span) * (h - pad * 2),
  ])
  const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `${line} L${(pad + (values.length - 1) * step).toFixed(1)},${h - pad} L${pad},${h - pad} Z`

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
      {pts.length > 0 ? <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="3.2" fill={color} /> : null}
    </svg>
  )
}

export function MiniBarChart({ data = [], height = 120, color = 'var(--v3-primary)', className = '' }) {
  const values = data.map((d) => (typeof d === 'number' ? d : Number(d?.value ?? 0)))
  const max = Math.max(...values, 1)
  const n = Math.max(values.length, 1)
  const gap = 4
  const bw = (300 - gap * (n - 1)) / n

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
export function HeatMap({ data = [], weeks = 20, color = 'var(--v3-primary)', className = '' }) {
  const days = useMemo(() => {
    if (Array.isArray(data) && data.length && typeof data[0] === 'object') {
      return data.map((d) => ({ date: d.date || d.day, value: Number(d.value ?? d.count ?? d.minutes ?? 0) }))
    }
    return (data || []).map((v, i) => ({ i, value: Number(v) || 0 }))
  }, [data])
  const max = Math.max(...days.map((d) => d.value), 1)
  const columns = Math.max(1, Math.ceil(days.length / 7))
  const cell = 12
  const gap = 3
  const width = columns * (cell + gap)
  const height = 7 * (cell + gap)

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
            x={col * (cell + gap)}
            y={row * (cell + gap)}
            width={cell}
            height={cell}
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
export function RadarChart({ data = [], size = 220, color = 'var(--v3-primary)', className = '' }) {
  const items = data.length ? data : [{ label: '暂无', value: 0 }]
  const cx = size / 2
  const cy = size / 2
  const r = size * 0.36
  const n = items.length
  const max = Math.max(...items.map((d) => Number(d.value) || 0), 1)
  const point = (i, ratio) => {
    const a = (Math.PI * 2 * i) / n - Math.PI / 2
    return [cx + Math.cos(a) * r * ratio, cy + Math.sin(a) * r * ratio]
  }
  const polygon = items.map((d, i) => point(i, (Number(d.value) || 0) / max).join(',')).join(' ')

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
