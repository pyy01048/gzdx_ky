import React, { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import {
  Alert, Badge, Button, Chip, Empty, IconButton, PageHeader, Skeleton,
  Tile, toastErr, toastOk,
} from '../ui'
import {
  ArrowRight, BarChart3, ChevronRight, LineChart, RefreshCw, School,
  Target, TrendingDown,
} from '../icons'
import '../styles/kaoyan-aux-v3.css'

const METRICS = [
  { value: 'total_line', label: '总分线', unit: '分' },
  { value: 'retest_line', label: '复试线', unit: '分' },
  { value: 'national_line', label: '国家线', unit: '分' },
  { value: 'admit_avg_score', label: '录取均分', unit: '分' },
  { value: 'enroll_count', label: '招生人数', unit: '人' },
  { value: 'retest_ratio', label: '复录比', unit: '' },
]

function fmtValue(value, unit = '') {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  const text = Number.isInteger(n) ? String(n) : n.toFixed(1)
  return unit ? `${text} ${unit}` : text
}

function niceScale(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1, ticks: [0, 1] }
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1
    min -= pad
    max += pad
  }
  const span = max - min
  const rough = span / Math.max(1, count - 1)
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  const err = rough / mag
  const step = mag * (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1)
  const lo = Math.floor(min / step) * step
  const hi = Math.ceil(max / step) * step
  const ticks = []
  for (let v = lo; v <= hi + step * 0.5; v += step) ticks.push(Number(v.toFixed(6)))
  return { min: lo, max: hi, ticks }
}

