import React, { useState, useEffect, useMemo } from 'react'
import { plannerApi } from '../api/client'
import { toast, toastOk, toastErr, Empty } from '../components/UI'
import { Card } from '../components/Card'
import useStore from '../store/useStore'
import { todayStr, daysBetween } from '../utils/date'
import { examDaysLeft, resolveExamDate } from '../utils/exam'
import { useSubjectConfig, subjectLabel } from '../hooks/useSubjectConfig'
import QuickAddTask from '../components/QuickAddTask'
import TaskItem from '../components/TaskItem'
import { Target, Calendar, Timer, Brain, Sun, Layers } from '../components/Icon'
import '../components/TaskList.css'

/* ============================================================
   学习计划表（V2 冷蓝设计系统）
   包含：日计划 / 周月计划 / 艾宾浩斯记忆表 / 早起打卡 / 阶段复习
   新增：① .ics 日历导出   ② 连续早起 streak 统计
   ============================================================ */

/* 标签页图标：真 SVG（对齐 Cards/UI 的约定，废除「文字模拟图标」），
   渲染时 aria-hidden，避免读屏把图标名与标签拼读（dogfood ISSUE-011）。 */
const TABS = [
  { key: 'daily', label: '日计划', icon: <Calendar size={14} /> },
  { key: 'weekmonth', label: '周月计划', icon: <Timer size={14} /> },
  { key: 'ebbinghaus', label: '艾宾浩斯', icon: <Brain size={14} /> },
  { key: 'earlybird', label: '早起打卡', icon: <Sun size={14} /> },
  { key: 'phase', label: '阶段复习', icon: <Layers size={14} /> },
]

/* 每科 4 条任务格 */
const TASK_SLOTS = 4

/**
 * 把某科目的任务值规整为定长数组。
 * 后端 planner 的 tasks 是自由 JSON：存量数据既有 ["a","b"] 也有 "教材精读 + 课后题" 这种整串。
 * 若直接按下标取值，字符串会被拆成单字（"教材精读"→"教"/"材"/"精"/"读"），
 * 用户改一格再保存就会把整条任务写成单个字，故字符串一律落到第 1 格。
 */
function slotsOf(value) {
  const base = Array.isArray(value)
    ? value.slice(0, TASK_SLOTS).map((v) => String(v ?? ''))
    : [String(value ?? '')].filter((v) => v !== '')
  while (base.length < TASK_SLOTS) base.push('')
  return base
}

/* 科目配色按顺序轮转，不再与科目名绑定 —— 科目现在来自 /api/goals/subjects 配置 */
const SUBJECT_ICO = ['blue', 'red', 'violet', 'green', 'amber']
const SUBJECT_BADGE = ['info', 'danger', 'accent', 'success', 'warning']

/** 周/月计划的单框文本视图：数组值合并展示，避免编辑时丢内容后被保存清空。 */
function textOf(value) {
  return Array.isArray(value)
    ? value.map((v) => String(v ?? '').trim()).filter(Boolean).join(' / ')
    : String(value ?? '')
}

/**
 * 计划表要渲染的科目 = 配置的考试科目 ∪ 已载入计划里出现过的历史科目。
 * 历史键必须保留：后端 planner 的 tasks 是自由 JSON，若只渲染当前配置的科目，
 * 用户之前写在一个已取消科目（如"专二"）下的任务会看不见，一保存就被清空。
 */
function planSubjects(examList, tasks) {
  return Array.from(new Set([...(examList || []), ...Object.keys(tasks || {})]))
}

/**
 * 科目为空时的空态。
 * 此前 useSubjectConfig 在没配置/后端不可达时兜一套内置科目，计划表于是固定长出
 * 6 行"你的科目"——那是某个人的专业方向，不是这位用户的。空表要如实是空表。
 */
function NoSubjects({ ready }) {
  return (
    <Empty
      title={ready ? '还没有备考科目' : '正在读取科目配置'}
      desc={ready
        ? '计划表按你配置的科目逐科铺开。到「设置 → 备考科目」添加后，这里立刻跟着变。'
        : '后端可达后自动带出你在设置里配置的科目；读取期间这里保持为空，不替你假设专业方向。'}
    />
  )
}

/* 艾宾浩斯 9 个复习周期（偏移量用于 .ics 复习点推算） */
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

/* ============================================================
   .ics 日历工具（纯前端 Blob 下载，零依赖）
   ============================================================ */
const pad2 = (n) => String(n).padStart(2, '0')

/** 本地时间 → iCalendar UTC 时间戳 20260901T083000Z */
function icsStamp(d) {
  return (
    d.getUTCFullYear() +
    pad2(d.getUTCMonth() + 1) +
    pad2(d.getUTCDate()) + 'T' +
    pad2(d.getUTCHours()) +
    pad2(d.getUTCMinutes()) +
    pad2(d.getUTCSeconds()) + 'Z'
  )
}

/** 'YYYY-MM-DD' → '20260901'（全天事件用） */
function icsDay(dateStr) {
  return String(dateStr || '').slice(0, 10).replace(/-/g, '')
}

