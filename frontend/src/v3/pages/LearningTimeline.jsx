import React, { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { growthApi } from '../../api/client'
import useApiData from '../../hooks/useApiData'
import {
  AnimatedNumber, Badge, Button, Card, CardHead, Empty, IconButton, PageHeader,
  Segmented, Skeleton, Tile, toastErr, toastOk,
} from '../ui'
import {
  Activity, AlertCircle, Calendar, ChevronRight, Clock, Flame, LineChart, PieChart,
  RefreshCw, Target,
} from '../icons'
import '../styles/timeline-v3.css'

/* ==========================================================================
   学习轨迹（Aurora v3）
   数据源：GET /growth/timeline?days=N
     - streak_days / active_days / streak_rule
     - timeline: [{ date, events, graded, correct, accuracy, study_seconds }]
     - subject_breakdown: [{ subject, events }]
   每日连续化 + 事件柱 / 正确率折线 + 科目分布环图（原生 SVG，无图表库）。
   ========================================================================== */

const RANGE_OPTIONS = [
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
  { value: 365, label: '一年' },
]

const SUBJECT_COLORS = [
  'var(--v3-primary)',
  'var(--v3-secondary)',
  'var(--v3-gemini-4)',
  'var(--v3-success)',
  'var(--v3-tertiary)',
  'var(--v3-gemini-1)',
  'var(--v3-info)',
  'var(--v3-warning)',
]

/** 把后端按日聚合结果补成连续日期序列：断学的日子要显示为 0，
 *  否则折线会把空缺日“跳过”，视觉上像连续学习（口径失真）。 */
function densify(timeline, days) {
  const map = new Map((timeline || []).map((d) => [d.date, d]))
  const out = []
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  for (let i = days - 1; i >= 0; i--) {
    const dt = new Date(today)
    dt.setDate(dt.getDate() - i)
    const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
    out.push(map.get(key) || { date: key, events: 0, graded: 0, correct: 0, accuracy: null, study_seconds: 0 })
  }
  return out
}

function fmtMinutes(sec) {
  const m = Math.round((sec || 0) / 60)
  if (m < 60) return `${m} 分钟`
  const h = Math.floor(m / 60)
  const rest = m % 60
  return rest ? `${h} 小时 ${rest} 分` : `${h} 小时`
}

function fmtAxis(v) {
  const n = Number(v) || 0
  return n >= 1000 ? `${Math.round(n / 100) / 10}k` : String(Math.round(n * 10) / 10)
}

/** Catmull-Rom → 三次贝塞尔，让正确率折线平滑但不过冲 */
function smoothPath(points) {
  if (!points.length) return ''
  if (points.length === 1) return ''
  let d = `M ${points[0].x} ${points[0].y}`
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i]
    const p1 = points[i]
    const p2 = points[i + 1]
    const p3 = points[i + 2] || points[i + 1]
    const cp1x = p1.x + (p2.x - p0.x) / 6
    const cp1y = p1.y + (p2.y - p0.y) / 6
    const cp2x = p2.x - (p3.x - p1.x) / 6
    const cp2y = p2.y - (p3.y - p1.y) / 6
    d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`
  }
  return d
}

function StatTile({ icon, label, value, unit, hint, format, className = '' }) {
  return (
    <Tile span={12} className={`tl3-stat ${className}`.trim()}>
      <span className="v3-tile__label">{icon}{label}</span>
      <span className="v3-tile__value">
        {value == null
          ? <span className="tl3-dash">—</span>
          : <AnimatedNumber value={value} format={format} />}
        {unit && value != null ? <em>{unit}</em> : null}
      </span>
      <span className="v3-tile__hint">{hint}</span>
    </Tile>
  )
}

export default function LearningTimeline() {
  const navigate = useNavigate()
  const [days, setDays] = useState(30)

  const fetcher = useCallback(() => growthApi.timeline(days), [days])
  const { data, loading, error, reload } = useApiData(fetcher, { deps: [days] })

  const rows = useMemo(() => densify(data?.timeline, days), [data, days])

  const totals = useMemo(() => {
    const events = rows.reduce((s, r) => s + (r.events || 0), 0)
    const graded = rows.reduce((s, r) => s + (r.graded || 0), 0)
    const correct = rows.reduce((s, r) => s + (r.correct || 0), 0)
    const seconds = rows.reduce((s, r) => s + (r.study_seconds || 0), 0)
    return {
      events,
      graded,
      correct,
      seconds,
      accuracy: graded ? Math.round((correct / graded) * 1000) / 10 : null,
    }
  }, [rows])

  const hasData = totals.events > 0

  /* ---------- 双轴图几何 ---------- */
  const chart = useMemo(() => {
    const W = 860
    const H = 320
    const padL = 44
    const padR = 48
    const padT = 22
    const padB = 32
    const plotW = W - padL - padR
    const plotH = H - padT - padB
    const bottom = H - padB
    const n = Math.max(1, rows.length)
    const maxEvents = Math.max(1, ...rows.map((r) => Number(r.events) || 0))
    const axisMax = Math.max(4, Math.ceil(maxEvents / 4) * 4)
    const band = plotW / n
    const barW = Math.max(1.5, Math.min(16, band * 0.58))

    const bars = rows.map((r, i) => {
      const h = ((Number(r.events) || 0) / axisMax) * plotH
      return {
        key: r.date || i,
        x: padL + i * band + (band - barW) / 2,
        y: bottom - h,
        w: barW,
        h,
        row: r,
        cx: padL + i * band + band / 2,
        bandX: padL + i * band,
      }
    })

    const points = rows.map((r, i) => (
      r.graded
        ? {
          x: padL + i * band + band / 2,
          y: bottom - (Math.min(100, Math.max(0, Number(r.accuracy) || 0)) / 100) * plotH,
          row: r,
        }
        : null
    ))

    const runs = []
    let current = []
    for (const p of points) {
      if (p) current.push(p)
      else if (current.length) { runs.push(current); current = [] }
    }
    if (current.length) runs.push(current)

    const lines = runs
      .filter((run) => run.length > 1)
      .map((run) => smoothPath(run))
    const isolated = runs.filter((run) => run.length === 1).map((run) => run[0])
    const markers = points.filter(Boolean)

    const labelEvery = Math.max(1, Math.ceil(n / 8))
    const xLabels = []
    rows.forEach((r, i) => {
      if (i % labelEvery === 0) {
        xLabels.push({ i, x: padL + i * band + band / 2, label: (r.date || '').slice(5).replace('-', '/') })
      }
    })
    const lastIndex = n - 1
    const lastShown = xLabels.length ? xLabels[xLabels.length - 1].i : -1
    if (lastIndex >= 0 && lastIndex !== lastShown && lastIndex - lastShown >= labelEvery * 0.55) {
      xLabels.push({ i: lastIndex, x: padL + lastIndex * band + band / 2, label: (rows[lastIndex].date || '').slice(5).replace('-', '/') })
    }

    return {
      W, H, padL, padR, padT, padB, plotW, plotH, bottom, axisMax, band, barW,
      bars, points, lines, markers, isolated, xLabels,
    }
  }, [rows])

  /* ---------- 科目分布 ---------- */
  const subjectData = useMemo(() => {
    const bd = Array.isArray(data?.subject_breakdown) ? data.subject_breakdown : []
    const total = bd.reduce((s, x) => s + (Number(x.events) || 0), 0)
    return {
      total,
      list: bd.map((s, i) => {
        const value = Number(s.events) || 0
        return {
          name: s.subject || '未分类',
          value,
          pct: total ? Math.round((value / total) * 1000) / 10 : 0,
          color: SUBJECT_COLORS[i % SUBJECT_COLORS.length],
        }
      }),
    }
  }, [data])

  const donut = useMemo(() => {
    const R = 70
    const C = 2 * Math.PI * R
    let acc = 0
    const segments = subjectData.list.map((s) => {
      const len = subjectData.total ? (s.value / subjectData.total) * C : 0
      const seg = {
        ...s,
        dash: `${Math.max(0, len - 2)} ${C - Math.max(0, len - 2)}`,
        offset: -acc,
        R,
        C,
      }
      acc += len
      return seg
    })
    return { R, C, segments }
  }, [subjectData])

  const refresh = async () => {
    const ok = await reload()
    if (ok) toastOk('学习轨迹已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  const header = (
    <PageHeader
      eyebrow="TIMELINE · 学习轨迹"
      title="学习轨迹"
      sub="基于答题 / 复习 / 学习事件自动统计，断学的日子按 0 计入"
      actions={(
        <>
          <Segmented
            ariaLabel="统计区间"
            options={RANGE_OPTIONS}
            value={days}
            onChange={setDays}
          />
          <IconButton
            label="刷新学习轨迹"
            icon={<RefreshCw size={17} />}
            onClick={refresh}
            disabled={loading}
          />
        </>
      )}
    />
  )

  /* ---------- 首次加载 ---------- */
  if (loading && !data) {
    return (
      <div className="v3-stack v3-timeline">
        {header}
        <div className="tl3-stats">
          {[0, 1, 2, 3, 4].map((i) => (
            <Tile span={12} key={i} className="tl3-stat tl3-stat--skeleton">
              <Skeleton height={13} width="56%" />
              <Skeleton height={32} width="46%" style={{ marginTop: 16 }} />
              <Skeleton height={10} width="70%" style={{ marginTop: 9 }} />
            </Tile>
          ))}
        </div>
        <div className="v3-bento">
          <Card className="v3-span-8 tl3-chart-card">
            <CardHead icon={<LineChart size={17} />} title="每日活跃与正确率" sub="正在统计学习轨迹…" />
            <Skeleton height={280} />
          </Card>
          <Card className="v3-span-4">
            <CardHead icon={<PieChart size={17} />} title="科目分布" sub="正在统计…" />
            <Skeleton height={200} width={200} radius={100} style={{ margin: '12px auto' }} />
          </Card>
        </div>
      </div>
    )
  }

  /* ---------- 失败 ---------- */
  if (error) {
    return (
      <div className="v3-stack v3-timeline">
        {header}
        <Card className="tl3-error-card">
          <Empty
            icon={<AlertCircle size={26} />}
            title="学习轨迹加载失败"
            text={error}
            action={<Button variant="tonal" icon={<RefreshCw size={16} />} loading={loading} onClick={reload}>重新加载</Button>}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="v3-stack v3-timeline">
      {header}

      {/* 关键指标 */}
      <div className="tl3-stats">
        <StatTile
          icon={<Flame size={15} />}
          label="连续学习"
          value={data?.streak_days ?? 0}
          unit="天"
          hint={data?.streak_rule || '今天或昨天起算'}
        />
        <StatTile
          icon={<Calendar size={15} />}
          label="活跃天数"
          value={data?.active_days ?? 0}
          unit="天"
          hint={`近 ${days} 天内有学习事件`}
        />
        <StatTile
          icon={<Activity size={15} />}
          label="学习事件"
          value={totals.events}
          unit="次"
          hint="答题 / 复习 / 学习"
        />
        <StatTile
          icon={<Target size={15} />}
          label="正确率"
          value={totals.accuracy}
          unit="%"
          format={(n) => Math.round(n * 10) / 10}
          hint={totals.graded ? `${totals.correct} / ${totals.graded} 题判分` : '暂无判分记录'}
        />
        <StatTile
          icon={<Clock size={15} />}
          label="累计时长"
          value={totals.seconds}
          format={(v) => fmtMinutes(v)}
          hint="按事件埋点估算"
          className="tl3-stat--duration"
        />
      </div>

      {!hasData ? (
        <Card className="tl3-empty-card">
          <Empty
            icon={<LineChart size={26} />}
            title={`近 ${days} 天还没有学习记录`}
            text="去刷题、背单词或复习卡片，事件会自动记录到这里。"
            action={<Button variant="gradient" icon={<Target size={16} />} onClick={() => navigate('/quiz')}>去刷题</Button>}
          />
        </Card>
      ) : (
        <div className="v3-bento">
          {/* 每日活跃与正确率 */}
          <Card className={`${subjectData.list.length ? 'v3-span-8' : 'v3-span-12'} tl3-chart-card`}>
            <CardHead
              icon={<LineChart size={17} />}
              title="每日活跃与正确率"
              sub={loading ? '同步中…' : `近 ${days} 天 · 柱形为事件数，折线仅连接有判分的日期`}
              actions={(
                <div className="tl3-legend">
                  <span><i className="is-bar" />事件数</span>
                  <span><i className="is-line" />正确率</span>
                </div>
              )}
            />
            <div className="tl3-chart">
              <svg
                viewBox={`0 0 ${chart.W} ${chart.H}`}
                role="img"
                aria-label={`近 ${days} 天每日学习事件与正确率，共 ${totals.events} 次事件`}
                preserveAspectRatio="xMidYMid meet"
              >
                <defs>
                  <linearGradient id="tl3-bar-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" style={{ stopColor: 'var(--v3-gemini-1)', stopOpacity: 0.95 }} />
                    <stop offset="100%" style={{ stopColor: 'var(--v3-gemini-2)', stopOpacity: 0.45 }} />
                  </linearGradient>
                </defs>

                {/* 轴标签 */}
                <text className="tl3-axis-title" x={chart.padL} y={11}>事件数</text>
                <text className="tl3-axis-title" x={chart.W - chart.padR} y={11} textAnchor="end">正确率</text>

                {/* 网格 + 双轴刻度 */}
                {[0, 1, 2, 3, 4].map((i) => {
                  const y = chart.bottom - (i / 4) * chart.plotH
                  return (
                    <g key={i}>
                      <line className="tl3-gridline" x1={chart.padL} y1={y} x2={chart.W - chart.padR} y2={y} />
                      <text className="tl3-tick" x={chart.padL - 8} y={y + 3.5} textAnchor="end">
                        {fmtAxis((chart.axisMax * i) / 4)}
                      </text>
                      <text className="tl3-tick" x={chart.W - chart.padR + 8} y={y + 3.5}>
                        {i * 25}%
                      </text>
                    </g>
                  )
                })}

                {/* 事件柱 + 悬浮热区 */}
                {chart.bars.map((b) => (
                  <g className="tl3-day" key={b.key}>
                    <rect
                      className="tl3-hoverband"
                      x={b.bandX}
                      y={chart.padT}
                      width={Math.max(1, chart.band)}
                      height={chart.plotH}
                      rx={3}
                    />
                    {b.h > 0 ? (
                      <rect
                        className="tl3-bar"
                        x={b.x}
                        y={b.y}
                        width={b.w}
                        height={Math.max(1, b.h)}
                        rx={Math.min(4, b.w / 2)}
                        fill="url(#tl3-bar-grad)"
                      />
                    ) : null}
                    <rect
                      x={b.bandX}
                      y={chart.padT}
                      width={Math.max(1, chart.band)}
                      height={chart.plotH}
                      fill="transparent"
                      pointerEvents="all"
                    >
                      <title>
                        {`${b.row.date} · 事件 ${Number(b.row.events) || 0}${b.row.graded ? ` · 正确率 ${b.row.accuracy}%（${b.row.correct}/${b.row.graded}）` : ' · 当日无判分'}`}
                      </title>
                    </rect>
                  </g>
                ))}

                {/* 正确率折线（无判分日断线） */}
                {chart.lines.map((d, i) => (
                  <path key={i} className="tl3-line" d={d} />
                ))}
                {chart.isolated.map((p, i) => (
                  <circle key={`iso-${i}`} className="tl3-dot" cx={p.x} cy={p.y} r={3} />
                ))}
                {rows.length <= 60
                  ? chart.markers.map((p, i) => (
                    <circle key={`m-${i}`} className="tl3-dot" cx={p.x} cy={p.y} r={2.4}>
                      <title>{`${p.row.date} · 正确率 ${p.row.accuracy}%`}</title>
                    </circle>
                  ))
                  : null}

                {/* X 轴日期 */}
                {chart.xLabels.map((t) => (
                  <text className="tl3-tick" key={t.i} x={t.x} y={chart.H - 10} textAnchor="middle">
                    {t.label}
                  </text>
                ))}
              </svg>
            </div>
          </Card>

          {/* 科目分布 */}
          {subjectData.list.length ? (
            <Card className="v3-span-4 tl3-subject-card">
              <CardHead
                icon={<PieChart size={17} />}
                title="科目分布"
                sub="按学习事件数聚合"
                actions={<Badge tone="outline">{subjectData.list.length} 个科目</Badge>}
              />
              <div className="tl3-donut">
                <svg viewBox="0 0 200 200" role="img" aria-label={`科目分布，共 ${subjectData.total} 次事件`}>
                  <circle className="tl3-donut-track" cx="100" cy="100" r={donut.R} />
                  <g transform="rotate(-90 100 100)">
                    {donut.segments.map((s) => (
                      s.value > 0 ? (
                        <circle
                          key={s.name}
                          className="tl3-donut-seg"
                          cx="100"
                          cy="100"
                          r={donut.R}
                          strokeDasharray={s.dash}
                          strokeDashoffset={s.offset}
                          style={{ stroke: s.color }}
                        >
                          <title>{`${s.name}：${s.value} 次（${s.pct}%）`}</title>
                        </circle>
                      ) : null
                    ))}
                  </g>
                </svg>
                <div className="tl3-donut-center">
                  <strong><AnimatedNumber value={subjectData.total} /></strong>
                  <span>学习事件</span>
                </div>
              </div>

              <ul className="tl3-subjects">
                {subjectData.list.map((s) => (
                  <li className="tl3-subject" key={s.name}>
                    <span className="tl3-subject__dot" style={{ background: s.color }} aria-hidden="true" />
                    <span className="tl3-subject__name" title={s.name}>{s.name}</span>
                    <span className="tl3-subject__val">{s.value} 次</span>
                    <span className="tl3-subject__pct">{s.pct}%</span>
                    <span className="tl3-subject__track" aria-hidden="true">
                      <i style={{ width: `${Math.max(0, Math.min(100, s.pct))}%`, background: s.color }} />
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      )}

      {hasData ? (
        <div className="tl3-note">
          <ChevronRight size={14} />
          <span>统计口径：学习事件由答题、复习与学习行为埋点累加；学习时长按事件估算，不等同于在线时长。</span>
        </div>
      ) : null}
    </div>
  )
}
