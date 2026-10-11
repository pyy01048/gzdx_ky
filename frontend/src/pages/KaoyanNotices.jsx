import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../api/kaoyanApi'
import { Empty } from '../components/UI'
import './KaoyanNotices.css'

const NOTICE_TYPES = ['公告', '简章', '复试', '调剂', '录取']

const TYPE_META = {
  '公告': { cls: 'ky-n-type-bulletin', icon: '📢' },
  '简章': { cls: 'ky-n-type-guide', icon: '📘' },
  '复试': { cls: 'ky-n-type-retest', icon: '🎯' },
  '调剂': { cls: 'ky-n-type-adjust', icon: '🔀' },
  '录取': { cls: 'ky-n-type-admit', icon: '🎉' },
}

// 改考事件 → 徽章色（停招最警示）
const REFORM_META = {
  '改考科目': { cls: 'ky-n-reform-subject', icon: '🔁' },
  '停招': { cls: 'ky-n-reform-stop', icon: '⛔' },
  '恢复招生': { cls: 'ky-n-reform-resume', icon: '✅' },
  '新增专业': { cls: 'ky-n-reform-new', icon: '🌟' },
  '参考书变更': { cls: 'ky-n-reform-book', icon: '📚' },
  '大纲调整': { cls: 'ky-n-reform-syllabus', icon: '🧭' },
  '复试调整': { cls: 'ky-n-reform-retest', icon: '🎯' },
  '学制/学费调整': { cls: 'ky-n-reform-system', icon: '⏱️' },
}

