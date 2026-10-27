import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import { request } from '../../api/client'
import { useUnreadNotices } from '../../hooks/useUnreadNotices'
import { daysBetween, humanDate, todayStr } from '../../utils/date'
import {
  AnimatedNumber, Badge, Button, Card, CardHead, Chip, Empty, IconButton, Input,
  LoadingState, Progress, Segmented, Select, cx, toast,
} from '../ui'
import {
  ArrowUpRight, Bell, BookOpen, CalendarClock, Check, CheckCircle2, ChevronLeft,
  ChevronRight, Clock, Compass, FileText, ListChecks, RefreshCw, School, Search,
  Sparkles, Star, Target, Warning, X,
} from '../icons'
import { useAuth } from '../../auth/AuthContext'
import '../styles/notices-v3.css'

/* ============================================================
   通知中心 · 公告已读/加星 + 改考雷达
   ============================================================ */
const PAGE_SIZE = 20

const TYPE_TONE = {
  简章: 'primary',
  复试: 'warning',
  调剂: 'success',
  录取: 'danger',
  公告: 'outline',
  目录: 'outline',
  大纲: 'outline',
}

const LEVEL_LABEL = {
  urgent: '紧急',
  important: '重要',
}

function levelOf(n) {
  const lv = n?.importance_level
  return lv === 'urgent' || lv === 'important' ? lv : 'normal'
}

/* ---------- 改考雷达 ---------- */
const REFORM_TYPES = {
  改考科目: <RefreshCw size={13} />,
  停招: <X size={13} />,
  恢复招生: <CheckCircle2 size={13} />,
  新增专业: <Sparkles size={13} />,
  参考书变更: <BookOpen size={13} />,
  大纲调整: <ListChecks size={13} />,
  复试调整: <Target size={13} />,
  '学制/学费调整': <Clock size={13} />,
}

const REFORM_TONE = {
  停招: 'danger',
  改考科目: 'warning',
  恢复招生: 'success',
  新增专业: 'primary',
}

