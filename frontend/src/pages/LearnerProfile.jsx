import React, { useState, useEffect, useCallback } from 'react'
import { analysisApi } from '../api/client'
import EChart from '../components/EChart'
import { useThemeTokens } from '../components/themeTokens'
import { toast } from '../components/UI'

/* ============================================================
   学习画像（T7）：/api/analysis/profile 的可视化
   总览指标带 → 科目掌握度分级卡 → 薄弱知识点 → 复习队列健康度
   → 近30天活跃趋势图 → 行为洞察建议
   分级口径（后端规则）：危/弱/稳/强；建议为确定性规则生成，非 AI。
   ============================================================ */

const MASTERY_STYLE = {
  危: { bg: 'var(--red, #c0392b)18', color: 'var(--red, #c0392b)', desc: '正确率<50% 或错题积压>20' },
  弱: { bg: 'var(--gold)22', color: 'var(--gold)', desc: '正确率<65%' },
  稳: { bg: 'var(--accent)18', color: 'var(--accent)', desc: '正确率<80%' },
  强: { bg: 'var(--green)18', color: 'var(--green)', desc: '正确率≥80%' },
  未开始: { bg: 'var(--surface-3)', color: 'var(--ink-3)', desc: '暂无答题记录' },
}

export default function LearnerProfile() {
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const T = useThemeTokens()

  const load = useCallback(async () => {
    setLoading(true); setFailed(false)
    try {
      setProfile(await analysisApi.profile({ days: 30 }))
    } catch (e) {
      setFailed(true)
      toast(`画像加载失败：${e.message}`)
    }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="ky-page"><div style={{ padding: 48, textAlign: 'center', color: 'var(--ink-3)' }}>正在聚合学习数据…</div></div>
  if (failed || !profile) return (
    <div className="ky-page">
      <div style={{ padding: 48, textAlign: 'center' }}>
        <div style={{ marginBottom: 12 }}>画像加载失败（后端未启动？）</div>
        <button className="btn primary" onClick={load}>重试</button>
      </div>
    </div>
  )

  const { overview, subjects, weak_points: weakPoints, review_queue: reviewQueue, trend, suggestions } = profile

  // 趋势图（答题/正确/错题三序列）
  const trendOption = trend.length ? {
    tooltip: { trigger: 'axis' },
    legend: { data: ['答题', '答对', '新增错题'], textStyle: { color: T['ink-2'] } },
    xAxis: { type: 'category', data: trend.map(t => t.date.slice(5)), axisLabel: { color: T['ink-3'] } },
    yAxis: { type: 'value', axisLabel: { color: T['ink-3'] } },
    series: [
      { name: '答题', type: 'line', smooth: true, data: trend.map(t => t.answers), itemStyle: { color: T.accent } },
      { name: '答对', type: 'line', smooth: true, data: trend.map(t => t.correct), itemStyle: { color: T.green } },
      { name: '新增错题', type: 'bar', data: trend.map(t => t.errors), itemStyle: { color: T.red, opacity: 0.6 } },
    ],
  } : null

  const statCards = [
    { label: '累计答题', value: overview.total_answers },
    { label: '总正确率', value: overview.overall_accuracy != null ? `${overview.overall_accuracy}%` : '—' },
    { label: '学习天数', value: overview.study_days },
    { label: '错题存量', value: overview.error_stock },
    { label: '错题已解决', value: overview.error_resolved },
    { label: '模考次数', value: overview.exam_count },
    { label: '模考均分', value: overview.exam_avg_score != null ? overview.exam_avg_score : '—' },
  ]

  return (
    <div className="ky-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h1 style={{ margin: 0 }}>学习画像</h1>
        <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>
          基于答题/错题/模考真实行为聚合 · 生成于 {profile.generated_at}
        </span>
      </div>

      {/* 总览指标带 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 1, background: 'var(--line)', border: '1px solid var(--line)', borderRadius: 12, overflow: 'hidden', marginBottom: 18 }}>
        {statCards.map(s => (
          <div key={s.label} style={{ background: 'var(--surface)', padding: '14px 8px', textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{s.value}</div>
            <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 2 }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* 行为洞察建议 */}
      <div style={{ padding: '14px 18px', borderRadius: 12, background: 'var(--surface-2)', border: '1px dashed var(--accent)', marginBottom: 18 }}>
        <b style={{ fontSize: 14 }}>💡 行为洞察</b>
        <ul style={{ margin: '8px 0 0', paddingLeft: 20, fontSize: 13.5, lineHeight: 2, color: 'var(--ink-2)' }}>
          {suggestions.map((s, i) => <li key={i}>{s}</li>)}
        </ul>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
        {/* 科目掌握度 */}
        <section style={{ padding: 16, border: '1px solid var(--line)', borderRadius: 12, background: 'var(--surface)' }}>
          <h3 style={{ margin: '0 0 4px', fontSize: 15 }}>科目掌握度</h3>
          <p style={{ margin: '0 0 12px', fontSize: 12, color: 'var(--ink-3)' }}>
            危：正确率&lt;50%或错题积压&gt;20 · 弱：&lt;65% · 稳：&lt;80% · 强：≥80%
          </p>
          {subjects.length === 0 && <div style={{ color: 'var(--ink-3)', fontSize: 13 }}>暂无答题记录，先去刷几题吧</div>}
          {subjects.map(s => {
            const st = MASTERY_STYLE[s.mastery] || MASTERY_STYLE['未开始']
            return (
              <div key={s.subject} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 4px', borderBottom: '1px solid var(--line)' }}>
                <em style={{ fontStyle: 'normal', width: 42, textAlign: 'center', padding: '3px 0', borderRadius: 8, fontSize: 13, fontWeight: 700, background: st.bg, color: st.color }}>{s.mastery}</em>
                <span style={{ fontWeight: 600, fontSize: 13.5 }}>{s.subject}</span>
                <span style={{ marginLeft: 'auto', fontSize: 12.5, color: 'var(--ink-3)' }}>
                  正确率 {s.accuracy != null ? `${s.accuracy}%` : '—'} · 答题 {s.answered} · 错题积压 {s.error_stock}
                  {s.exam_avg != null ? ` · 模考 ${s.exam_avg}` : ''}
                </span>
              </div>
            )
          })}
        </section>

        {/* 复习队列健康度 + 薄弱知识点 */}
        <section style={{ padding: 16, border: '1px solid var(--line)', borderRadius: 12, background: 'var(--surface)' }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15 }}>复习队列（SM-2）</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
            {[
              { label: '已排期', v: reviewQueue.scheduled, c: 'var(--ink-1)' },
              { label: '今日到期', v: reviewQueue.due_today, c: 'var(--gold)' },
              { label: '已逾期', v: reviewQueue.overdue, c: 'var(--red, #c0392b)' },
              { label: '未排期', v: reviewQueue.no_schedule, c: 'var(--ink-3)' },
            ].map(x => (
              <div key={x.label} style={{ textAlign: 'center', padding: '10px 4px', borderRadius: 10, background: 'var(--surface-2)' }}>
                <div style={{ fontSize: 19, fontWeight: 700, color: x.c }}>{x.v}</div>
                <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{x.label}</div>
              </div>
            ))}
          </div>
          <h3 style={{ margin: '0 0 8px', fontSize: 15 }}>薄弱知识点 TOP</h3>
          {weakPoints.length === 0 && <div style={{ color: 'var(--ink-3)', fontSize: 13 }}>暂无错题关联（答错后自动归集）</div>}
          {weakPoints.map((w, i) => (
            <div key={`${w.knowledge_point}-${i}`} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 2px', fontSize: 13 }}>
              <span style={{ width: 20, color: 'var(--ink-3)', fontSize: 12 }}>{i + 1}</span>
              <span style={{ fontWeight: 600 }}>{w.knowledge_point}</span>
              {w.subject && <em style={{ fontStyle: 'normal', fontSize: 11, padding: '1px 8px', borderRadius: 999, background: 'var(--surface-3)', color: 'var(--ink-3)' }}>{w.subject}</em>}
              <span style={{ marginLeft: 'auto', color: 'var(--red, #c0392b)', fontWeight: 600 }}>错 {w.error_count}</span>
            </div>
          ))}
        </section>
      </div>

      {/* 趋势 */}
      {trendOption && (
        <section style={{ marginTop: 16, padding: 16, border: '1px solid var(--line)', borderRadius: 12, background: 'var(--surface)' }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15 }}>近 30 天活跃趋势</h3>
          <EChart option={trendOption} style={{ height: 280 }} />
        </section>
      )}
    </div>
  )
}
