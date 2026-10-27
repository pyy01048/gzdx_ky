import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import {
  Alert, Badge, Button, Empty, IconButton, PageHeader, Skeleton, Tile,
} from '../ui'
import {
  ArrowRight, BarChart3, Database, Layers, RefreshCw, School, Sparkles, Target,
} from '../icons'
import '../styles/kaoyan-aux-v3.css'

/* -------------------------------------------------------------------------- */
/* Level palette                                                              */
/* -------------------------------------------------------------------------- */

const LEVEL_ORDER = ['985', '211', '双一流', '双非', '未分类']

const LEVEL_META = {
  985: { color: 'var(--v3-tertiary)', soft: 'var(--v3-tertiary-container)' },
  211: { color: 'var(--v3-warning)', soft: 'var(--v3-warning-container)' },
  双一流: { color: 'var(--v3-primary)', soft: 'var(--v3-primary-container)' },
  双非: { color: 'color-mix(in srgb, var(--v3-primary) 46%, var(--v3-surface))', soft: 'var(--v3-info-container)' },
  未分类: { color: 'var(--v3-text-3)', soft: 'var(--v3-surface-2)' },
}

function levelOf(item) {
  return String(item?.level || '').trim() || '未分类'
}

function levelMeta(level) {
  return LEVEL_META[level] || LEVEL_META['未分类']
}

function medians(values) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function mean(values) {
  if (!values.length) return null
  return values.reduce((sum, n) => sum + n, 0) / values.length
}

function num(value, digits = 1) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

/* -------------------------------------------------------------------------- */
/* Scales                                                                     */
/* -------------------------------------------------------------------------- */

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

/* -------------------------------------------------------------------------- */
/* Scatter chart                                                              */
/* -------------------------------------------------------------------------- */

const CHART_W = 940
const CHART_H = 520
const CHART_M = { top: 30, right: 30, bottom: 62, left: 74 }

