import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { request } from '../../api/client'
import { kaoyanApi } from '../../api/kaoyanApi'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, Badge, Button, Card, CardHead, Empty, Field, Input, PageHeader, Select,
  Skeleton, Spinner, Textarea, toastErr, toastOk, cx,
} from '../ui'
import {
  AlertCircle, ArrowRight, BookOpen, Calendar, CheckCircle2, GraduationCap,
  RefreshCw, Send, Sparkles, Trophy,
} from '../icons'

/* ============================================================================
 * 经验卡投稿（Contribute）
 *
 * 仅 alumni 角色可提交结构化经验卡：院校 / 专业 / 年份 / 分数 /
 * 方法论 / 备考依据（≥5 项）。提交后进入 pending 状态，等待管理员审核。
 * 数据源：POST /api/experiences
 * ========================================================================== */

/* 备考依据的 5 个结构化字段（对应 R6「依据字段 ≥5 项」） */
const EVIDENCE_FIELDS = [
  { key: 'subjects', label: '初试科目', placeholder: '如：政治 / 英语一 / 数学一 / 408' },
  { key: 'retest', label: '复试内容', placeholder: '如：笔试 + 面试，笔试考数据结构' },
  { key: 'books', label: '参考书目', placeholder: '如：王道数据结构、操作系统概念' },
  { key: 'schedule', label: '时间安排', placeholder: '如：3-6 月基础，7-9 月强化，10-12 月冲刺' },
  { key: 'notes', label: '注意事项', placeholder: '如：重视真题、保持作息、关注院校公告' },
]

const EMPTY_FORM = {
  school_id: '',
  major_id: '',
  year: String(new Date().getFullYear()),
  score: '',
  content: '',
  methodology: '',
  evidence: EVIDENCE_FIELDS.reduce((acc, f) => { acc[f.key] = ''; return acc }, {}),
}

