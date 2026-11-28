import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import { useAuth } from '../../auth/AuthContext'
import AiEvidenceCard, { ConfidenceBadge } from '../ai/AiEvidenceCard'
import { buildEvidenceFields, RECOMMEND_DISCLAIMER } from './KaoyanRecommend'
import {
  Alert, Badge, Button, Card, CardHead, Empty, PageHeader, Progress, Spinner,
} from '../ui'
import {
  AlertCircle, ChevronLeft, ArrowRight, BarChart3, CheckCircle2, Database,
  Flag, InfoCircle, Layers, RefreshCw, School,
} from '../icons'
import '../styles/kaoyan-aux-v3.css'
import '../styles/detail-pages.css'

const WEIGHTS = [
  ['gap', '分差', 40],
  ['retest_ratio', '复录比', 20],
  ['admit_avg', '录取均分', 20],
  ['region', '区域', 10],
  ['subject', '学科', 10],
]

const num = (value, digits = 1) => {
  const n = Number(value)
  return value == null || value === '' || !Number.isFinite(n) ? '—' : n.toFixed(digits)
}

/** 从 URL search 还原推荐请求参数；score 非法时返回 null 以触发引导态。 */
export function recommendParamsFromSearch(searchParams) {
  const score = Number(searchParams.get('score'))
  if (!Number.isInteger(score) || score <= 0 || score > 500) return null
  return {
    score,
    level: searchParams.get('level') || undefined,
    province: searchParams.get('province') || undefined,
    subject_code: searchParams.get('subject_code') || undefined,
    target_avg_score: searchParams.get('target_avg_score') || undefined,
    max_retest_ratio: searchParams.get('max_retest_ratio') || undefined,
    year: searchParams.get('year') || undefined,
  }
}

