import React, {
  useCallback, useEffect, useId, useMemo, useState,
} from 'react'
import { qualityApi } from '../../api/client'
import {
  Badge, Button, Card, CardHead, Dialog, Empty, PageHeader, Progress, Segmented,
  Skeleton, Tile, cx, toastErr, toastOk,
} from '../ui'
import {
  Activity, AlertCircle, Database, Gauge, Layers, LineChart, RefreshCw, Shield,
  Target,
} from '../icons'
import '../styles/admin-core-v3.css'

/* ============================================================
   评测与数据质量（/admin/quality）

   所有数字来自 eval_runs（评测脚本每次运行写一行）与库内聚合，
   前端不做估算。识别样本指标与语料全库规模分开展示，避免误读。
   ============================================================ */

const KINDS = [
  { value: 'recognition_policy', label: '识别口径' },
  { value: 'recognition', label: '识别精度' },
  { value: 'qa', label: '答疑模型' },
  { value: 'corpus_probe', label: '语料体检' },
]

const pct = (v) => (v === null || v === undefined || Number.isNaN(Number(v))
  ? '—'
  : `${(Number(v) * 100).toFixed(1)}%`)
const num = (v) => (v === null || v === undefined || Number.isNaN(Number(v))
  ? '—'
  : Number(v).toLocaleString('zh-CN'))

const METRIC_LABEL = {
  prec: ['学科池 Precision', 'high'],
  rec: ['域内 Recall', 'high'],
  f1: ['Macro F1', 'high'],
  cov: ['覆盖率', 'high'],
  pollute: ['域外污染率', 'low'],
}

function toneFor(metricKey, v) {
  if (v === null || v === undefined) return 'outline'
  const higherBetter = (METRIC_LABEL[metricKey] || [])[1] !== 'low'
  const good = higherBetter ? Number(v) >= 0.9 : Number(v) <= 0.2
  const bad = higherBetter ? Number(v) < 0.7 : Number(v) > 0.5
  return good ? 'success' : bad ? 'danger' : 'warning'
}

const fmtDateTime = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

const shortTime = (iso) => (iso ? String(iso).slice(5, 16).replace('T', ' ') : '—')

const HISTORY_KIND = Object.fromEntries(KINDS.map((k) => [k.value, k.label]))

const ALIGN_KIND = {
  alias_folded: ['别名折叠', 'success'],
  combined_expanded: ['合并口径展开', 'success'],
  not_aliased: ['明确不归一', 'danger'],
  unknown_mapping: ['词表未登记', 'danger'],
}

/* 固定 0–100% 纵轴的自绘趋势图：
   仅靠 ../ui 与 ../icons，不引入图表库；点用 HTML 定位，折线用 SVG，
   避免非等比拉伸把线宽和圆点压扁。 */
