import React, { useCallback, useEffect, useState } from 'react'
import { kaoyanApi } from '../../api/kaoyanApi'
import {
  AnimatedNumber, Badge, Button, Card, Empty, LoadingState, PageHeader,
  Progress, Ring, SectionHead, Tile, toast,
} from '../ui'
import {
  Activity, AlertCircle, CheckCircle2, Clock, FileText, Flame, Lock,
  RefreshCw, Sparkles, Star, Trophy, Zap,
} from '../icons'
import '../styles/aux-v3.css'

export default function GrowthPage() {
  const [summary, setSummary] = useState(null)
  const [badges, setBadges] = useState([])
  const [achievements, setAchievements] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      kaoyanApi.growthSummary(),
      kaoyanApi.growthBadges(),
      kaoyanApi.growthAchievements(),
    ])
      .then(([s, b, a]) => {
        setSummary(s)
        setBadges(b.badges || [])
        setAchievements(a.achievements || [])
      })
      .catch((e) => {
        setError(e?.message || '成长数据加载失败')
        toast('成长数据加载失败')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const lv = summary?.level || {}
  const stats = summary?.stats || {}
  const points = Number(lv.points) || 0
  const progress = Math.max(0, Math.min(100, Number(lv.progress) || 0))
  const pointsDetail = summary?.points_detail || []
  const badgeCount = Number(summary?.badge_count) || 0
  const achievementCount = Number(summary?.achievement_count) || 0
  const studyMinutes = Math.floor((Number(stats.study_seconds) || 0) / 60)
  const noPoints = pointsDetail.every((d) => !d.points)

  const statItems = [
    { icon: Activity, label: '答题', value: Number(stats.answer_total) || 0, unit: '题' },
    { icon: CheckCircle2, label: '答对', value: Number(stats.answer_correct) || 0, unit: '题' },
    { icon: FileText, label: '交卷', value: Number(stats.submit_total) || 0, unit: '次' },
    { icon: RefreshCw, label: '复习', value: Number(stats.review_total) || 0, unit: '次' },
    { icon: Clock, label: '学习时长', value: studyMinutes, unit: '分钟' },
    { icon: Flame, label: '活跃', value: Number(stats.active_days) || 0, unit: '天' },
  ]

  return (
    <div className="v3-aux-page v3-growth">
      <PageHeader
        eyebrow="GROWTH · 学习行为积分"
        title="成长体系"
        sub="等级 · 积分 · 徽章 · 成就 —— 基于学习行为事件自动计算"
        actions={(
          <Button
            variant="ghost"
            icon={<RefreshCw size={16} />}
            onClick={load}
            disabled={loading}
          >
            刷新
          </Button>
        )}
      />

      {loading ? (
        <LoadingState text="正在汇总成长数据…" />
      ) : error || !summary ? (
        <Card className="v3-aux-error">
          <Empty
            icon={<AlertCircle size={26} />}
            title="成长数据加载失败"
            text={error || '暂时没有拿到成长数据，请稍后重试。'}
            action={<Button variant="tonal" onClick={load}>重新加载</Button>}
          />
        </Card>
      ) : (
        <>
          {/* ---- 等级 / 积分 / 徽章 / 成就 ---- */}
          <div className="v3-bento v3-growth-hero">
            <Tile span={5} variant="hero" className="v3-growth-level">
              <div className="v3-growth-level__top">
                <div className="v3-growth-level__copy">
                  <div className="v3-tile__label"><Sparkles size={15} />当前等级</div>
                  <div className="v3-growth-level__name">
                    <span>Lv.</span><AnimatedNumber value={Number(lv.level) || 0} />
                  </div>
                  <div className="v3-growth-level__title">{lv.name || '—'}</div>
                </div>
                <Ring value={progress} size={112} stroke={10} gradient>
                  <div className="v3-growth-ring">
                    <strong>{Number(lv.level) || 0}</strong>
                    <span>级</span>
                  </div>
                </Ring>
              </div>
              <Progress value={progress} gradient />
              <div className="v3-growth-level__next">
                {lv.next ? (
                  <>
                    距 {lv.next.name}（{lv.next.threshold} 分）还差{' '}
                    <b><AnimatedNumber value={Math.max(0, Number(lv.next.threshold) - points)} /></b> 分
                  </>
                ) : '已达满级'}
              </div>
            </Tile>

            <Tile span={7} className="v3-growth-points-tile">
              <div className="v3-growth-points__head">
                <div>
                  <div className="v3-tile__label"><Zap size={15} />累计积分</div>
                  <div className="v3-growth-points__value">
                    <AnimatedNumber value={points} />
                    <em>分</em>
                  </div>
                </div>
                <span className="v3-growth-points__orb" aria-hidden="true"><Zap size={22} /></span>
              </div>
              <div className="v3-growth-stats">
                {statItems.map(({ icon: Icon, label, value, unit }) => (
                  <div key={label} className="v3-growth-stat">
                    <span className="v3-growth-stat__icon"><Icon size={14} /></span>
                    <span className="v3-growth-stat__label">{label}</span>
                    <b><AnimatedNumber value={value} /></b>
                    <em>{unit}</em>
                  </div>
                ))}
              </div>
            </Tile>

            <Tile span={6} className="v3-growth-medal-tile">
              <div className="v3-growth-medal__top">
                <span className="v3-growth-medal__orb is-badge"><Trophy size={23} /></span>
                <div className="v3-growth-medal__copy">
                  <div className="v3-tile__label">徽章</div>
                  <div className="v3-growth-medal__count">
                    <AnimatedNumber value={badgeCount} />
                    <span className="v3-growth-medal__total">/{badges.length}</span>
                  </div>
                  <div className="v3-caption">已解锁徽章数量</div>
                </div>
              </div>
              <Progress value={badges.length ? (badgeCount / badges.length) * 100 : 0} gradient />
            </Tile>

            <Tile span={6} className="v3-growth-medal-tile">
              <div className="v3-growth-medal__top">
                <span className="v3-growth-medal__orb is-achievement"><Star size={23} /></span>
                <div className="v3-growth-medal__copy">
                  <div className="v3-tile__label">成就</div>
                  <div className="v3-growth-medal__count">
                    <AnimatedNumber value={achievementCount} />
                    <span className="v3-growth-medal__total">/{achievements.length}</span>
                  </div>
                  <div className="v3-caption">已达成成就数量</div>
                </div>
              </div>
              <Progress
                value={achievements.length ? (achievementCount / achievements.length) * 100 : 0}
                gradient
              />
            </Tile>
          </div>

          {/* ---- 积分明细 ---- */}
          <section className="v3-growth-section">
            <SectionHead
              title="积分构成"
              sub="每一次答题、复习、交卷与学习时长都会折算成积分"
            />
            {noPoints ? (
              <Card className="v3-aux-error v3-growth-empty-points">
                <Empty
                  icon={<Zap size={26} />}
                  title="还没有积分"
                  text="积分来自答题、复习、交卷与学习时长。做过任意一项，这里会按来源拆出明细。"
                />
              </Card>
            ) : (
              <div className="v3-growth-points">
                {pointsDetail.map((d) => (
                  <Card key={d.source} className="v3-growth-point">
                    <div className="v3-growth-point__label">{d.source} × {d.count}</div>
                    <div className="v3-growth-point__value">
                      <AnimatedNumber value={d.points} format={(n) => `+${Math.round(n)}`} />
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </section>

          {/* ---- 徽章墙 ---- */}
          <section className="v3-growth-section">
            <SectionHead
              title="徽章墙"
              sub={`${badgeCount} / ${badges.length} 枚已解锁`}
            />
            {badges.length === 0 ? (
              <Card className="v3-aux-error">
                <Empty icon={<Trophy size={26} />} title="暂无徽章" text="完成对应学习目标后会自动解锁徽章。" />
              </Card>
            ) : (
              <div className="v3-growth-badges">
                {badges.map((b) => (
                  <Card
                    key={b.code}
                    className={`v3-growth-badge ${b.earned ? 'is-earned' : 'is-locked'}`}
                  >
                    <span className="v3-growth-badge__icon" aria-hidden="true">
                      {b.icon || <Trophy size={24} />}
                    </span>
                    <div className="v3-growth-badge__name">{b.name}</div>
                    <div className="v3-growth-badge__desc">{b.desc}</div>
                    <Badge tone={b.earned ? 'success' : 'outline'} className="v3-growth-badge__state">
                      {b.earned ? '已解锁' : '未解锁'}
                    </Badge>
                  </Card>
                ))}
              </div>
            )}
          </section>

          {/* ---- 成就 ---- */}
          <section className="v3-growth-section">
            <SectionHead
              title="成就"
              sub={`${achievementCount} / ${achievements.length} 项已达成`}
            />
            {achievements.length === 0 ? (
              <Card className="v3-aux-error">
                <Empty icon={<Star size={26} />} title="暂无成就" text="持续学习后，阶段性成就会自动记录在这里。" />
              </Card>
            ) : (
              <div className="v3-growth-achievements">
                {achievements.map((a) => (
                  <Card
                    key={a.code}
                    className={`v3-growth-achievement ${a.earned ? 'is-earned' : 'is-locked'}`}
                  >
                    <span className="v3-growth-achievement__orb">
                      {a.earned ? <Trophy size={19} /> : <Lock size={18} />}
                    </span>
                    <div className="v3-growth-achievement__copy">
                      <div className="v3-growth-achievement__title">
                        {a.earned ? '成就 ' : '锁定 '}{a.name}
                      </div>
                      <div className="v3-growth-achievement__desc">{a.desc}</div>
                    </div>
                    <Badge tone={a.earned ? 'success' : 'outline'} className="v3-growth-badge__state">
                      {a.earned ? '已达成' : '未达成'}
                    </Badge>
                  </Card>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
