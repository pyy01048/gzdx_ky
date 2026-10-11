import React, { useMemo, useState, useCallback, useEffect } from 'react'
import useStore from '../store/useStore'
import { todayStr, addDays, monthMatrix, weekdayIdx, fmtDateCN, parseDate } from '../utils/date'
import { SubTag, Modal, Segmented, Empty, toast } from '../components/UI'
import { Target, Brain } from '../components/Icon'
import { tasksApi } from '../api/client'

const SUBJECTS = [
  { value: 'math', name: '数学' },
  { value: 'english', name: '英语' },
  { value: 'politics', name: '政治' },
  { value: 'major', name: '专业课' },
]
const subjectName = (v) => (SUBJECTS.find((s) => s.value === v) || { name: v || '其他' }).name

/* ---------- 本地启发式 AI 规划（后端 ai-generate 不可用时兜底） ---------- */
function aiPlan(title) {
  const base = [
    { title: '数学：真题演练 + 错题回顾', subject: 'math' },
    { title: '英语：真题精读 2 篇', subject: 'english' },
    { title: '政治：背诵 + 选择题 30 题', subject: 'politics' },
    { title: '834 专业课：章节梳理 + 题库', subject: 'major' }
  ]
  if (title) base.unshift({ title, subject: 'major' })
  return base
}

