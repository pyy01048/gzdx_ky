import React, { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../api/kaoyanApi'
import { toast, Empty } from './UI'
import { FileText, RefreshCw, ChevronRight } from './Icon'

/**
 * 首页「院校公告」栏 —— 跨校公告聚合展示。
 *
 * 目标（docx/11 §5.4，用户点名「主页要能看当日哪些院校更新」）：
 *  - 概览：「最近 7 天 X 所学校更新 Y 条」+ 顶部总条数/最新采集时间
 *  - 列表：学校名 · 标题 · 日期 · 类型标签，点击新窗口打开原文
 *  - 兜底：无数据显示 Empty；接口失败 toast 提示，不白屏
 *
 * 数据源：GET /api/kaoyan/notices（跨校聚合，见 routers/kaoyan.py:list_all_notices）
 *        GET /api/kaoyan/notices/updates（最近 N 天更新院校概览）
 * 两个接口并发请求、独立容错：updates 失败仅隐藏概览行，不影响列表。
 */
const NOTICE_LIMIT = 8 // 首页仅展示最近 8 条，其余引导去院校库看全量

/** 相对日期文案：今天 / 昨天 / N 天前 / 具体日期（数据缺失时返回空串）。 */
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

/** 类型标签颜色（复用平台令牌，未知类型走中性色）。 */
const TYPE_COLOR = {
  '简章': 'var(--accent)',
  '复试': 'var(--gold, #b8860b)',
  '调剂': 'var(--green, #2e7d32)',
  '录取': 'var(--red, #c0392b)',
  '公告': 'var(--ink-3)',
}

export default function NoticeBoard() {
  const [items, setItems] = useState([])
  const [stats, setStats] = useState(null)
  const [updates, setUpdates] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ok | error
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await kaoyanApi.notices({ limit: NOTICE_LIMIT })
      // 后端契约：{ items, stats }；防御 null（client 对空响应体 resolve(null)）
      setItems(Array.isArray(d?.items) ? d.items : [])
      setStats(d?.stats || null)
      setStatus('ok')
    } catch {
      setStatus('error')
      setItems([])
    }
    // 最近 7 天更新概览：独立容错，失败不影响主列表
    try {
      const u = await kaoyanApi.noticeUpdates({ days: 7 })
      setUpdates(u && typeof u.total_schools === 'number' ? u : null)
    } catch {
      setUpdates(null)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const onRefresh = async () => {
    setRefreshing(true)
    try {
      await load()
      toast('院校公告已刷新')
    } finally {
      setRefreshing(false)
    }
  }

  /* ---------- 头部进度/加载态 ---------- */
  if (status === 'loading') {
    return (
      <div className="panel notice-board">
        <div className="panel-head">
          <h3 className="panel-title">院校公告</h3>
        </div>
        <div className="skeleton sk-line" style={{ height: 16, margin: '8px 0' }} />
        <div className="skeleton sk-line" style={{ height: 16, margin: '8px 0' }} />
        <div className="skeleton sk-line" style={{ height: 16, margin: '8px 0' }} />
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="panel notice-board">
        <div className="panel-head">
          <h3 className="panel-title">院校公告</h3>
          <button className="link-btn" onClick={load}>
            重试 <ChevronRight size={13} />
          </button>
        </div>
        <Empty
          icon={<FileText size={22} />}
          title="公告加载失败"
          desc="后端未启动或网络异常，点击右上角重试"
        />
      </div>
    )
  }

  const total = stats?.total ?? items.length
  const schoolCount = stats?.school_count ?? 0

  return (
    <div className="panel notice-board">
      <div className="panel-head">
        <h3 className="panel-title">院校公告</h3>
        <div className="notice-head-right">
          <span className="panel-sub">
            共 {total} 条 · {schoolCount} 所院校
          </span>
          <button
            className="btn ghost notice-refresh"
            onClick={onRefresh}
            disabled={refreshing}
            title="刷新公告"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* 当日/近期更新概览 */}
      {updates && updates.total_schools > 0 && (
        <div className="notice-overview">
          最近 7 天 <b>{updates.total_schools}</b> 所学校更新 <b>{updates.total_notices}</b> 条公告
        </div>
      )}

      {/* 公告列表 */}
      {items.length === 0 ? (
        <Empty
          icon={<FileText size={22} />}
          title="暂无院校公告"
          desc="公告按院校研究生院官网采集，可在院校库页触发采集"
        />
      ) : (
        <div className="notice-list">
          {items.map((n) => (
            <a
              key={n.id}
              className={`notice-item ${n.is_read ? 'is-read' : 'is-unread'}`}
              href={n.url || '#'}
              target="_blank"
              rel="noreferrer"
              title={n.title}
            >
              {/* 未读圆点：首页也能一眼看出哪些还没看 */}
              <span className="nc-dot" aria-hidden="true" />
              <span className="notice-school">{n.school_name || '未知院校'}</span>
              <span className="notice-title">{n.title}</span>
              {n.notice_type && (
                <em
                  className="notice-type"
                  style={{ color: TYPE_COLOR[n.notice_type] || 'var(--ink-3)' }}
                >
                  {n.notice_type}
                </em>
              )}
              <span className="notice-date">{humanDate(n.publish_date) || '—'}</span>
            </a>
          ))}
        </div>
      )}

      {stats?.latest_fetched_at && (
        <p className="notice-foot">
          最近采集：{String(stats.latest_fetched_at).slice(0, 16)}
        </p>
      )}

      {/* 引导到通知中心：可标记已读、只看未读、加星置顶
          文案口径与导航入口名「通知中心」对齐（#105a） */}
      <Link to="/kaoyan/notices" className="notice-more">
        进入通知中心：管理已读 / 查看全部 <ChevronRight size={13} />
      </Link>
    </div>
  )
}
