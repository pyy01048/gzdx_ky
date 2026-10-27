/**
 * 今日聚合中枢（/hub）
 *
 * 为什么单独做这一页，而不是把仪表盘再加长：
 *  - 仪表盘回答「我整体怎么样」，是**统计快照**；
 *  - 中枢回答「我现在先做什么」，是**行动聚合**。
 * 两者数据同源（/dashboard/summary + /insight/today + /words/stats + /review/stats），
 * 但信息组织方式不同：这里把到期、薄弱点、任务、单词、专注、刷题合成一条
 * 动态航线，顺序由真实数据计算，不是写死的卡片堆。
 *
 * 页面能力：
 *  - 动态聚合：api/hub.js 一个出口，带缓存 / 部分失败降级 / 口径对账；
 *  - 交互：航线跳转、KPI 下钻、任务乐观完成、专注计时、趋势切换、布局拖拽；
 *  - 动效：极光、分级入场、数字滚动、图表绘制、悬停追光；
 *  - 响应式 / 无障碍：移动端单列、键盘可操作、prefers-reduced-motion 降级。
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { fetchHubOverview, peekHubCache } from '../../api/hub'
import { tasksApi } from '../../api/client'
import { MUTATION_EVENT, MUTATION_REFRESH_DELAY } from '../../api/mutationEvent'
import { ukey, readMigrated } from '../../utils/userKeys'
import { MiniBarChart, MiniLineChart, HeatMap } from '../charts'
import { FocusTile } from './widgets'
import {
  AnimatedNumber, Button, Chip, Dialog, Empty, IconButton, Progress, Ring, Segmented,
  Skeleton, Switch, cx, toast, toastErr, toastOk,
} from '../ui'
import {
  Activity, AlertTriangle, ArrowRight, ArrowUpRight, Book, Brain, Calendar, Check,
  CheckCircle2, ChevronDown, ChevronRight, ChevronUp, Clock, Flame, Gauge, Info, Layers,
  ListChecks, RefreshCw, RotateCcw, SlidersHorizontal, Sparkles, Target, Timer, TrendingDown,
  TrendingUp, Trophy, Zap,
} from '../icons'
import '../styles/pages.css'
import '../styles/hub-v3.css'

const LAYOUT_KEY = 'hub_layout_v1'

/* 可聚合区块。id 是布局持久化的稳定键，新增区块会被自动追加到末尾。 */
const BLOCKS = [
  { id: 'trend', label: '14 天趋势', span: 8 },
  { id: 'focus', label: '专注计时', span: 4 },
  { id: 'heat', label: '学习热力', span: 8 },
  { id: 'weak', label: '薄弱点', span: 4 },
  { id: 'tasks', label: '今日任务', span: 6 },
  { id: 'modules', label: '模块进度', span: 6 },
  { id: 'caliber', label: '数据口径', span: 12 },
]
const BLOCK_IDS = BLOCKS.map((b) => b.id)
const BLOCK_BY_ID = Object.fromEntries(BLOCKS.map((b) => [b.id, b]))

const MODULE_ROUTE = {
  focus: '/planner',
  word: '/words',
  new_word: '/words',
  card: '/cards',
  question: '/quiz',
  realexam: '/exam',
  wrongbook: '/error-review',
  coding: '/codebank',
  task: '/tasks',
}

const QUEUE_ICON = {
  review: RotateCcw,
  target: Target,
  todo: ListChecks,
  word: Book,
  card: Layers,
  focus: Timer,
  brain: Brain,
}

const KPI_ICON = {
  focus: Timer,
  questions: Zap,
  accuracy: Target,
  streak: Flame,
}

const TREND_METRICS = [
  { value: 'focus', label: '专注', unit: '分钟' },
  { value: 'questions', label: '答题', unit: '道' },
  { value: 'accuracy', label: '正确率', unit: '%' },
]

const sum = (list) => list.reduce((a, b) => a + (Number(b) || 0), 0)
const avg = (list) => (list.length ? sum(list) / list.length : 0)
const fmt = (n) => (Number.isFinite(Number(n)) ? new Intl.NumberFormat('zh-CN').format(Number(n)) : '—')

function greeting() {
  const h = new Date().getHours()
  if (h < 5) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 13) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

function agoLabel(ts) {
  if (!ts) return '尚未同步'
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 15) return '刚刚同步'
  if (s < 60) return `${s} 秒前同步`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分钟前同步`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前同步`
  return `${Math.floor(h / 24)} 天前同步`
}

const first = (v) => (Array.isArray(v) ? v[0] : '')

