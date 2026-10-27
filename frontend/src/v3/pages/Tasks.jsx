import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import useStore from '../../store/useStore'
import { todayStr, addDays, monthMatrix, weekdayIdx, fmtDateCN, parseDate } from '../../utils/date'
import { tasksApi } from '../../api/client'
import { subjectTone } from '../../api/hub'
import { loadDomain } from '../../api/sync'
import { useSubjectConfig } from '../../hooks/useSubjectConfig'
import { friendlyAiError } from '../../utils/aiError'
import { Alert, Badge, Button, Dialog, Empty, Field, IconButton, Input, Progress, Segmented, Select, Textarea, cx, toast, toastOk, toastErr, useConfirm } from '../ui'
import { Brain, Check, ChevronLeft, ChevronRight, Download, Plus, Sparkles, Target, Trash } from '../icons'
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

export default function Tasks() {
  const tasks = useStore((s) => s.tasks)
  const addTask = useStore((s) => s.addTask)
  const toggleTask = useStore((s) => s.toggleTask)
  const removeTask = useStore((s) => s.removeTask)
  const importTasks = useStore((s) => s.importTasks)

  const [view, setView] = useState('day')
  const [date, setDate] = useState(todayStr())
  const [showAdd, setShowAdd] = useState(false)
  const [showAi, setShowAi] = useState(false)
  const [confirm, dialog] = useConfirm()
  const [title, setTitle] = useState('')
  const [subject, setSubject] = useState('')
  const [aiTitle, setAiTitle] = useState('')
  const [genTasks, setGenTasks] = useState(null)
  const [aiPlanText, setAiPlanText] = useState(null)
  const [aiErr, setAiErr] = useState('')
  const [aiBusy, setAiBusy] = useState(false)
  const [calShift, setCalShift] = useState(0)
  const [sortAsc, setSortAsc] = useState(false)
  const addTitleRef = useRef(null)

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

  useEffect(() => {
    if (!subjectChoices.length) return
    setSubject((cur) => {
      if (subjectChoices.includes(cur)) return cur
      return !cur || LEGACY_SUBJECT_CODES[cur] ? subjectChoices[0] : cur
    })
  }, [subjectChoices])

  useEffect(() => {
    const handler = (e) => {
      if (view !== 'day') return
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return
      if (e.key === 'ArrowLeft') { e.preventDefault(); setDate((d) => addDays(d, -1)) }
      else if (e.key === 'ArrowRight') { e.preventDefault(); setDate((d) => addDays(d, 1)) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [view])

  const [backendOk, setBackendOk] = useState(false)
  const [syncing, setSyncing] = useState(false)

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
  const doneAll = tasks.filter((t) => t.done).length
  /* 口径注释：tasks.length/doneAll 是**全部累积任务**；todayDue 才是「今日到期」。
     三口径含义对齐 /hub 的口径面板：Tasks 页只暴露「今日到期 + 全部累计」两个，
     「现在可做 / 艾宾浩斯」队列属于 Hub 与复习模块，不在这里混算。 */
  const todayDue = tasks.filter((t) => t.due === today).length

  const dayTasks = useMemo(
    () => [...tasks.filter((t) => t.due === date)].sort((a, b) => (sortAsc ? (a.due || '').localeCompare(b.due || '') : 0)),
    [tasks, date, sortAsc],
  )

  const groups = useMemo(() => {
    const g = {}
    for (const t of dayTasks) {
      const key = t.subject || 'other'
      if (!g[key]) g[key] = { tasks: [], done: 0 }
      g[key].tasks.push(t)
      if (t.done) g[key].done++
    }
    return g
  }, [dayTasks])

  const week = useMemo(() => {
    const start = addDays(date, -weekdayIdx(date))
    return Array.from({ length: 7 }, (_, i) => {
      const d = addDays(start, i)
      return { date: d, tasks: tasks.filter((t) => t.due === d) }
    })
  }, [date, tasks])

  const month = useMemo(() => {
    const d = parseDate(date)
    const mm = new Date(d.getFullYear(), d.getMonth() + calShift, 1)
    return { year: mm.getFullYear(), month: mm.getMonth() + 1, cells: monthMatrix(mm.getFullYear(), mm.getMonth() + 1) }
  }, [date, calShift])

  const viewTasks = useMemo(() => {
    if (view === 'day') return dayTasks
    if (view === 'week') return week.flatMap((d) => d.tasks)
    const days = new Set(month.cells.flat())
    return tasks.filter((t) => days.has(t.due))
  }, [view, dayTasks, week, month, tasks])

  const exportCsv = () => {
    const rows = viewTasks.map((t) => ({
      title: t.title, subject: subjectName(t.subject), due: t.due || '', status: t.done ? '已完成' : '进行中',
    }))
    if (!rows.length) { toast('当前视图没有可导出的任务'); return }
    const lines = [['标题', '科目', '截止日', '状态'].map(csvCell).join(',')]
      .concat(rows.map((r) => [r.title, r.subject, r.due, r.status].map(csvCell).join(',')))
    const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tasks-${todayStr()}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast(`已导出 ${rows.length} 条任务`)
  }

  const submitAdd = () => {
    if (!title.trim()) { toastErr('请填写任务名称'); addTitleRef.current?.focus(); return }
    const payload = { title: title.trim(), subject: subject || null, due_date: date }
    withBackend(
      () => tasksApi.create(payload),
      () => { addTask({ title: title.trim(), subject: subject || null, due: date }); toastOk('任务已添加') },
    )
    setTitle('')
    setShowAdd(false)
  }

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

  /* ---- P2 乐观打卡（修正版）---------------------------------------------
     store.toggleTask/removeTask 已是完整乐观实现：本地立即生效 + 后端异步持久化
     + 失败入 failedQueue 自动重试（见 store/useStore.js::syncTask）。
     页面层上一版又手工打了一遍同一接口并整域 refresh —— 双重请求 + 白等，
     这才是「打卡慢」的根因。现在页面只负责确认交互与失败提示。 */
  const onToggle = (id) => {
    if (!tasks.some((x) => x.id === id)) return
    toggleTask(id)
  }

  const onRemove = async (id) => {
    if (!(await confirm({ title: '删除任务', message: '删除后不可恢复，确定删除该任务吗？', danger: true }))) return
    removeTask(id)
    toast('已删除')
  }

  /* 同步失败的可感知反馈：store 抛出的 sync-error 事件带操作名（任务打卡/删除…），
     这里只接管与任务相关的失败；其余域（笔记/卡片等）由各自页面或全局监听处理。 */
  useEffect(() => {
    const onSyncError = (e) => {
      const op = String(e?.detail?.operationName || '')
      if (op.startsWith('任务')) toastErr(`${op}未同步，已加入失败队列，网络恢复后自动重试`)
    }
    window.addEventListener('sync-error', onSyncError)
    return () => window.removeEventListener('sync-error', onSyncError)
  }, [])

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
          <b>本地模式：数据未同步。</b> 当前任务只保存在本机浏览器，后端恢复后刷新即可拉取服务器数据。
        </Alert>
      )}

      <div className="v3-toolbar">
        <div className="v3-row" style={{ gap: 10 }}>
          <Segmented options={VIEWS} value={view} onChange={setView} ariaLabel="任务视图" />
          {view === 'day' && (
            <div className="v3-row" style={{ gap: 4 }}>
              <IconButton label="前一天" icon={<ChevronLeft size={16} />} onClick={() => setDate(addDays(date, -1))} />
              <Button size="sm" variant="text" onClick={() => setDate(today)}>今天</Button>
              <IconButton label="后一天" icon={<ChevronRight size={16} />} onClick={() => setDate(addDays(date, 1))} />
              <span className="v3-task-date">{fmtDateCN(date)} {date === today ? <Badge tone="primary">今日</Badge> : null}</span>
            </div>
          )}
          {view === 'month' && (
            <div className="v3-row" style={{ gap: 4 }}>
              <IconButton label="上月" icon={<ChevronLeft size={16} />} onClick={() => setCalShift((v) => v - 1)} />
              <span className="v3-task-date">{month.year} 年 {month.month} 月</span>
              <IconButton label="下月" icon={<ChevronRight size={16} />} onClick={() => setCalShift((v) => v + 1)} />
              <Button size="sm" variant="text" onClick={() => { setCalShift(0); setDate(today) }}>本月</Button>
            </div>
          )}
        </div>
        <div className="v3-row" style={{ gap: 8 }}>
          <Button size="sm" variant={sortAsc ? 'tonal' : 'text'} onClick={() => setSortAsc((v) => !v)}>截止日{sortAsc ? ' ↑' : ''}</Button>
          <Button size="sm" variant="text" icon={<Download size={15} />} onClick={exportCsv}>导出</Button>
        </div>
      </div>

      {view === 'day' && (
        Object.keys(groups).length === 0 ? (
          <div className="v3-card" style={{ padding: 40 }}>
            <Empty icon={<Target size={26} />} title="这一天没有任务" text="点击「新建任务」或「AI 生成」安排复习。" action={<Button variant="tonal" size="sm" onClick={() => setShowAdd(true)}>新建任务</Button>} />
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
                    {g.tasks.map((t) => (
                      <div key={t.id} className={cx('v3-task-row', t.done && 'is-done')}>
                        <button type="button" className="v3-task-row__check" onClick={() => onToggle(t.id)} aria-label={t.done ? '撤销完成' : '标记完成'}>
                          {t.done ? <Check size={14} /> : null}
                        </button>
                        <div className="v3-task-row__main">
                          <span className="v3-task-row__title">{t.title}</span>
                          <span className="v3-caption">
                            {fmtDateCN(t.due)}
                            {t.ai ? ' · AI 规划' : ''}
                          </span>
                        </div>
                        <Badge tone={t.done ? 'success' : 'primary'}>{t.done ? '已完成' : '进行中'}</Badge>
                        <Button size="sm" variant={t.done ? 'text' : 'tonal'} onClick={() => onToggle(t.id)}>{t.done ? '撤销' : '完成'}</Button>
                        <IconButton label="删除" size="sm" variant="ghost" icon={<Trash size={15} />} onClick={() => onRemove(t.id)} />
                      </div>
                    ))}
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
            return (
              <div key={d.date} className={cx('v3-week__col', d.date === today && 'is-today')}>
                <div className="v3-week__head">
                  <span>周{'一二三四五六日'[i]}</span>
                  <b>{parseDate(d.date).getDate()}</b>
                  {d.date === today ? <em>今天</em> : null}
                </div>
                <div className="v3-week__bar"><Progress value={pct} height={4} gradient /></div>
                <div className="v3-week__body">
                  {d.tasks.length === 0 ? <span className="v3-caption">无任务</span> : d.tasks.map((t) => (
                    <button key={t.id} type="button" className={cx('v3-week__task', t.done && 'is-done')} onClick={() => { setView('day'); setDate(d.date) }}>
                      <i />
                      <span>{t.title}</span>
                    </button>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {view === 'month' && (
        <div className="v3-card v3-cal">
          {['一', '二', '三', '四', '五', '六', '日'].map((w) => <div key={w} className="v3-cal__head">周{w}</div>)}
          {month.cells.flat().map((d) => {
            const list = tasks.filter((t) => t.due === d)
            const done = list.filter((t) => t.done).length
            const other = d.slice(0, 7) !== `${month.year}-${String(month.month).padStart(2, '0')}`
            return (
              <button
                key={d}
                type="button"
                className={cx('v3-cal__cell', d === today && 'is-today', other && 'is-other')}
                onClick={() => { setView('day'); setDate(d) }}
              >
                <span className="v3-cal__day">{parseDate(d).getDate()}</span>
                <span className="v3-cal__dots">
                  {list.slice(0, 3).map((t) => <i key={t.id} className={t.done ? 'done' : ''} />)}
                </span>
                {list.length ? <span className="v3-cal__pct">{done}/{list.length}</span> : null}
              </button>
            )
          })}
        </div>
      )}

      <Dialog open={showAdd} title="新建任务" onClose={() => setShowAdd(false)} footer={(
        <>
          <Button variant="text" onClick={() => setShowAdd(false)}>取消</Button>
          <Button variant="gradient" onClick={submitAdd}>保存</Button>
        </>
      )}>
        <div className="v3-stack" style={{ gap: 14 }}>
          <Field label="任务名称" hint="例如：英语真题 2018 Text4 精读">
            <Input ref={addTitleRef} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="要完成什么？" autoFocus />
          </Field>
          <Field label="科目">
            <Select value={subject} onChange={(e) => setSubject(e.target.value)}>
              <option value="">未分类</option>
              {subjectChoices.map((s) => <option key={s} value={s}>{subjectName(s)}</option>)}
              {!subjectsReady ? <option value="" disabled>科目配置未加载（后端不可用）</option> : null}
            </Select>
          </Field>
          <Field label="日期">
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
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
