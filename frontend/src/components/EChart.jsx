import React, { useEffect, useRef } from 'react'
// ECharts 按需引入：仅注册实际用到的图表与组件，显著减小 chunk 体积
import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart, PieChart, RadarChart, MapChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  PolarComponent,
  RadarComponent,
  GeoComponent,
  VisualMapComponent,
  DatasetComponent,
  TransformComponent,
} from 'echarts/components'
import { LabelLayout, UniversalTransition } from 'echarts/features'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart, LineChart, ScatterChart, PieChart, RadarChart, MapChart,
  TitleComponent, TooltipComponent, LegendComponent, GridComponent,
  PolarComponent, RadarComponent, GeoComponent, VisualMapComponent,
  DatasetComponent, TransformComponent,
  LabelLayout, UniversalTransition, CanvasRenderer,
])

// 注册中国地图（fetch GeoJSON 后 register）
let _mapRegistered = false
async function ensureChinaMap() {
  if (_mapRegistered) return
  try {
    const res = await fetch('/china.json')
    const geo = await res.json()
    echarts.registerMap('china', geo)
    _mapRegistered = true
  } catch (e) {
    console.error('china.json load failed:', e)
  }
}

/** 判断 option 是否真的带有可绘制的数据（避免渲染出一张空坐标系） */
function hasChartData(option) {
  if (!option) return false
  const series = Array.isArray(option.series) ? option.series : option.series ? [option.series] : []
  const seriesHasData = series.some((s) => {
    const d = s && s.data
    if (Array.isArray(d)) return d.length > 0
    return d != null && typeof d === 'object'
  })
  if (seriesHasData) return true
  const dataset = option.dataset
  if (Array.isArray(dataset)) return dataset.some((d) => Array.isArray(d?.source) && d.source.length > 0)
  return Array.isArray(dataset?.source) && dataset.source.length > 0
}

/** ECharts 通用封装：自适应大小，自动销毁；无数据时给统一的空态而非空坐标系 */
export default function Chart({ option, style = { height: '320px' }, emptyText = '暂无数据' }) {
  const ref = useRef(null)
  const chartRef = useRef(null)
  const hasData = hasChartData(option)
  // V7.0 P0-5：resize handler 必须以稳定引用保存，否则 cleanup 里的
  // removeEventListener 传入新函数引用 → 移除无效 → 每次挂载泄漏一个监听。
  const resizeHandlerRef = useRef(null)

  useEffect(() => {
    if (!hasData) return undefined
    if (!ref.current) return undefined
    let disposed = false
    let ro = null

    ensureChinaMap().then(() => {
      // 组件可能已在地图加载期间卸载，此时不能再 init / addEventListener
      if (disposed || !ref.current) return
      chartRef.current = echarts.init(ref.current)
      if (option) chartRef.current.setOption(option, true)
      const handler = () => chartRef.current && chartRef.current.resize()
      resizeHandlerRef.current = handler
      window.addEventListener('resize', handler)
      // ResizeObserver：容器宽度变化（侧栏展开/收起、分栏拖拽、隐藏面板重现）时
      // window 尺寸没变，旧实现不会重绘 → 图表被拉伸/压扁。这里监听容器自身。
      if (typeof ResizeObserver !== 'undefined') {
        ro = new ResizeObserver(() => handler())
        ro.observe(ref.current)
      }
    })

    return () => {
      disposed = true
      if (ro) { ro.disconnect(); ro = null }
      if (resizeHandlerRef.current) {
        window.removeEventListener('resize', resizeHandlerRef.current)
        resizeHandlerRef.current = null
      }
      chartRef.current && chartRef.current.dispose()
      chartRef.current = null
    }
  }, [hasData])

  useEffect(() => {
    if (chartRef.current && option) {
      chartRef.current.setOption(option, true)
    }
  }, [option])

  if (!hasData) {
    return (
      <div className="chart-empty" style={style}>
        <span className="chart-empty-text">{emptyText}</span>
      </div>
    )
  }

  return <div ref={ref} style={style} />
}