/* -------------------------------------------------------------------------- */
/* 布局偏好（按账号隔离、设备相关，写 localStorage 不污染后端 settings）           */
/* -------------------------------------------------------------------------- */
function normalizeLayout(raw) {
  const src = raw && typeof raw === 'object' ? raw : {}
  const seen = []
  ;(Array.isArray(src.order) ? src.order : []).forEach((id) => {
    if (BLOCK_IDS.includes(id) && !seen.includes(id)) seen.push(id)
  })
  const rest = BLOCK_IDS.filter((id) => !seen.includes(id))
  const hidden = (Array.isArray(src.hidden) ? src.hidden : []).filter((id) => BLOCK_IDS.includes(id))
  return { order: [...seen, ...rest], hidden }
}

function readLayout() {
  try {
    return normalizeLayout(readMigrated(LAYOUT_KEY, null))
  } catch {
    return normalizeLayout(null)
  }
}

function saveLayout(layout) {
  try {
    localStorage.setItem(ukey(LAYOUT_KEY), JSON.stringify(layout))
  } catch {
    /* 隐私模式 / 配额满：仅内存态生效 */
  }
}

/* -------------------------------------------------------------------------- */
/* 小组件                                                                      */
/* -------------------------------------------------------------------------- */
function Delta({ value, unit = '', pp = false }) {
  if (value == null) return null
  if (Number(value) === 0) return <span className="hub-delta">与昨日持平</span>
  const up = Number(value) > 0
  const Icon = up ? TrendingUp : TrendingDown
  return (
    <span className={cx('hub-delta', up ? 'is-up' : 'is-down')}>
      <Icon size={13} />
      {`${up ? '+' : ''}${value}${pp ? 'pp' : unit}`}
    </span>
  )
}

function PanelHead({ title, sub, icon, actions }) {
  return (
    <div className="hub-panel__head">
      <div className="hub-panel__heading">
        <span className="hub-panel__title">
          {icon}
          {title}
        </span>
        {sub ? <span className="hub-panel__sub">{sub}</span> : null}
      </div>
      {actions ? <div className="hub-panel__actions">{actions}</div> : null}
    </div>
  )
}