function smoothPath(pts) {
  if (!pts.length) return ''
  if (pts.length === 1) return `M${pts[0][0]},${pts[0][1]}`
  let d = `M${pts[0][0]},${pts[0][1]}`
  for (let i = 0; i < pts.length - 1; i += 1) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`
  }
  return d
}

function TrendChart({ data, unit, label }) {
  const gid = useId().replace(/:/g, '')
  const [active, setActive] = useState(null)
  const W = 880
  const H = 360
  const M = { top: 22, right: 26, bottom: 46, left: 58 }
  const innerW = W - M.left - M.right
  const innerH = H - M.top - M.bottom

  const points = useMemo(() => data
    .map((d, i) => ({ ...d, _i: i, n: Number(d.value) }))
    .filter((d) => Number.isFinite(d.n)), [data])

  const scale = useMemo(() => {
    const values = points.map((p) => p.n)
    return niceScale(Math.min(...values, 0), Math.max(...values, 1), 5)
  }, [points])

  if (!points.length) return null

  const x = (i) => (points.length === 1 ? M.left + innerW / 2 : M.left + (i * innerW) / (points.length - 1))
  const y = (v) => M.top + innerH - ((v - scale.min) / Math.max(scale.max - scale.min, 1e-9)) * innerH
  const pts = points.map((p, i) => [x(i), y(p.n)])
  const line = smoothPath(pts)
  const area = `${line} L${pts[pts.length - 1][0]},${M.top + innerH} L${pts[0][0]},${M.top + innerH} Z`

  return (
    <div className="v3-ky-chart">
      <svg
        className="v3-ky-chart__svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${label}近 5 年趋势图`}
      >
        <defs>
          <linearGradient id={`ky-line-${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--v3-primary)" stopOpacity="0.30" />
            <stop offset="100%" stopColor="var(--v3-primary)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {scale.ticks.map((tick) => {
          const ty = y(tick)
          return (
            <g key={tick}>
              <line className="v3-ky-chart__grid" x1={M.left} x2={W - M.right} y1={ty} y2={ty} />
              <text className="v3-ky-chart__tick" x={M.left - 10} y={ty + 4} textAnchor="end">{tick}</text>
            </g>
          )
        })}

        <path d={area} fill={`url(#ky-line-${gid})`} />
        <path d={line} className="v3-ky-chart__line" />

        {pts.map(([px, py], i) => {
          const point = points[i]
          const prevYear = points[i - 1]?.year
          const showLabel = points.length <= 8 || i === 0 || i === points.length - 1 || point.year !== prevYear
          return (
            <g
              key={`${point.year}-${i}`}
              className="v3-ky-chart__point"
              onMouseEnter={() => setActive(i)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              tabIndex={0}
              role="img"
              aria-label={`${point.year} 年 ${label} ${fmtValue(point.n, unit)}`}
            >
              <circle cx={px} cy={py} r="14" fill="transparent" />
              <circle cx={px} cy={py} r={active === i ? 5.5 : 4} className="v3-ky-chart__dot" />
              <title>{`${point.year} 年 · ${label} ${fmtValue(point.n, unit)}`}</title>
              {showLabel ? (
                <text className="v3-ky-chart__x" x={px} y={H - 18} textAnchor="middle">{point.year}</text>
              ) : null}
            </g>
          )
        })}
      </svg>

      {active != null ? (
        <div
          className="v3-ky-chart__tip"
          style={{
            left: `${(pts[active][0] / W) * 100}%`,
            top: `${(pts[active][1] / H) * 100}%`,
          }}
        >
          <span>{points[active].year} 年</span>
          <b>{fmtValue(points[active].n, unit)}</b>
        </div>
      ) : null}
    </div>
  )
}

export default function KaoyanAnalysis() {
  const [schools, setSchools] = useState({ items: [] })
  const [loadingSchools, setLoadingSchools] = useState(true)
  const [schoolsError, setSchoolsError] = useState('')
  const [selected, setSelected] = useState(null)
  const [metric, setMetric] = useState('total_line')
  const [trend, setTrend] = useState({ data: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadSchools = useCallback(async () => {
    setLoadingSchools(true)
    setSchoolsError('')
    const out = []
    try {
      for (let page = 1; page <= 20; page += 1) {
        const d = await kaoyanApi.schools({ page_size: 100, page })
        const items = Array.isArray(d?.items) ? d.items : []
        if (!items.length) break
        out.push(...items)
        if (items.length < 100 || out.length >= (d.total || 0)) break
      }
      setSchools({ items: out })
      return true
    } catch (e) {
      setSchoolsError(e?.message || '院校列表加载失败')
      setSchools({ items: out })
      return false
    } finally {
      setLoadingSchools(false)
    }
  }, [])

  useEffect(() => { loadSchools() }, [loadSchools])

  const loadTrend = useCallback(async () => {
    if (!selected) {
      setTrend({ data: [] })
      setError('')
      return
    }
    setLoading(true)
    setError('')
    try {
      const d = await kaoyanApi.trend({ school_id: selected, metric, years: 5 })
      setTrend(d?.data ? d : { data: [] })
      return true
    } catch (e) {
      setError(e?.message || '趋势数据加载失败')
      setTrend({ data: [] })
      return false
    } finally {
      setLoading(false)
    }
  }, [selected, metric])

  useEffect(() => { loadTrend() }, [loadTrend])

  const refresh = async () => {
    const ok = await loadTrend()
    if (ok) toastOk('趋势数据已刷新')
    else if (selected) toastErr('刷新失败，请稍后重试')
  }

  const schoolItems = Array.isArray(schools.items) ? schools.items : []
  const selectedSchool = schoolItems.find((s) => String(s.id) === String(selected))
  const metricMeta = METRICS.find((m) => m.value === metric) || METRICS[0]
  const rows = Array.isArray(trend.data) ? trend.data : []
  const validRows = rows.filter((d) => d.value != null && Number.isFinite(Number(d.value)))
  const latest = validRows.length ? validRows[validRows.length - 1] : null
  const first = validRows.length ? validRows[0] : null
  const values = validRows.map((d) => Number(d.value))
  const maxVal = values.length ? Math.max(...values) : null
  const minVal = values.length ? Math.min(...values) : null
  const change = latest && first ? Number(latest.value) - Number(first.value) : null

  const headerSub = loadingSchools
    ? '正在读取院校库…'
    : schoolsError
      ? '院校列表加载失败'
      : selectedSchool
        ? `${selectedSchool.name} · ${metricMeta.label} · 近 5 年数据`
        : `已收录 ${schoolItems.length} 所院校 · 六种指标 · 近 5 年趋势`

  return (
    <div className="v3-stack v3-ky">
      <PageHeader
        eyebrow="ANALYSIS · 分数趋势"
        title="分数分析"
        sub={headerSub}
        actions={(
          <>
            <IconButton label="刷新趋势数据" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading || !selected} />
            <Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">
              浏览院校库 <ArrowRight size={15} />
            </Link>
          </>
        )}
      />

      <Tile span={12} variant="hero" className="v3-ky-hero">
        <div className="v3-ky-hero__body">
          <div className="v3-ky-hero__copy">
            <span className="v3-eyebrow v3-ky-hero__eyebrow"><LineChart size={13} /> 五年走势</span>
            <h2>同一所院校，六种指标，<br />五年变化一眼看清。</h2>
            <p>
              总分线、复试线、国家线、录取均分、招生人数与复录比全部来自库内记录；
              缺值的年份留空，不用 0 或预测值补齐。
            </p>
            <div className="v3-ky-hero__actions">
              {selectedSchool ? (
                <Link className="v3-btn v3-btn--gradient" to={`/kaoyan/schools/${selectedSchool.id}`}>
                  查看院校详情 <ChevronRight size={15} />
                </Link>
              ) : (
                <Link className="v3-btn v3-btn--gradient" to="/kaoyan/schools">
                  去院校库挑一所 <ArrowRight size={15} />
                </Link>
              )}
              <Link className="v3-btn v3-btn--tonal" to="/kaoyan/map">看区域分布</Link>
            </div>
          </div>
          <div className="v3-ky-hero__stats">
            <div className="v3-ky-hero__stat">
              <b>{schoolItems.length || '—'}</b>
              <span>可选院校</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{validRows.length}</b>
              <span>有效数据点</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{metricMeta.label}</b>
              <span>当前指标</span>
            </div>
          </div>
        </div>
      </Tile>

      {loadingSchools ? (
        <>
          <Tile><Skeleton height={112} /></Tile>
          <Tile><Skeleton height={360} /></Tile>
        </>
      ) : schoolsError ? (
        <Tile>
          <Empty
            icon={<School size={26} />}
            title="院校列表加载失败"
            text={`接口请求失败：${schoolsError}`}
            action={<Button variant="tonal" onClick={loadSchools}>重新加载</Button>}
          />
        </Tile>
      ) : schoolItems.length === 0 ? (
        <Tile>
          <Empty
            icon={<School size={26} />}
            title="院校库还没有数据"
            text="分数分析依赖院校库中的院校与分数线记录。导入后即可按院校查看五年趋势。"
            action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">浏览院校库</Link>}
          />
        </Tile>
      ) : (
        <>
          <Tile span={12} className="v3-ky-panel">
            <div className="v3-ky-panel__head">
              <div>
                <h2>选择院校与指标</h2>
                <p>院校下拉来自库内实际记录；切换指标会重新请求近 5 年趋势。</p>
              </div>
              <Badge tone="outline">{schoolItems.length} 所院校</Badge>
            </div>

            <div className="v3-ky-analysis-select">
              <label className="v3-ky-analysis-select__school">
                <span className="v3-label">院校</span>
                <select
                  className="v3-select"
                  value={selected || ''}
                  aria-label="选择院校"
                  onChange={(e) => setSelected(e.target.value || null)}
                >
                  <option value="">请选择院校（共 {schoolItems.length} 所）</option>
                  {schoolItems.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </label>
              <div className="v3-ky-metric-chips" role="group" aria-label="选择指标">
                {METRICS.map((m) => (
                  <Chip key={m.value} active={metric === m.value} onClick={() => setMetric(m.value)}>
                    {m.label}
                  </Chip>
                ))}
              </div>
            </div>
          </Tile>

          <Tile span={12} className="v3-ky-analysis-chart-tile">
            {!selected ? (
              <Empty
                icon={<Target size={26} />}
                title="选择一所院校开始分析"
                text="选定院校后可切换总分线、复试线、国家线、录取均分、招生人数、复录比六种指标，查看近 5 年趋势与逐年数值。"
                action={<Link className="v3-btn v3-btn--gradient" to="/kaoyan/schools">去院校库挑一所</Link>}
              />
            ) : loading ? (
              <div className="v3-ky-analysis-loading">
                <Skeleton height={54} />
                <Skeleton height={340} />
              </div>
            ) : error ? (
              <Empty
                icon={<AlertIcon />}
                title="趋势数据加载失败"
                text={error}
                action={<Button variant="tonal" onClick={loadTrend}>重试</Button>}
              />
            ) : rows.length === 0 ? (
              <Empty
                icon={<BarChart3 size={26} />}
                title="暂无趋势数据"
                text={`该校的「${metricMeta.label}」还没有可展示的年份数据。换一个指标，或到院校详情页查看已收录的历年分数。`}
                action={<Link className="v3-btn v3-btn--tonal" to={`/kaoyan/schools/${selected}`}>查看院校详情</Link>}
              />
            ) : (
              <>
                <div className="v3-ky-analysis-head">
                  <div>
                    <span className="v3-eyebrow">{selectedSchool?.name || '院校'} · {metricMeta.label}</span>
                    <h2>近 5 年趋势</h2>
                  </div>
                  <div className="v3-ky-analysis-summary">
                    <div>
                      <span>最新</span>
                      <b>{latest ? fmtValue(latest.value, metricMeta.unit) : '—'}</b>
                      {latest ? <em>{latest.year} 年</em> : null}
                    </div>
                    <div>
                      <span>区间变化</span>
                      <b className={change > 0 ? 'is-up' : change < 0 ? 'is-down' : ''}>
                        {change == null ? '—' : `${change > 0 ? '+' : ''}${Number.isInteger(change) ? change : change.toFixed(1)}`}
                      </b>
                      {change != null ? <em>{change > 0 ? '上升' : change < 0 ? '下降' : '持平'}</em> : null}
                    </div>
                    <div>
                      <span>最高 / 最低</span>
                      <b>{maxVal == null ? '—' : fmtValue(maxVal, '')} <i>/</i> {minVal == null ? '—' : fmtValue(minVal, '')}</b>
                      <em>{metricMeta.unit || '倍数'}</em>
                    </div>
                  </div>
                </div>

                {validRows.length ? (
                  <TrendChart data={rows} unit={metricMeta.unit} label={metricMeta.label} />
                ) : (
                  <div className="v3-ky-chart-empty">
                    <BarChart3 size={22} />
                    <span>该指标暂无有效数值，下表保留原始记录。</span>
                  </div>
                )}

                <div className="v3-ky-table-block">
                  <div className="v3-ky-table-block__head">
                    <h3>逐年数值</h3>
                    <span>共 {rows.length} 条记录 · 空值显示为 —</span>
                  </div>
                  <div className="v3-table-wrap">
                    <table className="v3-table">
                      <thead>
                        <tr>
                          <th>年份</th>
                          <th>{metricMeta.label}</th>
                          <th>记录位置</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((d, i) => (
                          <tr key={`${d.year}-${i}`}>
                            <td><b>{d.year}</b></td>
                            <td>{d.value == null ? '—' : fmtValue(d.value, metricMeta.unit)}</td>
                            <td className="v3-ky-table-muted">第 {i + 1} 条</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="v3-ky-analysis-foot">
                  <Link className="v3-ky-inline-link" to={`/kaoyan/schools/${selected}`}>
                    查看院校完整档案 <ChevronRight size={14} />
                  </Link>
                  <span className="v3-caption">
                    {change == null
                      ? '历史数据不足，无法计算区间变化。'
                      : change > 0
                        ? `较首个有效年份上升 ${fmtValue(Math.abs(change), metricMeta.unit)}。`
                        : change < 0
                          ? `较首个有效年份下降 ${fmtValue(Math.abs(change), metricMeta.unit)}。`
                          : '首尾年份数值持平。'}
                  </span>
                </div>
              </>
            )}
          </Tile>
        </>
      )}

      <p className="v3-ky-footnote">
        <LineChart size={13} /> 数据点来自 /kaoyan/analysis/trend，按库内实际记录展示；趋势线只连线真实年份，不做外推。
      </p>
    </div>
  )
}

function AlertIcon() {
  return <TrendingDown size={26} />
}
