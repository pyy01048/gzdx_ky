import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { qualityApi } from '../../api/client'
import { kaoyanApi } from '../../api/kaoyanApi'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, Badge, Button, Chip, Empty, Field, Input, PageHeader, Progress,
  Ring, Select, Skeleton, Tile, toastWarn,
} from '../ui'
import {
  ArrowRight, BarChart3, CheckCircle2, Compass, Database, Flag, InfoCircle,
  Layers, School, Sparkles, Target, TrendingUp,
} from '../icons'
import '../styles/kaoyan-aux-v3.css'

const SAFETY_META = {
  稳妥: { tone: 'success', cls: 'stable' },
  适中: { tone: 'warning', cls: 'mid' },
  冲刺: { tone: 'danger', cls: 'rush' },
}

const BREAKDOWN_LABELS = {
  gap: '分差',
  retest_ratio: '复录比',
  admit_avg: '均分',
  region: '区域',
  subject: '学科',
}

const BUCKETS = [
  { key: 'rush', title: '冲刺', tone: 'danger', desc: '分差 -35 ~ -5 分，需要超常发挥' },
  { key: 'stable', title: '稳妥', tone: 'warning', desc: '分差 -5 ~ +15 分，匹配度最高' },
  { key: 'safe', title: '保底', tone: 'success', desc: '高出均分 15 分以上，胜算大' },
]

function normalizeProvince(value) {
  return String(value || '').trim()
    .replace(/(壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|省|市)$/u, '')
}

function num(v, digits = 1) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return digits == null ? String(n) : n.toFixed(digits)
}

function CoveragePanel({ cov }) {
  const s = cov?.summary
  if (!s) return null
  const rate = Number(s.coverage_rate || 0) * 100
  const gaps = Array.isArray(s.supply_gaps) ? s.supply_gaps.slice(0, 6) : []
  return (
    <Tile span={12} className="v3-ky-cover">
      <div className="v3-ky-cover__head">
        <div className="v3-ky-cover__copy">
          <span className="v3-tile__label"><Database size={15} /> 语料可靠度</span>
          <p>
            知识库覆盖 <b>{s.majors_covered || 0}</b>/{s.majors_with_professional || 0} 个专业的初试专业课，
            覆盖口径为「专业课名与文档学科精确相等」，公共课数学 / 英语 / 政治不参与匹配。
          </p>
        </div>
        <div className="v3-ky-cover__rate">
          <b>{rate.toFixed(1)}%</b>
          <span>专业课语料覆盖率</span>
        </div>
      </div>
      <Progress value={rate} gradient height={8} />
      <div className="v3-ky-cover__stats">
        <div><span>语料偏薄</span><b>{s.majors_thin || 0}</b></div>
        <div><span>已归档未入库</span><b>{s.majors_unindexed || 0}</b></div>
        <div><span>未覆盖</span><b>{s.majors_uncovered || 0}</b></div>
        <div><span>知识库学科数</span><b>{s.corpus_subjects || 0}</b></div>
      </div>
      {gaps.length > 0 ? (
        <div className="v3-ky-cover__gaps">
          <span>供给缺口 TOP</span>
          {gaps.map((g) => (
            <span key={g.subject} className="v3-ky-cover__gap">{g.subject}<i>{g.majors} 个专业</i></span>
          ))}
        </div>
      ) : null}
      <p className="v3-ky-cover__note">未覆盖 ≠ 答不了，只表示本库暂时没有该科目的语料。</p>
    </Tile>
  )
}

