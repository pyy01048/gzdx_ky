import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import EChart from '../../components/EChart'
import {
  ADMISSION_FIELDS, SCORE_FIELDS, UNTRUSTED_FIELDS, examSubjects, resolveSourceType,
} from '../../utils/kaoyanFields'
import { readMigrated, ukey } from '../../utils/userKeys'
import { toEchartsProvince } from '../../utils/province'
import { chartTheme } from '../charts'
import {
  Alert, AnimatedNumber, Badge, Button, Card, CardHead, Chip, Empty, LoadingState,
  PageHeader, Ring, Skeleton, Tabs, toast, toastErr, toastWarn, useMedia, cx,
} from '../ui'
import {
  Activity, AlertCircle, AlertTriangle, ArrowRight, ArrowUpRight, BarChart3, Bookmark,
  CheckCircle2, ChevronLeft, ExternalLink, FileText, GraduationCap, InfoCircle, ListChecks,
  Map, RefreshCw, School, TrendingDown, TrendingUp,
} from '../icons'
import { useAuth } from '../../auth/AuthContext'
import '../styles/kaoyan-core-v3.css'

/* ==========================================================================
   院校详情 · Aurora v3
   数据契约与旧版一致：/schools/{id}、/majors、/scores、/admissions、
   /enrollment-plan、/notices、/reforms、/analysis/score-detail/{id}
   ========================================================================== */

const FAV_KEY = 'kaoyan-fav-schools'
const CMP_KEY = 'ky_compare_school_ids'
const MAX_CMP = 5

const PROVINCE_COORDS = {
  北京: [116.4, 39.9], 天津: [117.2, 39.13], 河北: [114.5, 38.04],
  山西: [112.55, 37.87], 内蒙古: [111.75, 40.84], 辽宁: [123.43, 41.8],
  吉林: [125.32, 43.9], 黑龙江: [126.63, 45.75], 上海: [121.47, 31.23],
  江苏: [118.78, 32.04], 浙江: [120.15, 30.28], 安徽: [117.28, 31.86],
  福建: [119.3, 26.08], 江西: [115.89, 28.68], 山东: [117.0, 36.65],
  河南: [113.65, 34.76], 湖北: [114.3, 30.6], 湖南: [112.98, 28.19],
  广东: [113.28, 23.13], 广西: [108.32, 22.82], 海南: [110.35, 20.02],
  重庆: [106.55, 29.56], 四川: [104.07, 30.67], 贵州: [106.71, 26.57],
  云南: [102.71, 25.04], 西藏: [91.13, 29.66], 陕西: [108.95, 34.27],
  甘肃: [103.82, 36.06], 青海: [101.78, 36.62], 宁夏: [106.28, 38.47],
  新疆: [87.62, 43.82], 台湾: [121.5, 25.03], 香港: [114.17, 22.28],
  澳门: [113.55, 22.2],
}

const TREND_META = {
  持续上涨: { label: '持续上涨', hint: '录取均分逐年走高，竞争在加剧', cls: 'is-danger', icon: TrendingUp },
  持续下降: { label: '持续下降', hint: '录取均分逐年回落，报考窗口相对友好', cls: 'is-success', icon: TrendingDown },
  波动较大: { label: '波动较大', hint: '年度间起伏明显，建议结合近三年判断', cls: 'is-primary', icon: Activity },
  基本平稳: { label: '基本平稳', hint: '录取均分变化不大，参考价值较高', cls: 'is-muted', icon: Activity },
  数据不足: { label: '数据不足', hint: '连续年份数据不足，暂不做趋势判断', cls: 'is-muted', icon: InfoCircle },
}

const CHANGE_TONE = {
  停招: 'danger',
  改考科目: 'warning',
  新增专业: 'success',
}

const loadedFavs = () => {
  try {
    const value = readMigrated(FAV_KEY, {})
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  } catch {
    return {}
  }
}

const loadedCompare = () => {
  try {
    const value = readMigrated(CMP_KEY, [])
    return Array.isArray(value) ? value : []
  } catch {
    return []
  }
}

function normalizeTags(tags) {
  if (!tags) return []
  if (Array.isArray(tags)) {
    return tags
      .map((t) => (typeof t === 'string' ? t : t?.name || t?.label || ''))
      .map((t) => String(t).trim())
      .filter(Boolean)
  }
  if (typeof tags === 'string') {
    const raw = tags.trim()
    if (!raw) return []
    try {
      return normalizeTags(JSON.parse(raw))
    } catch {
      return raw.split(/[,，、;；|]/).map((t) => t.trim()).filter(Boolean)
    }
  }
  return []
}

function levelTone(level) {
  if (level === '985') return 'danger'
  if (level === '211') return 'primary'
  if (level === '双一流') return 'success'
  return undefined
}

function fmtStat(n) {
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n) >= 100) return Math.round(n).toLocaleString('zh-CN')
  return Math.round(n * 100) / 100
}

function referenceText(raw) {
  if (!raw) return ''
  if (Array.isArray(raw)) {
    return raw
      .map((item) => {
        if (typeof item === 'string') return item
        return item?.title || item?.name || item?.book || ''
      })
      .filter(Boolean)
      .join('；')
  }
  if (typeof raw === 'object') return raw.title || raw.name || ''
  return String(raw)
}

/* ---- V14: 择校宝典 / txkyer 数据渲染辅助 ---- */
function parseMarkdownTable(text) {
  if (!text) return null
  const lines = String(text).split('\n').map((l) => l.trim()).filter(Boolean)
  const tableLines = lines.filter((l) => l.startsWith('|'))
  if (tableLines.length < 2) return null
  const cells = (line) => line.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
  const headers = cells(tableLines[0]).filter(Boolean)
  const rows = tableLines
    .slice(1)
    .filter((l) => !/^[\s|\-:]+$/.test(l))
    .map(cells)
    .filter((r) => r.length >= headers.length && r.some((c) => c))
    .map((r) => r.slice(0, headers.length))
  if (!headers.length) return null
  return { headers, rows }
}

function parseMarkdownList(text) {
  if (!text) return []
  return String(text)
    .split('\n')
    .map((l) => l.replace(/^[-*]\s+/, '').replace(/\*\*(.+?)\*\*/g, '$1').trim())
    .filter(Boolean)
}

