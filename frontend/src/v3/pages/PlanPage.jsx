import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { kaoyanApi } from '../../api/kaoyanApi'
import {
  AnimatedNumber, Badge, Button, Card, Empty, LoadingState, PageHeader,
  SectionHead, Select, Tile, toast, toastErr,
} from '../ui'
import {
  AlertCircle, Calendar, CalendarClock, Clock, Flag, Flame, RefreshCw,
  School, Target,
} from '../icons'
import '../styles/aux-v3.css'

/* 阶段色只做视觉分组，不改变后端下发的阶段名。 */
const STAGE_TONE = {
  基础: 'foundation',
  强化: 'strength',
  冲刺: 'sprint',
}
const stageTone = (name) => STAGE_TONE[name] || 'other'

export default function PlanPage() {
  /* null = 不传年份，交给后端按 Goal 配置的届推导（_resolve_plan_year）。
     候选届数同样只认接口下发的 available_years。 */
  const [year, setYear] = useState(null)
  const [roadmap, setRoadmap] = useState(null)
  const [milestones, setMilestones] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [regenBusy, setRegenBusy] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([kaoyanApi.roadmap(year), kaoyanApi.milestones(year)])
      .then(([rm, ms]) => { setRoadmap(rm); setMilestones(ms) })
      .catch((e) => {
        setError(e?.message || '规划数据加载失败')
        toast('规划数据加载失败')
      })
      .finally(() => setLoading(false))
  }, [year])

  useEffect(() => { load() }, [load])

  const regenerate = async () => {
    setRegenBusy(true)
    try {
      await kaoyanApi.generatePlan(year)
      const [rm, ms] = await Promise.all([kaoyanApi.roadmap(year), kaoyanApi.milestones(year)])
      setRoadmap(rm)
      setMilestones(ms)
    } catch (e) {
      toastErr(e?.message || '重新生成失败，请稍后重试')
    } finally {
      setRegenBusy(false)
    }
  }

  const stageList = roadmap?.stages || []
  const sortedMilestones = useMemo(
    () => [...(milestones?.milestones || [])].sort((a, b) => (a.start || '').localeCompare(b.start || '')),
    [milestones],
  )

  const goal = roadmap?.goal || {}
  const exam = roadmap?.exam_date
  const daysNumber = Number(roadmap?.days_to_exam)
  const hasDays = roadmap?.days_to_exam != null && Number.isFinite(daysNumber)
  const urgent = hasDays && daysNumber <= 90

  return (
    <div className="v3-aux-page v3-plan">
      <PageHeader
        eyebrow="ROADMAP · 择校计划"
        title="考研规划"
        sub="阶段 → 月 → 周 → 日 三层规划 · 与择校目标联动"
        actions={roadmap ? (
          <div className="v3-plan-actions">
            <Select
              aria-label="选择届数"
              className="v3-plan-year"
              value={year ?? roadmap.year ?? ''}
              onChange={(e) => setYear(Number(e.target.value))}
            >
              {(roadmap.available_years || []).map((y) => (
                <option key={y} value={y}>{y} 考研</option>
              ))}
            </Select>
            <Button
              variant="tonal"
              icon={<RefreshCw size={16} />}
              loading={regenBusy}
              onClick={regenerate}
            >
              重新生成节点
            </Button>
          </div>
        ) : null}
      />

      {loading ? (
        <LoadingState text="正在加载规划…" />
      ) : error || !roadmap ? (
        <Card className="v3-aux-error">
          <Empty
            icon={<AlertCircle size={26} />}
            title="规划数据加载失败"
            text={error || '暂时没有拿到规划数据，请稍后重试。'}
            action={<Button variant="tonal" onClick={load}>重新加载</Button>}
          />
        </Card>
      ) : (
        <>
          {/* ---- 目标概览 ---- */}
          <div className="v3-bento v3-plan-overview">
            <Tile span={3} className="v3-plan-goal">
              <div className="v3-tile__label"><School size={15} />目标院校</div>
              <div className="v3-plan-goal__value">{goal.university || '未设置'}</div>
              <div className="v3-plan-goal__sub">{goal.major || '在择校目标中补充专业方向'}</div>
            </Tile>

            <Tile span={3} className="v3-plan-goal">
              <div className="v3-tile__label"><Target size={15} />总分目标</div>
              {goal.total_score_target ? (
                <div className="v3-plan-goal__value">
                  <AnimatedNumber value={Number(goal.total_score_target)} />
                  <em>分</em>
                </div>
              ) : (
                <div className="v3-plan-goal__value is-muted">未设置</div>
              )}
              <div className="v3-plan-goal__sub">来自当前择校目标</div>
            </Tile>

            <Tile span={3} className="v3-plan-goal">
              <div className="v3-tile__label"><CalendarClock size={15} />初试日期</div>
              <div className="v3-plan-goal__value is-date">
                {exam || '未设置'}
                {roadmap.exam_date_is_official === false && (
                  <span className="v3-plan-estimated">（预估）</span>
                )}
              </div>
              <div className="v3-plan-goal__sub">
                {roadmap.exam_date_is_official === false ? '官方日期尚未公布，按预估日期规划' : '教育部官方公布日期'}
              </div>
            </Tile>

            <Tile span={3} className={`v3-plan-goal v3-plan-countdown ${urgent ? 'is-urgent' : ''}`}>
              <div className="v3-tile__label"><Flame size={15} />距初试</div>
              <div className="v3-plan-countdown__value">
                {hasDays ? (
                  <>
                    <AnimatedNumber value={daysNumber} />
                    <em>天</em>
                  </>
                ) : (
                  <span className="is-muted">—</span>
                )}
              </div>
              <div className="v3-plan-goal__sub">
                {urgent ? '已进入冲刺区间，注意节奏与状态' : '按当前规划节奏推进即可'}
              </div>
            </Tile>
          </div>

          {/* ---- 阶段 → 月 → 周 → 日 ---- */}
          <section className="v3-plan-section">
            <SectionHead
              title="阶段 · 月 · 周 · 日 三层规划"
              sub={`共 ${stageList.length} 个阶段 · 每日执行节奏随阶段推进`}
            />
            {stageList.length === 0 ? (
              <Card className="v3-aux-error">
                <Empty
                  icon={<Calendar size={26} />}
                  title="暂无阶段规划"
                  text="点击「重新生成节点」，让后端按当前目标生成新的规划。"
                />
              </Card>
            ) : (
              <div className="v3-plan-stages">
                {stageList.map((s) => {
                  const tone = stageTone(s.name)
                  return (
                    <Card key={s.name} className={`v3-plan-stage is-${tone}`}>
                      <div className="v3-plan-stage__head">
                        <div className="v3-plan-stage__title-row">
                          <span className="v3-plan-stage__badge">{s.name}</span>
                          <span className="v3-plan-stage__date">
                            <Calendar size={13} />
                            {s.start} ~ {s.end}
                          </span>
                        </div>
                        <p className="v3-plan-stage__goal">{s.goal}</p>
                      </div>

                      <div className="v3-plan-months">
                        {(s.months || []).map((m) => (
                          <div key={m.month} className="v3-plan-month">
                            <div className="v3-plan-month__head">
                              <strong>{m.label}</strong>
                              <span>{m.start} ~ {m.end}</span>
                            </div>
                            <ul className="v3-plan-month__weeks">
                              {(m.weeks || []).map((w, i) => (
                                <li key={i}><i aria-hidden="true" />{w}</li>
                              ))}
                            </ul>
                            {s.daily_routine ? (
                              <div className="v3-plan-month__routine">
                                <Clock size={13} />
                                <span>{s.daily_routine}</span>
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </Card>
                  )
                })}
              </div>
            )}
          </section>

          {/* ---- 关键节点时间线 ---- */}
          <section className="v3-plan-section">
            <SectionHead
              title={`关键节点（${sortedMilestones.length} 个）`}
              sub="按时间顺序排列 · 重要度来自后端规划数据"
            />
            {sortedMilestones.length === 0 ? (
              <Card className="v3-aux-error">
                <Empty
                  icon={<Flag size={26} />}
                  title="暂无关键节点"
                  text="规划生成后，报名、确认、初试等节点会按时间出现在这里。"
                />
              </Card>
            ) : (
              <div className="v3-plan-timeline">
                {sortedMilestones.map((n) => {
                  const stage = stageList.find((s) => s.name === n.stage)
                  const tone = stageTone(stage?.name || n.stage)
                  const daysLeft = Number(n.days_left)
                  const hasDaysLeft = Number.isFinite(daysLeft)
                  const importance = Math.max(0, Math.min(5, Number(n.importance) || 0))
                  const range = n.start && n.end
                    ? `${n.start} ~ ${n.end}`
                    : (n.start || n.end || '日期待定')
                  return (
                    <Card key={n.id} className={`v3-plan-milestone is-${tone}`}>
                      <div className="v3-plan-milestone__top">
                        <span className="v3-plan-milestone__icon"><Flag size={16} /></span>
                        <div className="v3-plan-milestone__title">{n.name}</div>
                        <Badge className="v3-plan-stage-badge">{stage?.name || n.stage || '规划'}</Badge>
                      </div>
                      <div className="v3-plan-milestone__meta">
                        {[n.category, range].filter(Boolean).join(' · ')}
                      </div>
                      <div className="v3-plan-milestone__action">
                        <b>行动：</b>{n.action || '—'}
                      </div>
                      <div className="v3-plan-milestone__foot">
                        <span className={`v3-plan-milestone__days ${hasDaysLeft && daysLeft < 0 ? 'is-past' : ''}`}>
                          {hasDaysLeft
                            ? (daysLeft >= 0 ? `还有 ${daysLeft} 天` : `已过 ${-daysLeft} 天`)
                            : '日期待定'}
                        </span>
                        <span className="v3-plan-milestone__importance">
                          <span className="v3-plan-dots" aria-hidden="true">
                            {Array.from({ length: 5 }, (_, i) => (
                              <i key={i} className={i < importance ? 'on' : ''} />
                            ))}
                          </span>
                          重要度 {n.importance}/5
                        </span>
                      </div>
                    </Card>
                  )
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
