import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, AnimatedNumber, Badge, Button, Empty, IconButton, PageHeader, Skeleton, Tile,
  toastErr, toastOk,
} from '../ui'
import {
  ArrowRight, BarChart3, Compass, Database, GraduationCap, Layers, LineChart, Map,
  PieChart, RefreshCw, School, Sparkles, Target,
} from '../icons'
import '../styles/kaoyan-aux-v3.css'

const TOOLS = [
  { to: '/kaoyan/schools', label: '院校数据库', desc: '全国院校多维度筛选', icon: School },
  { to: '/kaoyan/compare', label: '院校对比', desc: '最多 5 所院校横向对比', icon: Layers },
  { to: '/kaoyan/analysis', label: '分数分析', desc: '近 5 年分数线趋势', icon: LineChart },
  { to: '/kaoyan/map', label: '区域热力图', desc: '全国各省院校分布与难度', icon: Map },
  { to: '/kaoyan/scatter', label: '招生散点图', desc: '招生人数 vs 录取均分', icon: BarChart3 },
  { to: '/kaoyan/recommend', label: '智能择校', desc: '多维权重推荐（复录比 / 均分 / 区域）', icon: Sparkles },
]

function StatTile({ icon, label, value, hint }) {
  return (
    <Tile className="v3-ky-stat">
      <span className="v3-tile__label">{icon}{label}</span>
      <span className="v3-tile__value"><AnimatedNumber value={value} /></span>
      <span className="v3-tile__hint">{hint}</span>
    </Tile>
  )
}

