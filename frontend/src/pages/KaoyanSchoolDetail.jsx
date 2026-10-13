import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { kaoyanApi } from '../api/kaoyanApi'
import EChart from '../components/EChart'
import { DataCell, SourceBadge, DataQualityNote } from '../components/SourceBadge'
import { useThemeTokens } from '../components/themeTokens'
import { SCORE_FIELDS, ADMISSION_FIELDS } from '../utils/kaoyanFields'
import { toast } from '../components/UI'

/* ============================================================
   院校详情（第四轮重设计，参考掌上考研/txkyer 的布局模式）：
   - Hero 头部：校名 + 层级徽章 + 省份/城市 + 关注按钮 + 官网入口
   - 汇总统计条：学院数/专业方向/进复试/拟录取/复录比/录取均分/专业课均分/热度
   - 标签页：院校概况 / 招生计划(专业方向) / 历年分数 / 招生数据
   - 历年分数：总分带「超国家线 ↗N」红色差值标注
   - 招生数据：各专业录取均分/专业课均分对比图（EChart 分组柱状）
   视觉沿用平台设计令牌（暖纸底/墨绿/金），不照搬参考站橙色。
   ============================================================ */

// D2: 省级行政中心坐标（用于地图定位标点）
const PROVINCE_COORDS = {
  '北京': [116.4, 39.9], '天津': [117.2, 39.13], '河北': [114.5, 38.04],
  '山西': [112.55, 37.87], '内蒙古': [111.75, 40.84], '辽宁': [123.43, 41.8],
  '吉林': [125.32, 43.9], '黑龙江': [126.63, 45.75], '上海': [121.47, 31.23],
  '江苏': [118.78, 32.04], '浙江': [120.15, 30.28], '安徽': [117.28, 31.86],
  '福建': [119.3, 26.08], '江西': [115.89, 28.68], '山东': [117.0, 36.65],
  '河南': [113.65, 34.76], '湖北': [114.3, 30.6], '湖南': [112.98, 28.19],
  '广东': [113.28, 23.13], '广西': [108.32, 22.82], '海南': [110.35, 20.02],
  '重庆': [106.55, 29.56], '四川': [104.07, 30.67], '贵州': [106.71, 26.57],
  '云南': [102.71, 25.04], '西藏': [91.13, 29.66], '陕西': [108.95, 34.27],
  '甘肃': [103.82, 36.06], '青海': [101.78, 36.62], '宁夏': [106.28, 38.47],
  '新疆': [87.62, 43.82], '台湾': [121.5, 25.03], '香港': [114.17, 22.28],
  '澳门': [113.55, 22.2],
}

/* 层级徽章：颜色区分（参考站用红色985/普通标签），用平台令牌。
   level 为空的院校（库内 190 条）显示中性「未分类」徽章，而不是直接不显示——
   否则用户无法区分「没定层级」和「样式没渲染出来」。 */