function ReformRadar({ canScan }) {
  const [items, setItems] = useState([])
  const [stats, setStats] = useState(null)
  const [changeType, setChangeType] = useState('')
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    const params = {}
    if (changeType) params.change_type = changeType
    Promise.all([kaoyanApi.reforms(params), kaoyanApi.reformStats()])
      .then(([list, s]) => {
        setItems(Array.isArray(list) ? list : [])
        setStats(s || null)
      })
      .catch(() => {
        setItems([])
        setStats(null)
        setError('雷达数据加载失败，请确认后端服务已启动后重试。')
      })
      .finally(() => setLoading(false))
  }, [changeType])

  useEffect(() => { load() }, [load])

  const runScan = () => {
    setScanning(true)
    setMsg('扫描中…')
    kaoyanApi.reformScan({})
      .then((r) => setMsg(`扫描完成：检测 ${r?.detected ?? 0} 条，新增 ${r?.inserted ?? 0} 条`))
      .catch(() => setMsg('扫描失败，请稍后重试'))
      .finally(() => {
        setScanning(false)
        load()
      })
  }

  const statChips = useMemo(() => {
    if (!stats) return []
    const raw = stats.by_type
    if (Array.isArray(raw)) return raw.slice(0, 4).map((x) => ({ type: x.type, total: x.total }))
    return Object.entries(raw || {})
      .slice(0, 4)
      .map(([type, c]) => ({ type, total: typeof c === 'number' ? c : (c && c.total) || 0 }))
  }, [stats])

  return (
    <div className="v3-notices-radar">
      <Card className="v3-notices-radar__bar" glow>
        <div className="v3-notices-radar__summary">
          <span className="v3-notices-radar__orb" aria-hidden="true"><Compass size={22} /></span>
          <div>
            <div className="v3-notices-radar__title">改考雷达</div>
            <div className="v3-notices-radar__stats">
              {stats ? (
                <>
                  <strong>{stats.total ?? 0}</strong>
                  <span>条变动事件</span>
                  {statChips.map(({ type, total }) => (
                    <Badge key={type} tone="outline">{type} {total}</Badge>
                  ))}
                </>
              ) : (
                <span>聚合院校改考 / 停招 / 新增专业等关键变动</span>
              )}
            </div>
          </div>
        </div>
        {canScan ? (
          <Button
            variant="filled"
            icon={<RefreshCw size={16} />}
            onClick={runScan}
            disabled={loading || scanning}
            loading={scanning}
          >
            扫描最新公告
          </Button>
        ) : null}
      </Card>

      {msg ? (
        <div className={cx('v3-notices-radar__msg', /失败/.test(msg) && 'is-error')} role="status">
          <span className="v3-notices-radar__pulse" aria-hidden="true" />
          {msg}
        </div>
      ) : null}

      <div className="v3-notices-radar__filters" role="group" aria-label="按变动类型过滤">
        <Chip active={!changeType} onClick={() => setChangeType('')}>全部类型</Chip>
        {Object.entries(REFORM_TYPES).map(([t, icon]) => (
          <Chip key={t} active={changeType === t} icon={icon} onClick={() => setChangeType(t)}>
            {t}
          </Chip>
        ))}
      </div>

      {loading ? (
        <Card className="v3-notices-statecard">
          <LoadingState text="雷达扫描中…" />
        </Card>
      ) : error ? (
        <Card className="v3-notices-statecard">
          <Empty
            icon={<Warning size={24} />}
            title="改考雷达加载失败"
            text={error}
            action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={load}>重试</Button>}
          />
        </Card>
      ) : items.length === 0 ? (
        <Card className="v3-notices-statecard">
          <Empty
            icon={<FileText size={24} />}
            title="暂无改考事件"
            text={canScan
              ? '点击「扫描最新公告」检测改考 / 停招等关键变动'
              : '公告采集入库后，这里会聚合改考 / 停招等关键变动'}
            action={canScan ? (
              <Button variant="tonal" icon={<Compass size={15} />} onClick={runScan} loading={scanning}>
                扫描最新公告
              </Button>
            ) : null}
          />
        </Card>
      ) : (
        <div className="v3-notices-radar__grid">
          {items.map((r) => {
            const tone = REFORM_TONE[r.change_type] || 'primary'
            return (
              <Card
                key={r.id}
                as="article"
                className={cx('v3-notices-reform', `tone-${tone}`)}
              >
                <div className="v3-notices-reform__head">
                  <span className="v3-notices-reform__kind">
                    {REFORM_TYPES[r.change_type] || <Warning size={13} />}
                    {r.change_type || '注意'}
                  </span>
                  {r.year ? <Badge tone="outline">{r.year} 年</Badge> : null}
                  <span className="v3-notices-reform__conf" title="规则匹配置信度">
                    置信 {Math.round((r.confidence || 0) * 100)}%
                  </span>
                </div>
                <h3 className="v3-notices-reform__title">{r.title}</h3>
                <div className="v3-notices-reform__meta">
                  {r.school_name ? (
                    r.school_id ? (
                      <Link to={`/kaoyan/schools/${r.school_id}`} className="v3-notices-reform__school">
                        <School size={14} />
                        {r.school_name}
                      </Link>
                    ) : (
                      <span className="v3-notices-reform__school">
                        <School size={14} />
                        {r.school_name}
                      </span>
                    )
                  ) : null}
                  {r.keywords ? <code className="v3-notices-reform__kw">命中：{r.keywords}</code> : null}
                  {r.url ? (
                    <a href={r.url} target="_blank" rel="noreferrer" className="v3-notices-reform__link">
                      公告原文 <ArrowUpRight size={13} />
                    </a>
                  ) : null}
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

/* ---------- 2027 考研关键日程 ---------- */
const KEY_SCHEDULE = [
  { label: '预报名', range: '2026-09-24 ~ 09-27', end: '2026-09-27', start: '2026-09-24' },
  { label: '正式报名', range: '2026-10-08 ~ 10-25', end: '2026-10-25', start: '2026-10-08' },
  { label: '网上确认', range: '10月底~11月初（各省不同）', end: null, start: null },
  { label: '准考证下载', range: '约 12-10 起', end: '2026-12-10', start: null },
  { label: '初试', range: '2026-12-19 ~ 12-20', end: '2026-12-19', start: '2026-12-19' },
  { label: '成绩公布', range: '2027-02 下旬', end: null, start: null },
  { label: '国家线', range: '2027-03 中旬', end: null, start: null },
  { label: '复试/调剂', range: '2027-03 ~ 04', end: null, start: null },
]

function KeyScheduleCard() {
  const today = todayStr()
  return (
    <Card className="v3-notices-schedule">
      <CardHead
        icon={<CalendarClock size={18} />}
        title="2027 考研关键日程"
        sub="以研招网与各省网报公告为准"
      />
      <div className="v3-notices-schedule__grid" role="group" aria-label="2027 考研关键日程">
        {KEY_SCHEDULE.map((s) => {
          const started = s.start ? daysBetween(today, s.start) <= 0 : false
          const dleft = s.end ? daysBetween(today, s.end) : null
          const state = dleft !== null && dleft < 0 ? 'past' : started ? 'now' : 'future'
          return (
            <div key={s.label} className={cx('v3-notices-schedule__item', `is-${state}`)}>
              <div className="v3-notices-schedule__main">
                <b>{s.label}</b>
                <span>{s.range}</span>
              </div>
              {state === 'now' ? <span className="v3-notices-schedule__state">进行中</span> : null}
              {state === 'future' && dleft !== null ? (
                <span className="v3-notices-schedule__state is-count">还剩 {dleft} 天</span>
              ) : null}
              {state === 'past' ? <span className="v3-notices-schedule__state is-done">已结束</span> : null}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

/* ---------- 主页面 ---------- */
export default function NoticeCenter() {
  const { isAdmin, user, status: authStatus } = useAuth()
  const isGuest = !user
  const {
    important_unread: importantUnread,
    urgent_unread: urgentUnread,
    refresh: refreshStats,
  } = useUnreadNotices({ enabled: !!user })

  const [tab, setTab] = useState('list')
  const [items, setItems] = useState([])
  const [meta, setMeta] = useState({ total: 0, unread: 0, page: 1, by_type_total: {} })
  const [status, setStatus] = useState('loading')
  const [fetching, setFetching] = useState(false)
  const [busy, setBusy] = useState(false)
  const [stats, setStats] = useState(null)

  const [readFilter, setReadFilter] = useState('all')
  const [noticeType, setNoticeType] = useState('')
  const [levelFilter, setLevelFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [kw, setKw] = useState('')
  const [kwInput, setKwInput] = useState('')

  const itemsRef = useRef(items)
  const reqSeq = useRef(0)
  useEffect(() => { itemsRef.current = items }, [items])

  const loadStats = useCallback(async () => {
    try {
      setStats(await kaoyanApi.noticeStats({ guest: isGuest }))
    } catch {
      setStats(null)
    }
  }, [isGuest])

  useEffect(() => {
    if (authStatus === 'loading') return
    loadStats()
  }, [authStatus, loadStats])

  const load = useCallback(async () => {
    const seq = ++reqSeq.current
    setFetching(true)
    setStatus(itemsRef.current.length ? 'ok' : 'loading')
    try {
      const d = await kaoyanApi.noticeList({
        unread_only: readFilter === 'unread',
        starred_only: readFilter === 'starred',
        notice_type: noticeType || undefined,
        keyword: kw || undefined,
        urgent_only: levelFilter === 'urgent',
        important_only: levelFilter === 'important',
        page,
        page_size: PAGE_SIZE,
      }, { guest: isGuest })
      if (seq !== reqSeq.current) return
      setItems(Array.isArray(d?.items) ? d.items : [])
      setMeta({
        total: d?.total ?? 0,
        unread: d?.unread ?? 0,
        page: d?.page ?? 1,
        by_type_total: d?.by_type_total || {},
      })
      setStatus('ok')
    } catch {
      if (seq !== reqSeq.current) return
      setItems([])
      setStatus('error')
    } finally {
      if (seq === reqSeq.current) setFetching(false)
    }
  }, [readFilter, noticeType, levelFilter, kw, page, isGuest])

  useEffect(() => {
    if (authStatus === 'loading') return
    load()
  }, [authStatus, load])

  const refreshAll = useCallback(async () => {
    await Promise.all([load(), isGuest ? null : refreshStats(), loadStats()])
  }, [load, refreshStats, loadStats, isGuest])

  const onSearch = (e) => {
    e.preventDefault()
    setKw(kwInput.trim())
    setPage(1)
  }

  const clearSearch = () => {
    setKwInput('')
    setKw('')
    setPage(1)
  }

  const changeReadFilter = (v) => {
    setReadFilter(v)
    setPage(1)
  }

  const onItemClick = useCallback(async (n) => {
    if (isGuest || n.is_read) return
    setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)))
    try {
      await kaoyanApi.markNoticeRead(n.id, true)
      await refreshStats()
    } catch {
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: false } : x)))
      toast('标记已读失败，请重试')
    }
  }, [refreshStats, isGuest])

  const onToggleStar = useCallback(async (e, n) => {
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
  }, [refreshStats])

  const onMarkAllRead = useCallback(async () => {
    setBusy(true)
    try {
      const r = await kaoyanApi.batchMarkNoticeRead({ all: true })
      toast(`已将 ${r?.updated ?? 0} 条通知标为已读`)
      await load()
      await refreshStats()
      await loadStats()
    } catch {
      toast('操作失败，请重试')
    } finally {
      setBusy(false)
    }
  }, [load, refreshStats, loadStats])

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

  const typeOptions = useMemo(() => {
    const opts = [{ value: '', label: '全部类型' }]
    // 公共聚合接口的 by_type 会跟着当前类型筛选收缩；访客的类型候选改用全局统计，
    // 否则选中某一类后下拉里就只剩这一类。
    const source = isGuest && Array.isArray(stats?.by_type)
      ? Object.fromEntries(stats.by_type.map((x) => [x.type, x.total]))
      : (meta.by_type_total || {})
    Object.entries(source)
      .sort((a, b) => b[1] - a[1])
      .forEach(([t, n]) => opts.push({ value: t, label: `${t} ${n}` }))
    return opts
  }, [meta.by_type_total, stats, isGuest])

  const filterOptions = [
    { value: 'all', label: '全部' },
    { value: 'unread', label: `只看未读${meta.unread ? ` ${meta.unread}` : ''}` },
    { value: 'starred', label: '只看加星' },
  ]

  const levelOptions = [
    { value: 'all', label: '全部等级' },
    { value: 'urgent', label: `仅紧急${urgentUnread ? ` ${urgentUnread}` : ''}` },
    { value: 'important', label: `仅重要${importantUnread ? ` ${importantUnread}` : ''}` },
  ]

  const totalPages = Math.max(1, Math.ceil(meta.total / PAGE_SIZE))
  const readPct = meta.total > 0 ? ((meta.total - meta.unread) / meta.total) * 100 : 0
  const statTypes = ['简章', '复试', '报名', '初试']

  const emptyAction = readFilter === 'unread' ? (
    <Button variant="tonal" size="sm" onClick={() => changeReadFilter('all')}>查看全部通知</Button>
  ) : kw ? (
    <Button variant="tonal" size="sm" onClick={clearSearch}>清除搜索</Button>
  ) : null

  return (
    <div className="v3-notices">
      <div className="v3-notices-head">
        <div>
          <div className="v3-eyebrow">INBOX · 考研情报</div>
          <h1 className="v3-notices-head__title">通知中心</h1>
          <p className="v3-notices-head__sub">
            {isGuest
              ? '院校公告、报名节点与改考动态，公开浏览；登录后可标记已读并接收提醒。'
              : '院校公告、报名节点与改考动态，逐条标记，不错过任何关键消息。'}
          </p>
        </div>
        <div className="v3-notices-head__actions">
          {tab === 'list' ? (
            <Button
              variant="outline"
              icon={<RefreshCw size={15} />}
              onClick={refreshAll}
              loading={fetching}
            >
              刷新
            </Button>
          ) : null}
          <div className="v3-notices-head__alerts">
            {isGuest ? (
              <Badge tone="outline">访客只读</Badge>
            ) : (
              <>
                {urgentUnread > 0 ? (
                  <Badge tone="danger">紧急未读 {urgentUnread}</Badge>
                ) : (
                  <Badge tone="success">无紧急未读</Badge>
                )}
                {importantUnread > 0 ? <Badge tone="warning">重要未读 {importantUnread}</Badge> : null}
              </>
            )}
          </div>
        </div>
      </div>

      <div className="v3-notices-tabs">
        <Segmented
          options={[
            { value: 'list', label: '通知列表', icon: <Bell size={15} /> },
            { value: 'reform', label: '改考雷达', icon: <Compass size={15} /> },
          ]}
          value={tab}
          onChange={setTab}
          ariaLabel="通知中心视图"
        />
        <span className="v3-notices-tabs__note">数据源 · 研招网 / 院校研究生院</span>
      </div>

      {tab === 'reform' ? (
        <ReformRadar canScan={isAdmin} />
      ) : status === 'loading' ? (
        <Card className="v3-notices-statecard">
          <LoadingState text="通知加载中…" />
        </Card>
      ) : status === 'error' ? (
        <Card className="v3-notices-statecard">
          <Empty
            icon={<Warning size={24} />}
            title="通知加载失败"
            text="后端未启动或网络异常，请确认服务已启动后重试。"
            action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={load}>重试</Button>}
          />
        </Card>
      ) : (
        <>
          <Card className="v3-notices-overview" glow>
            <div className="v3-notices-overview__left">
              {isGuest ? (
                <>
                  <div className="v3-notices-overview__unread">
                    <AnimatedNumber value={meta.total} className="v3-notices-overview__num" />
                    <span>条公告</span>
                  </div>
                  <div className="v3-notices-overview__sub">
                    <span>公共信息浏览 · 登录后可标记已读、加星与接收提醒</span>
                  </div>
                </>
              ) : (
                <>
                  <div className="v3-notices-overview__unread">
                    <AnimatedNumber value={meta.unread} className="v3-notices-overview__num" />
                    <span>条未读</span>
                  </div>
                  <div className="v3-notices-overview__sub">
                    <span>共 {meta.total} 条通知</span>
                    {urgentUnread > 0 ? <em className="is-urgent">含 {urgentUnread} 条紧急未读</em> : null}
                    {importantUnread > urgentUnread ? <em>重要未读 {importantUnread} 条</em> : null}
                  </div>
                  <div className="v3-notices-overview__progress">
                    <Progress value={readPct} gradient />
                    <span>已读 {Math.round(readPct)}%</span>
                  </div>
                </>
              )}
            </div>
            {isGuest ? null : (
              <div className="v3-notices-overview__actions">
                {isAdmin ? (
                  <Button
                    variant="tonal"
                    icon={<Star size={15} />}
                    onClick={onStarImportant}
                    loading={busy}
                  >
                    关键类型加星
                  </Button>
                ) : null}
                <Button
                  variant="filled"
                  icon={<Check size={15} />}
                  onClick={onMarkAllRead}
                  disabled={busy || meta.unread === 0}
                >
                  全部已读
                </Button>
              </div>
            )}
          </Card>

          {stats && stats.total > 0 ? (
            <Card className="v3-notices-stats">
              <div className="v3-notices-stats__grid" role="group" aria-label="通知分类统计">
                {statTypes.map((t) => {
                  const hit = (stats.by_type || []).find((x) => x.type === t)
                  const n = hit ? hit.total : 0
                  return (
                    <button
                      key={t}
                      type="button"
                      className={cx('v3-notices-stat', noticeType === t && 'is-on')}
                      onClick={() => {
                        setNoticeType(noticeType === t ? '' : t)
                        setPage(1)
                      }}
                      aria-pressed={noticeType === t}
                    >
                      <span className="v3-notices-stat__value">{n}</span>
                      <span className="v3-notices-stat__label">{t}</span>
                      {!isGuest && hit?.unread ? <span className="v3-notices-stat__unread">未读 {hit.unread}</span> : null}
                    </button>
                  )
                })}
              </div>
              <div className="v3-notices-stats__meta">
                <span><School size={14} />覆盖院校 {stats.schools_covered} 所</span>
                {isGuest ? null : (
                  <>
                    <span>未读 {stats.unread}</span>
                    <span>星标 {stats.starred}</span>
                  </>
                )}
              </div>
            </Card>
          ) : null}

          <KeyScheduleCard />

          <Card className="v3-notices-filters">
            <form className="v3-notices-search" onSubmit={onSearch}>
              <Input
                icon={<Search size={16} />}
                value={kwInput}
                onChange={(e) => setKwInput(e.target.value)}
                placeholder="搜索公告标题，如「初试科目」…"
                aria-label="搜索公告标题"
              />
              <Button variant="tonal" type="submit">搜索</Button>
              {kw ? <Button variant="text" onClick={clearSearch}>清除</Button> : null}
            </form>
            {isGuest ? null : (
              <Segmented
                options={filterOptions}
                value={readFilter}
                onChange={changeReadFilter}
                ariaLabel="已读状态筛选"
              />
            )}
            <Select
              className="v3-notices-select"
              aria-label="按通知类型过滤"
              value={noticeType}
              onChange={(e) => { setNoticeType(e.target.value); setPage(1) }}
              options={typeOptions}
            />
            {isGuest ? null : (
              <Select
                className="v3-notices-select"
                aria-label="按重要度筛选"
                value={levelFilter}
                onChange={(e) => { setLevelFilter(e.target.value); setPage(1) }}
                options={levelOptions}
              />
            )}
          </Card>

          <Card className="v3-notices-listcard">
            <CardHead
              icon={<Bell size={18} />}
              title="公告列表"
              sub={isGuest ? '点击任意通知查看原文' : '点击任意通知即标记为已读'}
              actions={<Badge tone="outline">共 {meta.total} 条</Badge>}
            />
            {items.length === 0 ? (
              <Empty
                icon={<FileText size={24} />}
                title={readFilter === 'unread' ? '没有未读通知' : '暂无通知'}
                text={readFilter === 'unread' ? '所有通知都已标记为已读' : '暂无符合筛选条件的通知'}
                action={emptyAction}
              />
            ) : (
              <div className="v3-notices-list">
                {items.map((n) => {
                  const lv = levelOf(n)
                  return (
                    <article
                      key={n.id}
                      className={cx(
                        'v3-notices-item',
                        !isGuest && (n.is_read ? 'is-read' : 'is-unread'),
                        !isGuest && n.is_starred && 'is-starred',
                        `lv-${lv}`,
                      )}
                    >
                      {/* 访客不显示未读圆点，但必须保留 8px 网格列，否则正文会被挤成一字一行 */}
                      <span
                        className="v3-notices-dot"
                        aria-hidden="true"
                        style={isGuest ? { visibility: 'hidden' } : undefined}
                      />
                      <a
                        className="v3-notices-item__main"
                        href={n.url || '#'}
                        target="_blank"
                        rel="noreferrer"
                        title={n.title}
                        onClick={(e) => {
                          if (!n.url) e.preventDefault()
                          onItemClick(n)
                        }}
                      >
                        <span className="v3-notices-item__top">
                          <span className="v3-notices-item__school">{n.school_name || '未知院校'}</span>
                          <span className="v3-notices-item__date">{humanDate(n.publish_date) || '—'}</span>
                        </span>
                        <span className="v3-notices-item__title">{n.title}</span>
                        <span className="v3-notices-item__tags">
                          {n.notice_type ? (
                            <Badge tone={TYPE_TONE[n.notice_type] || 'outline'}>{n.notice_type}</Badge>
                          ) : null}
                          {!isGuest && lv !== 'normal' && !n.is_read ? (
                            <Badge tone={lv === 'urgent' ? 'danger' : 'warning'}>{LEVEL_LABEL[lv]}</Badge>
                          ) : null}
                          {!isGuest && n.is_starred ? (
                            <span className="v3-notices-item__starred"><Star size={12} />重点</span>
                          ) : null}
                          {n.url ? <span className="v3-notices-item__open">原文 <ArrowUpRight size={12} /></span> : null}
                        </span>
                      </a>
                      {isGuest ? null : (
                        <IconButton
                          label={n.is_starred ? '取消加星' : '加星置顶'}
                          className={cx('v3-notices-star', n.is_starred && 'is-on')}
                          icon={<Star size={18} />}
                          onClick={(e) => onToggleStar(e, n)}
                          aria-pressed={!!n.is_starred}
                        />
                      )}
                    </article>
                  )
                })}
              </div>
            )}

            {totalPages > 1 ? (
              <div className="v3-notices-pager">
                <Button
                  variant="outline"
                  size="sm"
                  icon={<ChevronLeft size={15} />}
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  上一页
                </Button>
                <span className="v3-notices-pager__info">第 {page} / {totalPages} 页</span>
                <Button
                  variant="outline"
                  size="sm"
                  trailingIcon={<ChevronRight size={15} />}
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                </Button>
              </div>
            ) : null}
          </Card>
        </>
      )}
    </div>
  )
}
