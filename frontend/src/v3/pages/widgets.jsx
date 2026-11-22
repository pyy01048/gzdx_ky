import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { studyApi } from '../../api/client'
import { ukey } from '../../utils/userKeys'
import { Button, Chip, IconButton, Input, Progress, Select, toast } from '../ui'
import { Check, Pause, Play, Plus, Timer, X } from '../icons'

const PRESETS = [15, 25, 45]
const KEY = 'v3_focus_v1'
/* W5-4：自定义时长 —— 档位不再锁死 15/25/45。
   MIN/MAX 与后端 study_sessions 的合理区间一致（1 分钟起、单轮 10 小时封顶）。 */
const MIN_MIN = 1
const MAX_MIN = 600
const MINUTES_KEY = 'v3_focus_minutes_v1'
const PRESET_KEY = 'v3_focus_presets_v1'

function readState() {
  try {
    const raw = JSON.parse(localStorage.getItem(ukey(KEY)) || 'null')
    return raw && typeof raw === 'object' ? raw : null
  } catch {
    return null
  }
}

function readNumber(key, fallback) {
  try {
    const n = Number(localStorage.getItem(ukey(key)))
    return Number.isFinite(n) && n >= MIN_MIN && n <= MAX_MIN ? n : fallback
  } catch {
    return fallback
  }
}

function readPresets() {
  try {
    const raw = JSON.parse(localStorage.getItem(ukey(PRESET_KEY)) || '[]')
    if (!Array.isArray(raw)) return []
    return raw
      .map((n) => Number(n))
      .filter((n) => Number.isInteger(n) && n >= MIN_MIN && n <= MAX_MIN && !PRESETS.includes(n))
      .slice(0, 6)
  } catch {
    return []
  }
}

