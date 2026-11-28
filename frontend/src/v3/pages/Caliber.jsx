/**
 * 数据口径与接口体检（/admin/caliber，仅管理员）
 *
 * P0-1：今日中枢首页不再暴露接口路径 / 字段名 / 耗时等调试信息。
 * 口径对账数据仍由 api/hub.js 统一产出（caliber + sources），这里是唯一落点。
 * 非管理员手输 URL 会被 RequireAdmin 送去 403。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { fetchHubOverview, peekHubCache } from '../../api/hub'
import { Button, Skeleton, cx, toastOk } from '../ui'
import { AlertTriangle, Gauge, RefreshCw } from '../icons'
import '../styles/pages.css'
import '../styles/hub-v3.css'

/** 将数值格式化为中文千分位字符串；非有限数返回「—」。 */
const fmt = (n) => (Number.isFinite(Number(n)) ? new Intl.NumberFormat('zh-CN').format(Number(n)) : '—')

/**
 * 数据口径与接口体检页（/admin/caliber，仅管理员）。
 * 口径对账数据由 api/hub.js 统一产出，本页是唯一落点；
 * 非管理员手输 URL 会被 RequireAdmin 送去 403。
 */
export default function Caliber() {
  const [data, setData] = useState(() => peekHubCache())
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    return () => { aliveRef.current = false }
  }, [])

  /** 拉取口径概览；force=true 时强制后端刷新缓存并提示。 */
  const load = useCallback(async ({ force = false } = {}) => {
    setRefreshing(true)
    try {
      const next = await fetchHubOverview({ force })
      if (!aliveRef.current) return
      setData(next)
      setError(null)
      if (force) toastOk('口径数据已刷新')
    } catch (e) {
      if (!aliveRef.current) return
      setError(e)
    } finally {
      if (aliveRef.current) setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (!data) {
    return error ? (
      <div className="caliber-page">
        <section className="hub-error" role="alert">
          <span className="hub-error__icon" aria-hidden="true"><AlertTriangle size={30} /></span>
          <h1 className="hub-error__title">口径数据暂时取不到</h1>
          <p className="hub-error__text">{String(error?.message || '聚合接口不可达，请重试')}</p>
          <Button variant="filled" data-cta="primary" icon={<RefreshCw size={16} />} onClick={() => load({ force: true })}>重试</Button>
        </section>
      </div>
    ) : (
      <div className="caliber-page" aria-busy="true" aria-label="口径数据加载中">
        <Skeleton width={260} height={26} />
        <Skeleton width="100%" height={220} style={{ marginTop: 20 }} radius={12} />
        <Skeleton width="100%" height={140} style={{ marginTop: 16 }} radius={12} />
      </div>
    )
  }

  return (
    <div className="caliber-page">
      <header className="caliber-page__head">
        <div>
          <h1 className="caliber-page__title"><Gauge size={22} /> 数据口径与接口体检</h1>
          <p className="caliber-page__sub">
            今日中枢所有数字只来自 {data?.sources?.length ?? 0} 个聚合端点；派生指标由统一数据层计算。此页仅管理员可见。
          </p>
        </div>
        <Button
          variant="tonal"
          icon={<RefreshCw size={15} className={refreshing ? 'hub-spin' : ''} />}
          onClick={() => load({ force: true })}
          disabled={refreshing}
        >
          刷新
        </Button>
      </header>

      <section className="hub-panel" aria-labelledby="caliber-table-title">
        <h2 className="hub-panel__title" id="caliber-table-title">口径对账</h2>
        <div className="hub-caliber">
          <div className="hub-caliber__table">
            {(data?.caliber || []).map((row) => (
              <div className="hub-caliber__row" key={row.label}>
                <span className="hub-caliber__label">{row.label}</span>
                <strong className="hub-caliber__value">
                  {row.value == null ? '—' : fmt(row.value)}<small>{row.unit}</small>
                </strong>
                <code className="hub-caliber__source">{row.source}</code>
                <span className="hub-caliber__note">{row.note}</span>
              </div>
            ))}
          </div>
        </div>
        <p className="hub-hint-line">
          三个「到期」不是同一个队列：今日累计看未来负荷（截至 24:00），现在可做看复习调度，
          艾宾浩斯来自复盘计划。分开标注是为了避免把计划复习误当成错题欠账。
        </p>
      </section>

      <section className="hub-panel" aria-labelledby="caliber-sources-title">
        <h2 className="hub-panel__title" id="caliber-sources-title">接口体检</h2>
        <div className="hub-sources">
          {(data?.sources || []).map((s) => (
            <div key={s.key} className={cx('hub-source', s.ok ? 'is-ok' : 'is-fail')}>
              <span className="hub-source__dot" aria-hidden="true" />
              <span className="hub-source__name">{s.label}</span>
              <code>{s.path}</code>
              <span className="hub-source__ms">{s.ok ? `${s.ms} ms` : '失败'}</span>
              {!s.ok && s.error ? <span className="hub-source__err" title={s.error}>{s.error}</span> : null}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