/** 文本转义：反斜杠 / 分号 / 逗号 / 换行 */
function icsEsc(s) {
  return String(s == null ? '' : s)
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n')
}

/** RFC5545 折行：单行不超过 75 字节，续行以空格开头 */
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

/**
 * 生成 .ics 文本
 * events: [{ uid, summary, description, allDay, day, start, end, alarmMin }]
 */
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
      L.push(
        'DTEND;VALUE=DATE:' +
        (next.getFullYear() + pad2(next.getMonth() + 1) + pad2(next.getDate()))
      )
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

/** 纯前端下载 */
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

/** 兼容「数组」与「{items:[]}」两种后端返回形态 */
function pickList(data, key) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data[key])) return data[key]
  if (data && Array.isArray(data.items)) return data.items
  return []
}

/** 连续早起天数：从今天（或昨天）起向前数连续打卡 */
function computeStreak(records) {
  const set = new Set(records.map((r) => String(r.date || '').slice(0, 10)))
  const d = new Date(todayStr() + 'T00:00:00')
  if (!set.has(todayStr())) d.setDate(d.getDate() - 1)
  let n = 0
  for (let i = 0; i < 400; i++) {
    const key =
      d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
    if (!set.has(key)) break
    n++
    d.setDate(d.getDate() - 1)
  }
  return n
}

