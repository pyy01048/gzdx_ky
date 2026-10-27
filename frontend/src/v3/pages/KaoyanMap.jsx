import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import { toEchartsProvince } from '../../utils/province'
import {
  Alert, Badge, Button, Chip, Empty, IconButton, PageHeader, Skeleton, Tile,
} from '../ui'
import {
  ArrowRight, Compass, Database, Map as MapIcon, RefreshCw, School, Target,
} from '../icons'
import '../styles/kaoyan-aux-v3.css'

/* -------------------------------------------------------------------------- */
/* China basemap                                                              */
/* -------------------------------------------------------------------------- */

const GEO_URL = `${import.meta.env.BASE_URL}china.json`
const VIEW_W = 820
const VIEW_H = 560
const PAD = 30
/* 海南行政区包含南海诸岛，若按全部坐标定界会把大陆压成一条。
   丢掉北纬 17.2° 以南的碎岛环，只保留海南本岛与沿海岛屿。 */
const MIN_RING_LAT = 17.2

let chinaGeoCache = null

function fetchChinaGeo() {
  if (chinaGeoCache) return Promise.resolve(chinaGeoCache)
  return fetch(GEO_URL)
    .then((res) => {
      if (!res.ok) throw new Error(`底图请求失败（HTTP ${res.status}）`)
      return res.json()
    })
    .then((geo) => {
      if (!geo || !Array.isArray(geo.features)) throw new Error('底图数据格式异常')
      chinaGeoCache = geo
      return geo
    })
}

function shortProvince(name) {
  return String(name || '')
    .replace(/(壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|省|市)$/u, '')
    .trim()
}

/* 小省份标注相互压盖，给直辖市 / 特别行政区做一点偏移。 */
const LABEL_OFFSET = {
  北京: [-9, -7],
  天津: [10, 7],
  上海: [13, 2],
  江苏: [8, -2],
  浙江: [10, 8],
  香港: [12, 12],
  澳门: [-12, 15],
}