function RecommendCard({ item, rank, goalId, onSetGoal, busy }) {
  const meta = SAFETY_META[item.safety] || { tone: 'outline', cls: 'neutral' }
  const kb = item.kb_coverage
  const coveragePct = kb && kb.majors > 0 ? Math.round((kb.covered / kb.majors) * 100) : 0
  const score = Number(item.score)
  return (
    <article className={`v3-ky-rec v3-ky-rec--${meta.cls}`}>
      <div className="v3-ky-rec__top">
        <div className="v3-ky-rec__title">
          <div className="v3-ky-rec__badges">
            <Badge tone={meta.tone}>{item.safety || '未分档'}</Badge>
            <span className="v3-ky-rec__rank">#{rank}</span>
          </div>
          <Link to={`/kaoyan/schools/${item.school_id}`}>{item.name}</Link>
          <div className="v3-ky-rec__sub">
            <span>{item.level || '层级未标注'}</span>
            <span>{item.province || '省份未标注'}</span>
          </div>
        </div>
        <Ring value={Number.isFinite(score) ? score : 0} size={68} stroke={6} gradient>
          <div className="v3-ky-rec__ring">
            <b>{num(item.score, 1)}</b>
            <span>综合分</span>
          </div>
        </Ring>
      </div>

      <div className="v3-ky-rec__metrics">
        <div><span>分差</span><b className="is-positive">+{item.gap ?? '—'}</b><em>分</em></div>
        <div><span>复录比</span><b>{item.retest_ratio == null ? '—' : num(item.retest_ratio, 2)}</b></div>
        <div><span>录取均分</span><b>{item.admit_avg_score == null ? '—' : num(item.admit_avg_score, 1)}</b></div>
      </div>

      {item.score_breakdown ? (
        <div className="v3-ky-breakdown">
          <span className="v3-ky-breakdown__label"><Layers size={12} /> 权重明细</span>
          {Object.entries(BREAKDOWN_LABELS).map(([key, label]) => (
            <span key={key} className="v3-ky-breakdown__item">
              {label} <b>{item.score_breakdown[key] ?? '—'}</b>
            </span>
          ))}
        </div>
      ) : null}

      {kb ? (
        kb.majors === 0 ? (
          <p className="v3-ky-rec__coverage is-muted">库内无该校专业方向数据</p>
        ) : (
          <div className={`v3-ky-rec__coverage${kb.covered === 0 ? ' is-danger' : kb.covered < kb.majors ? ' is-warning' : ' is-success'}`}>
            <div>
              <span>语料覆盖 {kb.covered}/{kb.majors} 个专业</span>
              {kb.uncovered ? <em>未覆盖 {kb.uncovered}</em> : null}
            </div>
            <Progress value={coveragePct} height={5} />
          </div>
        )
      ) : null}

      <div className="v3-ky-rec__foot">
        <span className="v3-ky-rec__gap">总分线 {item.total_line ?? '—'} · 国家线 {item.national_line ?? '—'}</span>
        <Button
          size="sm"
          variant={goalId === item.school_id ? 'tonal' : 'outline'}
          icon={goalId === item.school_id ? <CheckCircle2 size={15} /> : <Flag size={15} />}
          disabled={busy || goalId === item.school_id}
          onClick={() => onSetGoal(item)}
        >
          {goalId === item.school_id ? '已设为目标' : '设为目标院校'}
        </Button>
      </div>
    </article>
  )
}

