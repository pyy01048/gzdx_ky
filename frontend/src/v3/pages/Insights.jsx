import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import EChart from '../../components/EChart'
import { statsApi, insightApi } from '../../api/client'
import { chartTheme } from '../charts'
import { Badge, Button, Empty, IconButton, PageHeader, Skeleton, Tile, toastErr, toastOk } from '../ui'
import { Activity, BookOpen, CalendarClock, Clock, RefreshCw, Target, TrendingUp } from '../icons'
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
  const [weekly, setWeekly] = useState(null)
  const [weeklyErr, setWeeklyErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    /* 周报与总览并行、互不阻塞：任一接口失败只降级对应模块，不整页报错 */
    const [ov, wk] = await Promise.allSettled([statsApi.overview(), insightApi.weeklyReport()])
    if (ov.status === 'fulfilled') setData(ov.value)
    else setError(ov.reason?.message || '加载失败')
    if (wk.status === 'fulfilled' && wk.value) {
      setWeekly(wk.value)
      setWeeklyErr('')
    } else {
      setWeeklyErr(wk.status === 'rejected' ? wk.reason?.message || '周报接口不可用' : '周报接口返回空')
    }
    setLoading(false)
    return ov.status === 'fulfilled'
  }, [])

  useEffect(() => {
    load()
  }, [load])

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
    yAxis: {
      type: 'category',
      data: subjects.map((s) => s.subject).reverse(),
      ...axis(t),
      splitLine: { show: false },
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 18,
        data: subjects.map((s) => s.accuracy).reverse(),
        label: { show: true, position: 'right', formatter: '{c}%', color: t.textStyle.color, fontSize: 11 },
        itemStyle: { borderRadius: [0, 9, 9, 0], color: '#4285F4' },
      },
    ],
  }

  const trendOption = {
    color: ['#9B72CB', '#D96570'],
    tooltip,
    legend: { top: 0, textStyle: { color: t.textStyle.color, fontSize: 11 } },
    grid: { left: 8, right: 8, top: 34, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: trend.map((x) => x.date), ...axis(t), splitLine: { show: false } },
    yAxis: [
      { type: 'value', ...axis(t) },
      { type: 'value', max: 100, ...axis(t), splitLine: { show: false } },
    ],
    series: [
      {
        name: '答题数',
        type: 'bar',
        barMaxWidth: 26,
        data: trend.map((x) => x.answered),
        itemStyle: { borderRadius: [7, 7, 0, 0] },
      },
      {
        name: '正确率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbolSize: 6,
        data: trend.map((x) => (x.answered ? Math.round((x.correct / x.answered) * 100) : 0)),
      },
    ],
  }

  const tagOption = {
    color: ['#D96570'],
    tooltip: { ...tooltip, formatter: '{b}<br/>错题 {c} 道' },
    grid: { left: 8, right: 36, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', ...axis(t) },
    yAxis: {
      type: 'category',
      data: tags.map((x) => x.tag).reverse(),
      ...axis(t),
      splitLine: { show: false },
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 14,
        data: tags.map((x) => x.count).reverse(),
        label: { show: true, position: 'right', color: t.textStyle.color, fontSize: 11 },
        itemStyle: { borderRadius: [0, 7, 7, 0] },
      },
    ],
  }

  const studyOption = {
    color: ['#4285F4', '#9B72CB', '#D96570', '#34A853', '#F9AB00', '#00ACC1'],
    tooltip: { ...t.tooltip, trigger: 'item', formatter: '{b}：{c} 分钟（{d}%）' },
    legend: {
      bottom: 0,
      textStyle: { color: t.textStyle.color, fontSize: 11 },
      itemWidth: 12,
      itemHeight: 8,
    },
    series: [
      {
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['50%', '43%'],
        itemStyle: { borderRadius: 6, borderColor: mode === 'dark' ? '#12151C' : '#fff', borderWidth: 2 },
        label: { show: true, formatter: '{b}\n{d}%', color: t.textStyle.color, fontSize: 10 },
        data: studyTime.map((s) => ({ name: s.subject, value: s.minutes })),
      },
    ],
  }

  return (
    <div className="v3-stack" style={{ gap: 20 }}>
      <PageHeader
        eyebrow="INSIGHTS · 全站聚合口径"
        title="学习复盘"
        sub={
          hasAny
            ? `累计答题 ${totalAnswered} 题 · 平均正确率 ${avgAccuracy ?? '—'}% · 累计学习 ${Math.round(totalMinutes / 60)} 小时`
            : '科目正确率、答题趋势、错题标签与学习时长'
        }
        actions={
          <IconButton label="刷新统计" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading} />
        }
      />

      {/* ---------- 本周复盘（对标主流学习 App 周报：核心数字 + 环比 + 逐日节奏 + 一句话结论）
          数据全部来自 GET /insight/weekly-report（近 7 天 vs 前 7 天，后端本地规则计算）。 ---------- */}
      <section className="v3-card v3-weekly" aria-label="本周复盘">
        <div className="v3-weekly__head">
          <span className="v3-insight-card-head" style={{ border: 0, padding: 0 }}>
            <CalendarClock size={16} /> 本周复盘
          </span>
          <Badge tone="outline">近 7 天 vs 前 7 天 · /insight/weekly-report</Badge>
        </div>
        {loading && !weekly ? (
          <Skeleton height={140} />
        ) : weekly ? (
          <>
            <p className="v3-weekly__summary">{weekly.summary || '暂无学习数据'}</p>
            <div className="v3-weekly__grid">
              {[
                {
                  label: '答题量',
                  value: weekly.this_week?.answered ?? 0,
                  unit: '题',
                  delta: weekly.answered_delta,
                  hint: `上周 ${weekly.last_week?.answered ?? 0} 题`,
                },
                {
                  label: '正确率',
                  value:
                    weekly.this_week?.accuracy == null ? null : Math.round(weekly.this_week.accuracy * 100),
                  unit: '%',
                  hint:
                    weekly.last_week?.accuracy == null
                      ? '上周样本不足'
                      : `上周 ${Math.round(weekly.last_week.accuracy * 100)}%`,
                  warn: (weekly.this_week?.answered ?? 0) === 0,
                },
                {
                  label: '学习时长',
                  value: weekly.this_week?.duration ?? 0,
                  unit: '分钟',
                  hint: `上周 ${weekly.last_week?.duration ?? 0} 分钟`,
                },
              ].map((m) => (
                <div key={m.label} className="v3-weekly__metric">
                  <span className="v3-weekly__metric-label">{m.label}</span>
                  <strong className="v3-weekly__metric-value">
                    {m.value == null ? <span className="v3-weekly--na">样本不足</span> : m.value}
                    {m.value != null ? <em>{m.unit}</em> : null}
                  </strong>
                  {m.delta != null && (
                    <span className={`v3-weekly__delta ${m.delta >= 0 ? 'is-up' : 'is-down'}`}>
                      环比 {m.delta >= 0 ? '+' : ''}
                      {m.delta}%
                    </span>
                  )}
                  <span className="v3-weekly__metric-hint">{m.hint}</span>
                </div>
              ))}
            </div>
            <div className="v3-weekly__days" role="img" aria-label="近 7 天逐日答题节奏">
              {(weekly.daily || []).map((d) => {
                const max = Math.max(1, ...(weekly.daily || []).map((x) => x.answered || 0))
                const h = Math.round(((d.answered || 0) / max) * 100)
                return (
                  <div
                    key={d.date}
                    className="v3-weekly__day"
                    title={`${d.date} · 答 ${d.answered || 0} 题${d.answered ? ` · 正确率 ${Math.round(((d.correct || 0) / d.answered) * 100)}%` : ''}`}
                  >
                    <span className="v3-weekly__day-bar">
                      <i
                        style={{ height: `${d.answered ? Math.max(6, h) : 2}%` }}
                        className={d.answered ? '' : 'is-zero'}
                      />
                    </span>
                    <span className="v3-weekly__day-label">{String(d.date || '').slice(5)}</span>
                    <span className="v3-weekly__day-num">{d.answered || 0}</span>
                  </div>
                )
              })}
            </div>
            {(weekly.this_week?.answered ?? 0) === 0 && (
              <div className="v3-weekly__cta">
                本周还没开始答题：<Link to="/quiz">去刷题</Link> 或 <Link to="/words">背单词</Link>
                ，任意一项完成后这里会实时刷新。
              </div>
            )}
          </>
        ) : (
          <p className="v3-weekly__err">周报加载失败：{weeklyErr}（不影响下方累计统计）</p>
        )}
      </section>

      {loading ? (
        <div className="v3-grid-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="v3-card" style={{ padding: 22 }}>
              <Skeleton height={220} />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="v3-card" style={{ padding: 36 }}>
          <Empty
            icon={<WarningIcon />}
            title="统计加载失败"
            text={error}
            action={
              <Button variant="tonal" onClick={load}>
                重试
              </Button>
            }
          />
        </div>
      ) : !hasAny ? (
        <div className="v3-card" style={{ padding: 40 }}>
          <Empty
            icon={<Activity size={26} />}
            title="还没有学习数据"
            text="完成几次刷题或学习打卡后，这里会汇总科目正确率、答题趋势、错题标签与学习时长分布。"
            action={
              <div className="v3-row">
                <Link className="v3-btn v3-btn--filled" to="/quiz">
                  去刷题
                </Link>
                <Link className="v3-btn v3-btn--text" to="/tasks">
                  去打卡
                </Link>
              </div>
            }
          />
        </div>
      ) : (
        <>
          <div className="v3-bento">
            {[
              { label: '累计答题', value: totalAnswered, unit: '题', icon: Target },
              {
                label: '平均正确率',
                value: avgAccuracy == null ? '—' : avgAccuracy,
                unit: avgAccuracy == null ? '' : '%',
                icon: TrendingUp,
              },
              { label: '累计学习', value: Math.round(totalMinutes / 60), unit: '小时', icon: Clock },
              { label: '覆盖科目', value: subjects.length, unit: '个', icon: BookOpen },
            ].map((s) => {
              const Icon = s.icon
              return (
                <Tile key={s.label} span={3} className="v3-insight-stat">
                  <span className="v3-tile__label">
                    <Icon size={15} /> {s.label}
                  </span>
                  <span className="v3-tile__value">
                    {s.value}
                    <em>{s.unit}</em>
                  </span>
                </Tile>
              )
            })}

            <Tile span={6}>
              <div className="v3-insight-card-head">
                <Activity size={16} /> 科目正确率
              </div>
              {subjects.length ? (
                <EChart option={subjectOption} style={{ height: Math.max(190, subjects.length * 44 + 30) }} />
              ) : (
                <Empty
                  icon={<Target size={20} />}
                  title="暂无答题记录"
                  action={
                    <Link className="v3-btn v3-btn--tonal v3-btn--sm" to="/quiz">
                      去刷题
                    </Link>
                  }
                />
              )}
            </Tile>

            <Tile span={6}>
              <div className="v3-insight-card-head">
                <TrendingUp size={16} /> 近 7 天答题趋势
              </div>
              <EChart option={trendOption} style={{ height: 280 }} />
            </Tile>

            <Tile span={6}>
              <div className="v3-insight-card-head">
                <Activity size={16} /> 错题标签 Top 10
              </div>
              {tags.length ? (
                <EChart option={tagOption} style={{ height: Math.max(190, tags.length * 34 + 30) }} />
              ) : (
                <Empty
                  icon={<Activity size={20} />}
                  title="暂无错题标签"
                  action={
                    <Link className="v3-btn v3-btn--tonal v3-btn--sm" to="/error-review">
                      去错题本
                    </Link>
                  }
                />
              )}
            </Tile>

            <Tile span={6}>
              <div className="v3-insight-card-head">
                <Clock size={16} /> 学习时长分布
              </div>
              {studyTime.length ? (
                <EChart option={studyOption} style={{ height: 300 }} />
              ) : (
                <Empty
                  icon={<Clock size={20} />}
                  title="暂无学习时长"
                  action={
                    <Link className="v3-btn v3-btn--tonal v3-btn--sm" to="/planner">
                      去制定计划
                    </Link>
                  }
                />
              )}
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
