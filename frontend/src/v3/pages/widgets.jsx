import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { studyApi } from '../../api/client'
import { ukey } from '../../utils/userKeys'
import { Button, Chip, IconButton, Progress, Select, toast } from '../ui'
import { Check, Pause, Play, Timer, X } from '../icons'

const PRESETS = [15, 25, 45]
const KEY = 'v3_focus_v1'

function readState() {
  try {
    const raw = JSON.parse(localStorage.getItem(ukey(KEY)) || 'null')
    return raw && typeof raw === 'object' ? raw : null
  } catch {
    return null
  }
}

/* 专注计时：只在用户点「记录」时写 study_sessions，写的是真实经过的分钟数。 */
export function FocusTile({ todayMinutes = 0, targetMinutes = null, subjects = [], onRecorded }) {
  const [session, setSession] = useState(readState)
  const [minutes, setMinutes] = useState(() => readState()?.minutes || 25)
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

  return (
    <div className="v3-focus">
      <div className="v3-focus__dial" data-running={running} data-reached={!!reached}>
        <span className="v3-focus__time">{mm}:{ss}</span>
        <span className="v3-caption">{session ? `本轮 ${session.minutes} 分钟` : '准备好就开始'}</span>
      </div>
      <div className="v3-focus__meta">
        <div className="v3-row" style={{ justifyContent: 'space-between' }}>
          <span className="v3-caption">今日专注</span>
          <strong style={{ fontSize: 15 }}>{todayMinutes} 分钟</strong>
        </div>
        {pct != null ? <Progress value={pct} gradient /> : null}
        <span className="v3-caption">
          {pct == null ? '未设置每日时长目标' : `目标 ${targetMinutes} 分钟 · ${pct}%`}
        </span>
      </div>
      {!session ? (
        <div className="v3-row" style={{ gap: 8 }}>
          {PRESETS.map((p) => (
            <Chip key={p} active={minutes === p} onClick={() => setMinutes(p)}>{p} 分钟</Chip>
          ))}
        </div>
      ) : null}
      <Select value={subject} onChange={(e) => pickSubject(e.target.value)} options={subjectOptions} aria-label="专注科目" />
      {!session ? (
        <Button variant="gradient" block icon={<Play size={16} />} onClick={start}>开始专注</Button>
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