function numOrNull(v) {
  const s = String(v ?? '').trim()
  if (!s) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

export default function Contribute() {
  const navigate = useNavigate()
  const { user, status: authStatus } = useAuth()

  const [form, setForm] = useState(EMPTY_FORM)
  const [errors, setErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(null)

  const [schools, setSchools] = useState([])
  const [schoolsLoading, setSchoolsLoading] = useState(true)
  const [majors, setMajors] = useState([])
  const [majorsLoading, setMajorsLoading] = useState(false)

  /* 院校候选：进入页面时拉一次（首页 200 条已覆盖主流院校） */
  useEffect(() => {
    let alive = true
    setSchoolsLoading(true)
    kaoyanApi.schools({ page_size: 200, page: 1 })
      .then((d) => {
        if (!alive) return
        const items = Array.isArray(d) ? d : (d?.items || [])
        setSchools(items)
      })
      .catch(() => { if (alive) setSchools([]) })
      .finally(() => { if (alive) setSchoolsLoading(false) })
    return () => { alive = false }
  }, [])

  /* 选中院校后拉取其专业方向，供专业下拉选择 */
  useEffect(() => {
    if (!form.school_id) {
      setMajors([])
      return
    }
    let alive = true
    setMajorsLoading(true)
    kaoyanApi.schoolMajors(form.school_id)
      .then((list) => { if (alive) setMajors(Array.isArray(list) ? list : []) })
      .catch(() => { if (alive) setMajors([]) })
      .finally(() => { if (alive) setMajorsLoading(false) })
    return () => { alive = false }
  }, [form.school_id])

  const schoolOptions = useMemo(
    () => [{ value: '', label: '请选择院校' }, ...schools.map((s) => ({ value: String(s.id), label: s.name }))],
    [schools],
  )
  const majorOptions = useMemo(
    () => [{ value: '', label: '未指定 / 通用' }, ...majors.map((m) => ({ value: String(m.id), label: `${m.code ? m.code + ' ' : ''}${m.name}` }))],
    [majors],
  )

  const setField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setErrors((prev) => ({ ...prev, [key]: '' }))
  }
  const setEvidence = (key, value) => {
    setForm((prev) => ({ ...prev, evidence: { ...prev.evidence, [key]: value } }))
    setErrors((prev) => ({ ...prev, evidence: '' }))
  }

  const validate = useCallback(() => {
    const next = {}
    if (!form.school_id) next.school_id = '请选择院校'
    const yearNum = numOrNull(form.year)
    if (yearNum == null) next.year = '请填写有效的年份'
    else if (yearNum < 1990 || yearNum > 2100) next.year = '年份范围异常'
    if (!form.content.trim()) next.content = '请填写经验内容'
    if (form.content.trim().length < 20) next.content = '经验内容至少 20 字'
    if (!form.methodology.trim()) next.methodology = '请填写方法论'
    const filledEvidence = EVIDENCE_FIELDS.filter((f) => form.evidence[f.key]?.trim())
    if (filledEvidence.length < 1) next.evidence = '请至少填写一项备考依据'
    setErrors(next)
    return Object.keys(next).length === 0
  }, [form])

  const submit = async () => {
    if (!validate()) {
      toastErr('请补全必填项后再提交')
      return
    }
    setSubmitting(true)
    try {
      const body = {
        school_id: Number(form.school_id),
        major_id: numOrNull(form.major_id),
        year: Number(form.year),
        score: numOrNull(form.score),
        content: form.content.trim(),
        methodology: form.methodology.trim(),
        evidence: EVIDENCE_FIELDS.reduce((acc, f) => {
          const v = form.evidence[f.key]?.trim()
          if (v) acc[f.key] = v
          return acc
        }, {}),
      }
      const d = await request('/experiences', { method: 'POST', body })
      setSubmitted(d)
      setForm(EMPTY_FORM)
      toastOk('经验卡已提交，等待管理员审核')
    } catch (e) {
      toastErr(e?.message || '提交失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  const reset = () => {
    setForm(EMPTY_FORM)
    setErrors({})
    setSubmitted(null)
  }

  const header = (
    <PageHeader
      eyebrow="CONTRIBUTE · 经验投稿"
      title="分享我的上岸经验"
      sub="结构化记录你的备考历程 · 经管理员审核后公开展示给后来者"
      actions={(
        <Link className="v3-btn v3-btn--tonal" to="/alumni">
          查看经验广场 <ArrowRight size={15} />
        </Link>
      )}
    />
  )

  /* ---------- 鉴权：未登录 / 非 alumni ---------- */
  if (authStatus === 'loading') {
    return (
      <div className="v3-stack contribute-page">
        {header}
        <Card><Skeleton height={120} /></Card>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="v3-stack contribute-page">
        {header}
        <Card>
          <Empty
            icon={<GraduationCap size={26} />}
            title="请先登录"
            text="分享上岸经验需要登录已上岸账号（alumni 角色）。"
            action={<Button variant="gradient" icon={<ArrowRight size={15} />} onClick={() => navigate('/login', { state: { from: '/contribute' } })}>去登录</Button>}
          />
        </Card>
      </div>
    )
  }

  if (user.role !== 'alumni') {
    return (
      <div className="v3-stack contribute-page">
        {header}
        <Alert tone="warning" icon={<AlertCircle size={18} />}>
          <p>当前账号角色为 <b>{user.role || '未知'}</b>，仅 <b>alumni（已上岸）</b> 角色可提交经验卡。如需调整角色，请联系管理员。</p>
        </Alert>
        <Card>
          <Empty
            icon={<GraduationCap size={26} />}
            title="权限不足"
            text="经验卡投稿仅对已上岸用户开放。"
            action={<Link className="v3-btn v3-btn--tonal" to="/alumni">返回经验广场</Link>}
          />
        </Card>
      </div>
    )
  }

  /* ---------- 提交成功 ---------- */
  if (submitted) {
    return (
      <div className="v3-stack contribute-page">
        {header}
        <Card className="contribute-success">
          <div className="contribute-success__orb" aria-hidden="true">
            <CheckCircle2 size={36} />
          </div>
          <h2 className="contribute-success__title">经验卡已提交</h2>
          <p className="contribute-success__text">
            你的上岸经验已提交，当前状态为<b>待审核</b>。管理员审核通过后，该经验卡将出现在经验广场中供其他同学参考。
          </p>
          {submitted.id ? <Badge tone="warning">编号 #{submitted.id} · 待审核</Badge> : null}
          <div className="contribute-success__actions">
            <Button variant="gradient" onClick={reset}>再分享一条</Button>
            <Link className="v3-btn v3-btn--tonal" to="/alumni">查看经验广场</Link>
          </div>
        </Card>
      </div>
    )
  }

  /* ---------- 表单 ---------- */
  const filledEvidenceCount = EVIDENCE_FIELDS.filter((f) => form.evidence[f.key]?.trim()).length

  return (
    <div className="v3-stack contribute-page">
      {header}

      <Alert tone="info" icon={<Sparkles size={18} />}>
        <p>请如实填写上岸经验。提交后进入待审核状态，管理员审核通过后会公开至经验广场，并纳入 RAG 知识检索供其他同学查阅。</p>
      </Alert>

      <Card className="contribute-form">
        <CardHead
          icon={<GraduationCap size={17} />}
          title="经验卡信息"
          sub="带 * 为必填项；备考依据建议至少填写 3 项，便于后来者复用"
        />

        <div className="contribute-form__grid">
          <Field label="院校 *" htmlFor="exp-school" error={errors.school_id}>
            <Select
              id="exp-school"
              aria-label="选择院校"
              value={form.school_id}
              onChange={(e) => { setField('school_id', e.target.value); setField('major_id', '') }}
              options={schoolOptions}
              disabled={schoolsLoading}
            />
          </Field>

          <Field label="专业方向" htmlFor="exp-major" hint="可选，未指定表示通用经验">
            <Select
              id="exp-major"
              aria-label="选择专业方向"
              value={form.major_id}
              onChange={(e) => setField('major_id', e.target.value)}
              options={majorOptions}
              disabled={!form.school_id || majorsLoading}
            />
          </Field>

          <Field label="上岸年份 *" htmlFor="exp-year" error={errors.year}>
            <Input
              id="exp-year"
              type="number"
              placeholder="如 2025"
              value={form.year}
              onChange={(e) => setField('year', e.target.value)}
            />
          </Field>

          <Field label="初试总分" htmlFor="exp-score" hint="可选">
            <Input
              id="exp-score"
              type="number"
              placeholder="如 380"
              value={form.score}
              onChange={(e) => setField('score', e.target.value)}
            />
          </Field>
        </div>

        <div className="contribute-form__section">
          <Field label="经验内容 *" htmlFor="exp-content" error={errors.content} hint="你的上岸故事与核心经验，至少 20 字">
            <Textarea
              id="exp-content"
              rows={5}
              placeholder="例如：双非跨考 408，初试 380+ 上岸某 211 计算机学硕。整体节奏是…"
              value={form.content}
              onChange={(e) => setField('content', e.target.value)}
              style={{ width: '100%' }}
            />
          </Field>
        </div>

        <div className="contribute-form__section">
          <Field label="方法论 *" htmlFor="exp-methodology" error={errors.methodology} hint="各科复习方法、阶段划分、资料选择等">
            <Textarea
              id="exp-methodology"
              rows={5}
              placeholder="例如：数学一 3-6 月基础轮（跟张宇），7-9 月强化轮（660+880），10-12 月真题与冲刺…"
              value={form.methodology}
              onChange={(e) => setField('methodology', e.target.value)}
              style={{ width: '100%' }}
            />
          </Field>
        </div>

        <div className="contribute-form__section">
          <div className="contribute-form__label">
            <BookOpen size={15} />
            <span>备考依据</span>
            <Badge tone={filledEvidenceCount >= 1 ? 'success' : 'outline'}>{filledEvidenceCount}/{EVIDENCE_FIELDS.length} 项已填</Badge>
          </div>
          {errors.evidence ? <div className="contribute-form__err">{errors.evidence}</div> : null}
          <div className="contribute-form__evidence">
            {EVIDENCE_FIELDS.map((f) => (
              <Field key={f.key} label={f.label}>
                <Textarea
                  rows={2}
                  placeholder={f.placeholder}
                  value={form.evidence[f.key]}
                  onChange={(e) => setEvidence(f.key, e.target.value)}
                  style={{ width: '100%' }}
                />
              </Field>
            ))}
          </div>
        </div>

        <div className="contribute-form__actions">
          <Button variant="gradient" icon={<Send size={16} />} loading={submitting} onClick={submit} disabled={submitting}>
            {submitting ? '提交中…' : '提交经验卡'}
          </Button>
          <Button variant="text" onClick={reset} disabled={submitting}>清空表单</Button>
        </div>
      </Card>

      <p className="contribute-footnote">
        提交即表示你同意将经验内容公开展示并用于知识检索。请勿包含个人隐私信息（如身份证号、手机号等）。
      </p>
    </div>
  )
}