export default function KaoyanNotices() {
  const [tab, setTab] = useState('feed') // feed | reform
  // ---- 公告流状态 ----
  const [q, setQ] = useState('')
  const [qInput, setQInput] = useState('')
  const [noticeType, setNoticeType] = useState('')
  const [page, setPage] = useState(1)
  const [feed, setFeed] = useState(null)
  const [feedLoading, setFeedLoading] = useState(false)
  // ---- 改考雷达状态 ----
  const [reforms, setReforms] = useState([])
  const [reformStats, setReformStats] = useState(null)
  const [reformType, setReformType] = useState('')
  const [reformLoading, setReformLoading] = useState(false)
  const [scanMsg, setScanMsg] = useState('')

  const loadFeed = useCallback(() => {
    setFeedLoading(true)
    const params = { page, page_size: 20 }
    if (q) params.q = q
    if (noticeType) params.notice_type = noticeType
    kaoyanApi.noticesFeed(params)
      .then(setFeed)
      .catch(() => setFeed(null))
      .finally(() => setFeedLoading(false))
  }, [q, noticeType, page])

  const loadReforms = useCallback(() => {
    setReformLoading(true)
    const params = {}
    if (reformType) params.change_type = reformType
    Promise.all([kaoyanApi.reforms(params), kaoyanApi.reformStats()])
      .then(([list, stats]) => { setReforms(list || []); setReformStats(stats) })
      .catch(() => { setReforms([]); setReformStats(null) })
      .finally(() => setReformLoading(false))
  }, [reformType])

  useEffect(() => { if (tab === 'feed') loadFeed() }, [tab, loadFeed])
  useEffect(() => { if (tab === 'reform') loadReforms() }, [tab, loadReforms])

  const search = (e) => {
    e.preventDefault()
    setQ(qInput.trim())
    setPage(1)
  }

  const runScan = () => {
    setScanMsg('扫描中…')
    kaoyanApi.reformScan({})
      .then((r) => setScanMsg(`扫描完成：检测 ${r.detected} 条，新增 ${r.inserted} 条`))
      .catch(() => setScanMsg('扫描失败，请稍后重试'))
      .then(loadReforms)
  }

  const totalPages = feed ? Math.max(1, Math.ceil(feed.total / feed.page_size)) : 1

  return (
    <div className="ky-notices">
      {/* Hero */}
      <div className="ky-n-hero">
        <div className="ky-n-hero-text">
          <h1>通知中心</h1>
          <p>跨院校公告聚合 · 改考雷达实时盯梢 · 不错过任何关键变动</p>
        </div>
        <div className="ky-n-hero-badge">{feed ? `${feed.total} 条公告` : '…'}</div>
      </div>

      {/* Tab 切换 */}
      <div className="ky-n-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'feed'} className={tab === 'feed' ? 'on' : ''} onClick={() => setTab('feed')}>📢 公告流</button>
        <button role="tab" aria-selected={tab === 'reform'} className={tab === 'reform' ? 'on' : ''} onClick={() => setTab('reform')}>🚨 改考雷达</button>
      </div>

      {tab === 'feed' && (
        <>
          <div className="ky-n-toolbar">
            <form className="ky-n-search" onSubmit={search}>
              <input value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="搜索公告标题，如「初试科目」…" aria-label="搜索公告" />
              <button type="submit">搜索</button>
            </form>
            <div className="ky-n-chips">
              <button className={!noticeType ? 'chip on' : 'chip'} onClick={() => { setNoticeType(''); setPage(1) }}>全部</button>
              {NOTICE_TYPES.map((t) => (
                <button key={t} className={noticeType === t ? 'chip on' : 'chip'} onClick={() => { setNoticeType(t); setPage(1) }}>
                  {TYPE_META[t]?.icon} {t}
                </button>
              ))}
            </div>
          </div>

          {feedLoading && (
            <div className="ky-n-list" aria-busy="true" aria-label="加载中">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="ky-n-card ky-n-skeleton">
                  <span className="ky-n-type ky-n-skel-box" style={{ width: 64, height: 22 }} />
                  <div className="ky-n-card-main">
                    <div className="ky-n-skel-box" style={{ width: '72%', height: 16, marginBottom: 10 }} />
                    <div className="ky-n-skel-box" style={{ width: '42%', height: 12 }} />
                  </div>
                </div>
              ))}
            </div>
          )}
          {!feedLoading && (!feed || feed.items.length === 0) && (
            <Empty text="暂无公告数据 · 可在「数据管理」页运行公告爬取" />
          )}
          {!feedLoading && feed && feed.items.length > 0 && (
            <div className="ky-n-list">
              {feed.items.map((n) => {
                const meta = TYPE_META[n.notice_type] || TYPE_META['公告']
                return (
                  <article key={n.id} className="ky-n-card">
                    <span className={`ky-n-type ${meta.cls}`}>{meta.icon} {n.notice_type}</span>
                    <div className="ky-n-card-main">
                      <h3>{n.title}</h3>
                      <div className="ky-n-card-meta">
                        <Link to={`/kaoyan/schools/${n.school_id}`} className="ky-n-school">{n.school_name}</Link>
                        <time>{n.publish_date || '—'}</time>
                        {n.url && n.url !== 'https://example.com/n' && (
                          <a href={n.url} target="_blank" rel="noreferrer" className="ky-n-link">原文 ↗</a>
                        )}
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          )}
          {!feedLoading && feed && feed.total > feed.page_size && (
            <div className="ky-n-pager">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
              <span>{page} / {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</button>
            </div>
          )}
        </>
      )}

      {tab === 'reform' && (
        <>
          <div className="ky-n-reform-bar">
            {reformStats && (
              <div className="ky-n-reform-stats">
                <strong>{reformStats.total}</strong> 条变动事件
                {Object.entries(reformStats.by_type).slice(0, 4).map(([t, c]) => (
                  <span key={t} className="ky-n-mini">{t} {c}</span>
                ))}
              </div>
            )}
            <button className="ky-n-scan" onClick={runScan} disabled={reformLoading}>⚡ 扫描最新公告</button>
          </div>
          {scanMsg && <div className="ky-n-scan-msg">{scanMsg}</div>}

          <div className="ky-n-chips">
            <button className={!reformType ? 'chip on' : 'chip'} onClick={() => setReformType('')}>全部</button>
            {Object.keys(REFORM_META).map((t) => (
              <button key={t} className={reformType === t ? 'chip on' : 'chip'} onClick={() => setReformType(t)}>
                {REFORM_META[t].icon} {t}
              </button>
            ))}
          </div>

          {reformLoading && <div className="ky-n-loading">雷达扫描中…</div>}
          {!reformLoading && reforms.length === 0 && (
            <Empty text="暂无改考事件 · 点击「扫描最新公告」检测" />
          )}
          {!reformLoading && reforms.length > 0 && (
            <div className="ky-n-reform-list">
              {reforms.map((r) => {
                const meta = REFORM_META[r.change_type] || { cls: '', icon: '⚠️' }
                return (
                  <article key={r.id} className={`ky-n-reform-card ${meta.cls}`}>
                    <div className="ky-n-reform-head">
                      <span className="ky-n-reform-badge">{meta.icon} {r.change_type}</span>
                      {r.year && <span className="ky-n-reform-year">{r.year}</span>}
                      <span className="ky-n-reform-conf" title="规则匹配置信度">置信 {Math.round((r.confidence || 0) * 100)}%</span>
                    </div>
                    <h3>{r.title}</h3>
                    <div className="ky-n-card-meta">
                      <Link to={`/kaoyan/schools/${r.school_id}`} className="ky-n-school">{r.school_name}</Link>
                      {r.keywords && <code className="ky-n-kw">命中：{r.keywords}</code>}
                      {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="ky-n-link">公告原文 ↗</a>}
                    </div>
                  </article>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
