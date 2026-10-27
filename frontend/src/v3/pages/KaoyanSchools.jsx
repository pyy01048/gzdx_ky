import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import { request } from '../../api/client'
import EChart from '../../components/EChart'
import { useAuth } from '../../auth/AuthContext'
import useStore from '../../store/useStore'
import { resolveExamDate, examDateMD, examDaysLeft } from '../../utils/exam'
import { examSubjectText } from '../../utils/kaoyanFields'
import { ukey, readMigrated } from '../../utils/userKeys'
import { chartTheme } from '../charts'
import {
  Alert, AnimatedNumber, Badge, Button, Card, CardHead, Chip, Dialog, Empty, Field,
  IconButton, Input, LoadingState, PageHeader, Segmented, Select, Skeleton, Spinner,
  Tile, toast, toastErr, toastWarn, cx,
} from '../ui'
import {
  AlertCircle, ArrowRight, BarChart3, Bookmark, CalendarClock, Check, ChevronDown,
  ChevronUp, Database, Flame, InfoCircle, ListChecks, Plus, RefreshCw, Search,
  SlidersHorizontal, Sparkles, Target, X,
} from '../icons'
import '../styles/kaoyan-core-v3.css'

/* ==========================================================================
   院校库 · Aurora v3
   数据契约与旧版完全一致：/kaoyan/schools（服务端排序 + 聚合字段）、
   /analysis/hot、/analysis/dashboard、/quality/major-coverage（仅登录用户）
   ========================================================================== */

const COV_LABEL = {
  covered: (c) => `语料 ${c.documents} 篇`,
  thin: (c) => `语料仅 ${c.documents} 篇`,
  unindexed: (c) => `${c.documents} 篇已归档未入库`,
  uncovered: () => '语料未覆盖',
}

function covTitle(c) {
  if (!c || c.state === 'public_only') return ''
  const conf = c.avg_confidence == null ? '—' : c.avg_confidence
  return `专业课「${c.subject || '—'}」按名称精确匹配知识库文档学科：`
    + `${c.documents} 篇 / ${c.chunks} 个可检索块 / 平均打标置信 ${conf}`
}

const PAGE_SIZE = 12
const FAV_KEY = 'ky_fav_school_ids'
const CMP_KEY = 'ky_compare_school_ids'
const EXAM_KEY = 'ky_exam_list'
const MAX_CMP = 5

const SORTS = [
  { key: 'heat', label: '热度' },
  { key: 'admit', label: '拟录取' },
  { key: 'ratio', label: '复录比' },
  { key: 'avg', label: '录取均分' },
  { key: 'name', label: '名称' },
]

const LEVEL_UNCLASSIFIED = '未分类'
const LEVELS = ['985', '211', '双一流', '双非', LEVEL_UNCLASSIFIED]
const REGIONS = ['A区', 'B区']
const SCHOOL_TYPES = ['公办', '科研院所', '军队院校']
const LEGACY_SEEDED_IDS = new Set(['kaoyan27', 'cet'])

const EMPTY_FILTERS = () => ({
  region: '', level: '', type: '', province: '', only0854: false, keyword: '',
  numAdmitMin: '', numAdmitMax: '', numRatioMin: '', numRatioMax: '',
  numRetestMin: '', numEnrollMin: '',
})

function normProvince(p) {
  if (!p) return '未知'
  return String(p)
    .replace(/(壮族|回族|维吾尔)?自治区$/, '')
    .replace(/(省|市)$/, '')
    .trim()
}

function normLevel(l) {
  const v = String(l == null ? '' : l).trim()
  return v || LEVEL_UNCLASSIFIED
}

function levelTone(level) {
  if (level === '985') return 'danger'
  if (level === '211') return 'primary'
  if (level === '双一流') return 'success'
  return undefined
}

function ratioClass(r) {
  if (r == null || Number.isNaN(Number(r))) return ''
  if (Number(r) < 1.2) return 'is-ok'
  if (Number(r) <= 1.8) return 'is-warn'
  return 'is-hot'
}

function fmtNum(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return Math.round(Number(v) * 10) / 10
}

function starText(star) {
  if (star == null || Number.isNaN(Number(star))) return '—'
  const full = Math.floor(Number(star))
  const half = Number(star) - full >= 0.5 ? 1 : 0
  return '★'.repeat(full) + '☆'.repeat(half)
}

function collegeInfo(s) {
  const parts = []
  if (s.college_count) parts.push(`${s.college_count}学院`)
  if (s.major_count) parts.push(`${s.major_count}方向`)
  return parts.length ? parts.join('/') : '—'
}

function countdownParts(dateStr, nowMs) {
  const target = new Date(dateStr).getTime()
  const diff = Math.max(0, target - nowMs)
  return {
    days: Math.floor(diff / 86400000),
    h: Math.floor((diff % 86400000) / 3600000),
    m: Math.floor((diff % 3600000) / 60000),
    s: Math.floor((diff % 60000) / 1000),
  }
}

const pad2 = (n) => String(n).padStart(2, '0')

async function fetchAllSchools(extra = {}) {
  let page = 1
  const out = []
  let total = Infinity
  while (out.length < total) {
    const data = await kaoyanApi.schools({ page_size: 100, page, ...extra })
    if (!data || !data.items) break
    out.push(...data.items)
    total = data.total || 0
    if (data.items.length < 100) break
    page += 1
    if (page > 20) break
  }
  return out
}

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

const chartAxis = (t) => ({
  axisLine: { lineStyle: { color: t.axisLine.lineStyle.color } },
  axisLabel: { color: t.textStyle.color, fontSize: 10 },
  splitLine: { lineStyle: { color: t.splitLine.lineStyle.color } },
})

