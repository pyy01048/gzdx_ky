import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { request } from '../../api/client'
import {
  Alert, Badge, Button, Card, CardHead, Chip, Dialog, Empty, Field, IconButton, Input,
  PageHeader, Progress, Ring, Skeleton, toastErr, toastOk, toastWarn, cx,
} from '../ui'
import {
  Activity, AlertTriangle, CheckCircle2, Clock, Copy, Cpu, FileText, Gauge, HardDrive,
  RefreshCw, Rocket, RotateCcw, SlidersHorizontal, Sparkles, Timer, Wand, Zap,
} from '../icons'
import '../styles/admin-ops-v3.css'

/* ============================================================================
   模型训练管理 · Aurora v3
   LoRA 微调任务的启动、轮询监控、取消与文档识别入口。
   所有指标直接来自 /api/model-training/training/status，不做任何演示值兜底。
   ========================================================================== */

const trainingApi = {
  // 训练环境探测可能阻塞，start 放宽到 180s（后端最多探测 120s）
  status: () => request('/model-training/training/status', { timeout: 15000 }),
  start: (body) => request('/model-training/training/start', { method: 'POST', body, timeout: 180000 }),
  cancel: () => request('/model-training/training/cancel', { method: 'POST', timeout: 60000 }),
}

const DEFAULT_CONFIG = {
  base_model: '',
  data_dir: '',
  num_epochs: 3,
  batch_size: 1,
  learning_rate: 2e-4,
  lora_r: 16,
  lora_alpha: 32,
  use_gpu: true,
}

const STATUS_META = {
  idle: { label: '空闲', tone: 'outline', note: '等待新任务' },
  preparing: { label: '准备中', tone: 'warning', note: '正在准备训练环境' },
  training: { label: '训练中', tone: 'primary', note: '真实训练进程运行中' },
  merging: { label: '合并中', tone: 'warning', note: '正在合并 LoRA 权重' },
  completed: { label: '已完成', tone: 'success', note: '训练与合并已完成' },
  error: { label: '失败', tone: 'danger', note: '训练进程异常退出' },
  cancelled: { label: '已取消', tone: 'soft', note: '任务已被人为取消' },
}

const ACTIVE_STATES = new Set(['preparing', 'training', 'merging'])
const STAGES = [
  { key: 'preparing', label: '准备环境' },
  { key: 'training', label: '训练 LoRA' },
  { key: 'merging', label: '合并权重' },
]

const fmtNum = (v) => {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN') : '—'
}

const fmtEpoch = (cur, total) => {
  if (!total) return '—'
  return `${cur ?? 0} / ${total}`
}

const fmtClock = (date) => (
  date
    ? date.toLocaleTimeString('zh-CN', { hour12: false })
    : '—'
)

function validateConfig(cfg) {
  const errs = {}
  const intInRange = (v, min, max) => Number.isInteger(v) && v >= min && v <= max
  if (!intInRange(cfg.num_epochs, 1, 10)) errs.num_epochs = '训练轮数需为 1–10 的整数'
  if (!intInRange(cfg.batch_size, 1, 8)) errs.batch_size = '批次大小需为 1–8 的整数'
  if (!Number.isFinite(cfg.learning_rate) || cfg.learning_rate <= 0 || cfg.learning_rate > 0.01) {
    errs.learning_rate = '学习率需大于 0 且不超过 0.01'
  }
  if (!intInRange(cfg.lora_r, 4, 64)) errs.lora_r = 'LoRA Rank 需为 4–64 的整数'
  if (!intInRange(cfg.lora_alpha, 8, 128)) errs.lora_alpha = 'LoRA Alpha 需为 8–128 的整数'
  return errs
}

