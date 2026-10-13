import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../api/kaoyanApi'
import { qualityApi } from '../api/client'
import { Empty } from '../components/UI'

export default function KaoyanRecommend() {
  const [form, setForm] = useState({ score: 350, level: '', province: '', subject_code: '', target_avg_score: '', max_retest_ratio: 1.5, year: 2026 })
  const [results, setResults] = useState([])
  const [algorithm, setAlgorithm] = useState('')
  const [loading, setLoading] = useState(false)
  const [goalMsg, setGoalMsg] = useState('')
  const [hasSearched, setHasSearched] = useState(false)
  const [cov, setCov] = useState(null)   // 知识库语料覆盖（/api/quality/major-coverage）

  useEffect(() => {
    qualityApi.majorCoverage().then(setCov).catch(() => setCov(null))
  }, [])

  const run = () => {
    setLoading(true)
    setGoalMsg('')
    kaoyanApi.recommend(form)
      .then(r => { setResults(r.recommendations || []); setAlgorithm(r.algorithm || '') })
      .catch(() => { setResults([]); setAlgorithm('') })
      .finally(() => setLoading(false))
  }

  const setGoal = (schoolId, name) => {
    kaoyanApi.setGoal(schoolId, form.score)
      .then(() => setGoalMsg(`已将「${name}」设为目标院校（目标分 ${form.score}）`))
      .catch(() => setGoalMsg(`设置「${name}」失败，请稍后重试`))
  }

  const safetyColors = { '稳妥': '#16a34a', '适中': '#f59e0b', '冲刺': '#ef4444' }

  return (
    <div className="ky-page">
      <h1 style={{ marginBottom: '16px' }}>智能择校推荐</h1>
      <p style={{ color: 'var(--ink-3)', marginBottom: '20px' }}>输入预估分数和偏好，推荐适合的院校</p>

      {cov && cov.summary && (() => {
        const s = cov.summary
        return (
          <div style={{ padding: '10px 14px', marginBottom: '16px', borderRadius: '8px',
            background: 'var(--surface)', border: '1px solid var(--line)',
            fontSize: '13px', color: 'var(--ink-2)', lineHeight: 1.7 }}>
            <b>语料可靠度</b>：知识库覆盖 {s.majors_covered}/{s.majors_with_professional} 个专业的初试专业课
            （{(s.coverage_rate * 100).toFixed(1)}%）· 语料偏薄 {s.majors_thin} · 已归档未入库 {s.majors_unindexed} · 未覆盖 {s.majors_uncovered}。
            <div style={{ color: 'var(--ink-3)', fontSize: '12px' }}>
              覆盖口径＝专业课名与文档学科精确相等（公共课数学/英语/政治不参与）；未覆盖≠答不了，只是本库没有该科目语料。
              {s.supply_gaps && s.supply_gaps.length > 0 && (
                <> 供给缺口 TOP：{s.supply_gaps.slice(0, 6).map(g => `${g.subject}(${g.majors} 个专业)`).join('、')}</>
              )}
            </div>
          </div>
        )
      })()}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginBottom: '24px' }}>
        <div>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px' }}>预估总分</label>
          <input type="number" value={form.score} onChange={e => setForm({...form, score: +e.target.value})}
            style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', width: '100%' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px' }}>目标层级</label>
          <select value={form.level} onChange={e => setForm({...form, level: e.target.value})}
            style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', width: '100%' }}>
            <option value="">不限</option>
            <option value="985">985</option>
            <option value="211">211</option>
            <option value="双一流">双一流</option>
            <option value="双非">双非</option>
          </select>
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px' }}>目标省份</label>
          <input value={form.province} onChange={e => setForm({...form, province: e.target.value})}
            placeholder="如：四川省"
            style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', width: '100%' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px' }}>学科代码</label>
          <input value={form.subject_code} onChange={e => setForm({...form, subject_code: e.target.value})}
            placeholder="如：0808"
            style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', width: '100%' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px' }}>目标录取均分</label>
          <input type="number" value={form.target_avg_score} onChange={e => setForm({...form, target_avg_score: e.target.value})}
            placeholder="如：380"
            style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', width: '100%' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px' }}>最大复录比</label>
          <input type="number" step="0.1" value={form.max_retest_ratio} onChange={e => setForm({...form, max_retest_ratio: e.target.value})}
            style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', width: '100%' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px' }}>参考年份</label>
          <select value={form.year} onChange={e => setForm({...form, year: +e.target.value})}
            style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--line)', width: '100%' }}>
            {[2026, 2025, 2024, 2023].map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      </div>

      <button onClick={run} disabled={loading}
        style={{ padding: '10px 32px', borderRadius: '8px', border: 'none', cursor: 'pointer',
          background: 'var(--accent)', color: '#fff', fontSize: '16px' }}>
        {loading ? '推荐中…' : '开始推荐'}
      </button>

      {!loading && hasSearched && results.length === 0 && (
        <Empty title='暂无推荐结果' desc='调整分数或筛选条件后重试' />
      )}

      {results.length > 0 && (
        <div style={{ marginTop: '24px' }}>
          <h2 style={{ fontSize: '18px', marginBottom: '12px' }}>推荐结果（{results.length}所）</h2>
          {algorithm && (
            <div style={{ padding: '10px 14px', marginBottom: '12px', borderRadius: '8px',
              background: 'var(--surface)', border: '1px solid var(--line)', fontSize: '13px', color: 'var(--ink-2)' }}>
              算法：{algorithm}
            </div>
          )}
          {goalMsg && (
            <div style={{ padding: '10px 14px', marginBottom: '12px', borderRadius: '8px',
              background: '#dcfce7', border: '1px solid #86efac', fontSize: '13px', color: '#166534' }}>
              {goalMsg}
            </div>
          )}
          {results.map((r, i) => (
            <div key={i}
              style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '16px', marginBottom: '8px', borderRadius: '12px',
                background: 'var(--surface)', border: '1px solid var(--line)',
              }}>
              <div>
                <Link to={`/kaoyan/schools/${r.school_id}`} style={{ fontWeight: 600, marginRight: '12px', color: 'var(--ink)', textDecoration: 'none' }}>{r.name}</Link>
                <span style={{ fontSize: '13px', color: 'var(--ink-3)' }}>{r.level} · {r.province}</span>
                {r.kb_coverage && (
                  <div style={{ fontSize: '11px', marginTop: '2px',
                    color: r.kb_coverage.majors === 0 ? 'var(--ink-3)'
                      : r.kb_coverage.covered > 0 ? 'var(--green)' : 'var(--red)' }}>
                    {r.kb_coverage.majors === 0
                      ? '库内无该校专业方向数据'
                      : `语料覆盖 ${r.kb_coverage.covered}/${r.kb_coverage.majors} 个专业`
                        + (r.kb_coverage.uncovered ? ` · 未覆盖 ${r.kb_coverage.uncovered}` : '')}
                  </div>
                )}
                {r.score_breakdown && (
                  <div style={{ fontSize: '11px', color: 'var(--ink-3)', marginTop: '4px' }}>
                    权重明细：分差 {r.score_breakdown.gap} · 复录比 {r.score_breakdown.retest_ratio} · 均分 {r.score_breakdown.admit_avg} · 区域 {r.score_breakdown.region} · 学科 {r.score_breakdown.subject}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '13px', color: 'var(--ink-3)' }}>分差 +{r.gap}</div>
                  {r.retest_ratio && <div style={{ fontSize: '11px', color: 'var(--ink-3)' }}>复录比 {r.retest_ratio}</div>}
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--accent)' }}>{r.score}</div>
                  <div style={{ fontSize: '10px', color: 'var(--ink-3)' }}>综合评分</div>
                </div>
                <span style={{
                  padding: '4px 12px', borderRadius: '4px', fontSize: '13px',
                  background: safetyColors[r.safety] || 'var(--surface-2)',
                  color: '#fff',
                }}>{r.safety}</span>
                <button
                  onClick={() => setGoal(r.school_id, r.name)}
                  style={{
                    padding: '6px 12px', borderRadius: '6px', border: '1px solid var(--accent)',
                    background: 'transparent', color: 'var(--accent)', cursor: 'pointer', fontSize: '13px',
                  }}>
                  设为目标院校
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <AutoAdjustPanel form={form} />
    </div>
  )
}

/* ---------- V10: 自动调整面板（冲/稳/保 三档 + 数据化理由） ---------- */
function AutoAdjustPanel({ form }) {
  const [adj, setAdj] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = () => {
    setLoading(true)
    setErr('')
    kaoyanApi.autoAdjust({
      user_score: form.score,
      subject_code: form.subject_code || undefined,
      province: form.province || undefined,
      level: form.level || undefined,
    })
      .then(setAdj)
      .catch(e => setErr(e?.message || '自动调整失败，请稍后重试'))
      .finally(() => setLoading(false))
  }

  const buckets = [
    { key: 'rush', title: '冲刺', icon: '🚀', color: '#ef4444', desc: '分差 35~5 分，需要超常发挥' },
    { key: 'stable', title: '稳妥', icon: '🛡️', color: '#f59e0b', desc: '分差 ±15 分，匹配度最高' },
    { key: 'safe', title: '保底', icon: '🌱', color: '#16a34a', desc: '高出均分 15 分以上，胜算大' },
  ]

  return (
    <div style={{ marginTop: '36px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
        <div>
          <h2 style={{ fontSize: '20px', margin: '0 0 4px' }}>⚡ 一键自动调整</h2>
          <p style={{ margin: 0, fontSize: '13px', color: 'var(--ink-3)' }}>
            基于近3年录取均分自动分「冲 / 稳 / 保」三档，附数据化理由（分数变化后点一下即可重新分档）
          </p>
        </div>
        <button onClick={run} disabled={loading}
          style={{
            padding: '11px 28px', borderRadius: '10px', border: 'none', cursor: 'pointer', fontSize: '15px', fontWeight: 600,
            background: 'linear-gradient(135deg, #3A6FB8, #2B5A9E)', color: '#fff',
            boxShadow: '0 6px 18px -6px rgba(43,90,158,.5)',
          }}>
          {loading ? '调整中…' : `按 ${form.score} 分自动调整`}
        </button>
      </div>

      {err && (
        <div style={{ padding: '10px 14px', borderRadius: '8px', background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b', fontSize: '13px' }}>{err}</div>
      )}

      {adj && (
        <>
          <div style={{ padding: '10px 14px', marginBottom: '14px', borderRadius: '10px', background: 'var(--surface)', border: '1px solid var(--line)', fontSize: '12px', color: 'var(--ink-2)' }}>
            {adj.method} · 覆盖院校 {adj.coverage?.total || 0} 所（有近3年录取均分数据的）
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
            {buckets.map(b => {
              const items = adj.buckets?.[b.key] || []
              return (
                <div key={b.key} style={{
                  borderRadius: '16px', background: 'var(--surface)', border: '1px solid var(--line)',
                  borderTop: `3px solid ${b.color}`, padding: '16px', minHeight: '160px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginBottom: '4px' }}>
                    <span style={{ fontSize: '16px', fontWeight: 700 }}>{b.icon} {b.title}</span>
                    <span style={{ fontSize: '12px', color: 'var(--ink-3)' }}>{items.length} 所</span>
                  </div>
                  <p style={{ margin: '0 0 12px', fontSize: '12px', color: 'var(--ink-3)' }}>{b.desc}</p>
                  {items.length === 0 && <p style={{ fontSize: '13px', color: 'var(--ink-3)' }}>暂无匹配院校</p>}
                  {items.map(s => (
                    <div key={s.school_id} style={{
                      padding: '10px 12px', marginBottom: '8px', borderRadius: '10px',
                      background: 'var(--surface-2, rgba(0,0,0,0.03))',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                        <Link to={`/kaoyan/schools/${s.school_id}`} style={{ fontWeight: 600, color: 'var(--ink)', textDecoration: 'none', fontSize: '14px' }}>{s.school_name}</Link>
                        <span style={{ fontSize: '12px', color: 'var(--ink-3)', whiteSpace: 'nowrap' }}>均分 {s.avg3}</span>
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--ink-3)', marginTop: '2px' }}>
                        {s.level || '—'} · {s.province || '—'} · 分差 {s.gap > 0 ? '+' : ''}{s.gap} · 信心 {Math.round(s.confidence * 100)}%
                      </div>
                      {s.reasons?.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '6px' }}>
                          {s.reasons.map((r, i) => (
                            <span key={i} style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '999px', background: 'var(--accent-soft, rgba(43,90,158,.1))', color: 'var(--accent)' }}>{r}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