function horizontalBar(t, names, values, color, width = 12) {
  return {
    grid: { left: 8, right: 22, top: 8, bottom: 8, containLabel: true },
    tooltip: { ...t.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', ...chartAxis(t) },
    yAxis: { type: 'category', data: names, ...chartAxis(t), splitLine: { show: false } },
    series: [{
      type: 'bar', data: values, barMaxWidth: width,
      itemStyle: { color, borderRadius: [0, 6, 6, 0] },
    }],
  }
}

function verticalBar(t, names, values, color, width = 20) {
  return {
    grid: { left: 8, right: 8, top: 16, bottom: 4, containLabel: true },
    tooltip: { ...t.tooltip, trigger: 'axis' },
    xAxis: { type: 'category', data: names, ...chartAxis(t), splitLine: { show: false } },
    yAxis: { type: 'value', ...chartAxis(t) },
    series: [{
      type: 'bar', data: values, barMaxWidth: width,
      itemStyle: { color, borderRadius: [6, 6, 0, 0] },
    }],
  }
}

function donut(t, data, palette) {
  return {
    tooltip: { ...t.tooltip, trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: t.textStyle.color, fontSize: 10 }, itemWidth: 10, itemHeight: 8 },
    series: [{
      type: 'pie', radius: ['44%', '68%'], center: ['50%', '44%'], label: { show: false },
      itemStyle: { borderColor: 'transparent', borderWidth: 2 },
      data: data.map((d, i) => ({ ...d, itemStyle: { color: palette[i % palette.length] } })),
    }],
  }
}

function pageWindow(cur, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const start = Math.min(Math.max(1, cur - 3), total - 6)
  return Array.from({ length: 7 }, (_, i) => start + i)
}