const csvCell = (v) => {
  const s = String(v ?? '')
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

export default function Tasks() {
  const { tasks, addTask, toggleTask, removeTask, importTasks, updateTask } = useStore()
  const settings = useStore((s) => s.settings)
  const [view, setView] = useState('day')
  const [date, setDate] = useState(todayStr())
  const [showAdd, setShowAdd] = useState(false)
  const [showInlineAdd, setShowInlineAdd] = useState(false)
  const [inlineTitle, setInlineTitle] = useState('')
  const [inlineSubject, setInlineSubject] = useState('major')
  const [showAi, setShowAi] = useState(false)
  const [title, setTitle] = useState('')
  const [subject, setSubject] = useState('major')
  const [aiTitle, setAiTitle] = useState('')
  const [genTasks, setGenTasks] = useState(null)
  const [aiPlanText, setAiPlanText] = useState(null)
  const [calShift, setCalShift] = useState(0)
  const [sortAsc, setSortAsc] = useState(false)

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

  /* 内联添加任务 */
  const handleInlineAdd = () => {
    if (!inlineTitle.trim()) return
    const newTask = { title: inlineTitle.trim(), subject: inlineSubject, due: date }
    withBackend(
      () => tasksApi.create(newTask),
      () => { addTask(newTask); toast('任务已添加') }
    )
    setInlineTitle('')
    setShowInlineAdd(false)
  }

  /* ---- 后端在线状态与数据同步 ---- */
  const [backendOk, setBackendOk] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const refresh = useCallback(async () => {
    setSyncing(true)   /* 批次2-2：首屏拉取后端任务时显示「同步中…」 */
    try {
      const data = await tasksApi.list({ page: 1, page_size: 200 })
      const list = data.items || data.tasks || data || []
      if (Array.isArray(list) && list.length !== undefined) {
        const mapped = list.map((t) => ({
          id: String(t.id),
          title: t.title,
          subject: t.subject || 'major',
          due: (t.due_date || t.due || todayStr()).slice(0, 10),
          done: t.status === 'done' || !!t.completed,
          ai: !!t.is_ai
        }))
        useStore.setState({ tasks: mapped })
        setBackendOk(true)
      }
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
    if (!title.trim()) return toast('请填写任务名称')
    const payload = { title: title.trim(), subject, due_date: date }
    withBackend(
      () => tasksApi.create(payload),
      () => { addTask({ title: title.trim(), subject, due: date }); toast('任务已添加') }
    )
    setTitle('')
    setShowAdd(false)
  }

  const submitAi = async () => {
    if (backendOk) {
      try {
        const r = await tasksApi.aiGenerate({ topic: aiTitle.trim(), count: 4 })
        const list = r.tasks || r.items || []
        if (Array.isArray(list) && list.length) {
          setGenTasks(list.map((t) => ({ title: t.title, subject: t.subject || 'major' })))
          setAiPlanText(null)
          return
        }
        if (r.plan && typeof r.plan === 'string') {
          setAiPlanText(r.plan)
          setGenTasks(null)
          toast('AI 计划已生成，请查看下方预览')
          return
        }
      } catch (e) {
        console.warn('AI生成失败，使用本地启发式:', e.message)
      }
    }
    setGenTasks(aiPlan(aiTitle.trim()))
    setAiPlanText(null)
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

  const onRemove = (id) => {
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
          <button className="btn ghost" onClick={() => setShowAi(true)}>AI 生成</button>
          <button className="btn primary" onClick={() => setShowInlineAdd(true)}>+ 新建任务</button>
        </div>
      </div>

      {!backendOk && (
        <div className="banner" style={{ background: '#fff8e1', border: '1px solid var(--gold, #f0b429)', color: '#7a5b00', padding: '10px 14px', borderRadius: 10, fontSize: 13, marginBottom: 12 }}>
          ⚠️ <strong>本地模式：数据未同步</strong>。当前任务仅保存在本机浏览器（localStorage），尚未同步到服务器；后端恢复连接后请重新刷新以拉取服务器数据。
        </div>
      )}

      <div className="toolbar">
        <div className="left">
          <Segmented options={[{ label: '日视图', value: 'day' }, { label: '周视图', value: 'week' }, { label: '月视图', value: 'month' }]} value={view} onChange={setView} />
        </div>
        <div className="right">
          <button className={`btn ghost sm ${sortAsc ? 'active' : ''}`} onClick={() => setSortAsc((v) => !v)}>
            {sortAsc ? '✓ 按截止日' : '按截止日排序'}
          </button>
          <button className="btn outline sm" onClick={exportCsv}>导出</button>
        </div>
      </div>

      {view === 'day' && (
        <div className="row wrap" style={{ gap: 8 }}>
          <button className="btn ghost sm" onClick={() => navDate(-1)}>‹ 前一天</button>
          <button className="btn ghost sm" onClick={() => setDate(today)}>今天</button>
          <button className="btn ghost sm" onClick={() => navDate(1)}>后一天 ›</button>
          <span className="badge neutral">{fmtDateCN(date)} {date === today && '· 今日'}</span>
        </div>
      )}
      {view === 'month' && (
        <div className="row wrap" style={{ gap: 8 }}>
          <button className="btn ghost sm" onClick={() => setCalShift((v) => v - 1)}>‹ 上月</button>
          <span className="badge neutral">{month.year} 年 {month.month} 月</span>
          <button className="btn ghost sm" onClick={() => setCalShift((v) => v + 1)}>下月 ›</button>
          <button className="btn ghost sm" onClick={() => { setCalShift(0); setDate(today) }}>本月</button>
        </div>
      )}

      {view === 'day' && (
        groups && Object.keys(groups).length === 0 ? (
          <Empty icon={<Target size={36} />} title="这一天没有任务" desc="点击右上角「新建任务」或「AI 生成」安排复习" />
        ) : (
          <div className="stack">
            {groups && Object.keys(groups).map((k) => {
              const g = groups[k]
              const pct = g.tasks.length ? Math.round((g.done / g.tasks.length) * 100) : 0
              return (
                <div key={k} className="card">
                  <div className="card-head">
                    <div className="row" style={{ gap: 10 }}>
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
                          <i style={{ width: 12, height: 12, borderRadius: '50%', display: 'block', background: t.done ? 'var(--green)' : 'var(--accent)' }} />
                        </span>
                        <div className="lr-main">
                          <div className="lr-title" style={t.done ? { textDecoration: 'line-through', color: 'var(--ink-3)' } : undefined}>{t.title}</div>
                          <div className="lr-meta">
                            {fmtDateCN(t.due)}
                            {t.ai && <span className="badge accent" style={{ marginLeft: 8 }}><Brain size={12} /> AI 规划</span>}
                            {statusBadge(t)}
                          </div>
                        </div>
                        <div className="lr-actions">
                          <button className="btn sm primary" onClick={() => onToggle(t.id)}>{t.done ? '撤销' : '完成'}</button>
                          <button className="btn sm ghost" onClick={() => onRemove(t.id)}>删除</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
            {showInlineAdd && (
              <div className="card">
                <div className="card-body row wrap">
                  <input
                    type="text"
                    className="input"
                    style={{ flex: 1, minWidth: 220 }}
                    placeholder="输入任务名称，回车添加..."
                    value={inlineTitle}
                    onChange={(e) => setInlineTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleInlineAdd()
                      if (e.key === 'Escape') { setShowInlineAdd(false); setInlineTitle('') }
                    }}
                    autoFocus
                  />
                  <select className="select" style={{ width: 130 }} value={inlineSubject} onChange={(e) => setInlineSubject(e.target.value)}>
                    <option value="major">专业课</option>
                    <option value="english">英语</option>
                    <option value="politics">政治</option>
                    <option value="math">数学</option>
                    <option value="other">其他</option>
                  </select>
                  <button className="btn primary" onClick={handleInlineAdd}>✓ 添加</button>
                  <button className="btn ghost" onClick={() => { setShowInlineAdd(false); setInlineTitle('') }}>✕</button>
                </div>
              </div>
            )}
          </div>
        )
      )}

      {view === 'week' && visibleTasks && (
        <div className="grid-4">
          {visibleTasks.days.map((d, i) => (
            <div key={d.date} className="card">
              <div className="card-head">
                <div className="row" style={{ gap: 8 }}>
                  <span className="ico sm blue">周{['一二三四五六日'][i]}</span>
                  <span className="card-title">{parseDate(d.date).getDate()}</span>
                </div>
                {d.date === today && <span className="badge accent">今日</span>}
              </div>
              <div className="list">
                {d.tasks.length === 0 && <div className="lr-meta" style={{ padding: '4px 2px' }}>无任务</div>}
                {d.tasks.map((t) => (
                  <div key={t.id} className="list-row">
                    <span className="lr-ico" style={{ background: 'transparent' }}>
                      <i style={{ width: 10, height: 10, borderRadius: '50%', display: 'block', background: t.done ? 'var(--green)' : 'var(--accent)' }} />
                    </span>
                    <div className="lr-main">
                      <div className="lr-title" style={t.done ? { textDecoration: 'line-through', color: 'var(--ink-3)' } : undefined}>{t.title}</div>
                      <div className="lr-meta">{subjectName(t.subject)}</div>
                    </div>
                    <div className="lr-actions">
                      <button className="btn sm ghost" onClick={() => { setView('day'); setDate(d.date) }}>查看</button>
                    </div>
                  </div>
                ))}
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
                    {dayTasks.slice(0, 3).map((t) => <i key={t.id} style={{ background: t.done ? 'var(--green)' : 'var(--accent)', opacity: 0.8 }} />)}
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
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="如：英语真题 2018 Text4 精读" autoFocus />
        </label>
        <label>科目
          <select className="input" value={subject} onChange={(e) => setSubject(e.target.value)}>
            {SUBJECTS.map((s) => <option key={s.value} value={s.value}>{s.name}</option>)}
          </select>
        </label>
        <label>日期
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
      </Modal>

      <Modal open={showAi} title="AI 生成任务" onClose={() => { setShowAi(false); setAiPlanText(null); }}
        footer={(genTasks || aiPlanText) ? <React.Fragment><button className="btn ghost" onClick={() => { setGenTasks(null); setAiPlanText(null); }}>重新生成</button>{genTasks && <button className="btn primary" onClick={confirmImport}>确认导入</button>}</React.Fragment> : null}>
        {!genTasks && !aiPlanText && (
          <React.Fragment>
            <label>主题（可选，留空则生成今日复习套餐）
              <input className="input" value={aiTitle} onChange={(e) => setAiTitle(e.target.value)} placeholder="如：线性代数特征值强化" />
            </label>
            <button className="btn primary" onClick={submitAi}>生成复习计划</button>
          </React.Fragment>
        )}
        {aiPlanText && (
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--ink-2)' }}>AI 生成的学习计划（文本）</div>
            <pre style={{ background: 'var(--surface-2)', padding: 12, borderRadius: 8, fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 300, overflowY: 'auto' }}>{aiPlanText}</pre>
            <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
              <button className="btn ghost" onClick={() => navigator.clipboard.writeText(aiPlanText).then(() => toast('已复制到剪贴板'))}>复制全文</button>
              <button className="btn ghost" onClick={() => { setAiPlanText(null); }}>重新生成</button>
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--ink-3)' }}>提示：你可以复制计划内容，手动添加到任务列表中。后续版本将支持自动解析文本为任务。</div>
          </div>
        )}
        {genTasks && (
          <div className="list">
            {genTasks.map((g, i) => (
              <div key={i} className="list-row">
                <span className="lr-ico" style={{ background: 'var(--violet-soft)', color: 'var(--violet)' }}><Brain size={16} /></span>
                <div className="lr-main">
                  <div className="lr-title">{g.title}</div>
                  <div className="lr-meta"><SubTag subject={g.subject} /><span>AI 依据学科薄弱点规划</span></div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  )
}
