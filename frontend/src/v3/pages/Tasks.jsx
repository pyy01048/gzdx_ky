import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import useStore from '../../store/useStore'
import { todayStr, addDays, monthMatrix, weekdayIdx, fmtDateCN, parseDate, WEEK_CN_SHORT } from '../../utils/date'
import { tasksApi } from '../../api/client'
import { subjectTone } from '../../api/hub'
import { loadDomain } from '../../api/sync'
import { useSubjectConfig } from '../../hooks/useSubjectConfig'
import { friendlyAiError } from '../../utils/aiError'
import { expandTaskDates, freqLabel, isRecurring, remindLabel, taskEmoji, FREQ_OPTIONS, monthCells } from '../../utils/recurrence'
import { Alert, Badge, Button, Chip, Dialog, Empty, Field, IconButton, Input, Progress, Segmented, Select, Switch, Textarea, cx, toast, toastOk, toastErr, useConfirm } from '../ui'
import { Bell, Brain, Calendar, Check, ChevronLeft, ChevronRight, Download, Layers, Plus, RefreshCw, Sparkles, Target, Trash } from '../icons'
import '../styles/pages.css'
import '../styles/study-glass.css'

const LEGACY_SUBJECT_CODES = { math: '数学', english: '英语', politics: '政治', major: '专业课', other: '其他' }
const subjectName = (v) => LEGACY_SUBJECT_CODES[v] || v || '未分类'

const csvCell = (v) => {
  const s = String(v ?? '')
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

const VIEWS = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
]

const weekStartOf = (d) => addDays(d, -weekdayIdx(d))
const pad2 = (n) => String(n).padStart(2, '0')
const monthGridRange = (d) => {
  const p = parseDate(d)
  const cells = monthMatrix(p.getFullYear(), p.getMonth() + 1)
  return { start: cells[0][0], end: cells[5][6] }
}

/* 视图 → 可见日期窗口：日/月共用「所选日期所在月视图网格」，翻一天多数不换窗口（少拉一次接口）。 */
function visibleRange(view, date) {
  if (view === 'week') return { start: weekStartOf(date), end: addDays(weekStartOf(date), 6) }
  return monthGridRange(date)
}

/* 统一 occurrence（发生日）形状：后端 /tasks/calendar 的 snake_case 与本地展开共用同一套取值口。 */
const occField = (occ, camel, snake) => (occ[camel] !== undefined ? occ[camel] : occ[snake])
const occRecurring = (occ) => (occ.isRecurring !== undefined ? occ.isRecurring : occ.is_recurring !== undefined ? occ.is_recurring : isRecurring(occ))
const occProgress = (occ) => ({
  on: !!(occField(occ, 'showProgress', 'show_progress')),
  done: Number(occField(occ, 'progressDone', 'progress_done') || 0),
  total: Number(occField(occ, 'progressTotal', 'progress_total') || 0),
})
const occSubjects = (occ) => {
  const list = occ.subjects && occ.subjects.length ? occ.subjects : occ.subject ? [occ.subject] : []
  return list.map(subjectName)
}
const occTitle = (occ) => occ.title

/* ========================================================================== *
 * 日期选择面板（W3：日/周/月都能一键跳到任意日期，含回看过去/预览未来）
 * ========================================================================== */
function DatePicker({ value, today, badges, onPick, onClose }) {
  const [cursor, setCursor] = useState(() => {
    const p = parseDate(value || today)
    return { year: p.getFullYear(), month: p.getMonth() + 1 }
  })
  const boxRef = useRef(null)
  useEffect(() => {
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) onClose()
    }
    // 下一拍再挂监听，避免打开面板的那一次点击立刻把它关掉
    const t = setTimeout(() => document.addEventListener('mousedown', onDown), 0)
    return () => {
      clearTimeout(t)
      document.removeEventListener('mousedown', onDown)
    }
  }, [onClose])

  const shiftMonth = (delta) => setCursor((c) => {
    const d = new Date(c.year, c.month - 1 + delta, 1)
    return { year: d.getFullYear(), month: d.getMonth() + 1 }
  })
  const cells = monthCells(cursor.year, cursor.month)
  const monthKey = `${cursor.year}-${pad2(cursor.month)}`

  return (
    <div className="v3-datepicker" ref={boxRef} role="dialog" aria-label="选择日期">
      <div className="v3-datepicker__head">
        <IconButton size="sm" variant="ghost" label="上一年" icon={<ChevronLeft size={14} />} onClick={() => setCursor((c) => ({ ...c, year: c.year - 1 }))} />
        <IconButton size="sm" variant="ghost" label="上个月" icon={<ChevronLeft size={16} />} onClick={() => shiftMonth(-1)} />
        <b>{cursor.year} 年 {cursor.month} 月</b>
        <IconButton size="sm" variant="ghost" label="下个月" icon={<ChevronRight size={16} />} onClick={() => shiftMonth(1)} />
        <IconButton size="sm" variant="ghost" label="下一年" icon={<ChevronRight size={14} />} onClick={() => setCursor((c) => ({ ...c, year: c.year + 1 }))} />
      </div>
      <div className="v3-datepicker__grid v3-datepicker__grid--head">
        {WEEK_CN_SHORT.map((w) => <span key={w}>{w}</span>)}
      </div>
      <div className="v3-datepicker__grid">
        {cells.map((d) => {
          const inMonth = d.slice(0, 7) === monthKey
          const count = badges?.[d]
          return (
            <button
              key={d}
              type="button"
              className={cx('v3-datepicker__cell', !inMonth && 'is-other', d === value && 'is-active', d === today && 'is-today')}
              onClick={() => { onPick(d); onClose() }}
            >
              {parseDate(d).getDate()}
              {count ? <i className="v3-datepicker__badge">{count > 99 ? '99+' : count}</i> : null}
            </button>
          )
        })}
      </div>
      <div className="v3-datepicker__foot">
        <Button size="sm" variant="text" onClick={() => { onPick(today); onClose() }}>回到今天</Button>
      </div>
    </div>
  )
}

