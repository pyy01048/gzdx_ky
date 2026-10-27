import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import EChart from '../../components/EChart'
import { statsApi } from '../../api/client'
import { chartTheme } from '../charts'
import { Button, Empty, IconButton, PageHeader, Skeleton, Tile, toastErr, toastOk } from '../ui'
import { Activity, BookOpen, Clock, RefreshCw, Target, TrendingUp } from '../icons'
import '../styles/pages.css'

function useThemeMode() {
  const read = () => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')
  const [mode, setMode] = useState(read)
  useEffect(() => {
    const obs = new MutationObserver(() => setMode(read()))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  return mode
}

const axis = (t) => ({
  axisLine: { lineStyle: { color: t.axisLine.lineStyle.color } },
  axisLabel: { color: t.textStyle.color, fontSize: 11 },
  splitLine: { lineStyle: { color: t.splitLine.lineStyle.color } },
})

export default function Insights() {
  const mode = useThemeMode()
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

  const refresh = async () => {
    const ok = await load()
    if (ok) toastOk('统计数据已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  const subjects = data?.subjects || []
  const trend = Object.entries(data?.trend_7d || {}).map(([date, v]) => ({ date: date.slice(5), ...v }))
  const tags = data?.top_error_tags || []
  const studyTime = data?.study_time || []
  const hasAny = subjects.length || trend.some((t) => t.answered) || tags.length || studyTime.length

  const totalAnswered = subjects.reduce((n, s) => n + s.answered, 0)
  const totalMinutes = studyTime.reduce((n, s) => n + s.minutes, 0)
  const avgAccuracy = totalAnswered
    ? ((subjects.reduce((n, s) => n + (s.correct || 0), 0) / totalAnswered) * 100).toFixed(1)
    : null

  const t = chartTheme(mode === 'dark')
  const tooltip = { ...t.tooltip, trigger: 'axis' }

  const subjectOption = {
    color: ['#4285F4'],
    tooltip: { ...tooltip, formatter: '{b}<br/>{c}%' },
    grid: { left: 8, right: 48, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', max: 100, ...axis(t) },
    yAxis: { type: 'category', data: subjects.map((s) => s.subject).reverse(), ...axis(t), splitLine: { show: false } },
    series: [{
      type: 'bar', barMaxWidth: 18,
      data: subjects.map((s) => s.accuracy).reverse(),
      label: { show: true, position: 'right', formatter: '{c}%', color: t.textStyle.color, fontSize: 11 },
      itemStyle: { borderRadius: [0, 9, 9, 0], color: '#4285F4' },
    }],
  }

  const trendOption = {
    color: ['#9B72CB', '#D96570'],
    tooltip,
    legend: { top: 0, textStyle: { color: t.textStyle.color, fontSize: 11 } },
    grid: { left: 8, right: 8, top: 34, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: trend.map((x) => x.date), ...axis(t), splitLine: { show: false } },
    yAxis: [{ type: 'value', ...axis(t) }, { type: 'value', max: 100, ...axis(t), splitLine: { show: false } }],
    series: [
      { name: '答题数', type: 'bar', barMaxWidth: 26, data: trend.map((x) => x.answered), itemStyle: { borderRadius: [7, 7, 0, 0] } },
      { name: '正确率', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 6, data: trend.map((x) => (x.answered ? Math.round((x.correct / x.answered) * 100) : 0)) },
    ],
  }

  const tagOption = {
    color: ['#D96570'],
    tooltip: { ...tooltip, formatter: '{b}<br/>错题 {c} 道' },
    grid: { left: 8, right: 36, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', ...axis(t) },
    yAxis: { type: 'category', data: tags.map((x) => x.tag).reverse(), ...axis(t), splitLine: { show: false } },
    series: [{ type: 'bar', barMaxWidth: 14, data: tags.map((x) => x.count).reverse(), label: { show: true, position: 'right', color: t.textStyle.color, fontSize: 11 }, itemStyle: { borderRadius: [0, 7, 7, 0] } }],
  }

  const studyOption = {
    color: ['#4285F4', '#9B72CB', '#D96570', '#34A853', '#F9AB00', '#00ACC1'],
    tooltip: { ...t.tooltip, trigger: 'item', formatter: '{b}：{c} 分钟（{d}%）' },
    legend: { bottom: 0, textStyle: { color: t.textStyle.color, fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    series: [{
      type: 'pie', radius: ['48%', '72%'], center: ['50%', '43%'],
      itemStyle: { borderRadius: 6, borderColor: mode === 'dark' ? '#12151C' : '#fff', borderWidth: 2 },
      label: { show: true, formatter: '{b}\n{d}%', color: t.textStyle.color, fontSize: 10 },
      data: studyTime.map((s) => ({ name: s.subject, value: s.minutes })),
    }],
  }

  return (
    <div className="v3-stack" style={{ gap: 20 }}>
      <PageHeader
        eyebrow="INSIGHTS · 全站聚合口径"
        title="学习统计"
        sub={hasAny ? `累计答题 ${totalAnswered} 题 · 平均正确率 ${avgAccuracy ?? '—'}% · 累计学习 ${Math.round(totalMinutes / 60)} 小时` : '科目正确率、答题趋势、错题标签与学习时长'}
        actions={<IconButton label="刷新统计" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading} />}
      />

      {loading ? (
        <div className="v3-grid-2">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="v3-card" style={{ padding: 22 }}><Skeleton height={220} /></div>)}</div>
      ) : error ? (
        <div className="v3-card" style={{ padding: 36 }}>
          <Empty icon={<WarningIcon />} title="统计加载失败" text={error} action={<Button variant="tonal" onClick={load}>重试</Button>} />
        </div>
      ) : !hasAny ? (
        <div className="v3-card" style={{ padding: 40 }}>
          <Empty
            icon={<Activity size={26} />}
            title="还没有学习数据"
            text="完成几次刷题或学习打卡后，这里会汇总科目正确率、答题趋势、错题标签与学习时长分布。"
            action={<div className="v3-row"><Link className="v3-btn v3-btn--filled" to="/quiz">去刷题</Link><Link className="v3-btn v3-btn--text" to="/tasks">去打卡</Link></div>}
          />
        </div>
      ) : (
        <>
          <div className="v3-bento">
            {[
              { label: '累计答题', value: totalAnswered, unit: '题', icon: Target },
              { label: '平均正确率', value: avgAccuracy == null ? '—' : avgAccuracy, unit: avgAccuracy == null ? '' : '%', icon: TrendingUp },
              { label: '累计学习', value: Math.round(totalMinutes / 60), unit: '小时', icon: Clock },
              { label: '覆盖科目', value: subjects.length, unit: '个', icon: BookOpen },
            ].map((s) => {
              const Icon = s.icon
              return (
                <Tile key={s.label} span={3} className="v3-insight-stat">
                  <span className="v3-tile__label"><Icon size={15} /> {s.label}</span>
                  <span className="v3-tile__value">{s.value}<em>{s.unit}</em></span>
                </Tile>
              )
            })}

            <Tile span={6}>
              <div className="v3-insight-card-head"><Activity size={16} /> 科目正确率</div>
              {subjects.length
                ? <EChart option={subjectOption} style={{ height: Math.max(190, subjects.length * 44 + 30) }} />
                : <Empty icon={<Target size={20} />} title="暂无答题记录" action={<Link className="v3-btn v3-btn--tonal v3-btn--sm" to="/quiz">去刷题</Link>} />}
            </Tile>

            <Tile span={6}>
              <div className="v3-insight-card-head"><TrendingUp size={16} /> 近 7 天答题趋势</div>
              <EChart option={trendOption} style={{ height: 280 }} />
            </Tile>

            <Tile span={6}>
              <div className="v3-insight-card-head"><Activity size={16} /> 错题标签 Top 10</div>
              {tags.length
                ? <EChart option={tagOption} style={{ height: Math.max(190, tags.length * 34 + 30) }} />
                : <Empty icon={<Activity size={20} />} title="暂无错题标签" action={<Link className="v3-btn v3-btn--tonal v3-btn--sm" to="/error-review">去错题本</Link>} />}
            </Tile>

            <Tile span={6}>
              <div className="v3-insight-card-head"><Clock size={16} /> 学习时长分布</div>
              {studyTime.length
                ? <EChart option={studyOption} style={{ height: 300 }} />
                : <Empty icon={<Clock size={20} />} title="暂无学习时长" action={<Link className="v3-btn v3-btn--tonal v3-btn--sm" to="/planner">去制定计划</Link>} />}
            </Tile>
          </div>
        </>
      )}
    </div>
  )
}

function WarningIcon() {
  return <Activity size={26} />
}