export default function KaoyanGuide() {
  const { isAdmin } = useAuth()
  const [stats, setStats] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [s, sub] = await Promise.all([kaoyanApi.stats(), kaoyanApi.subjects()])
      setStats(s || null)
      setSubjects(Array.isArray(sub) ? sub : Array.isArray(sub?.items) ? sub.items : [])
      return true
    } catch (e) {
      setError(e?.message || '数据加载失败')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const refresh = async () => {
    const ok = await load()
    if (ok) toastOk('择校数据已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  const totalRecords = stats
    ? (stats.school_count || 0) + (stats.major_count || 0)
      + (stats.admission_records || 0) + (stats.scoreline_records || 0)
    : 0
  const isEmpty = !loading && !error && totalRecords === 0 && subjects.length === 0
  const years = Array.isArray(stats?.years) ? stats.years : []
  const yearText = years.length
    ? (years.length > 1 ? `${years[years.length - 1]}–${years[0]}` : String(years[0]))
    : ''

  const subjectText = !loading && !error && stats
    ? (isEmpty
      ? '院校库、专业方向、招生与分数线记录尚未导入，导入后数据分析会自动可用'
      : `已收录 ${stats.school_count || 0} 所院校 · ${stats.major_count || 0} 个专业方向 · ${stats.scoreline_records || 0} 条分数线记录${yearText ? ` · 数据年份 ${yearText}` : ''}`)
    : '院校对比 · 分数趋势 · 招生分布 · 智能推荐'

  return (
    <div className="v3-stack v3-ky">
      <PageHeader
        eyebrow="KAOYAN · 择校数据中心"
        title="择校数据中心"
        sub={subjectText}
        actions={(
          <>
            <IconButton label="刷新择校数据" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading} />
            <Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">
              浏览院校库 <ArrowRight size={15} />
            </Link>
          </>
        )}
      />

      {loading ? (
        <>
          <Tile span={12} className="v3-ky-hero-skeleton"><Skeleton height={128} /></Tile>
          <div className="v3-ky-stat-grid">
            {Array.from({ length: 5 }).map((_, i) => <Tile key={i}><Skeleton height={52} /></Tile>)}
          </div>
          <div className="v3-ky-subject-grid">
            {Array.from({ length: 6 }).map((_, i) => <Tile key={i}><Skeleton height={70} /></Tile>)}
          </div>
        </>
      ) : error ? (
        <Tile span={12}>
          <Empty
            icon={<Database size={26} />}
            title="择校数据加载失败"
            text={`接口请求失败：${error}`}
            action={<Button variant="tonal" onClick={load}>重新加载</Button>}
          />
        </Tile>
      ) : isEmpty ? (
        <>
          <Tile span={12} variant="hero" className="v3-ky-hero v3-ky-hero--empty">
            <div className="v3-ky-hero__copy">
              <span className="v3-eyebrow v3-ky-hero__eyebrow"><Database size={13} /> 数据尚未导入</span>
              <h2>先把院校库装满，<br />所有分析才有意义。</h2>
              <p>
                院校库、专业方向、招生与分数线记录都来自导入的数据。当前库里还没有记录，
                导入后统计卡片、趋势图与推荐会自动读出真实数量，无需改动页面配置。
              </p>
              <div className="v3-ky-hero__actions">
                <Link className="v3-btn v3-btn--gradient" to="/kaoyan/schools">
                  浏览院校库 <ArrowRight size={15} />
                </Link>
                {isAdmin ? (
                  <Link className="v3-btn v3-btn--tonal" to="/admin/schools">去导入择校数据</Link>
                ) : null}
              </div>
              <p className="v3-ky-hero__note">
                {isAdmin
                  ? '分析工具与下方入口都依赖同一批表（院校 / 专业 / 招生 / 分数线），导入后即可使用。'
                  : '择校数据由管理员在后台导入，导入后这里会直接显示真实数量。'}
              </p>
            </div>
          </Tile>

          <section className="v3-ky-section">
            <div className="v3-ky-section__head">
              <div>
                <h2>分析工具</h2>
                <p>入口保留，数据导入后图表会按库内真实记录渲染。</p>
              </div>
            </div>
            <div className="v3-ky-tool-grid">
              {TOOLS.map((tool) => {
                const Icon = tool.icon
                return (
                  <Link key={tool.to} to={tool.to} className="v3-ky-tool">
                    <span className="v3-ky-tool__icon"><Icon size={19} /></span>
                    <span className="v3-ky-tool__copy">
                      <strong>{tool.label}</strong>
                      <em>{tool.desc}</em>
                    </span>
                    <ArrowRight size={16} className="v3-ky-tool__go" />
                  </Link>
                )
              })}
            </div>
          </section>
        </>
      ) : (
        <>
          <Tile span={12} variant="hero" className="v3-ky-hero">
            <div className="v3-ky-hero__body">
              <div className="v3-ky-hero__copy">
                <span className="v3-eyebrow v3-ky-hero__eyebrow"><Compass size={13} /> 数据全景</span>
                <h2>{totalRecords.toLocaleString('zh-CN')} 条记录，<br />支撑你的每一次择校判断。</h2>
                <p>
                  {stats.school_count || 0} 所院校 · {stats.major_count || 0} 个专业方向 ·
                  {' '}{stats.admission_records || 0} 条招生记录 · {stats.scoreline_records || 0} 条分数线记录
                  {yearText ? ` · 数据覆盖 ${yearText} 年` : ''}
                </p>
                <div className="v3-ky-hero__actions">
                  <Link className="v3-btn v3-btn--gradient" to="/kaoyan/schools">
                    从院校库开始 <ArrowRight size={15} />
                  </Link>
                  <Link className="v3-btn v3-btn--tonal" to="/kaoyan/recommend">按分数智能推荐</Link>
                </div>
              </div>
              <div className="v3-ky-hero__stats">
                <div className="v3-ky-hero__stat">
                  <b>{stats.subject_count || 0}</b>
                  <span>学科覆盖</span>
                </div>
                <div className="v3-ky-hero__stat">
                  <b>{subjects.length}</b>
                  <span>学科方向</span>
                </div>
                <div className="v3-ky-hero__stat">
                  <b>{yearText || '—'}</b>
                  <span>数据年份</span>
                </div>
              </div>
            </div>
          </Tile>

          <div className="v3-ky-stat-grid">
            <StatTile
              icon={<School size={15} />}
              label="院校数"
              value={stats.school_count || 0}
              hint="全部已收录院校"
            />
            <StatTile
              icon={<GraduationCap size={15} />}
              label="专业方向"
              value={stats.major_count || 0}
              hint="可用的专业目录记录"
            />
            <StatTile
              icon={<Target size={15} />}
              label="招生记录"
              value={stats.admission_records || 0}
              hint="拟招 / 复试 / 录取"
            />
            <StatTile
              icon={<LineChart size={15} />}
              label="分数线记录"
              value={stats.scoreline_records || 0}
              hint="院线 / 国家线 / 单科线"
            />
            <StatTile
              icon={<PieChart size={15} />}
              label="学科覆盖"
              value={stats.subject_count || 0}
              hint="库内已登记的学科"
            />
          </div>

          <section className="v3-ky-section">
            <div className="v3-ky-section__head">
              <div>
                <h2>学科方向</h2>
                <p>点进任一方向，在院校库中按学科代码筛选。</p>
              </div>
              <Badge tone="outline">{subjects.length} 个方向</Badge>
            </div>
            {subjects.length === 0 ? (
              <Tile>
                <Empty
                  icon={<GraduationCap size={24} />}
                  title="暂无学科方向数据"
                  text="学科方向依赖院校专业目录，导入后会在这里列出。"
                />
              </Tile>
            ) : (
              <div className="v3-ky-subject-grid">
                {subjects.map((s) => (
                  <Link key={s.code || s.name} to={`/kaoyan/schools?subject=${encodeURIComponent(s.code || '')}`} className="v3-ky-subject">
                    <div className="v3-ky-subject__top">
                      <span className="v3-ky-subject__icon"><GraduationCap size={17} /></span>
                      <Badge tone="outline">{s.code || '—'}</Badge>
                    </div>
                    <strong>{s.name || '未命名学科'}</strong>
                    <span className="v3-ky-subject__meta">{s.category || '学科分类未标注'}</span>
                    {s.exam_overlap ? (
                      <span className="v3-ky-subject__exam">考试科目：{s.exam_overlap}</span>
                    ) : null}
                    <span className="v3-ky-subject__go">在院校库筛选 <ArrowRight size={13} /></span>
                  </Link>
                ))}
              </div>
            )}
          </section>

          <section className="v3-ky-section">
            <div className="v3-ky-section__head">
              <div>
                <h2>分析工具</h2>
                <p>院校对比、分数趋势、区域分布、招生散点与智能推荐。</p>
              </div>
            </div>
            <div className="v3-ky-tool-grid">
              {TOOLS.map((tool) => {
                const Icon = tool.icon
                return (
                  <Link key={tool.to} to={tool.to} className="v3-ky-tool">
                    <span className="v3-ky-tool__icon"><Icon size={19} /></span>
                    <span className="v3-ky-tool__copy">
                      <strong>{tool.label}</strong>
                      <em>{tool.desc}</em>
                    </span>
                    <ArrowRight size={16} className="v3-ky-tool__go" />
                  </Link>
                )
              })}
              {isAdmin ? (
                <Link to="/admin/schools" className="v3-ky-tool v3-ky-tool--admin">
                  <span className="v3-ky-tool__icon"><Database size={19} /></span>
                  <span className="v3-ky-tool__copy">
                    <strong>数据管理</strong>
                    <em>数据导入与来源管理（管理后台）</em>
                  </span>
                  <ArrowRight size={16} className="v3-ky-tool__go" />
                </Link>
              ) : null}
            </div>
          </section>

          {isEmpty ? (
            <Alert tone="info">院校库为空时，统计卡片与图表会保持空态，不会用演示数据填充。</Alert>
          ) : null}
        </>
      )}

      <p className="v3-ky-footnote">个人考研学习平台 · 数据仅供参考 · 分数线与招生口径以院校官网为准</p>
    </div>
  )
}
