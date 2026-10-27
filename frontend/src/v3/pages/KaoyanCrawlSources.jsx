import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import {
  Alert, Badge, Button, Card, CardHead, Chip, Dialog, Empty, IconButton, Input, PageHeader,
  Select, Skeleton, Tabs, toastErr, toastOk, toastWarn, cx,
} from '../ui'
import {
  CheckCircle2, ChevronLeft, ChevronRight, Database, ExternalLink, Globe, RefreshCw,
  RotateCcw, School, Search, Server, Target, X,
} from '../icons'
import '../styles/admin-ops-v3.css'

/* ============================================================================
   院校采集源（Aurora v3）
   决定哪些院校参与采集；默认全部参与，被排除的院校不会进入后续采集任务。
   同时展示真实数据源注册中心（研招网 / 省考试院 / 院校官网 / 聚合站）。
   ========================================================================== */

const PAGE_SIZE = 30

const SOURCE_TYPE_LABEL = {
  yz: '研招网',
  exam_authority: '省考试院',
  school_official: '院校官网',
  aggregator: '聚合站',
}

const SOURCE_STATUS_LABEL = { active: '启用', paused: '暂停', deprecated: '已弃用' }
const SOURCE_STATUS_TONE = { active: 'success', paused: 'warning', deprecated: 'outline' }

const LEVEL_TONE = (level) => (['985', '211', '双一流'].includes(level) ? 'primary' : 'outline')

