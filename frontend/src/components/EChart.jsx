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

/** ECharts 通用封装：自适应大小，自动销毁 */
export default function Chart({ option, style = { height: '320px' } }) {
  const ref = useRef(null)
  const chartRef = useRef(null)
  // V7.0 P0-5：resize handler 必须以稳定引用保存，否则 cleanup 里的
  // removeEventListener 传入新函数引用 → 移除无效 → 每次挂载泄漏一个监听。
  const resizeHandlerRef = useRef(null)

  useEffect(() => {
    if (!ref.current) return
    let disposed = false

    ensureChinaMap().then(() => {
      // 组件可能已在地图加载期间卸载，此时不能再 init / addEventListener
      if (disposed || !ref.current) return
      chartRef.current = echarts.init(ref.current)
      if (option) chartRef.current.setOption(option, true)
      const handler = () => chartRef.current && chartRef.current.resize()
      resizeHandlerRef.current = handler
      window.addEventListener('resize', handler)
    })

    return () => {
      disposed = true
      if (resizeHandlerRef.current) {
        window.removeEventListener('resize', resizeHandlerRef.current)
        resizeHandlerRef.current = null
      }
      chartRef.current && chartRef.current.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    if (chartRef.current && option) {
      chartRef.current.setOption(option, true)
    }
  }, [option])

  return <div ref={ref} style={style} />
}