/* ============================================================
   主页面
   ============================================================ */
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
    } catch (e) { ok = false }
    try {
      const ebb = await plannerApi.listEbbinghaus()
      setEbbCount(pickList(ebb, 'items').length)
    } catch (e) { ok = false }
    return ok
  }

  useEffect(() => { loadOverview() }, [])

  /* 手动刷新概览：静默失败会让用户以为按钮坏了，这里明确给成败提示 */
  const refreshOverview = async () => {
    const ok = await loadOverview()
    if (ok) toastOk('计划概览已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  /* ---------- 新增功能①：导出 .ics 日历 ---------- */
  const exportIcs = async () => {
    setExporting(true)
    try {
      const events = []
      const nowMs = Date.now()

      /* 1) 艾宾浩斯 9 个复习点（只导出尚未过期的，避免日历被历史事件淹没） */
      let ebbItems = []
      try { ebbItems = pickList(await plannerApi.listEbbinghaus(), 'items') } catch (e) { /* 忽略 */ }
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

      /* 2) 早起打卡：按最近打卡的起床时间，为未来 14 天生成提醒 */
      let ebRecords = []
      try { ebRecords = pickList(await plannerApi.listEarlyBird(), 'records') } catch (e) { /* 忽略 */ }
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

      /* 3) 阶段复习：每日复习安排（全天事件） */
      let plans = []
      try { plans = pickList(await plannerApi.listPhase(), 'plans') } catch (e) { /* 忽略 */ }
      for (const p of plans.slice(0, 5)) {
        let reviews = []
        try { reviews = pickList(await plannerApi.getPhaseReviews(p.id), 'reviews') } catch (e) { /* 该接口缺失时跳过 */ }
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
      toast(`已导出 ${events.length} 条日程到 planner.ics`)
    } catch (e) {
      toast('导出失败：' + (e.message || '未知错误'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">学习计划表</h1>
          <p className="page-sub">科学规划，高效备考 · 日/周/月计划 · 艾宾浩斯 · 早起 · 阶段复习</p>
        </div>
        <div className="page-actions">
          <span className="badge warning" title="连续早起天数">高频 {streak} 天</span>
          {ebbCount > 0 && <span className="badge info">记忆 {ebbCount} 条记忆</span>}
          <button className="btn ghost" onClick={refreshOverview}>刷新</button>
          <button className="btn primary" onClick={exportIcs} disabled={exporting}>
            {exporting ? '生成中…' : '日期 导出日历 (.ics)'}
          </button>
        </div>
      </div>

      {/* 标签页导航 */}
      <div className="tabs" role="tablist" style={{ marginBottom: 'var(--space-4)', flexWrap: 'wrap' }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            className={`tab ${tab === t.key ? 'active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            <span aria-hidden="true" style={{ marginRight: 'var(--space-2)', display: 'inline-flex', alignItems: 'center' }}>{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      <div className="stack">
        {tab === 'daily' && <DailyPlanTab />}
        {tab === 'weekmonth' && <WeekMonthPlanTab />}
        {tab === 'ebbinghaus' && <EbbinghausTab />}
        {tab === 'earlybird' && <EarlyBirdTab onSync={loadOverview} />}
        {tab === 'phase' && <PhaseTab />}
      </div>
    </div>
  )
}

/* ============================================================
   日计划表 V2 - 滴答清单/Todoist 风格
   ============================================================ */
function DailyPlanTab() {
  const countdown = useStore((s) => s.countdown)
  const settingsExamDate = useStore((s) => s.settings.examDate)
  const { exam, ready: subjectsReady } = useSubjectConfig()
  const [date, setDate] = useState(todayStr())
  const [plan, setPlan] = useState(null)
  // 新数据结构：tasks 现在是数组 [{id, title, subject, duration, completed, subtasks}]
  const [taskList, setTaskList] = useState([])
  const [timeline, setTimeline] = useState([])
  const [score, setScore] = useState(0)
  const [summary, setSummary] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadPlan()
  }, [date])

  const loadPlan = async () => {
    try {
      const data = await plannerApi.getDaily(date)
      setPlan(data)
      // 兼容旧数据格式：如果是对象则转换，如果是数组则直接使用
      const rawTasks = data.tasks || {}
      if (Array.isArray(rawTasks)) {
        setTaskList(rawTasks)
      } else {
        // 从旧的 {subject: [str,str,str,str]} 格式迁移
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
      toast('加载日计划失败')
    }
  }

  const savePlan = async () => {
    setSaving(true)
    try {
      await plannerApi.saveDaily({
        date,
        tasks: taskList, // 直接保存数组
        timeline,
        score,
        summary,
      })
      toast('日计划已保存')
      loadPlan()
    } catch (e) {
      toast('保存失败')
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

  const toggleTask = (taskId) => {
    setTaskList((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, completed: !t.completed } : t))
    )
  }

  const deleteTask = (taskId) => {
    setTaskList((prev) => prev.filter((t) => t.id !== taskId))
  }

  const updateTask = (updatedTask) => {
    setTaskList((prev) =>
      prev.map((t) => (t.id === updatedTask.id ? updatedTask : t))
    )
  }

  const handleDragStart = (index) => {
    // 简单的拖拽占位，后续可实现完整 DnD
  }

  // 统计
  const totalTasks = taskList.length
  const completedTasks = taskList.filter((t) => t.completed).length
  const pct = totalTasks ? Math.round((completedTasks / totalTasks) * 100) : 0

  const remain = plan && plan.days_to_exam != null
    ? plan.days_to_exam
    : examDaysLeft(resolveExamDate(settingsExamDate || (countdown && countdown.exam_date), null))

  return (
    <>
      <div className="card">
        <div className="toolbar">
          <div className="left">
            <div className="field" style={{ minWidth: 170 }}>
              <label>计划日期</label>
              <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="计划日期" />
            </div>
            <div className="row" style={{ paddingTop: 'var(--space-5)' }}>
              {remain != null && <span className="badge accent">距考研 {remain} 天</span>}
              {remain == null && <span className="badge neutral">未设置初试日期</span>}
              {plan && plan.exists
                ? <span className="badge success">已有记录</span>
                : <span className="badge neutral">未填写</span>}
              <span className="badge info">任务 {completedTasks}/{totalTasks}</span>
            </div>
          </div>
          <div className="right" style={{ paddingTop: 'var(--space-5)' }}>
            <button className="btn ghost" onClick={loadPlan}>重新载入</button>
            <button className="btn primary" onClick={savePlan} disabled={saving}>
              {saving ? '保存中…' : '保存计划'}
            </button>
          </div>
        </div>
        <div className="progress" style={{ marginTop: 'var(--space-4)' }}>
          <i style={{ width: pct + '%' }} />
        </div>
      </div>

      {/* 未配置备考科目：不凭空生成科目行，给出配置入口（F1-05 / F3-01） */}
      {subjectsReady && (!exam || exam.length === 0) && (
        <div className="card">
          <Empty
            icon={<Target size={36} />}
            title="还没有备考科目"
            desc="日计划的任务需要先有科目。先到「设置 → 目标与概览 → 备考科目」勾选你要考的科目，再回来安排每天的任务。"
            action={<a className="btn primary" href="#/settings">配置备考科目</a>}
          />
        </div>
      )}

      {/* 快速添加区域 */}
      {subjectsReady && exam && exam.length > 0 && (
        <QuickAddTask onAdd={addTask} subjects={exam} />
      )}

      <div className="grid-2">
        {/* 左：任务列表 */}
        <Card
          title="今日学习任务"
          sub={taskList.length ? `${totalTasks} 个任务，${completedTasks} 个已完成` : '使用上方快速添加框创建任务'}
        >
          {taskList.length === 0 ? (
            <Empty
              title="还没有任务"
              desc="在上方输入任务标题，选择科目和时长，快速添加到今日计划"
            />
          ) : (
            <div className="task-list">
              {taskList.map((task, index) => (
                <TaskItem
                  key={task.id}
                  task={task}
                  index={index}
                  onToggle={toggleTask}
                  onDelete={deleteTask}
                  onUpdate={updateTask}
                  onReorder={handleDragStart}
                />
              ))}
            </div>
          )}
        </Card>

        {/* 右：评分与总结 */}
        <Card
          title="今日评价"
          extra={
            <span className={`badge ${score >= 8 ? 'success' : score >= 5 ? 'warning' : 'neutral'}`}>
              评分 {score}/10
            </span>
          }
        >
            <div className="field">
              <label>今日评分（1-10）</label>
              <input
                className="input"
                type="number"
                aria-label="今日评分（1-10）"
                min="1"
                max="10"
                value={score}
                onChange={(e) => setScore(Number(e.target.value))}
              />
              <div className="progress thin">
                <i style={{ width: Math.min(100, Math.max(0, score * 10)) + '%' }} />
              </div>
            </div>
            <div className="field">
              <label>今日总结</label>
              <textarea
                className="textarea"
                rows="8"
                aria-label="今日总结"
                placeholder="记录今天的学习收获、遇到的问题、明天的计划..."
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
              />
            </div>
            {timeline.length > 0 && (
              <div className="timeline">
                {timeline.slice(0, 6).map((t, i) => (
                  <div className="tl-item" key={i}>
                    <div className={`tl-dot ${t && t.done ? '' : 'gray'}`} />
                    <div className="tl-body">
                      <div className="tl-title">{(t && (t.title || t.content)) || '时间块'}</div>
                      <div className="tl-meta">{(t && (t.time || t.range)) || ''}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
        </Card>
      </div>
    </>
  )
}

/* ============================================================
   周月计划表
   ============================================================ */
function WeekMonthPlanTab() {
  const { exam, ready: subjectsReady } = useSubjectConfig()
  const [mode, setMode] = useState('month')
  const [year, setYear] = useState(new Date().getFullYear())
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const [weekStart, setWeekStart] = useState(() => {
    const d = new Date()
    const dow = (d.getDay() + 6) % 7 /* 周一为 0 */
    d.setDate(d.getDate() - dow)
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
  })
  const [plan, setPlan] = useState(null)
  const [tasks, setTasks] = useState({})
  const [completion, setCompletion] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadPlan()
  }, [year, month, mode, weekStart])

  const loadPlan = async () => {
    try {
      if (mode === 'month') {
        const data = await plannerApi.getMonth(year, month)
        setPlan(data)
        setTasks(data.tasks || {})
        setCompletion(data.completion || '')
      } else {
        const data = await plannerApi.getWeek(weekStart)
        setPlan(data)
        setTasks(data.tasks || {})
        setCompletion(data.completion || '')
      }
    } catch (e) {
      toast('加载计划失败')
    }
  }

  const savePlan = async () => {
    setSaving(true)
    try {
      if (mode === 'month') {
        await plannerApi.saveMonth({ year, month, tasks, completion })
        toast('月计划已保存')
      } else {
        await plannerApi.saveWeek({ week_start: weekStart, tasks, completion })
        toast('周计划已保存')
      }
      loadPlan()
    } catch (e) {
      toast('保存失败')
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

  return (
    <>
      <div className="card">
        <div className="toolbar">
          <div className="left">
            <div className="segmented">
              <button className={`seg ${mode === 'month' ? 'active' : ''}`} onClick={() => setMode('month')}>月计划</button>
              <button className={`seg ${mode === 'week' ? 'active' : ''}`} onClick={() => setMode('week')}>周计划</button>
            </div>
            {mode === 'month' ? (
              <>
                <select className="select" style={{ width: 110 }} value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="选择年份">
                  {/* 候选随「今年」滑动，而不是写死 [2025..2028]：
                      写死的话到了 2029 年这个下拉里就没有 2029 了。 */}
                  {Array.from({ length: 4 }, (_, i) => new Date().getFullYear() - 1 + i)
                    .concat(year)
                    .filter((y, i, arr) => arr.indexOf(y) === i)
                    .sort((a, b) => a - b)
                    .map((y) => <option key={y} value={y}>{y}年</option>)}
                </select>
                <select className="select" style={{ width: 100 }} value={month} onChange={(e) => setMonth(Number(e.target.value))} aria-label="选择月份">
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}月</option>)}
                </select>
              </>
            ) : (
              <>
                <button className="btn ghost sm" onClick={() => shiftWeek(-1)}>← 上一周</button>
                <input className="input" style={{ width: 160 }} type="date" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} aria-label="选择周起始日期" />
                <button className="btn ghost sm" onClick={() => shiftWeek(1)}>下一周 →</button>
              </>
            )}
            {plan && (plan.exists
              ? <span className="badge success">已有记录</span>
              : <span className="badge neutral">新建中</span>)}
          </div>
          <div className="right">
            <button className="btn primary" onClick={savePlan} disabled={saving}>{saving ? '保存中…' : '保存'}</button>
          </div>
        </div>
      </div>

      <Card
        title={title}
        sub={mode === 'month' ? '按月拆解各科任务量' : '周计划以周一为起点'}
      >
          {!subjects.length && <NoSubjects ready={subjectsReady} />}
          {subjects.map((subj, i) => (
            <div key={subj} className="field">
              <label>
                <span className={`badge ${SUBJECT_BADGE[i % SUBJECT_BADGE.length]}`}>{subjectLabel(subj)}</span>
              </label>
              <textarea
                className="textarea"
                rows="2"
                style={{ minHeight: 62 }}
                aria-label={`${subjectLabel(subj)}${mode === 'month' ? '本月' : '本周'}目标`}
                placeholder={`${subjectLabel(subj)}${mode === 'month' ? '本月' : '本周'}目标...`}
                value={textOf(tasks[subj])}
                onChange={(e) => setTasks((prev) => ({ ...prev, [subj]: e.target.value }))}
              />
            </div>
          ))}
          <hr className="hr" />
          <div className="field">
            <label>完成情况</label>
            <textarea
              className="textarea"
              rows="3"
              aria-label="完成情况"
              placeholder={`${mode === 'month' ? '本月' : '本周'}任务完成情况总结...`}
              value={completion}
              onChange={(e) => setCompletion(e.target.value)}
            />
          </div>
      </Card>
    </>
  )
}

/* ============================================================
   艾宾浩斯记忆表
   ============================================================ */
function EbbinghausTab() {
  const { exam } = useSubjectConfig()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)   /* 批次2-2：列表加载态 */
  const [error, setError] = useState('')           /* 阶段2：列表错误就地态 */
  const [newContent, setNewContent] = useState('')
  const [newSubject, setNewSubject] = useState('')
  const [filterSubject, setFilterSubject] = useState('')

  /* 记忆条目的科目下拉：配置科目 + 固定「其他」（后端按字符串存，不做白名单） */
  const memorySubjects = useMemo(() => Array.from(new Set([...exam.map(subjectLabel), '其他'])), [exam])
  useEffect(() => {
    setNewSubject((prev) => (prev && memorySubjects.includes(prev) ? prev : memorySubjects[0]))
  }, [memorySubjects])

  useEffect(() => {
    loadItems()
  }, [])

  const loadItems = async () => {
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
  }

  const addItem = async () => {
    if (!newContent.trim()) return toast('请输入学习内容')
    try {
      await plannerApi.createEbbinghaus({ content: newContent, subject: newSubject })
      toast('已添加，复习时间已自动计算')
      setNewContent('')
      loadItems()
    } catch (e) {
      toast('添加失败')
    }
  }

  const markReview = async (id, cycle) => {
    try {
      await plannerApi.markEbbinghausReview(id, cycle)
      toast(`${cycle} 复习已完成`)
      loadItems()
    } catch (e) {
      toast('标记失败')
    }
  }

  const deleteItem = async (id) => {
    try {
      await plannerApi.deleteEbbinghaus(id)
      toast('已删除')
      loadItems()
    } catch (e) {
      toast('删除失败')
    }
  }

  /** 依据首学时间推算「当前应复习的周期」 */
  const dueCycleOf = (item) => {
    const base = new Date(item.learn_date || '')
    if (isNaN(base.getTime())) return null
    const now = Date.now()
    let due = null
    CYCLES.forEach((c) => {
      if (base.getTime() + c.ms <= now) due = c
    })
    return due
  }

  const shown = useMemo(
    () => (filterSubject ? items.filter((i) => i.subject === filterSubject) : items),
    [items, filterSubject]
  )
  const subjects = useMemo(
    () => Array.from(new Set(items.map((i) => i.subject).filter(Boolean))),
    [items]
  )
  const masteredCount = items.filter((i) => i.mastered).length

  return (
    <>
      <Card title="新增记忆条目" sub="添加后自动生成 9 个复习时间点">
        <div className="row wrap">
          <select className="select" style={{ width: 120 }} value={newSubject} onChange={(e) => setNewSubject(e.target.value)} aria-label="选择科目">
            {memorySubjects.map((s) => <option key={s}>{s}</option>)}
          </select>
          <input
            className="input"
            style={{ flex: 1, minWidth: 220 }}
            type="text"
            aria-label="学习内容"
            placeholder="输入学习内容（如：abandon 放弃）"
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addItem()}
          />
          <button className="btn primary" onClick={addItem}>添加</button>
        </div>
        <p className="card-sub" style={{ marginTop: 'var(--space-3)' }}>
          复习节奏：5分钟 / 30分钟 / 12小时 / 1天 / 2天 / 4天 / 7天 / 15天 / 1个月 —— 完成「1个月」后自动标记为已掌握。
        </p>
      </Card>

      <Card
        flush
        headStyle={{ padding: 'var(--space-4) var(--space-5) 0', marginBottom: 'var(--space-3)' }}
        title={
          <>
            记忆列表 <span className="badge neutral">{shown.length} 条</span>
            {masteredCount > 0 && <span className="badge success" style={{ marginLeft: 'var(--space-2)' }}>已掌握 {masteredCount}</span>}
          </>
        }
        extra={
          <div className="row wrap">
            <span className={`chip ${filterSubject === '' ? 'active' : ''}`} onClick={() => setFilterSubject('')}
              role="button" tabIndex={0} aria-pressed={filterSubject === ''}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFilterSubject('') } }}>全部</span>
            {subjects.map((s) => (
              <span key={s} className={`chip ${filterSubject === s ? 'active' : ''}`} onClick={() => setFilterSubject(s)}
                role="button" tabIndex={0} aria-pressed={filterSubject === s}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFilterSubject(s) } }}>{s}</span>
            ))}
          </div>
        }
      >

        {loading ? (
          <div className="loading-inline">正在加载记忆条目…</div>
        ) : error ? (
          <div className="empty-state">
            <div className="empty-state-title">记忆列表加载失败</div>
            <div className="empty-state-desc">{error}</div>
            <div className="empty-state-action">
              <button className="btn ghost" onClick={loadItems}>重试</button>
            </div>
          </div>
        ) : shown.length === 0 ? (
          <div className="empty">
            <div className="e-ico">记忆</div>
            <div className="e-title">暂无记忆条目</div>
            <div className="e-text">添加第一条内容，系统会按艾宾浩斯遗忘曲线自动排布 9 次复习。</div>
          </div>
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 54 }}>序号</th>
                  <th style={{ width: 76 }}>学科</th>
                  <th>内容</th>
                  <th style={{ width: 108 }}>学习时间</th>
                  <th>复习打卡</th>
                  <th style={{ width: 70 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((item, idx) => {
                  const due = dueCycleOf(item)
                  return (
                    <tr key={item.id} style={item.mastered ? { opacity: 0.62 } : undefined}>
                      <td>{item.seq || idx + 1}</td>
                      <td><span className="badge neutral">{item.subject || '其他'}</span></td>
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--fg)' }}>{item.content}</div>
                        {item.mastered
                          ? <span className="badge success" style={{ marginTop: 'var(--space-1)' }}>已掌握 已完成</span>
                          : due
                            ? <span className="badge warning" style={{ marginTop: 'var(--space-1)' }}>待复习：{due.label}</span>
                            : <span className="badge info" style={{ marginTop: 'var(--space-1)' }}>记忆中</span>}
                      </td>
                      <td>{String(item.learn_date || '').slice(0, 10)}</td>
                      <td>
                        <div className="row wrap" style={{ gap: 'var(--space-2)' }}>
                          {CYCLES.map((c) => (
                            <span
                              key={c.key}
                              className={`chip ${due && due.key === c.key ? 'active' : ''}`}
                              title={`标记 ${c.label} 复习完成`}
                              onClick={() => markReview(item.id, c.key)}
                            >
                              {c.key}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>
                        <button className="btn danger sm" onClick={() => deleteItem(item.id)}>删除</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}

/* ============================================================
   早起打卡（含连续 streak 统计）
   ============================================================ */
function EarlyBirdTab({ onSync }) {
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(false)   /* 批次2-2：打卡记录加载态 */
  const [error, setError] = useState('')         /* 阶段2：记录列表错误就地态 */
  const [streak, setStreak] = useState(0)
  const [wakeTime, setWakeTime] = useState('06:30')
  const [sleepTime, setSleepTime] = useState('23:00')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    loadRecords()
  }, [])

  const loadRecords = async () => {
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
  }

  const refreshRecords = async () => {
    const ok = await loadRecords()
    if (ok) toastOk('打卡记录已刷新')
    else toastErr('打卡记录刷新失败')
  }

  const checkIn = async () => {
    setBusy(true)
    try {
      await plannerApi.createEarlyBird({
        date: todayStr(),
        wake_time: wakeTime,
        sleep_time: sleepTime,
      })
      toast('打卡成功！')
      await loadRecords()
      if (onSync) onSync()
    } catch (e) {
      toast('打卡失败')
    } finally {
      setBusy(false)
    }
  }

  const checkedToday = records.some((r) => String(r.date || '').slice(0, 10) === todayStr())

  /* 本地统计：平均起床时间 / 平均睡眠时长 / 最近 7 天打卡数 */
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
    <>
      {/* 新增功能②：连续打卡 streak */}
      <div className="grid-4">
        <div className="stat-tile">
          <div className="st-ico" style={{ background: 'var(--warn-soft)', color: 'var(--warn)' }}>高频</div>
          <div className="st-val">{streak}</div>
          <div className="st-label">当前连续早起（天）</div>
          <div className={`st-delta ${checkedToday ? 'up' : ''}`}>
            {checkedToday ? '今日已打卡 已完成' : '今日待打卡'}
          </div>
        </div>
        <div className="stat-tile">
          <div className="st-ico ico green" style={{ width: 38, height: 38 }}>趋势</div>
          <div className="st-val">{stats.last7}</div>
          <div className="st-label">最近 7 天打卡次数</div>
          <div className="st-delta">{stats.last7 >= 6 ? '保持得很好' : '再接再厉'}</div>
        </div>
        <div className="stat-tile">
          <div className="st-ico ico blue" style={{ width: 38, height: 38 }}>⏰</div>
          <div className="st-val" style={{ fontSize: 'var(--text-xl)' }}>{stats.avgWake}</div>
          <div className="st-label">平均起床时间</div>
        </div>
        <div className="stat-tile">
          <div className="st-ico ico violet" style={{ width: 38, height: 38 }}>日程</div>
          <div className="st-val">{stats.total}</div>
          <div className="st-label">累计打卡天数</div>
        </div>
      </div>

      <Card
        title="今日打卡"
        extra={
          checkedToday
            ? <span className="badge success">今天已记录</span>
            : <span className="badge warning">尚未打卡</span>
        }
      >
        <div className="row wrap">
          <div className="field" style={{ width: 160 }}>
            <label>今日起床</label>
            <input className="input" type="time" value={wakeTime} onChange={(e) => setWakeTime(e.target.value)} aria-label="今日起床时间" />
          </div>
          <div className="field" style={{ width: 160 }}>
            <label>昨晚就寝</label>
            <input className="input" type="time" value={sleepTime} onChange={(e) => setSleepTime(e.target.value)} aria-label="昨晚就寝时间" />
          </div>
          <div className="spacer" />
          <button className="btn primary" style={{ marginTop: 'var(--space-5)' }} onClick={checkIn} disabled={busy}>
            {busy ? '打卡中…' : checkedToday ? '更新今日记录' : '立即打卡'}
          </button>
        </div>
      </Card>

      <Card
        flush
        headStyle={{ padding: 'var(--space-4) var(--space-5) 0', marginBottom: 'var(--space-3)' }}
        title={<>打卡记录 <span className="badge neutral">最近 {records.length} 天</span></>}
        extra={<button className="btn ghost sm" onClick={refreshRecords}>刷新</button>}
      >
        {loading ? (
          <div className="loading-inline">正在加载打卡记录…</div>
        ) : error ? (
          <div className="empty-state">
            <div className="empty-state-title">打卡记录加载失败</div>
            <div className="empty-state-desc">{error}</div>
            <div className="empty-state-action">
              <button className="btn ghost" onClick={loadRecords}>重试</button>
            </div>
          </div>
        ) : records.length === 0 ? (
          <div className="empty">
            <div className="e-ico">早起</div>
            <div className="e-title">还没有打卡记录</div>
            <div className="e-text">今天开始吧，连续天数会自动累计，也可一并导出为日历提醒。</div>
          </div>
        ) : (
          <div className="table-container">
            <table className="table">
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
                          ? <span className={`badge ${early ? 'success' : 'warning'}`}>{early ? '早起达标' : '略晚'}</span>
                          : <span className="badge neutral">未记录</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}

/* ============================================================
   阶段复习表
   ============================================================ */
function PhaseTab() {
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(false)   /* 批次2-2：阶段计划加载态 */
  const [error, setError] = useState('')         /* 阶段2：阶段列表错误就地态 */
  const [selectedPlan, setSelectedPlan] = useState(null)
  const [reviews, setReviews] = useState([])
  const [showCreate, setShowCreate] = useState(false)
  const [newPlan, setNewPlan] = useState({
    name: '', start_date: todayStr(), end_date: '', cycle_days: 40,
    tasks: [{ index: 1, content: '' }],
  })

  useEffect(() => {
    loadPlans()
  }, [])

  const loadPlans = async () => {
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
  }

  const loadReviews = async (planId) => {
    try {
      const data = await plannerApi.getPhaseReviews(planId)
      setReviews(pickList(data, 'reviews'))
    } catch (e) {
      setReviews([])
    }
  }

  const selectPlan = (plan) => {
    setSelectedPlan(plan)
    loadReviews(plan.id)
  }

  const createPlan = async () => {
    if (!newPlan.name.trim()) return toast('请输入阶段名称')
    if (!newPlan.end_date) return toast('请选择结束日期')
    try {
      await plannerApi.createPhase(newPlan)
      toast('阶段计划已创建，每日复习安排已自动生成')
      setShowCreate(false)
      setNewPlan({ name: '', start_date: todayStr(), end_date: '', cycle_days: 40, tasks: [{ index: 1, content: '' }] })
      loadPlans()
    } catch (e) {
      toast('创建失败')
    }
  }

  const toggleDay = async (dayNum) => {
    if (!selectedPlan) return
    try {
      await plannerApi.checkPhaseDay(selectedPlan.id, dayNum)
      loadReviews(selectedPlan.id)
      loadPlans()
    } catch (e) {
      toast('操作失败')
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
    <>
      <div className="card">
        <div className="toolbar">
          <div className="left">
            <div className="card-title">阶段复习计划</div>
            <span className="badge neutral">{plans.length} 个阶段</span>
          </div>
          <div className="right">
            <button className={`btn ${showCreate ? 'ghost' : 'primary'}`} onClick={() => setShowCreate(!showCreate)}>
              {showCreate ? '取消' : '+ 新建阶段'}
            </button>
          </div>
        </div>
      </div>

      {showCreate && (
        <Card
          title="新建阶段复习计划"
          sub="按艾宾浩斯曲线自动排布每日早/晚复习任务"
          foot={
            <>
              <button className="btn ghost" onClick={() => setShowCreate(false)}>取消</button>
              <button className="btn primary" onClick={createPlan}>创建阶段计划</button>
            </>
          }
        >
            <div className="grid-2">
              <div className="field">
                <label>阶段名称</label>
                <input className="input" type="text" value={newPlan.name} onChange={(e) => setNewPlan({ ...newPlan, name: e.target.value })} placeholder="如：专业课一轮复习" aria-label="阶段名称" />
              </div>
              <div className="field">
                <label>周期天数</label>
                <input className="input" type="number" aria-label="周期天数" value={newPlan.cycle_days} onChange={(e) => setNewPlan({ ...newPlan, cycle_days: Number(e.target.value) })} />
              </div>
              <div className="field">
                <label>开始日期</label>
                <input className="input" type="date" aria-label="开始日期" value={newPlan.start_date} onChange={(e) => setNewPlan({ ...newPlan, start_date: e.target.value })} />
              </div>
              <div className="field">
                <label>结束日期</label>
                <input className="input" type="date" aria-label="结束日期" value={newPlan.end_date} onChange={(e) => setNewPlan({ ...newPlan, end_date: e.target.value })} />
              </div>
            </div>
            <hr className="hr" />
            <div className="sec-title">
              <h3>任务划分</h3>
              <div className="st-actions">
                <button className="btn ghost sm" onClick={addTask}>+ 添加任务</button>
              </div>
            </div>
            <div className="list">
              {newPlan.tasks.map((t, idx) => (
                <div key={idx} className="list-row">
                  <div className="lr-ico">{idx + 1}</div>
                  <div className="lr-main">
                    <input className="input" type="text" value={t.content} onChange={(e) => updateTask(idx, e.target.value)} placeholder={`任务 ${idx + 1} 内容，如：第一章 信号与系统`} aria-label={`任务 ${idx + 1} 内容`} />
                  </div>
                </div>
              ))}
            </div>
        </Card>
      )}

      <Card title="已有阶段" sub="点击卡片查看每日复习安排">
        {loading ? (
          <div className="loading-inline">正在加载阶段计划…</div>
        ) : error ? (
          <div className="empty-state">
            <div className="empty-state-title">阶段计划加载失败</div>
            <div className="empty-state-desc">{error}</div>
            <div className="empty-state-action">
              <button className="btn ghost" onClick={loadPlans}>重试</button>
            </div>
          </div>
        ) : plans.length === 0 ? (
          <div className="empty">
            <div className="e-ico">资料</div>
            <div className="e-title">还没有阶段计划</div>
            <div className="e-text">新建一个阶段（如「专业课一轮」），系统会按周期自动生成每日复习安排。</div>
          </div>
        ) : (
          <div className="grid-3">
            {plans.map((p) => {
              const prog = Number(p.progress || 0)
              const active = selectedPlan && selectedPlan.id === p.id
              return (
                <div
                  key={p.id}
                  className={`list-row ${active ? 'active' : ''}`}
                  style={{ flexDirection: 'column', alignItems: 'stretch', cursor: 'pointer', gap: 'var(--space-2)' }}
                  onClick={() => selectPlan(p)}
                >
                  <div className="spread">
                    <div className="lr-title">{p.name}</div>
                    <span className={`badge ${prog >= 100 ? 'success' : prog > 0 ? 'accent' : 'neutral'}`}>{prog}%</span>
                  </div>
                  <div className="lr-meta">{p.start_date} ~ {p.end_date || '未设置'}</div>
                  <div className="lr-meta">
                    {p.cycle_days} 天周期 · {(p.task_count != null ? p.task_count : (p.tasks ? p.tasks.length : 0))} 个任务
                  </div>
                  <div className="progress thin">
                    <i style={{ width: Math.min(100, Math.max(0, prog)) + '%' }} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Card>

      {selectedPlan && (
        <Card
          title={`${selectedPlan.name} · 每日复习安排`}
          extra={
            <div className="row">
              <span className="badge success">已完成 {doneCount}</span>
              <span className="badge neutral">共 {reviews.length} 天</span>
            </div>
          }
        >
          {reviews.length === 0 ? (
            <div className="empty">
              <div className="e-ico">日程</div>
              <div className="e-title">暂无每日安排</div>
              <div className="e-text">该阶段还没有生成复习明细，可在创建时填写任务划分后重新生成。</div>
            </div>
          ) : (
            <div className="grid-4" style={{ gap: 'var(--space-3)' }}>
              {reviews.map((r) => (
                <div
                  key={r.id || r.day_num}
                  className={`list-row ${r.completed ? 'active' : ''}`}
                  style={{ flexDirection: 'column', alignItems: 'stretch', cursor: 'pointer', gap: 'var(--space-2)' }}
                  onClick={() => toggleDay(r.day_num)}
                  title="点击切换完成状态"
                >
                  <div className="spread">
                    <div className="lr-title" style={{ fontSize: 'var(--text-sm)' }}>第 {r.day_num} 天</div>
                    {r.completed
                      ? <span className="badge success">已完成</span>
                      : <span className="badge neutral">待办</span>}
                  </div>
                  <div className="lr-meta">{String(r.date || '').slice(5, 10)}</div>
                  <div className="row wrap" style={{ gap: 'var(--space-1)' }}>
                    {r.morning_reviews && r.morning_reviews.length > 0 && (
                      <span className="badge info">早 {r.morning_reviews.join(',')}</span>
                    )}
                    {r.evening_reviews && r.evening_reviews.length > 0 && (
                      <span className="badge warning">晚 {r.evening_reviews.join(',')}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </>
  )
}
