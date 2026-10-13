import React, { useEffect, useMemo, useState } from 'react'
import { qualityApi } from '../api/client'
import { Empty, Modal, Segmented } from '../components/UI'
import Chart from '../components/EChart'

/* 口径说明：本页所有数字都来自 eval_runs（脚本每次运行自动写一行）与库内聚合，
   没有一个是前端估出来的。识别侧 precision/recall 只在 147 条人工判分样本上成立，
   语料规模才是全库口径 —— 两者分栏展示，避免把样本指标当成全库指标读。 */
const KINDS = [
  { value: 'recognition_policy', label: '识别口径' },
  { value: 'recognition', label: '识别精度' },
  { value: 'qa', label: '答疑模型' },
  { value: 'corpus_probe', label: '语料体检' },
]

const pct = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : `${(v * 100).toFixed(1)}%`)
const num = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('zh-CN'))

/* 指标名 → 展示文案 + 越高/越低越好 */
const METRIC_LABEL = {
  prec: ['学科池 Precision', 'high'],
  rec: ['域内 Recall', 'high'],
  f1: ['Macro F1', 'high'],
  cov: ['覆盖率', 'high'],
  pollute: ['域外污染率', 'low'],
}

function toneFor(metricKey, v) {
  const higherBetter = (METRIC_LABEL[metricKey] || [])[1] !== 'low'
  if (v === null || v === undefined) return 'chip'
  const good = higherBetter ? v >= 0.9 : v <= 0.2
  const bad = higherBetter ? v < 0.7 : v > 0.5
  return `chip ${good ? 'ok' : bad ? 'bad' : 'mid'}`
}

export default function QualityDashboard() {
  const [kind, setKind] = useState('recognition_policy')
  const [runs, setRuns] = useState([])
  const [corpus, setCorpus] = useState(null)
  const [align, setAlign] = useState(null)
  const [alignError, setAlignError] = useState(false)
  const [detail, setDetail] = useState(null)
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    let alive = true
    Promise.all([qualityApi.evalRuns({ limit: 200 }), qualityApi.corpus()])
      .then(([r, c]) => {
        if (!alive) return
        setRuns(r.items || [])
        setCorpus(c)
        setStatus('ok')
      })
      .catch(() => alive && setStatus('error'))
    return () => { alive = false }
  }, [])

  // 词表对齐单独取：它挂了不该把整页指标一起拖成「后端未响应」
  useEffect(() => {
    let alive = true
    qualityApi.subjectAlignment()
      .then((d) => alive && setAlign(d))
      .catch(() => alive && setAlignError(true))
    return () => { alive = false }
  }, [])

  const byKind = useMemo(() => runs.filter((r) => r.kind === kind), [runs, kind])

  // 趋势按时间正序（evalRuns 是倒序返回的）
  const trend = useMemo(() => byKind.slice().reverse(), [byKind])
  const option = useMemo(() => ({
    grid: { left: 52, right: 20, top: 30, bottom: 40 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: trend.map((r) => (r.created_at || '').slice(5, 16).replace('T', ' ')),
      axisLabel: { rotate: 20 },
    },
    yAxis: { type: 'value', min: 0, max: 1 },
    series: [{
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: trend.map((r) => (r.primary_metric === null ? null : r.primary_metric)),
      areaStyle: { opacity: 0.12 },
      lineStyle: { width: 2 },
    }],
  }), [trend])

  return (
    <div className="ky-page">
      <h1>评测与数据质量</h1>
      <p style={{ color: 'var(--ink-3)', marginBottom: '18px' }}>
        识别口径、答疑模型、语料体检的历史运行与指标。数字直接来自 <code>eval_runs</code> 表。
      </p>
      <CorpusTiles corpus={corpus} runs={runs} />

      <div className="card" style={{ marginTop: '18px' }}>
        <div className="card-header">
          <span className="card-title">指标趋势</span>
          <Segmented options={KINDS} value={kind} onChange={setKind} />
        </div>
        {status === 'error' && <Empty title="后端未响应" text="请确认服务已启动（/api/quality）" />}
        {status !== 'error' && trend.length === 0 && (
          <Empty title="还没有该类型的运行记录" text="跑一次评测脚本即可自动入库" />
        )}
        {trend.length > 0 && <Chart option={option} style={{ height: '300px' }} />}
      </div>

      <PolicyTable runs={runs} />

      <div className="card" style={{ marginTop: '18px' }}>
        <div className="card-header"><span className="card-title">运行历史</span></div>
        <div className="table-container">
          <table className="table table-striped">
            <thead>
              <tr><th>#</th><th>类型</th><th>口径/模型</th><th>主指标</th><th>样本</th><th>时间</th><th /></tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{(KINDS.find((k) => k.value === r.kind) || {}).label || r.kind}</td>
                  <td style={{ maxWidth: 260 }}>{r.arm || '—'}</td>
                  <td>{pct(r.primary_metric)}</td>
                  <td>{num(r.n_samples)}</td>
                  <td>{(r.created_at || '').slice(0, 16).replace('T', ' ')}</td>
                  <td><button className="btn btn-sm" onClick={() => setDetail(r)}>详情</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <CorpusTable corpus={corpus} />

      <SubjectAlignment data={align} error={alignError} />

      <Modal open={!!detail} title={detail ? `运行 #${detail.id} · ${detail.arm || ''}` : ''} onClose={() => setDetail(null)}>
        <RunDetail run={detail} />
      </Modal>
    </div>
  )
}