/* 专注计时：只在用户点「记录」时写 study_sessions，写的是真实经过的分钟数。 */
export function FocusTile({ todayMinutes = 0, targetMinutes = null, subjects = [], onRecorded }) {
  const [session, setSession] = useState(readState)
  const [minutes, setMinutes] = useState(() => readState()?.minutes || readNumber(MINUTES_KEY, 25))
  const [draft, setDraft] = useState(() => String(readState()?.minutes || readNumber(MINUTES_KEY, 25)))
  const [customPresets, setCustomPresets] = useState(readPresets)
  const [subject, setSubject] = useState(() => readState()?.subject || '')
  const [now, setNow] = useState(Date.now())
  const [busy, setBusy] = useState(false)
  const running = session?.runningSince != null

  useEffect(() => {
    try {
      if (session) localStorage.setItem(ukey(KEY), JSON.stringify(session))
      else localStorage.removeItem(ukey(KEY))
    } catch { /* ignore */ }
  }, [session])

  useEffect(() => {
    if (!running) return undefined
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [running])

  const elapsedMs = useMemo(() => {
    if (!session) return 0
    return (session.accumMs || 0) + (session.runningSince ? now - session.runningSince : 0)
  }, [session, now])

  const totalMs = (session?.minutes || minutes) * 60000
  const remaining = Math.max(0, totalMs - elapsedMs)
  const reached = session && remaining <= 0
  const mm = String(Math.floor(remaining / 60000)).padStart(2, '0')
  const ss = String(Math.floor((remaining % 60000) / 1000)).padStart(2, '0')
  const pct = targetMinutes ? Math.min(100, Math.round((todayMinutes / targetMinutes) * 100)) : null

  const start = () => {
    const ts = Date.now()
    setNow(ts)
    setSession({ minutes, subject, runningSince: ts, accumMs: 0, startedAt: ts })
  }
  const pause = () => setSession((s) => (s ? { ...s, accumMs: elapsedMs, runningSince: null } : s))
  const resume = () => {
    setNow(Date.now())
    setSession((s) => (s ? { ...s, runningSince: Date.now() } : s))
  }
  const discard = () => {
    setSession(null)
    toast('已放弃本次计时，没有写入记录')
  }
  const pickSubject = (value) => {
    setSubject(value)
    // 计时途中改科目也要落在本轮会话上，刷新后不会退回旧科目
    setSession((s) => (s ? { ...s, subject: value } : s))
  }

  const commit = useCallback(async () => {
    const mins = session ? Math.min(session.minutes, Math.floor(elapsedMs / 60000)) : 0
    if (mins < 1) {
      toast('不足 1 分钟，没有写入记录')
      setSession(null)
      return
    }
    setBusy(true)
    try {
      const res = await studyApi.addSession({
        duration: mins,
        subject: session.subject || null,
        task_type: 'pomodoro',
        remark: `专注计时 ${session.minutes} 分钟档`,
      })
      setSession(null)
      toast(`已记录 ${res?.duration ?? mins} 分钟`)
      onRecorded?.()
    } catch (e) {
      toast(String(e?.message || '记录失败，计时器已保留，可稍后再试'))
    } finally {
      setBusy(false)
    }
  }, [session, elapsedMs, onRecorded])

  const subjectOptions = useMemo(() => {
    const names = subjects.filter(Boolean)
    // 恢复的计时可能带着一个已从目标里移除的科目：保留它，别让下拉显示空白
    if (subject && !names.includes(subject)) names.push(subject)
    return [{ value: '', label: '不限科目' }, ...names.map((s) => ({ value: s, label: s }))]
  }, [subjects, subject])

  /* 空闲时把选中的时长落盘，刷新后不丢；计时进行中不许改档（口径不能中途换） */
  useEffect(() => {
    if (session) return
    try { localStorage.setItem(ukey(MINUTES_KEY), String(minutes)) } catch { /* ignore */ }
  }, [minutes, session])

  useEffect(() => {
    try { localStorage.setItem(ukey(PRESET_KEY), JSON.stringify(customPresets)) } catch { /* ignore */ }
  }, [customPresets])

  const parsedDraft = Math.floor(Number(draft))
  const draftValid = Number.isFinite(parsedDraft) && parsedDraft >= MIN_MIN && parsedDraft <= MAX_MIN

  const applyCustom = () => {
    if (!draftValid) {
      toast(`时长请填 ${MIN_MIN}–${MAX_MIN} 之间的整数分钟`)
      return
    }
    setMinutes(parsedDraft)
    toast(`本轮时长 ${parsedDraft} 分钟`)
  }

  const savePreset = () => {
    if (!draftValid) {
      toast(`时长请填 ${MIN_MIN}–${MAX_MIN} 之间的整数分钟`)
      return
    }
    setMinutes(parsedDraft)
    setCustomPresets((prev) => {
      if (prev.includes(parsedDraft) || PRESETS.includes(parsedDraft)) return prev
      return [...prev, parsedDraft].sort((a, b) => a - b).slice(-6)
    })
    toast(`已存为常用预设：${parsedDraft} 分钟`)
  }

  const chipMinutes = [...PRESETS, ...customPresets.filter((p) => !PRESETS.includes(p))]

  return (
    <div className="v3-focus">
      <div className="v3-focus__dial" data-running={running} data-reached={!!reached}>
        <span className="v3-focus__time">{mm}:{ss}</span>
        <span className="v3-caption">{session ? `本轮 ${session.minutes} 分钟` : '准备好就开始'}</span>
      </div>
      <div className="v3-focus__meta">
        <div className="v3-row" style={{ justifyContent: 'space-between' }}>
          <span className="v3-caption">今日专注</span>
          <strong style={{ fontSize: 16 }}>{todayMinutes} 分钟</strong>
        </div>
        {pct != null ? <Progress value={pct} /> : null}
        <span className="v3-caption">
          {pct == null ? '未设置每日时长目标' : `目标 ${targetMinutes} 分钟 · ${pct}%`}
        </span>
      </div>
      {!session ? (
        <div className="v3-focus__plan">
          <div className="v3-row" style={{ gap: 8, flexWrap: 'wrap' }}>
            {chipMinutes.map((p) => (
              <Chip
                key={p}
                active={minutes === p}
                onClick={() => { setMinutes(p); setDraft(String(p)) }}
              >
                {p} 分钟
              </Chip>
            ))}
          </div>
          {/* W5-4：任意分钟数都能计时，15/25/45 只是快捷档 */}
          <div className="v3-focus__custom">
            <Input
              type="number"
              inputMode="numeric"
              min={MIN_MIN}
              max={MAX_MIN}
              step={1}
              aria-label="自定义时长（分钟）"
              className="v3-focus__minutes"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); applyCustom() } }}
            />
            <span className="v3-caption">分钟</span>
            <Button variant="tonal" size="sm" onClick={applyCustom}>用这个时长</Button>
            <Button variant="text" size="sm" icon={<Plus size={14} />} onClick={savePreset}>存为预设</Button>
          </div>
        </div>
      ) : null}
      <Select value={subject} onChange={(e) => pickSubject(e.target.value)} options={subjectOptions} aria-label="专注科目" />
      {!subjects.length ? (
        <span className="v3-caption v3-focus__subject-hint">
          科目候选来自「设置 · 目标院校」的初试专业课与公共课，目前还没有配置，先去设置。
        </span>
      ) : null}
      {!session ? (
        <Button variant="filled" data-cta="primary" block icon={<Play size={16} />} onClick={start}>开始专注</Button>
      ) : (
        <div className="v3-row" style={{ gap: 8 }}>
          {running ? (
            <Button variant="tonal" block icon={<Pause size={16} />} onClick={pause}>暂停</Button>
          ) : (
            <Button variant="tonal" block icon={<Play size={16} />} onClick={resume}>继续</Button>
          )}
          <Button variant="filled" block icon={<Check size={16} />} loading={busy} onClick={commit} disabled={!reached && elapsedMs < 60000}>
            记录 {Math.min(session.minutes, Math.floor(elapsedMs / 60000))} 分钟
          </Button>
          <IconButton label="放弃" variant="ghost" icon={<X size={16} />} onClick={discard} />
        </div>
      )}
    </div>
  )
}

/* 轻量倒计时数字，用于 Hero */
export function useTicker(ms = 1000) {
  const [, setTick] = useState(0)
  const ref = useRef(null)
  useEffect(() => {
    ref.current = setInterval(() => setTick((t) => t + 1), ms)
    return () => clearInterval(ref.current)
  }, [ms])
}

export { Timer }
