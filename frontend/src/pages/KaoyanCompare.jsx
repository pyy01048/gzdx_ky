import React, { useState, useEffect, useMemo } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import EChart from '../components/EChart'
import { DataCell, SourceBadge } from '../components/SourceBadge'
import { useThemeTokens } from '../components/themeTokens'
import { toast, Empty } from '../components/UI'

/**
 * 院校对比
 * 选校方式（V8）：
 * 1. 优先从院校库「勾选 → 开始对比」跳转而来，选中 id 存在 localStorage['ky_compare_school_ids']；
 * 2. 本页也支持搜索院校名称添加、点击移除已选；
 * 3. 兼容旧入口：仍可用逗号分隔的院校 id 快速定位（兜底，不再作为主路径）。
 *
 * 对比口径：后端 /analysis/compare 仅返回 total_line / enroll_count / admit_avg_score
 * 三个可信指标（admit_count 为伪造列，不展示）。
 */
const COMPARE_COLUMNS = [
  { key: 'total_line', label: '进面最低分', from: 'score', badge: true },
  { key: 'enroll_count', label: '进面人数', from: 'adm', badge: true },
  { key: 'admit_avg_score', label: '进面均分', from: 'adm', badge: true },
]

const CMP_KEY = 'ky_compare_school_ids'
const MAX_CMP = 5

export default function KaoyanCompare() {
  const T = useThemeTokens()
  // selected: [{ id, name }]；id 为后端 school id，name 为展示名
  const [selected, setSelected] = useState(() => {
    try {
      const ids = JSON.parse(localStorage.getItem(CMP_KEY) || '[]')
      return (Array.isArray(ids) ? ids : []).map((id) => ({ id, name: '' }))
    } catch { return [] }
  })
  const [allSchools, setAllSchools] = useState([])   // 全量院校 { id, name } 用于 id→name 映射与搜索
  const [keyword, setKeyword] = useState('')          // 搜索框输入
  const [result, setResult] = useState({ items: [] })
  const [loading, setLoading] = useState(false)

  // 拉全量院校（仅用于名称回显 + 搜索候选），失败不阻断对比
  useEffect(() => {
    kaoyanApi.schools({ page_size: 1000 })
      .then((d) => {
        const list = (d?.items || d?.list || d || []).map((s) => ({ id: s.id, name: s.name }))
        setAllSchools(list)
      })
      .catch(() => {})
  }, [])

  // 名称回显：本地无 name 的 id，从 allSchools 补全
  const schoolName = (id) => {
    const s = allSchools.find((x) => String(x.id) === String(id))
    return s?.name || ''
  }
  const resolved = selected.map((s) => ({ id: s.id, name: s.name || schoolName(s.id) }))

  // 搜索候选（排除已选，按名称/拼音无关的简单包含匹配）
  const candidates = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return []
    return allSchools
      .filter((s) => (s.name || '').toLowerCase().includes(kw))
      .filter((s) => !selected.some((x) => String(x.id) === String(s.id)))
      .slice(0, 8)
  }, [keyword, allSchools, selected])

  const addSchool = (s) => {
    if (selected.length >= MAX_CMP) { toast(`最多对比 ${MAX_CMP} 所院校`); return }
    if (selected.some((x) => String(x.id) === String(s.id))) return
    setSelected((prev) => [...prev, { id: s.id, name: s.name }])
    setKeyword('')
  }
  const removeSchool = (id) => setSelected((prev) => prev.filter((x) => String(x.id) !== String(id)))

  // 从手输 id 兜底添加（旧入口）
  const addByIds = () => {
    const ids = keyword.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
    if (!ids.length) return
    ids.forEach((id) => {
      if (/^\d+$/.test(id)) addSchool({ id: Number(id), name: schoolName(id) })
    })
    setKeyword('')
  }

  const compareNow = () => {
    if (selected.length < 2) { toast('请至少选择 2 所院校'); return }
    setLoading(true)
    kaoyanApi.compare(selected.map((s) => s.id).join(','))
      .then(setResult)
      .catch(() => toast('对比数据加载失败'))
      .finally(() => setLoading(false))
  }

  // 雷达图（仅 3 个可信指标）
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
      <p style={{ color: 'var(--ink-3)', marginBottom: '20px' }}>
        从院校库勾选后跳转至此，或在此搜索添加院校（最多 {MAX_CMP} 所）
      </p>

      {/* 选校区 */}
      <div style={{ marginBottom: '20px' }}>
        {/* 已选 chips */}
        {resolved.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
            {resolved.map((s) => (
              <span key={s.id} style={{
                display: 'inline-flex', alignItems: 'center', gap: '6px',
                padding: '6px 12px', borderRadius: '999px', background: 'var(--accent-soft)',
                color: 'var(--accent)', fontSize: '13px', fontWeight: 600,
              }}>
                {s.name || `院校 #${s.id}`}
                <button onClick={() => removeSchool(s.id)} aria-label={`移除 ${s.name}`}
                  style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'inherit', fontSize: 16, lineHeight: 1, padding: 0 }}>
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {/* 搜索添加 */}
        <div style={{ position: 'relative', display: 'flex', gap: '8px' }}>
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索院校名称添加…"
            style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', flex: 1 }}
          />
          <button onClick={addByIds} disabled={!keyword.trim()}
            style={{
              padding: '8px 16px', borderRadius: '8px', border: 'none', cursor: keyword.trim() ? 'pointer' : 'default',
              background: keyword.trim() ? 'var(--surface-2)' : 'var(--surface-2)', color: keyword.trim() ? 'var(--ink-1)' : 'var(--ink-3)',
            }}>
            按 ID 添加
          </button>
        </div>

        {/* 搜索候选下拉 */}
        {candidates.length > 0 && (
          <div style={{
            position: 'absolute', zIndex: 20, marginTop: 4, width: '100%', maxWidth: 520,
            background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: '8px',
            boxShadow: '0 8px 24px rgba(0,0,0,0.08)', overflow: 'hidden',
          }}>
            {candidates.map((s) => (
              <button key={s.id} onClick={() => addSchool(s)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', padding: '10px 14px',
                  border: 'none', background: 'transparent', cursor: 'pointer',
                  fontSize: 14, color: 'var(--ink)', borderBottom: '1px solid var(--line)',
                }}>
                {s.name}
              </button>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        <button onClick={compareNow} disabled={selected.length < 2}
          style={{
            padding: '8px 20px', borderRadius: '8px', border: 'none', cursor: 'pointer',
            background: selected.length >= 2 ? 'var(--accent)' : 'var(--surface-2)',
            color: selected.length >= 2 ? 'var(--surface)' : 'var(--ink-3)',
          }}>
          开始对比（已选 {selected.length}）
        </button>
        {selected.length > 0 && (
          <button onClick={() => setSelected([])}
            style={{ padding: '8px 20px', borderRadius: '8px', border: '1px solid var(--line)', cursor: 'pointer', background: 'transparent', color: 'var(--ink-2)' }}>
            清空
          </button>
        )}
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
