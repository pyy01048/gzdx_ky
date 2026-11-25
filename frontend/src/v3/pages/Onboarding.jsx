/* ============================================================================
 * 首跑初始化向导（P1）
 *
 * 触发：登录成功后 GET /goals 返回 configured === false（见 Login.jsx）。
 * 四步：① 目标院校/专业/总分 ② 届数（初试日期由后端权威日历给出）
 *       ③ 每日学习配额 ④ 备考科目。
 * 每一步都可「跳过此步」，任何时刻可「跳过引导」—— 完成/跳过均进入 /hub，
 * 后续随时可在「设置」页补全，不做强拦截。
 * ========================================================================== */
import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { goalsApi } from '../../api/client'
import { refreshSubjectConfig } from '../../hooks/useSubjectConfig'
import {
  Button, Card, Chip, Field, Input, PageHeader, Select, toastOk, toastErr,
} from '../ui'
import { Reveal } from '../motion'
import {
  ArrowRight, BookOpen, CalendarClock, CheckCircle2, Gauge, School, Target,
} from '../icons'
import '../styles/pages.css'

const STEPS = [
  { key: 'goal', title: '目标院校', sub: '想考哪里？先立个靶子，之后随时可改。', icon: School },
  { key: 'calendar', title: '考试届数', sub: '选择你是哪一届考生，初试日期按官方日历自动确定。', icon: CalendarClock },
  { key: 'quota', title: '每日配额', sub: '每天打算学多少？留空表示暂不设定。', icon: Gauge },
  { key: 'subjects', title: '备考科目', sub: '勾选你实际要考的科目，计入复习进度统计。', icon: BookOpen },
]

const numOrNull = (v) => {
  const s = String(v ?? '').trim()
  if (!s) return null
  const n = Number(s)
  return Number.isFinite(n) && n >= 0 ? n : null
}