function projectChina(geo) {
  let minLon = Infinity
  let maxLon = -Infinity
  let minLat = Infinity
  let maxLat = -Infinity
  const features = []

  geo.features.forEach((feature) => {
    const name = feature?.properties?.name
    if (!name || !feature.geometry) return
    const polygons = feature.geometry.type === 'Polygon'
      ? [feature.geometry.coordinates]
      : Array.isArray(feature.geometry.coordinates) ? feature.geometry.coordinates : []
    const rings = []
    polygons.forEach((polygon) => {
      if (!Array.isArray(polygon)) return
      polygon.forEach((ring) => {
        if (!Array.isArray(ring) || ring.length < 3) return
        let ringMaxLat = -Infinity
        ring.forEach((point) => {
          if (Array.isArray(point) && Number.isFinite(point[0]) && Number.isFinite(point[1])) {
            if (point[1] > ringMaxLat) ringMaxLat = point[1]
          }
        })
        if (ringMaxLat < MIN_RING_LAT) return
        rings.push(ring)
        ring.forEach((point) => {
          if (!Array.isArray(point)) return
          const [lon, lat] = point
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) return
          if (lon < minLon) minLon = lon
          if (lon > maxLon) maxLon = lon
          if (lat < minLat) minLat = lat
          if (lat > maxLat) maxLat = lat
        })
      })
    })
    if (!rings.length) return
    features.push({
      name,
      short: shortProvince(name),
      rings,
      centroid: Array.isArray(feature.properties.centroid)
        ? feature.properties.centroid
        : Array.isArray(feature.properties.center) ? feature.properties.center : null,
    })
  })

  if (!Number.isFinite(minLon) || !features.length) return null

  const midLat = ((minLat + maxLat) / 2) * (Math.PI / 180)
  const lonScale = Math.cos(midLat)
  const rawW = (maxLon - minLon) * lonScale
  const rawH = maxLat - minLat
  const availW = VIEW_W - PAD * 2
  const availH = VIEW_H - PAD * 2
  const scale = Math.min(availW / rawW, availH / rawH)
  const offsetX = (VIEW_W - rawW * scale) / 2
  const offsetY = (VIEW_H - rawH * scale) / 2

  const project = (point) => [
    offsetX + (point[0] - minLon) * lonScale * scale,
    offsetY + (maxLat - point[1]) * scale,
  ]

  const projected = features.map((feature) => {
    let d = ''
    feature.rings.forEach((ring) => {
      ring.forEach((point, index) => {
        const [x, y] = project(point)
        d += `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
      })
      d += 'Z'
    })
    const center = feature.centroid ? project(feature.centroid) : null
    return { ...feature, d, center }
  })

  return { features: projected }
}

/* -------------------------------------------------------------------------- */
/* Formatting                                                                 */
/* -------------------------------------------------------------------------- */

const METRICS = [
  { value: 'value', label: '院校数量', unit: '所' },
  { value: 'avg_line', label: '平均分数线', unit: '分' },
  { value: 'avg_retest_ratio', label: '平均复录比', unit: '' },
]

function num(value, digits = 1) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function metricText(value, metric) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (metric.value === 'value') return `${Math.round(n)} 所`
  if (metric.value === 'avg_line') return `${num(n, 1)} 分`
  return num(n, 2)
}

function meanOf(items, key) {
  const vals = items
    .map((item) => Number(item[key]))
    .filter((n) => Number.isFinite(n) && n > 0)
  if (!vals.length) return null
  return vals.reduce((sum, n) => sum + n, 0) / vals.length
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function KaoyanMap() {
  const [data, setData] = useState({ items: [], available_years: [], year: null })
  /* null = 交给后端按库内最新年份返回，不在前端写死年份。 */
  const [year, setYear] = useState(null)
  const [metric, setMetric] = useState('value')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [geo, setGeo] = useState(null)
  const [geoError, setGeoError] = useState('')
  const [hoverName, setHoverName] = useState(null)
  const [pinnedName, setPinnedName] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const d = await kaoyanApi.heatmap(year == null ? {} : { year })
      setData(d?.items ? d : { items: [], available_years: [], year: null })
      return true
    } catch (e) {
      setError(e?.message || '地图数据加载失败')
      setData({ items: [], available_years: [], year: null })
      return false
    } finally {
      setLoading(false)
    }
  }, [year])

  useEffect(() => { load() }, [load])

  const loadGeo = useCallback(() => {
    setGeoError('')
    fetchChinaGeo()
      .then((d) => setGeo(d))
      .catch((e) => {
        setGeo(null)
        setGeoError(e?.message || '中国底图加载失败')
      })
  }, [])

  useEffect(() => { loadGeo() }, [loadGeo])

  const projection = useMemo(() => (geo ? projectChina(geo) : null), [geo])

  const metricMeta = METRICS.find((m) => m.value === metric) || METRICS[0]
  const items = Array.isArray(data.items) ? data.items : []
  const years = Array.isArray(data.available_years) ? data.available_years : []
  const maxVal = useMemo(
    () => Math.max(...items.map((item) => Number(item[metric]) || 0), 1),
    [items, metric],
  )

  const itemByMapName = useMemo(() => {
    const map = new Map()
    items.forEach((item) => {
      const mapName = toEchartsProvince(item.name)
      if (mapName) map.set(mapName, item)
    })
    return map
  }, [items])

  const sortedItems = useMemo(
    () => [...items].sort((a, b) => (Number(b[metric]) || 0) - (Number(a[metric]) || 0)),
    [items, metric],
  )

  const totalSchools = useMemo(
    () => items.reduce((sum, item) => sum + (Number(item.value) || 0), 0),
    [items],
  )
  const avgLine = useMemo(() => meanOf(items, 'avg_line'), [items])
  const avgRatio = useMemo(() => meanOf(items, 'avg_retest_ratio'), [items])
  const activeMapName = hoverName || pinnedName
  const activeItem = activeMapName ? itemByMapName.get(activeMapName) : null
  const activeFeature = activeMapName && projection
    ? projection.features.find((feature) => feature.name === activeMapName)
    : null
  const hasMap = projection && projection.features.length > 0

  const refresh = () => { load() }

  const yearText = data.year ?? year ?? '—'
  const headerSub = loading
    ? '正在读取区域热力数据…'
    : error
      ? '区域热力数据加载失败'
      : items.length
        ? `${items.length} 个省份有数据 · ${totalSchools} 所院校 · 当前按${metricMeta.label}着色`
        : '全国各省院校分布与录取难度可视化'

  const tooltipLeft = activeFeature?.center
    ? Math.min(88, Math.max(12, (activeFeature.center[0] / VIEW_W) * 100))
    : 50
  const tooltipTop = activeFeature?.center
    ? Math.min(86, Math.max(10, (activeFeature.center[1] / VIEW_H) * 100))
    : 30

  return (
    <div className="v3-stack v3-ky">
      <PageHeader
        eyebrow="MAP · 区域热力"
        title="区域择校热力图"
        sub={headerSub}
        actions={(
          <>
            <IconButton label="刷新区域热力数据" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading} />
            <Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">
              浏览院校库 <ArrowRight size={15} />
            </Link>
          </>
        )}
      />

      <Tile span={12} variant="hero" className="v3-ky-hero v3-ky-map-hero">
        <div className="v3-ky-hero__body">
          <div className="v3-ky-hero__copy">
            <span className="v3-eyebrow v3-ky-hero__eyebrow"><MapIcon size={13} /> 空间视角</span>
            <h2>先看省份，<br />再决定把志愿落在哪。</h2>
            <p>
              按省份聚合库内院校数量、平均分数线与平均复录比。
              热力越深代表当前指标越高；悬停或点击省份可查看明细，没有数据的省份保持中性底色。
            </p>
            <div className="v3-ky-hero__actions">
              <span className="v3-ky-hero__pill"><Compass size={14} /> {yearText === '—' ? '年份待导入' : `${yearText} 年数据`}</span>
              <span className="v3-ky-hero__pill"><School size={14} /> {totalSchools} 所院校</span>
              <span className="v3-ky-hero__pill"><Target size={14} /> {metricMeta.label}</span>
            </div>
          </div>
          <div className="v3-ky-hero__stats">
            <div className="v3-ky-hero__stat">
              <b>{items.length || '—'}</b>
              <span>覆盖省份</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{items.length ? totalSchools : '—'}</b>
              <span>院校总数</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{avgLine == null ? '—' : num(avgLine, 1)}</b>
              <span>平均分数线</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{avgRatio == null ? '—' : num(avgRatio, 2)}</b>
              <span>平均复录比</span>
            </div>
          </div>
        </div>
      </Tile>

      <Tile span={12} className="v3-ky-map-panel">
        <div className="v3-ky-map-head">
          <div>
            <h2>中国院校分布</h2>
            <p>颜色按「{metricMeta.label}」映射，数值范围 0 – {num(maxVal, metric === 'avg_retest_ratio' ? 2 : 0)}</p>
          </div>
          <div className="v3-ky-map-toolbar">
            {years.length > 0 ? (
              <label className="v3-ky-map-year">
                <span>数据年份</span>
                <select
                  className="v3-select"
                  aria-label="选择年份"
                  value={data.year ?? year ?? ''}
                  onChange={(e) => { setPinnedName(null); setYear(Number(e.target.value)) }}
                >
                  {years.map((y) => <option key={y} value={y}>{y} 年</option>)}
                </select>
              </label>
            ) : (
              <Badge tone="outline">暂无年份</Badge>
            )}
            <div className="v3-ky-map-metric" role="group" aria-label="选择热力指标">
              {METRICS.map((m) => (
                <Chip key={m.value} active={metric === m.value} onClick={() => setMetric(m.value)}>
                  {m.label}
                </Chip>
              ))}
            </div>
          </div>
        </div>

        {loading ? (
          <div className="v3-ky-map-skeleton">
            <Skeleton height={430} />
          </div>
        ) : error ? (
          <Empty
            icon={<Database size={26} />}
            title="区域热力数据加载失败"
            text={error}
            action={<Button variant="tonal" onClick={load}>重新加载</Button>}
          />
        ) : items.length === 0 ? (
          <Empty
            icon={<MapIcon size={26} />}
            title={years.length === 0 ? '院校库还没有数据' : '该年份没有可展示的省份数据'}
            text={years.length === 0
              ? '导入院校与分数线后，这里会按省份画出真实分布，不使用演示数据。'
              : '换一个年份看看，或到院校库确认该年分数线与招生记录是否已收录。'}
            action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">浏览院校库</Link>}
          />
        ) : (
          <>
            {geoError ? (
              <Alert tone="warning" className="v3-ky-map-alert">
                中国底图加载失败：{geoError}。下方改用省份卡片展示同一份真实数据。
                <Button size="sm" variant="text" onClick={loadGeo}>重试底图</Button>
              </Alert>
            ) : null}

            <div className="v3-ky-map-layout">
              <div className="v3-ky-map-stage">
                {!hasMap ? (
                  geoError ? (
                    <div className="v3-ky-map-fallback">
                      {sortedItems.map((item) => {
                        const pct = maxVal > 0 ? ((Number(item[metric]) || 0) / maxVal) * 100 : 0
                        return (
                          <button
                            key={item.name}
                            type="button"
                            className={`v3-ky-map-fallback__item${pinnedName === toEchartsProvince(item.name) ? ' is-active' : ''}`}
                            onClick={() => setPinnedName(toEchartsProvince(item.name))}
                          >
                            <span>{item.name}</span>
                            <b>{metricText(item[metric], metricMeta)}</b>
                            <i style={{ width: `${Math.max(pct, 3)}%` }} />
                          </button>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="v3-ky-map-skeleton"><Skeleton height={430} /></div>
                  )
                ) : (
                  <>
                    <svg
                      className="v3-ky-map-svg"
                      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
                      role="img"
                      aria-label={`中国各省${metricMeta.label}热力图，${data.year ?? '最新年份'}`}
                    >
                      {projection.features.map((feature) => {
                        const item = itemByMapName.get(feature.name)
                        const raw = item ? Number(item[metric]) : null
                        const ratio = item && Number.isFinite(raw) ? Math.min(Math.max(raw / maxVal, 0), 1) : 0
                        const fill = item && Number.isFinite(raw)
                          ? `color-mix(in srgb, var(--v3-primary) ${Math.round(12 + ratio * 62)}%, var(--v3-surface-2))`
                          : 'var(--v3-surface-1)'
                        const isActive = activeMapName === feature.name
                        const offset = LABEL_OFFSET[feature.short] || [0, 0]
                        const labelPos = feature.center
                          ? [feature.center[0] + offset[0], feature.center[1] + offset[1]]
                          : null
                        return (
                          <g
                            key={feature.name}
                            className={`v3-ky-map-province${isActive ? ' is-active' : ''}${item ? ' has-data' : ''}`}
                            tabIndex={0}
                            role="button"
                            aria-label={`${item?.name || feature.short}，${item ? `${metricMeta.label} ${metricText(raw, metricMeta)}` : '暂无数据'}`}
                            onMouseEnter={() => setHoverName(feature.name)}
                            onMouseLeave={() => setHoverName(null)}
                            onFocus={() => setHoverName(feature.name)}
                            onBlur={() => setHoverName(null)}
                            onClick={() => setPinnedName((prev) => (prev === feature.name ? null : feature.name))}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                setPinnedName((prev) => (prev === feature.name ? null : feature.name))
                              }
                            }}
                          >
                            <path d={feature.d} className="v3-ky-map-province__shape" style={{ fill }} />
                            {item && labelPos ? (
                              <text
                                className="v3-ky-map-label"
                                x={labelPos[0]}
                                y={labelPos[1]}
                                textAnchor="middle"
                                aria-hidden="true"
                              >
                                {item.name || feature.short}
                              </text>
                            ) : null}
                            <title>
                              {item
                                ? `${item.name} · 院校 ${item.value ?? '—'} 所 · 均分 ${item.avg_line ?? '—'} · 复录比 ${item.avg_retest_ratio ?? '—'}`
                                : `${feature.short} · 暂无数据`}
                            </title>
                          </g>
                        )
                      })}
                    </svg>

                    <div className="v3-ky-map-legend" aria-hidden="true">
                      <span>低</span>
                      <i />
                      <span>高</span>
                      <em>{metricMeta.label}</em>
                    </div>

                    {activeFeature ? (
                      <div
                        className="v3-ky-map-tip"
                        style={{ left: `${tooltipLeft}%`, top: `${tooltipTop}%` }}
                      >
                        <b>{activeItem?.name || activeFeature.short}</b>
                        {activeItem ? (
                          <>
                            <span>院校数量 <em>{activeItem.value ?? '—'} 所</em></span>
                            <span>平均分数线 <em>{activeItem.avg_line == null ? '—' : `${num(activeItem.avg_line, 1)} 分`}</em></span>
                            <span>平均复录比 <em>{activeItem.avg_retest_ratio == null ? '—' : num(activeItem.avg_retest_ratio, 2)}</em></span>
                          </>
                        ) : (
                          <span>该省份暂无收录数据</span>
                        )}
                      </div>
                    ) : null}
                  </>
                )}
              </div>

              <aside className="v3-ky-map-rank" aria-label={`${metricMeta.label}省份排行`}>
                <div className="v3-ky-map-rank__head">
                  <h3>省份排行</h3>
                  <span>按{metricMeta.label}</span>
                </div>
                {sortedItems.slice(0, 8).map((item, index) => {
                  const mapName = toEchartsProvince(item.name)
                  const pct = maxVal > 0 ? ((Number(item[metric]) || 0) / maxVal) * 100 : 0
                  return (
                    <button
                      key={item.name}
                      type="button"
                      className={`v3-ky-map-rank__item${pinnedName === mapName ? ' is-active' : ''}`}
                      onClick={() => setPinnedName((prev) => (prev === mapName ? null : mapName))}
                      onMouseEnter={() => setHoverName(mapName)}
                      onMouseLeave={() => setHoverName(null)}
                    >
                      <span className="v3-ky-map-rank__no">{String(index + 1).padStart(2, '0')}</span>
                      <span className="v3-ky-map-rank__name">{item.name}</span>
                      <b>{metricText(item[metric], metricMeta)}</b>
                      <i><em style={{ width: `${Math.max(pct, 3)}%` }} /></i>
                    </button>
                  )
                })}
                {items.length > 8 ? <p className="v3-ky-map-rank__more">另有 {items.length - 8} 个省份，见下方明细</p> : null}
              </aside>
            </div>

            <p className="v3-ky-map-help">
              悬停查看数据，点击省份可固定高亮；键盘可用 Tab 聚焦、Enter 固定。
              底图和省份边界来自本地 GeoJSON，数据只做区域聚合，不代表官方口径。
            </p>
          </>
        )}
      </Tile>

      {items.length > 0 && !loading && !error ? (
        <section className="v3-ky-section">
          <div className="v3-ky-section__head">
            <div>
              <h2>各省数据明细 <span className="v3-ky-section__count">{items.length} 个省份</span></h2>
              <p>按{metricMeta.label}从高到低排序；点击卡片可在上方地图中高亮该省份。</p>
            </div>
            <Badge tone="outline">{data.year ?? '最新年份'} 年</Badge>
          </div>
          <div className="v3-ky-province-grid">
            {sortedItems.map((item) => {
              const mapName = toEchartsProvince(item.name)
              const pct = maxVal > 0 ? ((Number(item[metric]) || 0) / maxVal) * 100 : 0
              const active = pinnedName === mapName
              return (
                <button
                  key={item.name}
                  type="button"
                  className={`v3-ky-province-card${active ? ' is-active' : ''}`}
                  onClick={() => setPinnedName(active ? null : mapName)}
                  aria-pressed={active}
                >
                  <div className="v3-ky-province-card__top">
                    <strong>{item.name || '未标注省份'}</strong>
                    <span>{metricText(item[metric], metricMeta)}</span>
                  </div>
                  <div className="v3-ky-province-card__meta">
                    <span>院校 {item.value ?? '—'} 所</span>
                    <span>均分 {item.avg_line == null ? '—' : num(item.avg_line, 1)}</span>
                    <span>复录比 {item.avg_retest_ratio == null ? '—' : num(item.avg_retest_ratio, 2)}</span>
                  </div>
                  <div className="v3-ky-province-card__bar"><i style={{ width: `${Math.max(pct, 3)}%` }} /></div>
                </button>
              )
            })}
          </div>
        </section>
      ) : null}

      <p className="v3-ky-footnote">
        <MapIcon size={13} /> 热力图数据来自 /kaoyan/analysis/heatmap；省份名按行政区全名匹配本地底图，未收录省份不着色。
      </p>
    </div>
  )
}
