/* 通知中心 —— 已读/未读管理与加星置顶
 *
 * 用户诉求：「每一个通知都要有一个已读标记，这样防止我错过消息」。
 * 本页是这套体系的主界面，核心能力：
 *   1. 未读视觉区分：未读=左侧圆点 + 标题加粗 + 浅色底；已读=淡化
 *   2. 全局未读数概览 + 「全部已读」一键清零
 *   3. 只看未读 / 只看加星 筛选切换
 *   4. 类型筛选（含各类型未读计数）
 *   5. 重要度分级提示（紧急=红竖条+「紧急」标签 / 重要=普通红点）+ 手动加星置顶
 *   6. 点击任一条即标记已读（错过的风险从「打开链接」前移到「扫一眼列表」）
 *   7. 分页（后端 page/page_size）
 *
 * 数据源（后端单用户设计，状态存于 kaoyan_notices 列）：
 *   GET  /api/notices/list
 *   GET  /api/notices/unread-stats
 *   POST /api/notices/{id}/read  |  /batch-read
 *   POST /api/notices/{id}/star
 *
 * 重要度口径（v2）：以服务端落库的 importance_level 为唯一权威
 *   urgent / important / normal，由 notice_alert.py 规则引擎打分回填。
 *   早期版本按 notice_type IN (录取,调剂,复试) 派生，会漏掉「网上报名公告」
 *   这类最易错过的节点（实测漏标 94 条 urgent 公告），故已废弃该白名单。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import { request } from '../api/client'
import { useUnreadNotices } from '../hooks/useUnreadNotices'
import { toast, Empty, Segmented } from '../components/UI'
import { FileText, RefreshCw, ChevronRight, Check } from '../components/Icon'
import './NoticeCenter.css'

const PAGE_SIZE = 20

/** 类型标签配色（复用平台令牌，未知类型走中性色）。 */
const TYPE_COLOR = {
  简章: 'var(--accent)',
  复试: 'var(--gold)',
  调剂: 'var(--green)',
  录取: 'var(--red)',
  公告: 'var(--ink-3)',
  目录: 'var(--ink-3)',
  大纲: 'var(--ink-3)',
}

/** 重要度分级标签文案。权威口径来自后端 importance_level（落库规则引擎打分）。 */
const LEVEL_LABEL = {
  urgent: '紧急',
  important: '重要',
}

/**
 * 取单条通知的重要度等级，并对 undefined 安全降级为 'normal'。
 * 后端未升级时不会有该字段，此时全部退化为不标记，绝不报错。
 */
function levelOf(n) {
  const lv = n?.importance_level
  return lv === 'urgent' || lv === 'important' ? lv : 'normal'
}

/** 相对日期文案：今天 / 昨天 / N 天前 / 具体日期。 */
function humanDate(dateStr) {
  if (!dateStr) return ''
  const day = String(dateStr).slice(0, 10)
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day)
  if (!m) return day
  const target = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((today - target) / 86400000)
  if (diff === 0) return '今天'
  if (diff === 1) return '昨天'
  if (diff > 1 && diff < 30) return `${diff} 天前`
  if (diff < 0) return '即将'
  return day
}