/** 录取总分直方图（默认 10 分一档；只统计最新年份） */
function scoreHistogram(details, binSize = 10) {
  if (!Array.isArray(details) || !details.length) return null
  const years = new Set(details.map((d) => Number(d.year) || 0).filter(Boolean))
  const year = years.size ? Math.max(...years) : null
  const bins = {}
  let min = Infinity
  let max = -Infinity
  let count = 0
  for (const d of details) {
    const v = Number(d.score_total)
    if (!Number.isFinite(v)) continue
    const y = Number(d.year) || 0
    if (year && y && y !== year) continue
    min = Math.min(min, v)
    max = Math.max(max, v)
    const lo = Math.floor(v / binSize) * binSize
    bins[lo] = (bins[lo] || 0) + 1
    count += 1
  }
  if (!count) return null
  const xs = Object.keys(bins).map(Number).sort((a, b) => a - b)
  return {
    year, min, max, count,
    xs,
    ys: xs.map((x) => bins[x]),
    labels: xs.map((x) => `${x}-${x + binSize - 1}`),
  }
}

const SOURCE_META = {
  官方: { label: '官方来源', cls: 'is-official', tone: 'success' },
  聚合: { label: '聚合来源', cls: 'is-aggregator', tone: 'warning' },
  未验证: { label: '来源未核验', cls: 'is-unverified', tone: undefined },
}

function sourceMeta(source) {
  return SOURCE_META[resolveSourceType(source)] || SOURCE_META['未验证']
}

function SourceDot({ source }) {
  const meta = sourceMeta(source)
  return (
    <span
      className={cx('kyv3-src-dot', meta.cls)}
      title={`数据来源：${meta.label}${source ? `（${source}）` : ''}`}
      aria-hidden="true"
    />
  )
}

function HeroStat({ label, value, tone }) {
  const n = Number(value)
  const valid = value !== null && value !== undefined && value !== '' && Number.isFinite(n)
  return (
    <div className="kyv3-hero-stat">
      <span className="kyv3-hero-stat__label" title={label}>{label}</span>
      <span className={cx('kyv3-hero-stat__value', tone && `is-${tone}`, !valid && 'is-muted')}>
        {valid ? <AnimatedNumber value={n} format={fmtStat} /> : '—'}
      </span>
    </div>
  )
}

