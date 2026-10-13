import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { kaoyanApi } from '../api/kaoyanApi'
import { request } from '../api/client'
import EChart from '../components/EChart'
import { useThemeTokens } from '../components/themeTokens'
import { toast, Empty } from '../components/UI'
import useStore from '../store/useStore'
import { resolveExamDate } from '../utils/exam'
import { examSubjectText } from '../utils/kaoyanFields'
import './KaoyanSchools.css'

/* ==========================================================================
   院校数据库（V11 对标 txkyer 择校数据平台）
   --------------------------------------------------------------------------
   数据口径（后端已升级，无需前端 join）：
     - /schools 列表项自带聚合字段：college_count / major_count / retest_count /
       admit_count / retest_ratio / admit_avg_score / major_avg_score / heat / star，
       旧的「scatter 按校名 join」补数逻辑已删除（按名 join 本身也不可靠）。
     - 热度榜 TOP10 直连 /analysis/hot，不再用拟招生人数代理热度。
     - 排序走后端 sort 参数（热度/拟录取/复录比/录取均分/名称），切换即重新拉取。
   所有空值一律渲染「—」，前端不臆造数字。
   ========================================================================== */

/* 语料可靠度徽标：口径 = 专业初试「专业课」名精确匹配知识库 documents.subject
   （后端 services/major_coverage.py，公共课数学/英语/政治不参与匹配）。
   未覆盖只代表"库里没有同名学科的文档"，不等于答不了，所以文案用「未覆盖」。 */
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

/* 排序选项：key 与后端 /schools?sort= 取值一一对应 */
const SORTS = [
  { key: 'heat', label: '热度' },
  { key: 'admit', label: '拟录取' },
  { key: 'ratio', label: '复录比' },
  { key: 'avg', label: '录取均分' },
  { key: 'name', label: '名称' },
]

/* 多考试倒计时的初试日期来自 utils/exam（后端 Goal → 本地设置 → 未配置）。
   这里原先硬编码 2026-12-19 与四六级 2026-12-12，同一应用会出现两套"还剩 X 天"。
   LEGACY_SEEDED_IDS 只用于清理旧版本自动写进 localStorage 的那两条假日期。 */
const LEGACY_SEEDED_IDS = new Set(['kaoyan27', 'cet'])

/* 倒计时：返回 {days, h, m, s} */
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

/* 省份名归一化：库内同时存在「广东省 / 广东 / 广西壮族自治区」等写法，
   筛选与聚合前统一去掉行政后缀，避免同省被拆成多个选项。 */
function normProvince(p) {
  if (!p) return '未知'
  return String(p)
    .replace(/(壮族|回族|维吾尔)?自治区$/, '')
    .replace(/(省|市)$/, '')
    .trim()
}

/* 层级归一化：库内 level 有 190 条为 NULL（未公开层级判定的院校）。
   空值统一映射为「未分类」，避免这批院校在任何层级筛选下都不可见。 */
export const LEVEL_UNCLASSIFIED = '未分类'
export function normLevel(l) {
  const v = String(l == null ? '' : l).trim()
  return v || LEVEL_UNCLASSIFIED
}

/* 层级选项（985 > 211 > 双一流 > 双非 为权威口径；
   「一本/二本/民办」是 2000 年代高考录取批次旧口径，教育部学科目录中无此分类，
   库内已全部清理完毕，故不再作为筛选项，避免产生恒 0 结果的死选项。 */
const LEVELS = ['985', '211', '双一流', '双非', LEVEL_UNCLASSIFIED]
/* 大区（教育部国家线分区）：直接使用后端 region 字段值，不再由省份派生 */
const REGIONS = ['A区', 'B区']
/* 院校类型：直接使用后端 type 字段值 */
const SCHOOL_TYPES = ['公办', '科研院所', '军队院校']

/* 层级 → 标签配色（「未分类」及任何未知层级统一用中性 other 样式） */
function tierClass(level) {
  if (level === '985') return 'ky-tier-985'
  if (level === '211') return 'ky-tier-211'
  if (level === '双一流') return 'ky-tier-双一流'
  if (level === '双非') return 'ky-tier-双非'
  return 'ky-tier-other'
}

/* 复录比配色：<1.2 绿（竞争友好）/ 1.2–1.8 金 / >1.8 红（竞争激烈） */
function ratioClass(r) {
  if (r == null || isNaN(r)) return ''
  if (r < 1.2) return 'ky-ratio-ok'
  if (r <= 1.8) return 'ky-ratio-warn'
  return 'ky-ratio-hot'
}
function fmtNum(v) {
  if (v == null || isNaN(v)) return '—'
  return Math.round(v * 10) / 10
}
/* 星级渲染：star=4.0 → ★★★★；半星用 ☆ 补位（如 2.5 → ★★☆） */
function starText(star) {
  if (star == null || isNaN(star)) return '—'
  const full = Math.floor(star)
  const half = star - full >= 0.5 ? 1 : 0
  return '★'.repeat(full) + '☆'.repeat(half)
}
/* 院校信息列：学院数 / 专业方向数，任一缺失整体显示 — */
function collegeInfo(s) {
  if (s.college_count == null && s.major_count == null) return '—'
  return `${s.college_count ?? '—'}学院/${s.major_count ?? '—'}方向`
}

/* 拉取全部院校（后端单页上限 100，循环翻页直到取完）。
   全量拉取是为了支撑后端不支持的三件事：省份下拉选项、随机抽一所、
   以及前端即时筛选（region/type 用后端字段值比对，口径与后端一致）。
   排序仍由后端 sort 参数决定。 */
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
    if (page > 20) break // 安全阀
  }
  return out
}

