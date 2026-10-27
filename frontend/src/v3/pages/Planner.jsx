import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { plannerApi } from '../../api/client'
import useStore from '../../store/useStore'
import { daysBetween, todayStr } from '../../utils/date'
import { examDaysLeft, resolveExamDate } from '../../utils/exam'
import { subjectLabel, useSubjectConfig } from '../../hooks/useSubjectConfig'
import {
  Badge, Button, Card, CardHead, Chip, Dialog, Empty, Field, IconButton, Input, Progress,
  Segmented, Select, Skeleton, Textarea, Tile, toast, toastErr, toastOk,
} from '../ui'
import {
  Brain, Calendar, CalendarClock, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clock,
  Edit, Flame, Layers, ListChecks, Plus, RefreshCw, Settings, Sun, Target, Timer, Trash, Trophy,
  Wand, X,
} from '../icons'
import '../styles/planner-v3.css'
import '../styles/study-glass.css'

/* ============================================================
   学习计划表 · 日 / 周月 / 艾宾浩斯 / 早起 / 阶段复习
   ============================================================ */
const TABS = [
  { value: 'daily', label: '日计划', icon: <Calendar size={15} /> },
  { value: 'weekmonth', label: '周月计划', icon: <Timer size={15} /> },
  { value: 'ebbinghaus', label: '艾宾浩斯', icon: <Brain size={15} /> },
  { value: 'earlybird', label: '早起打卡', icon: <Sun size={15} /> },
  { value: 'phase', label: '阶段复习', icon: <Layers size={15} /> },
]

const TASK_SLOTS = 4
const SUBJECT_BADGE = ['primary', 'danger', 'gradient', 'success', 'warning']

const CYCLES = [
  { key: '5min', label: '5分钟', ms: 5 * 60 * 1000 },
  { key: '30min', label: '30分钟', ms: 30 * 60 * 1000 },
  { key: '12h', label: '12小时', ms: 12 * 3600 * 1000 },
  { key: '1d', label: '1天', ms: 1 * 86400000 },
  { key: '2d', label: '2天', ms: 2 * 86400000 },
  { key: '4d', label: '4天', ms: 4 * 86400000 },
  { key: '7d', label: '7天', ms: 7 * 86400000 },
  { key: '15d', label: '15天', ms: 15 * 86400000 },
  { key: '1m', label: '1个月', ms: 30 * 86400000 },
]

/* 默认 9 点节奏的 cycle_config（与后端 DEFAULT_EBBINGHAUS_CYCLES 对齐） */
const DEFAULT_CYCLE_CONFIG = CYCLES.map((c) => ({
  key: c.key,
  label: c.label,
  offset_minutes: Math.round(c.ms / 60000),
}))

/** 取条目的周期配置；旧数据没有 cycle_config 时降级为默认 9 点。 */
function cycleConfigOf(item) {
  const cfg = item && Array.isArray(item.cycle_config) && item.cycle_config.length
    ? item.cycle_config
    : DEFAULT_CYCLE_CONFIG
  return cfg.map((c) => ({
    key: c && c.key != null ? c.key : `c${Math.random().toString(36).slice(2, 8)}`,
    label: (c && c.label) || '',
    offset_minutes: Number(c && c.offset_minutes) || 0,
  }))
}

/** 生成默认 9 点的 review_times（基于学习时间），用于旧数据降级。 */
function defaultReviewTimes(item) {
  const base = new Date(item && item.learn_date ? String(item.learn_date) : '')
  if (isNaN(base.getTime())) return []
  return DEFAULT_CYCLE_CONFIG.map((c) => ({
    key: c.key,
    label: c.label,
    time: new Date(base.getTime() + (c.offset_minutes || 0) * 60000).toISOString(),
    done: false,
  }))
}

/** 取条目的复习时间点数组；缺失时用默认 9 点生成，保证旧数据不崩。 */
function reviewTimesOf(item) {
  const rt = item && Array.isArray(item.review_times) ? item.review_times : null
  if (rt && rt.length) {
    return rt.map((r) => ({
      key: r && r.key != null ? r.key : `rt${Math.random().toString(36).slice(2, 8)}`,
      label: (r && r.label) || (r && r.key) || '复习',
      time: (r && r.time) || '',
      done: !!(r && r.done),
    }))
  }
  return defaultReviewTimes(item)
}

/** 显示复习时间（本地时区 HH:mm / MM-DD HH:mm）。 */
function fmtReviewTime(iso) {
  if (!iso) return '--:--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return String(iso).slice(5, 16).replace('T', ' ')
  const mm = pad2(d.getMonth() + 1)
  const dd = pad2(d.getDate())
  const hh = pad2(d.getHours())
  const mi = pad2(d.getMinutes())
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
    ? `${hh}:${mi}`
    : `${mm}-${dd} ${hh}:${mi}`
}

/** ISO 字符串转 datetime-local 输入值（本地时区）。 */
function isoToLocalInput(iso) {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/** 本地 datetime-local 字符串转 ISO（补秒与毫秒，new Date 按本地时区解析）。 */
function localToIso(localStr) {
  if (!localStr) return ''
  const d = new Date(localStr)
  if (isNaN(d.getTime())) return ''
  return d.toISOString()
}

const pad2 = (n) => String(n).padStart(2, '0')

function slotsOf(value) {
  const base = Array.isArray(value)
    ? value.slice(0, TASK_SLOTS).map((v) => String(v ?? ''))
    : [String(value ?? '')].filter((v) => v !== '')
  while (base.length < TASK_SLOTS) base.push('')
  return base
}

function textOf(value) {
  return Array.isArray(value)
    ? value.map((v) => String(v ?? '').trim()).filter(Boolean).join(' / ')
    : String(value ?? '')
}

function planSubjects(examList, tasks) {
  return Array.from(new Set([...(examList || []), ...Object.keys(tasks || {})]))
}

function pickList(data, key) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data[key])) return data[key]
  if (data && Array.isArray(data.items)) return data.items
  return []
}

function computeStreak(records) {
  const set = new Set(records.map((r) => String(r.date || '').slice(0, 10)))
  const d = new Date(todayStr() + 'T00:00:00')
  if (!set.has(todayStr())) d.setDate(d.getDate() - 1)
  let n = 0
  for (let i = 0; i < 400; i++) {
    const key = d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
    if (!set.has(key)) break
    n++
    d.setDate(d.getDate() - 1)
  }
  return n
}

/* ---------- .ics 日历工具（纯前端 Blob 下载，零依赖） ---------- */
function icsStamp(d) {
  return (
    d.getUTCFullYear()
    + pad2(d.getUTCMonth() + 1)
    + pad2(d.getUTCDate()) + 'T'
    + pad2(d.getUTCHours())
    + pad2(d.getUTCMinutes())
    + pad2(d.getUTCSeconds()) + 'Z'
  )
}

function icsDay(dateStr) {
  return String(dateStr || '').slice(0, 10).replace(/-/g, '')
}

function icsEsc(s) {
  return String(s == null ? '' : s)
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n')
}

function icsFold(line) {
  if (line.length <= 73) return line
  const out = []
  let rest = line
  out.push(rest.slice(0, 73))
  rest = rest.slice(73)
  while (rest.length > 72) {
    out.push(' ' + rest.slice(0, 72))
    rest = rest.slice(72)
  }
  if (rest) out.push(' ' + rest)
  return out.join('\r\n')
}

function buildIcs(events, calName) {
  const now = new Date()
  const L = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//KaoyanArchive//Planner V2//CN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'X-WR-CALNAME:' + icsEsc(calName || '考研学习计划'),
    'X-WR-TIMEZONE:Asia/Shanghai',
  ]
  events.forEach((ev) => {
    L.push('BEGIN:VEVENT')
    L.push('UID:' + ev.uid)
    L.push('DTSTAMP:' + icsStamp(now))
    if (ev.allDay) {
      const d0 = icsDay(ev.day)
      const next = new Date(String(ev.day).slice(0, 10) + 'T00:00:00')
      next.setDate(next.getDate() + 1)
      L.push('DTSTART;VALUE=DATE:' + d0)
      L.push('DTEND;VALUE=DATE:' + (next.getFullYear() + pad2(next.getMonth() + 1) + pad2(next.getDate())))
    } else {
      L.push('DTSTART:' + icsStamp(ev.start))
      L.push('DTEND:' + icsStamp(ev.end || new Date(ev.start.getTime() + 30 * 60000)))
    }
    L.push(icsFold('SUMMARY:' + icsEsc(ev.summary)))
    if (ev.description) L.push(icsFold('DESCRIPTION:' + icsEsc(ev.description)))
    L.push('CATEGORIES:' + icsEsc(ev.category || '考研'))
    if (ev.alarmMin) {
      L.push('BEGIN:VALARM')
      L.push('TRIGGER:-PT' + ev.alarmMin + 'M')
      L.push('ACTION:DISPLAY')
      L.push('DESCRIPTION:' + icsEsc(ev.summary))
      L.push('END:VALARM')
    }
    L.push('END:VEVENT')
  })
  L.push('END:VCALENDAR')
  return L.join('\r\n') + '\r\n'
}