function QualityNote() {
  const label = { admit_count: '拟录取人数' }
  return (
    <details className="kyv3-quality">
      <summary>为什么少了这几个字段？</summary>
      <ul>
        {Object.entries(UNTRUSTED_FIELDS)
          .filter(([key]) => key === 'admit_count')
          .map(([key, text]) => (
            <li key={key}><b>{label[key] || key}</b>：{text}</li>
          ))}
      </ul>
    </details>
  )
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

export default function KaoyanSchoolDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [school, setSchool] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [majors, setMajors] = useState([])
  const [enrollPlan, setEnrollPlan] = useState(null)
  const [scores, setScores] = useState([])
  const [admissions, setAdmissions] = useState([])
  const [admissionDetails, setAdmissionDetails] = useState([])
  const [notices, setNotices] = useState([])
  const [reforms, setReforms] = useState([])
  const [insight, setInsight] = useState(null)
  const [crawling, setCrawling] = useState(false)
  const [selMajorId, setSelMajorId] = useState(null)
  const [scoreYear, setScoreYear] = useState(null)
  const [scoreDegree, setScoreDegree] = useState('')
  const [tab, setTab] = useState('overview')
  const [favs, setFavs] = useState(loadedFavs)
  const [cmpIds, setCmpIds] = useState(loadedCompare)

  const mode = useThemeMode()
  const isMobile = useMedia('(max-width: 760px)')
  const isDark = mode === 'dark'

  useEffect(() => {
    let alive = true
    setSchool(null)
    setLoadError(null)
    setMajors([])
    setEnrollPlan(null)
    setScores([])
    setAdmissions([])
    setAdmissionDetails([])
    setNotices([])
    setReforms([])
    setInsight(null)
    setSelMajorId(null)
    setScoreYear(null)

    Promise.all([
      kaoyanApi.schoolDetail(id),
      kaoyanApi.schoolMajors(id),
      kaoyanApi.schoolScores(id),
      kaoyanApi.schoolAdmissions(id),
    ]).then(([detail, majorRows, scoreRows, admissionRows]) => {
      if (!alive) return
      setSchool(detail || null)
      setMajors(Array.isArray(majorRows) ? majorRows : [])
      setScores(Array.isArray(scoreRows) ? scoreRows : [])
      setAdmissions(Array.isArray(admissionRows) ? admissionRows : [])
      setScoreYear(Array.isArray(scoreRows) && scoreRows.length
        ? Math.max(...scoreRows.map((x) => Number(x.year) || 0))
        : null)
    }).catch((e) => {
      if (!alive) return
      setLoadError({ status: e?.status || 0, message: e?.message || '院校详情加载失败' })
    })

    kaoyanApi.schoolEnrollmentPlan(id)
      .then((plan) => { if (alive) setEnrollPlan(plan || null) })
      .catch(() => { if (alive) setEnrollPlan(null) })

    kaoyanApi.schoolNotices(id, { limit: 50 })
      .then((rows) => { if (alive) setNotices(Array.isArray(rows) ? rows : []) })
      .catch(() => { if (alive) setNotices([]) })

    kaoyanApi.reforms({ school_id: id, limit: 20 })
      .then((rows) => { if (alive) setReforms(Array.isArray(rows) ? rows : []) })
      .catch(() => { if (alive) setReforms([]) })

    kaoyanApi.schoolAdmissionDetails(id, { limit: 5000 })
      .then((rows) => { if (alive) setAdmissionDetails(Array.isArray(rows) ? rows : []) })
      .catch(() => { if (alive) setAdmissionDetails([]) })

    kaoyanApi.scoreDetail(id)
      .then((data) => { if (alive) setInsight(data || null) })
      .catch(() => { if (alive) setInsight(null) })

    return () => { alive = false }
  }, [id, reloadKey])

  const scoreYears = useMemo(
    () => Array.from(new Set(scores.map((s) => s.year))).filter((y) => y != null).sort((a, b) => b - a),
    [scores],
  )
  const activeScoreYear = scoreYear ?? scoreYears[0] ?? null

  const scoreRange = useMemo(() => {
    const byYear = {}
    scores.forEach((s) => {
      if (s.total_line == null) return
      ;(byYear[s.year] ||= []).push(Number(s.total_line))
    })
    return Object.keys(byYear)
      .map(Number)
      .sort((a, b) => a - b)
      .map((year) => {
        const values = byYear[year].filter((n) => Number.isFinite(n))
        if (!values.length) return null
        return {
          year,
          min: Math.min(...values),
          max: Math.max(...values),
          avg: +(values.reduce((a, b) => a + b, 0) / values.length).toFixed(1),
        }
      })
      .filter(Boolean)
  }, [scores])

  const scoreRangeOption = useMemo(() => {
    if (!scoreRange.length) return null
    const t = chartTheme(isDark)
    const axis = {
      axisLine: { lineStyle: { color: t.axisLine.lineStyle.color } },
      axisLabel: { color: t.textStyle.color, fontSize: 10 },
      splitLine: { lineStyle: { color: t.splitLine.lineStyle.color } },
      axisTick: { show: false },
    }
    return {
      color: t.color,
      textStyle: t.textStyle,
      tooltip: { ...t.tooltip, trigger: 'axis' },
      legend: {
        data: ['最高院线', '平均院线', '最低院线'],
        top: 0,
        itemWidth: 10,
        itemHeight: 10,
        icon: 'roundRect',
        textStyle: { color: t.textStyle.color, fontSize: 11 },
      },
      grid: { left: 8, right: 14, top: 40, bottom: 6, containLabel: true },
      xAxis: { type: 'category', data: scoreRange.map((r) => r.year), ...axis, splitLine: { show: false } },
      yAxis: {
        type: 'value',
        name: '分',
        ...axis,
        axisLine: { show: false },
        nameTextStyle: { color: t.textStyle.color, fontSize: 10 },
      },
      series: [
        {
          name: '最高院线', type: 'line', smooth: true, symbolSize: 6,
          data: scoreRange.map((r) => r.max),
          itemStyle: { color: '#D96570' }, lineStyle: { width: 2.4 },
        },
        {
          name: '平均院线', type: 'line', smooth: true, symbolSize: 6,
          data: scoreRange.map((r) => r.avg),
          itemStyle: { color: '#F9AB00' }, lineStyle: { width: 2.4 },
        },
        {
          name: '最低院线', type: 'line', smooth: true, symbolSize: 6,
          data: scoreRange.map((r) => r.min),
          itemStyle: { color: '#4285F4' }, lineStyle: { width: 2.4 },
        },
      ],
    }
  }, [scoreRange, isDark])

  const filteredScores = useMemo(
    () => scores
      .filter((s) => s.year === activeScoreYear && (!scoreDegree || s.degree_type === scoreDegree))
      .sort((a, b) => String(a.major_code || '').localeCompare(String(b.major_code || ''))),
    [scores, activeScoreYear, scoreDegree],
  )

  const latestAdmYear = useMemo(() => {
    if (!admissions.length) return null
    const years = admissions.map((a) => Number(a.year) || 0)
    return years.length ? Math.max(...years) : null
  }, [admissions])

  const majorRows = useMemo(() => {
    const byMajor = {}
    admissions
      .filter((a) => a.year === latestAdmYear)
      .forEach((a) => {
        const key = `${a.major_code || ''} ${a.major_name || ''}`.trim() || '未标注'
        if (!byMajor[key]) byMajor[key] = { admitAvg: [], majorAvg: [], retest: 0, admit: 0 }
        if (a.admit_avg_score != null && Number.isFinite(Number(a.admit_avg_score))) byMajor[key].admitAvg.push(Number(a.admit_avg_score))
        if (a.major_avg_score != null && Number.isFinite(Number(a.major_avg_score))) byMajor[key].majorAvg.push(Number(a.major_avg_score))
        byMajor[key].retest += Number(a.retest_count) || 0
        byMajor[key].admit += Number(a.admit_count) || 0
      })
    return Object.entries(byMajor)
      .map(([name, v]) => ({
        name,
        admitAvg: v.admitAvg.length ? +(v.admitAvg.reduce((x, y) => x + y, 0) / v.admitAvg.length).toFixed(1) : null,
        majorAvg: v.majorAvg.length ? +(v.majorAvg.reduce((x, y) => x + y, 0) / v.majorAvg.length).toFixed(1) : null,
        retest: v.retest,
        admit: v.admit,
      }))
      .sort((a, b) => (b.admit || 0) - (a.admit || 0))
      .slice(0, 20)
  }, [admissions, latestAdmYear])

  const majorAvgOption = useMemo(() => {
    if (!majorRows.length) return null
    const t = chartTheme(isDark)
    const axis = {
      axisLine: { lineStyle: { color: t.axisLine.lineStyle.color } },
      axisLabel: { color: t.textStyle.color, fontSize: 10 },
      splitLine: { lineStyle: { color: t.splitLine.lineStyle.color } },
      axisTick: { show: false },
    }
    return {
      color: t.color,
      textStyle: t.textStyle,
      tooltip: { ...t.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: {
        data: ['录取均分', '专业课均分'],
        top: 0,
        itemWidth: 10,
        itemHeight: 10,
        icon: 'roundRect',
        textStyle: { color: t.textStyle.color, fontSize: 11 },
      },
      grid: { left: 8, right: 14, top: 42, bottom: 8, containLabel: true },
      xAxis: {
        type: 'category',
        data: majorRows.map((r) => r.name),
        ...axis,
        splitLine: { show: false },
        axisLabel: {
          color: t.textStyle.color,
          fontSize: 9,
          interval: 0,
          rotate: isMobile ? 52 : 38,
          width: 86,
          overflow: 'truncate',
        },
      },
      yAxis: {
        type: 'value',
        name: '分数',
        ...axis,
        axisLine: { show: false },
        nameTextStyle: { color: t.textStyle.color, fontSize: 10 },
      },
      series: [
        {
          name: '录取均分', type: 'bar', barMaxWidth: 18,
          data: majorRows.map((r) => r.admitAvg),
          itemStyle: { color: '#F9AB00', borderRadius: [4, 4, 0, 0] },
        },
        {
          name: '专业课均分', type: 'bar', barMaxWidth: 18,
          data: majorRows.map((r) => r.majorAvg),
          itemStyle: { color: '#4285F4', borderRadius: [4, 4, 0, 0] },
        },
      ],
    }
  }, [majorRows, isDark, isMobile])

  const mapOption = useMemo(() => {
    if (!school?.province) return null
    const t = chartTheme(isDark)
    const palette = isDark
      ? { area: '#181C25', border: '#2A303C', emphasis: '#232A37', surface: '#12151D', accent: '#A8C7FA', text: '#E9EDF4', red: '#F28B82' }
      : { area: '#F2F5FA', border: '#C9D4E6', emphasis: '#E2EAF7', surface: '#FFFFFF', accent: '#8AB4F8', text: '#1F2023', red: '#C5221F' }
    const coords = PROVINCE_COORDS[school.province] || [105, 35]
    return {
      textStyle: t.textStyle,
      tooltip: {
        ...t.tooltip,
        trigger: 'item',
        formatter: (p) => (p.name ? `${p.name}<br/>${Array.isArray(p.value) ? p.value[2] || '' : ''}` : ''),
      },
      geo: {
        map: 'china',
        roam: false,
        zoom: 1.12,
        label: { show: false },
        itemStyle: { areaColor: palette.area, borderColor: palette.border },
        emphasis: { itemStyle: { areaColor: palette.emphasis } },
      },
      series: [
        {
          name: '院校省份',
          type: 'map',
          map: 'china',
          roam: false,
          zoom: 1.12,
          data: [{ name: toEchartsProvince(school.province), value: 1 }],
          label: { show: false },
          itemStyle: { areaColor: palette.accent, borderColor: palette.surface },
          emphasis: { label: { show: false }, itemStyle: { areaColor: palette.accent } },
          select: { disabled: true },
        },
        {
          name: '院校定位',
          type: 'scatter',
          coordinateSystem: 'geo',
          data: [{ name: school.name, value: [...coords, school.name] }],
          symbolSize: 14,
          itemStyle: { color: palette.red },
          label: {
            show: true,
            formatter: (p) => p.name || '',
            position: 'right',
            color: palette.text,
            fontSize: 11,
            fontWeight: 600,
          },
        },
      ],
    }
  }, [school, isDark])

  /* V14: 择校宝典院校特色（feature / research / employment） */
  const schoolTags = school?.tags && typeof school.tags === 'object' && !Array.isArray(school.tags) ? school.tags : {}
  const schoolFeature = String(schoolTags.feature || '').trim()
  const schoolResearch = String(schoolTags.research || '').trim()
  const schoolEmployment = String(schoolTags.employment || '').trim()
  const researchTable = useMemo(() => parseMarkdownTable(schoolResearch), [schoolResearch])
  const employmentItems = useMemo(() => parseMarkdownList(schoolEmployment), [schoolEmployment])
  const hasSchoolDetail = Boolean(schoolFeature || researchTable || employmentItems.length)

  /* V14: 2026 拟录取分数分布（逐人分数直方图） */
  const hist = useMemo(() => scoreHistogram(admissionDetails), [admissionDetails])
  const histOption = useMemo(() => {
    if (!hist) return null
    const t = chartTheme(isDark)
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 42, right: 16, top: 30, bottom: 34 },
      xAxis: {
        type: 'category', data: hist.labels,
        axisLabel: { color: t.textStyle.color, fontSize: 10, rotate: isMobile ? 35 : 0 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: t.textStyle.color },
        splitLine: { lineStyle: { color: t.splitLine.lineStyle.color } },
      },
      series: [{
        name: '录取人数', type: 'bar', data: hist.ys, barMaxWidth: 22,
        itemStyle: { color: '#FF6B35', borderRadius: [3, 3, 0, 0] },
      }],
    }
  }, [hist, isDark, isMobile])

  /* 最新年份带分数分布(extra)的拟录取明细 */
  const latestAdmRows = useMemo(
    () => admissions
      .filter((a) => a.year === latestAdmYear && a.extra && typeof a.extra === 'object')
      .sort((a, b) => String(a.major_name || '').localeCompare(String(b.major_name || ''))),
    [admissions, latestAdmYear],
  )

  if (!school) {
    if (!loadError) {
      return (
        <div className="kyv3-page">
          <Link to="/kaoyan/schools" className="kyv3-back"><ChevronLeft size={14} /> 返回院校库</Link>
          <Card className="kyv3-hero-card">
            <div className="kyv3-hero-top">
              <Skeleton width={66} height={66} radius={20} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <Skeleton width="38%" height={26} />
                <div style={{ height: 10 }} />
                <Skeleton width="58%" height={14} />
                <div style={{ height: 14 }} />
                <Skeleton width="72%" height={14} />
              </div>
            </div>
            <div style={{ height: 18 }} />
            <Skeleton height={72} radius={14} />
          </Card>
          <LoadingState text="院校详情加载中…" />
        </div>
      )
    }

    const notFound = loadError.status === 404
    return (
      <div className="kyv3-page">
        <Link to="/kaoyan/schools" className="kyv3-back"><ChevronLeft size={14} /> 返回院校库</Link>
        <Card>
          <Empty
            icon={notFound ? <School size={26} /> : <AlertCircle size={26} />}
            title={notFound ? '未找到该院校' : '院校详情加载失败'}
            text={notFound
              ? `院校 ID「${id}」不在院校库中，可能已被删除或链接有误。`
              : loadError.message}
            action={(
              <div className="v3-row">
                <Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">返回院校库</Link>
                {!notFound ? (
                  <Button variant="text" icon={<RefreshCw size={14} />} onClick={() => setReloadKey((k) => k + 1)}>
                    重试
                  </Button>
                ) : null}
              </div>
            )}
          />
        </Card>
      </div>
    )
  }

  const isFav = !!favs[school.id]
  const isCompared = cmpIds.some((x) => String(x) === String(school.id))
  const heroTags = normalizeTags(school.tags).filter((tag, i, arr) => arr.indexOf(tag) === i).slice(0, 8)
  const has0854 = majors.some((m) => String(m.subject_code || '').startsWith('0854'))
  const coverageItems = Array.isArray(school.coverage_items) ? school.coverage_items : []
  const noticeTypes = school.notice_types && typeof school.notice_types === 'object'
    ? Object.entries(school.notice_types)
    : []
  const coveredCount = coverageItems.filter((it) => it.ok).length
  const coverageTone = Number(school.coverage_score) >= 80 ? 'success' : Number(school.coverage_score) >= 50 ? 'primary' : 'warning'

  const persistCmp = (next) => {
    try { localStorage.setItem(ukey(CMP_KEY), JSON.stringify(next)) } catch { /* 隐私模式 */ }
  }

  const toggleFav = () => {
    const next = { ...favs }
    if (next[school.id]) delete next[school.id]
    else next[school.id] = { name: school.name, level: school.level }
    setFavs(next)
    try { localStorage.setItem(ukey(FAV_KEY), JSON.stringify(next)) } catch { /* 隐私模式 */ }
    toast(next[school.id] ? '已关注该院校' : '已取消关注')
  }

  const toggleCompare = () => {
    if (isCompared) {
      const next = cmpIds.filter((x) => String(x) !== String(school.id))
      setCmpIds(next)
      persistCmp(next)
      toast('已移出对比清单')
      return
    }
    if (cmpIds.length >= MAX_CMP) {
      toastWarn(`最多同时对比 ${MAX_CMP} 所院校`)
      return
    }
    const next = [...cmpIds, school.id]
    setCmpIds(next)
    persistCmp(next)
    toast('已加入对比清单')
  }

  const clearCompare = () => {
    setCmpIds([])
    persistCmp([])
    toast('已清空对比清单')
  }

  const crawlNotices = () => {
    if (crawling) return
    setCrawling(true)
    kaoyanApi.crawlSchoolNotices(school.id)
      .then((r) => {
        toast(r.new > 0 ? `已新增 ${r.new} 条公告（共 ${r.notices_total} 条）` : `暂无新增（共 ${r.notices_total} 条）`)
        return kaoyanApi.schoolNotices(school.id, { limit: 50 })
          .then((rows) => setNotices(Array.isArray(rows) ? rows : []))
          .catch(() => {})
      })
      .catch((e) => toastErr(e?.message || '爬取失败，真机联网后重试'))
      .finally(() => setCrawling(false))
  }

  const scoreStats = [
    { label: '学院数', value: school.college_count },
    { label: '专业方向', value: school.major_count },
    { label: `进复试${school.year ? `(${school.year})` : ''}`, value: school.retest_count },
    { label: '拟录取', value: school.admit_count },
    { label: '复录比', value: school.retest_ratio, tone: 'warn' },
    { label: '录取均分', value: school.admit_avg_score, tone: 'danger' },
    { label: '专业课均分', value: school.major_avg_score, tone: 'success' },
    { label: '热度', value: school.heat },
  ]

  const tabs = [
    { value: 'overview', label: '院校概况' },
    { value: 'majors', label: '招生计划', count: majors.length },
    { value: 'scores', label: '历年分数', count: scores.length || null },
    { value: 'admissions', label: '招生数据', count: admissions.length || null },
    ...(notices.length ? [{ value: 'notices', label: '公告文章', count: notices.length }] : []),
  ]

  const selMajor = majors.find((m) => String(m.id) === String(selMajorId)) || majors[0] || null
  const planItem = selMajor
    ? (enrollPlan?.items || []).find(
      (it) => (it.major_code && selMajor.code && it.major_code === selMajor.code) || it.major === selMajor.name,
    )
    : null
  const majorAdmission = selMajor
    ? admissions.find(
      (a) => (selMajor.code && a.major_code && String(a.major_code) === String(selMajor.code))
        || (selMajor.name && a.major_name === selMajor.name),
    )
    : null
  const selSubjects = selMajor
    ? (examSubjects(selMajor.exam_subjects).length
      ? examSubjects(selMajor.exam_subjects)
      : examSubjects(planItem?.exam_subjects))
    : []
  const selReferences = referenceText(selMajor?.reference_books)
  const trend = insight?.trends?.admit_avg_trend
  const trendMeta = TREND_META[trend] || null
  const recentAdmission = insight?.admissions_detail?.[0]
  const showInsight = insight?.trends && (trend !== '数据不足' || insight.line_vs_national)
  const lineVsNational = insight?.line_vs_national
  const lineDiff = lineVsNational?.diff != null && Number.isFinite(Number(lineVsNational.diff))
    ? Number(lineVsNational.diff)
    : null
  const TrendIcon = trendMeta?.icon || InfoCircle

  return (
    <div className="kyv3-page">
      <Link to="/kaoyan/schools" className="kyv3-back"><ChevronLeft size={14} /> 返回院校库</Link>

      <Card className="kyv3-hero-card">
        <div className="kyv3-hero-top">
          <div className="kyv3-hero-logo">
            {school.logo_url
              ? <img src={school.logo_url} alt="" />
              : (school.name || '校')[0]}
          </div>
          <div className="kyv3-hero-main">
            <PageHeader
              eyebrow={`SCHOOL PROFILE · ${school.province || '全国'}院校`}
              title={school.name}
              sub={[
                school.province && school.city ? `${school.province} · ${school.city}` : school.province,
                school.level || '未分类',
                school.coverage_score != null ? `资料完整度 ${school.coverage_score}%` : '',
              ].filter(Boolean).join(' · ')}
              actions={(
                <div className="kyv3-hero-actions">
                  <Button
                    variant="tonal"
                    className={cx('kyv3-hero-fav', isFav && 'is-active')}
                    icon={<Bookmark size={16} />}
                    onClick={toggleFav}
                  >
                    {isFav ? '已关注' : '关注'}
                  </Button>
                  <Button
                    variant="outline"
                    className={cx('kyv3-hero-cmp', isCompared && 'is-active')}
                    icon={<ListChecks size={16} />}
                    onClick={toggleCompare}
                  >
                    {isCompared ? '已加入对比' : '加入对比'}
                  </Button>
                  {school.official_url ? (
                    <a className="v3-btn v3-btn--filled" href={school.official_url} target="_blank" rel="noreferrer">
                      研究生院官网 <ExternalLink size={14} />
                    </a>
                  ) : null}
                </div>
              )}
            />
            <div className="kyv3-hero-tags">
              <Badge tone={levelTone(school.level || '未分类')}>{school.level || '未分类'}</Badge>
              {school.type ? <Badge>{school.type}</Badge> : null}
              {school.region ? <Badge>{school.region}</Badge> : null}
              {has0854 ? <Badge tone="primary">0854 电子信息</Badge> : null}
              {heroTags.map((tag) => <Badge key={tag} tone="outline">{tag}</Badge>)}
            </div>
            <div className="kyv3-hero-links">
              {school.official_url ? (
                <a href={school.official_url} target="_blank" rel="noreferrer">
                  研究生院官网 <ArrowUpRight size={12} />
                </a>
              ) : null}
              <a
                href={`https://yz.chsi.com.cn/sch/search.do?q=${encodeURIComponent(school.name || '')}`}
                target="_blank"
                rel="noreferrer"
              >
                研招网 <ArrowUpRight size={12} />
              </a>
              {school.province ? (
                <a
                  href={`https://map.baidu.com/search/${encodeURIComponent(school.name || '')}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  百度地图 <ArrowUpRight size={12} />
                </a>
              ) : null}
              {school.data_source ? <span>数据来源：{school.data_source}</span> : null}
            </div>
          </div>
        </div>
        <div className="kyv3-hero-stats">
          {scoreStats.map((s) => <HeroStat key={s.label} label={s.label} value={s.value} tone={s.tone} />)}
        </div>
      </Card>

      {reforms.length > 0 ? (
        <Alert tone="danger" icon={<AlertTriangle size={18} />} className="kyv3-reform-alert">
          <div className="kyv3-reform-head">
            <strong>院校变动雷达 · {reforms.length} 条与该校相关的变动</strong>
            <Link to="/kaoyan/notices" className="kyv3-reform-link">
              前往通知中心 <ArrowRight size={12} />
            </Link>
          </div>
          <div className="kyv3-reform-list">
            {reforms.slice(0, 3).map((r) => (
              <div className="kyv3-reform-row" key={r.id}>
                <Badge tone={CHANGE_TONE[r.change_type]}>{r.change_type || '变动'}</Badge>
                <span className="kyv3-reform-title">{r.title}</span>
                {r.year ? <span className="kyv3-reform-year">{r.year}</span> : null}
                {r.url ? (
                  <a className="kyv3-reform-src" href={r.url} target="_blank" rel="noreferrer">
                    原文 <ArrowUpRight size={11} />
                  </a>
                ) : null}
              </div>
            ))}
          </div>
          {reforms.length > 3 ? (
            <div className="kyv3-reform-more">还有 {reforms.length - 3} 条 · 可在「通知中心 · 改考雷达」查看全部</div>
          ) : null}
        </Alert>
      ) : null}

      {showInsight ? (
        <div className="kyv3-insight-grid">
          <Card className="kyv3-insight-card">
            <div className="kyv3-insight-label">录取均分趋势</div>
            {trendMeta ? (
              <div className={cx('kyv3-insight-value', trendMeta.cls)}>
                <TrendIcon size={17} /> {trendMeta.label}
              </div>
            ) : (
              <div className="kyv3-insight-value is-muted">数据不足</div>
            )}
            {trendMeta?.hint ? <div className="kyv3-insight-hint">{trendMeta.hint}</div> : null}
            {recentAdmission?.admit_avg_score != null ? (
              <div className="kyv3-insight-hint">
                最近年录取均分 {recentAdmission.admit_avg_score} 分{recentAdmission.year ? `（${recentAdmission.year}）` : ''}
              </div>
            ) : null}
          </Card>
          {lineVsNational && lineDiff != null ? (
            <Card className="kyv3-insight-card">
              <div className="kyv3-insight-label">复试线 vs 国家线（{lineVsNational.year}）</div>
              <div className={cx('kyv3-insight-value', lineDiff >= 0 ? 'is-danger' : 'is-success')}>
                {lineDiff >= 0 ? <TrendingUp size={17} /> : <TrendingDown size={17} />}
                {lineDiff >= 0 ? '高于' : '低于'}国家线 {Math.abs(lineDiff)} 分
              </div>
              <div className="kyv3-insight-hint">
                校线 {lineVsNational.total_line ?? '—'} / 国家线 {lineVsNational.national_line ?? '—'}
              </div>
            </Card>
          ) : null}
        </div>
      ) : null}

      <Tabs options={tabs} value={tab} onChange={setTab} ariaLabel="院校详情标签页" />

      {tab === 'overview' ? (
        <div className="kyv3-tab-panel">
          <Card>
            <CardHead
              icon={<School size={17} />}
              title="院校概况"
              sub="院校简介与官方入口，数据以目标院校研究生院公布为准"
            />
            <p className={cx('kyv3-prose', !school.intro && 'is-muted')}>
              {school.intro || '暂无院校简介。'}
            </p>
          </Card>

          {hasSchoolDetail ? (
            <Card>
              <CardHead
                icon={<GraduationCap size={17} />}
                title="院校特色 · 研究方向 · 就业去向"
                sub="来源：27考研电子通信考研择校宝典（txkyer.cn 数据）"
              />
              {schoolFeature ? (
                <div className="kyv3-school-feature">
                  <h4>院校特色</h4>
                  <p className="kyv3-prose">{schoolFeature}</p>
                </div>
              ) : null}
              {researchTable ? (
                <div className="kyv3-school-research">
                  <h4>研究方向</h4>
                  <div className="v3-table-wrap kyv3-table-wrap">
                    <table className="v3-table">
                      <thead>
                        <tr>
                          {researchTable.headers.map((h) => <th key={h}>{h}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {researchTable.rows.map((r, i) => (
                          <tr key={i}>
                            {r.map((c, j) => <td key={j}>{c}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
              {employmentItems.length ? (
                <div className="kyv3-school-employment">
                  <h4>就业去向</h4>
                  <ul>
                    {employmentItems.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              ) : null}
            </Card>
          ) : null}

          {coverageItems.length > 0 ? (
            <Card>
              <div className="kyv3-coverage-head">
                <div className="kyv3-coverage-title">
                  <Ring value={Number(school.coverage_score) || 0} size={58} stroke={6} gradient>
                    <strong className="kyv3-coverage-ring-value">{school.coverage_score ?? 0}<small>%</small></strong>
                  </Ring>
                  <div>
                    <h3>院校资料完整度</h3>
                    <p className="kyv3-soft-note">
                      口径：专业目录 / 复试线 / 报录比 / 复试细则 / 参考书 / 分数分布 / 公告 / 简介 / 官网
                    </p>
                  </div>
                </div>
                <Badge tone={coverageTone}>{coveredCount} / {coverageItems.length} 项已收录</Badge>
              </div>
              <div className="kyv3-coverage-grid">
                {coverageItems.map((it) => (
                  <div key={it.key} className={cx('kyv3-coverage-item', it.ok && 'is-ok')}>
                    <strong>
                      {it.ok ? <CheckCircle2 size={12} /> : <InfoCircle size={12} />}
                      {it.label}
                    </strong>
                    <span title={it.detail}>{it.detail}</span>
                  </div>
                ))}
              </div>
              {noticeTypes.length > 0 ? (
                <div className="kyv3-notice-types">
                  <span>公告构成：</span>
                  {noticeTypes.map(([type, count]) => (
                    <Badge key={type} tone="outline">{type} {count}</Badge>
                  ))}
                </div>
              ) : null}
            </Card>
          ) : null}

          {school.province ? (
            <Card>
              <CardHead
                icon={<Map size={17} />}
                title={`院校所在地（${school.province}${school.city || ''}）`}
                sub="地图为省级定位示意，精确位置请使用百度地图"
                actions={(
                  <a
                    className="v3-btn v3-btn--text v3-btn--sm"
                    href={`https://map.baidu.com/search/${encodeURIComponent(school.name || '')}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    百度地图 <ArrowUpRight size={13} />
                  </a>
                )}
              />
              {mapOption ? (
                <EChart option={mapOption} style={{ height: isMobile ? 280 : 350 }} emptyText="暂无地图数据" />
              ) : null}
            </Card>
          ) : null}

          {scoreRangeOption ? (
            <Card>
              <CardHead
                icon={<BarChart3 size={17} />}
                title="院线区间趋势（各专业总分）"
                sub="逐年聚合各专业总分的最低 / 平均 / 最高院线"
              />
              <EChart option={scoreRangeOption} style={{ height: isMobile ? 260 : 330 }} emptyText="暂无院线数据" />
            </Card>
          ) : null}
        </div>
      ) : null}

      {tab === 'majors' ? (
        <Card>
          <CardHead
            icon={<GraduationCap size={17} />}
            title={`招生计划（${majors.length}）`}
            sub={`按「院系 → 专业 → 拟招人数 → 初试科目」逐级展示${enrollPlan?.year ? ` · 招生年度 ${enrollPlan.year}` : ''}`}
          />
          {(!enrollPlan || !(enrollPlan.items || []).length) ? (
            <p className="kyv3-soft-note" style={{ marginTop: -6, marginBottom: 14 }}>
              暂无招生计划聚合数据，以下为专业方向明细。
            </p>
          ) : null}

          {majors.length === 0 ? (
            <Empty
              icon={<GraduationCap size={26} />}
              title="暂无专业数据"
              text="该校暂未收录专业方向与初试科目，稍后再来看看。"
            />
          ) : (
            <div className="kyv3-major-layout">
              <div className="kyv3-major-side" role="listbox" aria-label="专业方向列表">
                <div className="kyv3-major-panel-head">
                  专业方向 <span>共 {majors.length} 个</span>
                </div>
                {majors.map((m) => {
                  const active = selMajor && m.id === selMajor.id
                  return (
                    <button
                      key={m.id}
                      type="button"
                      role="option"
                      aria-selected={active}
                      className={cx('kyv3-major-btn', active && 'is-active')}
                      onClick={() => setSelMajorId(m.id)}
                    >
                      <code>{m.code || '—'}</code>
                      <span title={m.name}>{m.name}</span>
                    </button>
                  )
                })}
              </div>

              {selMajor ? (
                <div className="kyv3-major-detail">
                  <div className="kyv3-major-detail-head">
                    <h3>{selMajor.name}</h3>
                    <code>{selMajor.code || '—'}</code>
                    {selMajor.degree_type ? <Badge>{selMajor.degree_type}</Badge> : null}
                    {planItem?.enroll_count != null ? (
                      <Badge tone="primary">拟招 {planItem.enroll_count} 人</Badge>
                    ) : null}
                  </div>

                  {selMajor.research_direction ? (
                    <div className="kyv3-soft-note" style={{ marginBottom: 12 }}>
                      研究方向：{selMajor.research_direction}
                    </div>
                  ) : null}

                  <div className="kyv3-major-section-title">初试科目</div>
                  {selSubjects.length ? (
                    <div className="kyv3-subject-chips">
                      {selSubjects.map((s, i) => (
                        <span key={`${s.code || ''}-${s.name}-${i}`} className="kyv3-subject-chip">
                          {s.code ? <code>{s.code}</code> : null}
                          {s.name}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="kyv3-soft-note">暂无初试科目信息。</p>
                  )}

                  {selReferences ? (
                    <div className="kyv3-reference">
                      <b>参考书 · </b>{selReferences}
                    </div>
                  ) : (
                    <div className="kyv3-reference">暂无参考书信息。</div>
                  )}

                  {majorAdmission ? (
                    <div className="kyv3-major-admissions">
                      {[
                        ['拟录取', majorAdmission.admit_count],
                        ['进复试', majorAdmission.retest_count],
                        ['录取均分', majorAdmission.admit_avg_score],
                        ['复录比', majorAdmission.retest_ratio],
                      ].map(([label, value]) => (
                        <div key={label} className="kyv3-mini-stat">
                          <b>{value ?? '—'}</b>
                          <span>{label}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="kyv3-soft-note" style={{ marginTop: 14 }}>暂无该专业的录取汇总数据。</p>
                  )}
                </div>
              ) : null}
            </div>
          )}
        </Card>
      ) : null}

      {tab === 'scores' ? (
        <Card>
          <CardHead
            icon={<FileText size={17} />}
            title={`历年分数${scores.length ? `（${scores.length}）` : ''}`}
            sub="数据来源：掌上考研（聚合）。总分为该专业复试（院）线，红色 ↗N 为高于国家线的分差。"
          />
          {scoreRangeOption ? (
            <div style={{ marginBottom: 18 }}>
              <EChart option={scoreRangeOption} style={{ height: isMobile ? 250 : 310 }} emptyText="暂无院线数据" />
            </div>
          ) : null}

          {scores.length === 0 ? (
            <Empty
              icon={<BarChart3 size={26} />}
              title="暂无分数线数据"
              text="掌上考研暂未收录该校复试线，或该校暂未公布。"
            />
          ) : (
            <>
              <div className="kyv3-score-toolbar">
                <span className="kyv3-filter-label">年份</span>
                {scoreYears.map((y) => (
                  <Chip key={y} active={activeScoreYear === y} onClick={() => setScoreYear(y)}>{y}</Chip>
                ))}
                <span className="kyv3-score-toolbar__divider" aria-hidden="true" />
                {[{ v: '', label: '全部' }, { v: '专业型', label: '专业型' }, { v: '学术型', label: '学术型' }].map((o) => (
                  <Chip key={o.label} active={scoreDegree === o.v} onClick={() => setScoreDegree(o.v)}>{o.label}</Chip>
                ))}
                <span className="kyv3-score-toolbar__count">共 {filteredScores.length} 个专业</span>
              </div>

              <div className="v3-table-wrap kyv3-table-wrap">
                <table className="v3-table">
                  <thead>
                    <tr>
                      {['名称', '代码', '招生院系', ...SCORE_FIELDS.map((f) => f.label), '备注'].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredScores.map((s, i) => {
                      const diff = s.diff_total != null
                        ? Number(s.diff_total)
                        : (s.total_line != null && s.national_line != null
                          ? Number(s.total_line) - Number(s.national_line)
                          : null)
                      return (
                        <tr key={s.source_id || i}>
                          <td>
                            <span className="kyv3-score-major">
                              {s.major_name || '—'}
                              {s.degree_type ? <Badge tone="outline">{s.degree_type}</Badge> : null}
                            </span>
                          </td>
                          <td className="is-code">{s.major_code || '—'}</td>
                          <td>{s.depart_name || '—'}</td>
                          <td className="is-total">
                            <strong>{s.total_line ?? '—'}</strong>
                            {diff != null && Number.isFinite(diff) && diff > 0 ? (
                              <span className="kyv3-diff-up" title={`高于国家线 ${diff} 分`}>↗{diff}</span>
                            ) : null}
                            {diff === 0 ? <span className="kyv3-diff-flat">持平</span> : null}
                            {diff != null && diff < 0 ? (
                              <span className="kyv3-diff-down" title={`低于国家线 ${Math.abs(diff)} 分`}>↓{Math.abs(diff)}</span>
                            ) : null}
                          </td>
                          {SCORE_FIELDS.filter((f) => f.key !== 'total_line').map((f) => (
                            <td key={f.key}>{s[f.key] ?? '—'}</td>
                          ))}
                          <td className="is-note">{s.note || s.special_remark || '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {filteredScores.length === 0 ? (
                <div className="kyv3-inline-empty">
                  {activeScoreYear} 年暂无{scoreDegree || ''}分数线记录。
                </div>
              ) : null}

              <p className="kyv3-soft-note" style={{ marginTop: 12 }}>
                说明：总分 / 单科线为该校该专业的复试基本线；国家线差值由掌上考研给出，具体以院校研究生院官网公布为准。
              </p>
            </>
          )}
        </Card>
      ) : null}

      {tab === 'admissions' ? (
        <>
          {histOption && latestAdmRows.length ? (
            <Card>
              <CardHead
                icon={<BarChart3 size={17} />}
                title={`2026 拟录取分析${hist.year ? `（${hist.year}）` : ''}`}
                sub="逐人录取总分分布 · 来源于 27 考研择校宝典（txkyer.cn），与招生数据同源"
              />
              {hist ? (
                <div className="kyv3-chart-block" style={{ marginBottom: 18 }}>
                  <h3>录取总分分布（{hist.count} 人，最低 {hist.min} · 最高 {hist.max}）</h3>
                  <EChart option={histOption} style={{ height: isMobile ? 260 : 300 }} emptyText="暂无分数明细" />
                </div>
              ) : null}
              {latestAdmRows.length ? (
                <div className="v3-table-wrap kyv3-table-wrap">
                  <table className="v3-table">
                    <thead>
                      <tr>
                        {['专业', '进复试', '拟录取', '复录比', '录取最高', '录取最低', '录取中位', '录取均分', '专业课最高', '专业课最低', '专业课均分', '数学均分', '来源'].map((h) => (
                          <th key={h}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {latestAdmRows.map((a, i) => {
                        const meta = sourceMeta(a.data_source)
                        const e = a.extra || {}
                        const cell = (v) => (v != null && v !== '' && Number.isFinite(Number(v)) ? Number(v) : '—')
                        return (
                          <tr key={`${a.year || ''}-${a.major_code || ''}-${a.major_name || ''}-${i}`}>
                            <td>
                              <span className="kyv3-admission-major">
                                {a.major_code ? <code>{a.major_code}</code> : null}
                                {a.major_name || '—'}
                              </span>
                            </td>
                            <td>{a.retest_count ?? '—'}</td>
                            <td>{a.admit_count ?? '—'}</td>
                            <td>{a.retest_ratio ?? '—'}</td>
                            <td>{cell(e.admit_max)}</td>
                            <td>{cell(e.admit_min)}</td>
                            <td>{cell(e.admit_mid)}</td>
                            <td>{cell(e.admit_avg)}</td>
                            <td>{cell(e.course_max)}</td>
                            <td>{cell(e.course_min)}</td>
                            <td>{cell(e.course_avg)}</td>
                            <td>{cell(e.math_avg)}</td>
                            <td>
                              <Badge tone={meta.tone} title={a.data_source ? `原始来源：${a.data_source}` : '来源未标注'}>
                                {meta.label}
                              </Badge>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </Card>
          ) : null}

          <Card>
          <CardHead
            icon={<BarChart3 size={17} />}
            title={`招生数据${admissions.length ? `（${admissions.length}）` : ''}`}
            sub="进线人数 / 录取人数 / 进面均分 / 数学均分 / 复录比均为第三方聚合口径"
          />

          {majorAvgOption ? (
            <div className="kyv3-chart-block" style={{ marginBottom: 18 }}>
              <h3>各专业均分对比（{latestAdmYear ?? '—'} 年，按拟录取排序前 20）</h3>
              <p className="kyv3-soft-note">聚合口径：同专业多方向取平均；缺数据显示为空。</p>
              <EChart option={majorAvgOption} style={{ height: isMobile ? 320 : 380 }} emptyText="暂无招生数据" />
            </div>
          ) : null}

          <QualityNote />

          {admissions.length === 0 ? (
            <Empty
              icon={<BarChart3 size={26} />}
              title="暂无招生数据"
              text="该校暂未收录进线、录取与均分数据。"
            />
          ) : (
            <>
              <div className="v3-table-wrap kyv3-table-wrap">
                <table className="v3-table">
                  <thead>
                    <tr>
                      {['年份', '专业', ...ADMISSION_FIELDS.map((f) => f.label), '来源'].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {admissions.map((a, i) => {
                      const meta = sourceMeta(a.data_source)
                      return (
                        <tr key={`${a.year || ''}-${a.major_code || ''}-${a.major_name || ''}-${i}`}>
                          <td>{a.year ?? '—'}</td>
                          <td>
                            <span className="kyv3-admission-major">
                              {a.major_code ? <code>{a.major_code}</code> : null}
                              {a.major_name || '—'}
                            </span>
                          </td>
                          {ADMISSION_FIELDS.map((f) => {
                            const has = a[f.key] !== null && a[f.key] !== undefined && a[f.key] !== ''
                            return (
                              <td key={f.key}>
                                <span className="kyv3-data-cell">
                                  {has ? a[f.key] : '—'}
                                  {f.kind !== 'ratio' && has ? <SourceDot source={a.data_source} /> : null}
                                </span>
                              </td>
                            )
                          })}
                          <td>
                            <Badge tone={meta.tone} title={a.data_source ? `原始来源：${a.data_source}` : '来源未标注'}>
                              {meta.label}
                            </Badge>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p className="kyv3-soft-note" style={{ marginTop: 12 }}>
                圆点提示数据来源分档：绿色为官方、金色为聚合、灰色为未核验。复录比不挂来源角标。
              </p>
            </>
          )}
        </Card>
        </>
      ) : null}

      {tab === 'notices' ? (
        <Card>
          <div className="kyv3-notice-head">
            <CardHead
              icon={<FileText size={17} />}
              title={`公告文章（${notices.length}）`}
              sub="来源：院校研究生院官网公告列表；点标题打开原文。"
            />
            {isAdmin ? (
              <Button
                variant="outline"
                size="sm"
                icon={<RefreshCw size={14} />}
                onClick={crawlNotices}
                loading={crawling}
              >
                {crawling ? '爬取中…' : '立即爬取本校公告'}
              </Button>
            ) : null}
          </div>
          {notices.length ? (
            <div className="kyv3-notice-list">
              {notices.map((n) => (
                <a key={n.id} href={n.url} target="_blank" rel="noreferrer" className="kyv3-notice-row">
                  <span className="kyv3-notice-main">
                    <span className="kyv3-notice-dot" aria-hidden="true">●</span>
                    <span className="kyv3-notice-title" title={n.title}>{n.title}</span>
                    {n.notice_type ? <Badge tone="outline">{n.notice_type}</Badge> : null}
                  </span>
                  <span className="kyv3-notice-date">{n.publish_date || ''}</span>
                </a>
              ))}
            </div>
          ) : (
            <Empty
              icon={<FileText size={26} />}
              title="暂无公告"
              text="还没有采集到该校公告，可点击「立即爬取本校公告」再试。"
            />
          )}
        </Card>
      ) : null}

      {cmpIds.length > 0 ? (
        <div className="kyv3-compare-bar">
          <span className="kyv3-compare-bar__info">
            <ListChecks size={15} /> 对比清单 <b>{cmpIds.length}</b> / {MAX_CMP} 所
          </span>
          <span className="kyv3-compare-bar__actions">
            <Button variant="text" size="sm" onClick={clearCompare}>清空</Button>
            <Button
              size="sm"
              onClick={() => navigate('/kaoyan/compare')}
              disabled={cmpIds.length < 2}
              trailingIcon={<ArrowRight size={14} />}
            >
              前往对比
            </Button>
          </span>
        </div>
      ) : null}
    </div>
  )
}