/* ========================================================================== *
 * 任务新建器（W3：科目多选 + 子科目模块 + 起止日期 + 循环 + 提醒 + 进度条）
 * ========================================================================== */
const MODULE_PRESETS = { 英语: ['真题', '单词', '语法'], 数学: ['高数', '线代', '概率'], 政治: ['马原', '毛中特', '时政'] }

function TaskComposer({ subjectChoices, subjectsReady, defaultDate, backendOk, moduleDict, onAddModule, onRemoveModule, onClose, onSave }) {
  const [title, setTitle] = useState('')
  const [subjects, setSubjects] = useState([])
  const [modules, setModules] = useState([])
  const [newModule, setNewModule] = useState('')
  const [startDate, setStartDate] = useState(defaultDate || todayStr())
  const [endDate, setEndDate] = useState('')
  const [freq, setFreq] = useState('none')
  const [weekdays, setWeekdays] = useState([0, 1, 2, 3, 4])
  const [specDates, setSpecDates] = useState([])
  const [specDraft, setSpecDraft] = useState('')
  const [everyN, setEveryN] = useState(2)
  const [remindOn, setRemindOn] = useState(false)
  const [remindType, setRemindType] = useState('point')
  const [rTime, setRTime] = useState('08:00')
  const [rStart, setRStart] = useState('08:00')
  const [rEnd, setREnd] = useState('10:00')
  const [progressOn, setProgressOn] = useState(false)
  const [pTotal, setPTotal] = useState('')
  const [err, setErr] = useState('')
  const titleRef = useRef(null)

  const toggleSubject = (s) => setSubjects((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))
  const toggleModule = (m) => setModules((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]))
  const toggleWeekday = (w) => setWeekdays((cur) => (cur.includes(w) ? cur.filter((x) => x !== w) : [...cur, w]))

  /* 字典按已选科目分组展示；没选科目时展示全部（模块本质挂在科目下）。 */
  const dictGroups = useMemo(() => {
    const groups = []
    const scope = subjects.length ? subjects : [...new Set(moduleDict.map((m) => m.subject))]
    for (const s of scope) {
      const items = moduleDict.filter((m) => m.subject === s)
      if (items.length || subjects.includes(s)) groups.push({ subject: s, items })
    }
    return groups
  }, [moduleDict, subjects])

  const suggestAdd = async (subject, name) => {
    const n = String(name || '').trim()
    if (!n) return
    if (!modules.includes(n)) toggleModule(n)
    if (backendOk) {
      try { await onAddModule(subject || '其他', n) } catch { toast('模块保存到字典失败（本次任务仍会带上它）') }
    }
    setNewModule('')
  }

  const addSpecDate = () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(specDraft)) { toastErr('请选择一个日期'); return }
    setSpecDates((cur) => (cur.includes(specDraft) ? cur : [...cur, specDraft].sort()))
    setSpecDraft('')
  }

  const buildRecurrence = () => {
    if (freq === 'none') return { freq: 'none' }
    if (freq === 'weekly') return { freq, weekdays: [...weekdays].sort() }
    if (freq === 'specific') return { freq, dates: specDates }
    if (freq === 'custom') return { freq, interval: Number(everyN) || 1 }
    return { freq }
  }

  const submit = () => {
    setErr('')
    if (!title.trim()) { setErr('请填写任务名称'); titleRef.current?.focus(); return }
    if (endDate && endDate < startDate) { setErr('结束日期不能早于开始日期'); return }
    if (freq === 'weekly' && !weekdays.length) { setErr('每周指定日至少勾选一天'); return }
    if (freq === 'specific' && !specDates.length) { setErr('特定日期至少添加一天'); return }
    if (freq === 'custom' && (!Number.isFinite(Number(everyN)) || Number(everyN) < 1)) { setErr('自定义循环的间隔至少 1 天'); return }
    if (remindOn && remindType === 'range' && rEnd <= rStart) { setErr('提醒时间段的结束要晚于开始'); return }
    if (progressOn && (!Number.isFinite(Number(pTotal)) || Number(pTotal) < 1)) { setErr('进度条需要目标量（≥1）'); return }
    const recurrence = buildRecurrence()
    const remind = remindOn
      ? (remindType === 'point' ? { type: 'point', time: rTime } : { type: 'range', start: rStart, end: rEnd })
      : null
    onSave({
      title: title.trim(),
      subject: subjects[0] || null,
      subjects,
      modules,
      due_date: startDate,
      start_date: startDate,
      end_date: endDate || null,
      recurrence,
      remind,
      show_progress: progressOn,
      progress_total: progressOn ? Number(pTotal) : null,
    })
  }

  return (
    <div className="v3-stack" style={{ gap: 14 }}>
      <Field label="任务名称" hint="例如：英语真题 2018 Text4 精读">
        <Input ref={titleRef} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="要完成什么？" autoFocus />
      </Field>

      <Field label="科目（可多选）" hint={!subjectsReady ? '科目配置未加载（后端不可用），可从既有任务科目里选' : undefined}>
        <div className="v3-chip-row">
          {subjectChoices.map((s) => (
            <Chip key={s} active={subjects.includes(s)} onClick={() => toggleSubject(s)}>{subjectName(s)}</Chip>
          ))}
          {!subjects.includes('其他') && !subjectChoices.includes('其他') ? (
            <Chip active={subjects.includes('其他')} onClick={() => toggleSubject('其他')}>其他</Chip>
          ) : null}
          {!subjects.length ? <span className="v3-caption">不选 = 未分类</span> : null}
        </div>
      </Field>

      <Field label="子科目模块（可增删）" hint="如 英语→真题/单词/语法；添加后进入你的个人字典，× 可删除">
        <div className="v3-stack" style={{ gap: 8 }}>
          {dictGroups.map((g) => (
            <div key={g.subject} className="v3-chip-row" style={{ alignItems: 'center' }}>
              <span className="v3-caption">{subjectName(g.subject)}</span>
              {g.items.map((m) => (
                <Chip key={m.id ?? m.name} active={modules.includes(m.name)} onClick={() => toggleModule(m.name)}>
                  {m.name}
                  {backendOk && m.id != null ? (
                    <span
                      className="v3-chip__kill"
                      role="button"
                      tabIndex={0}
                      aria-label={`删除模块 ${m.name}`}
                      onClick={(e) => { e.stopPropagation(); onRemoveModule(m) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onRemoveModule(m) } }}
                    >×</span>
                  ) : null}
                </Chip>
              ))}
              {MODULE_PRESETS[subjectName(g.subject)]?.filter((p) => !g.items.some((m) => m.name === p)).map((p) => (
                <Chip key={`suggest-${p}`} onClick={() => suggestAdd(g.subject, p)} title="快速添加到我的模块">＋{p}</Chip>
              ))}
            </div>
          ))}
          {modules.filter((m) => !dictGroups.some((g) => g.items.some((x) => x.name === m))).map((m) => (
            <Chip key={m} active onClick={() => toggleModule(m)}>{m}</Chip>
          ))}
          <div className="v3-row" style={{ gap: 6 }}>
            <Input
              style={{ maxWidth: 180 }}
              value={newModule}
              onChange={(e) => setNewModule(e.target.value)}
              placeholder="新模块名（如 作文）"
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); suggestAdd(subjects[0], newModule) } }}
            />
            <Button size="sm" variant="tonal" icon={<Plus size={14} />} onClick={() => suggestAdd(subjects[0], newModule)}>添加</Button>
          </div>
        </div>
      </Field>

      <div className="v3-row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <Field label="开始日期">
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </Field>
        <Field label="结束日期" hint="留空 = 不限">
          <Input type="date" value={endDate} min={startDate} onChange={(e) => setEndDate(e.target.value)} />
        </Field>
      </div>

      <Field label="循环规则">
        <div className="v3-stack" style={{ gap: 8 }}>
          <Select value={freq} onChange={(e) => setFreq(e.target.value)} options={FREQ_OPTIONS} />
          {freq === 'weekly' && (
            <div className="v3-chip-row">
              {WEEK_CN_SHORT.map((w, i) => (
                <Chip key={w} active={weekdays.includes(i)} onClick={() => toggleWeekday(i)}>{w}</Chip>
              ))}
            </div>
          )}
          {freq === 'custom' && (
            <label className="v3-row" style={{ gap: 8 }}>
              每
              <Input type="number" min={1} style={{ width: 90 }} value={everyN} onChange={(e) => setEveryN(e.target.value)} />
              天一次（从开始日期起算）
            </label>
          )}
          {freq === 'specific' && (
            <div className="v3-stack" style={{ gap: 6 }}>
              <div className="v3-row" style={{ gap: 6 }}>
                <Input type="date" style={{ maxWidth: 190 }} value={specDraft} onChange={(e) => setSpecDraft(e.target.value)} />
                <Button size="sm" variant="tonal" icon={<Plus size={14} />} onClick={addSpecDate}>添加日期</Button>
              </div>
              <div className="v3-chip-row">
                {specDates.map((d) => (
                  <Chip key={d} active onClick={() => setSpecDates((cur) => cur.filter((x) => x !== d))} title="点击移除">{fmtDateCN(d)}</Chip>
                ))}
                {!specDates.length ? <span className="v3-caption">还没有日期</span> : null}
              </div>
            </div>
          )}
          {freq === 'ebbinghaus' && (
            <span className="v3-caption">按开始日期生成 1/2/4/7/15/30 天复习点（日粒度日历；分钟级节奏在「学习计划 · 艾宾浩斯」表里单独维护）。</span>
          )}
          {freq !== 'none' && <span className="v3-caption">循环任务的完成按「每一天」记录，可补打卡、可回看。</span>}
        </div>
      </Field>

      <Field label="提醒" hint={remindOn ? '提醒目前仅在当日待办中标注展示，暂未接系统推送（诚实标注）' : undefined}>
        <div className="v3-stack" style={{ gap: 8 }}>
          <div className="v3-row" style={{ gap: 8 }}>
            <Switch checked={remindOn} onChange={setRemindOn} label="开启提醒" />
            {remindOn ? <span className="v3-row" style={{ gap: 4 }}><Bell size={14} /><Badge tone="primary">{remindOn ? '已设置' : ''}</Badge></span> : <span className="v3-caption">不提醒</span>}
          </div>
          {remindOn && (
            <div className="v3-row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <Select value={remindType} onChange={(e) => setRemindType(e.target.value)} options={[{ value: 'point', label: '时间点' }, { value: 'range', label: '时间段' }]} />
              {remindType === 'point' ? (
                <Input type="time" value={rTime} onChange={(e) => setRTime(e.target.value)} style={{ maxWidth: 140 }} />
              ) : (
                <>
                  <Input type="time" value={rStart} onChange={(e) => setRStart(e.target.value)} style={{ maxWidth: 140 }} />
                  <span className="v3-caption">至</span>
                  <Input type="time" value={rEnd} onChange={(e) => setREnd(e.target.value)} style={{ maxWidth: 140 }} />
                </>
              )}
            </div>
          )}
        </div>
      </Field>

      <Field label="进度条">
        <div className="v3-row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <Switch checked={progressOn} onChange={setProgressOn} label="给任务加进度条" />
          {progressOn ? (
            <label className="v3-row" style={{ gap: 6 }}>
              目标量
              <Input type="number" min={1} style={{ width: 110 }} value={pTotal} onChange={(e) => setPTotal(e.target.value)} placeholder="如 100" />
              （打卡/手动 ± 递增，封顶目标量）
            </label>
          ) : <span className="v3-caption">不加</span>}
        </div>
      </Field>

      {err ? <Alert tone="danger">{err}</Alert> : null}
      <div className="v3-row" style={{ justifyContent: 'flex-end' }}>
        <Button variant="text" onClick={onClose}>取消</Button>
        <Button variant="gradient" onClick={submit}>保存任务</Button>
      </div>
    </div>
  )
}

