import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import EChart from '../../components/EChart'
import { readMigrated, ukey } from '../../utils/userKeys'
import { chartTheme } from '../charts'
import {
  AnimatedNumber, Badge, Button, Card, CardHead, Empty, Input, LoadingState, PageHeader,
  Tile, toast, toastWarn, useClickOutside, useMedia,
} from '../ui'
import {
  AlertCircle, ArrowRight, CalendarClock, Gauge, ListChecks, Plus, School, Search, X,
} from '../icons'
import '../styles/kaoyan-core-v3.css'

/* ==========================================================================
   院校对比 · Aurora v3
   对比口径与旧版一致：先选 2–5 所，再由 /analysis/compare 返回各校
   最新一年的最低院线、拟招人数、录取均分；雷达图只使用三项可信指标。
   ========================================================================== */

const CMP_KEY = 'ky_compare_school_ids'
const MAX_CMP = 5

function useThemeMode() {
  const read = () => (typeof document !== 'undefined' && document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')
  const [mode, setMode] = useState(read)
  useEffect(() => {
    const obs = new MutationObserver(() => setMode(read()))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  return mode
}

function levelTone(level) {
  if (level === '985') return 'danger'
  if (level === '211') return 'primary'
  if (level === '双一流') return 'success'
  return undefined
}

const initialSelected = () => {
  try {
    const ids = readMigrated(CMP_KEY, [])
    return (Array.isArray(ids) ? ids : []).map((id) => ({ id, name: '' }))
  } catch {
    return []
  }
}

export default function KaoyanCompare() {
  const [selected, setSelected] = useState(initialSelected)
  const [allSchools, setAllSchools] = useState([])
  const [keyword, setKeyword] = useState('')
  const [showCandidates, setShowCandidates] = useState(false)
  const [result, setResult] = useState({ items: [] })
  const [compared, setCompared] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [libLoaded, setLibLoaded] = useState(false)

  const searchRef = useRef(null)
  const compareSeq = useRef(0)
  const mode = useThemeMode()
  const isMobile = useMedia('(max-width: 760px)')
  const isDark = mode === 'dark'

  useClickOutside(searchRef, () => setShowCandidates(false))

  // 拉全量院校（page_size 上限 200，循环翻页；失败不阻断按 ID 对比）
  useEffect(() => {
    let alive = true
    const fetchAll = async () => {
      const PAGE = 200
      let page = 1
      const acc = []
      try {
        for (;;) {
          const data = await kaoyanApi.schools({ page_size: PAGE, page })
          const list = data?.items || data?.list || data || []
          if (!Array.isArray(list) || list.length === 0) break
          acc.push(...list.map((s) => ({ id: s.id, name: s.name })))
          if (list.length < PAGE) break
          page += 1
          if (page > 20) break
        }
      } catch { /* 单页失败即停，已拉到的仍可用 */ }
      if (alive) {
        setAllSchools(acc)
        setLibLoaded(true)
      }
    }
    fetchAll()
    return () => { alive = false }
  }, [])

  // 对比清单与原院校库、详情页共享，增删后同步回本地键
  useEffect(() => {
    try {
      localStorage.setItem(ukey(CMP_KEY), JSON.stringify(selected.map((s) => s.id)))
    } catch { /* 隐私模式 */ }
  }, [selected])

  const schoolName = (id) => {
    const found = allSchools.find((x) => String(x.id) === String(id))
    return found?.name || ''
  }

  const resolved = selected.map((s) => ({ id: s.id, name: s.name || schoolName(s.id) }))

  const candidates = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return []
    return allSchools
      .filter((s) => (s.name || '').toLowerCase().includes(kw))
      .filter((s) => !selected.some((x) => String(x.id) === String(s.id)))
      .slice(0, 8)
  }, [keyword, allSchools, selected])

  const latestYear = useMemo(() => {
    const years = []
    result.items.forEach((item) => {
      ;(item.recent_scores || []).forEach((s) => { if (s.year != null) years.push(Number(s.year)) })
      ;(item.recent_admissions || []).forEach((a) => { if (a.year != null) years.push(Number(a.year)) })
    })
    const valid = years.filter((y) => Number.isFinite(y))
    return valid.length ? Math.max(...valid) : null
  }, [result])

  const commitSelection = (next) => {
    compareSeq.current += 1
    setSelected(next)
    setResult({ items: [] })
    setCompared(false)
    setError(null)
    setLoading(false)
  }

  const addSchool = (s) => {
    if (selected.length >= MAX_CMP) {
      toastWarn(`最多对比 ${MAX_CMP} 所院校`)
      return false
    }
    if (selected.some((x) => String(x.id) === String(s.id))) return false
    commitSelection([...selected, { id: s.id, name: s.name }])
    setKeyword('')
    setShowCandidates(false)
    return true
  }

  const removeSchool = (id) => {
    commitSelection(selected.filter((x) => String(x.id) !== String(id)))
    setShowCandidates(false)
  }

  // 支持名称模糊匹配、数字 ID，以及一次输入多个（逗号 / 空格分隔）
  const addByIds = () => {
    const parts = keyword.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
    if (!parts.length) return

    let working = [...selected]
    let added = 0
    let maxed = false
    const notFound = []

    const tryAdd = (item) => {
      if (working.length >= MAX_CMP) {
        maxed = true
        return false
      }
      if (working.some((x) => String(x.id) === String(item.id))) return false
      working.push({ id: item.id, name: item.name })
      added += 1
      return true
    }

    parts.forEach((raw) => {
      if (/^\d+$/.test(raw)) {
        const id = Number(raw)
        if (!working.some((x) => String(x.id) === String(id))) {
          tryAdd({ id, name: schoolName(id) || `院校 #${id}` })
        }
        return
      }
      const kw = raw.toLowerCase()
      const hits = allSchools
        .filter((s) => (s.name || '').toLowerCase().includes(kw))
        .filter((s) => !working.some((x) => String(x.id) === String(s.id)))
      if (hits.length === 0) {
        notFound.push(raw)
        return
      }
      const exact = hits.find((s) => s.name === raw) || hits[0]
      if (tryAdd(exact) && hits.length > 1) {
        toast(`「${raw}」匹配到 ${hits.length} 所，已添加「${exact.name}」`)
      }
    })

    if (added) commitSelection(working)
    setKeyword('')
    setShowCandidates(false)

    if (maxed) toastWarn(`最多对比 ${MAX_CMP} 所院校`)
    if (notFound.length) toast(`未找到院校：${notFound.join('、')}（可输入 ID 或完整名称）`)
    else if (added) toast(`已添加 ${added} 所院校`)
  }

  const clearAll = () => {
    commitSelection([])
    setKeyword('')
  }

  const compareNow = () => {
    if (selected.length < 2) {
      toast('请至少选择 2 所院校')
      return
    }
    const seq = compareSeq.current + 1
    compareSeq.current = seq
    setLoading(true)
    setError(null)
    setCompared(false)
    kaoyanApi.compare(selected.map((s) => s.id).join(','))
      .then((data) => {
        if (seq !== compareSeq.current) return
        setResult(data || { items: [] })
        setCompared(true)
      })
      .catch((e) => {
        if (seq !== compareSeq.current) return
        setError(e?.message || '对比数据加载失败')
        toast('对比数据加载失败')
      })
      .finally(() => {
        if (seq === compareSeq.current) setLoading(false)
      })
  }

  const radarOption = useMemo(() => {
    const items = result.items || []
    if (!items.length) return null
    const t = chartTheme(isDark)
    return {
      color: t.color,
      textStyle: t.textStyle,
      tooltip: { ...t.tooltip, trigger: 'item' },
      legend: {
        data: items.map((i) => i.name),
        top: 0,
        type: 'scroll',
        itemWidth: 10,
        itemHeight: 10,
        icon: 'roundRect',
        textStyle: { color: t.textStyle.color, fontSize: 11 },
      },
      radar: {
        indicator: [
          { name: '最低院线', max: 450 },
          { name: '拟招人数', max: 500 },
          { name: '录取均分', max: 420 },
        ],
        center: ['50%', '57%'],
        radius: '62%',
        splitNumber: 4,
        axisName: { color: t.textStyle.color, fontSize: 11 },
        axisLine: { lineStyle: { color: t.axisLine.lineStyle.color } },
        splitLine: { lineStyle: { color: t.splitLine.lineStyle.color } },
        splitArea: {
          areaStyle: {
            color: isDark ? ['#181C25', '#12151D'] : ['#FAFBFE', '#FFFFFF'],
          },
        },
      },
      series: [{
        type: 'radar',
        symbolSize: 4,
        data: items.map((item, index) => {
          const score = item.recent_scores?.[0] || {}
          const adm = item.recent_admissions?.[0] || {}
          const color = t.color[index % t.color.length]
          return {
            name: item.name,
            value: [Number(score.total_line) || 0, Number(adm.enroll_count) || 0, Number(adm.admit_avg_score) || 0],
            itemStyle: { color },
            lineStyle: { color, width: 2 },
            areaStyle: { color, opacity: 0.09 },
          }
        }),
      }],
    }
  }, [result, isDark])

  const header = (
    <PageHeader
      eyebrow="SCHOOL COMPARE · 择校对比"
      title="院校对比"
      sub={`从院校库勾选后跳转至此，或在此搜索添加院校（最多 ${MAX_CMP} 所）`}
      actions={(
        <Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">
          去院校库勾选 <ArrowRight size={15} />
        </Link>
      )}
    />
  )

  /* 院校库为空时整页引导，避免只剩一个无反馈的搜索框 */
  if (libLoaded && allSchools.length === 0 && selected.length === 0) {
    return (
      <div className="kyv3-page">
        {header}
        <Card className="kyv3-empty-lib">
          <Empty
            icon={<School size={26} />}
            title="院校库还没有数据"
            text="先到「院校库」导入院校与分数线数据，之后就能在这里横向对比最低院线、拟招人数与录取均分。"
            action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">前往院校库</Link>}
          />
        </Card>
      </div>
    )
  }

  const statTiles = [
    { key: 'selected', label: '已选院校', icon: ListChecks, value: selected.length, unit: '所' },
    { key: 'library', label: '院校库', icon: School, value: allSchools.length, unit: '所' },
    { key: 'metrics', label: '对比指标', icon: Gauge, value: 3, unit: '项' },
    { key: 'year', label: '数据年份', icon: CalendarClock, value: latestYear, unit: '年' },
  ]

  const canCompare = selected.length >= 2 && !loading

  return (
    <div className="kyv3-page">
      {header}

      <div className="v3-bento">
        {statTiles.map((s) => {
          const Icon = s.icon
          return (
            <Tile key={s.key} span={3} className="kyv3-stat-tile">
              <span className="v3-tile__label"><Icon size={14} /> {s.label}</span>
              <span className="v3-tile__value">
                {s.value == null
                  ? <em>待对比</em>
                  : (
                    <>
                      <AnimatedNumber value={s.value} format={(n) => Math.round(n).toLocaleString('zh-CN')} />
                      <em>{s.unit}</em>
                    </>
                  )}
              </span>
            </Tile>
          )
        })}
      </div>

      <Card className="kyv3-compare-panel">
        <CardHead
          icon={<ListChecks size={17} />}
          title="对比清单"
          sub="选择 2–5 所院校，横向查看最低院线、拟招人数与录取均分"
          actions={<Badge tone={selected.length >= MAX_CMP ? 'warning' : 'primary'}>{selected.length} / {MAX_CMP} 所</Badge>}
        />

        {resolved.length ? (
          <div className="kyv3-selected-chips">
            {resolved.map((s) => (
              <span key={s.id} className="kyv3-selected-chip">
                {s.name || `院校 #${s.id}`}
                <button type="button" aria-label={`移除 ${s.name || s.id}`} onClick={() => removeSchool(s.id)}>
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        ) : (
          <div className="kyv3-selected-empty">
            <ListChecks size={15} />
            尚未选择院校，可在下方搜索添加，或前往院校库勾选「对比」。
          </div>
        )}

        <div className="kyv3-compare-search" ref={searchRef}>
          <Input
            icon={<Search size={16} />}
            type="search"
            aria-label="搜索院校名称添加对比"
            placeholder="搜索院校名称，或输入院校 ID，可一次输入多个…"
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value)
              setShowCandidates(true)
            }}
            onFocus={() => { if (keyword.trim()) setShowCandidates(true) }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); addByIds() }
              if (e.key === 'Escape') setShowCandidates(false)
            }}
          />
          <Button onClick={addByIds} disabled={!keyword.trim()} icon={<Plus size={15} />}>添加</Button>
          {showCandidates && candidates.length > 0 ? (
            <div className="kyv3-candidates" role="listbox" aria-label="院校搜索候选">
              {candidates.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  role="option"
                  className="kyv3-candidate"
                  onClick={() => addSchool(s)}
                >
                  <span>{s.name}</span>
                  <small>#{s.id}</small>
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="kyv3-compare-controls">
          <Button onClick={compareNow} disabled={!canCompare} loading={loading}>
            {loading ? '对比中…' : `开始对比（已选 ${selected.length}）`}
          </Button>
          {selected.length > 0 ? (
            <Button variant="text" onClick={clearAll}>清空</Button>
          ) : null}
          {!libLoaded ? (
            <span className="v3-caption" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span className="v3-spinner" style={{ width: 12, height: 12 }} /> 院校库加载中…
            </span>
          ) : (
            <span className="v3-caption">支持名称、数字 ID，或「清华 北大」批量添加</span>
          )}
        </div>
      </Card>

      {!loading && !error && !result.items.length && selected.length < 2 ? (
        <Card className="kyv3-guide">
          <Empty
            icon={<ListChecks size={26} />}
            title="先选 2–5 所院校"
            text="在院校库列表勾选「对比」后点底部「开始对比」，或直接在上方搜索院校名称添加。对比会展示最低院线、拟招人数与录取均分三项可信指标。"
            action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">去院校库挑选</Link>}
          />
          <div className="kyv3-guide-metrics">
            <div>
              <b>最低院线</b>
              <span>看门槛下限，已剔除管理类联考专业</span>
            </div>
            <div>
              <b>拟招人数</b>
              <span>看招生规模，取当年各专业计划数之和</span>
            </div>
            <div>
              <b>录取均分</b>
              <span>看实际竞争强度，取各专业录取均分均值</span>
            </div>
          </div>
        </Card>
      ) : null}

      {loading ? (
        <Card>
          <LoadingState text="对比中…" />
        </Card>
      ) : error ? (
        <Card>
          <Empty
            icon={<AlertCircle size={26} />}
            title="对比数据加载失败"
            text={error}
            action={<Button variant="tonal" onClick={compareNow}>重新对比</Button>}
          />
        </Card>
      ) : compared && !result.items.length && selected.length >= 2 ? (
        <Card>
          <Empty
            icon={<Gauge size={26} />}
            title="暂无可比数据"
            text="后端没有返回这几所院校的可比数据，换几所院校或稍后再试。"
            action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">去院校库挑选</Link>}
          />
        </Card>
      ) : result.items.length > 0 ? (
        <>
          <Card className="kyv3-radar-card">
            <div className="kyv3-radar-head">
              <h2>三项指标雷达 · 各校最新一年</h2>
              <p>最低院线看门槛下限，拟招人数看规模，录取均分看实际竞争强度</p>
            </div>
            {radarOption ? (
              <EChart
                option={radarOption}
                style={{ height: isMobile ? 320 : 390, marginTop: 8 }}
                emptyText="暂无可绘制数据"
              />
            ) : null}
            <p className="kyv3-radar-note">
              最低院线 = 该校当年普通专业院线的最低总分。已剔除 MBA / MPA / MPAcc 等管理类联考专业
              （考 199 综合、总分仅 300，不剔除会让所有院校都显示同一条国家线）；它反映门槛下限，不代表具体专业难度。
            </p>
          </Card>

          <Card className="kyv3-compare-table-card">
            <div className="kyv3-compare-title">最新一年逐校对比</div>
            <div className="kyv3-compare-sub">
              拟招人数为当年各专业计划招生数之和；录取均分为各专业录取均分的平均值
            </div>
            <div className="v3-table-wrap kyv3-compare-table-wrap">
              <table className="v3-table">
                <thead>
                  <tr>
                    <th>院校</th>
                    <th>层级</th>
                    <th>省份</th>
                    <th>年份</th>
                    <th>最低院线</th>
                    <th>拟招人数</th>
                    <th>录取均分</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((item) => {
                    const score = item.recent_scores?.[0] || {}
                    const adm = item.recent_admissions?.[0] || {}
                    const olderScores = (item.recent_scores || []).slice(1).filter((s) => s.total_line != null)
                    return (
                      <tr key={item.id}>
                        <td>
                          <Link to={`/kaoyan/schools/${item.id}`} className="kyv3-compare-school">
                            {item.name}
                          </Link>
                        </td>
                        <td>
                          {item.level
                            ? <Badge tone={levelTone(item.level)}>{item.level}</Badge>
                            : '—'}
                        </td>
                        <td>{item.province || '—'}</td>
                        <td className="is-year">{score.year ?? adm.year ?? '—'}</td>
                        <td>
                          <span className="kyv3-compare-value">{score.total_line ?? '—'}</span>
                          {olderScores.length > 0 ? (
                            <div className="kyv3-older-scores">
                              {olderScores.map((s) => `${s.year}: ${s.total_line}`).join(' · ')}
                            </div>
                          ) : null}
                        </td>
                        <td>{adm.enroll_count ?? '—'}</td>
                        <td>{adm.admit_avg_score ?? '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  )
}
