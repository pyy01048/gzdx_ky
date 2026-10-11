import React, { useState, useEffect } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import EChart from '../components/EChart'

/**
 * D5: 区域择校地图热力图
 * 使用 ECharts 中国地图展示各省院校数量、平均分数线、平均复录比
 */
export default function KaoyanMap() {
  const [data, setData] = useState({ items: [] })
  const [year, setYear] = useState(2026)
  const [loading, setLoading] = useState(false)
  const [metric, setMetric] = useState('value') // value=院校数, avg_line=平均分数线, avg_retest_ratio=平均复录比

  useEffect(() => {
    setLoading(true)
    kaoyanApi.heatmap({ year }).then(setData).catch(() => setData({ items: [] })).finally(() => setLoading(false))
  }, [year])

  // 省份名映射（简化版，ECharts china 需要标准省份名）
  const nameMap = {
    '北京': '北京', '天津': '天津', '河北': '河北', '山西': '山西', '内蒙古': '内蒙古',
    '辽宁': '辽宁', '吉林': '吉林', '黑龙江': '黑龙江', '上海': '上海', '江苏': '江苏',
    '浙江': '浙江', '安徽': '安徽', '福建': '福建', '江西': '江西', '山东': '山东',
    '河南': '河南', '湖北': '湖北', '湖南': '湖南', '广东': '广东', '广西': '广西',
    '海南': '海南', '重庆': '重庆', '四川': '四川', '贵州': '贵州', '云南': '云南',
    '西藏': '西藏', '陕西': '陕西', '甘肃': '甘肃', '青海': '青海', '宁夏': '宁夏',
    '新疆': '新疆', '台湾': '台湾', '香港': '香港', '澳门': '澳门',
  }

  const metricLabels = {
    value: '院校数量',
    avg_line: '平均分数线',
    avg_retest_ratio: '平均复录比',
  }

  const items = data.items || []
  const maxVal = Math.max(...items.map(i => i[metric] || 0), 1)

  const chartOption = items.length > 0 ? {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const item = items.find(i => nameMap[i.name] === p.name || i.name === p.name)
        if (!item) return p.name
        return `${p.name}<br/>院校数: ${item.value}<br/>平均分数线: ${item.avg_line || '-'}<br/>平均复录比: ${item.avg_retest_ratio || '-'}`
      },
    },
    visualMap: {
      min: 0, max: maxVal,
      left: 'left', bottom: '10%',
      text: ['高', '低'],
      calculable: true,
      inRange: { color: ['#e0f2fe', '#0284c7', '#0c4a6e'] },
    },
    series: [{
      name: metricLabels[metric],
      type: 'map',
      map: 'china',
      roam: true,
      label: { show: false },
      emphasis: { label: { show: true } },
      data: items.map(i => ({ name: nameMap[i.name] || i.name, value: i[metric] || 0 })),
    }],
  } : null

  return (
    <div className="ky-page">
      <h1 style={{ marginBottom: '4px' }}>区域择校热力图</h1>
      <p style={{ color: 'var(--ink-3)', marginBottom: '20px' }}>全国各省院校分布与录取难度可视化</p>

      <div style={{ display: 'flex', gap: '12px', marginBottom: '20px' }}>
        <select value={year} onChange={e => setYear(+e.target.value)}
          style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)' }}>
          {[2026, 2025, 2024, 2023].map(y => <option key={y} value={y}>{y}年</option>)}
        </select>
        <select value={metric} onChange={e => setMetric(e.target.value)}
          style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)' }}>
          {Object.entries(metricLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>

      {loading && <div style={{ padding: '48px', textAlign: 'center' }}>加载中…</div>}

      {chartOption ? (
        <EChart option={chartOption} style={{ height: '600px' }} />
      ) : (
        <div style={{ padding: '48px', textAlign: 'center', color: 'var(--ink-3)' }}>
          暂无数据
        </div>
      )}

      {items.length > 0 && (
        <div style={{ marginTop: '20px' }}>
          <h3 style={{ marginBottom: '12px' }}>各省数据明细</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '8px' }}>
            {items.sort((a, b) => (b[metric] || 0) - (a[metric] || 0)).map((item, i) => (
              <div key={i} style={{
                padding: '12px', borderRadius: '8px',
                background: 'var(--surface)', border: '1px solid var(--line)',
              }}>
                <div style={{ fontWeight: 600 }}>{item.name}</div>
                <div style={{ fontSize: '13px', color: 'var(--ink-3)' }}>
                  院校 {item.value} 所 · 均分 {item.avg_line || '-'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