export default function KaoyanCrawlSources() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('schools')

  /* ---------- 院校采集开关 ---------- */
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const [draft, setDraft] = useState('')
  const [province, setProvince] = useState('')
  const [level, setLevel] = useState('')
  const [enabledFilter, setEnabledFilter] = useState('')
  const [selected, setSelected] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [pendingIds, setPendingIds] = useState(() => new Set())
  const [resetOpen, setResetOpen] = useState(false)
  const [resetting, setResetting] = useState(false)

  const seqRef = useRef(0)
  const pendingRef = useRef(new Set())
  const allCheckRef = useRef(null)

  /* ---------- 数据源目录 ---------- */
  const [sources, setSources] = useState(null)
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [sourcesError, setSourcesError] = useState('')
  const [sourceType, setSourceType] = useState('')
  const sourcesSeqRef = useRef(0)

  const load = useCallback(async ({ quiet = false } = {}) => {
    const seq = ++seqRef.current
    if (!quiet) setLoading(true)
    setError('')
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (q) params.q = q
      if (province) params.province = province
      if (level) params.level = level
      if (enabledFilter) params.enabled = enabledFilter
      const result = await kaoyanApi.crawlTargets(params)
      if (seq !== seqRef.current) return false
      setData(result || null)
      setSelected(new Set())
      return true
    } catch (e) {
      if (seq !== seqRef.current) return false
      setError(e?.message || '无法读取院校采集清单')
      if (!quiet) setData(null)
      return false
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [page, q, province, level, enabledFilter])

  useEffect(() => { load() }, [load])

  const loadSources = useCallback(async () => {
    const seq = ++sourcesSeqRef.current
    setSourcesLoading(true)
    setSourcesError('')
    try {
      const result = await kaoyanApi.dataSources(sourceType ? { source_type: sourceType } : undefined)
      if (seq !== sourcesSeqRef.current) return
      setSources(Array.isArray(result?.items) ? result.items : [])
    } catch (e) {
      if (seq !== sourcesSeqRef.current) return
      setSources([])
      setSourcesError(e?.message || '无法读取数据源目录')
    } finally {
      if (seq === sourcesSeqRef.current) setSourcesLoading(false)
    }
  }, [sourceType])

  /* 首屏就拉数据源：统计条里的「数据源」数量不应该等切 Tab 才有值 */
  useEffect(() => { loadSources() }, [loadSources])

  const items = data?.items || []
  const totalPages = Math.max(1, Number(data?.total_pages) || 1)
  const totalSchools = data?.total_schools ?? data?.total
  const enabledCount = data?.enabled_count
  const disabledCount = data?.disabled_count
  const allChecked = items.length > 0 && items.every((it) => selected.has(it.id))
  const someChecked = selected.size > 0 && !allChecked

  useEffect(() => {
    if (allCheckRef.current) allCheckRef.current.indeterminate = someChecked
  }, [someChecked, selected])

  const hasFilters = !!(q || province || level || enabledFilter)

  const clearFilters = () => {
    setDraft('')
    setQ('')
    setProvince('')
    setLevel('')
    setEnabledFilter('')
    setPage(1)
  }

  const toggleOne = async (row) => {
    if (pendingRef.current.has(row.id) || busy) return
    const next = !row.enabled
    pendingRef.current.add(row.id)
    setPendingIds(new Set(pendingRef.current))

    // 乐观更新：开关立即反馈；失败时重新拉取真实状态
    setData((d) => {
      if (!d) return d
      const nextItems = (d.items || []).map((x) => (x.id === row.id ? { ...x, enabled: next } : x))
      const hasCounts = Number.isFinite(Number(d.disabled_count))
      const disabled = hasCounts
        ? Math.max(0, Number(d.disabled_count) + (next ? -1 : 1))
        : d.disabled_count
      const total = d.total_schools ?? d.total
      return {
        ...d,
        items: nextItems,
        disabled_count: disabled,
        enabled_count: hasCounts && total != null ? Number(total) - disabled : d.enabled_count,
      }
    })

    try {
      await kaoyanApi.toggleCrawlTarget({ school_id: row.id, enabled: next })
      toastOk(`${row.name} 已${next ? '恢复参与' : '排除'}采集`)
      if (enabledFilter) await load({ quiet: true })
    } catch (e) {
      toastErr(`保存失败：${e?.message || '请求失败'}`)
      await load({ quiet: true })
    } finally {
      pendingRef.current.delete(row.id)
      setPendingIds(new Set(pendingRef.current))
    }
  }

  const bulk = async (enable) => {
    if (!selected.size) {
      toastWarn('请先勾选院校')
      return
    }
    setBusy(true)
    try {
      const result = await kaoyanApi.bulkCrawlTargets({ school_ids: [...selected], enabled: enable })
      toastOk(`已${enable ? '启用' : '排除'} ${result?.changed ?? selected.size} 所院校`)
      await load({ quiet: true })
    } catch (e) {
      toastErr(`操作失败：${e?.message || '请求失败'}`)
    } finally {
      setBusy(false)
    }
  }

  const resetAll = async () => {
    setResetting(true)
    try {
      const result = await kaoyanApi.resetCrawlTargets()
      toastOk(`已恢复默认（清除 ${result?.removed ?? 0} 条开关记录）`)
      setResetOpen(false)
      await load({ quiet: true })
    } catch (e) {
      toastErr(`恢复失败：${e?.message || '请求失败'}`)
    } finally {
      setResetting(false)
    }
  }

  const facets = useMemo(() => ({
    provinces: Array.isArray(data?.provinces) ? data.provinces : [],
    levels: Array.isArray(data?.levels) ? data.levels : [],
  }), [data])

  const provinceOptions = useMemo(
    () => [{ value: '', label: '全部省份' }, ...facets.provinces.map((p) => ({ value: p, label: p }))],
    [facets.provinces],
  )
  const levelOptions = useMemo(
    () => [{ value: '', label: '全部层级' }, ...facets.levels.map((l) => ({ value: l, label: l }))],
    [facets.levels],
  )

  const participationRate = totalSchools && enabledCount != null
    ? `${Math.max(0, Math.min(100, Math.round(Number(enabledCount) / Number(totalSchools) * 100)))}%`
    : null

  const tabs = [
    { value: 'schools', label: '院校开关', icon: <School size={15} />, count: totalSchools ?? undefined },
    { value: 'sources', label: '数据源目录', icon: <Database size={15} />, count: sources?.length ?? undefined },
  ]

  return (
    <div className="v3-ops v3-kcs">
      <PageHeader
        eyebrow="数据管理 / 采集源"
        title="院校采集源"
        sub="决定哪些院校参与数据采集；默认全部参与，被排除的院校不会进入后续采集任务。"
        actions={(
          <>
            <Button
              variant="ghost"
              icon={<RefreshCw size={15} />}
              loading={loading}
              onClick={() => load()}
            >
              刷新
            </Button>
            <Button
              variant="danger"
              icon={<RotateCcw size={15} />}
              disabled={!data?.disabled_count || busy}
              onClick={() => setResetOpen(true)}
            >
              恢复默认
            </Button>
          </>
        )}
      />

      {/* 真实统计 */}
      <div className="v3-ops-stats">
        <div className="v3-ops-stat is-primary">
          <div className="v3-ops-stat__head"><span className="v3-ops-stat__label"><School size={14} />院校总数</span></div>
          <div className="v3-ops-stat__value">
            {loading && !data ? <Skeleton width={64} height={28} /> : (totalSchools == null ? '—' : Number(totalSchools).toLocaleString('zh-CN'))}
          </div>
          <div className="v3-ops-stat__hint">{hasFilters ? `当前筛选 ${data?.total ?? '—'} 所` : '择校库中的全部院校'}</div>
        </div>
        <div className="v3-ops-stat is-success">
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><CheckCircle2 size={14} />参与采集</span>
            {participationRate && <Badge tone="success">{participationRate}</Badge>}
          </div>
          <div className="v3-ops-stat__value">
            {loading && !data ? <Skeleton width={64} height={28} /> : (enabledCount == null ? '—' : Number(enabledCount).toLocaleString('zh-CN'))}
          </div>
          <div className="v3-ops-stat__hint">默认全部参与，无需逐校开启</div>
        </div>
        <div className="v3-ops-stat is-warning">
          <div className="v3-ops-stat__head"><span className="v3-ops-stat__label"><Target size={14} />已排除</span></div>
          <div className="v3-ops-stat__value">
            {loading && !data ? <Skeleton width={64} height={28} /> : (disabledCount == null ? '—' : Number(disabledCount).toLocaleString('zh-CN'))}
          </div>
          <div className="v3-ops-stat__hint">已排除院校不会新增采集记录</div>
        </div>
        <div className="v3-ops-stat is-muted">
          <div className="v3-ops-stat__head"><span className="v3-ops-stat__label"><Database size={14} />数据源</span></div>
          <div className="v3-ops-stat__value">
            {sourcesLoading && sources == null ? <Skeleton width={64} height={28} /> : (sources == null ? '—' : sources.length.toLocaleString('zh-CN'))}
          </div>
          <div className="v3-ops-stat__hint">后端注册中心中的真实数据源</div>
        </div>
      </div>

      <Tabs
        options={tabs}
        value={tab}
        onChange={setTab}
        ariaLabel="采集源视图"
        className="v3-kcs-tabs"
      />

      {tab === 'schools' && (
        <Card className="v3-kcs-card">
          <div className="v3-kcs-toolbar">
            <form
              className="v3-kcs-search"
              onSubmit={(e) => { e.preventDefault(); setPage(1); setQ(draft.trim()) }}
            >
              <Input
                icon={<Search size={15} />}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="搜索院校名称"
                aria-label="搜索院校名称"
              />
              {draft && (
                <IconButton
                  label="清空搜索"
                  size="sm"
                  icon={<X size={14} />}
                  onClick={() => { setDraft(''); setQ(''); setPage(1) }}
                  className="v3-kcs-search__clear"
                />
              )}
            </form>

            <Select
              options={provinceOptions}
              value={province}
              aria-label="按省份筛选"
              onChange={(e) => { setProvince(e.target.value); setPage(1) }}
            />
            <Select
              options={levelOptions}
              value={level}
              aria-label="按层级筛选"
              onChange={(e) => { setLevel(e.target.value); setPage(1) }}
            />

            <div className="v3-kcs-chips" role="group" aria-label="采集状态">
              {[['', '全部'], ['true', '参与中'], ['false', '已排除']].map(([value, label]) => (
                <Chip
                  key={value || 'all'}
                  active={enabledFilter === value}
                  onClick={() => { setEnabledFilter(value); setPage(1) }}
                >
                  {label}
                </Chip>
              ))}
            </div>
          </div>

          <div className="v3-kcs-bulk">
            <label className="v3-kcs-check">
              <input
                ref={allCheckRef}
                type="checkbox"
                checked={allChecked}
                onChange={(e) => setSelected(e.target.checked ? new Set(items.map((x) => x.id)) : new Set())}
                aria-label="全选本页"
              />
              全选本页
            </label>
            <span className="v3-kcs-bulk__count">
              {selected.size ? `已选 ${selected.size} 所` : '勾选后可批量启用或排除'}
            </span>
            <div className="v3-row">
              <Button size="sm" variant="ghost" disabled={!selected.size || busy} onClick={() => bulk(true)}>
                启用选中
              </Button>
              <Button size="sm" variant="ghost" className="v3-kcs-danger-text" disabled={!selected.size || busy} onClick={() => bulk(false)}>
                排除选中
              </Button>
            </div>
          </div>

          {loading && !data ? (
            <div className="v3-kcs-table-skeleton">
              {[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} height={54} radius={10} />)}
            </div>
          ) : error && !data ? (
            <Alert tone="danger">
              <div className="v3-ops-inline">
                <span>采集清单加载失败：{error}</span>
                <Button size="sm" variant="outline" onClick={() => load()}>重新加载</Button>
              </div>
            </Alert>
          ) : items.length === 0 ? (
            <Empty
              icon={<Target size={28} />}
              title={hasFilters ? '当前筛选下没有院校' : '院校库还是空的'}
              text={hasFilters
                ? '清空搜索，或切换省份 / 层级 / 状态筛选。'
                : '先在「数据管理」或「院校库」导入院校数据，再回来设置采集范围。'}
              action={hasFilters ? (
                <Button variant="outline" size="sm" onClick={clearFilters}>清空筛选</Button>
              ) : (
                <Button variant="filled" size="sm" icon={<School size={14} />} onClick={() => navigate('/admin/schools')}>
                  去导入院校数据
                </Button>
              )}
            />
          ) : (
            <>
              {error ? (
                <Alert tone="warning" className="v3-kcs-stale">
                  <div className="v3-ops-inline">
                    <span>刷新失败，当前展示的是上次成功加载的数据：{error}</span>
                    <Button size="sm" variant="outline" onClick={() => load()}>重试</Button>
                  </div>
                </Alert>
              ) : null}
              <div className="v3-table-wrap v3-kcs-table-wrap">
              <table className="v3-table v3-kcs-table">
                <thead>
                  <tr>
                    <th className="v3-kcs-col-check">选择</th>
                    <th>院校</th>
                    <th className="v3-kcs-hide-md">地区</th>
                    <th>层级</th>
                    <th className="v3-kcs-hide-sm">数据来源</th>
                    <th className="v3-kcs-hide-lg">最近采集</th>
                    <th>采集开关</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => {
                    const isSelected = selected.has(row.id)
                    const isPending = pendingIds.has(row.id)
                    return (
                      <tr key={row.id} className={cx(!row.enabled && 'is-off', isSelected && 'is-selected')}>
                        <td className="v3-kcs-col-check">
                          <input
                            type="checkbox"
                            className="v3-ops-check"
                            checked={isSelected}
                            onChange={(e) => setSelected((prev) => {
                              const next = new Set(prev)
                              if (e.target.checked) next.add(row.id)
                              else next.delete(row.id)
                              return next
                            })}
                            aria-label={`选择 ${row.name}`}
                          />
                        </td>
                        <td>
                          <div className="v3-kcs-school">
                            <Link to={`/kaoyan/schools/${row.id}`}>{row.name}</Link>
                            {row.official_url && (
                              <a
                                className="v3-kcs-school__link"
                                href={row.official_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label={`打开 ${row.name} 官网`}
                              >
                                <ExternalLink size={13} />
                              </a>
                            )}
                          </div>
                          <div className="v3-kcs-school__meta">
                            {[row.province, row.city].filter(Boolean).join(' · ') || '地区未标注'}
                            <span className="v3-kcs-only-md">
                              {row.level ? ` · ${row.level}` : ''}
                            </span>
                          </div>
                        </td>
                        <td className="v3-kcs-hide-md">{[row.province, row.city].filter(Boolean).join(' · ') || '—'}</td>
                        <td><Badge tone={LEVEL_TONE(row.level)}>{row.level || '未标注'}</Badge></td>
                        <td className="v3-kcs-hide-sm">{row.data_source || '—'}</td>
                        <td className="v3-kcs-hide-lg v3-ops-mono">
                          {row.last_crawled_at ? String(row.last_crawled_at).slice(0, 10) : '—'}
                        </td>
                        <td>
                          <div className="v3-kcs-toggle">
                            <Badge tone={row.enabled ? 'success' : 'outline'}>
                              {row.enabled ? '参与' : '已排除'}
                            </Badge>
                            <button
                              type="button"
                              role="switch"
                              aria-checked={row.enabled}
                              aria-label={`${row.name}参与采集`}
                              aria-busy={isPending}
                              className={cx('v3-kcs-switch', row.enabled && 'is-on', isPending && 'is-pending')}
                              onClick={() => toggleOne(row)}
                              disabled={isPending || busy}
                            >
                              <span className="v3-kcs-switch__knob" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              </div>
            </>
          )}

          <div className="v3-kcs-pager">
            <span>
              第 {page} / {totalPages} 页 · 共 {data?.total == null ? '—' : Number(data.total).toLocaleString('zh-CN')} 所
            </span>
            <div className="v3-row">
              <Button
                size="sm"
                variant="ghost"
                icon={<ChevronLeft size={14} />}
                disabled={page <= 1 || loading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </Button>
              <Button
                size="sm"
                variant="ghost"
                trailingIcon={<ChevronRight size={14} />}
                disabled={page >= totalPages || loading}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                下一页
              </Button>
            </div>
          </div>
        </Card>
      )}

      {tab === 'sources' && (
        <Card className="v3-kcs-card">
          <CardHead
            icon={<Server size={17} />}
            title="数据源目录"
            sub="研招网 / 省教育考试院 / 院校研究生院 / 聚合站；内置源由后端维护"
            actions={(
              <>
                <Select
                  options={[
                    { value: '', label: '全部类型' },
                    { value: 'yz', label: '研招网' },
                    { value: 'exam_authority', label: '省考试院' },
                    { value: 'school_official', label: '院校官网' },
                    { value: 'aggregator', label: '聚合站' },
                  ]}
                  value={sourceType}
                  aria-label="按数据源类型筛选"
                  onChange={(e) => { setSourceType(e.target.value); setSources(null) }}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<RefreshCw size={14} />}
                  loading={sourcesLoading}
                  onClick={loadSources}
                >
                  刷新
                </Button>
              </>
            )}
          />

          {sourcesLoading && sources == null ? (
            <div className="v3-kcs-source-grid">
              {[0, 1, 2, 3].map((i) => <Skeleton key={i} height={156} radius={16} />)}
            </div>
          ) : sourcesError ? (
            <Alert tone="danger">
              <div className="v3-ops-inline">
                <span>数据源目录加载失败：{sourcesError}</span>
                <Button size="sm" variant="outline" onClick={loadSources}>重新加载</Button>
              </div>
            </Alert>
          ) : !sources?.length ? (
            <Empty
              icon={<Database size={28} />}
              title="暂无数据源"
              text="后端注册中心还没有可展示的数据源。"
            />
          ) : (
            <div className="v3-kcs-source-grid">
              {sources.map((source) => (
                <Card className="v3-kcs-source" key={source.key}>
                  <div className="v3-kcs-source__head">
                    <span className="v3-kcs-source__icon"><Globe size={18} /></span>
                    <div className="v3-kcs-source__title">
                      <b>{source.name}</b>
                      <span>{SOURCE_TYPE_LABEL[source.source_type] || source.source_type_label || source.source_type || '未分类'}</span>
                    </div>
                    <Badge tone={SOURCE_STATUS_TONE[source.status] || 'outline'}>
                      {SOURCE_STATUS_LABEL[source.status] || source.status || '未知'}
                    </Badge>
                  </div>
                  <div className="v3-kcs-source__meta">
                    {source.province && <Badge tone="soft">{source.province}</Badge>}
                    <span className="v3-ops-mono">parser: {source.parser || '—'}</span>
                  </div>
                  {source.remark && <p className="v3-kcs-source__remark">{source.remark}</p>}
                  {source.base_url ? (
                    <a
                      className="v3-kcs-source__link"
                      href={source.base_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      打开数据源 <ExternalLink size={12} />
                    </a>
                  ) : (
                    <span className="v3-ops-caption">未配置 base_url</span>
                  )}
                </Card>
              ))}
            </div>
          )}
        </Card>
      )}

      <div className="v3-kcs-note">
        <Target size={17} />
        <div>
          <b>采集口径：</b>
          院校开关只影响后续采集任务；已入库的数据不会被删除。排除某校后，公告 / 分数线 / 拟录取都不会再为它新增记录。
          需要补数据时，可到「数据管理」按院校单独触发采集。
        </div>
      </div>

      <Dialog
        open={resetOpen}
        title="恢复默认采集范围"
        sub="将清空所有「排除」开关，恢复为全部院校参与采集。"
        onClose={() => { if (!resetting) setResetOpen(false) }}
        footer={(
          <>
            <Button variant="text" onClick={() => setResetOpen(false)} disabled={resetting}>取消</Button>
            <Button variant="danger" icon={<RotateCcw size={15} />} loading={resetting} onClick={resetAll}>
              恢复默认
            </Button>
          </>
        )}
      >
        <Alert tone="warning">
          已采集到的院校数据不会被删除；被清除的只有 {disabledCount == null ? '—' : disabledCount} 条「排除」开关记录。
        </Alert>
        <div className="v3-kcs-dialog-meta">
          <span>院校总数：<b>{totalSchools == null ? '—' : totalSchools}</b></span>
          <span>当前参与：<b>{enabledCount == null ? '—' : enabledCount}</b></span>
        </div>
      </Dialog>
    </div>
  )
}