function AutoAdjustPanel({ form }) {
  const [adj, setAdj] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const run = async () => {
    const raw = String(form.score || '').trim()
    const score = Number(raw)
    if (!raw || !Number.isInteger(score) || score < 200 || score > 500) {
      setError('自动调整需要 200–500 的整数预估总分，请先完善上方分数。')
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await kaoyanApi.autoAdjust({
        user_score: score,
        subject_code: form.subject_code.trim() || undefined,
        province: normalizeProvince(form.province) || undefined,
        level: form.level || undefined,
      })
      setAdj(data || null)
    } catch (e) {
      setError(e?.message || '自动调整失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  const coverage = adj && typeof adj.coverage === 'object'
    ? (adj.coverage?.total || 0)
    : (adj?.coverage || 0)
  const window = Array.isArray(adj?.year_window) ? adj.year_window : null

  return (
    <section className="v3-ky-section v3-ky-adjust">
      <div className="v3-ky-section__head">
        <div>
          <h2>快速一键自动调整</h2>
          <p>基于近 3 年录取均分自动分「冲 / 稳 / 保」三档，附数据化理由。</p>
        </div>
        <Button
          variant="gradient"
          icon={<Sparkles size={16} />}
          loading={loading}
          onClick={run}
        >
          {form.score ? `按 ${form.score} 分自动调整` : '按预估总分自动调整'}
        </Button>
      </div>

      {error ? <Alert tone="danger">{error}</Alert> : null}

      {adj ? (
        <>
          <div className="v3-ky-adjust__meta">
            <span><Compass size={14} /> {adj.method || '自动调整'}</span>
            <span><Database size={14} /> 覆盖院校 {coverage} 所</span>
            {window ? <span><BarChart3 size={14} /> 参考 {window[0]}–{window[1]} 年</span> : null}
          </div>
          <div className="v3-ky-buckets">
            {BUCKETS.map((bucket) => {
              const items = adj.buckets?.[bucket.key] || []
              return (
                <div key={bucket.key} className={`v3-ky-bucket v3-ky-bucket--${bucket.tone}`}>
                  <div className="v3-ky-bucket__head">
                    <div>
                      <strong>{bucket.title}</strong>
                      <span>{items.length} 所</span>
                    </div>
                    <Badge tone={bucket.tone}>{items.length ? '有匹配' : '空'}</Badge>
                  </div>
                  <p className="v3-ky-bucket__desc">{bucket.desc}</p>
                  {items.length === 0 ? (
                    <div className="v3-ky-bucket__empty">暂无匹配院校</div>
                  ) : (
                    <div className="v3-ky-bucket__list">
                      {items.map((s) => (
                        <div key={s.school_id} className="v3-ky-bucket__item">
                          <div className="v3-ky-bucket__item-top">
                            <Link to={`/kaoyan/schools/${s.school_id}`}>{s.school_name}</Link>
                            <span>均分 {num(s.avg3, 1)}</span>
                          </div>
                          <div className="v3-ky-bucket__item-meta">
                            <span>{s.level || '—'}</span>
                            <span>{s.province || '—'}</span>
                            <span>分差 {Number(s.gap) > 0 ? '+' : ''}{num(s.gap, 1)}</span>
                            <span>{s.years_used ? `${s.years_used} 年数据` : '—'}</span>
                          </div>
                          <div className="v3-ky-bucket__confidence">
                            <span>信心 {Math.round((Number(s.confidence) || 0) * 100)}%</span>
                            <Progress value={(Number(s.confidence) || 0) * 100} height={4} />
                          </div>
                          {Array.isArray(s.reasons) && s.reasons.length ? (
                            <div className="v3-ky-bucket__reasons">
                              {s.reasons.map((reason, i) => <span key={i}>{reason}</span>)}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      ) : !loading ? (
        <div className="v3-ky-adjust__empty">
          <InfoCircle size={18} />
          <span>填好预估总分后点按钮，这里会按库内近 3 年录取均分给出三档院校与理由。</span>
        </div>
      ) : (
        <div className="v3-ky-buckets">
          {BUCKETS.map((b) => <Skeleton key={b.key} height={150} />)}
        </div>
      )}
    </section>
  )
}

export default function KaoyanRecommend() {
  const { user, isAdmin } = useAuth()
  const [form, setForm] = useState({
    score: '', level: '', province: '', subject_code: '', target_avg_score: '',
    max_retest_ratio: 1.5, year: null,
  })
  const [years, setYears] = useState([])
  const [results, setResults] = useState([])
  const [algorithm, setAlgorithm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [formError, setFormError] = useState('')
  const [hasSearched, setHasSearched] = useState(false)
  const [safety, setSafety] = useState('all')
  const [goalMsg, setGoalMsg] = useState(null)
  const [goalId, setGoalId] = useState(null)
  const [goalBusy, setGoalBusy] = useState(false)
  const [cov, setCov] = useState(null)

  useEffect(() => {
    if (isAdmin) {
      qualityApi.majorCoverage().then(setCov).catch(() => setCov(null))
    } else {
      setCov(null)
    }
    kaoyanApi.dataYears()
      .then((r) => {
        const ys = Array.isArray(r?.items) ? r.items : []
        setYears(ys)
        if (ys.length) setForm((f) => (f.year == null ? { ...f, year: ys[0] } : f))
      })
      .catch(() => setYears([]))
  }, [isAdmin])

  const patch = (key, value) => setForm((f) => ({ ...f, [key]: value }))

  const resetFilters = () => {
    setForm((f) => ({ ...f, level: '', province: '', subject_code: '', target_avg_score: '', max_retest_ratio: 1.5 }))
    setResults([])
    setAlgorithm('')
    setHasSearched(false)
    setError('')
  }

  const run = async () => {
    const raw = String(form.score || '').trim()
    const score = Number(raw)
    if (!raw || !Number.isFinite(score) || score <= 0) {
      setFormError('请先填写预估总分。这是你自己的分数，系统不会预填默认值。')
      return
    }
    setFormError('')
    setLoading(true)
    setError('')
    setHasSearched(true)
    setGoalMsg(null)
    setResults([])
    setAlgorithm('')
    setSafety('all')
    try {
      const r = await kaoyanApi.recommend({
        score,
        level: form.level || undefined,
        province: normalizeProvince(form.province) || undefined,
        subject_code: form.subject_code.trim() || undefined,
        target_avg_score: String(form.target_avg_score).trim() || undefined,
        max_retest_ratio: String(form.max_retest_ratio).trim() || undefined,
        year: form.year == null ? undefined : form.year,
      })
      setResults(Array.isArray(r?.recommendations) ? r.recommendations : [])
      setAlgorithm(r?.algorithm || '')
    } catch (e) {
      setError(e?.message || '推荐请求失败，请稍后重试')
      setResults([])
      setAlgorithm('')
    } finally {
      setLoading(false)
    }
  }

  const setGoal = async (item) => {
    if (!user) {
      setGoalMsg({ tone: 'info', text: '登录后可将院校设为目标并同步到考研规划。当前推荐结果可正常浏览。' })
      return
    }
    if (!form.score) {
      toastWarn('请先填写预估总分')
      return
    }
    setGoalBusy(true)
    try {
      await kaoyanApi.setGoal(item.school_id, form.score)
      setGoalId(item.school_id)
      setGoalMsg({ tone: 'success', text: `已将「${item.name}」设为目标院校（目标分 ${form.score}）。` })
    } catch (e) {
      setGoalMsg({ tone: 'danger', text: `设置「${item.name}」失败：${e?.message || '请稍后重试'}` })
    } finally {
      setGoalBusy(false)
    }
  }

  const counts = useMemo(() => {
    const out = { 冲刺: 0, 适中: 0, 稳妥: 0 }
    results.forEach((r) => { if (out[r.safety] != null) out[r.safety] += 1 })
    return out
  }, [results])

  const shown = safety === 'all' ? results : results.filter((r) => r.safety === safety)
  const topScore = results.length
    ? Math.max(...results.map((r) => Number(r.score) || 0))
    : null

  const headerSub = years.length === 0 && hasSearched && !loading
    ? '院校库还没有可用的分数线年份，推荐依赖分数线与招生记录两张表'
    : results.length
      ? `按 ${form.score} 分筛出 ${results.length} 所院校 · 冲 ${counts.冲刺} / 稳 ${counts.适中} / 保 ${counts.稳妥} · 多维权重排序`
      : '输入预估分数和偏好，按分差、复录比、均分与区域综合排序，输出冲 / 稳 / 保三档院校'

  return (
    <div className="v3-stack v3-ky">
      <PageHeader
        eyebrow="RECOMMEND · 多维权重"
        title="智能择校推荐"
        sub={headerSub}
        actions={(
          <>
            <Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">
              浏览院校库 <ArrowRight size={15} />
            </Link>
            <Link className="v3-btn v3-btn--text" to="/kaoyan/analysis">查看分数趋势</Link>
          </>
        )}
      />

      <Tile span={12} variant="hero" className="v3-ky-hero">
        <div className="v3-ky-hero__body">
          <div className="v3-ky-hero__copy">
            <span className="v3-eyebrow v3-ky-hero__eyebrow"><Sparkles size={13} /> 择校引擎</span>
            <h2>把分数、复录比与区域偏好，<br />折算成一张冲稳保清单。</h2>
            <p>
              引擎读取库内真实分数线、招生复录比与录取均分，按五维权重打分；
              语料覆盖情况也会标注，避免把「没有资料」误当成「没有院校」。
            </p>
            <div className="v3-ky-hero__actions">
              <span className="v3-ky-hero__pill"><Target size={14} /> 5 维权重</span>
              <span className="v3-ky-hero__pill"><Layers size={14} /> 冲 / 稳 / 保 3 档</span>
              <span className="v3-ky-hero__pill"><Database size={14} /> 最多 20 所</span>
            </div>
          </div>
          <div className="v3-ky-hero__stats">
            <div className="v3-ky-hero__stat">
              <b>{hasSearched && results.length ? counts.冲刺 : '—'}</b>
              <span>冲刺</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{hasSearched && results.length ? counts.适中 : '—'}</b>
              <span>适中</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{hasSearched && results.length ? counts.稳妥 : '—'}</b>
              <span>稳妥</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{topScore == null ? '—' : num(topScore, 0)}</b>
              <span>最高综合分</span>
            </div>
          </div>
        </div>
      </Tile>

      {cov ? <CoveragePanel cov={cov} /> : null}

      <Tile span={12} className="v3-ky-panel">
        <div className="v3-ky-panel__head">
          <div>
            <h2>输入你的分数与偏好</h2>
            <p>预估总分必填；其余条件留空表示不限。省份按库内简称精确匹配（如「四川」）。</p>
          </div>
          <Badge tone="outline">{years.length ? `${years.length} 个参考年份` : '年份待导入'}</Badge>
        </div>

        <div className="v3-ky-form-grid">
          <Field label="预估总分（必填）" hint="系统不会预填默认分数" error={formError || undefined}>
            <Input
              type="number"
              inputMode="numeric"
              min="1"
              max="500"
              aria-label="预估总分"
              placeholder="你的预估总分"
              value={form.score}
              onChange={(e) => { patch('score', e.target.value); if (formError) setFormError('') }}
            />
          </Field>
          <Field label="目标层级">
            <Select value={form.level} aria-label="目标层级" onChange={(e) => patch('level', e.target.value)}>
              <option value="">不限</option>
              <option value="985">985</option>
              <option value="211">211</option>
              <option value="双一流">双一流</option>
              <option value="双非">双非</option>
            </Select>
          </Field>
          <Field label="目标省份" hint="如：四川 / 北京">
            <Input
              aria-label="目标省份"
              placeholder="如：四川"
              value={form.province}
              onChange={(e) => patch('province', e.target.value)}
            />
          </Field>
          <Field label="学科代码" hint="如：0808">
            <Input
              aria-label="学科代码"
              placeholder="如：0808"
              value={form.subject_code}
              onChange={(e) => patch('subject_code', e.target.value)}
            />
          </Field>
          <Field label="目标录取均分" hint="用于均分匹配项">
            <Input
              type="number"
              inputMode="numeric"
              aria-label="目标录取均分"
              placeholder="如：380"
              value={form.target_avg_score}
              onChange={(e) => patch('target_avg_score', e.target.value)}
            />
          </Field>
          <Field label="最大复录比" hint="越低竞争越激烈">
            <Input
              type="number"
              step="0.1"
              aria-label="最大复录比"
              value={form.max_retest_ratio}
              onChange={(e) => patch('max_retest_ratio', e.target.value)}
            />
          </Field>
          {years.length > 0 ? (
            <Field label="参考年份">
              <Select
                value={form.year ?? ''}
                aria-label="参考年份"
                onChange={(e) => patch('year', e.target.value === '' ? null : Number(e.target.value))}
              >
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </Select>
            </Field>
          ) : null}
        </div>

        {formError ? <Alert tone="danger" className="v3-ky-form-alert">{formError}</Alert> : null}
        {!years.length ? (
          <Alert tone="info" className="v3-ky-form-note">
            院校库尚未返回任何数据年份，推荐结果可能为空。导入分数线与招生记录后，年份会自动出现在这里。
          </Alert>
        ) : null}

        <div className="v3-ky-form__actions">
          <Button variant="gradient" size="lg" icon={<Sparkles size={18} />} loading={loading} onClick={run}>
            {loading ? '推荐中…' : '开始推荐'}
          </Button>
          <Button variant="text" onClick={resetFilters}>清空筛选</Button>
          <span className="v3-ky-form__hint">推荐只读取后端聚合数据，不生成虚构院校。</span>
        </div>
      </Tile>

      {hasSearched ? (
        <section className="v3-ky-section">
          <div className="v3-ky-section__head">
            <div>
              <h2>推荐结果 <span className="v3-ky-section__count">{results.length} 所</span></h2>
              <p>{algorithm || '按多维权重综合排序'}</p>
            </div>
            {results.length > 0 ? (
              <div className="v3-ky-filter-chips" role="group" aria-label="按风险档筛选">
                <Chip active={safety === 'all'} onClick={() => setSafety('all')}>全部 {results.length}</Chip>
                <Chip active={safety === '冲刺'} onClick={() => setSafety('冲刺')}>冲刺 {counts.冲刺}</Chip>
                <Chip active={safety === '适中'} onClick={() => setSafety('适中')}>适中 {counts.适中}</Chip>
                <Chip active={safety === '稳妥'} onClick={() => setSafety('稳妥')}>稳妥 {counts.稳妥}</Chip>
              </div>
            ) : null}
          </div>

          {goalMsg ? (
            <Alert tone={goalMsg.tone} className="v3-ky-goal-alert">
              {goalMsg.text}
              {!user && goalMsg.tone === 'info' ? <Link className="v3-ky-inline-link" to="/login">去登录</Link> : null}
            </Alert>
          ) : null}

          {loading ? (
            <div className="v3-ky-recs">
              {Array.from({ length: 4 }).map((_, i) => (
                <Tile key={i}><Skeleton height={210} /></Tile>
              ))}
            </div>
          ) : error ? (
            <Tile>
              <Empty
                icon={<School size={26} />}
                title="推荐请求失败"
                text={error}
                action={<Button variant="tonal" onClick={run}>重新推荐</Button>}
              />
            </Tile>
          ) : results.length === 0 ? (
            <Tile>
              {years.length === 0 ? (
                <Empty
                  icon={<Database size={26} />}
                  title="院校库还没有数据"
                  text="推荐依赖分数线与招生记录两张表。导入后无需改动这里的条件，直接重新推荐即可。"
                  action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/schools">浏览院校库</Link>}
                />
              ) : (
                <Empty
                  icon={<Compass size={26} />}
                  title="暂无推荐结果"
                  text="当前分数或筛选条件下没有匹配院校。可以适当放宽层级 / 省份 / 复录比后重试。"
                  action={(
                    <div className="v3-row">
                      <Button variant="tonal" onClick={resetFilters}>清空筛选</Button>
                      <Button variant="text" onClick={run}>用当前条件重试</Button>
                    </div>
                  )}
                />
              )}
            </Tile>
          ) : shown.length === 0 ? (
            <Tile>
              <Empty
                icon={<Compass size={26} />}
                title={`没有「${safety}」档院校`}
                text="切换其他风险档，或清空风险筛选查看全部推荐。"
                action={<Button variant="tonal" onClick={() => setSafety('all')}>查看全部</Button>}
              />
            </Tile>
          ) : (
            <div className="v3-ky-recs">
              {shown.map((item) => (
                <RecommendCard
                  key={item.school_id}
                  item={item}
                  rank={results.findIndex((r) => r.school_id === item.school_id) + 1}
                  goalId={goalId}
                  onSetGoal={setGoal}
                  busy={goalBusy}
                />
              ))}
            </div>
          )}
        </section>
      ) : null}

      <AutoAdjustPanel form={form} />

      <p className="v3-ky-footnote">
        <TrendingUp size={13} /> 推荐结果来自库内分数线 / 招生记录聚合；划线数据经第三方聚合的院校会标注来源可信度，请以院校官网口径为准。
      </p>
    </div>
  )
}