export default function ModelTraining() {
  const navigate = useNavigate()
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [initialError, setInitialError] = useState('')
  const [pollError, setPollError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [lastSync, setLastSync] = useState(null)
  const [showConfig, setShowConfig] = useState(false)
  const [config, setConfig] = useState(DEFAULT_CONFIG)
  const [fieldErrors, setFieldErrors] = useState({})
  const [confirmStart, setConfirmStart] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [starting, setStarting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [startError, setStartError] = useState('')
  const [logFollow, setLogFollow] = useState(true)

  const seqRef = useRef(0)
  const mountedRef = useRef(true)
  const hasDataRef = useRef(false)
  const configRef = useRef(null)
  const logRef = useRef(null)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  /* ---------------- 状态轮询（10s）与手动刷新共用 ---------------- */
  const loadStatus = useCallback(async ({ silent = false } = {}) => {
    const seq = ++seqRef.current
    if (!silent) setRefreshing(true)
    try {
      const data = await trainingApi.status()
      if (!mountedRef.current || seq !== seqRef.current) return false
      setStatus(data || null)
      hasDataRef.current = true
      setInitialError('')
      setPollError('')
      setLastSync(new Date())
      setLoading(false)
      return true
    } catch (e) {
      if (!mountedRef.current || seq !== seqRef.current) return false
      const msg = e?.message || '无法读取训练状态'
      if (!hasDataRef.current) setInitialError(msg)
      else setPollError(msg)
      setLoading(false)
      return false
    } finally {
      if (mountedRef.current && seq === seqRef.current) setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    loadStatus({ silent: true })
    const timer = window.setInterval(() => loadStatus({ silent: true }), 10000)
    return () => {
      window.clearInterval(timer)
      seqRef.current += 1
    }
  }, [loadStatus])

  const refreshStatus = async () => {
    const ok = await loadStatus()
    if (ok) toastOk('训练状态已刷新')
    else toastErr('刷新失败，请检查后端服务后重试')
  }

  const openConfig = useCallback(() => {
    setShowConfig(true)
    window.setTimeout(() => {
      try {
        configRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      } catch {
        /* 老浏览器不支持 smooth 时忽略 */
      }
    }, 80)
  }, [])

  const toggleConfig = () => {
    if (showConfig) setShowConfig(false)
    else openConfig()
  }

  const updateConfig = (key, value) => {
    setConfig((prev) => ({ ...prev, [key]: value }))
    setFieldErrors((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const resetConfig = () => {
    setConfig(DEFAULT_CONFIG)
    setFieldErrors({})
  }

  const statusValue = status?.status || ''
  const meta = STATUS_META[statusValue] || {
    label: statusValue || '未知', tone: 'outline', note: '状态来自后端',
  }
  const isActive = ACTIVE_STATES.has(statusValue)
  const hasJob = !!status && statusValue !== 'idle'
  const progress = Math.max(0, Math.min(100, Number(status?.progress) || 0))
  const logs = Array.isArray(status?.logs) ? status.logs : []

  /* 日志跟随：仅当用户停在底部时自动滚动，避免打断向上翻阅 */
  useEffect(() => {
    if (!logFollow) return
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [status?.logs, logFollow])

  const onLogScroll = () => {
    const el = logRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    setLogFollow(nearBottom)
  }

  const copyLogs = async () => {
    if (!logs.length) return
    try {
      await navigator.clipboard.writeText(logs.join('\n'))
      toastOk('训练日志已复制')
    } catch {
      toastErr('复制失败，请手动选择日志内容')
    }
  }

  const submitConfig = (e) => {
    e.preventDefault()
    const errs = validateConfig(config)
    setFieldErrors(errs)
    if (Object.keys(errs).length) {
      toastWarn('配置中有不合法的参数，请检查')
      return
    }
    setStartError('')
    setConfirmStart(true)
  }

  const startTraining = async () => {
    setStarting(true)
    setStartError('')
    try {
      const payload = {
        base_model: String(config.base_model || '').trim(),
        data_dir: String(config.data_dir || '').trim(),
        num_epochs: Number(config.num_epochs),
        batch_size: Number(config.batch_size),
        learning_rate: Number(config.learning_rate),
        lora_r: Number(config.lora_r),
        lora_alpha: Number(config.lora_alpha),
        use_gpu: !!config.use_gpu,
      }
      const result = await trainingApi.start(payload)
      toastOk(result?.message || '训练任务已启动')
      setConfirmStart(false)
      setShowConfig(false)
      await loadStatus({ silent: true })
    } catch (e) {
      const msg = e?.message || '启动训练失败'
      setStartError(msg)
      toastErr(msg)
    } finally {
      setStarting(false)
    }
  }

  const cancelTraining = async () => {
    setCancelling(true)
    try {
      const result = await trainingApi.cancel()
      const msg = result?.message || '训练任务已取消'
      if (/没有|未运行/.test(msg)) toastWarn(msg)
      else toastOk(msg)
      setConfirmCancel(false)
      await loadStatus({ silent: true })
    } catch (e) {
      toastErr(e?.message || '取消训练失败')
    } finally {
      setCancelling(false)
    }
  }

  const stageIndex = { preparing: 0, training: 1, merging: 2, completed: 3 }[statusValue]

  const metrics = useMemo(() => ([
    {
      label: '全局步数',
      value: status?.max_steps ? `${fmtNum(status.global_step)} / ${fmtNum(status.max_steps)}` : fmtNum(status?.global_step),
      hint: 'trainer_state.json',
    },
    { label: '最近 Loss', value: status?.last_loss == null ? '—' : String(status.last_loss), hint: '训练损失' },
    { label: '当前 Epoch', value: fmtEpoch(status?.current_epoch, status?.total_epochs), hint: '轮次进度' },
    {
      label: '预计剩余',
      value: status?.estimated_time && status.estimated_time !== '-' ? status.estimated_time : '—',
      hint: '后端按已用时间估算',
    },
  ]), [status])

  const detailRows = useMemo(() => {
    if (!hasJob) return []
    return [
      { label: '任务状态', value: meta.label, code: statusValue, note: meta.note },
      { label: '训练进度', value: `${Math.round(progress)}%`, note: '后端进度值' },
      { label: '当前 Epoch', value: fmtEpoch(status?.current_epoch, status?.total_epochs), note: '当前轮 / 总轮数' },
      {
        label: '全局步数',
        value: status?.max_steps ? `${fmtNum(status.global_step)} / ${fmtNum(status.max_steps)}` : fmtNum(status?.global_step),
        note: '已训练步数 / 总步数',
      },
      { label: '最近 Loss', value: status?.last_loss == null ? '—' : String(status.last_loss), note: '最近一次记录的损失' },
      {
        label: '预计剩余',
        value: status?.estimated_time && status.estimated_time !== '-' ? status.estimated_time : '—',
        note: '状态接口实时估算',
      },
      { label: '数据目录', value: status?.data_dir || '—', note: '训练数据目录', mono: true },
      { label: '输出目录', value: status?.output_dir || '—', note: 'checkpoints 输出目录', mono: true },
      { label: '训练进程 PID', value: status?.pid || '—', note: '后端进程号', mono: true },
      { label: '页面最后同步', value: lastSync ? lastSync.toLocaleString('zh-CN', { hour12: false }) : '—', note: '每 10 秒自动轮询' },
    ]
  }, [hasJob, meta, statusValue, progress, status, lastSync])

  const stopActive = isActive

  return (
    <div className="v3-ops v3-mt">
      <PageHeader
        eyebrow="数据管理 / 模型训练"
        title="模型训练与文档识别"
        sub="LoRA 微调答疑模型 · 批量 OCR 识别 · 去手写处理 · 知识库导入"
        actions={(
          <>
            <Button
              variant="ghost"
              icon={<RefreshCw size={15} />}
              loading={refreshing}
              onClick={refreshStatus}
            >
              刷新状态
            </Button>
            <Button
              variant={showConfig ? 'tonal' : 'filled'}
              icon={<SlidersHorizontal size={15} />}
              onClick={toggleConfig}
            >
              {showConfig ? '收起配置' : '训练配置'}
            </Button>
          </>
        )}
      />

      {initialError && !status && (
        <Alert tone="danger">
          <div className="v3-ops-inline">
            <span>训练状态读取失败：{initialError}</span>
            <Button size="sm" variant="outline" onClick={refreshStatus}>重试</Button>
          </div>
        </Alert>
      )}

      {/* 实时概览 */}
      <div className="v3-ops-stats">
        <div className={cx('v3-ops-stat', isActive && 'is-primary')}>
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><Activity size={14} />当前状态</span>
            {isActive && <span className="v3-ops-dot" aria-hidden="true" />}
          </div>
          <div className="v3-ops-stat__value v3-ops-stat__value--text">
            {loading && !status ? <Skeleton width={84} height={28} /> : (status ? meta.label : '—')}
          </div>
          <div className="v3-ops-stat__hint">{status ? meta.note : '等待状态接口'}</div>
        </div>

        <div className={cx('v3-ops-stat', hasJob && 'is-primary')}>
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><Gauge size={14} />训练进度</span>
            <span className="v3-ops-mono v3-ops-stat__tag">{hasJob ? `${Math.round(progress)}%` : '—'}</span>
          </div>
          <div className="v3-ops-stat__value">{loading && !status ? <Skeleton width={64} height={28} /> : (hasJob ? `${Math.round(progress)}%` : '—')}</div>
          <Progress value={progress} height={5} gradient className="v3-ops-stat__progress" />
          <div className="v3-ops-stat__hint">
            {status?.max_steps ? `第 ${fmtNum(status.global_step)} / ${fmtNum(status.max_steps)} 步` : '尚无步数数据'}
          </div>
        </div>

        <div className={cx('v3-ops-stat', hasJob && 'is-info')}>
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><Timer size={14} />当前 Epoch</span>
          </div>
          <div className="v3-ops-stat__value">{loading && !status ? <Skeleton width={72} height={28} /> : fmtEpoch(status?.current_epoch, status?.total_epochs)}</div>
          <div className="v3-ops-stat__hint">{status?.total_epochs ? `共 ${status.total_epochs} 轮` : '由 trainer_state 读取'}</div>
        </div>

        <div className={cx('v3-ops-stat', hasJob && 'is-warning')}>
          <div className="v3-ops-stat__head">
            <span className="v3-ops-stat__label"><Clock size={14} />预计剩余</span>
          </div>
          <div className="v3-ops-stat__value v3-ops-stat__value--text">
            {loading && !status
              ? <Skeleton width={96} height={28} />
              : (status?.estimated_time && status.estimated_time !== '-' ? status.estimated_time : '—')}
          </div>
          <div className="v3-ops-stat__hint">以真实进度估算</div>
        </div>
      </div>

      {/* 任务状态 / 实时控制台 */}
      <Card className="v3-mt-console">
        <CardHead
          icon={<Activity size={17} />}
          title="训练任务状态"
          sub={lastSync ? `最后同步 ${fmtClock(lastSync)} · 每 10 秒自动轮询` : '正在连接训练状态接口'}
          actions={(
            <>
              {pollError && <Badge tone="warning">同步异常</Badge>}
              <Badge tone={meta.tone}>{meta.label}</Badge>
            </>
          )}
        />

        {pollError && status && (
          <Alert tone="warning" className="v3-mt-poll-warning">
            最近一次自动同步失败：{pollError}。下方仍展示上一次成功读取的数据，可手动刷新重试。
          </Alert>
        )}

        {loading && !status ? (
          <div className="v3-mt-console__skeleton">
            <Skeleton width="100%" height={150} radius={20} />
            <div className="v3-ops-stats v3-ops-stats--tight">
              {[0, 1, 2, 3].map((i) => <Skeleton key={i} height={74} radius={16} />)}
            </div>
            <Skeleton width="100%" height={130} radius={16} />
          </div>
        ) : !status || !hasJob ? (
          <Empty
            icon={<Rocket size={28} />}
            title="暂无训练任务"
            text={status?.message || '配置 LoRA 参数后启动训练；页面会每 10 秒读取真实训练进度与日志。'}
            action={(
              <Button variant="filled" icon={<SlidersHorizontal size={15} />} onClick={openConfig}>
                去配置训练
              </Button>
            )}
          />
        ) : (
          <div className="v3-mt-console__body">
            <div className="v3-mt-console__main">
              <div className="v3-mt-ring">
                <Ring value={progress} size={128} stroke={10} gradient>
                  <div className="v3-mt-ring__value">{Math.round(progress)}<span>%</span></div>
                  <div className="v3-mt-ring__label">{meta.label}</div>
                </Ring>
              </div>

              <div className="v3-mt-console__info">
                <div className="v3-mt-message">
                  <Badge tone={meta.tone}>
                    {isActive && <span className="v3-ops-dot" aria-hidden="true" />}
                    {meta.label}
                  </Badge>
                  <span>{status.message || meta.note}</span>
                </div>

                <div className="v3-mt-stages" aria-label="训练阶段">
                  {STAGES.map((stage, idx) => {
                    let state = 'todo'
                    if (statusValue === 'completed') state = 'done'
                    else if (stageIndex != null && stageIndex <= 2) {
                      if (idx < stageIndex) state = 'done'
                      else if (idx === stageIndex) state = 'current'
                    }
                    return (
                      <div className={cx('v3-mt-stage', `is-${state}`)} key={stage.key}>
                        <span className="v3-mt-stage__dot">
                          {state === 'done' ? <CheckCircle2 size={13} /> : idx + 1}
                        </span>
                        <span className="v3-mt-stage__label">{stage.label}</span>
                      </div>
                    )
                  })}
                </div>

                <div className="v3-mt-metrics">
                  {metrics.map((m) => (
                    <div className="v3-mt-metric" key={m.label}>
                      <span>{m.label}</span>
                      <b>{m.value}</b>
                      <em>{m.hint}</em>
                    </div>
                  ))}
                </div>

                <div className="v3-mt-paths">
                  <div>
                    <HardDrive size={14} />
                    <span>数据目录</span>
                    <code>{status.data_dir || '—'}</code>
                  </div>
                  <div>
                    <Cpu size={14} />
                    <span>输出目录</span>
                    <code>{status.output_dir || '—'}</code>
                  </div>
                </div>

                <div className="v3-mt-console__actions">
                  {statusValue === 'training' ? (
                    <Button variant="danger" icon={<AlertTriangle size={15} />} onClick={() => setConfirmCancel(true)}>
                      取消训练
                    </Button>
                  ) : (
                    <span className="v3-ops-caption">
                      {isActive ? '当前阶段不支持取消（仅训练中可取消）' : '任务已结束，可重新配置启动'}
                    </span>
                  )}
                  <Button
                    variant="ghost"
                    icon={<SlidersHorizontal size={15} />}
                    onClick={openConfig}
                    disabled={stopActive && statusValue === 'training'}
                  >
                    配置新任务
                  </Button>
                </div>
              </div>
            </div>

            <div className="v3-mt-log">
              <div className="v3-mt-log__head">
                <div>
                  <span className="v3-mt-log__title">训练日志</span>
                  <span className="v3-ops-caption">后端回传最近 {logs.length} 行 · train.log</span>
                </div>
                <div className="v3-mt-log__tools">
                  <Chip active={logFollow} onClick={() => setLogFollow((v) => !v)}>自动滚动</Chip>
                  <IconButton
                    label="复制训练日志"
                    icon={<Copy size={15} />}
                    onClick={copyLogs}
                    disabled={!logs.length}
                  />
                </div>
              </div>
              {logs.length ? (
                <pre ref={logRef} className="v3-mt-log__pre" onScroll={onLogScroll}>
                  {logs.join('\n')}
                </pre>
              ) : (
                <div className="v3-mt-log__empty">
                  暂无训练日志。训练进程写入 train.log 后，这里会自动显示尾部内容。
                </div>
              )}
            </div>
          </div>
        )}
      </Card>

      {/* 训练配置（主操作卡） */}
      {showConfig && (
        <div ref={configRef} className="v3-mt-config-anchor">
          <Card className="v3-mt-config">
            <CardHead
              icon={<SlidersHorizontal size={17} />}
              title="LoRA 微调配置"
              sub="参数在本机训练进程执行；数据目录必须位于后端 data/ 下"
              actions={<Badge tone="soft">8GB 显存基线</Badge>}
            />
            <form onSubmit={submitConfig} noValidate>
              {isActive && (
                <Alert tone="warning" className="v3-mt-config__alert">
                  已有训练任务处于「{meta.label}」，后端会拒绝重复启动。请等待任务结束或先在状态卡中取消。
                </Alert>
              )}

              <div className="v3-mt-form">
                <Field label="基座模型" hint="留空则使用后端 LORA_MODEL_NAME">
                  <Input
                    value={config.base_model}
                    onChange={(e) => updateConfig('base_model', e.target.value)}
                    placeholder="留空则用后端 LORA_MODEL_NAME"
                    autoComplete="off"
                  />
                </Field>

                <Field label="训练数据目录" hint="留空则使用 data/lora_finetune；需含 train.jsonl / val.jsonl">
                  <Input
                    value={config.data_dir}
                    onChange={(e) => updateConfig('data_dir', e.target.value)}
                    placeholder="留空则用 data/lora_finetune"
                    autoComplete="off"
                  />
                </Field>

                <Field label="训练轮数 Epochs" hint="8GB 建议 3；前端上限 10" error={fieldErrors.num_epochs}>
                  <Input
                    type="number"
                    min="1"
                    max="10"
                    step="1"
                    value={config.num_epochs}
                    onChange={(e) => updateConfig('num_epochs', e.target.value === '' ? '' : Number(e.target.value))}
                  />
                </Field>

                <Field label="批次大小 Batch Size" hint="8GB 显存建议 1；前端上限 8" error={fieldErrors.batch_size}>
                  <Input
                    type="number"
                    min="1"
                    max="8"
                    step="1"
                    value={config.batch_size}
                    onChange={(e) => updateConfig('batch_size', e.target.value === '' ? '' : Number(e.target.value))}
                  />
                </Field>

                <Field label="学习率 Learning Rate" hint="默认 2e-4；需在 (0, 0.01] 内" error={fieldErrors.learning_rate}>
                  <Input
                    type="number"
                    step="0.00001"
                    value={config.learning_rate}
                    onChange={(e) => updateConfig('learning_rate', e.target.value === '' ? '' : parseFloat(e.target.value))}
                  />
                </Field>

                <Field label="LoRA Rank (r)" hint="4–64，越大显存占用越高" error={fieldErrors.lora_r}>
                  <Input
                    type="number"
                    min="4"
                    max="64"
                    step="1"
                    value={config.lora_r}
                    onChange={(e) => updateConfig('lora_r', e.target.value === '' ? '' : Number(e.target.value))}
                  />
                </Field>

                <Field label="LoRA Alpha" hint="8–128，一般设为 Rank 的 2 倍" error={fieldErrors.lora_alpha}>
                  <Input
                    type="number"
                    min="8"
                    max="128"
                    step="1"
                    value={config.lora_alpha}
                    onChange={(e) => updateConfig('lora_alpha', e.target.value === '' ? '' : Number(e.target.value))}
                  />
                </Field>

                <Field label="计算设备" hint="8GB 显存建议开启 GPU，并保持 batch_size = 1">
                  <div className="v3-mt-device" role="group" aria-label="计算设备">
                    <Chip
                      active={!!config.use_gpu}
                      gradient={!!config.use_gpu}
                      icon={<Zap size={14} />}
                      onClick={() => updateConfig('use_gpu', true)}
                    >
                      GPU 加速
                    </Chip>
                    <Chip
                      active={!config.use_gpu}
                      icon={<Cpu size={14} />}
                      onClick={() => updateConfig('use_gpu', false)}
                    >
                      CPU（极慢）
                    </Chip>
                  </div>
                </Field>
              </div>

              <Alert tone="warning" icon={<AlertTriangle size={17} />} className="v3-mt-guard">
                8GB 显存保护：建议 <b>batch_size = 1</b>、LoRA Rank ≤ 16；CPU 模式极慢，不推荐。
                训练数据目录必须位于后端 <code>data/</code> 下，并同时包含 <code>train.jsonl</code> 与 <code>val.jsonl</code>。
              </Alert>

              <div className="v3-mt-form__foot">
                <Button
                  variant="text"
                  icon={<RotateCcw size={15} />}
                  onClick={resetConfig}
                  disabled={starting}
                >
                  恢复建议值
                </Button>
                <div className="v3-row">
                  <Button variant="ghost" onClick={() => setShowConfig(false)} disabled={starting}>
                    收起
                  </Button>
                  <Button
                    type="submit"
                    variant="filled"
                    icon={<Rocket size={15} />}
                    disabled={isActive || starting}
                  >
                    {isActive ? '已有任务运行中' : '启动训练'}
                  </Button>
                </div>
              </div>
            </form>
          </Card>
        </div>
      )}

      {/* 当前任务明细：没有历史接口，只展示 status 真实字段 */}
      <Card>
        <CardHead
          icon={<Gauge size={17} />}
          title="当前任务明细"
          sub="直接映射 /api/model-training/training/status 返回字段"
          actions={<Badge tone="outline">实时</Badge>}
        />
        {loading && !status ? (
          <div className="v3-mt-detail-skeleton">
            {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} height={42} radius={10} />)}
          </div>
        ) : detailRows.length ? (
          <div className="v3-table-wrap">
            <table className="v3-table v3-mt-detail-table">
              <thead>
                <tr>
                  <th>指标</th>
                  <th>当前值</th>
                  <th className="v3-mt-hide-sm">说明</th>
                </tr>
              </thead>
              <tbody>
                {detailRows.map((row) => (
                  <tr key={row.label}>
                    <td className="v3-mt-detail-table__label">{row.label}</td>
                    <td className={cx('v3-mt-detail-table__value', row.mono && 'v3-ops-mono')}>
                      {row.value}
                      {row.code && <span className="v3-mt-detail-table__code">{row.code}</span>}
                    </td>
                    <td className="v3-mt-hide-sm v3-ops-muted">{row.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            icon={<Timer size={24} />}
            title="暂无任务明细"
            text="启动训练后，这里会展示后端实时返回的进度、Loss、目录与进程信息。"
          />
        )}
      </Card>

      {/* 文档识别与导入 */}
      <Card className="v3-mt-doc">
        <CardHead
          icon={<FileText size={17} />}
          title="文档识别与知识库导入"
          sub="OCR 与题目识别在知识库导入页执行；本页不伪造识别结果"
        />
        <div className="v3-ops-grid-2">
          <div className="v3-mt-doc__item">
            <div className="v3-mt-doc__icon"><FileText size={20} /></div>
            <div>
              <b>批量 OCR 识别</b>
              <p>对知识库中的 PDF / DOCX 文档进行 OCR 文字识别，提取可搜索内容，并在上传后自动解析分块。</p>
              <Button
                variant="outline"
                size="sm"
                icon={<Sparkles size={14} />}
                onClick={() => {
                  toastOk('已前往知识库导入，可在文档行触发扫描')
                  navigate('/admin/kb-import')
                }}
              >
                前往知识库导入
              </Button>
            </div>
          </div>

          <div className="v3-mt-doc__item is-muted">
            <div className="v3-mt-doc__icon"><Wand size={20} /></div>
            <div>
              <b>去手写处理</b>
              <p>移除扫描版教材 / 试卷上的手写笔记，保留印刷体内容。后端接口尚未实现，当前不可用。</p>
              <Button variant="outline" size="sm" icon={<Wand size={14} />} disabled>
                去手写处理（开发中）
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {/* 流程与约束 */}
      <Card>
        <CardHead icon={<FileText size={17} />} title="训练流程与运行约束" />
        <div className="v3-mt-flow">
          <div>
            <h3>训练流程</h3>
            <ol className="v3-mt-flow__list">
              <li><b>数据准备</b><span>指定数据目录，需含 train.jsonl / val.jsonl</span></li>
              <li><b>启动训练</b><span>配置参数后由后端真实拉起训练进程</span></li>
              <li><b>监控进度</b><span>每 10 秒读取 trainer_state.json 与日志尾部</span></li>
              <li><b>合并模型</b><span>训练完成后用 lora_finetune.py --stage merge 合并</span></li>
              <li><b>部署上线</b><span>新模型导入 Ollama，更新 AI 助手路由配置</span></li>
            </ol>
          </div>
          <div>
            <h3>注意事项</h3>
            <ul className="v3-mt-flow__list v3-mt-flow__list--bullets">
              <li>训练需要 GPU 支持，CPU 模式极慢（不推荐）</li>
              <li>建议至少 8GB 显存，否则可能 OOM</li>
              <li>训练日志写入所选数据目录的 train.log</li>
              <li>训练进程使用后端 LORA_TRAIN_PYTHON 指定的 Python（需装 torch / peft）</li>
              <li>页面仅展示后端真实状态；接口失败时保留上一次成功读取的数据并标注同步异常</li>
            </ul>
          </div>
        </div>
      </Card>

      {/* 启动确认 */}
      <Dialog
        open={confirmStart}
        title="启动 LoRA 微调任务"
        sub="预计需要 2–4 小时，训练期间会持续占用 GPU 资源。"
        onClose={() => { if (!starting) setConfirmStart(false) }}
        footer={(
          <>
            <Button variant="text" onClick={() => setConfirmStart(false)} disabled={starting}>取消</Button>
            <Button variant="filled" icon={<Rocket size={15} />} loading={starting} onClick={startTraining}>
              确认启动
            </Button>
          </>
        )}
      >
        <div className="v3-mt-confirm">
          <div className="v3-mt-confirm__grid">
            <div><span>基座模型</span><b>{config.base_model.trim() || '后端默认 LORA_MODEL_NAME'}</b></div>
            <div><span>数据目录</span><b>{config.data_dir.trim() || 'data/lora_finetune'}</b></div>
            <div><span>Epochs</span><b>{config.num_epochs}</b></div>
            <div><span>Batch Size</span><b>{config.batch_size}</b></div>
            <div><span>学习率</span><b>{config.learning_rate}</b></div>
            <div><span>LoRA</span><b>r={config.lora_r} · alpha={config.lora_alpha}</b></div>
            <div className="v3-mt-confirm__wide">
              <span>计算设备</span>
              <b>{config.use_gpu ? 'GPU 加速' : 'CPU（极慢）'}</b>
            </div>
          </div>
          <Alert tone="warning" icon={<AlertTriangle size={17} />}>
            请确认数据目录包含 train.jsonl / val.jsonl，且后端 data/ 空间充足。训练开始后可在状态卡中取消；取消不会删除已写入的检查点。
          </Alert>
          {startError && <Alert tone="danger">{startError}</Alert>}
        </div>
      </Dialog>

      {/* 取消确认 */}
      <Dialog
        open={confirmCancel}
        title="取消当前训练任务"
        sub="确定要取消正在运行的 LoRA 训练吗？"
        onClose={() => { if (!cancelling) setConfirmCancel(false) }}
        footer={(
          <>
            <Button variant="text" onClick={() => setConfirmCancel(false)} disabled={cancelling}>保留任务</Button>
            <Button variant="danger" loading={cancelling} onClick={cancelTraining}>确认取消</Button>
          </>
        )}
      >
        <Alert tone="danger" icon={<AlertTriangle size={17} />}>
          取消会终止后端训练进程。已写入的输出目录与日志不会被删除，但当前 epoch 的训练进度将丢失。
        </Alert>
        <div className="v3-mt-confirm__meta">
          <span>任务状态：<b>{meta.label}</b></span>
          <span>当前进度：<b>{Math.round(progress)}%</b></span>
          <span>PID：<b className="v3-ops-mono">{status?.pid || '—'}</b></span>
        </div>
      </Dialog>
    </div>
  )
}