export default function KaoyanSchools() {
  const T = useThemeTokens()
  const navigate = useNavigate()

  /* ---- 数据加载态 ---- */
  const [rows, setRows] = useState([])          // 全量院校（/schools 自带聚合字段）
  const [hotList, setHotList] = useState([])    // 热度榜 TOP10（/analysis/hot）
  const [analysis, setAnalysis] = useState(null) // 数据分析聚合（/analysis/dashboard）
  const [analysisError, setAnalysisError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sort, setSort] = useState('heat')      // 后端 sort 参数，默认热度
  const [covMap, setCovMap] = useState(null)     // 语料覆盖 school_id → {majors, covered}

  /* ---- 筛选（draft→apply，对齐参考件交互） ----
     数值筛选：录取均分 / 复录比 范围（min~max，空表示不限制） */
  const emptyFilters = { region: '', level: '', type: '', province: '', only0854: false, keyword: '',
    numAdmitMin: '', numAdmitMax: '', numRatioMin: '', numRatioMax: '',
    numRetestMin: '', numEnrollMin: '' }
  const [draft, setDraft] = useState(emptyFilters)
  const [filters, setFilters] = useState(emptyFilters)
  const [page, setPage] = useState(1)

  /* ---- 收藏 / 对比 / 随机高亮 ---- */
  const [favs, setFavs] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem(FAV_KEY) || '[]')) } catch { return new Set() }
  })
  const [cmpSet, setCmpSet] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem(CMP_KEY) || '[]')) } catch { return new Set() }
  })
  const [hlId, setHlId] = useState(null)

  /* ---- V10: 多考试倒计时（localStorage） ---- */
  const [now, setNow] = useState(Date.now())
  const [exams, setExams] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(EXAM_KEY) || 'null')
      if (Array.isArray(saved)) {
        // 只留用户自己添加的（id 形如 u_<ts>）；旧版本在这里自动播种过写死的日期，
        // 那些条目必须清掉，否则删了常量也删不掉 localStorage 里的旧值。
        return saved.filter((e) => e && e.date && !LEGACY_SEEDED_IDS.has(e.id))
      }
    } catch {}
    return []
  })

  /* 主考试日期走 utils/exam 的单一口径：后端 Goal → 本地设置 → 未配置（渲染空态） */
  const cd = useStore((s) => s.countdown)
  const settingExamDate = useStore((s) => s.settings.examDate)
  const mainExamDate = resolveExamDate(cd?.exam_date, settingExamDate)
  const cdList = useMemo(() => {
    if (!mainExamDate) return exams
    return [{
      id: '__main',
      name: `考研初试${cd?.is_default ? '（12/21 预估，可在设置修改）' : ''}`,
      date: `${mainExamDate}T08:30:00+08:00`,
      main: true,
    }, ...exams]
  }, [exams, mainExamDate, cd])
  const [showAddExam, setShowAddExam] = useState(false)
  const [newExam, setNewExam] = useState({ name: '', date: '' })

  /* ---- 院校专业方向展开行（按需懒加载） ---- */
  const [expandedId, setExpandedId] = useState(null)
  const [majorsMap, setMajorsMap] = useState({})   // id -> [major]
  const [majorsLoading, setMajorsLoading] = useState(null) // id

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  useEffect(() => { try { localStorage.setItem(EXAM_KEY, JSON.stringify(exams)) } catch {} }, [exams])

  const addExam = () => {
    if (!newExam.name.trim() || !newExam.date) { toast('请填写考试名称与日期'); return }
    setExams((prev) => [...prev, { id: `u_${Date.now()}`, name: newExam.name.trim(), date: newExam.date, main: false }])
    setNewExam({ name: '', date: '' })
    setShowAddExam(false)
    toast('已添加考试倒计时')
  }
  const removeExam = (id) => setExams((prev) => prev.filter((e) => e.id !== id))

  /* 展开某院校专业方向：懒加载 /schools/{id}/majors */
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
      toast('专业方向加载失败')
    } finally {
      setMajorsLoading(null)
    }
  }

  /* 主加载：sort 变化时整体重拉（排序由后端计算，前端不再二次排序）。
     dashboard / hot / 0854 集合失败不阻塞主表格，各自降级。 */
  const load = useCallback(async (sortKey) => {
    setLoading(true); setError(''); setAnalysisError('')
    try {
      const [schools, schools0854, dashboard, hot, cov] = await Promise.all([
        fetchAllSchools({ sort: sortKey }),
        fetchAllSchools({ subject_code: '0854' }).catch(() => []),
        kaoyanApi.dashboardAnalysis().catch(() => null),
        kaoyanApi.hot({ limit: 10 }).catch(() => ({ items: [] })),
        request('/quality/major-coverage').catch(() => null),
      ])
      // 0854 专项：按 id 集合标记，供复选框过滤
      const ids0854 = new Set((schools0854 || []).map((s) => s.id))
      setRows(schools.map((s) => ({ ...s, has0854: ids0854.has(s.id) })))
      setAnalysis(dashboard)
      if (!dashboard) setAnalysisError('数据分析聚合接口暂不可用，下方图表已隐藏')
      setHotList((hot && hot.items) || [])
      setCovMap((cov && cov.by_school) || {})
    } catch (e) {
      setError(e?.message || '院校数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(sort) }, [load, sort])

  /* 收藏 / 对比持久化 */
  useEffect(() => { try { localStorage.setItem(FAV_KEY, JSON.stringify([...favs])) } catch {} }, [favs])
  useEffect(() => { try { localStorage.setItem(CMP_KEY, JSON.stringify([...cmpSet])) } catch {} }, [cmpSet])

  /* ---- 省份选项（归一化后去重） ---- */
  const provinceOptions = useMemo(() => {
    const set = new Map()
    rows.forEach((r) => {
      const np = normProvince(r.province)
      if (!set.has(np)) set.set(np, r.province)
    })
    return [...set.keys()].sort((a, b) => a.localeCompare(b, 'zh'))
  }, [rows])

  /* ---- 过滤（排序保持后端返回顺序，不前端重排） ---- */
  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (filters.region && (r.region || '') !== filters.region) return false
      if (filters.level && normLevel(r.level) !== filters.level) return false
      if (filters.type && (r.type || '') !== filters.type) return false
      if (filters.province && normProvince(r.province) !== filters.province) return false
      if (filters.only0854 && !r.has0854) return false
      if (filters.keyword && !(r.name || '').toLowerCase().includes(filters.keyword.trim().toLowerCase())) return false
      // 数值筛选：录取均分范围
      const avg = r.admit_avg_score
      if (filters.numAdmitMin !== '' && (avg == null || avg < Number(filters.numAdmitMin))) return false
      if (filters.numAdmitMax !== '' && (avg == null || avg > Number(filters.numAdmitMax))) return false
      // V17 数值筛选：进复试≥ / 拟录取≥（txkyer 详细数据表口径）
      const retest = r.retest_count ?? r.retest
      if (filters.numRetestMin !== '' && (retest == null || retest < Number(filters.numRetestMin))) return false
      const enroll = r.admit_count ?? r.admit
      if (filters.numEnrollMin !== '' && (enroll == null || enroll < Number(filters.numEnrollMin))) return false
      // 数值筛选：复录比范围
      const ratio = r.retest_ratio
      if (filters.numRatioMin !== '' && (ratio == null || ratio < Number(filters.numRatioMin))) return false
      if (filters.numRatioMax !== '' && (ratio == null || ratio > Number(filters.numRatioMax))) return false
      return true
    })
  }, [rows, filters])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const curPage = Math.min(page, totalPages)
  const current = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE)

  const applyFilters = () => { setFilters({ ...draft }); setPage(1) }
  const resetFilters = () => { setDraft(emptyFilters); setFilters(emptyFilters); setPage(1) }
  const changeSort = (key) => {
    if (key === sort) return
    setSort(key)
    setPage(1) // 换排序后页码语义变化，回到第一页
  }

  const toggleFav = (id) => setFavs((prev) => {
    const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
  })
  const toggleCmp = (id) => setCmpSet((prev) => {
    const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
  })

  /* 随机抽一所：从当前过滤结果里随机选，跳转到其所在页并高亮 */
  const randomPick = () => {
    if (!filtered.length) return
    const s = filtered[Math.floor(Math.random() * filtered.length)]
    const idx = filtered.indexOf(s)
    setPage(Math.floor(idx / PAGE_SIZE) + 1)
    setHlId(s.id)
    toast(`已为你抽中：${s.name}`)
    setTimeout(() => setHlId(null), 3500)
  }

  const goCompare = () => {
    localStorage.setItem(CMP_KEY, JSON.stringify([...cmpSet]))
    navigate('/kaoyan/compare')
  }

  /* 含录取数据的院校数（口径：admit_count 非空） */
  const withAdmitCount = useMemo(() => rows.filter((r) => r.admit_count != null).length, [rows])

  /* ============================ 侧边图表（echarts） ============================
     全部改为基于 /schools 自带聚合字段统计，不再依赖 /analysis/scatter。 */
  // 1) 各省份拟录取人数（横向 bar，Top10）
  const provinceBar = useMemo(() => {
    const agg = {}
    rows.forEach((r) => {
      const p = normProvince(r.province)
      agg[p] = (agg[p] || 0) + (r.admit_count || 0)
    })
    const data = Object.entries(agg).map(([name, value]) => ({ name, value: Math.round(value) }))
      .sort((a, b) => a.value - b.value).slice(-10)
    return {
      grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
      yAxis: { type: 'category', data: data.map((d) => d.name), axisLabel: { color: T['ink-2'], fontSize: 11 } },
      series: [{ type: 'bar', data: data.map((d) => d.value), itemStyle: { color: T.accent, borderRadius: [0, 4, 4, 0] }, barWidth: 12 }],
    }
  }, [rows, T])

  // 2) 录取平均分分数段
  const scoreBuckets = useMemo(() => {
    const bands = ['<320', '320-340', '340-360', '360-380', '≥380']
    const arr = bands.map((name) => ({ name, value: 0 }))
    rows.forEach((r) => {
      const v = r.admit_avg_score
      if (v == null) return
      const i = v < 320 ? 0 : v < 340 ? 1 : v < 360 ? 2 : v < 380 ? 3 : 4
      arr[i].value++
    })
    return arr
  }, [rows])
  const scoreBar = {
    grid: { left: 8, right: 8, top: 16, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: scoreBuckets.map((b) => b.name), axisLabel: { color: T['ink-2'], fontSize: 10 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
    series: [{ type: 'bar', data: scoreBuckets.map((b) => b.value), itemStyle: { color: T.accent, borderRadius: [4, 4, 0, 0] }, barWidth: 18 }],
  }

  // 3) 复录比分布（按绿/金/红分色）
  const ratioBuckets = useMemo(() => {
    const bands = ['<1.2', '1.2-1.5', '1.5-1.8', '≥1.8']
    const arr = bands.map((name) => ({ name, value: 0 }))
    rows.forEach((r) => {
      const v = r.retest_ratio
      if (v == null) return
      const i = v < 1.2 ? 0 : v < 1.5 ? 1 : v < 1.8 ? 2 : 3
      arr[i].value++
    })
    return arr
  }, [rows])
  const ratioBar = {
    grid: { left: 8, right: 8, top: 16, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ratioBuckets.map((b) => b.name), axisLabel: { color: T['ink-2'], fontSize: 10 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
    series: [{
      type: 'bar', data: ratioBuckets.map((b, i) => ({
        value: b.value,
        itemStyle: { color: [T.green, T.gold, T.red, T.red][i], borderRadius: [4, 4, 0, 0] },
      })), barWidth: 18,
    }],
  }

  // 4) 院校层级分布（环形图）
  const levelPie = useMemo(() => {
    const agg = { '985': 0, '211': 0, '双一流': 0, '双非': 0, [LEVEL_UNCLASSIFIED]: 0 }
    rows.forEach((r) => { agg[normLevel(r.level)]++ })
    const palette = [T.red, T.accent, T.violet, T.gold, T['ink-3']]
    return {
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: T['ink-2'], fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['42%', '66%'], center: ['50%', '42%'],
        label: { show: false },
        data: Object.entries(agg).filter(([, v]) => v > 0).map(([name, value], i) => ({ name, value, itemStyle: { color: palette[i] } })),
      }],
    }
  }, [rows, T])

  /* ============================ V9 数据分析区块（/analysis/dashboard 实时聚合） ============================ */
  const dash = analysis || {}

  // 1) 热门业务课二 TOP15（横向 bar）
  const major2Bar = useMemo(() => {
    const data = dash.major2_top || []
    return {
      grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
      yAxis: { type: 'category', data: data.map((d) => d.name), axisLabel: { color: T['ink-2'], fontSize: 11 } },
      series: [{ type: 'bar', data: data.map((d) => d.count), itemStyle: { color: T.violet, borderRadius: [0, 4, 4, 0] }, barWidth: 12 }],
    }
  }, [dash.major2_top, T])

  // 2) 数学科目分布（横向 bar）
  const mathBar = useMemo(() => {
    const data = dash.subject_math || []
    return {
      grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
      yAxis: { type: 'category', data: data.map((d) => d.name), axisLabel: { color: T['ink-2'], fontSize: 11 } },
      series: [{ type: 'bar', data: data.map((d) => d.count), itemStyle: { color: T.accent, borderRadius: [0, 4, 4, 0] }, barWidth: 12 }],
    }
  }, [dash.subject_math, T])

  // 3) 英语科目分布（横向 bar）
  const englishBar = useMemo(() => {
    const data = dash.subject_english || []
    return {
      grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
      yAxis: { type: 'category', data: data.map((d) => d.name), axisLabel: { color: T['ink-2'], fontSize: 11 } },
      series: [{ type: 'bar', data: data.map((d) => d.count), itemStyle: { color: T.green, borderRadius: [0, 4, 4, 0] }, barWidth: 12 }],
    }
  }, [dash.subject_english, T])

  // 4) 各专业复试/录取平均分对比 TOP10（双系列横向 bar）
  const majorScoreBar = useMemo(() => {
    const list = (dash.major_comparison || []).slice(0, 10).reverse()
    return {
      grid: { left: 8, right: 24, top: 24, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { top: 0, textStyle: { color: T['ink-2'], fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
      yAxis: { type: 'category', data: list.map((d) => d.major), axisLabel: { color: T['ink-2'], fontSize: 10 } },
      series: [
        { name: '复试均分', type: 'bar', data: list.map((d) => d.major_avg), itemStyle: { color: T.accent, borderRadius: [0, 3, 3, 0] }, barWidth: 10 },
        { name: '录取均分', type: 'bar', data: list.map((d) => d.admit_avg), itemStyle: { color: T.gold, borderRadius: [0, 3, 3, 0] }, barWidth: 10 },
      ],
    }
  }, [dash.major_comparison, T])

  // 5) 各专业招生人数占比 TOP10（环形图）
  const majorPie = useMemo(() => {
    const list = (dash.major_comparison || []).slice(0, 10)
    const total = list.reduce((s, d) => s + (d.enroll_count || 0), 0)
    const palette = [T.red, T.accent, T.violet, T.gold, T.green, T['ink-3'], '#5B8FF9', '#61DDAA', '#65789B', '#F6BD16']
    return {
      tooltip: { trigger: 'item', formatter: (p) => `${p.name}<br/>${p.value} 人（${total ? ((p.value / total) * 100).toFixed(1) : 0}%）` },
      legend: { bottom: 0, textStyle: { color: T['ink-2'], fontSize: 10 }, itemWidth: 10, itemHeight: 10, type: 'scroll' },
      series: [{
        type: 'pie', radius: ['38%', '62%'], center: ['50%', '42%'], label: { show: false },
        data: list.map((d, i) => ({ name: d.major, value: d.enroll_count || 0, itemStyle: { color: palette[i % palette.length] } })),
      }],
    }
  }, [dash.major_comparison, T])

  // 6) 各学院招生情况 TOP10（横向 bar）
  const collegeBar = useMemo(() => {
    const data = (dash.college_enroll || []).slice(0, 10).reverse()
    return {
      grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
      yAxis: { type: 'category', data: data.map((d) => d.college), axisLabel: { color: T['ink-2'], fontSize: 10 } },
      series: [{ type: 'bar', data: data.map((d) => d.enroll_count), itemStyle: { color: T.red, borderRadius: [0, 4, 4, 0] }, barWidth: 12 }],
    }
  }, [dash.college_enroll, T])

  // 7) 专业课分数分布（纵向 bar）
  const scoreDistBar = useMemo(() => {
    const data = dash.major_score_dist || []
    return {
      grid: { left: 8, right: 8, top: 16, bottom: 4, containLabel: true },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: data.map((d) => d.band), axisLabel: { color: T['ink-2'], fontSize: 10 } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
      series: [{ type: 'bar', data: data.map((d) => d.count), itemStyle: { color: T.gold, borderRadius: [4, 4, 0, 0] }, barWidth: 18 }],
    }
  }, [dash.major_score_dist, T])

  /* ============================ V12 新增：分数分布直方图三联（总分/专业课/数学） ============================
     优先使用后端 /analysis/dashboard 新增的 total_score_dist / major_score_dist / math_score_dist
     （基于 kaoyan_scorelines.total_line / major_avg_score / math_line 实时分箱）；
     后端旧版本未返回时，前端基于 /schools 自带字段（admit_avg_score/major_avg_score）兜底计算，
     数学分数分布无兜底来源则显示提示。 */
  const buildHist = (bands, counts, color) => ({
    grid: { left: 8, right: 8, top: 20, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: bands, axisLabel: { color: T['ink-2'], fontSize: 10 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: T.line } }, axisLabel: { color: T['ink-3'] } },
    series: [{ type: 'bar', data: counts, itemStyle: { color, borderRadius: [4, 4, 0, 0] }, barWidth: 20 }],
  })

  // 总分分布：优先后端 total_score_dist，兜底 rows.admit_avg_score 分箱
  const totalHist = useMemo(() => {
    const TOTAL_BANDS = ['<300', '300-320', '320-340', '340-360', '360-380', '≥380']
    if (Array.isArray(dash.total_score_dist) && dash.total_score_dist.length) {
      return {
        bands: dash.total_score_dist.map((d) => d.band),
        counts: dash.total_score_dist.map((d) => d.count),
        fromBackend: true,
      }
    }
    const arr = TOTAL_BANDS.map(() => 0)
    rows.forEach((r) => {
      const v = r.admit_avg_score
      if (v == null) return
      const i = v < 300 ? 0 : v < 320 ? 1 : v < 340 ? 2 : v < 360 ? 3 : v < 380 ? 4 : 5
      arr[i]++
    })
    return { bands: TOTAL_BANDS, counts: arr, fromBackend: false }
  }, [dash.total_score_dist, rows])

  // 专业课分布：优先后端 major_score_dist，兜底 rows.major_avg_score 分箱
  const majorHist = useMemo(() => {
    const MAJOR_BANDS = ['<90', '90-100', '100-110', '110-120', '120-130', '130-140', '≥140']
    if (Array.isArray(dash.major_score_dist) && dash.major_score_dist.length) {
      return {
        bands: dash.major_score_dist.map((d) => d.band),
        counts: dash.major_score_dist.map((d) => d.count),
        fromBackend: true,
      }
    }
    const arr = MAJOR_BANDS.map(() => 0)
    rows.forEach((r) => {
      const v = r.major_avg_score
      if (v == null) return
      const i = v < 90 ? 0 : v < 100 ? 1 : v < 110 ? 2 : v < 120 ? 3 : v < 130 ? 4 : v < 140 ? 5 : 6
      arr[i]++
    })
    return { bands: MAJOR_BANDS, counts: arr, fromBackend: false }
  }, [dash.major_score_dist, rows])

  // 数学分布：仅后端 math_score_dist（无兜底来源）
  const mathHist = useMemo(() => {
    if (Array.isArray(dash.math_score_dist) && dash.math_score_dist.length) {
      return {
        bands: dash.math_score_dist.map((d) => d.band),
        counts: dash.math_score_dist.map((d) => d.count),
        fromBackend: true,
      }
    }
    return null
  }, [dash.math_score_dist])

  const totalHistBar = useMemo(
    () => buildHist(totalHist.bands, totalHist.counts, T.accent),
    [totalHist, T]
  )
  const majorHistBar = useMemo(
    () => buildHist(majorHist.bands, majorHist.counts, T.gold),
    [majorHist, T]
  )
  const mathHistBar = useMemo(
    () => (mathHist ? buildHist(mathHist.bands, mathHist.counts, T.green) : null),
    [mathHist, T]
  )

  /* ============================ 渲染 ============================ */
  if (loading) return (
    <div className="ky-page">
      <div className="ky-loading"><span className="table-spinner" /> 院校数据加载中…</div>
    </div>
  )

  if (error) return (
    <div className="ky-page">
      <div className="ky-error">
        <Empty
          icon="⚠"
          title="院校数据加载失败"
          desc={error}
          action={<button className="btn primary" onClick={() => load(sort)}>重试</button>}
        />
      </div>
    </div>
  )

  return (
    <div className="ky-page">
      {/* 页头 + 我方既有能力入口 */}
      <div className="ky-head">
        <div>
          <h1>院校数据库</h1>
          <p className="ky-head-sub">共收录 {rows.length} 所招生单位 · {withAdmitCount} 所含招生/录取数据</p>
        </div>
        <div className="ky-entry-row">
          <Link to="/kaoyan/assistant" className="btn ghost">AI 择校问答</Link>
          <Link to="/kaoyan/recommend" className="btn ghost">智能推荐</Link>
          <Link to="/kaoyan/compare" className="btn ghost">院校对比</Link>
        </div>
      </div>

      {/* 数据来源提示条 */}
      <div className="ky-source-note">
        <span>ⓘ</span>
        <span><b>数据说明：</b>本页招生/录取/复录比均为第三方聚合数据，未经院校官方逐条核验，仅供择校参考；正式信息以目标院校研究生院官网为准。</span>
      </div>

      {/* V10: 多考试倒计时 */}
      <div className="ky-countdown-strip">
        {cdList.length === 0 && (
          <div className="ky-cd-card">
            <div className="ky-cd-name">倒计时未配置</div>
            <div className="ky-cd-pill">—</div>
            <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 4 }}>去「设置」填初试日期，或点右侧添加考试</div>
          </div>
        )}
        {cdList.map((e) => {
          const p = countdownParts(e.date, now)
          return (
            <div key={e.id} className={`ky-cd-card ${e.main ? 'main' : ''}`}>
              <div className="ky-cd-name">{e.name}</div>
              {e.main ? (
                <>
                  <div className="ky-cd-big">{p.days}<span> 天</span></div>
                  <div className="ky-cd-clock">{pad2(p.h)}:{pad2(p.m)}:{pad2(p.s)}</div>
                </>
              ) : (
                <div className="ky-cd-pill">{p.days}<span> 天</span></div>
              )}
              {!e.main && (
                <button className="ky-cd-del" onClick={() => removeExam(e.id)} aria-label={`删除 ${e.name}`}>×</button>
              )}
            </div>
          )
        })}
        {showAddExam ? (
          <div className="ky-cd-addbox">
            <input className="input" placeholder="考试名称（如：考研初试）" value={newExam.name}
              onChange={(ev) => setNewExam({ ...newExam, name: ev.target.value })} />
            <input className="input" type="date" value={newExam.date}
              onChange={(ev) => setNewExam({ ...newExam, date: ev.target.value ? ev.target.value + 'T00:00:00+08:00' : '' })} />
            <div className="ky-cd-add-actions">
              <button className="btn primary mini" onClick={addExam}>添加</button>
              <button className="btn ghost mini" onClick={() => setShowAddExam(false)}>取消</button>
            </div>
          </div>
        ) : (
          <button className="ky-cd-add" onClick={() => setShowAddExam(true)}>＋ 添加考试</button>
        )}
      </div>

      {/* 热度榜 TOP10：直连 /analysis/hot，热度为后端派生指标 */}
      {hotList.length > 0 && (
        <div className="ky-hot-card">
          <div className="ky-hot-head">
            <h2 className="ky-list-title">🔥 热度榜 TOP10</h2>
            <span className="ky-hot-note">热度取自后端 /api/kaoyan/analysis/hot</span>
          </div>
          <ol className="ky-hot-grid">
            {hotList.map((s, i) => (
              <li key={s.id ?? i} className="ky-hot-item">
                <span className={`ky-hot-rank ${i < 3 ? `top${i + 1}` : ''}`}>{s.rank ?? i + 1}</span>
                <span className="ky-badge sm">{(s.name || '?').slice(0, 1)}</span>
                <div className="ky-hot-info">
                  <Link to={`/kaoyan/schools/${s.id || 0}`} className="ky-hot-name">{s.name}</Link>
                  <div className="ky-hot-meta">
                    <span className={`ky-tier ${tierClass(s.level)}`}>{normLevel(s.level)}</span>
                    <span className="ky-hot-num">热度 {s.heat != null ? Math.round(s.heat) : '—'}</span>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* V9: 数据分析（/analysis/dashboard 实时聚合，无前端硬编码） */}
      {analysis && (
        <div className="ky-analysis-block" style={{ marginTop: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <h2 className="ky-list-title" style={{ margin: 0 }}>数据分析</h2>
            <span className="ky-hot-note">全部图表数据实时取自后端聚合接口 /api/kaoyan/analysis/dashboard</span>
          </div>
          {analysisError && <div className="ky-chart-note" style={{ color: 'var(--danger, #e74c3c)', marginBottom: 10 }}>{analysisError}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 14 }}>
            <div className="ky-chart-card">
              <h3 className="ky-chart-title">热门业务课二 TOP15</h3>
              <EChart option={major2Bar} style={{ height: 280 }} />
            </div>
            <div className="ky-chart-card">
              <h3 className="ky-chart-title">数学科目分布</h3>
              <EChart option={mathBar} style={{ height: 220 }} />
            </div>
            <div className="ky-chart-card">
              <h3 className="ky-chart-title">英语科目分布</h3>
              <EChart option={englishBar} style={{ height: 220 }} />
            </div>
            <div className="ky-chart-card">
              <h3 className="ky-chart-title">各专业复试/录取平均分对比 TOP10</h3>
              <EChart option={majorScoreBar} style={{ height: 280 }} />
            </div>
            <div className="ky-chart-card">
              <h3 className="ky-chart-title">各专业招生人数占比 TOP10</h3>
              <EChart option={majorPie} style={{ height: 260 }} />
            </div>
            <div className="ky-chart-card">
              <h3 className="ky-chart-title">各学院招生情况 TOP10</h3>
              <EChart option={collegeBar} style={{ height: 260 }} />
            </div>
            <div className="ky-chart-card">
              <h3 className="ky-chart-title">专业课分数分布</h3>
              <EChart option={scoreDistBar} style={{ height: 220 }} />
            </div>
            {/* V12 新增：分数分布直方图三联（总分/专业课/数学） */}
            <div className="ky-chart-card ky-hist-card">
              <h3 className="ky-chart-title">分数分布直方图（总分 / 专业课 / 数学）</h3>
              <div className="ky-hist-grid">
                <div className="ky-hist-item">
                  <div className="ky-hist-sub">{totalHist.fromBackend ? '总分（总分线）' : '总分（录取均分兜底）'}</div>
                  <EChart option={totalHistBar} style={{ height: 210 }} />
                </div>
                <div className="ky-hist-item">
                  <div className="ky-hist-sub">{majorHist.fromBackend ? '专业课（专业课均分）' : '专业课（专业课均分兜底）'}</div>
                  <EChart option={majorHistBar} style={{ height: 210 }} />
                </div>
                <div className="ky-hist-item">
                  <div className="ky-hist-sub">数学（数学线）</div>
                  {mathHistBar ? (
                    <EChart option={mathHistBar} style={{ height: 210 }} />
                  ) : (
                    <div className="ky-hist-empty">数学分数分布数据待后端聚合接口刷新后展示</div>
                  )}
                </div>
              </div>
              <div className="ky-chart-note">数据库无逐考生原始分数，基于现有分数线/均分数据按分数段统计（后端 /api/kaoyan/analysis/dashboard 实时聚合，前端兜底计算标注为「兜底」）</div>
            </div>
          </div>
        </div>
      )}

      {/* 多维筛选 */}
      <div className="ky-filterbar">
        <div className="ky-filter-grid">
          <label className="ky-field">
            <span className="ky-field-label">地区</span>
            <select className="ky-select" value={draft.region} onChange={(e) => setDraft({ ...draft, region: e.target.value })}>
              <option value="">全部地区</option>
              {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>

          <label className="ky-field">
            <span className="ky-field-label">院校层级</span>
            <select className="ky-select" value={draft.level} onChange={(e) => setDraft({ ...draft, level: e.target.value })}>
              <option value="">全部层级</option>
              {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>

          <label className="ky-field">
            <span className="ky-field-label">院校类型</span>
            <select className="ky-select" value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
              <option value="">全部类型</option>
              {SCHOOL_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>

          <label className="ky-field">
            <span className="ky-field-label">省份</span>
            <select className="ky-select" value={draft.province} onChange={(e) => setDraft({ ...draft, province: e.target.value })}>
              <option value="">全部省份</option>
              {provinceOptions.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>

          <label className="ky-field">
            <span className="ky-field-label">录取均分（范围）</span>
            <span className="ky-range">
              <input className="ky-range-input" type="number" placeholder="最低" min="0" max="500"
                value={draft.numAdmitMin} onChange={(e) => setDraft({ ...draft, numAdmitMin: e.target.value })} />
              <span className="ky-range-sep">~</span>
              <input className="ky-range-input" type="number" placeholder="最高" min="0" max="500"
                value={draft.numAdmitMax} onChange={(e) => setDraft({ ...draft, numAdmitMax: e.target.value })} />
            </span>
          </label>

          <label className="ky-field">
            <span className="ky-field-label">复录比（范围）</span>
            <span className="ky-range">
              <input className="ky-range-input" type="number" placeholder="最低" min="0" max="10" step="0.1"
                value={draft.numRatioMin} onChange={(e) => setDraft({ ...draft, numRatioMin: e.target.value })} />
              <input className="ky-range-input" type="number" min="0" placeholder="进复试≥" style={{ width: 90 }}
                value={draft.numRetestMin} onChange={(e) => setDraft({ ...draft, numRetestMin: e.target.value })} />
              <input className="ky-range-input" type="number" min="0" placeholder="拟录取≥" style={{ width: 90 }}
                value={draft.numEnrollMin} onChange={(e) => setDraft({ ...draft, numEnrollMin: e.target.value })} />
              <span className="ky-range-sep">~</span>
              <input className="ky-range-input" type="number" placeholder="最高" min="0" max="10" step="0.1"
                value={draft.numRatioMax} onChange={(e) => setDraft({ ...draft, numRatioMax: e.target.value })} />
            </span>
          </label>

          <div className="ky-checks">
            <label className="ky-check">
              <input type="checkbox" checked={draft.only0854} onChange={(e) => setDraft({ ...draft, only0854: e.target.checked })} />
              0854 电子信息专项
            </label>
          </div>

          <div className="ky-filter-actions">
            <button className="btn primary" onClick={applyFilters}>应用筛选</button>
            <button className="btn ghost" onClick={resetFilters}>重置</button>
          </div>
        </div>
      </div>

      {/* 主区：表格 + 侧边图表 */}
      <div className="ky-main-grid">
        <div className="ky-list-card">
          <div className="ky-list-head">
            <h2 className="ky-list-title">
              学校列表<span className="ky-list-count">共 {filtered.length} 所</span>
            </h2>
            <div className="ky-list-tools">
              <span className="ky-search">
                <span className="ky-search-icon">⌕</span>
                <input
                  type="search" placeholder="搜索院校名称…"
                  value={draft.keyword}
                  onChange={(e) => setDraft({ ...draft, keyword: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') applyFilters() }}
                />
              </span>
              <button className="btn primary" onClick={applyFilters}>搜索</button>
            </div>
          </div>

          {/* 排序：切换后按新 sort 重拉 /schools（排序逻辑在后端） */}
          <div className="ky-list-tools" style={{ marginBottom: 10 }}>
            <span className="ky-hot-note">排序</span>
            {SORTS.map((o) => (
              <button
                key={o.key}
                className={`btn mini ${sort === o.key ? 'primary' : 'ghost'}`}
                onClick={() => changeSort(o.key)}
                aria-pressed={sort === o.key}
              >
                {o.label}
              </button>
            ))}
          </div>

          <div className="ky-card-grid">
            {current.map((s) => {
              const isOpen = expandedId === s.id
              const majors = majorsMap[s.id]
              const yzLink = `https://yz.chsi.com.cn/sch/search.do?q=${encodeURIComponent(s.name || '')}`
              return (
                <div key={s.id} className={`ky-school-card ${hlId === s.id ? 'ky-card-hl' : ''}`}>
                  <div className="ky-card-head">
                    <span className="ky-badge">{(s.name || '?').slice(0, 1)}</span>
                    <div className="ky-card-titlebox">
                      <Link to={`/kaoyan/schools/${s.id}`} className="ky-card-name">{s.name}</Link>
                      <span className="ky-card-sub">{normProvince(s.province)} · {collegeInfo(s)}</span>
                    </div>
                    <div className="ky-card-tools">
                      <button className={`ky-fav ${favs.has(s.id) ? 'on' : ''}`} onClick={() => toggleFav(s.id)} aria-label={favs.has(s.id) ? `取消收藏 ${s.name}` : `收藏 ${s.name}`}>★</button>
                      <input type="checkbox" className="ky-cmp" checked={cmpSet.has(s.id)} onChange={() => toggleCmp(s.id)} aria-label={`对比 ${s.name}`} />
                    </div>
                  </div>

                  <div className="ky-card-tags">
                    <span className={`ky-tier ${tierClass(s.level)}`}>{normLevel(s.level)}</span>
                    {s.region && <span className="ky-tier ky-tier-other">{s.region}</span>}
                    {s.type && <span className="ky-tier ky-tier-other">{s.type}</span>}
                    {s.star != null && (
                      <span className="ky-card-star" title={`星级 ${s.star}`} style={{ color: 'var(--gold)' }}>{starText(s.star)}</span>
                    )}
                    {s.has0854 && <span className="ky-card-0854">0854 专项</span>}
                    {covMap && (() => {
                      const c = covMap[s.id]
                      /* 库内只有 223/577 所院校有专业方向记录；没有记录时不渲染徽标
                         （那是"招生数据缺失"，不是"语料缺失"，标出来只会变成 354 个同色噪声）。 */
                      if (!c || !c.majors) return null
                      return (
                        <span className={`ky-cov ky-cov-${c.covered > 0 ? 'covered' : 'uncovered'}`}
                          title={`初试专业课名精确匹配知识库文档学科：${c.majors} 个专业方向中 ${c.covered} 个有语料`}>
                          语料覆盖 {c.covered}/{c.majors}
                        </span>
                      )
                    })()}
                  </div>

                  <div className="ky-card-metrics">
                    <div className="ky-metric">
                      <span className="ky-metric-v">{fmtNum(s.retest_count)}</span>
                      <span className="ky-metric-k">进复试</span>
                    </div>
                    <div className="ky-metric">
                      <span className="ky-metric-v">{fmtNum(s.admit_count)}</span>
                      <span className="ky-metric-k">拟录取</span>
                    </div>
                    <div className="ky-metric">
                      <span className={`ky-metric-v ky-ratio ${ratioClass(s.retest_ratio)}`}>{fmtNum(s.retest_ratio)}</span>
                      <span className="ky-metric-k">复录比</span>
                    </div>
                    <div className="ky-metric">
                      <span className="ky-metric-v">{fmtNum(s.admit_avg_score)}</span>
                      <span className="ky-metric-k">录取均分</span>
                    </div>
                    <div className="ky-metric">
                      <span className="ky-metric-v">{fmtNum(s.major_avg_score)}</span>
                      <span className="ky-metric-k">专业课均分</span>
                    </div>
                    <div className="ky-metric">
                      <span className="ky-metric-v">{s.heat != null ? Math.round(s.heat) : '—'}</span>
                      <span className="ky-metric-k">热度</span>
                    </div>
                  </div>

                  <div className="ky-card-links">
                    <Link to={`/kaoyan/schools/${s.id}`} className="ky-link">院校详情</Link>
                    {s.official_url && (
                      <a href={s.official_url} target="_blank" rel="noopener noreferrer" className="ky-link">院校官网</a>
                    )}
                    <a href={yzLink} target="_blank" rel="noopener noreferrer" className="ky-link">研招网</a>
                    <button className="ky-expand-btn ky-link-expand" onClick={() => toggleExpand(s.id)} aria-label={isOpen ? '收起专业方向' : '展开专业方向'}>
                      {isOpen ? '收起专业方向 ▾' : '专业方向 ▸'}
                    </button>
                  </div>

                  {isOpen && (
                    <div className="ky-card-expand">
                      <div className="ky-expand-title">专业方向 / 招生科目
                        <span className="ky-expand-hint">徽标＝知识库语料覆盖（未覆盖＝库里没有同名科目语料，不代表答不了）</span>
                      </div>
                      {majorsLoading === s.id ? (
                        <div className="ky-expand-empty">加载专业方向中…</div>
                      ) : majors && majors.length ? (
                        <ul className="ky-major-list">
                          {majors.map((m) => (
                            <li key={m.id}>
                              <span className="ky-major-code">{m.code}</span>
                              <span className="ky-major-name">{m.name}</span>
                              {m.exam_subjects && <span className="ky-major-exam">{examSubjectText(m.exam_subjects)}</span>}
                              {m.kb_coverage && m.kb_coverage.state !== 'public_only' && (
                                <span
                                  className={`ky-cov ky-cov-${m.kb_coverage.state}`}
                                  title={covTitle(m.kb_coverage)}
                                >
                                  {COV_LABEL[m.kb_coverage.state](m.kb_coverage)}
                                  {m.kb_coverage.avg_confidence != null
                                    && m.kb_coverage.avg_confidence < 0.4 && ' · 置信低'}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <div className="ky-expand-empty">暂无专业方向数据</div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
            {current.length === 0 && (
              <div className="ky-card-empty"><Empty icon="🗂" title="没有符合条件的院校" desc="试试放宽地区 / 层级 / 关键词，或点击「随机抽一所」" /></div>
            )}
          </div>

          {/* 分页 */}
          <nav className="ky-pager" aria-label="分页">
            <button disabled={curPage <= 1} onClick={() => setPage(curPage - 1)}>上一页</button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).slice(0, 7).map((n) => (
              <button key={n} className={n === curPage ? 'cur' : ''} onClick={() => setPage(n)}>{n}</button>
            ))}
            {totalPages > 7 && <span className="ky-pager-info">…</span>}
            <button disabled={curPage >= totalPages} onClick={() => setPage(curPage + 1)}>下一页</button>
            <span className="ky-pager-info">第 {curPage}/{totalPages} 页 · 共 {filtered.length} 所</span>
          </nav>

          {/* 对比浮动条 */}
          {cmpSet.size > 0 && (
            <div className="ky-compare-bar">
              <span className="info">已选 {cmpSet.size} 所院校用于对比</span>
              <span className="btns">
                <button className="btn ghost" onClick={() => setCmpSet(new Set())}>清空</button>
                <button className="btn solid" onClick={goCompare} disabled={cmpSet.size < 2}>开始对比（≥2）</button>
              </span>
            </div>
          )}
        </div>

        {/* 侧边图表 + 随机/收藏 */}
        <aside className="ky-side">
          <div className="ky-side-actions">
            <button className="ky-side-btn random" onClick={randomPick}>
              <span className="ico">🎲</span><span className="lbl">随机抽一所</span>
            </button>
            <div className="ky-side-btn favcount">
              <span className="ico">★</span><span className="lbl">目标院校 {favs.size}</span>
            </div>
          </div>

          <div className="ky-chart-card">
            <h3 className="ky-chart-title">各省份拟录取人数 Top10</h3>
            <EChart option={provinceBar} style={{ height: 260 }} />
          </div>

          <div className="ky-chart-card">
            <h3 className="ky-chart-title">录取平均分分数段</h3>
            <EChart option={scoreBar} style={{ height: 180 }} />
          </div>

          <div className="ky-chart-card">
            <h3 className="ky-chart-title">复录比分布</h3>
            <EChart option={ratioBar} style={{ height: 180 }} />
            <div className="ky-chart-note">绿 &lt;1.2 友好 · 金 1.2–1.8 适中 · 红 ≥1.8 激烈</div>
          </div>

          <div className="ky-chart-card">
            <h3 className="ky-chart-title">院校层级分布</h3>
            <EChart option={levelPie} style={{ height: 200 }} />
          </div>
        </aside>
      </div>
    </div>
  )
}

/* 字段口径（V11，全部直出 /api/kaoyan/schools，无前端 join）：
   - 层级 level / 省份 province / 校名 name / logo_url：/schools 直出；logo_url 多为空 → 首字色块占位。
   - 院校信息 college_count + major_count、进复试 retest_count、拟录取 admit_count、
     复录比 retest_ratio、录取均分 admit_avg_score、专业课均分 major_avg_score、
     热度 heat、星级 star：均为后端聚合字段，空值渲染 —。
   - 热度榜 TOP10：/analysis/hot?limit=10（rank/id/name/level/heat）。
   - 地区 region：后端无字段，由省份派生。
   - 收藏：后端无收藏接口 → localStorage 本地持久化。
   - 0854 专项：通过 /schools?subject_code=0854 取 id 集合，前端过滤。 */