/* 骨架屏：结构与真实页面同形，避免数据到达时跳版 */
function HubSkeleton() {
  return (
    <div className="hub hub--skeleton" aria-busy="true" aria-label="聚合数据加载中">
      <section className="hub-hero hub-glass">
        <div className="hub-hero__main">
          <Skeleton width={160} height={12} />
          <Skeleton width="58%" height={40} style={{ marginTop: 18 }} />
          <Skeleton width="38%" height={14} style={{ marginTop: 12 }} />
          <div className="hub-hero__actions" style={{ marginTop: 22 }}>
            <Skeleton width={148} height={42} radius={999} />
            <Skeleton width={118} height={42} radius={999} />
          </div>
        </div>
        <div className="hub-hero__aside">
          <Skeleton width={132} height={132} radius={999} />
        </div>
      </section>
      <section className="hub-onboard hub-glass">
        <div className="hub-onboard__main">
          <Skeleton width={150} height={18} />
          <Skeleton width="82%" height={14} style={{ marginTop: 10 }} />
          <Skeleton width="64%" height={14} style={{ marginTop: 8 }} />
        </div>
        <Skeleton width={96} height={40} radius={999} />
      </section>
      <div className="hub-kpis">
        {[0, 1, 2, 3].map((i) => (
          <div className="hub-kpi hub-glass" key={i}>
            <Skeleton width="48%" height={12} />
            <Skeleton width="62%" height={34} style={{ marginTop: 14 }} />
            <Skeleton width="78%" height={12} style={{ marginTop: 12 }} />
          </div>
        ))}
      </div>
      <div className="hub-blocks">
        <div className="hub-block hub-panel hub-span-8">
          <Skeleton width={180} height={16} />
          <Skeleton width="100%" height={150} style={{ marginTop: 18 }} />
        </div>
        <div className="hub-block hub-panel hub-span-4">
          <Skeleton width={120} height={16} />
          <Skeleton width="100%" height={150} style={{ marginTop: 18 }} />
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* 主页面                                                                      */
/* -------------------------------------------------------------------------- */
export default function Hub() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const [layout, setLayout] = useState(readLayout)
  const [data, setData] = useState(() => peekHubCache())
  const [status, setStatus] = useState(() => (peekHubCache() ? 'stale' : 'loading'))
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [syncedAt, setSyncedAt] = useState(() => (peekHubCache() ? Date.now() : 0))
  const [taskBusy, setTaskBusy] = useState(null)
  const [metric, setMetric] = useState('focus')
  const [customOpen, setCustomOpen] = useState(false)
  const [dragId, setDragId] = useState(null)
  const [, setTick] = useState(0)

  const aliveRef = useRef(true)
  const dataRef = useRef(data)
  const lastLoadRef = useRef(0)

  /* StrictMode 会「挂载→卸载→再挂载」：setup 里必须复位 alive，
     否则第一次清理把 ref 置 false 后，首屏请求回来直接 return，页面永远停在骨架屏。 */
  useEffect(() => {
    aliveRef.current = true
    return () => { aliveRef.current = false }
  }, [])
  useEffect(() => { dataRef.current = data }, [data])

  /* 15s 刷新一次「x 分钟前同步」，让时间标签活着但不频繁重渲染 */
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 15000)
    return () => clearInterval(t)
  }, [])

  const load = useCallback(async ({ force = false, silent = false } = {}) => {
    if (!silent) setRefreshing(true)
    try {
      const next = await fetchHubOverview({ force })
      if (!aliveRef.current) return
      setData(next)
      setStatus('ok')
      setError(null)
      setSyncedAt(Date.now())
      lastLoadRef.current = Date.now()
    } catch (e) {
      if (!aliveRef.current) return
      setError(e)
      setStatus(dataRef.current ? 'ok' : 'error')
      if (!silent) toastErr(e?.message || '聚合数据加载失败')
    } finally {
      if (aliveRef.current) setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      if (Date.now() - lastLoadRef.current < 55_000) return
      load({ silent: true })
    }, 60_000)
    const onVisible = () => {
      if (document.visibilityState === 'visible' && Date.now() - lastLoadRef.current > 55_000) {
        load({ silent: true })
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [load])

  /* client.js 的任何写接口成功（答题/打卡/背词/专注记录…）都会广播 MUTATION_EVENT：
     防抖后静默刷新一次，让中枢在用户停留时跟上数据，又不会被高频操作打爆。
     页面在后台标签页时不刷 —— 回到前台由 visibilitychange 分支接管。 */
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return undefined
    let timer = null
    const onMutation = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        timer = null
        if (aliveRef.current && document.visibilityState === 'visible') load({ silent: true })
      }, MUTATION_REFRESH_DELAY)
    }
    window.addEventListener(MUTATION_EVENT, onMutation)
    return () => {
      if (timer) clearTimeout(timer)
      window.removeEventListener(MUTATION_EVENT, onMutation)
    }
  }, [load])

  const refresh = useCallback(async () => {
    await load({ force: true })
    if (aliveRef.current) toastOk('今日中枢已刷新')
  }, [load])

  const persist = useCallback((next) => {
    setLayout(next)
    saveLayout(next)
  }, [])

  const moveBlock = useCallback((id, dir) => {
    setLayout((cur) => {
      const idx = cur.order.indexOf(id)
      const to = idx + dir
      if (idx < 0 || to < 0 || to >= cur.order.length) return cur
      const order = [...cur.order]
      ;[order[idx], order[to]] = [order[to], order[idx]]
      const next = { ...cur, order }
      saveLayout(next)
      return next
    })
  }, [])

  const toggleBlock = useCallback((id) => {
    setLayout((cur) => {
      const hidden = cur.hidden.includes(id) ? cur.hidden.filter((x) => x !== id) : [...cur.hidden, id]
      const next = { ...cur, hidden }
      saveLayout(next)
      return next
    })
  }, [])

  const resetLayout = useCallback(() => {
    const next = normalizeLayout(null)
    persist(next)
    toast('已恢复默认聚合布局')
  }, [persist])

  const onDragStart = (e, id) => {
    setDragId(id)
    e.dataTransfer.effectAllowed = 'move'
    try { e.dataTransfer.setData('text/plain', id) } catch { /* 部分浏览器限制 */ }
  }
  const onDragOver = (e, id) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (!dragId || dragId === id) return
    setLayout((cur) => {
      const from = cur.order.indexOf(dragId)
      const to = cur.order.indexOf(id)
      if (from < 0 || to < 0) return cur
      const order = [...cur.order]
      order.splice(from, 1)
      order.splice(to, 0, dragId)
      return { ...cur, order }
    })
  }
  const onDragEnd = () => {
    setDragId(null)
    setLayout((cur) => {
      saveLayout(cur)
      return cur
    })
  }

  const toggleTask = async (task) => {
    if (taskBusy) return
    const id = Number(task.id)
    if (!Number.isInteger(id)) {
      toast('该任务没有后端 id，暂不支持打卡')
      return
    }
    const done = task.status !== 'done'
    setTaskBusy(task.id)
    setData((cur) => {
      if (!cur) return cur
      const items = cur.tasks.items.map((t) => (t.id === task.id ? { ...t, status: done ? 'done' : 'pending' } : t))
      return {
        ...cur,
        tasks: {
          ...cur.tasks,
          items,
          done: items.filter((t) => t.status === 'done').length,
          pending: items.filter((t) => t.status !== 'done').length,
        },
      }
    })
    try {
      if (done) await tasksApi.complete(id)
      else await tasksApi.uncomplete(id)
      toastOk(done ? '任务已完成' : '已取消完成')
      await load({ force: true, silent: true })
    } catch (e) {
      toastErr(e?.message || '同步失败，已回滚')
      await load({ force: true, silent: true })
    } finally {
      if (aliveRef.current) setTaskBusy(null)
    }
  }

  const scrollToJourney = () => {
    const el = document.getElementById('hub-journey')
    if (!el) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  }

  const onRecorded = useCallback(() => {
    toastOk('专注时长已写入今日 KPI')
    load({ force: true, silent: true })
  }, [load])

  const visibleBlocks = useMemo(
    () => layout.order.filter((id) => !layout.hidden.includes(id) && BLOCK_BY_ID[id]),
    [layout],
  )

  if (!data) {
    if (status === 'error') {
      return (
        <div className="hub hub--error">
          <section className="hub-error hub-glass">
            <span className="hub-error__icon"><AlertTriangle size={30} /></span>
            <h1 className="hub-error__title">聚合数据暂时取不到</h1>
            <p className="hub-error__text">{String(error?.message || '后端不可达或会话已过期')}</p>
            <div className="hub-row">
              <Button variant="gradient" icon={<RefreshCw size={16} />} onClick={refresh}>重试</Button>
              <Button variant="tonal" onClick={() => navigate('/')}>先看旧版仪表盘</Button>
            </div>
          </section>
        </div>
      )
    }
    return <HubSkeleton />
  }

  const q = data.queue
  const steps = q.items
  const countdown = data.countdown
  const today = data.today
  const rate = today.correct_rate == null ? null : Math.round(today.correct_rate)
  const providerName = user?.display_name || user?.username || '同学'

  /* 备考进程环：以「今年 1 月 1 日 → 初试日」为一条完整时间轴 */
  const ringPct = (() => {
    if (!countdown.examDate) return 0
    const start = new Date(`${new Date().getFullYear()}-01-01T00:00:00`)
    const end = new Date(`${countdown.examDate}T00:00:00`)
    const total = end - start
    if (!Number.isFinite(total) || total <= 0) return 0
    return Math.max(0, Math.min(100, ((Date.now() - start) / total) * 100))
  })()

  const metrics = data.kpiCards

  const trendSeries = data.trend.series
  const trendValues = trendSeries.map((d) => {
    if (metric === 'focus') return Number(d.focus) || 0
    if (metric === 'questions') return Number(d.questions) || 0
    return d.correctRate == null ? 0 : Number(d.correctRate) || 0
  })
  const metricDef = TREND_METRICS.find((m) => m.value === metric) || TREND_METRICS[0]
  const trendHeadline = metric === 'accuracy' ? `${Math.round(avg(trendValues))}%` : fmt(sum(trendValues))
  const trendUnit = metric === 'accuracy' ? '' : metricDef.unit
  const trendHasData = trendValues.some((v) => v > 0)

  const heatDays = data.heatmap.days.slice(-84)
  const heatFocus = sum(heatDays.map((d) => d.focus))
  const heatActive = heatDays.filter((d) => d.focus > 0 || d.questions > 0 || d.words > 0).length

  const sourceOk = data.sources.filter((s) => s.ok).length
  const sourceTotal = data.sources.length

  return (
    <div className="hub">
      {/* 极光背景：只做视觉，不拦截事件 */}
      <div className="hub-aurora" aria-hidden="true">
        <span className="hub-aurora__blob hub-aurora__blob--a" />
        <span className="hub-aurora__blob hub-aurora__blob--b" />
        <span className="hub-aurora__blob hub-aurora__blob--c" />
        <span className="hub-aurora__grid" />
      </div>

      <header className="hub-hero hub-glass">
        <span className="hub-hero__sheen" aria-hidden="true" />
        <div className="hub-hero__main">
          <div className="hub-eyebrow">
            <Sparkles size={14} />
            <span>今日中枢</span>
            <span className="hub-eyebrow__dot" aria-hidden="true">·</span>
            <span>动态聚合 {sourceOk}/{sourceTotal} 个数据源</span>
            <span className={cx('hub-live', status === 'stale' && 'is-stale')} aria-label="数据状态">
              <i aria-hidden="true" />
              {refreshing ? '刷新中' : agoLabel(syncedAt)}
            </span>
          </div>

          <h1 className="hub-hero__title">
            {greeting()}，{providerName}
          </h1>
          <p className="hub-hero__sub">
            {data.dateLabel}
            {data.goalLine ? ` · ${data.goalLine}` : ' · 还没有设置目标院校'}
          </p>

          <div className="hub-hero__chips">
            {countdown.phaseLabel ? <Chip as="span" active>{countdown.phaseLabel}</Chip> : null}
            <Chip as="span" icon={<Flame size={14} />}>连续 {data.streak.current} 天</Chip>
            <Chip as="span" icon={<Clock size={14} />}>今日专注 {today.focus_minutes || 0} 分钟</Chip>
            {data.degraded ? <Chip as="span" icon={<AlertTriangle size={14} />}>部分数据降级</Chip> : null}
          </div>

          <div className="hub-hero__actions">
            <Button variant="gradient" icon={<Zap size={16} />} onClick={scrollToJourney}>
              开始今日航线
            </Button>
            <Button variant="tonal" icon={<SlidersHorizontal size={16} />} onClick={() => setCustomOpen(true)}>
              聚合布局
            </Button>
            <IconButton
              label="刷新聚合数据"
              variant="ghost"
              icon={<RefreshCw size={17} className={refreshing ? 'hub-spin' : ''} />}
              onClick={refresh}
              disabled={refreshing}
            />
          </div>
        </div>

        <div className="hub-hero__aside">
          <div className="hub-countdown">
            <Ring value={ringPct} size={132} stroke={9} gradient>
              <div className="hub-countdown__inside">
                <span className="hub-countdown__days">
                  {countdown.days == null ? '—' : <AnimatedNumber value={countdown.days} />}
                </span>
                <span className="hub-countdown__unit">天</span>
              </div>
            </Ring>
            <div className="hub-countdown__meta">
              <span className="hub-countdown__label">距离 {countdown.examYear || '目标'} 考研</span>
              <strong>{countdown.examDate || '未设置初试日期'}</strong>
              <span className="hub-countdown__note">
                {countdown.isDefault ? '日期为系统估算，去目标页核对' : '备考时间轴已走过 ' + Math.round(ringPct) + '%'}
              </span>
            </div>
          </div>

          <div className="hub-hero__stats">
            <div>
              <span>今日答题</span>
              <b>{today.questions_done || 0}<small>道</small></b>
            </div>
            <div>
              <span>正确率</span>
              <b>{rate == null ? '—' : rate}<small>{rate == null ? '' : '%'}</small></b>
            </div>
            <div>
              <span>今日新词</span>
              <b>{data.words.new}<small>词</small></b>
            </div>
          </div>
        </div>
      </header>

      {data.degraded ? (
        <div className="hub-banner hub-banner--warn" role="status">
          <AlertTriangle size={16} />
          <span>
            部分数据源暂不可用：{data.failedSources.map((s) => s.label).join('、')}。其余指标照常展示，可稍后刷新。
          </span>
          <button type="button" className="hub-banner__action" onClick={refresh}>立即重试</button>
        </div>
      ) : null}

      {data.dataCoverage?.is_empty ? (
        <div className="hub-banner" role="status">
          <Info size={16} />
          <span>还没有学习记录。先从一次 25 分钟专注或 10 个单词开始，热力图和趋势会自动长出来。</span>
          <button type="button" className="hub-banner__action" onClick={() => navigate('/words')}>去背单词</button>
        </div>
      ) : null}

      {/* ── 今日航线：页面聚合的行动层 ─────────────────────────────── */}
      <section id="hub-journey" className="hub-journey hub-panel hub-glass" aria-labelledby="hub-journey-title">
        <div className="hub-panel__head">
          <div className="hub-panel__heading">
            <span className="hub-panel__title" id="hub-journey-title"><Zap size={18} /> 今日航线</span>
            <span className="hub-panel__sub">
              按真实到期量与薄弱点动态排序 · 已完成 {q.doneCount}/{q.total}
            </span>
          </div>
          <div className="hub-journey__progress">
            <Progress value={q.progress} gradient />
            <span>{q.progress}%</span>
          </div>
        </div>

        <div className="hub-steps">
          {steps.map((step, i) => {
            const Icon = QUEUE_ICON[step.icon] || Zap
            const active = q.activeId === step.id
            return (
              <button
                key={step.id}
                type="button"
                className={cx('hub-step', `hub-toned--${step.tone}`, step.done && 'is-done', active && 'is-active')}
                onClick={() => navigate(step.to)}
                style={{ '--i': i }}
                aria-label={`${step.label}：${step.hint}${step.done ? '（已完成）' : ''}`}
              >
                <span className="hub-step__index" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
                <span className="hub-step__icon"><Icon size={19} /></span>
                <span className="hub-step__label">{step.label}</span>
                <span className="hub-step__count">
                  {step.done ? <Check size={13} /> : null}
                  {fmt(step.count)}<small>{step.unit}</small>
                </span>
                <span className="hub-step__hint">{step.hint}</span>
                <span className="hub-step__go" aria-hidden="true"><ChevronRight size={16} /></span>
                <span className="hub-step__urgency" aria-hidden="true" style={{ '--u': `${Math.min(100, step.urgency)}%` }} />
              </button>
            )
          })}
        </div>

        <div className="hub-journey__foot">
          <span><Gauge size={14} /> 排序规则：到期欠账 → 薄弱点 → 任务 → 单词/卡片 → 专注 → 刷题</span>
          <Link to="/planner" className="hub-link">打开完整计划 <ArrowRight size={14} /></Link>
        </div>
      </section>

      {/* ── KPI：从聚合模型里取，不各打接口 ──────────────────────────── */}
      <section className="hub-kpis" aria-label="今日关键指标">
        {metrics.map((card, i) => {
          const Icon = KPI_ICON[card.icon] || Activity
          const color = {
            indigo: 'var(--v3-primary)',
            cyan: 'var(--v3-info)',
            violet: 'var(--v3-secondary)',
            amber: 'var(--v3-warning)',
          }[card.tone] || 'var(--v3-primary)'
          return (
            <button
              key={card.id}
              type="button"
              className={cx('hub-kpi', 'hub-glass', `hub-toned--${card.tone}`)}
              style={{ '--i': i }}
              onClick={() => navigate(card.to)}
              aria-label={`${card.label} ${card.value == null ? '暂无数据' : `${card.value}${card.unit}`}，点击查看`}
            >
              <span className="hub-kpi__top">
                <span className="hub-kpi__label"><Icon size={15} /> {card.label}</span>
                <ArrowUpRight size={16} className="hub-kpi__arrow" />
              </span>
              <span className="hub-kpi__value">
                {card.value == null ? <span className="hub-kpi__na">—</span> : <AnimatedNumber value={card.value} />}
                {card.value == null ? null : <small>{card.unit}</small>}
              </span>
              <span className="hub-kpi__meta">
                {card.delta != null ? <Delta value={card.delta} unit={card.unit === '%' ? '%' : ''} pp={card.id === 'accuracy'} /> : null}
                <span className="hub-kpi__hint">{card.hint}</span>
              </span>
              <span className="hub-kpi__spark" aria-hidden="true">
                <MiniLineChart data={card.series.map((v) => ({ value: v }))} height={42} color={color} showArea strokeWidth={2} />
              </span>
            </button>
          )
        })}
      </section>

      {/* ── 可拖拽 / 可自定义的聚合区块 ─────────────────────────────── */}
      <div className="hub-blocks">
        {visibleBlocks.map((id) => {
          const block = BLOCK_BY_ID[id]
          return (
            <section
              key={id}
              className={cx(
                'hub-block', 'hub-panel', 'hub-glass', `hub-span-${block.span}`,
                dragId === id && 'is-dragging',
              )}
              draggable
              onDragStart={(e) => onDragStart(e, id)}
              onDragOver={(e) => onDragOver(e, id)}
              onDragEnd={onDragEnd}
              onDrop={(e) => { e.preventDefault(); onDragEnd() }}
              aria-labelledby={`hub-block-${id}`}
            >
              <span className="hub-block__grip" title="拖动排序" aria-hidden="true"><ListChecks size={14} /></span>

              {id === 'trend' ? (
                <>
                  <PanelHead
                    title="14 天趋势"
                    sub="数据来自 dashboard/summary · trend"
                    icon={<Activity size={17} />}
                    actions={(
                      <Segmented
                        options={TREND_METRICS.map((m) => ({ value: m.value, label: m.label }))}
                        value={metric}
                        onChange={setMetric}
                        ariaLabel="趋势指标"
                      />
                    )}
                  />
                  <div className="hub-trend__headline">
                    <strong>{trendHasData ? trendHeadline : '—'}</strong>
                    <span>{trendUnit || metricDef.unit}</span>
                    <em>{metric === 'accuracy' ? '近 14 天平均' : `近 14 天累计 · ${metricDef.label}`}</em>
                  </div>
                  <div className="hub-chart">
                    {metric === 'accuracy'
                      ? <MiniLineChart data={trendValues.map((v) => ({ value: v }))} height={148} color="var(--v3-secondary)" />
                      : <MiniBarChart data={trendValues.map((v) => ({ value: v }))} height={148} color={metric === 'focus' ? 'var(--v3-primary)' : 'var(--v3-info)'} />}
                  </div>
                  <div className="hub-chart__axis" aria-hidden="true">
                    <span>{first(trendSeries)?.date?.slice(5) || ''}</span>
                    <span>{trendSeries.at(-1)?.date?.slice(5) || ''}</span>
                  </div>
                  {!trendHasData ? (
                    <p className="hub-hint-line">最近 14 天还没有{metricDef.label}记录，完成一次学习后这里会动起来。</p>
                  ) : null}
                </>
              ) : null}

              {id === 'focus' ? (
                <>
                  <PanelHead
                    title="专注计时"
                    sub="真实写入 study_sessions，同步刷新 KPI"
                    icon={<Timer size={17} />}
                  />
                  <div className="hub-focus">
                    <FocusTile
                      todayMinutes={today.focus_minutes || 0}
                      targetMinutes={data.goal.dailyTargets.focus}
                      subjects={data.focusSubjects}
                      onRecorded={onRecorded}
                    />
                  </div>
                  <p className="hub-hint-line">
                    只记录真实经过的分钟数；暂停发呆的时间不会被写成专注。
                  </p>
                </>
              ) : null}

              {id === 'heat' ? (
                <>
                  <PanelHead
                    title="学习热力"
                    sub={`近 12 周 · 活跃 ${heatActive} 天 · 累计 ${fmt(heatFocus)} 分钟`}
                    icon={<Flame size={17} />}
                    actions={<span className="hub-legend"><i />少<span /><i />多</span>}
                  />
                  <div className="hub-heat">
                    <HeatMap data={heatDays.map((d) => ({ date: d.date, value: d.focus }))} color="var(--v3-primary)" />
                  </div>
                  <div className="hub-heat__meta">
                    <span><b>{heatActive}</b> 天有学习痕迹</span>
                    <span><b>{fmt(heatFocus)}</b> 分钟专注</span>
                    <Link to="/timeline" className="hub-link">看学习轨迹 <ArrowRight size={14} /></Link>
                  </div>
                </>
              ) : null}

              {id === 'weak' ? (
                <>
                  <PanelHead
                    title="薄弱点"
                    sub={data.weakness.has ? `${data.weakness.points.length} 个高频错点` : '暂无薄弱点'}
                    icon={<Target size={17} />}
                    actions={<Link to="/error-review" className="hub-link">去复盘 <ArrowRight size={14} /></Link>}
                  />
                  {data.weakness.points.length ? (
                    <div className="hub-weak">
                      {data.weakness.points.slice(0, 5).map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          className="hub-weak__row"
                          onClick={() => navigate(p.knowledgePointId ? `/knowledge/${p.knowledgePointId}` : '/quiz?mode=weak')}
                        >
                          <span className="hub-weak__dot" aria-hidden="true" />
                          <span className="hub-weak__main">
                            <b>{p.name}</b>
                            <small>{[p.subject, p.chapter].filter(Boolean).join(' · ') || '未挂接章节'}</small>
                          </span>
                          <span className="hub-weak__stat">
                            <span className="hub-weak__bar" aria-hidden="true">
                              <i style={{ width: `${Math.max(3, Math.min(100, p.mastery ?? 0))}%` }} />
                            </span>
                            <small>{p.mastery == null ? '—' : `${Math.round(p.mastery)}%`}</small>
                          </span>
                        </button>
                      ))}
                      {data.weakness.reasons.length ? (
                        <div className="hub-weak__reasons">
                          {data.weakness.reasons.slice(0, 3).map((r) => (
                            <Chip key={r.reason} as="span">{r.reason} ×{r.count}</Chip>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <Empty icon={<CheckCircle2 size={24} />} title="暂无薄弱点" text="继续按航线推进，错题会在这里自动聚合并按掌握度排序。" />
                  )}
                </>
              ) : null}

              {id === 'tasks' ? (
                <>
                  <PanelHead
                    title="今日任务"
                    sub={data.tasks.total ? `已完成 ${data.tasks.done}/${data.tasks.total}` : '还没有安排今天的任务'}
                    icon={<ListChecks size={17} />}
                    actions={<Link to="/tasks" className="hub-link">全部任务 <ArrowRight size={14} /></Link>}
                  />
                  {data.tasks.items.length ? (
                    <ul className="hub-tasks">
                      {data.tasks.items.slice(0, 6).map((t) => (
                        <li key={t.id} className={cx('hub-task', t.status === 'done' && 'is-done')}>
                          <button
                            type="button"
                            className="hub-task__check"
                            aria-pressed={t.status === 'done'}
                            aria-label={`${t.status === 'done' ? '取消完成' : '完成'}：${t.title}`}
                            disabled={taskBusy === t.id}
                            onClick={() => toggleTask(t)}
                          >
                            {t.status === 'done' ? <Check size={14} /> : null}
                          </button>
                          <span className="hub-task__title">{t.title}</span>
                          {t.subject ? <span className="hub-task__subject">{t.subject}</span> : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <Empty
                      icon={<ListChecks size={24} />}
                      title="今天还没有任务"
                      text="从系统到期队列里挑一件开始，或去任务页安排 3 件最重要的事。"
                      action={<Button variant="tonal" onClick={() => navigate('/tasks')}>去安排任务</Button>}
                    />
                  )}
                  {data.tasks.modules.filter((m) => (m.due || 0) > 0).length ? (
                    <div className="hub-task-mods">
                      {data.tasks.modules.filter((m) => (m.due || 0) > 0).map((m) => (
                        <button
                          key={m.key}
                          type="button"
                          className="hub-task-mods__item"
                          onClick={() => navigate(MODULE_ROUTE[m.key] || '/tasks')}
                        >
                          <b>{m.label}</b>
                          <span>{m.due}{m.unit}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : null}

              {id === 'modules' ? (
                <>
                  <PanelHead
                    title="模块进度"
                    sub="同一份 module_progress，不按科目拆数据源"
                    icon={<Layers size={17} />}
                    actions={<Link to="/insights" className="hub-link">看统计 <ArrowRight size={14} /></Link>}
                  />
                  {data.modules.length ? (
                    <div className="hub-mods">
                      {data.modules.slice(0, 8).map((m) => {
                        const pct = m.percent == null ? 0 : m.percent
                        return (
                          <button
                            key={m.key}
                            type="button"
                            className={cx('hub-mod', m.status === 'not_tracked' && 'is-muted')}
                            onClick={() => navigate(MODULE_ROUTE[m.key] || '/insights')}
                            title={m.note || m.label}
                          >
                            <Ring value={pct} size={52} stroke={6} gradient={m.percent != null}>
                              <span className="hub-mod__pct">{m.percent == null ? '—' : `${Math.round(pct)}%`}</span>
                            </Ring>
                            <span className="hub-mod__label">{m.label}</span>
                            <span className="hub-mod__value">
                              {m.status === 'not_tracked'
                                ? '未接入'
                                : m.target
                                  ? `${m.done ?? 0}/${m.target} ${m.unit}`
                                  : `${m.done ?? 0} ${m.unit}`}
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  ) : (
                    <Empty title="暂无模块数据" text="完成一次专注、背词或刷题后，这里会显示各模块进度。" />
                  )}
                </>
              ) : null}

              {id === 'caliber' ? (
                <>
                  <PanelHead
                    title="数据口径与接口体检"
                    sub={`本页所有数字只来自 ${sourceTotal} 个聚合端点 · 派生指标由 api/hub.js 统一计算`}
                    icon={<Gauge size={17} />}
                    actions={(
                      <Button variant="tonal" icon={<RefreshCw size={15} className={refreshing ? 'hub-spin' : ''} />} onClick={refresh} disabled={refreshing}>
                        刷新
                      </Button>
                    )}
                  />
                  <div className="hub-caliber">
                    <div className="hub-caliber__table">
                      {data.caliber.map((row) => (
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
                    <div className="hub-sources">
                      {data.sources.map((s) => (
                        <div key={s.key} className={cx('hub-source', s.ok ? 'is-ok' : 'is-fail')}>
                          <span className="hub-source__dot" aria-hidden="true" />
                          <span className="hub-source__name">{s.label}</span>
                          <code>{s.path}</code>
                          <span className="hub-source__ms">{s.ok ? `${s.ms} ms` : '失败'}</span>
                          {!s.ok && s.error ? <span className="hub-source__err" title={s.error}>{s.error}</span> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                  <p className="hub-hint-line">
                    三个「到期」不是同一个队列：今日累计看未来负荷（截至 24:00），现在可做看复习调度，
                    艾宾浩斯来自复盘计划。分开标注是为了避免把 200 条计划复习误当成 200 道错题。
                  </p>
                </>
              ) : null}
            </section>
          )
        })}
      </div>

      <footer className="hub-foot">
        <span><Info size={14} /> 聚合入口：<code>fetchHubOverview()</code> · 后端提供 <code>/api/hub/overview</code> 后只需替换数据层</span>
        <span>{agoLabel(syncedAt)}</span>
      </footer>

      {/* 自定义布局：拖拽的键盘/移动端等价路径 */}
      <Dialog
        open={customOpen}
        title="聚合布局"
        sub="调整卡片顺序与显隐。偏好按账号保存在本机，不影响其他设备。"
        onClose={() => setCustomOpen(false)}
        footer={(
          <>
            <Button variant="tonal" icon={<RotateCcw size={15} />} onClick={resetLayout}>恢复默认</Button>
            <Button variant="gradient" onClick={() => setCustomOpen(false)}>完成</Button>
          </>
        )}
      >
        <div className="hub-custom">
          {layout.order.map((id, i) => {
            const b = BLOCK_BY_ID[id]
            if (!b) return null
            const hidden = layout.hidden.includes(id)
            return (
              <div key={id} className={cx('hub-custom__row', hidden && 'is-hidden')}>
                <span className="hub-custom__name">{b.label}</span>
                <div className="hub-custom__ops">
                  <IconButton
                    label={`上移${b.label}`}
                    variant="ghost"
                    icon={<ChevronUp size={16} />}
                    disabled={i === 0}
                    onClick={() => moveBlock(id, -1)}
                  />
                  <IconButton
                    label={`下移${b.label}`}
                    variant="ghost"
                    icon={<ChevronDown size={16} />}
                    disabled={i === layout.order.length - 1}
                    onClick={() => moveBlock(id, 1)}
                  />
                  <Switch
                    checked={!hidden}
                    onChange={() => toggleBlock(id)}
                    label={`显示${b.label}`}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </Dialog>
    </div>
  )
}
