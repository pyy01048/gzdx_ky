import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../api/kaoyanApi'
import { toast, Empty } from '../components/UI'

export default function KaoyanGuide() {
  const [stats, setStats] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([kaoyanApi.stats(), kaoyanApi.subjects()])
      .then(([s, sub]) => { setStats(s); setSubjects(sub) })
      .catch(() => toast('数据加载失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={{padding:'48px',textAlign:'center'}}>加载中…</div>
  if (!stats) return <Empty title='数据加载失败' desc='请检查后端连接后刷新页面' />

  return (
    <div className="ky-page">
      <h1 style={{ marginBottom: '8px' }}>考研择校数据中心</h1>
      <p style={{ color: 'var(--ink-3)', marginBottom: '24px' }}>
        多年份 · 多学科 · 院校对比 · 分数趋势 · 智能推荐
      </p>

      {/* 统计概览 */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px', marginBottom: '32px' }}>
          {[
            { label: '院校数', value: stats.school_count || 0 },
            { label: '专业方向', value: stats.major_count || 0 },
            { label: '招生记录', value: stats.admission_records || 0 },
            { label: '分数线记录', value: stats.scoreline_records || 0 },
            { label: '学科覆盖', value: stats.subject_count || 0 },
          ].map((s) => (
            <div key={s.label} style={{
              background: 'var(--surface)', borderRadius: '12px', padding: '20px',
              border: '1px solid var(--line)', textAlign: 'center',
            }}>
              <div style={{ fontSize: '32px', fontWeight: 700, color: 'var(--accent)' }}>{s.value}</div>
              <div style={{ fontSize: '14px', color: 'var(--ink-3)', marginTop: '4px' }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* 学科入口 */}
      <h2 style={{ fontSize: '20px', marginBottom: '16px' }}>学科方向</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px', marginBottom: '32px' }}>
        {subjects.map((s) => (
          <Link key={s.code} to={`/kaoyan/schools?subject=${s.code}`}
            style={{
              display: 'block', padding: '16px', borderRadius: '12px',
              background: 'var(--surface)', border: '1px solid var(--line)',
              textDecoration: 'none', color: 'var(--ink)',
            }}>
            <div style={{ fontSize: '16px', fontWeight: 600 }}>{s.name}</div>
            <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>代码 {s.code} · {s.category}</div>
            {s.exam_overlap && (
              <div style={{ fontSize: '11px', color: 'var(--ink-3)', marginTop: '8px' }}>
                考试科目：{s.exam_overlap}
              </div>
            )}
          </Link>
        ))}
      </div>

      {/* 功能入口 */}
      <h2 style={{ fontSize: '20px', marginBottom: '16px' }}>分析工具</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
        {[
          { to: '/kaoyan/schools', label: '院校数据库', desc: '全国院校多维度筛选' },
          { to: '/kaoyan/compare', label: '院校对比', desc: '最多 5 所院校横向对比' },
          { to: '/kaoyan/analysis', label: '分数分析', desc: '多年分数线趋势' },
          { to: '/kaoyan/map', label: '区域热力图', desc: '全国各省院校分布' },
          { to: '/kaoyan/scatter', label: '招生散点图', desc: '招生人数 vs 录取均分' },
          { to: '/kaoyan/recommend', label: '智能择校', desc: '多维权重推荐（复录比 / 均分 / 区域）' },
          { to: '/kaoyan/import', label: '数据管理', desc: '数据导入与来源管理' },
        ].map((item) => (
          <Link key={item.to} to={item.to}
            style={{
              display: 'block', padding: '20px', borderRadius: '12px',
              background: 'var(--surface)', border: '1px solid var(--line)',
              textDecoration: 'none', color: 'var(--ink)',
            }}>
            <div style={{ fontSize: '18px', fontWeight: 600 }}>{item.label}</div>
            <div style={{ fontSize: '13px', color: 'var(--ink-3)', marginTop: '4px' }}>{item.desc}</div>
          </Link>
        ))}
      </div>

      <div style={{ marginTop: '48px', padding: '16px', textAlign: 'center', color: 'var(--ink-3)', fontSize: '13px' }}>
        个人考研学习平台 · 数据仅供参考
      </div>
    </div>
  )
}