export default function Onboarding() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [saving, setSaving] = useState(false)

  /* ① 目标 */
  const [school, setSchool] = useState('')
  const [major, setMajor] = useState('')
  const [score, setScore] = useState('')
  /* ② 届数 */
  const [cal, setCal] = useState(null)
  const [year, setYear] = useState('')
  /* ③ 配额 */
  const [quota, setQuota] = useState({ newWords: '', reviewWords: '', questions: '', focus: '' })
  /* ④ 科目 */
  const [subjCfg, setSubjCfg] = useState(null)
  const [exam, setExam] = useState([])
  const [support, setSupport] = useState([])

  /* P1（F-06）：title 由 App 的 RouteTitle 从 ROUTE_META 统一派生 */

  /* 预填已有档案：任何一路失败都不阻塞向导（对应步骤退化为空表单） */
  useEffect(() => {
    let alive = true
    Promise.allSettled([goalsApi.list(), goalsApi.examCalendar(), goalsApi.subjects()])
      .then(([g, c, s]) => {
        if (!alive) return
        if (g.status === 'fulfilled') {
          const goal = Array.isArray(g.value) ? (g.value[0] || {}) : (g.value || {})
          setSchool(goal.university || '')
          setMajor(goal.major || '')
          const total = goal.score_targets?.total ?? goal.total_score_target
          if (total != null) setScore(String(total))
          const t = goal.daily_targets || {}
          setQuota({
            newWords: t.new_words == null ? '' : String(t.new_words),
            reviewWords: t.review_words == null ? '' : String(t.review_words),
            questions: t.questions == null ? '' : String(t.questions),
            focus: t.focus_minutes == null ? '' : String(t.focus_minutes),
          })
        }
        if (c.status === 'fulfilled' && c.value) {
          setCal(c.value)
          setYear(String(c.value.exam_year || ''))
        }
        if (s.status === 'fulfilled' && s.value) {
          setSubjCfg(s.value)
          setExam(s.value.exam_subjects || [])
          setSupport(s.value.support_subjects || [])
        }
      })
    return () => { alive = false }
  }, [])

  const finish = () => navigate('/hub', { replace: true })
  const advance = () => {
    if (step < STEPS.length - 1) setStep(step + 1)
    else finish()
  }

  const saveAndNext = async () => {
    if (saving) return
    setSaving(true)
    try {
      if (step === 0) {
        await goalsApi.update({
          university: school.trim() || null,
          major: major.trim() || null,
          total_score_target: numOrNull(score),
        })
      } else if (step === 1) {
        if (year) {
          const d = await goalsApi.updateExamCalendar({ exam_year: Number(year) })
          setCal(d)
        }
      } else if (step === 2) {
        await goalsApi.update({
          daily_new_words: numOrNull(quota.newWords),
          daily_review_words: numOrNull(quota.reviewWords),
          daily_questions: numOrNull(quota.questions),
          daily_focus_minutes: numOrNull(quota.focus),
        })
      } else {
        await goalsApi.updateSubjects({ exam_subjects: exam, support_subjects: support })
        refreshSubjectConfig(true)
      }
      toastOk(step === STEPS.length - 1 ? '初始化完成，开始备考吧' : '已保存')
      advance()
    } catch (e) {
      toastErr(`保存失败：${e?.message || '后端不可达'}，可先跳过此步`)
    } finally {
      setSaving(false)
    }
  }

  const toggle = (list, setList, name) => {
    setList(list.includes(name) ? list.filter((x) => x !== name) : [...list, name])
  }

  const meta = STEPS[step]
  const StepIcon = meta.icon
  const knownSubjects = subjCfg?.all_known || []

  return (
    <div className="v3-onboard">
      <PageHeader
        eyebrow={`初始化引导 · 第 ${step + 1} / ${STEPS.length} 步`}
        title="把备考的基本盘先搭起来"
        sub="每一步都可以跳过，之后随时在「设置」页补全。"
        icon={<Target size={22} />}
        actions={<Button variant="text" onClick={finish}>跳过引导</Button>}
      />

      <div className="v3-onboard__steps" role="list" aria-label="引导步骤">
        {STEPS.map((s, i) => (
          <span
            key={s.key}
            role="listitem"
            className={`v3-onboard__step${i === step ? ' is-active' : ''}${i < step ? ' is-done' : ''}`}
            aria-current={i === step ? 'step' : undefined}
          >
            {i < step ? <CheckCircle2 size={14} /> : <s.icon size={14} />}
            {s.title}
          </span>
        ))}
      </div>

      <Reveal key={meta.key}>
        <Card className="v3-onboard__card">
          <div className="v3-onboard__head">
            <span className="v3-onboard__icon"><StepIcon size={18} /></span>
            <div>
              <div className="v3-onboard__title">{meta.title}</div>
              <div className="v3-onboard__sub">{meta.sub}</div>
            </div>
          </div>

          {step === 0 ? (
            <div className="v3-onboard__form">
              <Field label="目标院校" htmlFor="ob-school" hint="可留空，之后在设置页选择">
                <Input id="ob-school" placeholder="如：目标院校" value={school}
                  onChange={(e) => setSchool(e.target.value)} maxLength={64} />
              </Field>
              <Field label="目标专业" htmlFor="ob-major">
                <Input id="ob-major" placeholder="如：计算机技术" value={major}
                  onChange={(e) => setMajor(e.target.value)} maxLength={64} />
              </Field>
              <Field label="总分目标" htmlFor="ob-score" hint="满分 500（部分专业 300）">
                <Input id="ob-score" type="number" min="0" max="500" placeholder="如：360"
                  value={score} onChange={(e) => setScore(e.target.value)} />
              </Field>
            </div>
          ) : null}

          {step === 1 ? (
            <div className="v3-onboard__form">
              <Field label="考试届数" htmlFor="ob-year"
                hint={cal ? `${cal.source || '后端权威日历'}${cal.is_official ? '' : ' · 预估日期，以研招网公告为准'}` : '日历加载中，可直接跳过'}>
                <Select id="ob-year" value={year} onChange={(e) => setYear(e.target.value)}>
                  {(cal?.year_options || (year ? [Number(year)] : [])).map((y) => (
                    <option key={y} value={y}>{y} 届</option>
                  ))}
                </Select>
              </Field>
              {cal?.exam_date ? (
                <p className="v3-onboard__note">
                  <CalendarClock size={14} /> 初试日期：{cal.exam_date}
                  {cal.days_left != null && cal.days_left >= 0 ? ` · 还有 ${cal.days_left} 天` : ''}
                </p>
              ) : null}
            </div>
          ) : null}

          {step === 2 ? (
            <div className="v3-onboard__form v3-onboard__form--grid">
              <Field label="每日新词（个）" htmlFor="ob-new-words">
                <Input id="ob-new-words" type="number" min="0" placeholder="如：20"
                  value={quota.newWords} onChange={(e) => setQuota((q) => ({ ...q, newWords: e.target.value }))} />
              </Field>
              <Field label="每日复习词（个）" htmlFor="ob-review-words">
                <Input id="ob-review-words" type="number" min="0" placeholder="如：50"
                  value={quota.reviewWords} onChange={(e) => setQuota((q) => ({ ...q, reviewWords: e.target.value }))} />
              </Field>
              <Field label="每日刷题（题）" htmlFor="ob-questions">
                <Input id="ob-questions" type="number" min="0" placeholder="如：30"
                  value={quota.questions} onChange={(e) => setQuota((q) => ({ ...q, questions: e.target.value }))} />
              </Field>
              <Field label="每日专注（分钟）" htmlFor="ob-focus">
                <Input id="ob-focus" type="number" min="0" placeholder="如：120"
                  value={quota.focus} onChange={(e) => setQuota((q) => ({ ...q, focus: e.target.value }))} />
              </Field>
            </div>
          ) : null}

          {step === 3 ? (
            <div className="v3-onboard__form">
              {subjCfg ? (
                <>
                  <div className="v3-onboard__group">
                    <div className="v3-onboard__group-title">考试科目（计入进度）</div>
                    <div className="v3-onboard__chips">
                      {knownSubjects.map((name) => (
                        <Chip key={name} active={exam.includes(name)}
                          onClick={() => toggle(exam, setExam, name)}>{name}</Chip>
                      ))}
                    </div>
                  </div>
                  <div className="v3-onboard__group">
                    <div className="v3-onboard__group-title">专业课支撑科目（不计进度，可查资料出题）</div>
                    <div className="v3-onboard__chips">
                      {knownSubjects.map((name) => (
                        <Chip key={name} active={support.includes(name)}
                          onClick={() => toggle(support, setSupport, name)}>{name}</Chip>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <p className="v3-onboard__note">科目清单加载失败或后端不可达，可跳过此步，稍后在「设置 → 备考科目」配置。</p>
              )}
            </div>
          ) : null}

          <div className="v3-onboard__actions">
            <Button variant="text" onClick={advance} disabled={saving}>跳过此步</Button>
            <Button variant="filled" loading={saving} onClick={saveAndNext}
              trailingIcon={step === STEPS.length - 1 ? <CheckCircle2 size={16} /> : <ArrowRight size={16} />}>
              {step === STEPS.length - 1 ? '完成，进入今日中枢' : '保存并继续'}
            </Button>
          </div>
        </Card>
      </Reveal>
    </div>
  )
}
