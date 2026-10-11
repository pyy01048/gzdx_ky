import React, { useState, useEffect, useCallback } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import { toast, Empty } from '../components/UI'

/* ============================================================
   数据管理 / 采集中心（T5 重做）
   - 定向采集（工科代码集：电子/通信/408/光学/电气/AI）
   - 国家线回填（官方核实静态数据）
   - 公告采集（各校研究生院官网列表页）
   - 采集历史（kaoyan_collection_runs）
   - 周期任务说明（每周一 06:00 自动跑轻量增量）
   旧版"请在服务器执行命令"的提示卡全部替换为页面内一键操作。
   ============================================================ */

const COLLECT_SOURCES = [
  {
    key: 'engineering', label: '工科定向采集', icon: '🎯',
    desc: '研招网 07/08 门类院校增量 + 电子/通信/408/光学/电气/AI 专业代码集过滤（耗时较长，2-5s/页 礼貌延迟）',
  },
  {
    key: 'national_line', label: '国家线回填', icon: '📐',
    desc: '官方核实的历年国家线（A区 工学/电子信息）回填 kaoyan_scorelines，补齐「超国家线差值」标注的数据底座',
  },
  {
    key: 'notices', label: '公告采集', icon: '📰',
    desc: '各校研究生院官网公告列表页（招生公告/简章/复试/调剂/录取），robots 允许的站点才采集',
  },
]

