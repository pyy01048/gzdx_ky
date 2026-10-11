/**
 * 数据可视化组件 V3.0
 * 轻量 SVG 图表，不依赖 ECharts
 *
 * 包含：
 * - MiniBarChart 迷你柱状图
 * - MiniLineChart 迷你折线图
 * - RingProgress 环形进度图
 * - HeatMap 热力图
 * - RadarChart 雷达图
 */
import React, { useMemo } from 'react'

/**
 * 迷你柱状图
 * @param {Object} props
 * @param {Array} props.data - 数据 [{label, value}]
 * @param {number} props.height - 高度
 * @param {string} props.color - 颜色
 */
export function MiniBarChart({ data = [], height = 120, color = 'var(--accent)' }) {
  const maxValue = Math.max(...data.map((d) => d.value), 1)
  const barWidth = 100 / data.length

  return (
    <svg width="100%" height={height} viewBox={`0 0 100 ${height}`} preserveAspectRatio="none">
      {data.map((d, i) => {
        const barHeight = (d.value / maxValue) * (height - 20)
        const y = height - barHeight - 10
        return (
          <g key={i}>
            <rect
              x={i * barWidth + barWidth * 0.2}
              y={y}
              width={barWidth * 0.6}
              height={barHeight}
              fill={color}
              rx="2"
              opacity={0.8}
            />
            {data.length <= 7 && (
              <text
                x={i * barWidth + barWidth / 2}
                y={height - 2}
                textAnchor="middle"
                fontSize="8"
                fill="var(--ink-3)"
              >
                {d.label}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

/**
 * 迷你折线图
 * @param {Object} props
 * @param {Array} props.data - 数据 [{label, value}]
 * @param {number} props.height - 高度
 * @param {string} props.color - 颜色
 * @param {boolean} props.showArea - 是否显示填充区域
 */
export function MiniLineChart({ data = [], height = 120, color = 'var(--accent)', showArea = true }) {
  const maxValue = Math.max(...data.map((d) => d.value), 1)
  const minValue = Math.min(...data.map((d) => d.value), 0)
  const range = maxValue - minValue || 1

  const points = data.map((d, i) => {
    const x = (i / (data.length - 1)) * 100
    const y = height - 15 - ((d.value - minValue) / range) * (height - 35)
    return { x, y }
  })

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
  const areaPath = `${linePath} L 100 ${height - 10} L 0 ${height - 10} Z`

  return (
    <svg width="100%" height={height} viewBox={`0 0 100 ${height}`} preserveAspectRatio="none">
      {showArea && (
        <path d={areaPath} fill={color} opacity="0.1" />
      )}
      <path d={linePath} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="1.5" fill={color} />
      ))}
      {data.length <= 7 && data.map((d, i) => (
        <text
          key={i}
          x={points[i].x}
          y={height - 2}
          textAnchor="middle"
          fontSize="8"
          fill="var(--ink-3)"
        >
          {d.label}
        </text>
      ))}
    </svg>
  )
}

/**
 * 环形进度图
 * @param {Object} props
 * @param {number} props.percent - 百分比 0-100
 * @param {number} props.size - 尺寸
 * @param {number} props.strokeWidth - 线宽
 * @param {string} props.color - 颜色
 * @param {string} props.trackColor - 轨道颜色
 * @param {React.ReactNode} props.children - 中心内容
 */
export function RingProgress({
  percent = 0,
  size = 120,
  strokeWidth = 10,
  color = 'var(--accent)',
  trackColor = 'var(--surface-2)',
  children,
}) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (Math.min(percent, 100) / 100) * circumference

  return (
    <div className="ring-progress" style={{ width: size, height: size, position: 'relative' }}>
      <svg width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={trackColor}
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 0.5s ease' }}
        />
      </svg>
      <div
        className="ring-progress-center"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
        }}
      >
        {children || (
          <>
            <span style={{ fontSize: size * 0.25, fontWeight: 700, color: 'var(--ink)' }}>{Math.round(percent)}%</span>
          </>
        )}
      </div>
    </div>
  )
}

/**
 * 热力图
 * @param {Object} props
 * @param {Array} props.data - 数据 [{date, value}] 或二维数组
 * @param {number} props.weeks - 周数
 * @param {string} props.color - 基础颜色
 */
export function HeatMap({ data = [], weeks = 20, color = 'var(--accent)' }) {
  const days = weeks * 7
  const maxValue = Math.max(...data.map((d) => d.value), 1)

  const cells = useMemo(() => {
    const result = []
    for (let w = 0; w < weeks; w++) {
      for (let d = 0; d < 7; d++) {
        const idx = w * 7 + d
        const item = data[idx]
        const value = item?.value || 0
        const opacity = value > 0 ? 0.2 + (value / maxValue) * 0.8 : 0.08
        result.push({ w, d, value, opacity, date: item?.date })
      }
    }
    return result
  }, [data, weeks, maxValue])

  const cellSize = 12
  const gap = 3

  return (
    <div className="heatmap" style={{ display: 'flex', gap: gap + 'px' }}>
      {Array.from({ length: weeks }).map((_, w) => (
        <div key={w} style={{ display: 'flex', flexDirection: 'column', gap: gap + 'px' }}>
          {Array.from({ length: 7 }).map((_, d) => {
            const cell = cells.find((c) => c.w === w && c.d === d)
            return (
              <div
                key={d}
                title={cell?.date ? `${cell.date}: ${cell.value} 分钟` : ''}
                style={{
                  width: cellSize,
                  height: cellSize,
                  borderRadius: 2,
                  background: cell?.value > 0 ? color : 'var(--surface-2)',
                  opacity: cell?.opacity || 0.08,
                }}
              />
            )
          })}
        </div>
      ))}
    </div>
  )
}

/**
 * 雷达图
 * @param {Object} props
 * @param {Array} props.data - 数据 [{label, value}] value 0-100
 * @param {number} props.size - 尺寸
 * @param {string} props.color - 颜色
 */
export function RadarChart({ data = [], size = 200, color = 'var(--accent)' }) {
  const center = size / 2
  const radius = size / 2 - 30
  const angleStep = (2 * Math.PI) / data.length

  const points = data.map((d, i) => {
    const angle = i * angleStep - Math.PI / 2
    const r = (d.value / 100) * radius
    return {
      x: center + r * Math.cos(angle),
      y: center + r * Math.sin(angle),
      labelX: center + (radius + 15) * Math.cos(angle),
      labelY: center + (radius + 15) * Math.sin(angle),
    }
  })

  const polygonPath = points.map((p) => `${p.x},${p.y}`).join(' ')

  // 网格线
  const gridLevels = [0.25, 0.5, 0.75, 1]

  return (
    <svg width={size} height={size}>
      {/* 网格 */}
      {gridLevels.map((level, i) => {
        const gridPoints = data.map((_, j) => {
          const angle = j * angleStep - Math.PI / 2
          const r = level * radius
          return `${center + r * Math.cos(angle)},${center + r * Math.sin(angle)}`
        }).join(' ')
        return (
          <polygon
            key={i}
            points={gridPoints}
            fill="none"
            stroke="var(--line)"
            strokeWidth="0.5"
          />
        )
      })}

      {/* 轴线 */}
      {data.map((_, i) => {
        const angle = i * angleStep - Math.PI / 2
        return (
          <line
            key={i}
            x1={center}
            y1={center}
            x2={center + radius * Math.cos(angle)}
            y2={center + radius * Math.sin(angle)}
            stroke="var(--line)"
            strokeWidth="0.5"
          />
        )
      })}

      {/* 数据区域 */}
      <polygon points={polygonPath} fill={color} opacity="0.2" />
      <polygon points={polygonPath} fill="none" stroke={color} strokeWidth="2" />

      {/* 数据点 */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="3" fill={color} />
      ))}

      {/* 标签 */}
      {points.map((p, i) => (
        <text
          key={i}
          x={p.labelX}
          y={p.labelY}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="10"
          fill="var(--ink-2)"
        >
          {data[i].label}
        </text>
      ))}
    </svg>
  )
}

export default {
  MiniBarChart,
  MiniLineChart,
  RingProgress,
  HeatMap,
  RadarChart,
}
