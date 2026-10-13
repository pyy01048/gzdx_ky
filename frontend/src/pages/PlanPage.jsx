import React, { useState, useEffect } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import { toast, Empty } from '../components/UI'

const STAGE_COLORS = {
  '基础': 'var(--accent)',
  '强化': '#e6a23c',
  '冲刺': '#f56c6c',
}

const CAT_ORDER = ['招生', '大纲', '报名', '确认', '命题', '准考证', '初试', '阅卷', '查分', '院校线', '国家线', '复试', '调剂', '体检', '政审', '录取']

export default function PlanPage() {
  const [year, setYear] = useState(2027)
  const [roadmap, setRoadmap] = useState(null)
  const [milestones, setMilestones] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([kaoyanApi.roadmap(year), kaoyanApi.milestones(year)])
      .then(([rm, ms]) => { setRoadmap(rm); setMilestones(ms) })
      .catch(() => toast('规划数据加载失败'))
      .finally(() => setLoading(false))
  }, [year])

  const regenerate = () => {
    kaoyanApi.generatePlan(year).then(() =>
      Promise.all([kaoyanApi.roadmap(year), kaoyanApi.milestones(year)])
        .then(([rm, ms]) => { setRoadmap(rm); setMilestones(ms) })
    )
  }

  if (loading) return <div style={{ padding: '48px', textAlign: 'center' }}>加载中…</div>
  if (!roadmap) return <Empty title='规划数据加载失败' desc='请检查后端连接后刷新页面' />

  const goal = roadmap.goal || {}
  const exam = roadmap.exam_date

  return (
    <div className="ky-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '8px' }}>
        <h1 style={{ marginBottom: '0' }}>考研规划</h1>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}
            style={{ padding: '6px 12px', borderRadius: '8px', border: '1px solid var(--line)', background: 'var(--surface)' }}>
            {[2026, 2027, 2028].map((y) => <option key={y} value={y}>{y} 考研</option>)}
          </select>
          <button onClick={regenerate} style={{ padding: '6px 14px', borderRadius: '8px', border: '1px solid var(--line)', background: 'var(--surface)', cursor: 'pointer' }}>
            重新生成节点
          </button>
        </div>
      </div>
      <p style={{ color: 'var(--ink-3)', marginBottom: '24px' }}>
        阶段 → 月 → 周 → 日 三层规划 · 与择校目标联动
      </p>

      {/* 目标概览 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px', marginBottom: '28px' }}>
        <div style={{ background: 'var(--surface)', borderRadius: '12px', padding: '18px', border: '1px solid var(--line)' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>目标院校</div>
          <div style={{ fontSize: '18px', fontWeight: 600, marginTop: '4px' }}>{goal.university || '未设置'}</div>
          {goal.major && <div style={{ fontSize: '13px', color: 'var(--ink-3)' }}>{goal.major}</div>}
        </div>
        <div style={{ background: 'var(--surface)', borderRadius: '12px', padding: '18px', border: '1px solid var(--line)' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>总分目标</div>
          <div style={{ fontSize: '18px', fontWeight: 600, marginTop: '4px' }}>{goal.total_score_target ? `${goal.total_score_target} 分` : '未设置'}</div>
        </div>
        <div style={{ background: 'var(--surface)', borderRadius: '12px', padding: '18px', border: '1px solid var(--line)' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>初试日期</div>
          <div style={{ fontSize: '18px', fontWeight: 600, marginTop: '4px' }}>{exam}</div>
        </div>
        <div style={{ background: 'var(--surface)', borderRadius: '12px', padding: '18px', border: '1px solid var(--line)', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>距初试</div>
          <div style={{ fontSize: '32px', fontWeight: 700, color: roadmap.days_to_exam <= 90 ? 'var(--danger, #f56c6c)' : 'var(--accent)' }}>
            {roadmap.days_to_exam} 天
          </div>
        </div>
      </div>

      {/* 阶段 → 月 → 周 → 日 */}
      <h2 style={{ fontSize: '20px', marginBottom: '16px' }}>阶段 · 月 · 周 · 日 三层规划</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '32px' }}>
        {roadmap.stages.map((s) => (
          <div key={s.name} style={{ border: '1px solid var(--line)', borderRadius: '12px', overflow: 'hidden', background: 'var(--surface)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '14px 18px', background: 'color-mix(in srgb, var(--surface) 60%, transparent)' }}>
              <span style={{ padding: '4px 12px', borderRadius: '20px', fontSize: '13px', fontWeight: 600, color: '#fff', background: STAGE_COLORS[s.name] || 'var(--accent)' }}>{s.name}</span>
              <span style={{ fontSize: '13px', color: 'var(--ink-3)' }}>{s.start} ~ {s.end}</span>
              <span style={{ flex: 1, fontSize: '13px', color: 'var(--ink-2)' }}>{s.goal}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '10px', padding: '14px 18px' }}>
              {s.months.map((m) => (
                <div key={m.month} style={{ border: '1px solid var(--line)', borderRadius: '12px', padding: '12px' }}>
                  <div style={{ fontSize: '14px', fontWeight: 600, marginBottom: '6px' }}>{m.label}</div>
                  <div style={{ fontSize: '12px', color: 'var(--ink-3)', marginBottom: '8px' }}>{m.start} ~ {m.end}</div>
                  <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '12px', color: 'var(--ink-2)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {m.weeks.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                  <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px dashed var(--line)', fontSize: '12px', color: 'var(--accent)' }}>
                    {s.daily_routine}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* 关键节点时间线（数量随后端里程碑数据动态变化） */}
      <h2 style={{ fontSize: '20px', marginBottom: '16px' }}>关键节点（{(milestones?.milestones || []).length} 个）</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '12px' }}>
        {[...(milestones?.milestones || [])].sort((a, b) => (a.start || '').localeCompare(b.start || '')).map((n) => {
          const stage = roadmap.stages.find((s) => s.name === n.stage)
          return (
            <div key={n.id} style={{ border: '1px solid var(--line)', borderRadius: '12px', padding: '14px', background: 'var(--surface)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{ fontSize: '15px', fontWeight: 600 }}>{n.name}</span>
                <span style={{ fontSize: '12px', padding: '2px 8px', borderRadius: '12px', background: 'color-mix(in srgb, ' + (STAGE_COLORS[stage?.name] || 'var(--accent)') + ' 18%, transparent)', color: STAGE_COLORS[stage?.name] || 'var(--accent)' }}>
                  {stage?.name || n.stage}
                </span>
              </div>
              <div style={{ fontSize: '12px', color: 'var(--ink-3)', marginBottom: '6px' }}>
                {n.category} · {n.start} ~ {n.end}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--ink-2)', marginBottom: '6px' }}>
                <b>行动：</b>{n.action}
              </div>
              <div style={{ fontSize: '12px', color: n.days_left < 0 ? '#f56c6c' : 'var(--ink-3)' }}>
                {n.days_left >= 0 ? `还有 ${n.days_left} 天` : `已过 ${-n.days_left} 天`} · 重要度 {n.importance}/5
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