export default function NoticeCenter() {
  // 全局未读快照：概览条与筛选器计数都来自这里，保证与侧边栏角标口径一致
  const { important_unread: importantUnread, urgent_unread: urgentUnread, refresh: refreshStats } =
    useUnreadNotices()

  const [items, setItems] = useState([])
  const [meta, setMeta] = useState({ total: 0, unread: 0, page: 1, by_type_total: {} })
  const [status, setStatus] = useState('loading') // loading | ok | error
  const [busy, setBusy] = useState(false)

  // 筛选状态
  const [readFilter, setReadFilter] = useState('all') // all | unread | starred
  const [noticeType, setNoticeType] = useState('')
  const [levelFilter, setLevelFilter] = useState('all') // all | urgent | important
  const [page, setPage] = useState(1)

  const load = useCallback(async () => {
    setStatus(items.length ? 'ok' : 'loading')
    try {
      const d = await kaoyanApi.noticeList({
        unread_only: readFilter === 'unread',
        starred_only: readFilter === 'starred',
        notice_type: noticeType || undefined,
        // 重要度筛选走后端 SQL 参数（而非前端本地过滤），
        // 否则只会过滤当前页的 20 条，分页语义会骗人。
        urgent_only: levelFilter === 'urgent',
        important_only: levelFilter === 'important',
        page,
        page_size: PAGE_SIZE,
      })
      setItems(Array.isArray(d?.items) ? d.items : [])
      setMeta({
        total: d?.total ?? 0,
        unread: d?.unread ?? 0,
        page: d?.page ?? 1,
        by_type_total: d?.by_type_total || {},
      })
      setStatus('ok')
    } catch {
      setStatus('error')
      setItems([])
    }
  }, [readFilter, noticeType, levelFilter, page, items.length])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readFilter, noticeType, levelFilter, page])

  /** 点击列表项：先本地置为已读（即时反馈），再调后端持久化。 */
  const onItemClick = useCallback(
    async (n) => {
      if (n.is_read) return // 已读无需再请求
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)))
      try {
        await kaoyanApi.markNoticeRead(n.id, true)
        await refreshStats()
      } catch {
        // 失败则回滚本地状态，避免"看起来已读但实际没存"
        setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: false } : x)))
        toast('标记已读失败，请重试')
      }
    },
    [refreshStats]
  )

  /** 加星/取消加星：即时反馈 + 后端持久化。 */
  const onToggleStar = useCallback(
    async (e, n) => {
      e.preventDefault()
      e.stopPropagation()
      const next = !n.is_starred
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_starred: next } : x)))
      try {
        await kaoyanApi.starNotice(n.id, next)
        await refreshStats()
        toast(next ? '已加星置顶' : '已取消加星')
      } catch {
        setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_starred: !next } : x)))
        toast('操作失败，请重试')
      }
    },
    [refreshStats]
  )

  /** 全部已读（对应后端 all 作用域）。 */
  const onMarkAllRead = useCallback(async () => {
    setBusy(true)
    try {
      const r = await kaoyanApi.batchMarkNoticeRead({ all: true })
      toast(`已将 ${r?.updated ?? 0} 条通知标为已读`)
      await load()
      await refreshStats()
    } catch {
      toast('操作失败，请重试')
    } finally {
      setBusy(false)
    }
  }, [load, refreshStats])

  /** 一键加星全部关键类型（用户想快速置顶录取/调剂/复试时用）。 */
  const onStarImportant = useCallback(async () => {
    setBusy(true)
    try {
      const r = await request('/notices/backfill-important', { method: 'POST' })
      toast(`已加星 ${r?.starred ?? 0} 条关键通知（录取/调剂/复试）`)
      await load()
      await refreshStats()
    } catch {
      toast('操作失败，请重试')
    } finally {
      setBusy(false)
    }
  }, [load, refreshStats])

  // 类型筛选项（带各类型总数，来自后端 by_type_total）
  const typeOptions = useMemo(() => {
    const opts = [{ value: '', label: '全部类型' }]
    Object.entries(meta.by_type_total || {})
      .sort((a, b) => b[1] - a[1])
      .forEach(([t, n]) => opts.push({ value: t, label: `${t} ${n}` }))
    return opts
  }, [meta.by_type_total])

  const totalPages = Math.max(1, Math.ceil(meta.total / PAGE_SIZE))

  const filterOptions = [
    { value: 'all', label: '全部' },
    { value: 'unread', label: `只看未读${meta.unread ? ` ${meta.unread}` : ''}` },
    { value: 'starred', label: '只看加星' },
  ]

  // 重要度筛选：计数取自 unread-stats（全库口径，非当前页）
  const levelOptions = [
    { value: 'all', label: '全部等级' },
    { value: 'urgent', label: `仅紧急${urgentUnread ? ` ${urgentUnread}` : ''}` },
    { value: 'important', label: `仅重要${importantUnread ? ` ${importantUnread}` : ''}` },
  ]

  if (status === 'loading') {
    return (
      <div className="notice-center">
        <div className="panel">
          <div className="skeleton sk-line" style={{ height: 16, margin: '8px 0' }} />
          <div className="skeleton sk-line" style={{ height: 16, margin: '8px 0' }} />
          <div className="skeleton sk-line" style={{ height: 16, margin: '8px 0' }} />
        </div>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="notice-center">
        <div className="panel">
          <Empty
            icon={<FileText size={22} />}
            title="通知加载失败"
            desc="后端未启动或网络异常，点击右上角重试"
            action={
              <button className="btn ghost" onClick={load}>
                重试
              </button>
            }
          />
        </div>
      </div>
    )
  }

  return (
    <div className="notice-center">
      {/* 概览条 */}
      <div className="panel nc-overview">
        <div className="nc-ov-left">
          <div className="nc-ov-num">
            <b>{meta.unread}</b>
            <span>条未读</span>
          </div>
          <div className="nc-ov-sub">
            共 {meta.total} 条通知
            {urgentUnread > 0 && (
              <em className="nc-ov-warn is-urgent">含 {urgentUnread} 条紧急未读</em>
            )}
            {importantUnread > urgentUnread && (
              <em className="nc-ov-warn">重要未读 {importantUnread} 条</em>
            )}
          </div>
        </div>
        <div className="nc-ov-actions">
          <button className="btn ghost" onClick={load} title="刷新">
            <RefreshCw size={14} />
          </button>
          <button className="btn ghost" onClick={onStarImportant} disabled={busy}>
            关键类型加星
          </button>
          <button className="btn primary" onClick={onMarkAllRead} disabled={busy || meta.unread === 0}>
            <Check size={14} />
            全部已读
          </button>
        </div>
      </div>

      {/* 筛选 */}
      <div className="panel nc-filters">
        <Segmented options={filterOptions} value={readFilter} onChange={setReadFilter} />
        <select className="nc-type-select" value={noticeType} onChange={(e) => { setNoticeType(e.target.value); setPage(1) }}>
          {typeOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          className="nc-type-select"
          value={levelFilter}
          aria-label="按重要度筛选"
          onChange={(e) => { setLevelFilter(e.target.value); setPage(1) }}
        >
          {levelOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {/* 列表 */}
      <div className="panel">
        {items.length === 0 ? (
          <Empty
            icon={<FileText size={22} />}
            title={readFilter === 'unread' ? '没有未读通知' : '暂无通知'}
            desc={readFilter === 'unread' ? '所有通知都已标记为已读' : '暂无符合筛选条件的通知'}
          />
        ) : (
          <div className="nc-list">
            {items.map((n) => {
              const lv = levelOf(n)
              return (
                <div
                  key={n.id}
                  className={`nc-item ${n.is_read ? 'is-read' : 'is-unread'} ${n.is_starred ? 'is-starred' : ''} lv-${lv}`}
                >
                {/* 未读圆点：最直观的"还有没看"信号 */}
                <span className="nc-dot" aria-hidden="true" />
                <a
                  className="nc-main"
                  href={n.url || '#'}
                  target="_blank"
                  rel="noreferrer"
                  title={n.title}
                  onClick={() => onItemClick(n)}
                >
                  <span className="nc-school">{n.school_name || '未知院校'}</span>
                  <span className="nc-title">{n.title}</span>
                  <span className="nc-tags">
                    {n.notice_type && (
                      <em
                        className="nc-type"
                        style={{ color: TYPE_COLOR[n.notice_type] || 'var(--ink-3)' }}
                      >
                        {n.notice_type}
                      </em>
                    )}
                    {/* 重要度分级提示：紧急=「紧急」红标签(+左侧红竖条见 CSS)，
                        重要=普通红点。均只对未读生效，已读不再打扰。 */}
                    {lv !== 'normal' && !n.is_read && (
                      <em className={`nc-important lv-${lv}`}>{LEVEL_LABEL[lv]}</em>
                    )}
                  </span>
                  <span className="nc-date">{humanDate(n.publish_date) || '—'}</span>
                </a>
                {/* 加星按钮：手动置顶关键通知 */}
                <button
                  className={`nc-star ${n.is_starred ? 'on' : ''}`}
                  onClick={(e) => onToggleStar(e, n)}
                  title={n.is_starred ? '取消加星' : '加星置顶'}
                  aria-label={n.is_starred ? '取消加星' : '加星置顶'}
                >
                  {n.is_starred ? '★' : '☆'}
                </button>
              </div>
              )
            })}
          </div>
        )}

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="nc-pager">
            <button
              className="btn ghost"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              上一页
            </button>
            <span className="nc-pager-info">
              第 {page} / {totalPages} 页
            </span>
            <button
              className="btn ghost"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页 <ChevronRight size={13} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
