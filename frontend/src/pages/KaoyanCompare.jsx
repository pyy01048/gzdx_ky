import React, { useState, useEffect } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import EChart from '../components/EChart'
import { DataCell, SourceBadge } from '../components/SourceBadge'
import { useThemeTokens } from '../components/themeTokens'
import { toast, Empty } from '../components/UI'

/**
 * V7.0 P0-2：对比口径
 * 后端 /analysis/compare 只返回 total_line / retest_line / enroll_count /
 * admit_count / admit_avg_score 五个字段，其中 retest_line 与 total_line 同值、
 * admit_count 为伪造列，故此处只对比 3 个可信指标。
 */
const COMPARE_COLUMNS = [
  { key: 'total_line', label: '进面最低分', from: 'score', badge: true },
  { key: 'enroll_count', label: '进面人数', from: 'adm', badge: true },
  { key: 'admit_avg_score', label: '进面均分', from: 'adm', badge: true },
]

export default function KaoyanCompare() {
  const [schools, setSchools] = useState([])
  const [result, setResult] = useState({ items: [] })
  const [loading, setLoading] = useState(false)
  // V7.0 P0-3：Canvas 图表需真实色值
  const T = useThemeTokens()

  const compareNow = () => {
    if (schools.length < 2) return
    setLoading(true)
    kaoyanApi.compare(schools.join(','))
      .then(setResult)
      .catch(() => toast('对比数据加载失败'))
      .finally(() => setLoading(false))
  }

  // 雷达图（V7.0 P0-2：指标口径改为审计确认的真实含义）
  const radarOption = result.items.length > 0 ? {
    tooltip: {},
    legend: { data: result.items.map(i => i.name), textStyle: { color: T['ink-2'] } },
    radar: {
      indicator: [
        { name: '进面最低分', max: 450 },
        { name: '进面人数', max: 500 },
        { name: '进面均分', max: 420 },
      ],
    },
    series: [{
      type: 'radar',
      data: result.items.map(i => {
        const score = i.recent_scores?.[0] || {}
        const adm = i.recent_admissions?.[0] || {}
        return {
          name: i.name,
          value: [score.total_line || 0, adm.enroll_count || 0, adm.admit_avg_score || 0],
        }
      }),
    }],
  } : null

  return (
    <div className="ky-page">
      <h1 style={{ marginBottom: '16px' }}>院校对比</h1>
      <p style={{ color: 'var(--ink-3)', marginBottom: '20px' }}>输入院校ID（逗号分隔），最多5所</p>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        <input
          value={schools.join(',')}
          onChange={e => setSchools(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
          placeholder="如: 1,2,3"
          style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', flex: 1 }}
        />
        <button onClick={compareNow} disabled={schools.length < 2}
          style={{
            padding: '8px 20px', borderRadius: '8px', border: 'none', cursor: 'pointer',
            background: schools.length >= 2 ? 'var(--accent)' : 'var(--surface-2)',
            // V7.0 P0-3：主色上的文字用 surface，明暗两套主题下均保持对比度
            color: schools.length >= 2 ? 'var(--surface)' : 'var(--ink-3)',
          }}>
          开始对比
        </button>
      </div>

      {loading && <div style={{padding:'48px',textAlign:'center'}}>对比中…</div>}

      {result.items.length > 0 && (
        <>
          {radarOption && <EChart option={radarOption} style={{ height: '400px', marginBottom: '20px' }} />}

          <div className="table-container">
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--line)' }}>
                <th style={{ padding: '10px', textAlign: 'left' }}>院校</th>
                <th style={{ padding: '10px' }}>层级</th>
                <th style={{ padding: '10px' }}>省份</th>
                <th style={{ padding: '10px' }}>年份</th>
                <th style={{ padding: '10px' }}>复试线</th>
                <th style={{ padding: '10px' }}>拟招</th>
                <th style={{ padding: '10px' }}>均分</th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((item) => {
                const score = item.recent_scores[0] || {}
                const adm = item.recent_admissions[0] || {}
                return (
                  <tr key={item.id} style={{ borderBottom: '1px solid var(--line)' }}>
                    <td style={{ padding: '10px', fontWeight: 600 }}>{item.name}</td>
                    <td style={{ padding: '10px' }}>{item.level}</td>
                    <td style={{ padding: '10px' }}>{item.province}</td>
                    <td style={{ padding: '10px' }}>{score.year || adm.year || '-'}</td>
                    <td style={{ padding: '10px' }}>{score.retest_line || '-'}</td>
                    <td style={{ padding: '10px' }}>{adm.enroll_count || '-'}</td>
                    <td style={{ padding: '10px' }}>{adm.admit_avg_score || '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          </div>
        </>
      )}
    </div>
  )
}