function downloadText(text, filename, mime) {
  const blob = new Blob(['\ufeff' + text], { type: mime || 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

function LoadErrorBar({ title, detail, onRetry }) {
  return (
    <div className="v3-plan-errorbar" role="alert">
      <div>
        <b>{title}</b>
        <span>{detail}</span>
      </div>
      <Button variant="outline" size="sm" onClick={onRetry}>重试</Button>
    </div>
  )
}

function NoSubjects({ ready }) {
  return (
    <Empty
      icon={<Target size={26} />}
      title={ready ? '还没有备考科目' : '正在读取科目配置'}
      text={ready
        ? '计划表按你配置的科目逐科铺开。到「设置 → 目标与概览 → 备考科目」添加后，这里立刻跟着变。'
        : '后端可达后自动带出你在设置里配置的科目；读取期间这里保持为空，不替你假设专业方向。'}
      action={ready ? <Link className="v3-btn v3-btn--filled" to="/settings">配置备考科目</Link> : null}
    />
  )
}

/* ============================================================ */
export default function Planner() {
  const [tab, setTab] = useState('daily')
  const [streak, setStreak] = useState(0)
  const [ebbCount, setEbbCount] = useState(0)
  const [exporting, setExporting] = useState(false)

  const loadOverview = async () => {
    let ok = true
    try {
      const eb = await plannerApi.listEarlyBird()
      const recs = pickList(eb, 'records')
      setStreak(eb && eb.current_streak != null ? eb.current_streak : computeStreak(recs))
    } catch {
      ok = false
    }
    try {
      const ebb = await plannerApi.listEbbinghaus()
      setEbbCount(pickList(ebb, 'items').length)
    } catch {
      ok = false
    }
    return ok
  }

  useEffect(() => { loadOverview() }, [])

  const refreshOverview = async () => {
    const ok = await loadOverview()
    if (ok) toastOk('计划概览已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  const exportIcs = async () => {
    setExporting(true)
    try {
      const events = []
      const nowMs = Date.now()

      let ebbItems = []
      try { ebbItems = pickList(await plannerApi.listEbbinghaus(), 'items') } catch { /* 忽略 */ }
      ebbItems.forEach((item) => {
        if (item.mastered) return
        const base = new Date(item.learn_date || todayStr())
        if (isNaN(base.getTime())) return
        CYCLES.forEach((c) => {
          const start = new Date(base.getTime() + c.ms)
          if (start.getTime() < nowMs) return
          events.push({
            uid: `ebb-${item.id}-${c.key}@kaoyan.local`,
            summary: `记忆 复习(${c.label})：${item.content || ''}`,
            description: `艾宾浩斯记忆曲线复习点\n学科：${item.subject || '未分类'}\n首次学习：${String(item.learn_date || '').slice(0, 16).replace('T', ' ')}`,
            start,
            end: new Date(start.getTime() + 15 * 60000),
            category: '艾宾浩斯复习',
            alarmMin: 5,
          })
        })
      })

      let ebRecords = []
      try { ebRecords = pickList(await plannerApi.listEarlyBird(), 'records') } catch { /* 忽略 */ }
      const lastWake = (ebRecords[0] && ebRecords[0].wake_time
        ? String(ebRecords[0].wake_time).slice(0, 5)
        : '06:30')
      const [wh, wm] = lastWake.split(':').map((x) => Number(x) || 0)
      for (let i = 0; i < 14; i++) {
        const d = new Date(todayStr() + 'T00:00:00')
        d.setDate(d.getDate() + i)
        d.setHours(wh, wm, 0, 0)
        if (d.getTime() < nowMs) continue
        events.push({
          uid: `earlybird-${icsDay(d.toISOString())}-${i}@kaoyan.local`,
          summary: `早起 早起打卡（${lastWake}）`,
          description: `目标起床时间 ${lastWake}，起床后到平台「早起打卡」记录一笔，保持连续天数。`,
          start: d,
          end: new Date(d.getTime() + 20 * 60000),
          category: '早起打卡',
          alarmMin: 10,
        })
      }

      let plans = []
      try { plans = pickList(await plannerApi.listPhase(), 'plans') } catch { /* 忽略 */ }
      for (const p of plans.slice(0, 5)) {
        let reviews = []
        try { reviews = pickList(await plannerApi.getPhaseReviews(p.id), 'reviews') } catch { /* 该接口缺失时跳过 */ }
        reviews.forEach((r) => {
          const day = String(r.date || '').slice(0, 10)
          if (!day) return
          const mm = (r.morning_reviews || []).join('、')
          const ee = (r.evening_reviews || []).join('、')
          events.push({
            uid: `phase-${p.id}-${r.day_num || day}@kaoyan.local`,
            summary: `资料 ${p.name} 第${r.day_num || '?'}天复习`,
            description: [
              mm ? '早间复习任务：' + mm : '',
              ee ? '晚间复习任务：' + ee : '',
              r.completed ? '状态：已完成' : '状态：待完成',
            ].filter(Boolean).join('\n'),
            allDay: true,
            day,
            category: '阶段复习',
          })
        })
      }

      if (!events.length) {
        toast('暂无可导出的日程（先添加艾宾浩斯条目或打一次早起卡）')
        setExporting(false)
        return
      }
      downloadText(buildIcs(events, '考研学习计划'), 'planner.ics')
      toastOk(`已导出 ${events.length} 条日程到 planner.ics`)
    } catch (e) {
      toastErr('导出失败：' + (e.message || '未知错误'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="v3-stack v3-plan">
      <PageHead
        streak={streak}
        ebbCount={ebbCount}
        exporting={exporting}
        onRefresh={refreshOverview}
        onExport={exportIcs}
      />
      <div className="v3-plan-tabs">
        <Segmented options={TABS} value={tab} onChange={setTab} ariaLabel="计划视图" />
      </div>

      {tab === 'daily' && <DailyPlanTab />}
      {tab === 'weekmonth' && <WeekMonthPlanTab />}
      {tab === 'ebbinghaus' && <EbbinghausTab />}
      {tab === 'earlybird' && <EarlyBirdTab onSync={loadOverview} />}
      {tab === 'phase' && <PhaseTab />}
    </div>
  )
}

function PageHead({ streak, ebbCount, exporting, onRefresh, onExport }) {
  return (
    <div className="v3-plan-head">
      <div className="v3-plan-head__glow" aria-hidden="true" />
      <div className="v3-plan-head__inner">
        <div>
          <div className="v3-eyebrow"><Wand size={13} /> 学习节奏</div>
          <h1 className="v3-plan-title">学习计划表</h1>
          <p className="v3-plan-sub">科学规划，高效备考 · 日 / 周 / 月计划 · 艾宾浩斯 · 早起 · 阶段复习</p>
          <div className="v3-plan-head__badges">
            <span className="v3-plan-streak"><Flame size={14} /> 连续早起 {streak} 天</span>
            {ebbCount > 0 && <span className="v3-plan-ebb"><Brain size={14} /> 记忆 {ebbCount} 条</span>}
          </div>
        </div>
        <div className="v3-plan-head__actions">
          <Button variant="outline" icon={<RefreshCw size={15} />} onClick={onRefresh}>刷新概览</Button>
          <Button icon={<Calendar size={15} />} loading={exporting} onClick={onExport}>导出日历 (.ics)</Button>
        </div>
      </div>
    </div>
  )
}

/* ============================================================
   日计划
   ============================================================ */
function DailyPlanTab() {
  const countdown = useStore((s) => s.countdown)
  const settingsExamDate = useStore((s) => s.settings.examDate)
  const { exam, ready: subjectsReady } = useSubjectConfig()
  const [date, setDate] = useState(todayStr())
  const [plan, setPlan] = useState(null)
  const [taskList, setTaskList] = useState([])
  const [timeline, setTimeline] = useState([])
  const [score, setScore] = useState(0)
  const [summary, setSummary] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [quickTitle, setQuickTitle] = useState('')
  const [quickSubject, setQuickSubject] = useState(exam[0] || '')
  const [quickDuration, setQuickDuration] = useState(25)
  /* P2 乐观保存：草稿改动后自动静默落库（详情见下方防抖 effect） */
  const [autoSavedAt, setAutoSavedAt] = useState('')
  const saveTimerRef = useRef(null)
  const lastSavedRef = useRef('')
  const quickRef = useRef(null)
  const dragFrom = useRef(null)

  useEffect(() => {
    setQuickSubject((s) => (exam.includes(s) ? s : (exam[0] || '')))
  }, [exam])

  const loadPlan = useCallback(async () => {
    setLoadErr('')
    setLoading(true)
    try {
      const data = await plannerApi.getDaily(date)
      setPlan(data)
      const rawTasks = data.tasks || {}
      if (Array.isArray(rawTasks)) {
        setTaskList(rawTasks)
      } else {
        const migrated = []
        Object.entries(rawTasks).forEach(([subject, items]) => {
          const list = Array.isArray(items) ? items : [items]
          list.forEach((item, idx) => {
            if (typeof item === 'string' && item.trim()) {
              migrated.push({
                id: `${subject}-${idx}-${Date.now()}`,
                title: item,
                subject,
                duration: 25,
                completed: false,
                subtasks: [],
                order: idx,
              })
            }
          })
        })
        setTaskList(migrated)
      }
      setTimeline(data.timeline || [])
      setScore(data.score || 0)
      setSummary(data.summary || '')
    } catch (e) {
      setLoadErr(e?.message || '后端未响应')
      toastErr('加载日计划失败')
    } finally {
      setLoading(false)
    }
  }, [date])

  useEffect(() => { loadPlan() }, [loadPlan])

  /* ---- P2：草稿自动保存 ------------------------------------------------
     上一版唯一的持久化入口是「保存计划」按钮——用户勾完任务、写完总结，
     忘了点保存就全部丢失（页头也只在手动保存后才提示）。现在改为：
     任何草稿变化后 1.2s 防抖静默保存一次；空草稿不触发（避免只是打开
     看了一眼就悄悄创建一条空日计划记录）；失败不打断输入，手动按钮仍是兜底。 */
  useEffect(() => {
    if (loading) return undefined
    if (!taskList.length && !timeline.length && !score && !summary) return undefined
    const payload = { date, tasks: taskList, timeline, score, summary }
    const stamp = JSON.stringify(payload)
    if (stamp === lastSavedRef.current) return undefined
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null
      plannerApi.saveDaily(payload)
        .then(() => {
          lastSavedRef.current = stamp
          setAutoSavedAt(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
        })
        .catch(() => { /* 静默失败：左上有「保存计划」按钮兜底 */ })
    }, 1200)
    return () => {
      if (saveTimerRef.current) { clearTimeout(saveTimerRef.current); saveTimerRef.current = null }
    }
  }, [loading, date, taskList, timeline, score, summary])

  const savePlan = async () => {
    setSaving(true)
    try {
      const payload = { date, tasks: taskList, timeline, score, summary }
      await plannerApi.saveDaily(payload)
      lastSavedRef.current = JSON.stringify(payload) /* 手动保存计入防抖基线，避免紧跟着重复一次自动保存 */
      toastOk('日计划已保存')
      loadPlan()
    } catch {
      toastErr('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const addTask = (newTask) => {
    const task = {
      ...newTask,
      id: `task-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      order: taskList.length,
    }
    setTaskList((prev) => [...prev, task])
  }

  const submitQuick = (e) => {
    e.preventDefault()
    const title = quickTitle.trim()
    if (!title) {
      toastErr('请输入任务标题')
      quickRef.current?.focus()
      return
    }
    addTask({
      title,
      subject: quickSubject,
      duration: Number(quickDuration),
      completed: false,
      subtasks: [],
      createdAt: new Date().toISOString(),
    })
    setQuickTitle('')
    quickRef.current?.focus()
  }

  const toggleTask = (taskId) => {
    setTaskList((prev) => prev.map((t) => (t.id === taskId ? { ...t, completed: !t.completed } : t)))
  }
  const deleteTask = (taskId) => setTaskList((prev) => prev.filter((t) => t.id !== taskId))
  const updateTask = (updated) => setTaskList((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))

  /* ---- P2：重排统一走 moveTask(from, to) -------------------------------
     上一版只有 HTML5 拖拽一条路（draggable + onDrop），触屏与键盘用户
     完全无法调整顺序。现在拖拽与「上移/下移」按钮共用同一实现。 */
  const moveTask = (from, to) => {
    if (from == null || to == null || from === to) return
    setTaskList((prev) => {
      if (from < 0 || to < 0 || from >= prev.length || to >= prev.length) return prev
      const next = [...prev]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return next.map((t, i) => ({ ...t, order: i }))
    })
  }
  const reorderTask = (toIndex) => {
    const from = dragFrom.current
    dragFrom.current = null
    moveTask(from, toIndex)
  }

  const totalTasks = taskList.length
  const completedTasks = taskList.filter((t) => t.completed).length
  const pct = totalTasks ? Math.round((completedTasks / totalTasks) * 100) : 0

  const remain = plan && plan.days_to_exam != null
    ? plan.days_to_exam
    : examDaysLeft(resolveExamDate(settingsExamDate || (countdown && countdown.exam_date), null))

  if (loading && !plan) {
    return (
      <div className="v3-stack">
        <Card>
          <div className="v3-plan-toolbar">
            <Skeleton width={160} height={38} />
            <Skeleton width={220} height={32} />
            <div style={{ flex: 1 }} />
            <Skeleton width={110} height={40} />
          </div>
          <Skeleton height={6} style={{ marginTop: 18 }} />
        </Card>
        <div className="v3-plan-daily">
          <Card>
            <CardHead title="今日学习任务" sub="正在加载今日计划…" />
            <div className="v3-stack">
              <Skeleton height={56} />
              <Skeleton height={56} />
              <Skeleton height={56} />
            </div>
          </Card>
          <Card>
            <CardHead title="今日评价" sub="正在加载…" />
            <Skeleton height={120} />
          </Card>
        </div>
      </div>
    )
  }

  if (loadErr && !plan) {
    return (
      <LoadErrorBar
        title="加载日计划失败"
        detail={`${loadErr}。未加载到任何数据，暂不显示编辑区；请检查后端后重试。`}
        onRetry={loadPlan}
      />
    )
  }

  return (
    <div className="v3-stack">
      {loadErr && (
        <LoadErrorBar
          title="加载日计划失败"
          detail={`${loadErr}。下方是上一次成功加载的内容，可能不是最新。`}
          onRetry={loadPlan}
        />
      )}

      <Card variant="tonal" className="v3-plan-dailybar">
        <div className="v3-plan-toolbar">
          <Field label="计划日期" className="v3-plan-datefield">
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="计划日期" />
          </Field>
          <div className="v3-plan-badges">
            {remain != null
              ? <Badge tone="primary">距考研 {remain} 天</Badge>
              : <Badge tone="outline">未设置初试日期</Badge>}
            {plan?.exists ? <Badge tone="success">已有记录</Badge> : <Badge tone="outline">未填写</Badge>}
            <Badge tone="outline">任务 {completedTasks}/{totalTasks}</Badge>
            {autoSavedAt ? <Badge tone="success" title="草稿已自动保存到服务器">已自动保存 {autoSavedAt}</Badge> : null}
          </div>
          <div className="v3-plan-toolbaractions">
            <Button variant="ghost" size="sm" onClick={loadPlan} loading={loading}>重新载入</Button>
            <Button size="sm" onClick={savePlan} loading={saving}>保存计划</Button>
          </div>
        </div>
        <div className="v3-plan-progressrow">
          <Progress value={pct} gradient />
          <b>{pct}%</b>
        </div>
      </Card>

      {subjectsReady && (!exam || exam.length === 0) && (
        <Card><NoSubjects ready={subjectsReady} /></Card>
      )}

      {subjectsReady && exam && exam.length > 0 && (
        <Card className="v3-plan-quick">
          <form className="v3-plan-quickform" onSubmit={submitQuick}>
            <Input
              ref={quickRef}
              value={quickTitle}
              onChange={(e) => setQuickTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') { setQuickTitle(''); e.target.blur() } }}
              placeholder="快速添加任务…（例：背单词 30分钟）"
              aria-label="任务标题"
              className="v3-plan-quickinput"
            />
            <Select
              aria-label="选择科目"
              value={quickSubject}
              onChange={(e) => setQuickSubject(e.target.value)}
              options={exam}
            />
            <Select
              aria-label="预计时长"
              value={quickDuration}
              onChange={(e) => setQuickDuration(Number(e.target.value))}
              options={[15, 25, 45, 60, 90, 120].map((n) => ({ value: n, label: `${n} 分钟` }))}
            />
            <Button type="submit" icon={<Plus size={14} />} disabled={!quickTitle.trim()}>添加</Button>
          </form>
          <div className="v3-plan-quickhint">选择科目与时长，按 Enter 或点击「添加」即可连续创建任务。</div>
        </Card>
      )}

      <div className="v3-plan-daily">
        <Card>
          <CardHead
            icon={<ListChecks size={16} />}
            title="今日学习任务"
            sub={taskList.length ? `${totalTasks} 个任务，${completedTasks} 个已完成` : '使用上方快速添加框创建任务'}
            actions={<Badge tone="outline">{completedTasks}/{totalTasks}</Badge>}
          />
          {taskList.length === 0 ? (
            <Empty
              icon={<ListChecks size={26} />}
              title="还没有任务"
              text="在上方输入任务标题，选择科目和时长，快速添加到今日计划。"
            />
          ) : (
            <div className="v3-plan-tasks">
              {taskList.map((task, index) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  index={index}
                  onToggle={toggleTask}
                  onDelete={deleteTask}
                  onUpdate={updateTask}
                  onDragStart={() => { dragFrom.current = index }}
                  onDrop={() => reorderTask(index)}
                  onMoveUp={() => moveTask(index, index - 1)}
                  onMoveDown={() => moveTask(index, index + 1)}
                  canMoveUp={index > 0}
                  canMoveDown={index < taskList.length - 1}
                />
              ))}
            </div>
          )}
        </Card>

        <Card>
          <CardHead
            icon={<Trophy size={16} />}
            title="今日评价"
            sub="给今天的学习状态留一个刻度"
            actions={(
              <Badge tone={score >= 8 ? 'success' : score >= 5 ? 'warning' : 'outline'}>
                评分 {score}/10
              </Badge>
            )}
          />
          <Field label="今日评分（1-10）">
            <Input
              type="number"
              min="1"
              max="10"
              aria-label="今日评分（1-10）"
              value={score}
              onChange={(e) => setScore(Number(e.target.value))}
            />
          </Field>
          <Progress value={Math.min(100, Math.max(0, score * 10))} gradient className="v3-plan-scorebar" />

          <Field label="今日总结" className="v3-plan-summaryfield">
            <Textarea
              rows="7"
              aria-label="今日总结"
              placeholder="记录今天的学习收获、遇到的问题、明天的计划…"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
            />
          </Field>

          {timeline.length > 0 && (
            <div className="v3-plan-timeline">
              {timeline.slice(0, 6).map((t, i) => (
                <div className="v3-plan-tlitem" key={i}>
                  <span className={`v3-plan-tldot${t && t.done ? ' is-done' : ''}`} />
                  <div>
                    <b>{(t && (t.title || t.content)) || '时间块'}</b>
                    <span>{(t && (t.time || t.range)) || ''}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

function TaskRow({ task, index, onToggle, onDelete, onUpdate, onDragStart, onDrop, onMoveUp, onMoveDown, canMoveUp, canMoveDown }) {
  const [expanded, setExpanded] = useState(false)
  const [newSubtask, setNewSubtask] = useState('')
  const total = (task.subtasks || []).length
  const done = (task.subtasks || []).filter((st) => st.completed).length
  const progress = total ? Math.round((done / total) * 100) : 0

  const addSubtask = (e) => {
    e.preventDefault()
    if (!newSubtask.trim()) return
    onUpdate({
      ...task,
      subtasks: [
        ...(task.subtasks || []),
        { title: newSubtask.trim(), completed: false, createdAt: new Date().toISOString() },
      ],
    })
    setNewSubtask('')
  }

  const toggleSubtask = (subIdx) => {
    onUpdate({
      ...task,
      subtasks: (task.subtasks || []).map((st, i) => (i === subIdx ? { ...st, completed: !st.completed } : st)),
    })
  }

  const deleteSubtask = (subIdx) => {
    onUpdate({
      ...task,
      subtasks: (task.subtasks || []).filter((_, i) => i !== subIdx),
    })
  }

  return (
    <div
      className={`v3-plan-task${task.completed ? ' is-completed' : ''}`}
      draggable
      onDragStart={onDragStart}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      <div className="v3-plan-task__main">
        <input
          type="checkbox"
          className="v3-plan-check"
          checked={!!task.completed}
          onChange={() => onToggle(task.id)}
          aria-label={`标记「${task.title}」为${task.completed ? '未完成' : '已完成'}`}
        />
        <div className="v3-plan-task__content">
          <span className="v3-plan-task__title">{task.title}</span>
          <div className="v3-plan-task__meta">
            {task.subject && <Badge tone="outline">{task.subject}</Badge>}
            {task.duration && <Badge tone="primary">{task.duration} 分钟</Badge>}
            {total > 0 && <Badge tone="success">子任务 {done}/{total}</Badge>}
          </div>
        </div>
        <div className="v3-plan-task__actions">
          <span className="v3-plan-task__reorder" aria-hidden={false}>
            <IconButton
              label={`上移「${task.title}」`}
              size="sm"
              icon={<ChevronUp size={15} />}
              disabled={!canMoveUp}
              onClick={onMoveUp}
            />
            <IconButton
              label={`下移「${task.title}」`}
              size="sm"
              icon={<ChevronDown size={15} />}
              disabled={!canMoveDown}
              onClick={onMoveDown}
            />
          </span>
          {total > 0 && (
            <IconButton
              label={expanded ? '收起子任务' : '展开子任务'}
              size="sm"
              icon={expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
              onClick={() => setExpanded((v) => !v)}
            />
          )}
          <IconButton
            label={`删除任务「${task.title}」`}
            size="sm"
            icon={<Trash size={14} />}
            onClick={() => onDelete(task.id)}
          />
        </div>
      </div>

      {total > 0 && <Progress value={progress} className="v3-plan-subprogress" />}

      {expanded && (
        <div className="v3-plan-subtasks">
          {(task.subtasks || []).map((st, idx) => (
            <div className="v3-plan-subtask" key={`${st.title}-${idx}`}>
              <input
                type="checkbox"
                className="v3-plan-check is-small"
                checked={!!st.completed}
                onChange={() => toggleSubtask(idx)}
                aria-label={`标记子任务「${st.title}」为${st.completed ? '未完成' : '已完成'}`}
              />
              <span className={st.completed ? 'is-done' : ''}>{st.title}</span>
              <IconButton
                label={`删除子任务「${st.title}」`}
                size="sm"
                icon={<X size={13} />}
                onClick={() => deleteSubtask(idx)}
              />
            </div>
          ))}
          <form className="v3-plan-subadd" onSubmit={addSubtask}>
            <Input
              value={newSubtask}
              onChange={(e) => setNewSubtask(e.target.value)}
              placeholder="+ 添加子任务"
              aria-label="新子任务标题"
            />
            <Button variant="ghost" size="sm" type="submit" disabled={!newSubtask.trim()}>添加</Button>
          </form>
        </div>
      )}
    </div>
  )
}

/* ============================================================
   周 / 月计划
   ============================================================ */
function WeekMonthPlanTab() {
  const { exam, ready: subjectsReady } = useSubjectConfig()
  const [mode, setMode] = useState('month')
  const [year, setYear] = useState(new Date().getFullYear())
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const [weekStart, setWeekStart] = useState(() => {
    const d = new Date()
    const dow = (d.getDay() + 6) % 7
    d.setDate(d.getDate() - dow)
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
  })
  const [plan, setPlan] = useState(null)
  const [tasks, setTasks] = useState({})
  const [completion, setCompletion] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')

  const loadPlan = useCallback(async () => {
    setLoadErr('')
    setLoading(true)
    try {
      const data = mode === 'month'
        ? await plannerApi.getMonth(year, month)
        : await plannerApi.getWeek(weekStart)
      setPlan(data)
      setTasks(data.tasks || {})
      setCompletion(data.completion || '')
    } catch (e) {
      setLoadErr(e?.message || '后端未响应')
      toastErr('加载计划失败')
    } finally {
      setLoading(false)
    }
  }, [mode, year, month, weekStart])

  useEffect(() => { loadPlan() }, [loadPlan])

  const savePlan = async () => {
    setSaving(true)
    try {
      if (mode === 'month') {
        await plannerApi.saveMonth({ year, month, tasks, completion })
        toastOk('月计划已保存')
      } else {
        await plannerApi.saveWeek({ week_start: weekStart, tasks, completion })
        toastOk('周计划已保存')
      }
      loadPlan()
    } catch {
      toastErr('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const shiftWeek = (delta) => {
    const d = new Date(weekStart + 'T00:00:00')
    d.setDate(d.getDate() + delta * 7)
    setWeekStart(d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()))
  }

  const weekEnd = useMemo(() => {
    const d = new Date(weekStart + 'T00:00:00')
    d.setDate(d.getDate() + 6)
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
  }, [weekStart])

  const title = mode === 'month' ? `${year}年${month}月学习目标` : `${weekStart} ~ ${weekEnd} 本周目标`
  const subjects = useMemo(() => planSubjects(exam, tasks), [exam, tasks])

  if (loadErr && !plan) {
    return (
      <LoadErrorBar
        title="加载周 / 月计划失败"
        detail={`${loadErr}。未加载到任何数据，暂不显示编辑区；请检查后端后重试。`}
        onRetry={loadPlan}
      />
    )
  }

  return (
    <div className="v3-stack">
      {loadErr && (
        <LoadErrorBar
          title="加载周 / 月计划失败"
          detail={`${loadErr}。下方是上一次成功加载的内容，可能不是最新。`}
          onRetry={loadPlan}
        />
      )}

      <Card variant="tonal">
        <div className="v3-plan-toolbar">
          <Segmented
            ariaLabel="计划周期"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'month', label: '月计划', icon: <Calendar size={14} /> },
              { value: 'week', label: '周计划', icon: <Timer size={14} /> },
            ]}
          />
          {mode === 'month' ? (
            <div className="v3-plan-period">
              <Select
                aria-label="选择年份"
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                options={Array.from({ length: 4 }, (_, i) => new Date().getFullYear() - 1 + i)
                  .concat(year)
                  .filter((y, i, arr) => arr.indexOf(y) === i)
                  .sort((a, b) => a - b)
                  .map((y) => ({ value: y, label: `${y}年` }))}
              />
              <Select
                aria-label="选择月份"
                value={month}
                onChange={(e) => setMonth(Number(e.target.value))}
                options={Array.from({ length: 12 }, (_, i) => i + 1).map((m) => ({ value: m, label: `${m}月` }))}
              />
            </div>
          ) : (
            <div className="v3-plan-period">
              <Button variant="ghost" size="sm" icon={<ChevronLeft size={14} />} onClick={() => shiftWeek(-1)}>上一周</Button>
              <Input
                type="date"
                value={weekStart}
                onChange={(e) => setWeekStart(e.target.value)}
                aria-label="选择周起始日期"
                className="v3-plan-weekdate"
              />
              <Button variant="ghost" size="sm" trailingIcon={<ChevronRight size={14} />} onClick={() => shiftWeek(1)}>下一周</Button>
            </div>
          )}
          <div className="v3-plan-toolbaractions">
            {plan && (plan.exists ? <Badge tone="success">已有记录</Badge> : <Badge tone="outline">新建中</Badge>)}
            <Button size="sm" onClick={savePlan} loading={saving}>保存</Button>
          </div>
        </div>
      </Card>

      <Card>
        <CardHead
          icon={<Target size={16} />}
          title={title}
          sub={mode === 'month' ? '按月拆解各科任务量' : '周计划以周一为起点'}
          actions={loading ? <Badge tone="outline">加载中…</Badge> : <Badge tone="primary">{subjects.length} 个科目</Badge>}
        />
        {loading && !plan ? (
          <div className="v3-stack">
            <Skeleton height={78} />
            <Skeleton height={78} />
            <Skeleton height={78} />
          </div>
        ) : !subjects.length ? (
          <NoSubjects ready={subjectsReady} />
        ) : (
          <div className="v3-plan-monthfields">
            {subjects.map((subj, i) => (
              <Field
                key={subj}
                label={<Badge tone={SUBJECT_BADGE[i % SUBJECT_BADGE.length]}>{subjectLabel(subj)}</Badge>}
              >
                <Textarea
                  rows={2}
                  aria-label={`${subjectLabel(subj)}${mode === 'month' ? '本月' : '本周'}目标`}
                  placeholder={`${subjectLabel(subj)}${mode === 'month' ? '本月' : '本周'}目标…`}
                  value={textOf(tasks[subj])}
                  onChange={(e) => setTasks((prev) => ({ ...prev, [subj]: e.target.value }))}
                />
              </Field>
            ))}
          </div>
        )}
        <div className="v3-plan-divider" />
        <Field label="完成情况">
          <Textarea
            rows="3"
            aria-label="完成情况"
            placeholder={`${mode === 'month' ? '本月' : '本周'}任务完成情况总结…`}
            value={completion}
            onChange={(e) => setCompletion(e.target.value)}
          />
        </Field>
      </Card>
    </div>
  )
}

/* ============================================================
   艾宾浩斯记忆表
   ============================================================ */

/** 周期编辑器：可增删行，每行 label + offset_minutes。 */
function CycleEditor({ value, onChange, compact }) {
  const updateRow = (idx, patch) => {
    onChange(value.map((c, i) => (i === idx ? { ...c, ...patch } : c)))
  }
  const removeRow = (idx) => {
    if (value.length <= 1) return
    onChange(value.filter((_, i) => i !== idx))
  }
  const addRow = () => {
    const lastOffset = value.length ? Number(value[value.length - 1].offset_minutes) || 0 : 0
    onChange([
      ...value,
      {
        key: `c${value.length + 1}`,
        label: '',
        offset_minutes: lastOffset + 1440,
      },
    ])
  }

  return (
    <div className={`v3-plan-cycleeditor${compact ? ' is-compact' : ''}`}>
      {value.map((c, idx) => (
        <div className="v3-plan-cycleeditor__row" key={c.key || idx}>
          <span className="v3-plan-cycleeditor__idx">{idx + 1}</span>
          <Input
            className="v3-plan-cycleeditor__label"
            aria-label={`复习点 ${idx + 1} 名称`}
            placeholder="如：10分钟 / 1天"
            value={c.label}
            onChange={(e) => updateRow(idx, { label: e.target.value })}
          />
          <Input
            className="v3-plan-cycleeditor__offset"
            type="number"
            min="1"
            aria-label={`复习点 ${idx + 1} 偏移分钟`}
            placeholder="偏移分钟"
            value={Number(c.offset_minutes) || ''}
            onChange={(e) => updateRow(idx, { offset_minutes: Number(e.target.value) })}
          />
          <span className="v3-plan-cycleeditor__unit">分钟后</span>
          <IconButton
            label={`删除复习点 ${idx + 1}`}
            size="sm"
            icon={<Trash size={13} />}
            disabled={value.length <= 1}
            onClick={() => removeRow(idx)}
          />
        </div>
      ))}
      <Button variant="ghost" size="sm" icon={<Plus size={13} />} onClick={addRow}>添加复习点</Button>
    </div>
  )
}

function EbbinghausTab() {
  const { exam } = useSubjectConfig()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [newContent, setNewContent] = useState('')
  const [newSubject, setNewSubject] = useState('')
  const [filterSubject, setFilterSubject] = useState('')
  const [adding, setAdding] = useState(false)
  const [customEnabled, setCustomEnabled] = useState(false)
  const [customCycles, setCustomCycles] = useState(() => [
    { key: 'c1', label: '10分钟', offset_minutes: 10 },
    { key: 'c2', label: '1小时', offset_minutes: 60 },
    { key: 'c3', label: '1天', offset_minutes: 1440 },
    { key: 'c4', label: '2天', offset_minutes: 2880 },
    { key: 'c5', label: '4天', offset_minutes: 5760 },
  ])
  /* 调整节奏弹窗 */
  const [adjustItem, setAdjustItem] = useState(null)
  const [adjustCycles, setAdjustCycles] = useState([])
  const [savingCycles, setSavingCycles] = useState(false)
  /* 改时间弹窗 */
  const [timeItem, setTimeItem] = useState(null)
  const [timePoint, setTimePoint] = useState(null)
  const [timeValue, setTimeValue] = useState('')
  const [savingTime, setSavingTime] = useState(false)

  const memorySubjects = useMemo(
    () => Array.from(new Set([...exam.map(subjectLabel), '其他'])),
    [exam],
  )
  useEffect(() => {
    setNewSubject((prev) => (prev && memorySubjects.includes(prev) ? prev : memorySubjects[0]))
  }, [memorySubjects])

  const loadItems = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await plannerApi.listEbbinghaus()
      setItems(pickList(data, 'items'))
    } catch (e) {
      setError(e.message || '加载失败')
      toast('加载记忆条目失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadItems() }, [loadItems])

  const addItem = async () => {
    if (!newContent.trim()) return toast('请输入学习内容')
    setAdding(true)
    try {
      const body = { content: newContent, subject: newSubject }
      /* 自定义节奏启用且至少一行有效时携带 custom_cycles，否则走默认 9 点 */
      const validCycles = customEnabled
        ? customCycles.filter((c) => String(c.label || '').trim() && Number(c.offset_minutes) > 0)
        : []
      if (validCycles.length) {
        body.custom_cycles = validCycles.map((c) => ({
          label: String(c.label).trim(),
          offset_minutes: Number(c.offset_minutes),
        }))
      }
      await plannerApi.createEbbinghaus(body)
      toastOk('已添加，复习时间已自动计算')
      setNewContent('')
      loadItems()
    } catch {
      toastErr('添加失败')
    } finally {
      setAdding(false)
    }
  }

  const markReview = async (id, rt) => {
    const label = (rt && rt.label) || (rt && rt.key) || '复习点'
    try {
      await plannerApi.markEbbinghausReview(id, rt.key)
      toastOk(`${label} 复习已完成`)
      loadItems()
    } catch {
      toastErr('标记失败')
    }
  }

  const deleteItem = async (id) => {
    try {
      await plannerApi.deleteEbbinghaus(id)
      toastOk('已删除')
      loadItems()
    } catch {
      toastErr('删除失败')
    }
  }

  /* 基于 review_times 判断到期复习点：time <= now 且未 done 的最近一个点。 */
  const dueCycleOf = (item) => {
    const times = reviewTimesOf(item)
    if (!times.length) return null
    const now = Date.now()
    let due = null
    times.forEach((rt) => {
      const t = new Date(rt.time)
      if (!isNaN(t.getTime()) && t.getTime() <= now && !rt.done) due = rt
    })
    return due
  }

  /* 打开「调整节奏」弹窗：预填当前 cycle_config */
  const openAdjust = (item) => {
    setAdjustItem(item)
    setAdjustCycles(cycleConfigOf(item))
  }

  const saveCycles = async () => {
    if (!adjustItem) return
    const cycles = adjustCycles.filter((c) => String(c.label || '').trim() && Number(c.offset_minutes) > 0)
    if (!cycles.length) return toastErr('至少需要一行有效的复习节奏')
    setSavingCycles(true)
    try {
      await plannerApi.updateEbbinghausCycles(adjustItem.id, {
        cycles: cycles.map((c) => ({ label: String(c.label).trim(), offset_minutes: Number(c.offset_minutes) })),
      })
      toastOk('复习节奏已更新')
      setAdjustItem(null)
      loadItems()
    } catch {
      toastErr('保存失败')
    } finally {
      setSavingCycles(false)
    }
  }

  /* 打开「修改复习时间」弹窗 */
  const openTimeEdit = (item, rt) => {
    setTimeItem(item)
    setTimePoint(rt)
    setTimeValue(isoToLocalInput(rt.time))
  }

  const saveReviewTime = async () => {
    if (!timeItem || !timePoint) return
    const iso = localToIso(timeValue)
    if (!iso) return toastErr('请选择有效的复习时间')
    setSavingTime(true)
    try {
      await plannerApi.updateEbbinghausReviewTime(timeItem.id, {
        key: timePoint.key,
        review_time: iso,
        label: timePoint.label,
      })
      toastOk('复习时间已修改')
      setTimeItem(null)
      setTimePoint(null)
      loadItems()
    } catch {
      toastErr('修改失败')
    } finally {
      setSavingTime(false)
    }
  }

  const shown = useMemo(
    () => (filterSubject ? items.filter((i) => i.subject === filterSubject) : items),
    [items, filterSubject],
  )
  const subjects = useMemo(
    () => Array.from(new Set(items.map((i) => i.subject).filter(Boolean))),
    [items],
  )
  const masteredCount = items.filter((i) => i.mastered).length
  /* 自定义节奏有效的行数 */
  const validCustomCount = customCycles.filter((c) => String(c.label || '').trim() && Number(c.offset_minutes) > 0).length

  return (
    <div className="v3-stack">
      <Card>
        <CardHead
          icon={<Brain size={16} />}
          title="新增记忆条目"
          sub={customEnabled
            ? `按自定义节奏生成 ${validCustomCount || 0} 个复习点`
            : '添加后自动生成 9 个复习时间点'}
          actions={(
            <>
              {customEnabled
                ? <Badge tone="warning">自定义节奏 {validCustomCount || 0} 点</Badge>
                : <Badge tone="primary">9 次复习</Badge>}
              <Button
                variant={customEnabled ? 'filled' : 'outline'}
                size="sm"
                icon={<Settings size={13} />}
                onClick={() => setCustomEnabled((v) => !v)}
              >
                {customEnabled ? '自定义节奏已开启' : '自定义节奏'}
              </Button>
            </>
          )}
        />
        <div className="v3-plan-ebbingadd">
          <Select
            aria-label="选择科目"
            value={newSubject}
            onChange={(e) => setNewSubject(e.target.value)}
            options={memorySubjects}
          />
          <Input
            aria-label="学习内容"
            placeholder="输入学习内容（如：abandon 放弃）"
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') addItem() }}
          />
          <Button icon={<Plus size={14} />} loading={adding} onClick={addItem} disabled={!newContent.trim()}>添加</Button>
        </div>
        {customEnabled && (
          <div className="v3-plan-ebbcustom">
            <CycleEditor value={customCycles} onChange={setCustomCycles} />
          </div>
        )}
        <p className="v3-plan-ebbcycle">
          {customEnabled
            ? `当前自定义节奏：${validCustomCount ? customCycles
              .filter((c) => String(c.label || '').trim() && Number(c.offset_minutes) > 0)
              .map((c) => `${c.label}(${c.offset_minutes}分钟)`).join(' / ') : '尚未填写有效复习点'} —— 可手动修改每个复习点的时间。`
            : `复习节奏：${CYCLES.map((c) => c.label).join(' / ')} —— 完成「1个月」后自动标记为已掌握。`}
        </p>
      </Card>

      <Card>
        <CardHead
          icon={<ListChecks size={16} />}
          title={<>记忆列表 <Badge tone="outline">{shown.length} 条</Badge>{masteredCount > 0 && <Badge tone="success">已掌握 {masteredCount}</Badge>}</>}
          sub="点击复习周期即可打卡；可调整节奏或单个复习点时间"
          actions={(
            <div className="v3-plan-filters">
              <Chip active={filterSubject === ''} onClick={() => setFilterSubject('')}>全部</Chip>
              {subjects.map((s) => (
                <Chip key={s} active={filterSubject === s} onClick={() => setFilterSubject(s)}>{s}</Chip>
              ))}
            </div>
          )}
        />
        {loading ? (
          <div className="v3-stack">
            <Skeleton height={44} />
            <Skeleton height={44} />
            <Skeleton height={44} />
          </div>
        ) : error ? (
          <Empty
            icon={<Brain size={24} />}
            title="记忆列表加载失败"
            text={error}
            action={<Button variant="outline" onClick={loadItems}>重试</Button>}
          />
        ) : shown.length === 0 ? (
          <Empty
            icon={<Brain size={26} />}
            title="暂无记忆条目"
            text="添加第一条内容，系统会按艾宾浩斯遗忘曲线自动排布复习时间点（可自定义节奏）。"
          />
        ) : (
          <div className="v3-plan-tablewrap">
            <table className="v3-plan-table">
              <thead>
                <tr>
                  <th style={{ width: 54 }}>序号</th>
                  <th style={{ width: 84 }}>学科</th>
                  <th>内容</th>
                  <th style={{ width: 108 }}>学习时间</th>
                  <th>复习打卡</th>
                  <th style={{ width: 70 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((item, idx) => {
                  const due = dueCycleOf(item)
                  const times = reviewTimesOf(item)
                  return (
                    <tr key={item.id} className={item.mastered ? 'is-mastered' : undefined}>
                      <td>{item.seq || idx + 1}</td>
                      <td><Badge tone="outline">{item.subject || '其他'}</Badge></td>
                      <td>
                        <div className="v3-plan-ebbcontent">{item.content}</div>
                        {item.mastered
                          ? <Badge tone="success">已掌握</Badge>
                          : due
                            ? <Badge tone="warning">到期复习 · {due.label}</Badge>
                            : <Badge tone="primary">记忆中</Badge>}
                      </td>
                      <td className="v3-plan-muted">{String(item.learn_date || '').slice(0, 10)}</td>
                      <td>
                        <div className="v3-plan-cyclechips">
                          {times.map((rt) => {
                            const isDue = due && rt.key === due.key
                            return (
                              <span
                                className="v3-plan-reviewpoint"
                                key={rt.key}
                                title={`标记「${rt.label}」复习完成`}
                              >
                                <Chip
                                  active={rt.done || isDue}
                                  gradient={!!rt.done}
                                  onClick={() => markReview(item.id, rt)}
                                >
                                  {rt.done ? '✓ ' : ''}{rt.label}
                                </Chip>
                                <button
                                  type="button"
                                  className="v3-plan-reviewtime"
                                  onClick={() => openTimeEdit(item, rt)}
                                  title={`修改「${rt.label}」复习时间：${fmtReviewTime(rt.time)}`}
                                >
                                  <Clock size={10} />
                                  {fmtReviewTime(rt.time)}
                                </button>
                              </span>
                            )
                          })}
                        </div>
                      </td>
                      <td>
                        <div className="v3-plan-rowactions">
                          <IconButton
                            label={`调整「${item.content}」的复习节奏`}
                            size="sm"
                            icon={<CalendarClock size={14} />}
                            onClick={() => openAdjust(item)}
                          />
                          <IconButton
                            label={`删除记忆条目「${item.content}」`}
                            size="sm"
                            icon={<Trash size={14} />}
                            onClick={() => deleteItem(item.id)}
                          />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* 调整复习节奏弹窗 */}
      <Dialog
        open={!!adjustItem}
        title="调整复习节奏"
        sub={adjustItem ? `「${adjustItem.content}」将按新节奏重新生成全部复习时间点` : ''}
        onClose={() => setAdjustItem(null)}
        footer={(
          <>
            <Button variant="text" onClick={() => setAdjustItem(null)}>取消</Button>
            <Button loading={savingCycles} onClick={saveCycles}>保存并重新生成</Button>
          </>
        )}
      >
        <CycleEditor value={adjustCycles} onChange={setAdjustCycles} compact />
        <p className="v3-plan-ebbcycle">
          保存后所有复习时间点将按新节奏重新生成，已打卡状态会重置。
        </p>
      </Dialog>

      {/* 修改单个复习点时间弹窗 */}
      <Dialog
        open={!!timeItem && !!timePoint}
        title="修改复习时间"
        sub={timeItem && timePoint ? `「${timeItem.content}」· ${timePoint.label}` : ''}
        onClose={() => { setTimeItem(null); setTimePoint(null) }}
        footer={(
          <>
            <Button variant="text" onClick={() => { setTimeItem(null); setTimePoint(null) }}>取消</Button>
            <Button loading={savingTime} onClick={saveReviewTime}>保存时间</Button>
          </>
        )}
      >
        <Field label="复习时间">
          <Input
            type="datetime-local"
            aria-label="复习时间"
            value={timeValue}
            onChange={(e) => setTimeValue(e.target.value)}
          />
        </Field>
      </Dialog>
    </div>
  )
}

/* ============================================================
   早起打卡
   ============================================================ */
function EarlyBirdTab({ onSync }) {
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [streak, setStreak] = useState(0)
  const [wakeTime, setWakeTime] = useState('06:30')
  const [sleepTime, setSleepTime] = useState('23:00')
  const [busy, setBusy] = useState(false)

  const loadRecords = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await plannerApi.listEarlyBird()
      const recs = pickList(data, 'records')
      setRecords(recs)
      setStreak(data && data.current_streak != null ? data.current_streak : computeStreak(recs))
      return true
    } catch (e) {
      setError(e.message || '加载失败')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadRecords() }, [loadRecords])

  const refreshRecords = async () => {
    const ok = await loadRecords()
    if (ok) toastOk('打卡记录已刷新')
    else toastErr('打卡记录刷新失败')
  }

  const checkIn = async () => {
    setBusy(true)
    try {
      await plannerApi.createEarlyBird({ date: todayStr(), wake_time: wakeTime, sleep_time: sleepTime })
      toastOk('打卡成功！')
      await loadRecords()
      if (onSync) onSync()
    } catch {
      toastErr('打卡失败')
    } finally {
      setBusy(false)
    }
  }

  const checkedToday = records.some((r) => String(r.date || '').slice(0, 10) === todayStr())

  const stats = useMemo(() => {
    const wakes = records.map((r) => String(r.wake_time || '').slice(0, 5)).filter(Boolean)
    const avgMin = wakes.length
      ? Math.round(wakes.reduce((s, t) => {
        const [h, m] = t.split(':').map(Number)
        return s + h * 60 + m
      }, 0) / wakes.length)
      : null
    const last7 = records.filter((r) => {
      const d = String(r.date || '').slice(0, 10)
      if (!d) return false
      return daysBetween(d, todayStr()) <= 6 && daysBetween(d, todayStr()) >= 0
    }).length
    return {
      avgWake: avgMin == null ? '--:--' : `${pad2(Math.floor(avgMin / 60))}:${pad2(avgMin % 60)}`,
      last7,
      total: records.length,
    }
  }, [records])

  return (
    <div className="v3-stack">
      <div className="v3-plan-stats">
        <Tile variant="well" className="v3-plan-stat">
          <div className="v3-tile__label"><Flame size={15} /> 连续早起</div>
          <div className="v3-tile__value">{streak}</div>
          <div className="v3-tile__hint">{checkedToday ? '今日已打卡' : '今日待打卡'}</div>
        </Tile>
        <Tile variant="well" className="v3-plan-stat">
          <div className="v3-tile__label"><Calendar size={15} /> 最近 7 天</div>
          <div className="v3-tile__value">{stats.last7}</div>
          <div className="v3-tile__hint">{stats.last7 >= 6 ? '保持得很好' : '再接再厉'}</div>
        </Tile>
        <Tile variant="well" className="v3-plan-stat">
          <div className="v3-tile__label"><Clock size={15} /> 平均起床</div>
          <div className="v3-tile__value is-time">{stats.avgWake}</div>
          <div className="v3-tile__hint">按全部记录平均</div>
        </Tile>
        <Tile variant="well" className="v3-plan-stat">
          <div className="v3-tile__label"><Trophy size={15} /> 累计打卡</div>
          <div className="v3-tile__value">{stats.total}</div>
          <div className="v3-tile__hint">天</div>
        </Tile>
      </div>

      <Card>
        <CardHead
          icon={<Sun size={16} />}
          title="今日打卡"
          sub="记录起床与就寝时间，连续天数会自动累计"
          actions={checkedToday ? <Badge tone="success">今天已记录</Badge> : <Badge tone="warning">尚未打卡</Badge>}
        />
        <div className="v3-plan-checkin">
          <Field label="今日起床">
            <Input type="time" value={wakeTime} onChange={(e) => setWakeTime(e.target.value)} aria-label="今日起床时间" />
          </Field>
          <Field label="昨晚就寝">
            <Input type="time" value={sleepTime} onChange={(e) => setSleepTime(e.target.value)} aria-label="昨晚就寝时间" />
          </Field>
          <Button icon={<Sun size={15} />} onClick={checkIn} loading={busy}>
            {checkedToday ? '更新今日记录' : '立即打卡'}
          </Button>
        </div>
      </Card>

      <Card>
        <CardHead
          icon={<ListChecks size={16} />}
          title={<>打卡记录 <Badge tone="outline">最近 {records.length} 天</Badge></>}
          sub="早起达标线为 07:00"
          actions={<Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={refreshRecords}>刷新</Button>}
        />
        {loading ? (
          <div className="v3-stack">
            <Skeleton height={42} />
            <Skeleton height={42} />
            <Skeleton height={42} />
          </div>
        ) : error ? (
          <Empty
            icon={<Sun size={24} />}
            title="打卡记录加载失败"
            text={error}
            action={<Button variant="outline" onClick={loadRecords}>重试</Button>}
          />
        ) : records.length === 0 ? (
          <Empty
            icon={<Sun size={26} />}
            title="还没有打卡记录"
            text="今天开始吧，连续天数会自动累计，也可一并导出为日历提醒。"
          />
        ) : (
          <div className="v3-plan-tablewrap">
            <table className="v3-plan-table">
              <thead>
                <tr>
                  <th style={{ width: 90 }}>天数</th>
                  <th style={{ width: 130 }}>日期</th>
                  <th style={{ width: 110 }}>起床时间</th>
                  <th style={{ width: 110 }}>就寝时间</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => {
                  const w = String(r.wake_time || '').slice(0, 5)
                  const early = w && w <= '07:00'
                  return (
                    <tr key={r.id}>
                      <td>第 {r.day_num} 天</td>
                      <td>{String(r.date || '').slice(0, 10)}</td>
                      <td>{w || '-'}</td>
                      <td>{String(r.sleep_time || '').slice(0, 5) || '-'}</td>
                      <td>
                        {w
                          ? <Badge tone={early ? 'success' : 'warning'}>{early ? '早起达标' : '略晚'}</Badge>
                          : <Badge tone="outline">未记录</Badge>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

/* ============================================================
   阶段复习
   ============================================================ */
function PhaseTab() {
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedPlan, setSelectedPlan] = useState(null)
  const [reviews, setReviews] = useState([])
  const [reviewsLoading, setReviewsLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newPlan, setNewPlan] = useState({
    name: '', start_date: todayStr(), end_date: '', cycle_days: 40,
    tasks: [{ index: 1, content: '' }],
  })

  const loadPlans = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await plannerApi.listPhase()
      setPlans(pickList(data, 'plans'))
    } catch (e) {
      setError(e.message || '加载失败')
      toast('加载阶段计划失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadPlans() }, [loadPlans])

  const loadReviews = async (planId) => {
    setReviewsLoading(true)
    try {
      const data = await plannerApi.getPhaseReviews(planId)
      setReviews(pickList(data, 'reviews'))
    } catch {
      setReviews([])
    } finally {
      setReviewsLoading(false)
    }
  }

  const selectPlan = (plan) => {
    if (selectedPlan && selectedPlan.id === plan.id) {
      setSelectedPlan(null)
      setReviews([])
      return
    }
    setSelectedPlan(plan)
    loadReviews(plan.id)
  }

  const createPlan = async () => {
    if (!newPlan.name.trim()) return toast('请输入阶段名称')
    if (!newPlan.end_date) return toast('请选择结束日期')
    setCreating(true)
    try {
      await plannerApi.createPhase(newPlan)
      toastOk('阶段计划已创建，每日复习安排已自动生成')
      setShowCreate(false)
      setNewPlan({ name: '', start_date: todayStr(), end_date: '', cycle_days: 40, tasks: [{ index: 1, content: '' }] })
      loadPlans()
    } catch {
      toastErr('创建失败')
    } finally {
      setCreating(false)
    }
  }

  const toggleDay = async (dayNum) => {
    if (!selectedPlan) return
    try {
      await plannerApi.checkPhaseDay(selectedPlan.id, dayNum)
      loadReviews(selectedPlan.id)
      loadPlans()
    } catch {
      toastErr('操作失败')
    }
  }

  const addTask = () => {
    setNewPlan((prev) => ({
      ...prev,
      tasks: [...prev.tasks, { index: prev.tasks.length + 1, content: '' }],
    }))
  }

  const updateTask = (idx, value) => {
    setNewPlan((prev) => ({
      ...prev,
      tasks: prev.tasks.map((t, i) => (i === idx ? { ...t, content: value } : t)),
    }))
  }

  const doneCount = reviews.filter((r) => r.completed).length

  return (
    <div className="v3-stack">
      <Card variant="tonal">
        <div className="v3-plan-phasebar">
          <div>
            <b>阶段复习计划</b>
            <span>把一轮复习拆成阶段，按艾宾浩斯曲线自动排布每日早 / 晚复习任务</span>
          </div>
          <div className="v3-plan-toolbaractions">
            <Badge tone="outline">{plans.length} 个阶段</Badge>
            <Button
              variant={showCreate ? 'ghost' : 'filled'}
              size="sm"
              icon={showCreate ? <X size={14} /> : <Plus size={14} />}
              onClick={() => setShowCreate((v) => !v)}
            >
              {showCreate ? '取消新建' : '新建阶段'}
            </Button>
          </div>
        </div>
      </Card>

      {showCreate && (
        <Card>
          <CardHead
            icon={<Layers size={16} />}
            title="新建阶段复习计划"
            sub="填写阶段区间与任务划分，系统会生成每日复习安排"
          />
          <div className="v3-grid v3-grid-2 v3-plan-phaseform">
            <Field label="阶段名称">
              <Input
                value={newPlan.name}
                onChange={(e) => setNewPlan({ ...newPlan, name: e.target.value })}
                placeholder="如：专业课一轮复习"
                aria-label="阶段名称"
              />
            </Field>
            <Field label="周期天数">
              <Input
                type="number"
                aria-label="周期天数"
                value={newPlan.cycle_days}
                onChange={(e) => setNewPlan({ ...newPlan, cycle_days: Number(e.target.value) })}
              />
            </Field>
            <Field label="开始日期">
              <Input
                type="date"
                aria-label="开始日期"
                value={newPlan.start_date}
                onChange={(e) => setNewPlan({ ...newPlan, start_date: e.target.value })}
              />
            </Field>
            <Field label="结束日期">
              <Input
                type="date"
                aria-label="结束日期"
                value={newPlan.end_date}
                onChange={(e) => setNewPlan({ ...newPlan, end_date: e.target.value })}
              />
            </Field>
          </div>
          <div className="v3-plan-divider" />
          <div className="v3-plan-phasetasks">
            <div className="v3-plan-sectionrow">
              <b>任务划分</b>
              <Button variant="ghost" size="sm" icon={<Plus size={13} />} onClick={addTask}>添加任务</Button>
            </div>
            {newPlan.tasks.map((t, idx) => (
              <div className="v3-plan-phasetask" key={idx}>
                <span>{idx + 1}</span>
                <Input
                  value={t.content}
                  onChange={(e) => updateTask(idx, e.target.value)}
                  placeholder={`任务 ${idx + 1} 内容，如：第一章 信号与系统`}
                  aria-label={`任务 ${idx + 1} 内容`}
                />
              </div>
            ))}
          </div>
          <div className="v3-card__foot">
            <span />
            <Button loading={creating} onClick={createPlan}>创建阶段计划</Button>
          </div>
        </Card>
      )}

      <Card>
        <CardHead
          icon={<Layers size={16} />}
          title="已有阶段"
          sub="点击卡片查看每日复习安排，再点日期格切换完成状态"
        />
        {loading ? (
          <div className="v3-stack">
            <Skeleton height={88} />
            <Skeleton height={88} />
          </div>
        ) : error ? (
          <Empty
            icon={<Layers size={24} />}
            title="阶段计划加载失败"
            text={error}
            action={<Button variant="outline" onClick={loadPlans}>重试</Button>}
          />
        ) : plans.length === 0 ? (
          <Empty
            icon={<Layers size={26} />}
            title="还没有阶段计划"
            text="新建一个阶段（如「专业课一轮」），系统会按周期自动生成每日复习安排。"
            action={<Button variant="tonal" icon={<Plus size={14} />} onClick={() => setShowCreate(true)}>新建阶段</Button>}
          />
        ) : (
          <div className="v3-plan-phasegrid">
            {plans.map((p) => {
              const prog = Number(p.progress || 0)
              const active = selectedPlan && selectedPlan.id === p.id
              return (
                <Card
                  key={p.id}
                  variant="outline"
                  interactive
                  className={`v3-plan-phasecard${active ? ' is-active' : ''}`}
                  onClick={() => selectPlan(p)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectPlan(p) } }}
                >
                  <div className="v3-plan-phasecard__head">
                    <b>{p.name}</b>
                    <Badge tone={prog >= 100 ? 'success' : prog > 0 ? 'primary' : 'outline'}>{prog}%</Badge>
                  </div>
                  <div className="v3-plan-phasecard__meta">{p.start_date} ~ {p.end_date || '未设置'}</div>
                  <div className="v3-plan-phasecard__meta">
                    {p.cycle_days} 天周期 · {(p.task_count != null ? p.task_count : (p.tasks ? p.tasks.length : 0))} 个任务
                  </div>
                  <Progress value={prog} className="v3-plan-phasebar__progress" />
                </Card>
              )
            })}
          </div>
        )}
      </Card>

      {selectedPlan && (
        <Card>
          <CardHead
            icon={<Calendar size={16} />}
            title={`${selectedPlan.name} · 每日复习安排`}
            sub="点击任意日期格切换完成状态"
            actions={(
              <>
                <Badge tone="success">已完成 {doneCount}</Badge>
                <Badge tone="outline">共 {reviews.length} 天</Badge>
              </>
            )}
          />
          {reviewsLoading ? (
            <div className="v3-plan-reviewgrid">
              {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} height={82} />)}
            </div>
          ) : reviews.length === 0 ? (
            <Empty
              icon={<Calendar size={24} />}
              title="暂无每日安排"
              text="该阶段还没有生成复习明细，可在创建时填写任务划分后重新生成。"
            />
          ) : (
            <div className="v3-plan-reviewgrid">
              {reviews.map((r) => (
                <button
                  type="button"
                  key={r.id || r.day_num}
                  className={`v3-plan-daycard${r.completed ? ' is-done' : ''}`}
                  onClick={() => toggleDay(r.day_num)}
                  title="点击切换完成状态"
                >
                  <div>
                    <b>第 {r.day_num} 天</b>
                    <span>{String(r.date || '').slice(5, 10)}</span>
                  </div>
                  <div className="v3-plan-daycard__tags">
                    {r.morning_reviews?.length > 0 && <Badge tone="primary">早 {r.morning_reviews.join(',')}</Badge>}
                    {r.evening_reviews?.length > 0 && <Badge tone="warning">晚 {r.evening_reviews.join(',')}</Badge>}
                  </div>
                  {r.completed ? <Badge tone="success">已完成</Badge> : <Badge tone="outline">待办</Badge>}
                </button>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