function EvidenceTable({ title, rows, columns, note }) {
  const shown = rows.slice(0, 20)
  return (
    <Card className="v3-detail-card">
      <CardHead icon={<Database size={17} />} title={title} sub={rows.length ? `共 ${rows.length} 条，展示前 ${shown.length} 条` : '暂无记录'} />
      <div className="v3-detail-card__body">
        {shown.length ? (
          <div className="v3-detail-table-wrap">
            <table className="v3-detail-table">
              <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
              <tbody>{shown.map((row, index) => (
                <tr key={row.id ?? `${row.year}-${row.major_code}-${index}`}>
                  {columns.map((column) => <td key={column.key}>{column.value(row)}</td>)}
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="v3-caption">该院校在当前数据范围内没有{title}。</p>}
        {note ? <p className="v3-caption">{note}</p> : null}
      </div>
    </Card>
  )
}

export default function KaoyanRecommendDetail() {
  const { schoolId } = useParams()
  const [searchParams] = useSearchParams()
  const { user } = useAuth()
  const params = useMemo(() => recommendParamsFromSearch(searchParams), [searchParams])
  const validSchool = /^\d+$/.test(String(schoolId || ''))
  const [state, setState] = useState('loading')
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [school, setSchool] = useState(null)
  const [scores, setScores] = useState({ state: 'loading', items: [] })
  const [admissions, setAdmissions] = useState({ state: 'loading', items: [] })
  const [goalBusy, setGoalBusy] = useState(false)
  const [goalDone, setGoalDone] = useState(false)
  const [goalMessage, setGoalMessage] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const goalSeq = useRef(0)

  useEffect(() => {
    goalSeq.current += 1
    setGoalBusy(false)
    setGoalDone(false)
    setGoalMessage(null)
  }, [schoolId, params])

  useEffect(() => {
    if (!params || !validSchool) return undefined
    let alive = true
    setState('loading')
    setError('')
    setResult(null)
    setSchool(null)
    setScores({ state: 'loading', items: [] })
    setAdmissions({ state: 'loading', items: [] })
    setGoalDone(false)
    setGoalMessage(null)

    kaoyanApi.recommend(params).then((data) => {
      if (!alive) return
      setResult(data || null)
      const found = (data?.recommendations || []).find((item) => String(item.school_id) === String(schoolId))
      setState(found ? 'ok' : 'missing')
    }).catch((e) => {
      if (!alive) return
      setState('error')
      setError(e?.message || '推荐详情加载失败')
    })

    kaoyanApi.schoolDetail(schoolId).then((data) => {
      if (alive) setSchool(data || null)
    }).catch(() => {})

    kaoyanApi.schoolScores(schoolId, params.year ? { year: Number(params.year) } : undefined).then((rows) => {
      if (alive) setScores({ state: 'ok', items: Array.isArray(rows) ? rows : [] })
    }).catch((e) => {
      if (alive) setScores({ state: 'error', items: [], error: e?.message || '分数线加载失败' })
    })

    kaoyanApi.schoolAdmissions(schoolId).then((rows) => {
      if (alive) setAdmissions({ state: 'ok', items: Array.isArray(rows) ? rows : [] })
    }).catch((e) => {
      if (alive) setAdmissions({ state: 'error', items: [], error: e?.message || '招生数据加载失败' })
    })

    return () => { alive = false }
  }, [schoolId, params, validSchool, reloadKey])

  const item = result?.recommendations?.find((row) => String(row.school_id) === String(schoolId))
  const relevantAdmissions = useMemo(() => (
    (admissions.items || []).filter((row) => !result?.year || Number(row.year) === Number(result.year))
  ), [admissions.items, result?.year])

  const setGoal = useCallback(async () => {
    if (!user) return
    const current = ++goalSeq.current
    setGoalBusy(true)
    setGoalMessage(null)
    try {
      await kaoyanApi.setGoal(schoolId, params.score)
      if (current !== goalSeq.current) return
      setGoalDone(true)
      setGoalMessage({ tone: 'success', text: `已将「${item?.name || school?.name || '该院校'}」设为目标院校。` })
    } catch (e) {
      if (current === goalSeq.current) {
        setGoalMessage({ tone: 'danger', text: `设置目标失败：${e?.message || '请稍后重试'}` })
      }
    } finally {
      if (current === goalSeq.current) setGoalBusy(false)
    }
  }, [user, schoolId, params?.score, item?.name, school?.name])

  if (!params || !validSchool) {
    return (
      <div className="v3-stack v3-detail-page">
        <PageHeader eyebrow="RECOMMEND · 链接校验" title="推荐依据详情" sub="请从推荐结果重新进入，以还原本次评分条件。" />
        <Card className="v3-detail-state">
          <Empty icon={<AlertCircle size={28} />} title="推荐详情链接不完整" text="详情需要有效的院校编号和预估总分，请从推荐结果重新进入。" action={<Link className="v3-btn v3-btn--tonal" to="/kaoyan/recommend">返回择校推荐</Link>} />
        </Card>
      </div>
    )
  }

  if (state === 'loading') {
    return (
      <div className="v3-stack v3-detail-page">
        <PageHeader eyebrow="RECOMMEND · 单校决策依据" title="推荐依据详情" sub="正在还原这次推荐及其数据依据…" />
        <div className="v3-detail-loading" role="status"><Spinner size={22} /><span>正在读取评分与原始数据…</span></div>
      </div>
    )
  }

  if (state !== 'ok' || !item) {
    return (
      <div className="v3-stack v3-detail-page">
        <PageHeader eyebrow="RECOMMEND · 单校决策依据" title="推荐依据详情" sub={state === 'error' ? '本次推荐暂时无法还原，可重试或返回推荐页。' : '当前推荐结果不包含这所院校。'} />
        <Card className="v3-detail-state">
          <Empty
            icon={<School size={28} />}
            title={state === 'error' ? '推荐详情加载失败' : '这所院校不在当前推荐结果中'}
            text={state === 'error' ? error : '分数、年份或筛选条件可能已变化。返回推荐页调整条件后会生成新的结果。'}
            action={<div className="v3-row"><Link className="v3-btn v3-btn--tonal" to="/kaoyan/recommend">返回推荐页</Link>{state === 'error' ? <Button icon={<RefreshCw size={15} />} onClick={() => setReloadKey((key) => key + 1)}>重试</Button> : null}</div>}
          />
        </Card>
      </div>
    )
  }

  const scoreColumns = [
    { key: 'year', label: '年份', value: (row) => row.year ?? '—' },
    { key: 'major', label: '专业', value: (row) => row.major_name || row.major_code || '未标注专业' },
    { key: 'total', label: '总分线', value: (row) => num(row.total_line, 0) },
    { key: 'retest', label: '复试线', value: (row) => num(row.retest_line, 0) },
    { key: 'national', label: '国家线', value: (row) => num(row.national_line, 0) },
    { key: 'source', label: '来源', value: (row) => row.source || row.data_source || school?.data_source || '—' },
  ]
  const admissionColumns = [
    { key: 'year', label: '年份', value: (row) => row.year ?? '—' },
    { key: 'major', label: '专业', value: (row) => row.major_name || row.major_code || '未标注专业' },
    { key: 'enroll', label: '拟招', value: (row) => row.enroll_count ?? '—' },
    { key: 'admit', label: '录取', value: (row) => row.admit_count ?? '—' },
    { key: 'ratio', label: '复录比', value: (row) => num(row.retest_ratio, 2) },
    { key: 'avg', label: '录取均分', value: (row) => num(row.admit_avg_score, 1) },
  ]

  return (
    <div className="v3-stack v3-detail-page v3-ky">
      <nav className="v3-detail-breadcrumb" aria-label="面包屑">
        <Link to="/kaoyan/recommend">择校推荐</Link><span>/</span><span>{item.name} · 推荐依据</span>
      </nav>
      <header className="v3-detail-hero">
        <div>
          <span className="v3-eyebrow"><Layers size={13} /> RECOMMEND · 单校决策依据</span>
          <h1>{item.name}，为什么推荐给你？</h1>
          <p>按你填写的 {params.score} 分和筛选条件，还原本次评分、分档及原始数据。公式相同，但库内数据更新后结果可能变化。</p>
        </div>
        <div className="v3-detail-hero__badges">
          <Badge tone={item.safety === '稳妥' ? 'success' : item.safety === '适中' ? 'warning' : 'danger'}>{item.safety}</Badge>
          <ConfidenceBadge confidence={item.confidence ?? item.reliability ?? null} />
          <Badge tone="outline">{result.year ?? '年份未知'} 年</Badge>
        </div>
      </header>

      {goalMessage ? <Alert tone={goalMessage.tone}>{goalMessage.text}</Alert> : null}

      <div className="v3-detail-grid">
        <main className="v3-detail-main">
          <Card className="v3-detail-card">
            <CardHead icon={<BarChart3 size={17} />} title="评分拆解" sub={result.algorithm || '五维权重'} />
            <div className="v3-detail-card__body">
              <div className="v3-recommend-score-hero"><strong>{num(item.score, 1)}</strong><span>综合分 / 100</span><em>预估 {params.score} 分 · 与最低总分线相差 {num(item.gap, 0)} 分</em></div>
              <div className="v3-recommend-weights">
                {WEIGHTS.map(([key, label, weight]) => {
                  const value = Number(item.score_breakdown?.[key])
                  return (
                    <div className="v3-recommend-weight" key={key}>
                      <div><span>{label}<small>权重 {weight}</small></span><b>{Number.isFinite(value) ? num(value, 1) : '—'}</b></div>
                      {Number.isFinite(value) ? <Progress value={value / weight * 100} height={6} /> : <span className="v3-caption">暂无分项得分</span>}
                    </div>
                  )
                })}
              </div>
              <div className="v3-detail-facts">
                <div><dt>风险分档</dt><dd>{item.safety}（按与最低总分线的分差判定）</dd></div>
                <div><dt>复录比</dt><dd>{num(item.retest_ratio, 2)}</dd></div>
                <div><dt>录取均分</dt><dd>{num(item.admit_avg_score, 1)}</dd></div>
                <div><dt>专业语料</dt><dd>{item.kb_coverage ? `${item.kb_coverage.covered}/${item.kb_coverage.majors} 个专业有资料` : '未提供'}</dd></div>
              </div>
              <AiEvidenceCard title={`${item.name} · 推荐依据`} engine="库内聚合" confidence={item.confidence ?? item.reliability ?? null} fields={buildEvidenceFields(item, result.year)} />
              <Alert tone="info">{RECOMMEND_DISCLAIMER}</Alert>
            </div>
          </Card>

          <EvidenceTable title="分数线记录" rows={scores.items} columns={scoreColumns} note={scores.state === 'error' ? scores.error : '推荐使用当前年份最低总分线；这里保留专业维度的原始记录。'} />
          <EvidenceTable title="招生记录" rows={relevantAdmissions} columns={admissionColumns} note={admissions.state === 'error' ? admissions.error : `仅展示推荐参考年份 ${result.year ?? '未知'}。录取人数缺失不代表 0 人。`} />
        </main>

        <aside className="v3-detail-side">
          <Card className="v3-detail-card">
            <CardHead icon={<Flag size={17} />} title="把判断变成目标" />
            <div className="v3-detail-card__body">
              <p>目标分使用本次推荐的 {params.score} 分，设置后同步到个人考研规划。</p>
              {user ? (
                <Button block variant="gradient" icon={goalDone ? <CheckCircle2 size={16} /> : <Flag size={16} />} loading={goalBusy} disabled={goalDone} onClick={setGoal}>{goalDone ? '已设为目标院校' : '设为目标院校'}</Button>
              ) : (
                <><Alert tone="info">登录后可保存目标院校。</Alert><Link className="v3-btn v3-btn--gradient v3-btn--block" to="/login">登录后设置</Link></>
              )}
            </div>
          </Card>
          <Card className="v3-detail-card">
            <CardHead icon={<InfoCircle size={17} />} title="本次筛选条件" />
            <dl className="v3-detail-facts v3-detail-card__body">
              <div><dt>预估总分</dt><dd>{params.score}</dd></div>
              <div><dt>层级</dt><dd>{params.level || '不限'}</dd></div>
              <div><dt>省份</dt><dd>{params.province || '不限'}</dd></div>
              <div><dt>学科代码</dt><dd>{params.subject_code || '未指定'}</dd></div>
              <div><dt>目标均分</dt><dd>{params.target_avg_score || '未指定'}</dd></div>
              <div><dt>最大复录比</dt><dd>{params.max_retest_ratio || '1.5'}</dd></div>
            </dl>
          </Card>
          <Card className="v3-detail-card">
            <CardHead icon={<School size={17} />} title="继续核验" />
            <div className="v3-detail-card__body v3-stack">
              <Link className="v3-btn v3-btn--tonal v3-btn--block" to={`/kaoyan/schools/${schoolId}`}>查看完整院校档案 <ArrowRight size={15} /></Link>
              <Link className="v3-btn v3-btn--outline v3-btn--block" to="/kaoyan/compare">打开院校对比</Link>
              <Link className="v3-btn v3-btn--text v3-btn--block" to="/kaoyan/recommend"><ChevronLeft size={15} /> 返回推荐结果</Link>
            </div>
          </Card>
        </aside>
      </div>
    </div>
  )
}