function CorpusTiles({ corpus, runs }) {
  const policy = runs.find((r) => r.kind === 'recognition_policy')
  const [latest, setLatest] = useState(null)
  useEffect(() => {
    if (!policy) return
    qualityApi.evalRun(policy.id).then(setLatest).catch(() => {})
  }, [policy])
  const p = ((latest && latest.metrics) || {}).policies || {}
  // 只认「生产采用」这一行。以前写成 `|| Object.values(p).pop()`：没有生产口径时
  // 会随手抓最后一个候选策略冒充生产指标，屏幕上是一个来路不明的数字。
  const prod = p['生产采用']
  // 样本数取自 eval_runs.n_samples，不硬编码 —— 硬编码的「147 样本」在换数据集后
  // 会继续显示 147，等于给新数字贴上旧口径的标签。
  const nSamples = (latest && latest.run && latest.run.n_samples) ?? policy?.n_samples ?? null
  // ghost_index：状态写着 indexed、库里却一块都没有（列表页显示「已入库」，RAG 搜不到）
  const ghost = corpus && corpus.ghost_index ? corpus.ghost_index.indexed_without_chunks : null
  return (
    <div className="stat-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
      <div className="stat-card">
        <b>{prod ? pct(prod.prec) : '—'}</b>
        <span>学科池 Precision{nSamples === null ? '（无生产口径记录）' : `（${num(nSamples)} 样本）`}</span>
      </div>
      <div className="stat-card"><b>{prod ? pct(prod.rec) : '—'}</b><span>域内 Recall</span></div>
      <div className="stat-card"><b>{prod ? pct(prod.pollute) : '—'}</b><span>域外污染率</span></div>
      <div className="stat-card"><b>{num(corpus && corpus.total_chunks)}</b><span>语料块总数</span></div>
      <div className="stat-card"><b>{pct(corpus && corpus.abstained_rate)}</b><span>弃权占比</span></div>
      <div className="stat-card">
        <b style={ghost ? { color: 'var(--warn, #d97706)' } : undefined}>{num(ghost)}</b>
        <span>「已入库」但零分块</span>
      </div>
    </div>
  )
}

