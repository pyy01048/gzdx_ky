import React, { useState, useEffect } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import EChart from '../components/EChart'

/**
 * D6: 招生人数分布散点图
 * X轴: 拟招生人数, Y轴: 录取均分, 点大小: 复录比, 颜色: 院校层级
 */
export default function KaoyanScatter() {
  const [data, setData] = useState({ items: [] })
  const [year, setYear] = useState(2026)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    kaoyanApi.scatter({ year }).then(setData).catch(() => setData({ items: [] })).finally(() => setLoading(false))
  }, [year])

  const levelColor = {
    '985': '#dc2626',
    '211': '#f59e0b',
    '双一流': '#8b5cf6',
    '一本': '#10b981',
    '二本': '#3b82f6',
    '民办': '#6b7280',
  }

  const items = data.items || []

  // 按层级分组
  const groups = {}
  items.forEach(item => {
    const lvl = item.level || '其他'
    if (!groups[lvl]) groups[lvl] = []
    groups[lvl].push([
      item.enroll || 0,
      item.admit_avg || 0,
      item.retest_ratio ? item.retest_ratio * 5 : 10, // 气泡大小
      item.name,
      item.province,
    ])
  })

  const chartOption = items.length > 0 ? {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        return `${p.data[3]}<br/>招生: ${p.data[0]}人<br/>均分: ${p.data[1]}<br/>复录比: ${(p.data[2] / 5).toFixed(2)}`
      },
    },
    legend: { top: 0 },
    grid: { left: '8%', right: '5%', bottom: '10%', top: '15%' },
    xAxis: { name: '拟招生人数', type: 'value' },
    yAxis: { name: '录取均分', type: 'value' },
    series: Object.entries(groups).map(([level, data]) => ({
      name: level,
      type: 'scatter',
      data: data,
      symbolSize: (d) => d[2],
      itemStyle: { color: levelColor[level] || '#6b7280' },
    })),
  } : null

  return (
    <div className="ky-page">
      <h1 style={{ marginBottom: '4px' }}>招生人数分布散点图</h1>
      <p style={{ color: 'var(--ink-3)', marginBottom: '20px' }}>
        X轴=招生人数 · Y轴=录取均分 · 气泡大小=复录比 · 颜色=院校层级
      </p>

      <div style={{ marginBottom: '20px' }}>
        <select value={year} onChange={e => setYear(+e.target.value)}
          style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)' }}>
          {[2026, 2025, 2024, 2023].map(y => <option key={y} value={y}>{y}年</option>)}
        </select>
      </div>

      {loading && <div style={{ padding: '48px', textAlign: 'center' }}>加载中…</div>}

      {chartOption ? (
        <EChart option={chartOption} style={{ height: '500px' }} />
      ) : (
        <div style={{ padding: '48px', textAlign: 'center', color: 'var(--ink-3)' }}>暂无数据</div>
      )}

      {items.length > 0 && (
        <div style={{ marginTop: '20px' }}>
          <h3 style={{ marginBottom: '12px' }}>院校数据明细（{items.length}所）</h3>
          <div className="table-container">
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--line)' }}>
                {['院校', '层级', '省份', '招生', '录取均分', '复录比'].map(h =>
                  <th key={h} style={{ padding: '8px', textAlign: 'left' }}>{h}</th>
                )}
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 50).map((item, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--line)' }}>
                  <td style={{ padding: '8px', fontWeight: 600 }}>{item.name}</td>
                  <td style={{ padding: '8px' }}>
                    <span style={{ color: levelColor[item.level] || '#6b7280' }}>{item.level || '-'}</span>
                  </td>
                  <td style={{ padding: '8px' }}>{item.province || '-'}</td>
                  <td style={{ padding: '8px' }}>{item.enroll || '-'}</td>
                  <td style={{ padding: '8px' }}>{item.admit_avg || '-'}</td>
                  <td style={{ padding: '8px' }}>{item.retest_ratio || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          {items.length > 50 && <div style={{ padding: '12px', color: 'var(--ink-3)' }}>仅显示前50条</div>}
        </div>
      )}
    </div>
  )
}