export default function KaoyanImport() {
  const [stats, setStats] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [noticeStats, setNoticeStats] = useState(null)
  const [runs, setRuns] = useState([])
  const [busy, setBusy] = useState('')   // 正在采集的 source key
  const [lastResult, setLastResult] = useState(null)

  const refresh = useCallback(() => {
    kaoyanApi.stats().then(setStats).catch(() => toast('统计数据加载失败'))
    kaoyanApi.subjects().then(setSubjects).catch(() => {})
    kaoyanApi.noticeTypeStats().then(setNoticeStats).catch(() => setNoticeStats(null))
    // 采集历史
    kaoyanApi.collectionRuns?.().then((d) => setRuns(d?.runs || d?.items || [])).catch(() => {})
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const runCollect = async (source) => {
    if (busy) return
    setBusy(source)
    setLastResult(null)
    try {
      const r = await kaoyanApi.refresh({ source, dry_run: false })
      setLastResult({ source, ok: true, data: r })
      toast(`${source} 采集完成`)
      refresh()
    } catch (e) {
      setLastResult({ source, ok: false, error: e.message })
      toast(`采集失败：${e.message}`)
    }
    setBusy('')
  }

  return (
    <div className="ky-page">
      <h1 style={{ marginBottom: '16px' }}>数据管理 · 采集中心</h1>

      {/* 数据概览 */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px', marginBottom: '24px' }}>
          {[
            { label: '院校', value: stats.school_count },
            { label: '专业', value: stats.major_count },
            { label: '招生记录', value: stats.admission_records },
            { label: '分数线记录', value: stats.scoreline_records },
            { label: '公告', value: noticeStats?.total ?? '—' },
          ].map(s => (
            <div key={s.label} style={{ padding: '16px', borderRadius: '12px', background: 'var(--surface)', border: '1px solid var(--line)', textAlign: 'center' }}>
              <div style={{ fontSize: '24px', fontWeight: 700 }}>{s.value}</div>
              <div style={{ fontSize: '12px', color: 'var(--ink-3)' }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* 公告类型分布 */}
      {noticeStats && noticeStats.total > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h2 style={{ fontSize: '16px', marginBottom: 8 }}>公告类型分布</h2>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(noticeStats.by_type).map(([t, n]) => (
              <span key={t} style={{ padding: '4px 12px', borderRadius: 999, fontSize: 13, background: 'var(--surface-2)' }}>{t} {n}</span>
            ))}
          </div>
        </div>
      )}

      {/* 采集操作 */}
      <h2 style={{ fontSize: '18px', marginBottom: '12px' }}>定向采集</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px', marginBottom: 20 }}>
        {COLLECT_SOURCES.map(s => (
          <div key={s.key} style={{ padding: '16px', borderRadius: 12, background: 'var(--surface)', border: '1px solid var(--line)' }}>
            <h3 style={{ marginBottom: 6 }}>{s.icon} {s.label}</h3>
            <p style={{ fontSize: 12.5, color: 'var(--ink-3)', lineHeight: 1.6, minHeight: 44 }}>{s.desc}</p>
            <button
              disabled={!!busy}
              onClick={() => runCollect(s.key)}
              style={{
                padding: '8px 20px', borderRadius: 8, border: 'none', cursor: busy ? 'wait' : 'pointer',
                background: busy === s.key ? 'var(--surface-3)' : 'var(--accent)',
                color: busy === s.key ? 'var(--ink-2)' : '#fff', fontSize: 13,
              }}>
              {busy === s.key ? '采集中…' : '立即采集'}
            </button>
          </div>
        ))}
      </div>

      {/* 最近一次结果 */}
      {lastResult && (
        <div style={{
          padding: '12px 16px', borderRadius: 10, marginBottom: 20,
          background: 'var(--surface-2)', border: `1px solid ${lastResult.ok ? 'var(--green)' : 'var(--red, #c0392b)'}33`,
          fontSize: 13, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto',
        }}>
          <b>{lastResult.ok ? '✓ 采集结果' : '✗ 采集失败'}</b>
          {lastResult.ok
            ? '\n' + JSON.stringify(lastResult.data?.results?.[0] || lastResult.data, null, 2).slice(0, 1500)
            : `\n${lastResult.error}`}
        </div>
      )}

      {/* 周期任务说明 */}
      <div style={{ padding: '14px 16px', borderRadius: 10, background: 'var(--surface-2)', border: '1px dashed var(--line)', marginBottom: 20, fontSize: 13, color: 'var(--ink-3)', lineHeight: 1.7 }}>
        ⏰ <b>周期任务</b>：每周一 06:00 自动执行轻量增量（国家线新年份回填 + 公告列表前 10 所）。
        工科研招网全量爬取不进周期任务（耗时长），需要时点上方「工科定向采集」手动触发。
        全部采集遵守 robots.txt 与 2-5s 随机延迟。
      </div>

      {/* 已覆盖学科 */}
      <h2 style={{ fontSize: '18px', marginBottom: '12px' }}>已覆盖学科</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '24px' }}>
        {subjects.map(s => (
          <span key={s.code} style={{ padding: '4px 12px', borderRadius: '4px', fontSize: '13px', background: 'var(--surface-2)' }}>
            {s.name} ({s.code})
          </span>
        ))}
      </div>

      {/* 采集历史 */}
      <h2 style={{ fontSize: '18px', marginBottom: '12px' }}>采集历史</h2>
      {runs.length === 0 ? (
        <Empty icon="📡" title="暂无采集记录" desc="上方触发一次采集后，历史会记录在这里（含每周自动任务）" />
      ) : (
        <div className="table-container">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--line)', textAlign: 'left' }}>
                <th style={{ padding: 8 }}>时间</th>
                <th style={{ padding: 8 }}>来源</th>
                <th style={{ padding: 8 }}>范围</th>
                <th style={{ padding: 8 }}>行数</th>
                <th style={{ padding: 8 }}>状态</th>
              </tr>
            </thead>
            <tbody>
              {runs.slice(0, 20).map((r) => (
                <tr key={r.id} style={{ borderBottom: '1px solid var(--line)' }}>
                  <td style={{ padding: 8, color: 'var(--ink-3)' }}>{String(r.created_at || '').slice(0, 19)}</td>
                  <td style={{ padding: 8 }}>{r.source}</td>
                  <td style={{ padding: 8, color: 'var(--ink-3)' }}>{r.scope || '—'}</td>
                  <td style={{ padding: 8 }}>{r.row_count ?? '—'}</td>
                  <td style={{ padding: 8 }}>
                    <em style={{ fontStyle: 'normal', padding: '1px 10px', borderRadius: 999, fontSize: 12,
                      background: r.status === 'success' ? 'var(--green)22' : 'var(--surface-3)', color: 'var(--ink-2)' }}>
                      {r.status}
                    </em>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