/* 识别口径对照表：把脚本里的候选策略原样列出，采用行高亮、否决行标灰。 */
function PolicyTable({ runs }) {
  const [m, setM] = useState(null)
  const target = runs.find((r) => r.kind === 'recognition_policy')
  useEffect(() => {
    if (!target) return
    qualityApi.evalRun(target.id).then((r) => setM(r.metrics || {})).catch(() => {})
  }, [target])
  if (!m || !m.policies) return null
  const rows = Object.entries(m.policies)
  const rejected = Object.entries(m.rejected || {})
  return (
    <div className="card" style={{ marginTop: '18px' }}>
      <div className="card-header"><span className="card-title">识别口径对照（同一样本、同一打分）</span></div>
      <div className="table-container">
        <table className="table">
          <thead>
            <tr><th>口径</th>{Object.keys(METRIC_LABEL).map((k) => <th key={k}>{METRIC_LABEL[k][0]}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(([name, v]) => (
              <tr key={name} style={name === '生产采用' ? { background: 'var(--surface-2)', fontWeight: 600 } : undefined}>
                <td>{name}</td>
                {Object.keys(METRIC_LABEL).map((k) => (
                  <td key={k}><span className={toneFor(k, v[k])}>{pct(v[k])}</span></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rejected.length > 0 && (
        <p style={{ color: 'var(--ink-3)', fontSize: '13px', marginTop: '10px' }}>
          已实测否决：{rejected.map(([k, why]) => `${k} — ${why}`).join('；')}
        </p>
      )}
    </div>
  )
}

function CorpusTable({ corpus }) {
  if (!corpus || !corpus.subjects) return null
  const subs = corpus.subjects
  const max = Math.max(1, ...subs.map((s) => s.chunks))
  return (
    <div className="card" style={{ marginTop: '18px' }}>
      <div className="card-header">
        <span className="card-title">分学科体检（全库 {num(corpus.total_chunks)} 块 / {num(corpus.total_documents)} 篇）</span>
      </div>
      <div className="table-container">
        <table className="table table-striped">
          <thead>
            <tr><th>学科</th><th>块数</th><th>占比</th><th>平均置信</th><th>低置信(&lt;0.40)</th><th>弃权</th></tr>
          </thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.subject}>
                <td>
                  {s.subject}
                  {!s.in_subject_pool && <span className="chip" style={{ marginLeft: 6 }}>池外/弃权</span>}
                </td>
                <td>{num(s.chunks)}</td>
                <td>
                  <div style={{ background: 'var(--surface-2)', borderRadius: 4, height: 8, width: 120 }}>
                    <div style={{ background: 'var(--accent)', height: 8, borderRadius: 4, width: `${(100 * s.chunks) / max}%` }} />
                  </div>
                </td>
                <td>{pct(s.avg_confidence)}</td>
                <td>{num(s.low_conf_chunks)}</td>
                <td>{num(s.abstained_chunks)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* 学科词表对齐（docx/16 §1.5-E）。
   为什么要有这张表：documents.subject 的写法比 knowledge_chunks.subject 多，
   「数模电」「公共课-数学」「408」这些在分块侧没有同名值，按学科名等值关联的
   每个入口都会把这些文档算成 0 块 —— 资料页选「数学」看不到 31 篇「公共课-数学」。
   折叠只在查询层发生，库里标签一个字没改；所以每一行都必须把「折叠后连不连得上」
   写清楚：kind=not_aliased/unknown_mapping 就是要人批的，不粉饰成已解决。 */
const ALIGN_KIND = {
  alias_folded: ['别名折叠', 'ok'],
  combined_expanded: ['合并口径展开', 'ok'],
  not_aliased: ['明确不归一', 'bad'],
  unknown_mapping: ['词表未登记', 'bad'],
}

function SubjectAlignment({ data, error }) {
  if (error) return <Empty title="词表对齐数据未加载" text="接口 /api/quality/subject-alignment 无响应（后端未重启时也是这个提示）" />
  if (!data) return null
  const rows = data.rows || []
  return (
    <div className="card" style={{ marginTop: '18px' }}>
      <div className="card-header">
        <span className="card-title">学科词表对齐（只读，未改动 documents.subject）</span>
      </div>
      <p style={{ color: 'var(--ink-3)', fontSize: '13px', margin: '0 16px 10px' }}>
        文档侧 {num(data.document_subjects)} 个写法中，{num(data.unaligned_labels)} 个在分块侧没有同名值，
        涉及 {num(data.unaligned_documents)} 篇；其中可按口径折叠 {num(data.foldable_documents)} 篇，
        另有 {num(data.not_indexed_documents)} 篇还没有可检索的分块。{data.note || ''}
      </p>
      {rows.length === 0 ? (
        <Empty title="没有词表分裂" text="文档学科与分块学科完全同名" />
      ) : (
        <div className="table-container">
          <table className="table table-striped">
            <thead>
              <tr>
                <th>文档侧写法</th><th>文档数</th><th>自带分块</th><th>有块的文档</th>
                <th>未入库</th><th>口径</th><th>折叠目标</th><th>说明</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const [label, tone] = ALIGN_KIND[r.kind] || [r.kind, 'chip']
                return (
                  <tr key={r.subject}>
                    <td>{r.subject}</td>
                    <td>{num(r.documents)}</td>
                    <td>{num(r.own_chunks)}</td>
                    <td>{num(r.documents_with_chunks)}</td>
                    <td>{num(r.not_indexed)}</td>
                    <td><span className={`chip ${tone}`}>{label}</span></td>
                    <td>
                      {(r.target_chunks || []).length === 0 ? '—'
                        : r.target_chunks.map((t) => `${t.subject} ${num(t.chunks)}`).join(' / ')}
                    </td>
                    <td style={{ maxWidth: 320, color: 'var(--ink-3)', fontSize: 12 }}>{r.reason}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function RunDetail({ run }) {
  const [full, setFull] = useState(null)
  useEffect(() => {
    if (!run) return
    setFull(null)
    qualityApi.evalRun(run.id).then(setFull).catch(() => {})
  }, [run])
  if (!run) return null
  const m = (full && full.metrics) || {}
  return (
    <div>
      <p style={{ color: 'var(--ink-3)', fontSize: '13px' }}>
        数据集指纹 <code>{run.dataset_fingerprint || '—'}</code> · 样本 {num(run.n_samples)} ·
        报告 <code>{run.report_path || '—'}</code>
      </p>
      {run.notes && <p style={{ fontSize: '13px' }}>{run.notes}</p>}
      <pre style={{ maxHeight: '46vh', overflow: 'auto', fontSize: 12, background: 'var(--surface-2)', padding: 12, borderRadius: 8 }}>
        {JSON.stringify(m, null, 1)}
      </pre>
    </div>
  )
}