function TrendChart({ runs }) {
  const gid = useId().replace(/:/g, '')
  const areaId = `quality-area-${gid}`
  const lineId = `quality-line-${gid}`

  const coords = runs.map((r, i) => {
    const raw = r.primary_metric
    const v = raw === null || raw === undefined || Number.isNaN(Number(raw))
      ? null
      : Math.max(0, Math.min(1, Number(raw)))
    return {
      id: r.id,
      label: shortTime(r.created_at),
      arm: r.arm || '—',
      v,
      x: runs.length === 1 ? 50 : (i / (runs.length - 1)) * 100,
      y: v === null ? null : (1 - v) * 100,
    }
  })

  const segments = []
  let current = []
  coords.forEach((c) => {
    if (c.y === null) {
      if (current.length) segments.push(current)
      current = []
    } else {
      current.push(c)
    }
  })
  if (current.length) segments.push(current)

  const pathOf = (seg) => seg
    .map((c, i) => `${i ? 'L' : 'M'} ${c.x.toFixed(2)} ${c.y.toFixed(2)}`)
    .join(' ')
  const linePath = segments.map(pathOf).join(' ')
  const areaPath = segments
    .filter((seg) => seg.length > 1)
    .map((seg) => `${pathOf(seg)} L ${seg[seg.length - 1].x.toFixed(2)} 100 L ${seg[0].x.toFixed(2)} 100 Z`)
    .join(' ')

  const labelIdx = coords.length <= 5
    ? coords.map((_, i) => i)
    : Array.from(new Set([0, Math.round((coords.length - 1) * 0.25), Math.round((coords.length - 1) * 0.5), Math.round((coords.length - 1) * 0.75), coords.length - 1]))

  const scored = coords.filter((c) => c.v !== null)
  const avg = scored.length ? scored.reduce((n, c) => n + c.v, 0) / scored.length : null

  return (
    <>
      <div className="v3-admin-q-chart">
        <div className="v3-admin-q-chart__y" aria-hidden="true">
          <span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0%</span>
        </div>
        <div className="v3-admin-q-chart__plot">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="主指标随运行时间的变化">
            <defs>
              <linearGradient id={areaId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: 'var(--v3-secondary)' }} stopOpacity="0.32" />
                <stop offset="100%" style={{ stopColor: 'var(--v3-secondary)' }} stopOpacity="0" />
              </linearGradient>
              <linearGradient id={lineId} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" style={{ stopColor: 'var(--v3-primary)' }} />
                <stop offset="52%" style={{ stopColor: 'var(--v3-secondary)' }} />
                <stop offset="100%" style={{ stopColor: 'var(--v3-gemini-3)' }} />
              </linearGradient>
            </defs>
            {areaPath ? <path d={areaPath} fill={`url(#${areaId})`} /> : null}
            {linePath ? (
              <path
                d={linePath}
                fill="none"
                stroke={`url(#${lineId})`}
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </svg>
          {scored.map((c) => (
            <span
              key={c.id}
              className="v3-admin-q-chart__dot"
              style={{ left: `${c.x}%`, top: `${c.y}%` }}
              title={`${c.label} · ${c.arm} · ${pct(c.v)}`}
            />
          ))}
        </div>
        <div className="v3-admin-q-chart__x" aria-hidden="true">
          {labelIdx.map((i) => <span key={i}>{coords[i].label}</span>)}
        </div>
      </div>
      <div className="v3-admin-q-trend-legend">
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <span className="v3-admin-q-legend-dot" />
          主指标（纵轴固定 0–100%）
        </span>
        <span>有效点 <b>{scored.length}</b> / {coords.length}</span>
        <span>均值 <b>{avg === null ? '—' : pct(avg)}</b></span>
      </div>
    </>
  )
}

function RunDetail({ run }) {
  const [full, setFull] = useState(null)
  const [state, setState] = useState('loading')

  useEffect(() => {
    if (!run) return undefined
    let alive = true
    setFull(null)
    setState('loading')
    qualityApi.evalRun(run.id)
      .then((d) => {
        if (!alive) return
        setFull(d)
        setState('ok')
      })
      .catch(() => alive && setState('error'))
    return () => { alive = false }
  }, [run])

  if (!run) return null
  const samples = full?.run?.n_samples ?? run.n_samples
  return (
    <div>
      <div className="v3-admin-q-meta">
        <div>
          <span>数据集指纹</span>
          <b className="v3-admin-mono">{run.dataset_fingerprint || '—'}</b>
        </div>
        <div>
          <span>样本数</span>
          <b>{num(samples)}</b>
        </div>
        <div>
          <span>报告路径</span>
          <b className="v3-admin-mono">{run.report_path || '—'}</b>
        </div>
        <div>
          <span>运行时间</span>
          <b>{fmtDateTime(run.created_at)}</b>
        </div>
      </div>
      {run.notes ? <p className="v3-admin-q-notes">{run.notes}</p> : null}
      {state === 'loading' ? (
        <div style={{ display: 'grid', gap: 8 }}>
          <Skeleton height={13} width="42%" />
          <Skeleton height={140} radius={10} />
        </div>
      ) : null}
      {state === 'error' ? (
        <Empty
          icon={<AlertCircle size={26} />}
          title="完整指标加载失败"
          text={`无法读取运行 #${run.id} 的指标明细，请稍后重试。`}
        />
      ) : null}
      {state === 'ok' ? (
        <pre className="v3-admin-q-pre">{JSON.stringify(full?.metrics || {}, null, 1)}</pre>
      ) : null}
    </div>
  )
}

export default function QualityDashboard() {
  const [kind, setKind] = useState('recognition_policy')
  const [runs, setRuns] = useState([])
  const [corpus, setCorpus] = useState(null)
  const [align, setAlign] = useState(null)
  const [alignStatus, setAlignStatus] = useState('loading')
  const [detail, setDetail] = useState(null)
  const [status, setStatus] = useState('loading')
  const [policy, setPolicy] = useState({ status: 'idle', metrics: null, run: null, error: '' })

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const [r, c] = await Promise.all([
        qualityApi.evalRuns({ limit: 200 }),
        qualityApi.corpus(),
      ])
      setRuns(r?.items || [])
      setCorpus(c)
      setStatus('ok')
      return true
    } catch {
      setStatus('error')
      return false
    }
  }, [])

  const loadAlign = useCallback(async () => {
    setAlignStatus('loading')
    try {
      const d = await qualityApi.subjectAlignment()
      setAlign(d)
      setAlignStatus('ok')
      return true
    } catch {
      setAlignStatus('error')
      return false
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadAlign() }, [loadAlign])

  const policyRun = useMemo(() => runs.find((r) => r.kind === 'recognition_policy'), [runs])
  const policyId = policyRun?.id

  useEffect(() => {
    if (!policyId) {
      setPolicy({ status: 'idle', metrics: null, run: null, error: '' })
      return undefined
    }
    let alive = true
    setPolicy({ status: 'loading', metrics: null, run: null, error: '' })
    qualityApi.evalRun(policyId)
      .then((d) => {
        if (!alive) return
        setPolicy({ status: 'ok', metrics: d?.metrics || {}, run: d?.run || null, error: '' })
      })
      .catch((e) => {
        if (!alive) return
        setPolicy({ status: 'error', metrics: null, run: null, error: e?.message || '指标明细加载失败' })
      })
    return () => { alive = false }
  }, [policyId])

  const refresh = async () => {
    const [mainOk, alignOk] = await Promise.all([load(), loadAlign()])
    if (mainOk && alignOk) toastOk('质量数据已刷新')
    else toastErr('部分质量数据刷新失败，请检查后端服务')
  }

  const byKind = useMemo(() => runs.filter((r) => r.kind === kind), [runs, kind])
  const trend = useMemo(() => byKind.slice().reverse(), [byKind])

  const prod = policy.metrics?.policies?.['生产采用'] || null
  const nSamples = policy.run?.n_samples ?? policyRun?.n_samples ?? null
  const ghost = corpus?.ghost_index?.indexed_without_chunks ?? null
  const corpusLoading = status === 'loading' && !corpus

  /* 历史运行刚返回、口径明细还没开始取时，也不能先闪一帧「暂无口径」 */
  const policyLoading = policy.status === 'loading'
    || (status === 'loading' && !policyRun)
    || (policy.status === 'idle' && !!policyRun)

  const policyHint = (okText) => {
    if (policy.status === 'loading') return '正在读取生产口径…'
    if (policy.status === 'error') return '口径明细加载失败'
    return okText
  }

  const corpusSubs = Array.isArray(corpus?.subjects) ? corpus.subjects : []
  const maxChunks = Math.max(1, ...corpusSubs.map((s) => Number(s.chunks) || 0))
  const totalChunks = Number(corpus?.total_chunks) || 0

  const policyRows = policy.status === 'ok' ? Object.entries(policy.metrics?.policies || {}) : []
  const rejectedRows = policy.status === 'ok' ? Object.entries(policy.metrics?.rejected || {}) : []
  const alignRows = Array.isArray(align?.rows) ? align.rows : []

  return (
    <div className="v3-admin-page">
      <PageHeader
        eyebrow="ADMIN · 评测质量"
        title="评测与数据质量"
        sub="识别口径、答疑模型、语料体检的历史运行与指标；数字直接来自 eval_runs 与库内聚合，不做前端估算。"
        actions={(
          <Button
            variant="outline"
            icon={<RefreshCw size={15} />}
            loading={status === 'loading'}
            onClick={refresh}
          >
            刷新数据
          </Button>
        )}
      />

      <div className="v3-admin-stats">
        <Tile className="v3-admin-stat v3-admin-q-tile">
          <span className="v3-tile__label"><Gauge size={14} />学科池 Precision</span>
          <span className="v3-tile__value">{prod ? pct(prod.prec) : '—'}</span>
          <span className="v3-tile__hint">
            {policyHint(nSamples === null ? '无生产口径记录' : `${num(nSamples)} 条人工判分样本`)}
          </span>
        </Tile>
        <Tile className="v3-admin-stat v3-admin-q-tile">
          <span className="v3-tile__label"><Target size={14} />域内 Recall</span>
          <span className="v3-tile__value">{prod ? pct(prod.rec) : '—'}</span>
          <span className="v3-tile__hint">{policyHint('生产采用口径 · 越高越好')}</span>
        </Tile>
        <Tile className="v3-admin-stat v3-admin-q-tile">
          <span className="v3-tile__label"><Shield size={14} />域外污染率</span>
          <span className="v3-tile__value">{prod ? pct(prod.pollute) : '—'}</span>
          <span className="v3-tile__hint">{policyHint('生产采用口径 · 越低越好')}</span>
        </Tile>
        <Tile className="v3-admin-stat v3-admin-q-tile">
          <span className="v3-tile__label"><Database size={14} />语料块总数</span>
          <span className="v3-tile__value">{num(corpus?.total_chunks)}</span>
          <span className="v3-tile__hint">
            {corpusLoading ? '正在聚合库内数据…' : status === 'error' ? '语料接口未响应' : `覆盖 ${num(corpus?.total_documents)} 篇文档`}
          </span>
        </Tile>
        <Tile className="v3-admin-stat v3-admin-q-tile">
          <span className="v3-tile__label"><Layers size={14} />弃权占比</span>
          <span className="v3-tile__value">{pct(corpus?.abstained_rate)}</span>
          <span className="v3-tile__hint">
            {corpusLoading ? '正在聚合库内数据…' : '分块无法归入学科池的比例'}
          </span>
        </Tile>
        <Tile className={cx('v3-admin-stat', 'v3-admin-q-tile', ghost > 0 && 'is-warn')}>
          <span className="v3-tile__label"><AlertCircle size={14} />「已入库」但零分块</span>
          <span className="v3-tile__value">{num(ghost)}</span>
          <span className="v3-tile__hint">
            {ghost > 0
              ? '列表显示已入库，但 RAG 检索不到内容'
              : corpusLoading
                ? '正在读取语料体检…'
                : status === 'error' ? '语料接口未响应' : '状态与分块一致'}
          </span>
        </Tile>
      </div>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <div className="v3-admin-q-trend-head">
            <div>
              <div className="v3-card__title"><LineChart size={16} />指标趋势</div>
              <div className="v3-card__sub">按运行时间正序；纵轴固定 0–100%，不随数据缩放。</div>
            </div>
            <Segmented options={KINDS} value={kind} onChange={setKind} ariaLabel="评测类型" />
          </div>
        </div>
        <div className="v3-admin-panel__body">
          {status === 'loading' ? (
            <div style={{ display: 'grid', gap: 12 }}>
              <Skeleton height={232} radius={12} />
              <Skeleton height={12} width="48%" />
            </div>
          ) : null}
          {status === 'error' ? (
            <Empty
              icon={<AlertCircle size={28} />}
              title="后端未响应"
              text="请确认服务已启动（/api/quality）后重试。"
              action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={refresh}>重试</Button>}
            />
          ) : null}
          {status === 'ok' && trend.length === 0 ? (
            <Empty
              icon={<LineChart size={28} />}
              title="还没有该类型的运行记录"
              text="跑一次评测脚本即可自动入库。"
            />
          ) : null}
          {status === 'ok' && trend.length > 0 ? <TrendChart runs={trend} /> : null}
        </div>
      </Card>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            icon={<Shield size={16} />}
            title="识别口径对照"
            sub="同一样本、同一打分；「生产采用」行高亮，已实测否决的候选项列在表下。"
          />
        </div>
        {policyLoading ? (
          <div className="v3-admin-panel__body">
            <div style={{ display: 'grid', gap: 9 }}>
              <Skeleton height={12} width="35%" />
              <Skeleton height={38} radius={8} />
              <Skeleton height={38} radius={8} />
              <Skeleton height={38} radius={8} />
            </div>
          </div>
        ) : null}
        {!policyLoading && policy.status === 'error' ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<AlertCircle size={26} />}
              title="口径明细加载失败"
              text={policy.error}
            />
          </div>
        ) : null}
        {!policyLoading && (policy.status === 'idle' || (policy.status === 'ok' && policyRows.length === 0)) ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<Shield size={26} />}
              title="暂无可对照的生产口径"
              text={status === 'error' && !policyRun ? '评测数据未加载，请刷新后重试。' : '还没有 recognition_policy 类型的运行记录。'}
            />
          </div>
        ) : null}
        {policy.status === 'ok' && policyRows.length > 0 ? (
          <>
            <div className="v3-admin-table-wrap">
              <table className="v3-admin-table">
                <thead>
                  <tr>
                    <th>口径</th>
                    {Object.keys(METRIC_LABEL).map((k) => (
                      <th key={k} className="is-right">{METRIC_LABEL[k][0]}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {policyRows.map(([name, v]) => (
                    <tr key={name} className={name === '生产采用' ? 'v3-admin-q-prod-row' : undefined}>
                      <td className="is-strong">{name}</td>
                      {Object.keys(METRIC_LABEL).map((k) => (
                        <td key={k} className="is-right">
                          <Badge tone={toneFor(k, v?.[k])}>{pct(v?.[k])}</Badge>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rejectedRows.length > 0 ? (
              <p className="v3-admin-q-rejected">
                <b>已实测否决：</b>
                {rejectedRows.map(([name, why]) => `${name} — ${why}`).join('；')}
              </p>
            ) : null}
          </>
        ) : null}
      </Card>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            icon={<Activity size={16} />}
            title="运行历史"
            sub="eval_runs 倒序返回；点「详情」查看完整指标 JSON。"
            actions={<Badge tone="outline">{runs.length} 次运行</Badge>}
          />
        </div>
        <div className="v3-admin-table-wrap">
          <table className="v3-admin-table">
            <thead>
              <tr>
                <th className="is-right">#</th>
                <th>类型</th>
                <th>口径 / 模型</th>
                <th className="is-right">主指标</th>
                <th className="is-right">样本</th>
                <th>时间</th>
                <th className="is-right">详情</th>
              </tr>
            </thead>
            <tbody>
              {status === 'loading' && runs.length === 0
                ? Array.from({ length: 4 }).map((_, i) => (
                  <tr key={`sk-${i}`} aria-hidden="true">
                    <td colSpan={7}><Skeleton height={12} width={`${52 + (i % 3) * 10}%`} /></td>
                  </tr>
                ))
                : runs.map((r) => (
                  <tr key={r.id}>
                    <td className="is-right is-tabular is-muted">{r.id}</td>
                    <td className="is-nowrap">{HISTORY_KIND[r.kind] || r.kind || '—'}</td>
                    <td className="is-truncate" title={r.arm || ''}>{r.arm || '—'}</td>
                    <td className="is-right is-tabular is-strong">{pct(r.primary_metric)}</td>
                    <td className="is-right is-tabular">{num(r.n_samples)}</td>
                    <td className="is-nowrap is-muted">{fmtDateTime(r.created_at)}</td>
                    <td className="is-right">
                      <Button variant="text" size="sm" onClick={() => setDetail(r)}>详情</Button>
                    </td>
                  </tr>
                ))}
              {status === 'ok' && runs.length === 0 ? (
                <tr><td colSpan={7} className="v3-admin-table__empty">还没有评测运行记录</td></tr>
              ) : null}
              {status === 'error' && runs.length === 0 ? (
                <tr><td colSpan={7} className="v3-admin-table__empty">运行记录加载失败，请刷新重试</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            icon={<Database size={16} />}
            title="分学科体检"
            sub={corpus
              ? `全库 ${num(corpus.total_chunks)} 块 / ${num(corpus.total_documents)} 篇文档`
              : '库内分块与置信度的全量聚合'}
          />
        </div>
        {corpusLoading ? (
          <div className="v3-admin-panel__body">
            <div style={{ display: 'grid', gap: 9 }}>
              <Skeleton height={12} width="28%" />
              <Skeleton height={36} radius={8} />
              <Skeleton height={36} radius={8} />
              <Skeleton height={36} radius={8} />
            </div>
          </div>
        ) : null}
        {!corpusLoading && !corpus ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<Database size={26} />}
              title="语料体检数据未加载"
              text="接口 /api/quality/corpus 无响应，请确认后端服务后刷新。"
              action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={refresh}>重试</Button>}
            />
          </div>
        ) : null}
        {corpus && corpusSubs.length === 0 ? (
          <div className="v3-admin-panel__body">
            <Empty icon={<Database size={26} />} title="暂无分块数据" text="知识库还没有可检索的分块。" />
          </div>
        ) : null}
        {corpus && corpusSubs.length > 0 ? (
          <div className="v3-admin-table-wrap">
            <table className="v3-admin-table">
              <thead>
                <tr>
                  <th>学科</th>
                  <th className="is-right">块数</th>
                  <th>占比</th>
                  <th className="is-right">平均置信</th>
                  <th className="is-right">低置信 (&lt;0.40)</th>
                  <th className="is-right">弃权</th>
                </tr>
              </thead>
              <tbody>
                {corpusSubs.map((s) => {
                  const share = totalChunks ? (Number(s.chunks) || 0) / totalChunks * 100 : 0
                  return (
                    <tr key={s.subject}>
                      <td>
                        <div className="v3-admin-badge-row">
                          <span className="is-strong">{s.subject}</span>
                          {!s.in_subject_pool ? <Badge tone="outline">池外/弃权</Badge> : null}
                        </div>
                      </td>
                      <td className="is-right is-tabular">{num(s.chunks)}</td>
                      <td>
                        <div className="v3-admin-q-progress">
                          <Progress value={(100 * (Number(s.chunks) || 0)) / maxChunks} gradient height={6} />
                          <span>{share.toFixed(1)}%</span>
                        </div>
                      </td>
                      <td className="is-right is-tabular">{pct(s.avg_confidence)}</td>
                      <td className="is-right is-tabular">{num(s.low_conf_chunks)}</td>
                      <td className="is-right is-tabular">{num(s.abstained_chunks)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
        {corpus && corpusSubs.length > 0 ? (
          <div className="v3-admin-q-table-note">
            占比条按本次最大块数归一化，右侧数字为占全库分块的比例；低置信阈值 0.40。
          </div>
        ) : null}
      </Card>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            icon={<Target size={16} />}
            title="学科词表对齐"
            sub="只读，未改动 documents.subject；「明确不归一 / 词表未登记」仍需人工确认。"
            actions={(
              <Badge tone={
                alignStatus === 'error'
                  ? 'danger'
                  : alignStatus === 'loading' || (alignStatus === 'ok' && !align)
                    ? 'outline'
                    : alignRows.length ? 'warning' : 'success'
              }>
                {alignStatus === 'loading' ? '加载中' : alignStatus === 'error' ? '未加载' : alignRows.length ? `${alignRows.length} 个分裂写法` : '无分裂'}
              </Badge>
            )}
          />
        </div>

        {alignStatus === 'loading' && !align ? (
          <div className="v3-admin-panel__body">
            <div style={{ display: 'grid', gap: 9 }}>
              <Skeleton height={12} width="62%" />
              <Skeleton height={36} radius={8} />
              <Skeleton height={36} radius={8} />
            </div>
          </div>
        ) : null}

        {alignStatus === 'error' ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<AlertCircle size={26} />}
              title="词表对齐数据未加载"
              text="接口 /api/quality/subject-alignment 无响应（后端未重启时也是这个提示）。"
              action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={loadAlign}>重试</Button>}
            />
          </div>
        ) : null}

        {alignStatus === 'ok' && align ? (
          <>
            <div className="v3-admin-q-align-summary">
              <span><b>{num(align.document_subjects)}</b>文档侧写法</span>
              <span><b>{num(align.unaligned_labels)}</b>无同名值</span>
              <span><b>{num(align.unaligned_documents)}</b>涉及文档</span>
              <span><b>{num(align.foldable_documents)}</b>可按口径折叠</span>
              <span><b>{num(align.not_indexed_documents)}</b>尚无分块</span>
            </div>
            {alignRows.length === 0 ? (
              <div className="v3-admin-panel__body">
                <Empty icon={<Target size={26} />} title="没有词表分裂" text="文档学科与分块学科完全同名。" />
              </div>
            ) : (
              <div className="v3-admin-table-wrap">
                <table className="v3-admin-table">
                  <thead>
                    <tr>
                      <th>文档侧写法</th>
                      <th className="is-right">文档数</th>
                      <th className="is-right">自带分块</th>
                      <th className="is-right">有块的文档</th>
                      <th className="is-right">未入库</th>
                      <th>口径</th>
                      <th>折叠目标</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alignRows.map((r) => {
                      const [label, tone] = ALIGN_KIND[r.kind] || [r.kind || '未分类', 'outline']
                      const targets = Array.isArray(r.target_chunks) ? r.target_chunks : []
                      return (
                        <tr key={r.subject}>
                          <td className="is-strong is-nowrap">{r.subject}</td>
                          <td className="is-right is-tabular">{num(r.documents)}</td>
                          <td className="is-right is-tabular">{num(r.own_chunks)}</td>
                          <td className="is-right is-tabular">{num(r.documents_with_chunks)}</td>
                          <td className="is-right is-tabular">{num(r.not_indexed)}</td>
                          <td><Badge tone={tone}>{label}</Badge></td>
                          <td className={targets.length ? undefined : 'is-muted'}>
                            {targets.length === 0
                              ? '—'
                              : targets.map((t) => `${t.subject} ${num(t.chunks)}`).join(' / ')}
                          </td>
                          <td className="is-wrap is-muted">{r.reason || '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {align.note ? <div className="v3-admin-q-table-note">{align.note}</div> : null}
          </>
        ) : null}
      </Card>

      <Dialog
        open={!!detail}
        title={detail ? `运行 #${detail.id}` : '运行详情'}
        sub={detail ? [detail.arm, fmtDateTime(detail.created_at)].filter(Boolean).join(' · ') : ''}
        onClose={() => setDetail(null)}
        wide
        footer={<Button variant="text" onClick={() => setDetail(null)}>关闭</Button>}
      >
        <RunDetail run={detail} />
      </Dialog>
    </div>
  )
}
