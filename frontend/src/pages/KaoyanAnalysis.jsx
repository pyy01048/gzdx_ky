import React, { useState, useEffect } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import EChart from '../components/EChart'
import { toast, Empty } from '../components/UI'

export default function KaoyanAnalysis() {
  const [schools, setSchools] = useState([])
  const [selected, setSelected] = useState(null)
  const [metric, setMetric] = useState('total_line')
  const [trend, setTrend] = useState({ data: [] })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    kaoyanApi.schools({ page_size: 100 }).then(setSchools).catch(() => toast('院校列表加载失败'))
  }, [])

  useEffect(() => {
    if (!selected) return
    setLoading(true)
    kaoyanApi.trend({ school_id: selected, metric, years: 5 })
      .then(setTrend)
      .catch(() => toast('趋势数据加载失败'))
      .finally(() => setLoading(false))
  }, [selected, metric])

  const metrics = [
    { value: 'total_line', label: '总分线' },
    { value: 'retest_line', label: '复试线' },
    { value: 'national_line', label: '国家线' },
    { value: 'admit_avg_score', label: '录取均分' },
    { value: 'enroll_count', label: '招生人数' },
    { value: 'retest_ratio', label: '复录比' },
  ]

  const chartOption = trend.data.length > 0 ? {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: trend.data.map(d => d.year) },
    yAxis: { type: 'value' },
    series: [{ type: 'line', data: trend.data.map(d => d.value), smooth: true, areaStyle: {} }],
  } : null

  return (
    <div className="ky-page">
      <h1 style={{ marginBottom: '16px' }}>分数分析</h1>

      <div style={{ display: 'flex', gap: '12px', marginBottom: '20px' }}>
        <select value={selected || ''} onChange={e => setSelected(e.target.value)}
          style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', flex: 1 }}>
          <option value="">选择院校</option>
          {schools.items?.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select value={metric} onChange={e => setMetric(e.target.value)}
          style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)' }}>
          {metrics.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
      </div>

      {loading && <div style={{padding:'48px',textAlign:'center'}}>分析中…</div>}

      {chartOption ? (
        <EChart option={chartOption} style={{ height: '400px' }} />
      ) : (
        <Empty title='暂无趋势数据' desc='选择院校和指标后查看分数线趋势图' />
      )}

      {trend.data.length > 0 && (
        <div className="table-container">
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '20px' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--line)' }}>
              <th style={{ padding: '8px' }}>年份</th>
              <th style={{ padding: '8px' }}>{metrics.find(m => m.value === metric)?.label}</th>
            </tr>
          </thead>
          <tbody>
            {trend.data.map((d, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--line)' }}>
                <td style={{ padding: '8px' }}>{d.year}</td>
                <td style={{ padding: '8px' }}>{d.value ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </div>
  )
}