/* -------------------------------------------------------------------------- */
/* Countdown (own clock so the page itself does not re-render every second)    */
/* -------------------------------------------------------------------------- */
function CountdownStrip() {
  const cd = useStore((s) => s.countdown)
  const settingExamDate = useStore((s) => s.settings.examDate)
  const mainExamDate = resolveExamDate(settingExamDate || cd?.exam_date, null)
  const [now, setNow] = useState(Date.now())
  const [exams, setExams] = useState(() => {
    try {
      const saved = readMigrated(EXAM_KEY, null)
      if (Array.isArray(saved)) {
        return saved.filter((e) => e && e.date && !LEGACY_SEEDED_IDS.has(e.id))
      }
    } catch { /* ignore */ }
    return []
  })
  const [showAdd, setShowAdd] = useState(false)
  const [newExam, setNewExam] = useState({ name: '', date: '' })

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    try { localStorage.setItem(ukey(EXAM_KEY), JSON.stringify(exams)) } catch { /* ignore */ }
  }, [exams])

  const list = useMemo(() => {
    if (!mainExamDate) return exams
    return [{
      id: '__main',
      name: `考研初试${cd?.is_default ? `（${examDateMD(mainExamDate)} 预估，可在设置修改）` : ''}`,
      date: `${mainExamDate}T08:30:00+08:00`,
      main: true,
    }, ...exams]
  }, [exams, mainExamDate, cd])

  const addExam = () => {
    if (!newExam.name.trim() || !newExam.date) { toastWarn('请填写考试名称与日期'); return }
    setExams((prev) => [...prev, { id: `u_${Date.now()}`, name: newExam.name.trim(), date: newExam.date, main: false }])
    setNewExam({ name: '', date: '' })
    setShowAdd(false)
    toast('已添加考试倒计时')
  }

  const dateValue = newExam.date ? newExam.date.slice(0, 10) : ''

  return (
    <Card variant="tonal" className="kyv3-countdown">
      <div className="kyv3-countdown-head">
        <h2><CalendarClock size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: '-3px' }} />考试倒计时</h2>
        <Button variant="text" size="sm" icon={<Plus size={15} />} onClick={() => setShowAdd(true)}>添加考试</Button>
      </div>
      <div className="kyv3-countdown-rail">
        {list.length === 0 ? (
          <div className="kyv3-cd-empty">
            倒计时未配置。去「设置」填写初试日期，或点右侧「添加考试」自行添加。
          </div>
        ) : null}
        {list.map((e) => {
          const p = countdownParts(e.date, now)
          const days = examDaysLeft(String(e.date || '').slice(0, 10)) ?? p.days
          return (
            <div key={e.id} className={cx('kyv3-cd', e.main && 'is-main')}>
              <div className="kyv3-cd__name" title={e.name}>{e.name}</div>
              <div className="kyv3-cd__days">
                <AnimatedNumber value={days} format={(n) => Math.round(n)} />
                <span>天</span>
              </div>
              {e.main ? <div className="kyv3-cd__clock">{pad2(p.h)}:{pad2(p.m)}:{pad2(p.s)}</div> : null}
              {!e.main ? (
                <button type="button" className="kyv3-cd__remove" aria-label={`删除 ${e.name}`}
                  onClick={() => setExams((prev) => prev.filter((x) => x.id !== e.id))}>
                  <X size={13} />
                </button>
              ) : null}
            </div>
          )
        })}
        {list.length > 0 ? (
          <button type="button" className="kyv3-cd-add" onClick={() => setShowAdd(true)}>
            <Plus size={16} style={{ margin: '0 auto 4px' }} />
            添加考试
          </button>
        ) : null}
      </div>

      <Dialog
        open={showAdd}
        title="添加考试倒计时"
        sub="日期保存在本机，仅用于倒计时展示"
        onClose={() => setShowAdd(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowAdd(false)}>取消</Button>
            <Button onClick={addExam} disabled={!newExam.name.trim() || !newExam.date}>添加</Button>
          </>
        )}
      >
        <div className="v3-stack" style={{ gap: 14 }}>
          <Field label="考试名称" htmlFor="kyv3-exam-name">
            <Input id="kyv3-exam-name" placeholder="如：考研初试 / 六级" value={newExam.name}
              onChange={(e) => setNewExam((p) => ({ ...p, name: e.target.value }))} />
          </Field>
          <Field label="考试日期" htmlFor="kyv3-exam-date">
            <Input id="kyv3-exam-date" type="date" value={dateValue}
              onChange={(e) => setNewExam((p) => ({
                ...p,
                date: e.target.value ? `${e.target.value}T00:00:00+08:00` : '',
              }))} />
          </Field>
        </div>
      </Dialog>
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* School card                                                                */
/* -------------------------------------------------------------------------- */
function SchoolCard({
  s, isFav, isCmp, isOpen, majors, majorsLoading,
  onFav, onCmp, onExpand, highlight, covMap,
}) {
  const yzLink = `https://yz.chsi.com.cn/sch/search.do?q=${encodeURIComponent(s.name || '')}`
  const cov = covMap && covMap[s.id]
  return (
    <article className={cx('kyv3-school', highlight && 'is-hl')}>
      <div className="kyv3-school-top">
        <div className="kyv3-logo">
          {s.logo_url ? <img src={s.logo_url} alt="" loading="lazy" /> : (s.name || '?').slice(0, 1)}
        </div>
        <div className="kyv3-school-title-wrap">
          <Link to={`/kaoyan/schools/${s.id}`} className="kyv3-school-name" title={s.name}>{s.name}</Link>
          <div className="kyv3-school-badges">
            <Badge tone={levelTone(normLevel(s.level))}>{normLevel(s.level)}</Badge>
            {s.region ? <Badge>{s.region}</Badge> : null}
            {s.type ? <Badge>{s.type}</Badge> : null}
            {s.has0854 ? <Badge tone="primary">0854</Badge> : null}
            {isFav ? <Badge tone="warning">目标院校</Badge> : null}
          </div>
        </div>
        <div className="kyv3-school-actions">
          <IconButton
            label={isFav ? `取消收藏 ${s.name}` : `收藏 ${s.name}`}
            icon={<Bookmark size={16} />}
            className={cx('kyv3-fav', isFav && 'is-active')}
            onClick={onFav}
          />
        </div>
      </div>

      <div className="kyv3-school-meta">
        <span>{normProvince(s.province)}{s.city ? ` · ${s.city}` : ''}</span>
        <span>{collegeInfo(s)}</span>
        {s.scoreline_count > 0 ? <span>分数线 {s.scoreline_count} 条</span> : null}
        {s.star != null ? <span className="kyv3-star" title={`星级 ${s.star}`}>{starText(s.star)}</span> : null}
        {s.official_url ? <a href={s.official_url} target="_blank" rel="noopener noreferrer">官网 ↗</a> : null}
        <a href={yzLink} target="_blank" rel="noopener noreferrer">研招网 ↗</a>
      </div>

      <p className="kyv3-school-intro">{s.intro ? s.intro.replace(/\s+/g, ' ').slice(0, 96) : '暂无院校简介'}</p>

      <div className="kyv3-school-tags">
        {s.coverage_score != null ? (
          <Badge tone="outline" title="资料完整度：专业目录/招生数据/分数线/简介/官网">资料 {s.coverage_score}%</Badge>
        ) : null}
        {cov && cov.majors ? (
          <span
            className={cx('kyv3-coverage', cov.covered > 0 && 'is-covered')}
            title={`初试专业课名精确匹配知识库文档学科：${cov.majors} 个专业方向中 ${cov.covered} 个有语料`}
          >
            <Database size={10} /> 语料覆盖 {cov.covered}/{cov.majors}
          </span>
        ) : null}
      </div>

      <div className="kyv3-school-stats">
        <div className="kyv3-school-stat"><b>{fmtNum(s.retest_count)}</b><span>进复试</span></div>
        <div className="kyv3-school-stat"><b>{fmtNum(s.admit_count)}</b><span>拟录取</span></div>
        <div className="kyv3-school-stat"><b className={ratioClass(s.retest_ratio)}>{fmtNum(s.retest_ratio)}</b><span>复录比</span></div>
        <div className="kyv3-school-stat"><b>{fmtNum(s.admit_avg_score)}</b><span>录取均分</span></div>
        <div className="kyv3-school-stat"><b>{s.heat > 0 ? Math.round(s.heat) : '—'}</b><span>热度</span></div>
      </div>

      <div className="kyv3-school-foot">
        <Link to={`/kaoyan/schools/${s.id}`} className="v3-btn v3-btn--filled v3-btn--sm">查看详情</Link>
        <Button
          variant={isCmp ? 'tonal' : 'text'}
          size="sm"
          icon={isCmp ? <Check size={14} /> : <ListChecks size={14} />}
          onClick={onCmp}
          aria-pressed={isCmp}
        >
          {isCmp ? '已选对比' : '加入对比'}
        </Button>
        <Button
          variant="text"
          size="sm"
          className="kyv3-expand"
          icon={isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          onClick={onExpand}
          aria-expanded={isOpen}
        >
          专业方向
        </Button>
      </div>

      {isOpen ? (
        <div className="kyv3-major-panel">
          <div className="kyv3-major-panel-head">
            专业方向 / 招生科目
            <span>徽标＝知识库语料覆盖，未覆盖不代表答不了</span>
          </div>
          {majorsLoading ? (
            <div className="kyv3-major-empty"><Spinner size={14} /> 加载专业方向中…</div>
          ) : majors && majors.length ? (
            <ul className="kyv3-major-list">
              {majors.map((m) => (
                <li key={m.id} className="kyv3-major-item">
                  <code>{m.code || '—'}</code>
                  <b>{m.name}</b>
                  {m.exam_subjects ? <small>{examSubjectText(m.exam_subjects)}</small> : null}
                  {m.kb_coverage && m.kb_coverage.state !== 'public_only' && COV_LABEL[m.kb_coverage.state] ? (
                    <span className={cx('kyv3-coverage', (m.kb_coverage.state === 'covered' || m.kb_coverage.state === 'thin') && 'is-covered')} title={covTitle(m.kb_coverage)}>
                      {COV_LABEL[m.kb_coverage.state](m.kb_coverage)}
                      {m.kb_coverage.avg_confidence != null && m.kb_coverage.avg_confidence < 0.4 ? ' · 置信低' : ''}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <div className="kyv3-major-empty">暂无专业方向数据</div>
          )}
        </div>
      ) : null}
    </article>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */
export default function KaoyanSchools() {
  const navigate = useNavigate()
  const { user, status: authStatus } = useAuth()
  const mode = useThemeMode()
  const t = useMemo(() => chartTheme(mode === 'dark'), [mode])

  const [rows, setRows] = useState([])
  const [hotList, setHotList] = useState([])
  const [analysis, setAnalysis] = useState(null)
  const [analysisError, setAnalysisError] = useState('')
  const [showAnalysis, setShowAnalysis] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sort, setSort] = useState('heat')
  const [covMap, setCovMap] = useState(null)

  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [showMore, setShowMore] = useState(false)
  const [onlyFav, setOnlyFav] = useState(false)

  const [favs, setFavs] = useState(() => {
    try { return new Set(readMigrated(FAV_KEY, [])) } catch { return new Set() }
  })
  const [cmpSet, setCmpSet] = useState(() => {
    try { return new Set(readMigrated(CMP_KEY, [])) } catch { return new Set() }
  })
  const [hlId, setHlId] = useState(null)

  const [expandedId, setExpandedId] = useState(null)
  const [majorsMap, setMajorsMap] = useState({})
  const [majorsLoading, setMajorsLoading] = useState(null)

  const load = useCallback(async (sortKey) => {
    setLoading(true)
    setError('')
    setAnalysisError('')
    try {
      const [schools, schools0854, dashboard, hot, cov] = await Promise.all([
        fetchAllSchools({ sort: sortKey }),
        fetchAllSchools({ subject_code: '0854' }).catch(() => []),
        kaoyanApi.dashboardAnalysis().catch(() => null),
        kaoyanApi.hot({ limit: 10 }).catch(() => ({ items: [] })),
        user ? request('/quality/major-coverage').catch(() => null) : Promise.resolve(null),
      ])
      const ids0854 = new Set((schools0854 || []).map((s) => s.id))
      setRows(schools.map((s) => ({ ...s, has0854: ids0854.has(s.id) })))
      setAnalysis(dashboard)
      if (!dashboard) setAnalysisError('数据分析聚合接口暂不可用，图表区已隐藏')
      setHotList(hot?.items || [])
      setCovMap((cov && cov.by_school) || {})
    } catch (e) {
      setError(e?.message || '院校数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    if (authStatus === 'loading') return
    load(sort)
  }, [load, sort, authStatus])

  useEffect(() => { try { localStorage.setItem(ukey(FAV_KEY), JSON.stringify([...favs])) } catch { /* ignore */ } }, [favs])
  useEffect(() => { try { localStorage.setItem(ukey(CMP_KEY), JSON.stringify([...cmpSet])) } catch { /* ignore */ } }, [cmpSet])

  const provinceOptions = useMemo(() => {
    const set = new Set()
    rows.forEach((r) => set.add(normProvince(r.province)))
    return [...set].sort((a, b) => a.localeCompare(b, 'zh'))
  }, [rows])

  const filtered = useMemo(() => rows.filter((r) => {
    if (filters.region && (r.region || '') !== filters.region) return false
    if (filters.level && normLevel(r.level) !== filters.level) return false
    if (filters.type && (r.type || '') !== filters.type) return false
    if (filters.province && normProvince(r.province) !== filters.province) return false
    if (filters.only0854 && !r.has0854) return false
    if (onlyFav && !favs.has(r.id)) return false
    if (filters.keyword && !(r.name || '').toLowerCase().includes(filters.keyword.trim().toLowerCase())) return false
    const avg = r.admit_avg_score
    if (filters.numAdmitMin !== '' && (avg == null || avg < Number(filters.numAdmitMin))) return false
    if (filters.numAdmitMax !== '' && (avg == null || avg > Number(filters.numAdmitMax))) return false
    const retest = r.retest_count ?? r.retest
    if (filters.numRetestMin !== '' && (retest == null || retest < Number(filters.numRetestMin))) return false
    const enroll = r.admit_count ?? r.admit
    if (filters.numEnrollMin !== '' && (enroll == null || enroll < Number(filters.numEnrollMin))) return false
    const ratio = r.retest_ratio
    if (filters.numRatioMin !== '' && (ratio == null || ratio < Number(filters.numRatioMin))) return false
    if (filters.numRatioMax !== '' && (ratio == null || ratio > Number(filters.numRatioMax))) return false
    return true
  }), [rows, filters, onlyFav, favs])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const curPage = Math.min(page, totalPages)
  const current = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE)

  const applyFilters = () => { setFilters({ ...draft }); setPage(1) }
  const quickApply = (patch) => {
    const next = { ...draft, ...patch }
    setDraft(next)
    setFilters(next)
    setPage(1)
  }
  const resetFilters = () => {
    setDraft(EMPTY_FILTERS())
    setFilters(EMPTY_FILTERS())
    setOnlyFav(false)
    setPage(1)
  }
  const changeSort = (key) => {
    if (key === sort) return
    setSort(key)
    setPage(1)
  }

  const toggleFav = (id) => setFavs((prev) => {
    const n = new Set(prev)
    if (n.has(id)) n.delete(id); else n.add(id)
    return n
  })

  const toggleCmp = (id) => setCmpSet((prev) => {
    const n = new Set(prev)
    if (n.has(id)) n.delete(id)
    else {
      if (n.size >= MAX_CMP) { toast(`最多对比 ${MAX_CMP} 所院校`); return prev }
      n.add(id)
    }
    return n
  })

  const toggleExpand = async (id) => {
    if (expandedId === id) { setExpandedId(null); return }
    setExpandedId(id)
    if (majorsMap[id]) return
    setMajorsLoading(id)
    try {
      const list = await kaoyanApi.schoolMajors(id)
      setMajorsMap((prev) => ({ ...prev, [id]: list || [] }))
    } catch {
      setMajorsMap((prev) => ({ ...prev, [id]: [] }))
      toastErr('专业方向加载失败')
    } finally {
      setMajorsLoading(null)
    }
  }

  const randomPick = () => {
    if (!filtered.length) return
    const s = filtered[Math.floor(Math.random() * filtered.length)]
    const idx = filtered.indexOf(s)
    setPage(Math.floor(idx / PAGE_SIZE) + 1)
    setHlId(s.id)
    toast(`已为你抽中：${s.name}`)
    window.setTimeout(() => setHlId(null), 3500)
  }

  const goCompare = () => {
    try { localStorage.setItem(ukey(CMP_KEY), JSON.stringify([...cmpSet])) } catch { /* ignore */ }
    navigate('/kaoyan/compare')
  }

  const withAdmitCount = useMemo(() => rows.filter((r) => r.admit_count != null).length, [rows])

  const schoolStats = useMemo(() => {
    let l985 = 0, l211 = 0, withScores = 0
    rows.forEach((r) => {
      const lv = normLevel(r.level)
      if (lv === '985') l985++
      if (lv === '211') l211++
      if ((r.scoreline_count || 0) > 0) withScores++
    })
    return [
      { k: '院校总数', v: rows.length, unit: '所', icon: Database },
      { k: '覆盖省份', v: provinceOptions.length, unit: '个', icon: Target },
      { k: '985 院校', v: l985, unit: '所', icon: Sparkles },
      { k: '211 院校', v: l211, unit: '所', icon: Sparkles },
      { k: '有分数线', v: withScores, unit: '所', icon: BarChart3 },
      { k: '有招生数据', v: withAdmitCount, unit: '所', icon: Flame },
    ]
  }, [rows, provinceOptions.length, withAdmitCount])

  const activeFilterCount = useMemo(() => {
    let n = Object.entries(filters).filter(([, v]) => v !== '' && v !== false).length
    if (onlyFav) n++
    return n
  }, [filters, onlyFav])

  const hotTop = useMemo(() => hotList.filter((s) => (s.heat || 0) > 0).slice(0, 10), [hotList])

  const dash = useMemo(() => analysis || {}, [analysis])

  /* ----- Charts built from /schools aggregate fields ----- */
  const provinceBar = useMemo(() => {
    const agg = {}
    rows.forEach((r) => {
      const p = normProvince(r.province)
      agg[p] = (agg[p] || 0) + (r.admit_count || 0)
    })
    const data = Object.entries(agg)
      .map(([name, value]) => ({ name, value: Math.round(value) }))
      .sort((a, b) => a.value - b.value)
      .slice(-10)
    return horizontalBar(t, data.map((d) => d.name), data.map((d) => d.value), '#4285F4')
  }, [rows, t])

  const scoreBar = useMemo(() => {
    const bands = ['<320', '320-340', '340-360', '360-380', '≥380']
    const counts = bands.map(() => 0)
    rows.forEach((r) => {
      const v = r.admit_avg_score
      if (v == null) return
      const i = v < 320 ? 0 : v < 340 ? 1 : v < 360 ? 2 : v < 380 ? 3 : 4
      counts[i]++
    })
    return verticalBar(t, bands, counts, '#4285F4', 26)
  }, [rows, t])

  const ratioBar = useMemo(() => {
    const bands = ['<1.2', '1.2-1.5', '1.5-1.8', '≥1.8']
    const counts = bands.map(() => 0)
    rows.forEach((r) => {
      const v = r.retest_ratio
      if (v == null) return
      const i = v < 1.2 ? 0 : v < 1.5 ? 1 : v < 1.8 ? 2 : 3
      counts[i]++
    })
    const colors = ['#34A853', '#F9AB00', '#D96570', '#D96570']
    return {
      ...verticalBar(t, bands, counts, colors[0], 26),
      series: [{
        type: 'bar',
        data: counts.map((v, i) => ({ value: v, itemStyle: { color: colors[i], borderRadius: [6, 6, 0, 0] } })),
        barMaxWidth: 26,
      }],
    }
  }, [rows, t])

  const levelPie = useMemo(() => {
    const agg = { '985': 0, '211': 0, '双一流': 0, '双非': 0, [LEVEL_UNCLASSIFIED]: 0 }
    rows.forEach((r) => { agg[normLevel(r.level)]++ })
    const palette = ['#D96570', '#4285F4', '#9B72CB', '#F9AB00', '#8A93A3']
    return donut(t, Object.entries(agg).filter(([, v]) => v > 0).map(([name, value]) => ({ name, value })), palette)
  }, [rows, t])

  const major2Bar = useMemo(() => {
    const data = dash.major2_top || []
    return horizontalBar(t, data.map((d) => d.name), data.map((d) => d.count), '#9B72CB')
  }, [dash, t])

  const mathBar = useMemo(() => {
    const data = dash.subject_math || []
    return horizontalBar(t, data.map((d) => d.name), data.map((d) => d.count), '#4285F4')
  }, [dash, t])

  const englishBar = useMemo(() => {
    const data = dash.subject_english || []
    return horizontalBar(t, data.map((d) => d.name), data.map((d) => d.count), '#34A853')
  }, [dash, t])

  const majorScoreBar = useMemo(() => {
    const list = (dash.major_comparison || []).slice(0, 10).reverse()
    return {
      grid: { left: 8, right: 20, top: 28, bottom: 8, containLabel: true },
      tooltip: { ...t.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { top: 0, textStyle: { color: t.textStyle.color, fontSize: 10 }, itemWidth: 10, itemHeight: 8 },
      xAxis: { type: 'value', ...chartAxis(t) },
      yAxis: { type: 'category', data: list.map((d) => d.major), ...chartAxis(t), splitLine: { show: false } },
      series: [
        { name: '复试均分', type: 'bar', data: list.map((d) => d.major_avg), itemStyle: { color: '#4285F4', borderRadius: [0, 5, 5, 0] }, barMaxWidth: 11 },
        { name: '录取均分', type: 'bar', data: list.map((d) => d.admit_avg), itemStyle: { color: '#F9AB00', borderRadius: [0, 5, 5, 0] }, barMaxWidth: 11 },
      ],
    }
  }, [dash, t])

  const majorPie = useMemo(() => {
    const list = (dash.major_comparison || []).slice(0, 10)
    const total = list.reduce((sum, d) => sum + (d.enroll_count || 0), 0)
    return {
      tooltip: {
        ...t.tooltip,
        trigger: 'item',
        formatter: (p) => `${p.name}<br/>${p.value} 人（${total ? ((p.value / total) * 100).toFixed(1) : 0}%）`,
      },
      legend: { bottom: 0, textStyle: { color: t.textStyle.color, fontSize: 10 }, itemWidth: 10, itemHeight: 8, type: 'scroll' },
      series: [{
        type: 'pie', radius: ['40%', '64%'], center: ['50%', '43%'], label: { show: false },
        data: list.map((d, i) => ({
          name: d.major,
          value: d.enroll_count || 0,
          itemStyle: { color: ['#4285F4', '#9B72CB', '#D96570', '#34A853', '#F9AB00', '#00ACC1'][i % 6] },
        })),
      }],
    }
  }, [dash, t])

  const collegeBar = useMemo(() => {
    const data = (dash.college_enroll || []).slice(0, 10).reverse()
    return horizontalBar(t, data.map((d) => d.college), data.map((d) => d.enroll_count), '#D96570')
  }, [dash, t])

  const scoreDistBar = useMemo(() => {
    const data = dash.major_score_dist || []
    return verticalBar(t, data.map((d) => d.band), data.map((d) => d.count), '#F9AB00', 26)
  }, [dash, t])

  const totalHist = useMemo(() => {
    const bands = ['<300', '300-320', '320-340', '340-360', '360-380', '≥380']
    if (Array.isArray(dash.total_score_dist) && dash.total_score_dist.length) {
      return {
        bands: dash.total_score_dist.map((d) => d.band),
        counts: dash.total_score_dist.map((d) => d.count),
        fromBackend: true,
      }
    }
    const counts = bands.map(() => 0)
    rows.forEach((r) => {
      const v = r.admit_avg_score
      if (v == null) return
      const i = v < 300 ? 0 : v < 320 ? 1 : v < 340 ? 2 : v < 360 ? 3 : v < 380 ? 4 : 5
      counts[i]++
    })
    return { bands, counts, fromBackend: false }
  }, [dash, rows])

  const majorHist = useMemo(() => {
    const bands = ['<90', '90-100', '100-110', '110-120', '120-130', '130-140', '≥140']
    if (Array.isArray(dash.major_score_dist) && dash.major_score_dist.length) {
      return {
        bands: dash.major_score_dist.map((d) => d.band),
        counts: dash.major_score_dist.map((d) => d.count),
        fromBackend: true,
      }
    }
    const counts = bands.map(() => 0)
    rows.forEach((r) => {
      const v = r.major_avg_score
      if (v == null) return
      const i = v < 90 ? 0 : v < 100 ? 1 : v < 110 ? 2 : v < 120 ? 3 : v < 130 ? 4 : v < 140 ? 5 : 6
      counts[i]++
    })
    return { bands, counts, fromBackend: false }
  }, [dash, rows])

  const mathHist = useMemo(() => {
    if (Array.isArray(dash.math_score_dist) && dash.math_score_dist.length) {
      return {
        bands: dash.math_score_dist.map((d) => d.band),
        counts: dash.math_score_dist.map((d) => d.count),
        fromBackend: true,
      }
    }
    return null
  }, [dash])

  const totalHistBar = useMemo(() => verticalBar(t, totalHist.bands, totalHist.counts, '#4285F4', 26), [totalHist, t])
  const majorHistBar = useMemo(() => verticalBar(t, majorHist.bands, majorHist.counts, '#F9AB00', 26), [majorHist, t])
  const mathHistBar = useMemo(
    () => (mathHist ? verticalBar(t, mathHist.bands, mathHist.counts, '#34A853', 26) : null),
    [mathHist, t],
  )

  const pageNumbers = pageWindow(curPage, totalPages)
  const initialLoading = loading && rows.length === 0

  /* ------------------------------ loading ------------------------------ */
  if (initialLoading) {
    return (
      <div className="kyv3-page">
        <PageHeader
          eyebrow="SCHOOL DATABASE · 全国院校库"
          title="院校库"
          sub="择校第一步 · 查院校、看分数、比招生"
          actions={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/compare">院校对比 <ArrowRight size={15} /></Link>}
        />
        <div className="v3-bento">
          {Array.from({ length: 6 }).map((_, i) => (
            <Tile key={i} span={2} className="kyv3-stat-tile"><Skeleton height={54} /></Tile>
          ))}
        </div>
        <Card><Skeleton height={180} /><div style={{ height: 12 }} /><Skeleton height={180} /></Card>
        <LoadingState text="院校数据加载中…" />
      </div>
    )
  }

  /* ------------------------------- error ------------------------------- */
  if (error && rows.length === 0) {
    return (
      <div className="kyv3-page">
        <PageHeader
          eyebrow="SCHOOL DATABASE · 全国院校库"
          title="院校库"
          sub="择校第一步 · 查院校、看分数、比招生"
          actions={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/compare">院校对比 <ArrowRight size={15} /></Link>}
        />
        <Card>
          <Empty
            icon={<AlertCircle size={26} />}
            title="院校数据加载失败"
            text={error}
            action={<Button variant="tonal" onClick={() => load(sort)}>重新加载</Button>}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="kyv3-page">
      <PageHeader
        eyebrow="SCHOOL DATABASE · 全国院校库"
        title="院校库"
        sub="择校第一步 · 查院校、看分数、比招生"
        actions={(
          <>
            <Link className="v3-btn v3-btn--tonal" to="/kaoyan/compare">
              院校对比 <ArrowRight size={15} />
            </Link>
            <Link className="v3-btn v3-btn--text" to="/kaoyan/recommend">智能推荐</Link>
            <IconButton label="刷新院校数据" icon={<RefreshCw size={17} />} onClick={() => load(sort)} disabled={loading} />
          </>
        )}
      />

      <div className="v3-bento">
        {schoolStats.map((s) => {
          const Icon = s.icon
          return (
            <Tile key={s.k} span={2} className="kyv3-stat-tile">
              <span className="v3-tile__label"><Icon size={14} /> {s.k}</span>
              <span className="v3-tile__value">
                <AnimatedNumber value={s.v} format={(n) => Math.round(n).toLocaleString('zh-CN')} />
                <em>{s.unit}</em>
              </span>
            </Tile>
          )
        })}
      </div>

      <Alert tone="info" icon={<InfoCircle size={18} />} className="kyv3-note">
        <p><b>数据说明：</b>本页招生 / 录取 / 复录比均为第三方聚合数据，未经院校官方逐条核验，仅供择校参考；正式信息以目标院校研究生院官网为准。</p>
      </Alert>

      {analysisError ? (
        <Alert tone="warning" icon={<AlertCircle size={18} />} className="kyv3-note">
          <p>{analysisError}</p>
        </Alert>
      ) : null}

      <CountdownStrip />

      {hotTop.length > 0 ? (
        <Card className="kyv3-hot">
          <CardHead
            icon={<Flame size={17} style={{ color: 'var(--v3-danger)' }} />}
            title="高频热度榜 TOP10"
            sub="按数据热度排序 · 仅供择校参考"
          />
          <ol className="kyv3-hot-grid">
            {hotTop.map((s, i) => (
              <li key={s.id ?? i} className="kyv3-hot-item">
                <span className={cx('kyv3-hot-rank', i === 0 && 'is-top1', i === 1 && 'is-top2', i === 2 && 'is-top3')}>
                  {s.rank ?? i + 1}
                </span>
                <div className="kyv3-hot-main">
                  <Link to={`/kaoyan/schools/${s.id || 0}`} className="kyv3-hot-name" title={s.name}>{s.name}</Link>
                  <div className="kyv3-hot-meta">
                    <Badge tone={levelTone(normLevel(s.level))}>{normLevel(s.level)}</Badge>
                    <span>热度 {s.heat != null ? Math.round(s.heat) : '—'}</span>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      ) : null}

      <Card className="kyv3-filter">
        <div className="kyv3-search-row">
          <Input
            icon={<Search size={16} />}
            type="search"
            placeholder="输入院校名称，如：清华大学"
            aria-label="搜索院校名称"
            value={draft.keyword}
            onChange={(e) => setDraft({ ...draft, keyword: e.target.value })}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); applyFilters() } }}
          />
          <Button onClick={applyFilters}>搜索</Button>
          <Button
            variant="text"
            icon={<SlidersHorizontal size={15} />}
            onClick={() => setShowMore((v) => !v)}
            aria-expanded={showMore}
          >
            {showMore ? '收起更多筛选' : '更多筛选'}
          </Button>
          <span className="kyv3-found">筛出 <b>{filtered.length}</b> 所</span>
        </div>

        <div className="kyv3-filter-grid">
          <div className="kyv3-filter-line">
            <span className="kyv3-filter-label">地区</span>
            <div className="kyv3-chips">
              <Chip active={draft.region === ''} onClick={() => quickApply({ region: '' })}>全部</Chip>
              {REGIONS.map((r) => <Chip key={r} active={draft.region === r} onClick={() => quickApply({ region: r })}>{r}</Chip>)}
            </div>
          </div>
          <div className="kyv3-filter-line">
            <span className="kyv3-filter-label">层级</span>
            <div className="kyv3-chips">
              <Chip active={draft.level === ''} onClick={() => quickApply({ level: '' })}>全部</Chip>
              {LEVELS.map((l) => <Chip key={l} active={draft.level === l} onClick={() => quickApply({ level: l })}>{l}</Chip>)}
            </div>
          </div>
          <div className="kyv3-filter-line">
            <span className="kyv3-filter-label">类型</span>
            <div className="kyv3-chips">
              <Chip active={draft.type === ''} onClick={() => quickApply({ type: '' })}>全部</Chip>
              {SCHOOL_TYPES.map((tp) => <Chip key={tp} active={draft.type === tp} onClick={() => quickApply({ type: tp })}>{tp}</Chip>)}
            </div>
          </div>
          <div className="kyv3-filter-line">
            <span className="kyv3-filter-label">省份</span>
            <Select
              className="kyv3-select-sm"
              aria-label="按省份筛选"
              value={draft.province}
              onChange={(e) => quickApply({ province: e.target.value })}
              options={[{ value: '', label: '全部省份' }, ...provinceOptions.map((p) => ({ value: p, label: p }))]}
            />
            <Chip active={draft.only0854} onClick={() => quickApply({ only0854: !draft.only0854 })}>0854 电子信息</Chip>
            <Chip active={onlyFav} onClick={() => { setOnlyFav((v) => !v); setPage(1) }}>
              我的关注{favs.size ? ` (${favs.size})` : ''}
            </Chip>
          </div>
        </div>

        {showMore ? (
          <div className="kyv3-filter-more">
            <label className="kyv3-num">
              <span>录取均分范围</span>
              <span className="kyv3-range">
                <Input type="number" min="0" max="500" placeholder="最低" aria-label="录取均分下限"
                  value={draft.numAdmitMin} onChange={(e) => setDraft({ ...draft, numAdmitMin: e.target.value })} />
                <span className="kyv3-range-sep">~</span>
                <Input type="number" min="0" max="500" placeholder="最高" aria-label="录取均分上限"
                  value={draft.numAdmitMax} onChange={(e) => setDraft({ ...draft, numAdmitMax: e.target.value })} />
              </span>
            </label>
            <label className="kyv3-num">
              <span>复录比范围</span>
              <span className="kyv3-range">
                <Input type="number" min="0" max="10" step="0.1" placeholder="最低" aria-label="复录比下限"
                  value={draft.numRatioMin} onChange={(e) => setDraft({ ...draft, numRatioMin: e.target.value })} />
                <span className="kyv3-range-sep">~</span>
                <Input type="number" min="0" max="10" step="0.1" placeholder="最高" aria-label="复录比上限"
                  value={draft.numRatioMax} onChange={(e) => setDraft({ ...draft, numRatioMax: e.target.value })} />
              </span>
            </label>
            <label className="kyv3-num">
              <span>进复试人数 ≥</span>
              <Input type="number" min="0" placeholder="不限" aria-label="进复试人数下限"
                value={draft.numRetestMin} onChange={(e) => setDraft({ ...draft, numRetestMin: e.target.value })} />
            </label>
            <label className="kyv3-num">
              <span>拟录取人数 ≥</span>
              <Input type="number" min="0" placeholder="不限" aria-label="拟录取人数下限"
                value={draft.numEnrollMin} onChange={(e) => setDraft({ ...draft, numEnrollMin: e.target.value })} />
            </label>
            <div className="v3-row" style={{ alignItems: 'flex-end' }}>
              <Button variant="tonal" size="sm" onClick={applyFilters}>应用数值筛选</Button>
            </div>
          </div>
        ) : null}

        <div className="kyv3-filter-foot">
          <span className="kyv3-active-count">已启用 <b>{activeFilterCount}</b> 项筛选</span>
          {activeFilterCount > 0 ? <Button variant="text" size="sm" onClick={resetFilters}>清空全部</Button> : null}
          {onlyFav ? <Chip active onClick={() => { setOnlyFav(false); setPage(1) }}>只看关注 ×</Chip> : null}
          {loading ? <span className="v3-caption" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Spinner size={13} /> 刷新中</span> : null}
        </div>
      </Card>

      <Card className="kyv3-list-card">
        <div className="kyv3-list-head">
          <div className="kyv3-list-title">
            院校列表
            <small>共 {filtered.length} 所 · 第 {curPage}/{totalPages} 页</small>
          </div>
          <div className="kyv3-list-tools">
            <Segmented
              ariaLabel="院校排序"
              value={sort}
              onChange={changeSort}
              options={SORTS.map((o) => ({ value: o.key, label: o.label }))}
            />
            <Button variant="tonal" size="sm" icon={<Sparkles size={14} />} onClick={randomPick} disabled={!filtered.length}>
              随机抽一所
            </Button>
          </div>
        </div>

        {error ? (
          <Alert tone="danger" icon={<AlertCircle size={18} />} className="kyv3-note kyv3-note--spaced">
            <p>{error}</p>
          </Alert>
        ) : null}

        {current.length ? (
          <div className="kyv3-school-grid">
            {current.map((s) => (
              <SchoolCard
                key={s.id}
                s={s}
                isFav={favs.has(s.id)}
                isCmp={cmpSet.has(s.id)}
                isOpen={expandedId === s.id}
                majors={majorsMap[s.id]}
                majorsLoading={majorsLoading === s.id}
                onFav={() => toggleFav(s.id)}
                onCmp={() => toggleCmp(s.id)}
                onExpand={() => toggleExpand(s.id)}
                highlight={hlId === s.id}
                covMap={covMap}
              />
            ))}
          </div>
        ) : (
          <Empty
            icon={<Search size={26} />}
            title="没有符合条件的院校"
            text="试试放宽地区 / 层级 / 关键词，或点击「随机抽一所」"
            action={<Button variant="tonal" onClick={resetFilters}>清空筛选</Button>}
          />
        )}

        {filtered.length > PAGE_SIZE ? (
          <nav className="kyv3-pager" aria-label="分页">
            <button type="button" disabled={curPage <= 1} onClick={() => setPage(curPage - 1)}>上一页</button>
            {pageNumbers[0] > 1 ? (
              <>
                <button type="button" onClick={() => setPage(1)}>1</button>
                {pageNumbers[0] > 2 ? <span className="kyv3-pager-gap">…</span> : null}
              </>
            ) : null}
            {pageNumbers.map((n) => (
              <button key={n} type="button" className={n === curPage ? 'is-current' : ''} onClick={() => setPage(n)}>{n}</button>
            ))}
            {pageNumbers[pageNumbers.length - 1] < totalPages ? (
              <>
                {pageNumbers[pageNumbers.length - 1] < totalPages - 1 ? <span className="kyv3-pager-gap">…</span> : null}
                <button type="button" onClick={() => setPage(totalPages)}>{totalPages}</button>
              </>
            ) : null}
            <button type="button" disabled={curPage >= totalPages} onClick={() => setPage(curPage + 1)}>下一页</button>
            <span className="kyv3-pager-info">第 {curPage}/{totalPages} 页 · 共 {filtered.length} 所</span>
          </nav>
        ) : null}

        {cmpSet.size > 0 ? (
          <div className="kyv3-compare-bar">
            <span className="kyv3-compare-bar__info">
              <ListChecks size={15} /> 已选 <b>{cmpSet.size}</b> 所院校用于对比
            </span>
            <span className="kyv3-compare-bar__actions">
              <Button variant="text" size="sm" onClick={() => setCmpSet(new Set())}>清空</Button>
              <Button size="sm" onClick={goCompare} disabled={cmpSet.size < 2}>开始对比（≥2）</Button>
            </span>
          </div>
        ) : null}
      </Card>

      <Card className="kyv3-analysis">
        <div className="kyv3-analysis-head">
          <CardHead
            icon={<BarChart3 size={17} />}
            title="数据分析"
            sub="实时取自 /api/kaoyan/analysis/dashboard 与院校聚合字段"
          />
          <Button variant="text" size="sm" onClick={() => setShowAnalysis((v) => !v)} aria-expanded={showAnalysis}>
            {showAnalysis ? '收起数据看板' : '展开数据看板'}
          </Button>
        </div>
        {showAnalysis ? (
          analysis ? (
            <div className="kyv3-chart-grid">
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">各省份拟录取人数 Top10</div>
                <EChart option={provinceBar} style={{ height: 260 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">录取平均分分数段</div>
                <EChart option={scoreBar} style={{ height: 220 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">复录比分布</div>
                <EChart option={ratioBar} style={{ height: 220 }} />
                <div className="kyv3-chart-note">绿 &lt;1.2 友好 · 金 1.2–1.8 适中 · 红 ≥1.8 激烈</div>
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">院校层级分布</div>
                <EChart option={levelPie} style={{ height: 240 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">热门业务课二 Top15</div>
                <EChart option={major2Bar} style={{ height: 280 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">数学科目分布</div>
                <EChart option={mathBar} style={{ height: 220 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">英语科目分布</div>
                <EChart option={englishBar} style={{ height: 220 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">各专业复试 / 录取平均分对比 Top10</div>
                <EChart option={majorScoreBar} style={{ height: 300 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">各专业招生人数占比 Top10</div>
                <EChart option={majorPie} style={{ height: 260 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">各学院招生情况 Top10</div>
                <EChart option={collegeBar} style={{ height: 260 }} />
              </div>
              <div className="kyv3-chart-card">
                <div className="kyv3-chart-title">专业课分数分布</div>
                <EChart option={scoreDistBar} style={{ height: 220 }} />
              </div>
              <div className="kyv3-chart-card kyv3-hist-card">
                <div className="kyv3-chart-title">分数分布直方图（总分 / 专业课 / 数学）</div>
                <div className="kyv3-hist-grid">
                  <div className="kyv3-hist-item">
                    <div className="kyv3-hist-sub">{totalHist.fromBackend ? '总分（总分线）' : '总分（录取均分兜底）'}</div>
                    <EChart option={totalHistBar} style={{ height: 210 }} />
                  </div>
                  <div className="kyv3-hist-item">
                    <div className="kyv3-hist-sub">{majorHist.fromBackend ? '专业课（专业课均分）' : '专业课（专业课均分兜底）'}</div>
                    <EChart option={majorHistBar} style={{ height: 210 }} />
                  </div>
                  <div className="kyv3-hist-item">
                    <div className="kyv3-hist-sub">数学（数学线）</div>
                    {mathHistBar ? <EChart option={mathHistBar} style={{ height: 210 }} /> : (
                      <div className="kyv3-hist-empty">数学分数分布数据待后端聚合接口刷新后展示</div>
                    )}
                  </div>
                </div>
                <div className="kyv3-chart-note">
                  数据库无逐考生原始分数，基于现有分数线 / 均分数据按分数段统计；前端兜底计算的部分已标注为「兜底」。
                </div>
              </div>
            </div>
          ) : (
            <Empty icon={<BarChart3 size={24} />} title="数据分析暂不可用" text={analysisError || '聚合接口没有返回数据，稍后刷新重试。'} />
          )
        ) : (
          <p className="v3-caption" style={{ marginTop: 8 }}>
            默认收起，避免首屏堆叠图表。展开后可查看省份招生、分数段、复录比、专业 / 学院分布等 14 组实时聚合视图。
          </p>
        )}
      </Card>
    </div>
  )
}