function ScatterChart({ points, hiddenLevels, onToggleLevel, levels }) {
  const [active, setActive] = useState(null)
  const innerW = CHART_W - CHART_M.left - CHART_M.right
  const innerH = CHART_H - CHART_M.top - CHART_M.bottom

  const scales = useMemo(() => {
    if (!points.length) {
      return { x: niceScale(0, 100, 6), y: niceScale(300, 450, 5) }
    }
    const xs = points.map((p) => p.enroll)
    const ys = points.map((p) => p.admitAvg)
    const xMax = Math.max(...xs, 1)
    const yMin = Math.min(...ys)
    const yMax = Math.max(...ys)
    return {
      x: niceScale(0, xMax, 6),
      y: niceScale(Math.floor((yMin - 8) / 10) * 10, yMax + 8, 5),
    }
  }, [points])

  const px = (value) => CHART_M.left + ((value - scales.x.min) / Math.max(scales.x.max - scales.x.min, 1e-9)) * innerW
  const py = (value) => CHART_M.top + innerH - ((value - scales.y.min) / Math.max(scales.y.max - scales.y.min, 1e-9)) * innerH

  const visible = points.filter((p) => !hiddenLevels.has(p.level))
  const activePoint = active != null ? points.find((p) => p.i === active) : null
  const activeVisible = activePoint && !hiddenLevels.has(activePoint.level)
  const tip = activePoint && activeVisible
    ? {
      left: Math.min(88, Math.max(12, (px(activePoint.enroll) / CHART_W) * 100)),
      top: Math.min(86, Math.max(12, (py(activePoint.admitAvg) / CHART_H) * 100)),
    }
    : null

  return (
    <div className="v3-ky-scatter">
      <div className="v3-ky-scatter__legend" role="group" aria-label="按院校层级筛选">
        {levels.map((level) => {
          const meta = levelMeta(level)
          const off = hiddenLevels.has(level)
          return (
            <button
              key={level}
              type="button"
              className={`v3-ky-scatter__legend-item${off ? ' is-off' : ''}`}
              aria-pressed={!off}
              onClick={() => {
                setActive(null)
                onToggleLevel(level)
              }}
            >
              <i style={{ background: meta.color }} />
              <span>{level}</span>
              <em>{points.filter((p) => p.level === level).length}</em>
            </button>
          )
        })}
      </div>

      <div className="v3-ky-scatter__canvas">
        <svg
          className="v3-ky-scatter__svg"
          viewBox={`0 0 ${CHART_W} ${CHART_H}`}
          role="img"
          aria-label={`招生人数与录取均分散点图，共 ${visible.length} 所院校`}
        >
          {scales.y.ticks.map((tick) => {
            const ty = py(tick)
            if (ty < CHART_M.top - 1 || ty > CHART_M.top + innerH + 1) return null
            return (
              <g key={`y-${tick}`}>
                <line
                  className="v3-ky-scatter__grid"
                  x1={CHART_M.left}
                  x2={CHART_W - CHART_M.right}
                  y1={ty}
                  y2={ty}
                />
                <text className="v3-ky-scatter__tick" x={CHART_M.left - 12} y={ty + 4} textAnchor="end">{tick}</text>
              </g>
            )
          })}
          {scales.x.ticks.map((tick) => {
            const tx = px(tick)
            if (tx < CHART_M.left - 1 || tx > CHART_W - CHART_M.right + 1) return null
            return (
              <g key={`x-${tick}`}>
                <line
                  className="v3-ky-scatter__grid v3-ky-scatter__grid--x"
                  x1={tx}
                  x2={tx}
                  y1={CHART_M.top}
                  y2={CHART_M.top + innerH}
                />
                <text className="v3-ky-scatter__tick" x={tx} y={CHART_M.top + innerH + 24} textAnchor="middle">{tick}</text>
              </g>
            )
          })}

          <line
            className="v3-ky-scatter__axis"
            x1={CHART_M.left}
            x2={CHART_M.left}
            y1={CHART_M.top}
            y2={CHART_M.top + innerH}
          />
          <line
            className="v3-ky-scatter__axis"
            x1={CHART_M.left}
            x2={CHART_W - CHART_M.right}
            y1={CHART_M.top + innerH}
            y2={CHART_M.top + innerH}
          />

          <text className="v3-ky-scatter__axis-label" x={CHART_M.left} y={16}>录取均分（分）</text>
          <text
            className="v3-ky-scatter__axis-label"
            x={CHART_W - CHART_M.right}
            y={CHART_H - 16}
            textAnchor="end"
          >
            拟招生人数（人）
          </text>

          {visible.map((point) => {
            const cx = px(point.enroll)
            const cy = py(point.admitAvg)
            const meta = levelMeta(point.level)
            const isActive = active === point.i
            return (
              <g
                key={`${point.name}-${point.i}`}
                className={`v3-ky-scatter__point${isActive ? ' is-active' : ''}`}
                tabIndex={0}
                role="img"
                aria-label={`${point.name}，${point.level}，招生 ${point.enroll} 人，录取均分 ${num(point.admitAvg, 1)}，复录比 ${point.retestRatio == null ? '未收录' : num(point.retestRatio, 2)}`}
                onMouseEnter={() => setActive(point.i)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(point.i)}
                onBlur={() => setActive(null)}
                onClick={(e) => {
                  e.stopPropagation()
                  setActive((prev) => (prev === point.i ? null : point.i))
                }}
              >
                <circle
                  cx={cx}
                  cy={cy}
                  r={point.r + 5}
                  fill="transparent"
                />
                <circle
                  cx={cx}
                  cy={cy}
                  r={point.r}
                  className="v3-ky-scatter__bubble"
                  style={{ fill: meta.color }}
                />
                <title>
                  {`${point.name} · ${point.level} · ${point.province || '省份未标注'} · 招生 ${point.enroll} 人 · 均分 ${num(point.admitAvg, 1)} · 复录比 ${point.retestRatio == null ? '—' : num(point.retestRatio, 2)}`}
                </title>
              </g>
            )
          })}
        </svg>

        {tip && activePoint ? (
          <div className="v3-ky-scatter__tip" style={{ left: `${tip.left}%`, top: `${tip.top}%` }}>
            <b>{activePoint.name}</b>
            <span className="v3-ky-scatter__tip-meta">
              <i style={{ background: levelMeta(activePoint.level).color }} />
              {activePoint.level} · {activePoint.province || '省份未标注'}
            </span>
            <div className="v3-ky-scatter__tip-grid">
              <span>招生 <em>{activePoint.enroll} 人</em></span>
              <span>录取均分 <em>{num(activePoint.admitAvg, 1)}</em></span>
              <span>复录比 <em>{activePoint.retestRatio == null ? '—' : num(activePoint.retestRatio, 2)}</em></span>
            </div>
          </div>
        ) : null}

        {!visible.length ? (
          <div className="v3-ky-scatter__hidden-note">
            <Layers size={20} />
            <span>当前层级已全部隐藏，点击上方图例恢复显示。</span>
          </div>
        ) : null}
      </div>

      <p className="v3-ky-scatter__size-note">
        <i aria-hidden="true" />
        气泡大小代表复录比，复录比越高，气泡越大；横轴为拟招生人数，纵轴为录取均分。
      </p>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function KaoyanScatter() {
  const [data, setData] = useState({ items: [], available_years: [], year: null })
  /* 年份不预设：null 表示由后端决定库内最新年份。 */
  const [year, setYear] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [hiddenLevels, setHiddenLevels] = useState(() => new Set())

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const d = await kaoyanApi.scatter(year == null ? {} : { year })
      setData(d?.items ? d : { items: [], available_years: [], year: null })
      return true
    } catch (e) {
      setError(e?.message || '散点数据加载失败')
      setData({ items: [], available_years: [], year: null })
      return false
    } finally {
      setLoading(false)
    }
  }, [year])

  useEffect(() => { load() }, [load])

  const items = Array.isArray(data.items) ? data.items : []
  const years = Array.isArray(data.available_years) ? data.available_years : []

  const levels = useMemo(() => {
    const seen = new Set(items.map(levelOf))
    const ordered = LEVEL_ORDER.filter((level) => seen.has(level))
    const extra = [...seen].filter((level) => !LEVEL_ORDER.includes(level)).sort()
    return [...ordered, ...extra]
  }, [items])

  useEffect(() => {
    setHiddenLevels((prev) => {
      const next = new Set([...prev].filter((level) => levels.includes(level)))
      return next.size === prev.size ? prev : next
    })
  }, [levels])

  const points = useMemo(() => {
    const valid = items
      .map((item, i) => {
        const enroll = Number(item.enroll)
        const admitAvg = Number(item.admit_avg)
        if (!Number.isFinite(enroll) || !Number.isFinite(admitAvg) || enroll <= 0) return null
        const ratio = Number(item.retest_ratio)
        return {
          i,
          name: item.name || '未命名院校',
          level: levelOf(item),
          province: item.province || '',
          enroll,
          admitAvg,
          retestRatio: Number.isFinite(ratio) ? ratio : null,
          r: Number.isFinite(ratio) ? Math.min(16, Math.max(4, ratio * 2.6)) : 4.5,
        }
      })
      .filter(Boolean)
    return valid
  }, [items])

  const visibleItems = useMemo(
    () => items.filter((item) => !hiddenLevels.has(levelOf(item))),
    [items, hiddenLevels],
  )

  const chartReady = points.length > 0
  const stats = useMemo(() => {
    const enrollVals = items.map((item) => Number(item.enroll)).filter((n) => Number.isFinite(n) && n > 0)
    const avgVals = items.map((item) => Number(item.admit_avg)).filter((n) => Number.isFinite(n) && n > 0)
    const ratioVals = items.map((item) => Number(item.retest_ratio)).filter((n) => Number.isFinite(n) && n > 0)
    return {
      totalEnroll: enrollVals.reduce((sum, n) => sum + n, 0),
      avgAdmit: mean(avgVals),
      medianRatio: medians(ratioVals),
    }
  }, [items])

  const toggleLevel = (level) => {
    setHiddenLevels((prev) => {
      const next = new Set(prev)
      if (next.has(level)) next.delete(level)
      else next.add(level)
      return next
    })
  }

  const yearText = data.year ?? year ?? '—'
  const headerSub = loading
    ? '正在读取招生分布数据…'
    : error
      ? '招生分布数据加载失败'
      : items.length
        ? `${items.length} 所院校 · 招生 ${stats.totalEnroll} 人 · 气泡大小表示复录比`
        : '招生人数、录取均分与复录比的分布视图'

  return (
    <div className="v3-stack v3-ky">
      <PageHeader
        eyebrow="SCATTER · 招生分布"
        title="招生人数分布"
        sub={headerSub}
        actions={(
          <>
            <IconButton label="刷新招生分布数据" icon={<RefreshCw size={17} />} onClick={load} disabled={loading} />
            <Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">
              浏览院校库 <ArrowRight size={15} />
            </Link>
          </>
        )}
      />

      <Tile span={12} variant="hero" className="v3-ky-hero">
        <div className="v3-ky-hero__body">
          <div className="v3-ky-hero__copy">
            <span className="v3-eyebrow v3-ky-hero__eyebrow"><BarChart3 size={13} /> 招生 × 分数</span>
            <h2>招生规模大，<br />不一定代表更好考。</h2>
            <p>
              横轴是拟招生人数，纵轴是录取均分，气泡大小对应复录比。
              把「招得多」和「录得高」放在同一张图里，比单看一条分数线更接近真实竞争格局。
            </p>
            <div className="v3-ky-hero__actions">
              <span className="v3-ky-hero__pill"><Target size={14} /> {yearText === '—' ? '年份待导入' : `${yearText} 年`}</span>
              <span className="v3-ky-hero__pill"><Layers size={14} /> {levels.length || '—'} 个层级</span>
              <span className="v3-ky-hero__pill"><Sparkles size={14} /> 气泡 = 复录比</span>
            </div>
          </div>
          <div className="v3-ky-hero__stats">
            <div className="v3-ky-hero__stat">
              <b>{items.length || '—'}</b>
              <span>院校数</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{items.length ? stats.totalEnroll : '—'}</b>
              <span>招生总数</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{stats.avgAdmit == null ? '—' : num(stats.avgAdmit, 1)}</b>
              <span>平均录取分</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{stats.medianRatio == null ? '—' : num(stats.medianRatio, 2)}</b>
              <span>复录比中位数</span>
            </div>
          </div>
        </div>
      </Tile>

      <Tile span={12} className="v3-ky-scatter-panel">
        <div className="v3-ky-scatter-head">
          <div>
            <h2>招生与录取分布</h2>
            <p>颜色区分院校层级，点击图例可暂时隐藏该层级。</p>
          </div>
          <div className="v3-ky-scatter-tools">
            {years.length > 0 ? (
              <label className="v3-ky-map-year">
                <span>数据年份</span>
                <select
                  className="v3-select"
                  aria-label="选择年份"
                  value={data.year ?? year ?? ''}
                  onChange={(e) => {
                    setHiddenLevels(new Set())
                    setYear(Number(e.target.value))
                  }}
                >
                  {years.map((y) => <option key={y} value={y}>{y} 年</option>)}
                </select>
              </label>
            ) : (
              <Badge tone="outline">暂无年份</Badge>
            )}
            <Badge tone="outline">{visibleItems.length} / {items.length} 所</Badge>
          </div>
        </div>

        {loading ? (
          <div className="v3-ky-scatter-skeleton">
            <Skeleton height={470} />
          </div>
        ) : error ? (
          <Empty
            icon={<Database size={26} />}
            title="招生分布数据加载失败"
            text={error}
            action={<Button variant="tonal" onClick={load}>重新加载</Button>}
          />
        ) : items.length === 0 ? (
          <Empty
            icon={<BarChart3 size={26} />}
            title={years.length === 0 ? '院校库还没有招生数据' : `${data.year ?? '该'} 年还没有可绘制的招生数据`}
            text={years.length === 0
              ? '散点图依赖各院校的招生人数与录取均分。招生数据入库后，这里会按库里的真实年份出图。'
              : '散点图需要「拟招生人数 + 录取均分」同时有值。该年份目前可能只采到录取分、还缺招生人数，补齐后会自动出图。'}
            action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">浏览院校库</Link>}
          />
        ) : !chartReady ? (
          <Empty
            icon={<BarChart3 size={26} />}
            title="暂无可绘制的坐标数据"
            text="当前年份的院校记录缺少「拟招生人数」或「录取均分」，无法定位气泡。下方表格保留原始记录。"
            action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">浏览院校库</Link>}
          />
        ) : (
          <>
            {hiddenLevels.size > 0 ? (
              <Alert tone="info" className="v3-ky-scatter-alert">
                已隐藏 {hiddenLevels.size} 个层级，图表与明细同步筛选。
                <Button size="sm" variant="text" onClick={() => setHiddenLevels(new Set())}>恢复全部</Button>
              </Alert>
            ) : null}
            <ScatterChart
              points={points}
              hiddenLevels={hiddenLevels}
              onToggleLevel={toggleLevel}
              levels={levels}
            />
          </>
        )}
      </Tile>

      {items.length > 0 && !loading && !error ? (
        <section className="v3-ky-section">
          <div className="v3-ky-section__head">
            <div>
              <h2>院校数据明细 <span className="v3-ky-section__count">{visibleItems.length} 所</span></h2>
              <p>招生人数与录取均分来自招生记录；复录比为空时显示 —。</p>
            </div>
            {items.length > 50 ? <Badge tone="outline">仅显示前 50 条</Badge> : null}
          </div>
          <Tile className="v3-ky-table-tile">
            {visibleItems.length === 0 ? (
              <Empty
                icon={<Layers size={24} />}
                title="所有层级都已隐藏"
                text="上方图例可以逐层恢复，或点击「恢复全部」查看完整明细。"
                action={<Button variant="tonal" onClick={() => setHiddenLevels(new Set())}>恢复全部</Button>}
              />
            ) : (
              <>
                <div className="v3-table-wrap">
                  <table className="v3-table">
                    <thead>
                      <tr>
                        <th>院校</th>
                        <th>层级</th>
                        <th>省份</th>
                        <th>拟招生</th>
                        <th>录取均分</th>
                        <th>复录比</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleItems.slice(0, 50).map((item, i) => (
                        <tr key={`${item.name}-${i}`}>
                          <td>
                            <b className="v3-ky-table-school">{item.name || '未命名院校'}</b>
                          </td>
                          <td>
                            <span className="v3-ky-level">
                              <i style={{ background: levelMeta(levelOf(item)).color }} />
                              {levelOf(item)}
                            </span>
                          </td>
                          <td>{item.province || '—'}</td>
                          <td>{item.enroll == null ? '—' : item.enroll}</td>
                          <td>{item.admit_avg == null ? '—' : num(item.admit_avg, 1)}</td>
                          <td>{item.retest_ratio == null ? '—' : num(item.retest_ratio, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {visibleItems.length > 50 ? (
                  <p className="v3-ky-table-more">共 {visibleItems.length} 所，仅显示前 50 条；可用层级图例缩小范围。</p>
                ) : null}
              </>
            )}
          </Tile>
        </section>
      ) : null}

      <p className="v3-ky-footnote">
        <School size={13} /> 散点数据来自 /kaoyan/analysis/scatter；只绘制同时具备招生人数与录取均分的院校，不为缺失值补零。
      </p>
    </div>
  )
}
