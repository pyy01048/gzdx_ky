import React, { useState, useEffect } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import { toast, Empty } from '../components/UI'

export default function GrowthPage() {
  const [summary, setSummary] = useState(null)
  const [badges, setBadges] = useState([])
  const [achievements, setAchievements] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      kaoyanApi.growthSummary(),
      kaoyanApi.growthBadges(),
      kaoyanApi.growthAchievements(),
    ])
      .then(([s, b, a]) => { setSummary(s); setBadges(b.badges || []); setAchievements(a.achievements || []) })
      .catch(() => toast('成长数据加载失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={{ padding: '48px', textAlign: 'center' }}>加载中…</div>
  if (!summary) return <Empty title='成长数据加载失败' desc='请检查后端连接后刷新页面' />

  const lv = summary.level
  const stats = summary.stats || {}

  return (
    <div className="ky-page">
      <h1 style={{ marginBottom: '8px' }}>成长体系</h1>
      <p style={{ color: 'var(--ink-3)', marginBottom: '24px' }}>
        等级 · 积分 · 徽章 · 成就 —— 基于学习行为事件自动计算
      </p>

      {/* 等级总览 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
        <div style={{ background: 'var(--surface)', borderRadius: '12px', padding: '20px', border: '1px solid var(--line)' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>当前等级</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--accent)', marginTop: '4px' }}>Lv.{lv.level}</div>
          <div style={{ fontSize: '16px', fontWeight: 600 }}>{lv.name}</div>
          <div style={{ height: '8px', borderRadius: '4px', background: 'var(--line)', marginTop: '12px', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${lv.progress}%`, background: 'var(--accent)', borderRadius: '4px' }} />
          </div>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)', marginTop: '6px' }}>
            {lv.next ? `距 ${lv.next.name}（${lv.next.threshold} 分）还差 ${lv.next.threshold - lv.points} 分` : '已达满级'}
          </div>
        </div>
        <div style={{ background: 'var(--surface)', borderRadius: '12px', padding: '20px', border: '1px solid var(--line)' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>累计积分</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--accent)', marginTop: '4px' }}>{lv.points}</div>
          <div style={{ fontSize: '13px', color: 'var(--ink-3)', marginTop: '8px' }}>答题 {stats.answer_total} · 答对 {stats.answer_correct} · 交卷 {stats.submit_total}</div>
          <div style={{ fontSize: '13px', color: 'var(--ink-3)', marginTop: '4px' }}>复习 {stats.review_total} · 学习 {Math.floor((stats.study_seconds || 0) / 60)} 分钟 · 活跃 {stats.active_days} 天</div>
        </div>
        <div style={{ background: 'var(--surface)', borderRadius: '12px', padding: '20px', border: '1px solid var(--line)' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>徽章</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--accent)', marginTop: '4px' }}>{summary.badge_count}/{badges.length}</div>
          <div style={{ fontSize: '13px', color: 'var(--ink-3)', marginTop: '8px' }}>已解锁徽章数量</div>
        </div>
        <div style={{ background: 'var(--surface)', borderRadius: '12px', padding: '20px', border: '1px solid var(--line)' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>成就</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--accent)', marginTop: '4px' }}>{summary.achievement_count}/{achievements.length}</div>
          <div style={{ fontSize: '13px', color: 'var(--ink-3)', marginTop: '8px' }}>已达成成就数量</div>
        </div>
      </div>

      {/* 积分明细 */}
      <h2 style={{ fontSize: '20px', marginBottom: '12px' }}>积分构成</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '28px' }}>
        {(summary.points_detail || []).map((d) => (
          <div key={d.source} style={{ background: 'var(--surface)', borderRadius: '12px', padding: '14px', border: '1px solid var(--line)' }}>
            <div style={{ fontSize: '13px', color: 'var(--ink-3)' }}>{d.source} × {d.count}</div>
            <div style={{ fontSize: '20px', fontWeight: 600, marginTop: '4px' }}>+{d.points}</div>
          </div>
        ))}
      </div>

      {/* 徽章墙 */}
      <h2 style={{ fontSize: '20px', marginBottom: '12px' }}>徽章墙</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '12px', marginBottom: '28px' }}>
        {badges.map((b) => (
          <div key={b.code} style={{
            background: 'var(--surface)', borderRadius: '12px', padding: '16px', textAlign: 'center',
            border: '1px solid var(--line)', opacity: b.earned ? 1 : 0.42,
          }}>
            <div style={{
              width: '56px', height: '56px', margin: '0 auto 8px', borderRadius: '50%', display: 'flex',
              alignItems: 'center', justifyContent: 'center', fontSize: '20px', fontWeight: 700,
              background: b.earned ? 'var(--accent)' : 'var(--line)', color: b.earned ? '#fff' : 'var(--ink-3)',
            }}>{b.icon}</div>
            <div style={{ fontSize: '14px', fontWeight: 600 }}>{b.name}</div>
            <div style={{ fontSize: '11px', color: 'var(--ink-3)', marginTop: '4px' }}>{b.desc}</div>
          </div>
        ))}
      </div>

      {/* 成就列表 */}
      <h2 style={{ fontSize: '20px', marginBottom: '12px' }}>成就</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
        {achievements.map((a) => (
          <div key={a.code} style={{
            background: 'var(--surface)', borderRadius: '12px', padding: '14px', border: '1px solid var(--line)',
            opacity: a.earned ? 1 : 0.5,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '15px', fontWeight: 600 }}>{a.earned ? '🏅 ' : '🔒 '}{a.name}</span>
              <span style={{ fontSize: '12px', padding: '2px 8px', borderRadius: '12px', background: a.earned ? 'color-mix(in srgb, var(--accent) 15%, transparent)' : 'var(--line)', color: a.earned ? 'var(--accent)' : 'var(--ink-3)' }}>
                {a.earned ? '已达成' : '未达成'}
              </span>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--ink-3)', marginTop: '6px' }}>{a.desc}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
