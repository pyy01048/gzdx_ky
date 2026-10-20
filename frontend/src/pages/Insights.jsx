import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw, Activity } from '../components/Icon'
import { toastOk, toastErr } from '../components/UI'
import EChart from '../components/EChart'
import { LoadingState, ErrorState, EmptyState } from '../components/States'
import { statsApi } from '../api/client'
import { chartFor } from '../styles/tokens'
import StudyHeatmap from '../components/StudyHeatmap'

/* 图表主题跟随 data-theme（与 tokens.css 暗色令牌同源） */
function useChartTheme() {
  const read = () => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')
  const [mode, setMode] = useState(read)
  useEffect(() => {
    const obs = new MutationObserver(() => setMode(read()))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  return mode
}

const CARD = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--card-radius)',
  boxShadow: 'var(--shadow-sm)',
  padding: 'var(--space-5)',
}

export default function Insights() {
  const mode = useChartTheme()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await statsApi.overview())
      return true
    } catch (e) {
      setError(e?.message || '加载失败')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  /* 手动刷新：成功/失败都有提示，避免用户不知道统计有没有更新 */
  const refresh = async () => {
    const ok = await load()
    if (ok) toastOk('统计数据已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  const pageHead = (
    <div className="page-head">
      <div>
        <h2 className="page-title" style={{ margin: 0 }}>学习统计</h2>
        <p className="page-sub">科目正确率 · 答题趋势 · 错题标签 · 学习时长</p>
      </div>
      <button className="btn outline" onClick={refresh} disabled={loading}>
        <RefreshCw size={14} /> 刷新
      </button>
    </div>
  )

  if (loading) return <div className="stack" style={{ gap: 'var(--space-5)' }}>{pageHead}<LoadingState text='统计聚合加载中…' rows={6} /></div>
  if (error) return <div className="stack" style={{ gap: 'var(--space-5)' }}>{pageHead}<ErrorState message={error} onRetry={load} /></div>

  const subjects = data?.subjects || []
  const trendMap = data?.trend_7d || {}
  const trend = Object.entries(trendMap).map(([date, v]) => ({ date: date.slice(5), ...v }))
  const tags = data?.top_error_tags || []
  const studyTime = data?.study_time || []
  const hasAny = subjects.length || trend.some((t) => t.answered) || tags.length || studyTime.length

  if (!hasAny) {
    return (
      <div className="stack" style={{ gap: 'var(--space-5)' }}>
        {pageHead}
        <StudyHeatmap />
        <div className="card">
          <EmptyState
            title='还没有学习数据'
            desc='完成几次刷题或学习打卡后，这里会汇总科目正确率、答题趋势、错题标签与学习时长分布。'
            action={(
              <div className="row">
                <a className="btn primary" href="#/quiz">去刷题</a>
                <a className="btn ghost" href="#/tasks">去打卡</a>
              </div>
            )}
          />
        </div>
      </div>
    )
  }

  const c = chartFor(mode)
  const axisCommon = {
    axisLine: { lineStyle: { color: c.axis } },
    axisLabel: { color: c.axis, fontSize: 12 },
    splitLine: { lineStyle: { color: c.splitLine } },
  }

  /* 1) 科目正确率：横向条形（答题量 + 正确率标签） */
  const subjectOption = {
    color: c.palette,
    tooltip: { trigger: 'axis', backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: mode === 'dark' ? '#F5F5F7' : '#1D1D1F' } },
    grid: { left: 8, right: 44, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', ...axisCommon },
    yAxis: { type: 'category', data: subjects.map((s) => s.subject).reverse(), ...axisCommon, splitLine: { show: false } },
    series: [
      {
        name: '正确率', type: 'bar', barMaxWidth: 18,
        data: subjects.map((s) => s.accuracy).reverse(),
        label: { show: true, position: 'right', formatter: '{c}%', color: c.axis, fontSize: 11 },
        itemStyle: { borderRadius: [0, 9, 9, 0] },
      },
    ],
  }

  /* 2) 近7天趋势：答题量柱 + 正确率线 */
  const trendOption = {
    color: [c.palette[0], c.palette[2]],
    tooltip: { trigger: 'axis', backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: mode === 'dark' ? '#F5F5F7' : '#1D1D1F' } },
    legend: { top: 0, textStyle: { color: c.axis, fontSize: 12 } },
    grid: { left: 8, right: 8, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: trend.map((t) => t.date), ...axisCommon, splitLine: { show: false } },
    yAxis: [{ type: 'value', ...axisCommon }, { type: 'value', max: 100, axisLabel: { ...axisCommon.axisLabel, formatter: '{value}%' }, splitLine: { show: false } }],
    series: [
      { name: '答题数', type: 'bar', barMaxWidth: 26, data: trend.map((t) => t.answered), itemStyle: { borderRadius: [6, 6, 0, 0] } },
      {
        name: '正确率', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 6,
        data: trend.map((t) => (t.answered ? Math.round((t.correct / t.answered) * 100) : 0)),
      },
    ],
  }

  /* 3) 错题标签 Top10：横向条形 */
  const tagOption = {
    color: [c.palette[3]],
    tooltip: { trigger: 'axis', backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: mode === 'dark' ? '#F5F5F7' : '#1D1D1F' } },
    grid: { left: 8, right: 32, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', ...axisCommon },
    yAxis: { type: 'category', data: tags.map((t) => t.tag).reverse(), ...axisCommon, splitLine: { show: false } },
    series: [{
      name: '错题数', type: 'bar', barMaxWidth: 14,
      data: tags.map((t) => t.count).reverse(),
      label: { show: true, position: 'right', color: c.axis, fontSize: 11 },
      itemStyle: { borderRadius: [0, 7, 7, 0] },
    }],
  }

  /* 4) 学习时长分布：环形图 */
  const studyOption = {
    color: c.palette,
    tooltip: { trigger: 'item', backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: mode === 'dark' ? '#F5F5F7' : '#1D1D1F' }, formatter: '{b}：{c} 分钟（{d}%）' },
    legend: { bottom: 0, textStyle: { color: c.axis, fontSize: 12 }, itemWidth: 12, itemHeight: 8 },
    series: [{
      name: '学习时长', type: 'pie', radius: ['46%', '70%'], center: ['50%', '44%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: c.tooltipBg, borderWidth: 2 },
      label: { show: true, formatter: '{b}\n{d}%', color: c.axis, fontSize: 11 },
      data: studyTime.map((s) => ({ name: s.subject, value: s.minutes })),
    }],
  }

  const totalAnswered = subjects.reduce((n, s) => n + s.answered, 0)
  const totalMinutes = studyTime.reduce((n, s) => n + s.minutes, 0)
  const avgAccuracy = totalAnswered
    ? (subjects.reduce((n, s) => n + (s.correct || 0), 0) / totalAnswered * 100).toFixed(1)
    : '0.0'

  return (
    <div className="stack" style={{ gap: 'var(--space-5)' }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-3)' }}>
        <div>
          <h2 className="page-title" style={{ margin: 0 }}>学习统计</h2>
          <p style={{ margin: 'var(--space-1) 0 0', color: 'var(--muted)', fontSize: 'var(--text-sm)' }}>
            全站聚合口径 · 累计答题 {totalAnswered} 题 · 平均正确率 {avgAccuracy}% · 累计学习 {Math.round(totalMinutes / 60)} 小时
          </p>
        </div>
        <button className="btn outline" onClick={refresh} disabled={loading}>
          <RefreshCw size={14} /> 刷新
        </button>
      </div>

      <StudyHeatmap />

      {/* min(420px, 100%)：窄屏（<420px）时轨道上限收缩到容器宽度，避免横向溢出 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(420px, 100%), 1fr))', gap: 'var(--space-5)' }}>
        <section style={CARD}>
          <div className="row" style={{ alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
            <Activity size={16} color="var(--accent)" />
            <strong style={{ fontSize: 'var(--text-md)' }}>科目正确率</strong>
          </div>
          {subjects.length ? <EChart option={subjectOption} style={{ height: `${Math.max(180, subjects.length * 44 + 40)}px` }} /> : <EmptyState title='暂无答题记录' desc='去刷题页练习几道题吧' action={<Link className="btn sm primary" to="/quiz">去刷题</Link>} />}
        </section>

        <section style={CARD}>
          <div className="row" style={{ alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
            <Activity size={16} color="var(--accent)" />
            <strong style={{ fontSize: 'var(--text-md)' }}>近 7 天答题趋势</strong>
          </div>
          <EChart option={trendOption} style={{ height: '280px' }} />
        </section>

        <section style={CARD}>
          <div className="row" style={{ alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
            <Activity size={16} color="var(--accent)" />
            <strong style={{ fontSize: 'var(--text-md)' }}>错题标签 Top10</strong>
          </div>
          {tags.length ? <EChart option={tagOption} style={{ height: `${Math.max(180, tags.length * 34 + 40)}px` }} /> : <EmptyState title='暂无错题标签' desc='错题本录入后自动聚合' action={<Link className="btn sm primary" to="/error-review">去错题本</Link>} />}
        </section>

        <section style={CARD}>
          <div className="row" style={{ alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
            <Activity size={16} color="var(--accent)" />
            <strong style={{ fontSize: 'var(--text-md)' }}>学习时长分布</strong>
          </div>
          {studyTime.length ? <EChart option={studyOption} style={{ height: '300px' }} /> : <EmptyState title='暂无学习时长' desc='打卡或开始学习会话后自动记录' action={<Link className="btn sm primary" to="/planner">去制定计划</Link>} />}
        </section>
      </div>
    </div>
  )
}
