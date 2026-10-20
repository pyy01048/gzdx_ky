import React, { useMemo, useState, useCallback, useEffect, useRef } from 'react'
import useStore from '../store/useStore'
import { todayStr, addDays, monthMatrix, weekdayIdx, fmtDateCN, parseDate } from '../utils/date'
import { SubTag, Modal, Segmented, Empty, toast, toastOk, toastErr, focusAndScroll, useConfirm } from '../components/UI'
import { Target, Brain, AlertCircle, Plus, ChevronLeft, ChevronRight } from '../components/Icon'
import { tasksApi } from '../api/client'
import { friendlyAiError } from '../utils/aiError'
import { loadDomain } from '../api/sync'
import { useSubjectConfig } from '../hooks/useSubjectConfig'

/* 科目一律来自后端科目配置（hooks/useSubjectConfig），这里只保留**旧英文码 → 中文**
   的显示映射：历史数据存的是 math/english/…，新数据直接存后端配置里的真实科目名。 */
const LEGACY_SUBJECT_CODES = { math: '数学', english: '英语', politics: '政治', major: '专业课', other: '其他' }
const subjectName = (v) => LEGACY_SUBJECT_CODES[v] || v || '未分类'

const csvCell = (v) => {
  const s = String(v ?? '')
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

export default function Tasks() {
  /* 字段级选择器：store 其他字段变化不再触发本页重渲染（actions 引用稳定，不会引发额外渲染） */
  const tasks = useStore((s) => s.tasks)
  const addTask = useStore((s) => s.addTask)
  const toggleTask = useStore((s) => s.toggleTask)
  const removeTask = useStore((s) => s.removeTask)
  const importTasks = useStore((s) => s.importTasks)
  const updateTask = useStore((s) => s.updateTask)
  const settings = useStore((s) => s.settings)
  const [view, setView] = useState('day')
  const [date, setDate] = useState(todayStr())
  const [showAdd, setShowAdd] = useState(false)
  /* E2E2-001 修复（2026-10-18）：原「新建任务」按钮绑定的是 showInlineAdd（内联快加表单），
     而该表单只在「当天已有任务」的列表分支里渲染——空日期点击必然无响应（dogfood ISSUE-001
     与 E2E2-001 的真凶）。现改开全字段弹窗 showAdd，任何视图/空态都可用；不可达的内联表单已移除。 */
  const [showAi, setShowAi] = useState(false)
  /* 删除任务二次确认（e2e3 回归建议）：误触即丢数据，用全站统一的 Promise 确认框 */
  const [confirm, dialog] = useConfirm()
  const [title, setTitle] = useState('')
  const [subject, setSubject] = useState('')
  const addTitleRef = useRef(null)
  const [aiTitle, setAiTitle] = useState('')
  const [genTasks, setGenTasks] = useState(null)
  const [aiPlanText, setAiPlanText] = useState(null)
  const [aiErr, setAiErr] = useState('')
  const [calShift, setCalShift] = useState(0)
  const [sortAsc, setSortAsc] = useState(false)

  /* 科目下拉的唯一来源：后端科目配置（/api/goals/subjects）。
     配置还没到位时宁可只给「未分类」，也不再写死数学/英语/政治/专业课四个科目——
     用户换科目方向后这四条就成了假选项。 */
  const { active: configuredSubjects, ready: subjectsReady } = useSubjectConfig()
  const subjectChoices = useMemo(() => {
    const out = []
    const push = (v) => {
      const raw = String(v || '').trim()
      if (raw && !out.some((o) => subjectName(o) === subjectName(raw))) out.push(raw)
    }
    if (subjectsReady) for (const s of configuredSubjects) push(s)
    for (const t of tasks || []) push(t.subject)
    return out
  }, [configuredSubjects, subjectsReady, tasks])

  /* 旧数据里存的是 math/major 这类英文码，配置就绪后把选中值迁到真实科目 */
  useEffect(() => {
    if (!subjectChoices.length) return
    const migrate = (v) => {
      if (subjectChoices.includes(v)) return v
      // 空值或旧英文码 → 用配置里的第一个真实科目；已经是真实科目名 → 原样保留
      return (!v || LEGACY_SUBJECT_CODES[v]) ? subjectChoices[0] : v
    }
    setSubject(migrate)
    setInlineSubject(migrate)
  }, [subjectChoices])

  /* 键盘快捷键：左右箭头切换日期（日视图） */
  useEffect(() => {
    const handler = (e) => {
      if (view !== 'day') return
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setDate((d) => addDays(d, -1))
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        setDate((d) => addDays(d, 1))
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [view])

  /* 内联快加表单已随 E2E2-001 修复移除（原实现不可达），新建任务统一走 showAdd 弹窗 */

  /* ---- 后端在线状态与数据同步 ---- */
  const [backendOk, setBackendOk] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const refresh = useCallback(async () => {
    setSyncing(true)   /* 批次2-2：首屏拉取后端任务时显示「同步中…」 */
    try {
      /* 与启动时回填走同一个 loader：逐页取全量（后端 page_size 上限 200，写更大会
         422 而不是截断），HTTP 成功即算后端可用，空结果照空结果写，只有抛错才降级。 */
      await loadDomain('tasks')
      setBackendOk(true)
    } catch {
      setBackendOk(false)
    } finally {
      setSyncing(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  /* 后端写操作：成功后刷新，失败回退本地 */
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

  const today = todayStr()

  /* 当前视图下的全部任务（用于导出 / 排序） */
  const viewTasks = useMemo(() => {
    if (view === 'day') return tasks.filter((t) => t.due === date)
    if (view === 'week') {
      const start = addDays(date, -weekdayIdx(date))
      const arr = []
      for (let i = 0; i < 7; i++) arr.push(...tasks.filter((t) => t.due === addDays(start, i)))
      return arr
    }
    const d = parseDate(date)
    const mm = new Date(d.getFullYear(), d.getMonth() + calShift, 1)
    const days = monthMatrix(mm.getFullYear(), mm.getMonth() + 1).flat()
    return tasks.filter((t) => days.includes(t.due))
  }, [view, date, tasks, calShift])

  const sortedViewTasks = useMemo(() => {
    if (!sortAsc) return viewTasks
    return [...viewTasks].sort((a, b) => (a.due || '').localeCompare(b.due || ''))
  }, [viewTasks, sortAsc])

  const visibleTasks = useMemo(() => {
    if (view === 'day') return tasks.filter((t) => t.due === date)
    if (view === 'week') {
      const start = addDays(date, -weekdayIdx(date))
      const arr = []
      for (let i = 0; i < 7; i++) arr.push(addDays(start, i))
      return { start, days: arr.map((d) => ({ date: d, tasks: tasks.filter((t) => t.due === d) })) }
    }
    return null
  }, [view, date, tasks])

  const month = useMemo(() => {
    const d = parseDate(date)
    const y = d.getFullYear(), m = d.getMonth() + 1 + calShift
    const mm = new Date(y, m - 1, 1)
    return { year: mm.getFullYear(), month: mm.getMonth() + 1, cells: monthMatrix(mm.getFullYear(), mm.getMonth() + 1) }
  }, [date, calShift])

  const groups = useMemo(() => {
    if (view !== 'day') return null
    const base = sortAsc
      ? [...visibleTasks].sort((a, b) => (a.due || '').localeCompare(b.due || ''))
      : visibleTasks
    const g = {}
    for (const t of base || []) {
      const key = t.subject || 'other'
      if (!g[key]) g[key] = { tasks: [], done: 0 }
      g[key].tasks.push(t)
      if (t.done) g[key].done++
    }
    return g
  }, [view, visibleTasks, sortAsc])

  const doneAll = tasks.filter((t) => t.done).length

  /* 导出当前视图任务为 CSV（纯前端 Blob 下载） */
  const exportCsv = () => {
    const rows = sortedViewTasks.map((t) => ({
      title: t.title,
      subject: subjectName(t.subject),
      due: t.due || '',
      status: t.done ? '已完成' : '进行中'
    }))
    if (!rows.length) return toast('当前视图没有可导出的任务')
    const header = ['标题', '科目', '截止日', '状态']
    const lines = [header.map(csvCell).join(',')].concat(
      rows.map((r) => [r.title, r.subject, r.due, r.status].map(csvCell).join(','))
    )
    const csv = '﻿' + lines.join('\r\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tasks-${todayStr()}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast(`已导出 ${rows.length} 条任务到 tasks-${todayStr()}.csv`)
  }

  const submitAdd = () => {
    if (!title.trim()) {
      toastErr('请填写任务名称')
      focusAndScroll(addTitleRef.current)
      return
    }
    const payload = { title: title.trim(), subject: subject || null, due_date: date }
    withBackend(
      () => tasksApi.create(payload),
      () => { addTask({ title: title.trim(), subject: subject || null, due: date }); toastOk('任务已添加') }
    )
    setTitle('')
    setShowAdd(false)
  }

  const submitAi = async () => {
    setAiErr('')
    if (!backendOk) {
      /* 曾经这里会本地"生成"一套 数学/英语/政治/834专业课 的假任务并当成 AI 结果，
         假任务一旦被导入就成了学习记录。后端不可用就如实说，不编。 */
      setAiErr('AI 规划需要后端在线（当前后端不可用）。可在「设置 → AI 服务」检查配置后重试。')
      setGenTasks(null); setAiPlanText(null)
      return
    }
    try {
      const r = await tasksApi.aiGenerate({ topic: aiTitle.trim() })
      const list = Array.isArray(r?.tasks) ? r.tasks : (Array.isArray(r?.items) ? r.items : [])
      if (list.length) {
        // 后端下发结构化任务才走「一键导入」；科目原样透传，不再补成「专业课」。
        setGenTasks(list.map((t) => ({ title: t.title, subject: t.subject || '' })))
        setAiPlanText(null)
        return
      }
      if (r?.plan && typeof r.plan === 'string') {
        setAiPlanText(r.plan)
        setGenTasks(null)
        toast('AI 计划已生成，请查看下方预览')
        return
      }
      setAiErr('后端没有返回可用的计划内容。')
    } catch (e) {
      /* dogfood ISSUE-002：不再把 401/服务商地址等原始异常亮给用户 */
      setAiErr(friendlyAiError(e))
    }
  }

  const confirmImport = () => {
    if (backendOk) {
      const payload = { tasks: genTasks.map((t) => ({ title: t.title, subject: t.subject, due_date: today })) }
      withBackend(
        () => Promise.all(payload.tasks.map((t) => tasksApi.create(t))),
        () => {}
      )
      toast(`已导入 ${genTasks.length} 项任务`)
    } else {
      importTasks(genTasks)
      toast(`已导入 ${genTasks.length} 项任务`)
    }
    setGenTasks(null)
    setShowAi(false)
    setAiTitle('')
  }

  const onToggle = (id) => {
    const t = tasks.find((x) => x.id === id)
    if (!t) return
    withBackend(
      () => (t.done ? tasksApi.uncomplete(Number(id)) : tasksApi.complete(Number(id))),
      () => toggleTask(id)
    )
  }

  const onRemove = async (id) => {
    // e2e3 回归建议：删除此前无二次确认，误触即丢（2026-10-19 补）
    if (!(await confirm({ title: '删除任务', message: '删除后不可恢复，确定删除该任务吗？', danger: true }))) return
    withBackend(
      () => tasksApi.remove(Number(id)),
      () => { removeTask(id); toast('已删除') }
    )
  }

  const navDate = (delta) => setDate(addDays(date, delta))

  const statusBadge = (t) =>
    t.done
      ? <span className="badge success">已完成</span>
      : <span className="badge accent">进行中</span>

  return (
    <div className="container stack">
      <div className="page-head">
        <div>
          <h1 className="page-title">任务打卡</h1>
          <p className="page-sub">
            日 / 周 / 月视图管理复习计划 · 已完成 {doneAll}/{tasks.length}
            {backendOk ? <span className="live-dot"> · 后端已连接</span> : <span className="offline-dot"> · 本地模式</span>}
            {syncing && <span className="offline-dot"> · 同步中…</span>}
          </p>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={() => setShowAi(true)}><Brain size={15} /> AI 生成</button>
          <button className="btn primary" onClick={() => setShowAdd(true)}><Plus size={15} /> 新建任务</button>
        </div>
      </div>

      {!backendOk && (
        <div className="banner">
          <strong>本地模式：数据未同步。</strong>
          当前任务仅保存在本机浏览器（localStorage），尚未同步到服务器；后端恢复连接后请刷新以拉取服务器数据。
        </div>
      )}

      <div className="toolbar">
        <div className="left">
          <Segmented options={[{ label: '日视图', value: 'day' }, { label: '周视图', value: 'week' }, { label: '月视图', value: 'month' }]} value={view} onChange={setView} />
        </div>
        <div className="right">
          <button className={`btn sm ${sortAsc ? 'active' : 'ghost'}`} onClick={() => setSortAsc((v) => !v)}
            title="按截止日升序排列">
            截止日{sortAsc ? ' ↑' : ''}
          </button>
          <button className="btn outline sm" onClick={exportCsv}>导出</button>
        </div>
      </div>

      {view === 'day' && (
        <div className="date-nav">
          <button className="btn sm ghost date-nav-arrow" onClick={() => navDate(-1)} aria-label="前一天">
            <ChevronLeft size={16} />
          </button>
          <button className="btn sm ghost" onClick={() => setDate(today)}>今天</button>
          <button className="btn sm ghost date-nav-arrow" onClick={() => navDate(1)} aria-label="后一天">
            <ChevronRight size={16} />
          </button>
          <span className="date-nav-label">
            {fmtDateCN(date)} {date === today && <em>今日</em>}
          </span>
        </div>
      )}
      {view === 'month' && (
        <div className="date-nav">
          <button className="btn sm ghost date-nav-arrow" onClick={() => setCalShift((v) => v - 1)} aria-label="上月">
            <ChevronLeft size={16} />
          </button>
          <span className="date-nav-label">{month.year} 年 {month.month} 月</span>
          <button className="btn sm ghost date-nav-arrow" onClick={() => setCalShift((v) => v + 1)} aria-label="下月">
            <ChevronRight size={16} />
          </button>
          <button className="btn sm ghost" onClick={() => { setCalShift(0); setDate(today) }}>本月</button>
        </div>
      )}

      {view === 'day' && (
        groups && Object.keys(groups).length === 0 ? (
          <div className="card">
            <Empty icon={<Target size={22} />} title="这一天没有任务" desc="点击右上角「新建任务」或「AI 生成」安排复习" />
          </div>
        ) : (
          <div className="stack">
            {groups && Object.keys(groups).map((k) => {
              const g = groups[k]
              const pct = g.tasks.length ? Math.round((g.done / g.tasks.length) * 100) : 0
              return (
                <div key={k} className="card">
                  <div className="card-head">
                    <div className="row" style={{ gap: 'var(--space-3)' }}>
                      <SubTag subject={k} />
                      <span className="card-sub">{g.done}/{g.tasks.length} 完成</span>
                    </div>
                    <div className="progress thin" style={{ width: 140 }}>
                      <i style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                  <div className="list">
                    {g.tasks.map((t) => (
                      <div key={t.id} className="list-row">
                        <span className="lr-ico" style={{ background: 'transparent' }}>
                          <i style={{ width: 12, height: 12, borderRadius: '50%', display: 'block', background: t.done ? 'var(--success)' : 'var(--accent)' }} />
                        </span>
                        <div className="lr-main">
                          <div className="lr-title" style={t.done ? { textDecoration: 'line-through', color: 'var(--muted)' } : undefined}>{t.title}</div>
                          <div className="lr-meta">
                            {fmtDateCN(t.due)}
                            {t.ai && <span className="badge accent" style={{ marginLeft: 'var(--space-2)' }}><Brain size={12} /> AI 规划</span>}
                            {statusBadge(t)}
                          </div>
                        </div>
                        <div className="lr-actions">
                          <button className={`btn sm ${t.done ? 'ghost' : 'tint'}`} onClick={() => onToggle(t.id)}>{t.done ? '撤销' : '完成'}</button>
                          <button className="btn sm ghost" onClick={() => onRemove(t.id)}>删除</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )
      )}

      {view === 'week' && visibleTasks && (
        <div className="week-agenda">
          {visibleTasks.days.map((d, i) => (
            <div key={d.date} className={`week-day-row ${d.date === today ? 'is-today' : ''}`}>
              <div className="week-day-label">
                <span className="wd-name">周{'一二三四五六日'[i]}</span>
                <span className="wd-date">{parseDate(d.date).getDate()}</span>
                {d.date === today && <span className="wd-today">今天</span>}
              </div>
              <div className="week-day-body">
                {d.tasks.length === 0 ? (
                  <span className="week-day-empty">无任务</span>
                ) : (
                  d.tasks.map((t) => (
                    <button key={t.id} type="button" className="week-task"
                      onClick={() => { setView('day'); setDate(d.date) }}>
                      <i className={`wt-dot ${t.done ? 'done' : ''}`} />
                      <span className={`wt-title ${t.done ? 'done' : ''}`}>{t.title}</span>
                      <span className="wt-subject">{subjectName(t.subject)}</span>
                    </button>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {view === 'month' && (
        <div className="card flush">
          <div className="cal-grid">
            {['一', '二', '三', '四', '五', '六', '日'].map((w) => <div key={w} className="cal-head">周{w}</div>)}
            {month.cells.flat().map((d) => {
              const dayTasks = tasks.filter((t) => t.due === d)
              const done = dayTasks.filter((t) => t.done).length
              const other = d.slice(0, 7) !== `${month.year}-${String(month.month).padStart(2, '0')}`
              return (
                <div key={d} className={`cal-cell ${d === today ? 'today' : ''} ${other ? 'other' : ''}`} onClick={() => { setView('day'); setDate(d) }}>
                  <div className="d">{parseDate(d).getDate()}</div>
                  <div className="cbar">
                    {dayTasks.slice(0, 3).map((t) => <i key={t.id} style={{ background: t.done ? 'var(--success)' : 'var(--accent)', opacity: 0.8 }} />)}
                  </div>
                  {dayTasks.length > 0 && <span className="cpct">{done}/{dayTasks.length}</span>}
                </div>
              )
            })}
          </div>
        </div>
      )}

      <Modal open={showAdd} title="新建任务" onClose={() => setShowAdd(false)}
        footer={<React.Fragment><button className="btn ghost" onClick={() => setShowAdd(false)}>取消</button><button className="btn primary" onClick={submitAdd}>保存</button></React.Fragment>}>
        <label>任务名称
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="如：英语真题 2018 Text4 精读" autoFocus ref={addTitleRef} />
        </label>
        <label>科目
          <select className="input" aria-label="新建任务科目" value={subject} onChange={(e) => setSubject(e.target.value)}>
            <option value="">未分类</option>
            {subjectChoices.map((s) => <option key={s} value={s}>{subjectName(s)}</option>)}
          </select>
          {!subjectsReady && (
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>
              科目配置未加载（后端不可用），可先留「未分类」，稍后在任务里补科目。
            </div>
          )}
        </label>
        <label>日期
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
      </Modal>

      <Modal open={showAi} title="AI 生成任务" onClose={() => { setShowAi(false); setAiPlanText(null); setAiErr(''); }}
        footer={(genTasks || aiPlanText) ? <React.Fragment><button className="btn ghost" onClick={() => { setGenTasks(null); setAiPlanText(null); setAiErr(''); }}>重新生成</button>{genTasks && <button className="btn primary" onClick={confirmImport}>确认导入</button>}</React.Fragment> : null}>
        {!genTasks && !aiPlanText && (
          <React.Fragment>
            <label>主题（可选，留空则按目标院校与待办数生成全科复习计划）
              <input className="input" value={aiTitle} onChange={(e) => setAiTitle(e.target.value)} placeholder="如：线性代数特征值强化" />
            </label>
            <button className="btn primary" onClick={submitAi}>生成复习计划</button>
            {aiErr && (
              <div className="inline-error" role="alert">
                <AlertCircle size={14} /><span>{aiErr}</span>
              </div>
            )}
          </React.Fragment>
        )}
        {aiPlanText && (
          <div>
            <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--space-2)', color: 'var(--fg-2)' }}>AI 生成的学习计划（文本）</div>
            <pre style={{ background: 'var(--surface-2)', padding: 'var(--space-3)', borderRadius: 8, fontSize: 'var(--text-sm)', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 300, overflowY: 'auto' }}>{aiPlanText}</pre>
            <div style={{ marginTop: 'var(--space-3)', display: 'flex', gap: 'var(--space-2)' }}>
              <button className="btn ghost" onClick={() => navigator.clipboard.writeText(aiPlanText).then(() => toast('已复制到剪贴板'))}>复制全文</button>
              <button className="btn ghost" onClick={() => { setAiPlanText(null); }}>重新生成</button>
            </div>
            <div style={{ marginTop: 'var(--space-2)', fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>提示：你可以复制计划内容，手动添加到任务列表中。后续版本将支持自动解析文本为任务。</div>
          </div>
        )}
        {genTasks && (
          <div className="list">
            {genTasks.map((g, i) => (
              <div key={i} className="list-row">
                <span className="lr-ico" style={{ background: 'var(--info-soft)', color: 'var(--chart-5)' }}><Brain size={16} /></span>
                <div className="lr-main">
                  <div className="lr-title">{g.title}</div>
                  <div className="lr-meta"><SubTag subject={g.subject} /><span>后端 AI 生成，导入前请核对科目与题量</span></div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>
      {dialog}
    </div>
  )
}