function LevelBadge({ level }) {
  const lv = String(level || '').trim() || '未分类'
  const style = {
    '985': { background: 'var(--red, #c0392b)', color: '#fff' },
    '211': { background: 'var(--accent)', color: 'var(--surface)' },
    '双一流': { background: 'var(--green)', color: 'var(--surface)' },
    '双非': { background: 'var(--surface-3)', color: 'var(--ink-2)' },
  }[lv] || { background: 'var(--surface-3)', color: 'var(--ink-2)' }
  return <em style={{ ...style, fontStyle: 'normal', padding: '2px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600 }}>{lv}</em>
}

const FAV_KEY = 'kaoyan-fav-schools'
const loadFavs = () => { try { return JSON.parse(localStorage.getItem(FAV_KEY) || '{}') } catch { return {} } }

export default function KaoyanSchoolDetail() {
  const { id } = useParams()
  const [school, setSchool] = useState(null)
  const [majors, setMajors] = useState([])
  // M3-4: 招生计划聚合（院系→专业→拟招人数→考试科目），单次调用避免两次拼接
  const [enrollPlan, setEnrollPlan] = useState(null)
  const [scores, setScores] = useState([])
  const [admissions, setAdmissions] = useState([])
  const [notices, setNotices] = useState([])
  const [reforms, setReforms] = useState([])   // V10 改考事件
  const [insight, setInsight] = useState(null) // V10 分数全景
  const [crawling, setCrawling] = useState(false) // V16 公告爬取中
  const [selMajorId, setSelMajorId] = useState(null) // V17 招生计划选中专业
  const [tab, setTab] = useState('overview')
  const [favs, setFavs] = useState(loadFavs)
  // V7.0 P0-3：Canvas 图表必须用真实色值，不能直接写 var(--x)
  const T = useThemeTokens()

  useEffect(() => {
    Promise.all([
      kaoyanApi.schoolDetail(id),
      kaoyanApi.schoolMajors(id),
      kaoyanApi.schoolScores(id),
      kaoyanApi.schoolAdmissions(id),
    ]).then(([s, m, sc, ad]) => {
      setSchool(s); setMajors(m); setScores(sc); setAdmissions(ad)
    }).catch(() => toast('院校详情加载失败'))
    // M3-4: 招生计划聚合独立加载（含拟招人数/考试科目），失败静默回退到 /majors 渲染
    kaoyanApi.schoolEnrollmentPlan(id)
      .then(setEnrollPlan)
      .catch(() => setEnrollPlan(null))
    // 公告独立加载（新表可能未建，失败静默——无数据时标签页隐藏）
    kaoyanApi.schoolNotices(id, { limit: 50 })
      .then(setNotices)
      .catch(() => setNotices([]))
    // V10: 改考雷达事件 + 分数全景（失败静默，不影响主数据）
    kaoyanApi.reforms({ school_id: id, limit: 20 })
      .then(setReforms)
      .catch(() => setReforms([]))
    kaoyanApi.scoreDetail(id)
      .then(setInsight)
      .catch(() => setInsight(null))
  }, [id])

  if (!school) return <div style={{ padding: '48px', textAlign: 'center' }}>加载中…</div>

  const toggleFav = () => {
    const next = { ...favs }
    if (next[school.id]) { delete next[school.id] } else { next[school.id] = { name: school.name, level: school.level } }
    setFavs(next)
    try { localStorage.setItem(FAV_KEY, JSON.stringify(next)) } catch { /* 隐私模式 */ }
    toast(next[school.id] ? '已关注该院校' : '已取消关注')
  }

  /* 分数线趋势图（V7.0 P0-2：只画可信字段，复试线/国家线为不可信列已下线） */
  const scoreChartOption = scores.length > 0 ? {
    tooltip: { trigger: 'axis' },
    legend: { data: SCORE_FIELDS.map(f => f.label), textStyle: { color: T['ink-2'] } },
    xAxis: { type: 'category', data: scores.map(s => s.year).reverse(), axisLabel: { color: T['ink-3'] } },
    yAxis: { type: 'value', name: '分数', axisLabel: { color: T['ink-3'] } },
    series: SCORE_FIELDS.map((f, i) => ({
      name: f.label,
      type: 'line',
      data: scores.map(s => s[f.key]).reverse(),
      smooth: true,
      itemStyle: { color: [T.accent, T.gold][i % 2] },
    })),
  } : null

  /* 各专业均分对比（参考站「各专业复试/录取平均分对比」）：
     取最近有数据年份，按专业聚合；录取均分/专业课均分双系列 */
  const latestAdmYear = admissions.length ? Math.max(...admissions.map(a => a.year || 0)) : null
  const admByMajor = {}
  ;(admissions.filter(a => a.year === latestAdmYear) || []).forEach((a) => {
    const key = `${a.major_code || ''} ${a.major_name || ''}`.trim() || '未标注'
    if (!admByMajor[key]) admByMajor[key] = { admit_avg: [], major_avg: [], retest: 0, admit: 0 }
    if (a.admit_avg_score != null) admByMajor[key].admit_avg.push(a.admit_avg_score)
    if (a.major_avg_score != null) admByMajor[key].major_avg.push(a.major_avg_score)
    admByMajor[key].retest += a.retest_count || 0
    admByMajor[key].admit += a.admit_count || 0
  })
  const majorRows = Object.entries(admByMajor)
    .map(([k, v]) => ({
      name: k,
      admitAvg: v.admit_avg.length ? +(v.admit_avg.reduce((x, y) => x + y, 0) / v.admit_avg.length).toFixed(1) : null,
      majorAvg: v.major_avg.length ? +(v.major_avg.reduce((x, y) => x + y, 0) / v.major_avg.length).toFixed(1) : null,
      retest: v.retest, admit: v.admit,
    }))
    .sort((a, b) => (b.admit || 0) - (a.admit || 0))
    .slice(0, 20) // 图表最多 20 个专业，避免轴标签挤爆
  const majorAvgChart = majorRows.length ? {
    tooltip: { trigger: 'axis' },
    legend: { data: ['录取均分', '专业课均分'], textStyle: { color: T['ink-2'] } },
    grid: { bottom: 90 },
    xAxis: { type: 'category', data: majorRows.map(r => r.name), axisLabel: { color: T['ink-3'], rotate: 38, fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', name: '分数', axisLabel: { color: T['ink-3'] } },
    series: [
      { name: '录取均分', type: 'bar', data: majorRows.map(r => r.admitAvg), itemStyle: { color: T.gold } },
      { name: '专业课均分', type: 'bar', data: majorRows.map(r => r.majorAvg), itemStyle: { color: T.accent } },
    ],
  } : null

  /* 汇总统计条：与列表页同口径（/schools/{id} 复用后端聚合），缺数据显示 — */
  const stats = [
    { label: '学院数', value: school.college_count, color: 'inherit' },
    { label: '专业方向', value: school.major_count, color: 'inherit' },
    { label: `进复试${school.year ? `(${school.year})` : ''}`, value: school.retest_count, color: 'inherit' },
    { label: '拟录取', value: school.admit_count, color: 'inherit' },
    { label: '复录比', value: school.retest_ratio, color: 'var(--gold)' },
    { label: '录取均分', value: school.admit_avg_score, color: 'var(--red, #c0392b)' },
    { label: '专业课均分', value: school.major_avg_score, color: 'var(--green)' },
    { label: `热度 ${school.star ? '·' + '★'.repeat(Math.round(school.star)) : ''}`, value: school.heat, color: 'inherit' },
  ]

  const tabs = [
    { key: 'overview', label: '院校概况' },
    { key: 'majors', label: `招生计划 (${majors.length})` },
    { key: 'scores', label: '历年分数' },
    { key: 'admissions', label: '招生数据' },
    // 参考站「公告文章」标签：采集到数据才显示（无数据不摆空壳）
    ...(notices.length ? [{ key: 'notices', label: `公告文章 (${notices.length})` }] : []),
  ]

  return (
    <div className="ky-page">
      <Link to="/kaoyan/schools" style={{ color: 'var(--ink-3)', textDecoration: 'none', marginBottom: '12px', display: 'inline-block' }}>
        ← 返回院校库
      </Link>

      {/* Hero 头部：校名 + 徽章 + 位置 + 关注（参考站院校卡模式） */}
      <div style={{
        padding: '20px 24px', borderRadius: 14, marginBottom: 14,
        background: 'linear-gradient(135deg, var(--surface-2), var(--surface))',
        border: '1px solid var(--line)', display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap',
      }}>
        {/* logo 缺失时用校名首字占位，不伪造图片 */}
        {school.logo_url
          ? <img src={school.logo_url} alt="" style={{ width: 64, height: 64, borderRadius: '50%', objectFit: 'cover', border: '2px solid var(--line)' }} />
          : <div style={{ width: 64, height: 64, borderRadius: '50%', background: 'var(--accent)', color: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28, fontWeight: 700 }}>{(school.name || '校')[0]}</div>}
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0, fontSize: 24 }}>{school.name}</h1>
            <LevelBadge level={school.level} />
            {school.province && <em style={{ fontStyle: 'normal', fontSize: 12, padding: '2px 10px', borderRadius: 999, background: 'var(--surface-3)', color: 'var(--ink-2)' }}>📍 {school.province}{school.city ? ` · ${school.city}` : ''}</em>}
          </div>
          <div style={{ marginTop: 6, fontSize: 13, color: 'var(--ink-3)', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            {school.official_url && <a href={school.official_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>研究生院官网 →</a>}
            <span>数据来源：{school.data_source || '—'}</span>
          </div>
        </div>
        <button
          onClick={toggleFav}
          className="btn ghost"
          style={{ borderColor: favs[school.id] ? 'var(--gold)' : 'var(--line)', color: favs[school.id] ? 'var(--gold)' : 'var(--ink-2)' }}>
          {favs[school.id] ? '★ 已关注' : '☆ 关注'}
        </button>
      </div>

      {/* V10: 改考提醒横幅（有改考/停招等事件时置顶警示） */}
      {reforms.length > 0 && (
        <div style={{
          marginBottom: 18, padding: '14px 18px', borderRadius: 12,
          background: 'linear-gradient(135deg, rgba(239,68,68,.10), rgba(245,158,11,.06))',
          border: '1px solid rgba(239,68,68,.25)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 16 }}>🚨</span>
            <strong style={{ fontSize: 15, color: '#b91c1c' }}>院校变动雷达 · {reforms.length} 条与该校相关的变动</strong>
          </div>
          <div style={{ display: 'grid', gap: 6 }}>
            {reforms.slice(0, 3).map(r => {
              const color = r.change_type === '停招' ? '#b91c1c'
                : r.change_type === '改考科目' ? '#d97706' : 'var(--accent)'
              return (
                <div key={r.id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', fontSize: 13 }}>
                  <em style={{ fontStyle: 'normal', padding: '1px 8px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: color, color: '#fff' }}>{r.change_type}</em>
                  <span style={{ color: 'var(--ink-2)' }}>{r.title}</span>
                  {r.year ? <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{r.year}</span> : null}
                  {r.url && <a href={r.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: 'var(--accent)' }}>原文 ↗</a>}
                </div>
              )
            })}
          </div>
          {reforms.length > 3 && <div style={{ marginTop: 6, fontSize: 12, color: 'var(--ink-3)' }}>还有 {reforms.length - 3} 条 →「通知中心 · 改考雷达」</div>}
        </div>
      )}

      {/* V10: 分数全景洞察条（趋势 + 国家线差值，数据来自 score-detail 聚合） */}
      {insight && insight.trends && (insight.trends.admit_avg_trend !== '数据不足' || insight.line_vs_national) && (
        <div style={{
          display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'stretch',
          marginBottom: 18,
        }}>
          <div style={{
            flex: '1 1 220px', padding: '14px 18px', borderRadius: 12,
            background: 'var(--surface)', border: '1px solid var(--line)',
          }}>
            <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 4 }}>录取均分趋势</div>
            <div style={{ fontSize: 17, fontWeight: 700 }}>
              {insight.trends.admit_avg_trend === '持续上涨' && <span style={{ color: '#b45309' }}>📈 持续上涨</span>}
              {insight.trends.admit_avg_trend === '持续下降' && <span style={{ color: '#15803d' }}>📉 持续下降</span>}
              {insight.trends.admit_avg_trend === '波动较大' && <span style={{ color: 'var(--accent)' }}>〰️ 波动较大</span>}
              {insight.trends.admit_avg_trend === '基本平稳' && <span style={{ color: 'var(--ink-2)' }}>➖ 基本平稳</span>}
              {insight.trends.admit_avg_trend === '数据不足' && <span style={{ color: 'var(--ink-3)' }}>数据不足</span>}
            </div>
            {insight.admissions_detail?.[0]?.admit_avg_score && (
              <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4 }}>
                最近年录取均分 {insight.admissions_detail[0].admit_avg_score} 分
              </div>
            )}
          </div>
          {insight.line_vs_national && (
            <div style={{
              flex: '1 1 220px', padding: '14px 18px', borderRadius: 12,
              background: 'var(--surface)', border: '1px solid var(--line)',
            }}>
              <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 4 }}>复试线 vs 国家线（{insight.line_vs_national.year}）</div>
              <div style={{ fontSize: 17, fontWeight: 700 }}>
                <span style={{ color: insight.line_vs_national.diff >= 0 ? '#b91c1c' : '#15803d' }}>
                  {insight.line_vs_national.diff >= 0 ? '↑' : '↓'} 超国家线 {Math.abs(insight.line_vs_national.diff)} 分
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4 }}>
                校线 {insight.line_vs_national.total_line} / 国家线 {insight.line_vs_national.national_line}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 汇总统计条（参考站 8 指标横排模式；星级为层级派生，热度为派生代理） */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))',
        gap: 1, background: 'var(--line)', border: '1px solid var(--line)',
        borderRadius: 12, overflow: 'hidden', marginBottom: 18,
      }}>
        {stats.map(s => (
          <div key={s.label} style={{ background: 'var(--surface)', padding: '12px 8px', textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: 19, fontWeight: 700, color: s.color }}>{s.value ?? '—'}</div>
          </div>
        ))}
      </div>

      {/* 标签页 */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '20px', borderBottom: '2px solid var(--line)' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{
              padding: '10px 16px', border: 'none', cursor: 'pointer',
              background: tab === t.key ? 'var(--accent)' : 'transparent',
              color: tab === t.key ? 'var(--surface)' : 'var(--ink-2)',
              borderRadius: '8px 8px 0 0', fontSize: '14px',
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div>
          {school.intro && <p style={{ lineHeight: '1.8', marginBottom: '16px' }}>{school.intro}</p>}
          {!school.intro && <p style={{ lineHeight: 1.8, color: 'var(--ink-3)', marginBottom: 16 }}>暂无院校简介（采集到 official_url 的院校可后续自动补全）。</p>}
          {/* D2: 地图定位 — 内嵌中国地图标点 + 百度地图外链 */}
          {school.province && (
            <div style={{ marginTop: '12px' }}>
              <h3 style={{ marginBottom: '8px' }}>院校所在地（{school.province}{school.city || ''}）</h3>
              <EChart
                option={{
                  tooltip: { trigger: 'item', formatter: (p) => (p.name ? `${p.name}<br/>${p.value ? (Array.isArray(p.value) ? p.value[2] || '' : '') : ''}` : '') },
                  geo: {
                    map: 'china', roam: false, zoom: 1.1,
                    label: { show: false },
                    itemStyle: { areaColor: T['surface-2'], borderColor: T['ink-3'] },
                    emphasis: { itemStyle: { areaColor: T['surface-3'] } },
                  },
                  series: [
                    {
                      name: '院校省份', type: 'map', map: 'china', roam: false, zoom: 1.1,
                      data: [{ name: school.province, value: 1 }],
                      label: { show: true, color: T.surface, fontSize: 10 },
                      itemStyle: { areaColor: T.accent, borderColor: T.surface },
                      select: { disabled: true },
                    },
                    {
                      name: '院校定位', type: 'scatter', coordinateSystem: 'geo',
                      data: [{ name: school.name, value: [...(PROVINCE_COORDS[school.province] || [105, 35]), school.name] }],
                      symbolSize: 16, itemStyle: { color: T.red },
                      label: { show: true, formatter: (p) => p.name || '', position: 'right', color: T.ink, fontSize: 12, fontWeight: 600 },
                    },
                  ],
                }}
                style={{ height: '380px', marginBottom: '12px' }}
              />
              <a href={`https://map.baidu.com/search/${encodeURIComponent(school.name)}`}
                target="_blank" rel="noreferrer"
                style={{ color: 'var(--accent)', fontSize: '14px' }}>
                在百度地图查看精确位置 →
              </a>
            </div>
          )}
          {scoreChartOption && (
            <div style={{ marginTop: '24px' }}>
              <h3 style={{ marginBottom: '12px' }}>分数线趋势</h3>
              <EChart option={scoreChartOption} style={{ height: '360px' }} />
            </div>
          )}
        </div>
      )}

      {tab === 'majors' && (
        <div>
          <p style={{ fontSize: 12.5, color: 'var(--ink-3)', margin: '0 0 12px' }}>
            按参考站「招生计划」模式（M3-4 单次聚合）：院系 → 专业 → 拟招人数 → 初试科目。
            {enrollPlan && enrollPlan.year ? ` 招生年度：${enrollPlan.year}。` : ''}
            {(!enrollPlan || (enrollPlan.items || []).length === 0) && ' 暂无招生计划聚合数据，以下为专业方向明细。'}
          </p>
          {majors.length === 0 ? (
            <div style={{ padding: '24px', color: 'var(--ink-3)' }}>暂无专业数据</div>
          ) : (() => {
            const selId = selMajorId ?? majors[0]?.id ?? null
            const sel = majors.find(m => m.id === selId) || majors[0]
            const ad = admissions.find(a => a.major_id === sel.id)
            const planItem = (enrollPlan?.items || []).find(
              it => (it.major_code && it.major_code === sel.code) || it.major === sel.name
            )
            const subjChips = (s) => Array.isArray(s) ? s : (s ? [s] : [])
            return (
              <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 14, alignItems: 'start' }}>
                {/* 左：专业列表（V17 参考站布局） */}
                <div style={{ maxHeight: 520, overflow: 'auto', border: '1px solid var(--line)', borderRadius: 12, background: 'var(--surface)' }}>
                  {majors.map(m => (
                    <button key={m.id} onClick={() => setSelMajorId(m.id)}
                      style={{ display: 'block', width: '100%', textAlign: 'left', padding: '11px 14px',
                        border: 'none', borderBottom: '1px solid var(--line)', cursor: 'pointer',
                        background: m.id === sel?.id ? 'var(--accent-soft, rgba(43,90,158,.08))' : 'transparent' }}>
                      <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>{m.code || '—'}</div>
                      <div style={{ fontSize: 13.5, fontWeight: m.id === sel?.id ? 700 : 500, color: 'var(--ink)' }}>{m.name}</div>
                    </button>
                  ))}
                </div>
                {/* 右：专业详情（方向 / 初试科目 / 参考书 / 录取数据） */}
                {sel && (
                  <div style={{ border: '1px solid var(--line)', borderRadius: 12, padding: 18, background: 'var(--surface)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
                      <strong style={{ fontSize: 17 }}>{sel.name}</strong>
                      <code style={{ fontSize: 12, color: 'var(--accent)' }}>{sel.code}</code>
                      {sel.degree_type && <em style={{ fontStyle: 'normal', fontSize: 12, padding: '1px 10px', borderRadius: 999, background: 'var(--surface-3)', color: 'var(--ink-2)' }}>{sel.degree_type}</em>}
                      {planItem?.enroll_count != null && <em style={{ fontStyle: 'normal', fontSize: 12, padding: '1px 10px', borderRadius: 999, background: 'var(--accent-soft, rgba(43,90,158,.08))', color: 'var(--accent)' }}>拟招 {planItem.enroll_count} 人</em>}
                    </div>
                    {sel.research_direction && <div style={{ fontSize: 13, color: 'var(--ink-2)', marginBottom: 6 }}>研究方向：{sel.research_direction}</div>}
                    {subjChips(sel.exam_subjects).length > 0 && (
                      <div style={{ margin: '10px 0' }}>
                        <div style={{ fontSize: 12.5, color: 'var(--ink-3)', marginBottom: 6 }}>初试科目</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {subjChips(sel.exam_subjects).map((s, i) => (
                            <em key={i} style={{ fontStyle: 'normal', fontSize: 12.5, padding: '3px 10px', borderRadius: 8, background: 'var(--accent-soft, rgba(43,90,158,.08))', color: 'var(--accent)' }}>{s}</em>
                          ))}
                        </div>
                      </div>
                    )}
                    {sel.reference_books && (
                      <div style={{ fontSize: 13, color: 'var(--ink-2)', marginTop: 8 }}>
                        参考书：{Array.isArray(sel.reference_books) ? sel.reference_books.join('；') : sel.reference_books}
                      </div>
                    )}
                    {/* 关联录取数据（有则展示，来源 admissions） */}
                    {ad && (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginTop: 14 }}>
                        {[['拟录取', ad.admit_count], ['进复试', ad.retest_count], ['录取均分', ad.admit_avg_score], ['复录比', ad.retest_ratio]].map(([l, v]) => (
                          <div key={l} style={{ textAlign: 'center', padding: '8px 4px', borderRadius: 10, background: 'var(--surface-2, rgba(0,0,0,.03))' }}>
                            <div style={{ fontSize: 16, fontWeight: 700 }}>{v ?? '—'}</div>
                            <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>{l}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })()}
        </div>
      )}

      {tab === 'scores' && (
        <div>
          {/* 参考站模式：红色分数 = 院线与国家线的差值 */}
          <p style={{ fontSize: 12.5, color: 'var(--ink-3)', margin: '0 0 10px' }}>
            注：红色 ↗N 表示该专业院线总分高出国家线 N 分（仅在有国家线数据时显示）。
          </p>
          {scoreChartOption ? <EChart option={scoreChartOption} style={{ height: '360px', marginBottom: '20px' }} /> : null}
          <DataQualityNote fields={['politics_line', 'english_line', 'math_line', 'retest_line', 'national_line']} />
          <div className="table-container">
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--line)' }}>
                {['年份', ...SCORE_FIELDS.map(f => f.label), '来源'].map(h =>
                  <th key={h} style={{ padding: '8px', textAlign: 'left' }}>{h}</th>
                )}
              </tr>
            </thead>
            <tbody>
              {scores.map((s, i) => {
                /* 差值：仅总分列展示，>0 红色上箭头（参考站口径） */
                const diff = (s.total_line != null && s.national_line != null) ? s.total_line - s.national_line : null
                /* V16 对比去年批注：与上一年份总分线的差值（红涨绿降灰平） */
                const prev = scores[i + 1]  // scores 按年降序，i+1 即上一年
                const yoy = (s.total_line != null && prev?.total_line != null)
                  ? s.total_line - prev.total_line : null
                return (
                <tr key={i} style={{ borderBottom: '1px solid var(--line)' }}>
                  <td style={{ padding: '8px' }}>{s.year}</td>
                  <td style={{ padding: '8px' }}>
                    <DataCell value={s.total_line} record={s} badge />
                    {diff != null && diff > 0 && (
                      <span style={{ color: 'var(--red, #c0392b)', fontSize: 12, marginLeft: 4 }} title={`超国家线 ${diff} 分`}>↗{diff}</span>
                    )}
                    {yoy != null && yoy !== 0 && (
                      <span style={{
                        fontSize: 11.5, marginLeft: 6, padding: '1px 7px', borderRadius: 999,
                        color: '#fff', background: yoy > 0 ? '#c0392b' : '#15803d',
                      }} title={`较 ${prev.year} 年${yoy > 0 ? '上涨' : '下降'} ${Math.abs(yoy)} 分`}>
                        {yoy > 0 ? '↑' : '↓'}{Math.abs(yoy)} 较去年
                      </span>
                    )}
                    {yoy === 0 && (
                      <span style={{ fontSize: 11.5, marginLeft: 6, color: 'var(--ink-3)' }}>— 持平</span>
                    )}
                  </td>
                  {SCORE_FIELDS.filter(f => f.key !== 'total_line').map(f => (
                    <td key={f.key} style={{ padding: '8px' }}>
                      <DataCell value={s[f.key]} record={s} badge />
                    </td>
                  ))}
                  <td style={{ padding: '8px' }}>
                    <SourceBadge source={s.source} sourceType={s.source_type} />
                  </td>
                </tr>
              )})}
            </tbody>
          </table>
          </div>
          {scores.length === 0 && <div style={{ padding: '24px', color: 'var(--ink-3)' }}>暂无分数线数据</div>}
        </div>
      )}

      {tab === 'admissions' && (
        <div>
          {/* 各专业均分对比（参考站「各专业复试/录取平均分对比」模式） */}
          {majorAvgChart && (
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ marginBottom: 4 }}>各专业均分对比（{latestAdmYear} 年，按拟录取排序前 20）</h3>
              <p style={{ fontSize: 12, color: 'var(--ink-3)', margin: '0 0 8px' }}>聚合口径：同专业多方向取平均；缺数据显示为空。</p>
              <EChart option={majorAvgChart} style={{ height: 380 }} />
            </div>
          )}
          <DataQualityNote fields={['admit_count']} />
          <div className="table-container">
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--line)' }}>
                {['年份', '专业', ...ADMISSION_FIELDS.map(f => f.label), '来源'].map(h =>
                  <th key={h} style={{ padding: '8px', textAlign: 'left' }}>{h}</th>
                )}
              </tr>
            </thead>
            <tbody>
              {admissions.map((a, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--line)' }}>
                  <td style={{ padding: '8px' }}>{a.year}</td>
                  <td style={{ padding: '8px', fontSize: 13 }}>{a.major_code ? `${a.major_code} ` : ''}{a.major_name}</td>
                  {ADMISSION_FIELDS.map(f => (
                    <td key={f.key} style={{ padding: '8px' }}>
                      <DataCell value={a[f.key]} record={a} badge={f.kind !== 'ratio'} />
                    </td>
                  ))}
                  <td style={{ padding: '8px' }}>
                    <SourceBadge source={a.data_source} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          {admissions.length === 0 && <div style={{ padding: '24px', color: 'var(--ink-3)' }}>暂无招生数据</div>}
        </div>
      )}

      {tab === 'notices' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <p style={{ fontSize: 12.5, color: 'var(--ink-3)', margin: 0 }}>
              来源：院校研究生院官网公告列表（采集时间见数据管理页）；点标题打开原文。
            </p>
            {/* V16 随时爬取本校公告 */}
            <button className="btn sm outline" disabled={crawling}
              onClick={() => {
                setCrawling(true)
                kaoyanApi.crawlSchoolNotices(school.id)
                  .then(r => {
                    toast(r.new > 0 ? `已新增 ${r.new} 条公告（共 ${r.notices_total} 条）` : `暂无新增（共 ${r.notices_total} 条）`)
                    return kaoyanApi.schoolNotices(school.id, { limit: 50 }).then(setNotices).catch(() => {})
                  })
                  .catch(e => toast(e?.message || '爬取失败，真机联网后重试'))
                  .finally(() => setCrawling(false))
              }}>
              {crawling ? '爬取中…' : '⚡ 立即爬取本校公告'}
            </button>
          </div>
          {notices.map(n => (
            <a key={n.id} href={n.url} target="_blank" rel="noreferrer"
              style={{ display: 'flex', justifyContent: 'space-between', gap: 16, padding: '11px 4px',
                borderBottom: '1px solid var(--line)', textDecoration: 'none', color: 'var(--ink-1, inherit)' }}>
              <span style={{ display: 'flex', gap: 8, alignItems: 'baseline', minWidth: 0 }}>
                <span style={{ color: 'var(--gold)', flexShrink: 0 }}>●</span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.title}</span>
                <em style={{ fontStyle: 'normal', fontSize: 11, padding: '1px 8px', borderRadius: 999, background: 'var(--surface-3)', color: 'var(--ink-3)', flexShrink: 0 }}>{n.notice_type}</em>
              </span>
              <span style={{ color: 'var(--ink-3)', fontSize: 12.5, flexShrink: 0 }}>{n.publish_date || ''}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
