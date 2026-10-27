import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import EChart from '../../components/EChart'
import { analysisApi } from '../../api/client'
import useApiData from '../../hooks/useApiData'
import { chartTheme } from '../charts'
import {
  AlertCircle, ArrowRight, BookOpen, Brain, Calendar, Flame, RefreshCw, Sparkles,
  Target, TrendingUp,
} from '../icons'
import {
  Button, Empty, IconButton, PageHeader, Progress, Ring, Skeleton, Tile, toast,
  toastOk, toastErr,
} from '../ui'
import '../styles/pages.css'

const MASTERY = {
  危: { cls: 'danger', desc: '正确率 <50% 或错题积压 >20' },
  弱: { cls: 'warning', desc: '正确率 <65%' },
  稳: { cls: 'primary', desc: '正确率 <80%' },
  强: { cls: 'success', desc: '正确率 ≥80%' },
  未开始: { cls: 'outline', desc: '暂无答题记录' },
}

function useThemeMode() {
  const read = () => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')
  const [mode, setMode] = useState(read)
  useEffect(() => {
    const obs = new MutationObserver(() => setMode(read()))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  return mode
}

function fmtTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('zh-CN', { hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function ProfileStat({ icon, label, value, unit, hint }) {
  return (
    <Tile span={3} className="v3-profile-stat">
      <span className="v3-tile__label">{icon} {label}</span>
      <span className="v3-tile__value">{value}<em>{unit}</em></span>
      {hint ? <span className="v3-tile__hint">{hint}</span> : null}
    </Tile>
  )
}

export default function LearnerProfile() {
  const navigate = useNavigate()
  const mode = useThemeMode()
  const { data: profile, loading, error, isEmpty, reload } = useApiData(
    () => analysisApi.profile({ days: 30 }),
    { onError: (e) => toast(`画像加载失败：${e.message}`) },
  )
  const [refreshing, setRefreshing] = useState(false)

  const refresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const ok = await reload()
      if (ok) toastOk('画像已刷新')
      else toastErr('刷新失败，请稍后重试')
    } finally {
      setRefreshing(false)
    }
  }, [reload])

  const T = chartTheme(mode === 'dark')

  if (loading) {
    return (
      <div className="v3-stack" style={{ gap: 20 }}>
        <PageHeader eyebrow="PROFILE · 真实行为聚合" title="学习画像" sub="正在聚合答题、错题与模考记录" />
        <div className="v3-bento">
          {Array.from({ length: 4 }).map((_, i) => (
            <Tile key={i} span={3}><Skeleton height={92} /></Tile>
          ))}
          <Tile span={7}><Skeleton height={260} /></Tile>
          <Tile span={5}><Skeleton height={260} /></Tile>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="v3-stack" style={{ gap: 20 }}>
        <PageHeader eyebrow="PROFILE · 真实行为聚合" title="学习画像" />
        <div className="v3-card" style={{ padding: 36 }}>
          <Empty
            icon={<AlertCircle size={26} />}
            title="画像加载失败"
            text={error}
            action={<Button variant="tonal" onClick={reload}>重新加载</Button>}
          />
        </div>
      </div>
    )
  }

  if (isEmpty) {
    return (
      <div className="v3-stack" style={{ gap: 20 }}>
        <PageHeader eyebrow="PROFILE · 真实行为聚合" title="学习画像" sub="基于答题 · 错题 · 模考的真实记录聚合" />
        <div className="v3-card" style={{ padding: 44 }}>
          <Empty
            icon={<Brain size={28} />}
            title="还没有可聚合的学习行为"
            text="画像由答题、错题、模考的真实记录算出来。先去刷几题或参加一次模考，这里就会有内容。"
            action={<Button variant="filled" onClick={() => navigate('/quiz')}>去刷题 <ArrowRight size={15} /></Button>}
          />
        </div>
      </div>
    )
  }

  const {
    overview = {}, subjects = [], weak_points: weakPoints = [], knowledge_points: kp3,
    review_queue: reviewQueue = {}, trend = [], suggestions = [],
  } = profile

  const kpTotal = kp3?.total || 0
  const queueTotal = (reviewQueue.scheduled || 0) + (reviewQueue.no_schedule || 0)
  const scheduledPct = queueTotal ? Math.round((reviewQueue.scheduled / queueTotal) * 100) : 0
  const masteryOrder = ['危', '弱', '稳', '强', '未开始']
  const masteryCount = subjects.reduce((acc, s) => {
    const key = masteryOrder.includes(s.mastery) ? s.mastery : '未开始'
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})

  const trendOption = trend.length ? {
    color: ['#4285F4', '#34A853', '#D96570'],
    tooltip: {
      ...T.tooltip, trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: T.axisLine.lineStyle.color } },
    },
    legend: { data: ['答题', '答对', '新增错题'], textStyle: { color: T.textStyle.color, fontSize: 11 }, top: 0 },
    grid: { left: 8, right: 12, top: 34, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category', data: trend.map((t) => t.date.slice(5)),
      axisLine: { lineStyle: { color: T.axisLine.lineStyle.color } },
      axisLabel: { color: T.textStyle.color, fontSize: 10 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: T.textStyle.color, fontSize: 10 },
      splitLine: { lineStyle: { color: T.splitLine.lineStyle.color } },
    },
    series: [
      { name: '答题', type: 'line', smooth: true, symbolSize: 5, data: trend.map((t) => t.answers) },
      { name: '答对', type: 'line', smooth: true, symbolSize: 5, data: trend.map((t) => t.correct) },
      { name: '新增错题', type: 'bar', barMaxWidth: 14, data: trend.map((t) => t.errors), itemStyle: { borderRadius: [4, 4, 0, 0], opacity: 0.75 } },
    ],
  } : null

  return (
    <div className="v3-stack" style={{ gap: 20 }}>
      <PageHeader
        eyebrow="PROFILE · 真实行为聚合"
        title="学习画像"
        sub={`生成于 ${fmtTime(profile.generated_at)} · 由答题 / 错题 / 模考确定性聚合，非模型臆测`}
        actions={<IconButton label="刷新画像" icon={<RefreshCw size={17} />} onClick={refresh} disabled={refreshing} />}
      />

      <div className="v3-bento">
        <ProfileStat icon={<Target size={15} />} label="累计答题" value={overview.total_answers ?? 0} unit="题" />
        <ProfileStat
          icon={<TrendingUp size={15} />} label="总正确率"
          value={overview.overall_accuracy != null ? overview.overall_accuracy : '—'}
          unit={overview.overall_accuracy != null ? '%' : ''}
        />
        <ProfileStat icon={<Calendar size={15} />} label="学习天数" value={overview.study_days ?? 0} unit="天" />
        <ProfileStat
          icon={<AlertCircle size={15} />} label="错题存量"
          value={overview.error_stock ?? 0} unit="道"
          hint={`已解决 ${overview.error_resolved ?? 0} 道 · 模考 ${overview.exam_count ?? 0} 次`}
        />

        <Tile span={7} className="v3-profile-subjects">
          <div className="v3-card__head">
            <div>
              <div className="v3-card__title"><BookOpen size={16} /> 科目掌握度</div>
              <div className="v3-card__sub">危 &lt;50% 或错题积压 &gt;20 · 弱 &lt;65% · 稳 &lt;80% · 强 ≥80%</div>
            </div>
            <span className="v3-profile-mastery-legend">
              {masteryOrder.filter((k) => masteryCount[k]).map((k) => (
                <span key={k} className={`v3-profile-mastery-dot is-${MASTERY[k].cls}`} title={MASTERY[k].desc}>
                  {k} {masteryCount[k]}
                </span>
              ))}
            </span>
          </div>
          {subjects.length ? (
            <div className="v3-profile-rows">
              {subjects.map((s) => {
                const st = MASTERY[s.mastery] || MASTERY['未开始']
                return (
                  <div key={s.subject} className="v3-profile-row">
                    <span className={`v3-badge v3-badge--${st.cls}`}>{s.mastery}</span>
                    <div className="v3-profile-row__main">
                      <div className="v3-profile-row__title">{s.subject}</div>
                      <div className="v3-profile-row__meta">
                        答题 {s.answered} · 错题积压 {s.error_stock}
                        {s.exam_avg != null ? ` · 模考均分 ${s.exam_avg}` : ''}
                      </div>
                    </div>
                    <div className="v3-profile-row__acc">
                      <b>{s.accuracy != null ? `${s.accuracy}%` : '—'}</b>
                      <span>正确率</span>
                    </div>
                    <div className="v3-profile-row__bar">
                      <Progress value={s.accuracy || 0} height={6} />
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <Empty icon={<BookOpen size={20} />} title="暂无答题记录" text="先去刷几题，科目掌握度会随真实答题更新。"
              action={<button className="v3-btn v3-btn--text v3-btn--sm" onClick={() => navigate('/quiz')}>去刷题</button>} />
          )}
        </Tile>

        <Tile span={5} className="v3-profile-queue">
          <div className="v3-card__head">
            <div>
              <div className="v3-card__title"><Flame size={16} /> 复习队列</div>
              <div className="v3-card__sub">SM-2 排期健康度</div>
            </div>
            <Ring value={scheduledPct} size={62} stroke={6}>
              <span style={{ fontSize: 14, fontWeight: 700 }}>{scheduledPct}%</span>
            </Ring>
          </div>
          <div className="v3-profile-queue__grid">
            {[
              ['已排期', reviewQueue.scheduled || 0, 'neutral'],
              ['今日到期', reviewQueue.due_today || 0, 'warning'],
              ['已逾期', reviewQueue.overdue || 0, 'danger'],
              ['未排期', reviewQueue.no_schedule || 0, 'neutral'],
            ].map(([label, value, tone]) => (
              <div key={label} className={`v3-profile-queue__cell is-${tone}`}>
                <b>{value}</b>
                <span>{label}</span>
              </div>
            ))}
          </div>
          <div className="v3-profile-queue__foot">
            <span>模考均分 <b>{overview.exam_avg_score != null ? overview.exam_avg_score : '—'}</b></span>
            <span>模考 <b>{overview.exam_count ?? 0}</b> 次</span>
            <button className="v3-btn v3-btn--text v3-btn--sm" onClick={() => navigate('/cards')}>去复习 <ArrowRight size={14} /></button>
          </div>
        </Tile>

        {kp3 && kpTotal > 0 ? (
          <Tile span={5} className="v3-profile-kp">
            <div className="v3-card__head">
              <div>
                <div className="v3-card__title"><Brain size={16} /> 知识点掌握度</div>
                <div className="v3-card__sub">共 {kpTotal} 个 · 未学不计入薄弱统计</div>
              </div>
            </div>
            <div className="v3-profile-kp__cards">
              {[
                [kp3.labels?.unlearned || '未学', kp3.unlearned || 0, 'neutral', '无学习记录'],
                [kp3.labels?.weak || '薄弱', kp3.weak || 0, 'warning', '掌握度 <70'],
                [kp3.labels?.mastered || '已掌握', kp3.mastered || 0, 'success', '掌握度 ≥70'],
              ].map(([label, value, tone, desc]) => (
                <div key={label} className={`v3-profile-kp__card is-${tone}`}>
                  <b>{value}</b>
                  <span>{label}</span>
                  <em>{desc}</em>
                </div>
              ))}
            </div>
            <div className="v3-profile-kp__bar" aria-label="知识点掌握度分布">
              <span className="is-neutral" style={{ width: `${((kp3.unlearned || 0) / kpTotal) * 100}%` }} />
              <span className="is-warning" style={{ width: `${((kp3.weak || 0) / kpTotal) * 100}%` }} />
              <span className="is-success" style={{ width: `${((kp3.mastered || 0) / kpTotal) * 100}%` }} />
            </div>
            <button className="v3-btn v3-btn--text v3-btn--sm v3-profile-kp__link" onClick={() => navigate('/knowledge')}>
              打开知识图谱 <ArrowRight size={14} />
            </button>
          </Tile>
        ) : (
          <Tile span={5}><Empty icon={<Brain size={20} />} title="暂无知识点记录" text="答题与错题挂接知识点后，这里会显示三态分布。" /></Tile>
        )}

        <Tile span={7} className="v3-profile-weak">
          <div className="v3-card__head">
            <div>
              <div className="v3-card__title"><AlertCircle size={16} /> 薄弱知识点 TOP</div>
              <div className="v3-card__sub">按错题数排序 · 点击进入错题本</div>
            </div>
          </div>
          {weakPoints.length ? (
            <div className="v3-profile-weak__list">
              {weakPoints.slice(0, 8).map((w, i) => (
                <button
                  key={`${w.knowledge_point_id}-${i}`}
                  type="button"
                  className="v3-profile-weak__row"
                  onClick={() => navigate(`/error-review?kp_id=${w.knowledge_point_id}&kp_name=${encodeURIComponent(w.name || '')}`)}
                >
                  <span className="v3-profile-weak__rank">{String(i + 1).padStart(2, '0')}</span>
                  <span className="v3-profile-weak__name">{w.name}</span>
                  {w.subject ? <span className="v3-profile-weak__subject">{w.subject}</span> : null}
                  <span className="v3-profile-weak__count">错 {w.error_count}</span>
                  <ArrowRight size={14} />
                </button>
              ))}
            </div>
          ) : (
            <Empty icon={<Target size={20} />} title="暂无薄弱知识点" text="答错后会自动归集考点；先积累几道错题。" />
          )}
        </Tile>

        {trendOption ? (
          <Tile span={8}>
            <div className="v3-card__head">
              <div>
                <div className="v3-card__title"><TrendingUp size={16} /> 近 30 天活跃趋势</div>
                <div className="v3-card__sub">答题 / 答对 / 新增错题</div>
              </div>
            </div>
            <EChart option={trendOption} style={{ height: 280 }} />
          </Tile>
        ) : null}

        <Tile span={trendOption ? 4 : 12} className="v3-profile-insight">
          <div className="v3-card__title"><Sparkles size={16} data-idle="spin" /> 行为洞察</div>
          <div className="v3-card__sub">确定性规则生成 · 非 AI</div>
          {suggestions.length ? (
            <ul className="v3-profile-insight__list">
              {suggestions.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          ) : (
            <p className="v3-caption">暂无可给出的建议，继续保持记录。</p>
          )}
        </Tile>
      </div>
    </div>
  )
}