/* ========================================================================== *
 * 主页面
 * ========================================================================== */
export default function Tasks() {
  const tasks = useStore((s) => s.tasks)
  const addTask = useStore((s) => s.addTask)
  const toggleTask = useStore((s) => s.toggleTask)
  const removeTask = useStore((s) => s.removeTask)
  const importTasks = useStore((s) => s.importTasks)

  const [view, setView] = useState('day')
  const [date, setDate] = useState(todayStr())
  const [showAdd, setShowAdd] = useState(false)
  const [showExport, setShowExport] = useState(false)
  const [showAi, setShowAi] = useState(false)
  const [showPicker, setShowPicker] = useState(false)
  const [confirm, dialog] = useConfirm()
  const [aiTitle, setAiTitle] = useState('')
  const [genTasks, setGenTasks] = useState(null)
  const [aiPlanText, setAiPlanText] = useState(null)
  const [aiErr, setAiErr] = useState('')
  const [aiBusy, setAiBusy] = useState(false)
  const [sortAsc, setSortAsc] = useState(false)

  const { active: configuredSubjects, ready: subjectsReady } = useSubjectConfig()
  const subjectChoices = useMemo(() => {
    const out = []
    const push = (v) => {
      const raw = String(v || '').trim()
      if (raw && !out.some((o) => subjectName(o) === subjectName(raw))) out.push(raw)
    }
    if (subjectsReady) for (const s of configuredSubjects) push(s)
    for (const t of tasks || []) for (const s of (t.subjects?.length ? t.subjects : [t.subject])) push(s)
    return out
  }, [configuredSubjects, subjectsReady, tasks])

  useEffect(() => {
    const handler = (e) => {
      if (view !== 'day' || showAdd || showAi || showExport) return
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return
      if (e.key === 'ArrowLeft') { e.preventDefault(); setDate((d) => addDays(d, -1)) }
      else if (e.key === 'ArrowRight') { e.preventDefault(); setDate((d) => addDays(d, 1)) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [view, showAdd, showAi, showExport])

  const [backendOk, setBackendOk] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [moduleDict, setModuleDict] = useState([])

  const refresh = useCallback(async () => {
    setSyncing(true)
    try {
      await loadDomain('tasks')
      setBackendOk(true)
    } catch {
      setBackendOk(false)
    } finally {
      setSyncing(false)
    }
  }, [])
  useEffect(() => { refresh() }, [refresh])

  /* 模块字典：后端在线才拉（个人数据，本地模式不编造）。 */
  const reloadModules = useCallback(() => {
    if (!backendOk) return
    tasksApi.modules().then((d) => setModuleDict(d?.items || [])).catch(() => {})
  }, [backendOk])
  useEffect(() => { reloadModules() }, [reloadModules])

  const withBackend = async (fn, localFn) => {
    if (!backendOk) { localFn(); return }
    try {
      setSyncing(true)
      await fn()
      await refresh()
    } catch {
      localFn()
      toast('后端同步失败，已保存到本地')
    } finally {
      setSyncing(false)
    }
  }

  /* ---------- 发生日（occurrence）：在线走 /tasks/calendar，离线本地同口径展开 ---------- */
  const range = useMemo(() => visibleRange(view, date), [view, date])
  const [occs, setOccs] = useState(null)
  const seqRef = useRef(0)
  useEffect(() => {
    if (!backendOk) { setOccs(null); return }
    const seq = (seqRef.current += 1)
    tasksApi.calendar({ start: range.start, end: range.end })
      .then((d) => { if (seq === seqRef.current) setOccs(d?.items || []) })
      .catch(() => { if (seq === seqRef.current) setOccs(null) })
  }, [backendOk, range.start, range.end])

  const localOccs = useMemo(() => {
    if (backendOk && occs) return null
    const out = []
    for (const t of tasks || []) {
      const dates = expandTaskDates(t, range.start, range.end)
      const recurring = isRecurring(t)
      for (const d of dates) {
        out.push({
          ...t,
          date: d,
          recurring,
          done: recurring ? (t.doneDates || []).includes(d) : !!t.done,
          checkin: recurring && (t.doneDates || []).includes(d),
        })
      }
    }
    return out
  }, [backendOk, occs, tasks, range.start, range.end])

  const occsSorted = useMemo(() => {
    const arr = [...((backendOk && occs ? occs : localOccs) || [])]
    arr.sort((a, b) => (a.date === b.date ? (Number(b.priority || 0) - Number(a.priority || 0)) : a.date.localeCompare(b.date)))
    return arr
  }, [backendOk, occs, localOccs])

  const occByDate = useMemo(() => {
    const m = {}
    for (const o of occsSorted) (m[o.date] = m[o.date] || []).push(o)
    return m
  }, [occsSorted])

  const today = todayStr()
  const todayOccs = occByDate[today] || []
  const doneAll = tasks.filter((t) => t.done).length
  /* 口径注释（P2 契约）：todayDue 是「今天到期的发生日条数」（含已完成与循环任务展开）；
     doneAll/tasks.length 是**全部累积任务**的整任务完成数，两者分开表述不混算。 */
  const todayDue = todayOccs.length

  const dayTasks = useMemo(() => {
    const list = occByDate[date] || []
    if (!sortAsc) return list
    return [...list].sort((a, b) => occTitle(a).localeCompare(occTitle(b), 'zh'))
  }, [occByDate, date, sortAsc])

  const groups = useMemo(() => {
    const g = {}
    for (const t of dayTasks) {
      const key = (t.subjects && t.subjects.length ? t.subjects[0] : t.subject) || 'other'
      if (!g[key]) g[key] = { tasks: [], done: 0 }
      g[key].tasks.push(t)
      if (t.done) g[key].done++
    }
    return g
  }, [dayTasks])

  const week = useMemo(() => {
    const start = weekStartOf(date)
    return Array.from({ length: 7 }, (_, i) => {
      const d = addDays(start, i)
      return { date: d, tasks: occByDate[d] || [] }
    })
  }, [date, occByDate])

  const month = useMemo(() => {
    const d = parseDate(date)
    return { year: d.getFullYear(), month: d.getMonth() + 1, cells: monthMatrix(d.getFullYear(), d.getMonth() + 1) }
  }, [date])

  /* 日期选择面板上的角标：可见窗口内每天发生数 */
  const pickerBadges = useMemo(() => {
    const m = {}
    for (const o of occsSorted) m[o.date] = (m[o.date] || 0) + 1
    return m
  }, [occsSorted])

  /* ---------- 交互 ---------- */
  const shiftView = (delta) => {
    if (view === 'day') setDate((d) => addDays(d, delta))
    else if (view === 'week') setDate((d) => addDays(d, delta * 7))
    else {
      setDate((d) => {
        const p = parseDate(d)
        const nd = new Date(p.getFullYear(), p.getMonth() + delta, Math.min(p.getDate(), 28))
        return `${nd.getFullYear()}-${pad2(nd.getMonth() + 1)}-${pad2(nd.getDate())}`
      })
    }
  }

  const occKey = (o) => `${o.id}@${o.date}`

  const onToggleOcc = (occ) => {
    const recurring = occRecurring(occ)
    if (!recurring) {
      /* 非循环单日：维持既有乐观打卡口径（store → /complete 旧语义） */
      const id = String(occ.id)
      if (!tasks.some((x) => x.id === id)) return
      toggleTask(id)
      return
    }
    if (backendOk) {
      const call = occ.done ? tasksApi.uncomplete(occ.id, { date: occ.date }) : tasksApi.complete(occ.id, { date: occ.date })
      Promise.resolve(call).then(refresh).catch(() => toast('后端同步失败，请稍后重试'))
    } else {
      useStore.setState((s) => ({
        tasks: s.tasks.map((t) => {
          if (t.id !== String(occ.id)) return t
          const dates = new Set(t.doneDates || [])
          if (occ.done) dates.delete(occ.date)
          else dates.add(occ.date)
          return { ...t, doneDates: [...dates].sort() }
        }),
      }))
    }
  }

  const onProgressStep = (occ, delta) => {
    if (backendOk) {
      tasksApi.progress(occ.id, { delta }).then(refresh).catch((e) => toastErr(e?.message || '进度更新失败'))
      return
    }
    useStore.setState((s) => ({
      tasks: s.tasks.map((t) => {
        if (t.id !== String(occ.id)) return t
        const total = Number(t.progressTotal) || 0
        const next = Math.max(0, Math.min(total, (t.progressDone || 0) + delta))
        return { ...t, progressDone: next }
      }),
    }))
  }

  const onRemove = async (occ) => {
    if (!(await confirm({ title: '删除任务', message: '删除后不可恢复（含全部循环日期），确定删除该任务吗？', danger: true }))) return
    removeTask(String(occ.id))
    toast('已删除')
  }

  useEffect(() => {
    const onSyncError = (e) => {
      const op = String(e?.detail?.operationName || '')
      if (op.startsWith('任务')) toastErr(`${op}未同步，已加入失败队列，网络恢复后自动重试`)
    }
    window.addEventListener('sync-error', onSyncError)
    return () => window.removeEventListener('sync-error', onSyncError)
  }, [])

  /* ---------- 新建 ---------- */
  const saveNewTask = (payload) => {
    const localShape = {
      title: payload.title,
      subject: payload.subject || '',
      subjects: payload.subjects || [],
      modules: payload.modules || [],
      due: payload.due_date,
      start: payload.start_date,
      end: payload.end_date,
      recurrence: payload.recurrence,
      remind: payload.remind,
      showProgress: !!payload.show_progress,
      progressTotal: payload.progress_total,
      progressDone: 0,
      doneDates: [],
      isRecurring: payload.recurrence?.freq !== 'none',
    }
    withBackend(
      () => tasksApi.create(payload),
      () => { addTask(localShape); toastOk('任务已添加（本地）') },
    )
    setShowAdd(false)
  }

  /* ---------- AI ---------- */
  const submitAi = async () => {
    setAiErr('')
    if (!backendOk) {
      setAiErr('AI 规划需要后端在线（当前后端不可用）。可在「设置 → AI 服务」检查配置后重试。')
      setGenTasks(null)
      setAiPlanText(null)
      return
    }
    setAiBusy(true)
    try {
      const r = await tasksApi.aiGenerate({ topic: aiTitle.trim() })
      const list = Array.isArray(r?.tasks) ? r.tasks : (Array.isArray(r?.items) ? r.items : [])
      if (list.length) {
        setGenTasks(list.map((t) => ({ title: t.title, subject: t.subject || '' })))
        setAiPlanText(null)
      } else if (r?.plan && typeof r.plan === 'string') {
        setAiPlanText(r.plan)
        setGenTasks(null)
      } else {
        setAiErr('后端没有返回可用的计划内容。')
      }
    } catch (e) {
      setAiErr(friendlyAiError(e))
    } finally {
      setAiBusy(false)
    }
  }

  const confirmImport = () => {
    if (backendOk) {
      Promise.all(genTasks.map((t) => tasksApi.create({ title: t.title, subject: t.subject, due_date: today })))
        .then(refresh)
        .catch(() => toast('部分任务导入失败'))
      toast(`正在导入 ${genTasks.length} 项任务`)
    } else {
      importTasks(genTasks)
      toast(`已导入 ${genTasks.length} 项任务`)
    }
    setGenTasks(null)
    setShowAi(false)
    setAiTitle('')
  }

  /* ---------- 导出（列表式 + 日期区间） ---------- */
  const [expStart, setExpStart] = useState(() => monthGridRange(todayStr()).start)
  const [expEnd, setExpEnd] = useState(() => monthGridRange(todayStr()).end)
  const [expBusy, setExpBusy] = useState(false)

  const gatherExport = useCallback(async () => {
    if (backendOk) {
      const d = await tasksApi.calendar({ start: expStart, end: expEnd })
      return d?.items || []
    }
    const out = []
    for (const t of tasks || []) {
      for (const dd of expandTaskDates(t, expStart, expEnd)) {
        const recurring = isRecurring(t)
        out.push({ ...t, date: dd, recurring, done: recurring ? (t.doneDates || []).includes(dd) : !!t.done })
      }
    }
    return out.sort((a, b) => a.date.localeCompare(b.date))
  }, [backendOk, tasks, expStart, expEnd])

  const exportList = async (mode) => {
    setExpBusy(true)
    try {
      const rows = await gatherExport()
      if (!rows.length) { toast('所选区间没有任务'); return }
      const weekName = (d) => `周${WEEK_CN_SHORT[weekdayIdx(d)]}`
      if (mode === 'csv') {
        const lines = [['日期', '星期', '标题', '科目', '模块', '循环', '提醒', '状态', '进度'].map(csvCell).join(',')]
        for (const r of rows) {
          const p = occProgress(r)
          lines.push([
            r.date, weekName(r.date), occTitle(r),
            occSubjects(r).join('/'), (r.modules || []).join('/'), freqLabel(r), remindLabel(r).replace('⏰ ', ''),
            r.done ? '已完成' : '未完成',
            p.on ? `${p.done}/${p.total}` : '',
          ].map(csvCell).join(','))
        }
        const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `tasks-${expStart}~${expEnd}.csv`
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
        toastOk(`已导出 ${rows.length} 条（${expStart} ~ ${expEnd}）`)
      } else {
        const byDate = {}
        for (const r of rows) (byDate[r.date] = byDate[r.date] || []).push(r)
        const md = [`# 任务清单（${expStart} ~ ${expEnd}）`, '']
        for (const d of Object.keys(byDate).sort()) {
          md.push(`## ${d} ${weekName(d)}`)
          for (const r of byDate[d]) {
            const bits = [occSubjects(r).join('/'), (r.modules || []).join('/'), freqLabel(r), remindLabel(r)].filter(Boolean).join(' · ')
            const p = occProgress(r)
            md.push(`- [${r.done ? 'x' : ' '}] ${taskEmoji(r)} ${occTitle(r)}${bits ? `（${bits}）` : ''}${p.on ? ` — ${p.done}/${p.total}` : ''}`)
          }
          md.push('')
        }
        await navigator.clipboard.writeText(md.join('\n'))
        toastOk(`清单已复制（${rows.length} 条）`)
      }
      setShowExport(false)
    } catch (e) {
      toastErr(e?.message || '导出失败')
    } finally {
      setExpBusy(false)
    }
  }

  /* ---------- 渲染 ---------- */
  const renderRow = (t) => {
    const recurring = occRecurring(t)
    const p = occProgress(t)
    const fl = freqLabel(t)
    const rl = remindLabel(t)
    return (
      <div key={occKey(t)} className={cx('v3-task-row', t.done && 'is-done')}>
        <button type="button" className="v3-task-row__check" onClick={() => onToggleOcc(t)} aria-label={t.done ? '撤销完成' : '标记完成'}>
          {t.done ? <Check size={14} /> : null}
        </button>
        <div className="v3-task-row__main">
          <span className="v3-task-row__title">
            <span className="v3-task-row__emoji" aria-hidden="true">{taskEmoji(t)}</span>
            {occTitle(t)}
          </span>
          <span className="v3-task-row__tags">
            {occSubjects(t).map((s) => <Badge key={s}>{s}</Badge>)}
            {(t.modules || []).map((m) => <Badge key={m} tone="outline">{m}</Badge>)}
            {fl ? <span className="v3-caption"><RefreshCw size={11} /> {fl}</span> : null}
            {rl ? <span className="v3-caption">{rl}（仅展示）</span> : null}
            {recurring ? <span className="v3-caption">{t.date === today ? '今天' : fmtDateCN(t.date)}</span> : null}
            {t.ai ? <span className="v3-caption">AI 规划</span> : null}
          </span>
          {p.on ? (
            <span className="v3-task-row__progress">
              <Progress value={p.total ? (p.done / p.total) * 100 : 0} height={6} gradient />
              <span className="v3-caption">{p.done}/{p.total}</span>
              <button type="button" className="v3-step-btn" aria-label="进度减一" onClick={() => onProgressStep(t, -1)}>−</button>
              <button type="button" className="v3-step-btn" aria-label="进度加一" onClick={() => onProgressStep(t, 1)}>＋</button>
            </span>
          ) : null}
        </div>
        <Badge tone={t.done ? 'success' : 'primary'}>{t.done ? '已完成' : recurring ? '待打卡' : '进行中'}</Badge>
        <Button size="sm" variant={t.done ? 'text' : 'tonal'} onClick={() => onToggleOcc(t)}>{t.done ? '撤销' : '完成'}</Button>
        <IconButton label="删除" size="sm" variant="ghost" icon={<Trash size={15} />} onClick={() => onRemove(t)} />
      </div>
    )
  }

  const dateLabelText = view === 'month'
    ? `${month.year} 年 ${month.month} 月`
    : view === 'week'
      ? `${fmtDateCN(week[0].date)} ~ ${fmtDateCN(week[6].date)}`
      : `${fmtDateCN(date)} · ${WEEK_CN_SHORT[weekdayIdx(date)]}`

  return (
    <div className="v3-stack v3-glasspage" style={{ gap: 18 }}>
      <header className="v3-page-head">
        <div>
          <div className="v3-eyebrow">TASKS · 日 / 周 / 月</div>
          <h1 className="v3-h1" style={{ marginTop: 6 }}>任务打卡</h1>
          <p className="v3-body" style={{ marginTop: 6 }}>
            今日到期 {todayDue} · 已完成 {doneAll}/{tasks.length}
            {backendOk ? ' · 后端已连接' : ' · 本地模式'}
            {syncing ? ' · 同步中…' : ''}
          </p>
        </div>
        <div className="v3-row" style={{ gap: 8 }}>
          <Button variant="tonal" icon={<Brain size={16} />} onClick={() => setShowAi(true)}>AI 生成</Button>
          <Button variant="gradient" icon={<Plus size={16} />} onClick={() => setShowAdd(true)}>新建任务</Button>
        </div>
      </header>

      {!backendOk && (
        <Alert tone="warning" icon={<Sparkles size={16} />}>
          <b>本地模式：数据未同步。</b> 当前任务只保存在本机浏览器，后端恢复后刷新即可拉取服务器数据；循环任务的打卡记录同样只存本地。
        </Alert>
      )}

      <div className="v3-toolbar">
        <div className="v3-row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <Segmented options={VIEWS} value={view} onChange={setView} ariaLabel="任务视图" />
          <div className="v3-row" style={{ gap: 4 }}>
            <IconButton label="上一页" icon={<ChevronLeft size={16} />} onClick={() => shiftView(-1)} />
            <div className="v3-datepicker-anchor">
              <Button size="sm" variant={showPicker ? 'tonal' : 'text'} icon={<Calendar size={15} />} onClick={() => setShowPicker((v) => !v)} aria-haspopup="dialog">
                {dateLabelText}
              </Button>
              {showPicker ? (
                <DatePicker
                  value={date}
                  today={today}
                  badges={pickerBadges}
                  onPick={setDate}
                  onClose={() => setShowPicker(false)}
                />
              ) : null}
            </div>
            <IconButton label="下一页" icon={<ChevronRight size={16} />} onClick={() => shiftView(1)} />
            <Button size="sm" variant="text" onClick={() => setDate(today)}>今天</Button>
            {date !== today && view === 'day' ? <Badge tone="outline">{date < today ? '回看' : '未来'}</Badge> : null}
          </div>
        </div>
        <div className="v3-row" style={{ gap: 8 }}>
          <Button size="sm" variant={sortAsc ? 'tonal' : 'text'} onClick={() => setSortAsc((v) => !v)}>按标题排序</Button>
          <Button size="sm" variant="text" icon={<Download size={15} />} onClick={() => {
            const r = visibleRange(view, date)
            setExpStart(r.start)
            setExpEnd(r.end)
            setShowExport(true)
          }}>导出</Button>
        </div>
      </div>

      {view === 'day' && (
        Object.keys(groups).length === 0 ? (
          <div className="v3-card" style={{ padding: 40 }}>
            <Empty icon={<Target size={26} />} title="这一天没有任务" text="点击「新建任务」或「AI 生成」安排复习；循环任务会自动出现在每一天。" action={<Button variant="tonal" size="sm" onClick={() => setShowAdd(true)}>新建任务</Button>} />
          </div>
        ) : (
          <div className="v3-task-groups">
            {Object.keys(groups).map((k) => {
              const g = groups[k]
              const pct = g.tasks.length ? Math.round((g.done / g.tasks.length) * 100) : 0
              return (
                <section key={k} className="v3-card v3-task-group">
                  <header className="v3-task-group__head">
                    <div className="v3-row" style={{ gap: 10 }}>
                      <span className={cx('v3-subject-dot', `tone-${subjectTone(k)}`)} />
                      <strong>{subjectName(k)}</strong>
                      <span className="v3-caption">{g.done}/{g.tasks.length} 完成</span>
                    </div>
                    <div style={{ width: 150 }}><Progress value={pct} height={6} gradient /></div>
                  </header>
                  <div className="v3-task-list">
                    {g.tasks.map(renderRow)}
                  </div>
                </section>
              )
            })}
          </div>
        )
      )}

      {view === 'week' && (
        <div className="v3-week">
          {week.map((d, i) => {
            const pct = d.tasks.length ? Math.round((d.tasks.filter((t) => t.done).length / d.tasks.length) * 100) : 0
            const shown = d.tasks.slice(0, 4)
            const rest = d.tasks.length - shown.length
            return (
              <div key={d.date} className={cx('v3-week__col', d.date === today && 'is-today')}>
                <button type="button" className="v3-week__head v3-week__head--link" onClick={() => { setView('day'); setDate(d.date) }} title="打开这一天">
                  <span>{WEEK_CN_SHORT[i]}</span>
                  <b>{parseDate(d.date).getDate()}</b>
                  {d.date === today ? <em>今天</em> : null}
                  {d.tasks.length ? <span className="v3-week__count">{d.tasks.filter((t) => t.done).length}/{d.tasks.length}</span> : null}
                </button>
                <div className="v3-week__bar"><Progress value={pct} height={4} gradient /></div>
                <div className="v3-week__body">
                  {shown.map((t) => (
                    <button key={occKey(t)} type="button" className={cx('v3-week__task', t.done && 'is-done')} onClick={() => onToggleOcc(t)} title={t.done ? '点击撤销' : '点击打卡'}>
                      <i />
                      <span aria-hidden="true">{taskEmoji(t)}</span>
                      <span>{occTitle(t)}</span>
                    </button>
                  ))}
                  {!d.tasks.length ? <span className="v3-caption">无任务</span> : null}
                  {rest > 0 ? (
                    <button type="button" className="v3-week__more" onClick={() => { setView('day'); setDate(d.date) }}>+{rest} 查看全部</button>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {view === 'month' && (
        <div className="v3-card v3-cal">
          {WEEK_CN_SHORT.map((w) => <div key={w} className="v3-cal__head">周{w}</div>)}
          {month.cells.flat().map((d) => {
            const list = occByDate[d] || []
            const done = list.filter((t) => t.done).length
            const other = d.slice(0, 7) !== `${month.year}-${pad2(month.month)}`
            return (
              <button
                key={d}
                type="button"
                className={cx('v3-cal__cell', d === today && 'is-today', other && 'is-other', d === date && 'is-active')}
                onClick={() => { setView('day'); setDate(d) }}
              >
                <span className="v3-cal__day">{parseDate(d).getDate()}</span>
                <span className="v3-cal__dots">
                  {list.slice(0, 3).map((t) => <i key={occKey(t)} className={t.done ? 'done' : ''} />)}
                  {list.length > 3 ? <em className="v3-cal__more">+{list.length - 3}</em> : null}
                </span>
                {list.length ? <span className="v3-cal__pct">{done}/{list.length}</span> : null}
              </button>
            )
          })}
        </div>
      )}

      <Dialog open={showAdd} title="新建任务" sub="科目多选 · 子科目模块 · 循环 · 提醒 · 进度条" wide onClose={() => setShowAdd(false)} footer={null}>
        <TaskComposer
          subjectChoices={subjectChoices}
          subjectsReady={subjectsReady}
          defaultDate={date}
          backendOk={backendOk}
          moduleDict={moduleDict}
          onAddModule={async (subject, name) => {
            const r = await tasksApi.addModule({ subject, name })
            setModuleDict((cur) => (cur.some((m) => m.subject === r.subject && m.name === r.name) ? cur : [...cur, r]))
          }}
          onRemoveModule={(m) => {
            if (m.id == null) return
            tasksApi.removeModule(m.id).then(() => setModuleDict((cur) => cur.filter((x) => x.id !== m.id))).catch(() => toast('删除失败'))
          }}
          onClose={() => setShowAdd(false)}
          onSave={saveNewTask}
        />
      </Dialog>

      <Dialog open={showExport} title="导出任务清单" sub="按日期区间导出列表（CSV 下载 / Markdown 复制）" onClose={() => setShowExport(false)} footer={(
        <>
          <Button variant="text" onClick={() => setShowExport(false)}>取消</Button>
          <Button variant="tonal" loading={expBusy} icon={<Layers size={15} />} onClick={() => exportList('md')}>复制清单</Button>
          <Button variant="gradient" loading={expBusy} icon={<Download size={15} />} onClick={() => exportList('csv')}>导出 CSV</Button>
        </>
      )}>
        <div className="v3-stack" style={{ gap: 14 }}>
          <div className="v3-row" style={{ gap: 10, flexWrap: 'wrap' }}>
            <Field label="开始日期"><Input type="date" value={expStart} max={expEnd} onChange={(e) => setExpStart(e.target.value)} /></Field>
            <Field label="结束日期"><Input type="date" value={expEnd} min={expStart} onChange={(e) => setExpEnd(e.target.value)} /></Field>
          </div>
          <span className="v3-caption">区间内每个发生日一行（循环任务逐日展开），含科目/模块/循环/提醒/进度与完成状态。</span>
        </div>
      </Dialog>

      <Dialog open={showAi} title="AI 生成任务" sub="先预览，再决定是否导入" onClose={() => { setShowAi(false); setAiPlanText(null); setAiErr('') }} footer={(genTasks || aiPlanText) ? (
        <>
          <Button variant="text" onClick={() => { setGenTasks(null); setAiPlanText(null); setAiErr('') }}>重新生成</Button>
          {genTasks ? <Button variant="gradient" onClick={confirmImport}>确认导入</Button> : null}
        </>
      ) : null}>
        <div className="v3-stack" style={{ gap: 14 }}>
          {!genTasks && !aiPlanText && (
            <>
              <Field label="主题（可选）" hint="留空则按目标院校与待办数生成全科复习计划">
                <Input value={aiTitle} onChange={(e) => setAiTitle(e.target.value)} placeholder="如：线性代数特征值强化" />
              </Field>
              <Button variant="gradient" icon={<Sparkles size={16} />} loading={aiBusy} onClick={submitAi}>生成复习计划</Button>
              {aiErr ? <Alert tone="danger">{aiErr}</Alert> : null}
            </>
          )}
          {aiPlanText && (
            <div className="v3-stack" style={{ gap: 10 }}>
              <span className="v3-caption">AI 生成的学习计划（文本）</span>
              <Textarea readOnly value={aiPlanText} style={{ minHeight: 260 }} />
              <div className="v3-row">
                <Button size="sm" variant="tonal" onClick={() => navigator.clipboard.writeText(aiPlanText).then(() => toast('已复制到剪贴板'))}>复制全文</Button>
                <Button size="sm" variant="text" onClick={() => setAiPlanText(null)}>重新生成</Button>
              </div>
              <span className="v3-caption">复制计划后可手动拆成任务；结构化任务会直接给出「确认导入」。</span>
            </div>
          )}
          {genTasks && (
            <div className="v3-task-list">
              {genTasks.map((g, i) => (
                <div key={i} className="v3-task-row">
                  <span className="v3-task-row__check is-ai"><Brain size={13} /></span>
                  <div className="v3-task-row__main">
                    <span className="v3-task-row__title">{g.title}</span>
                    <span className="v3-caption">{subjectName(g.subject)} · AI 生成，导入前请核对</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Dialog>
      {dialog}
    </div>
  )
}
