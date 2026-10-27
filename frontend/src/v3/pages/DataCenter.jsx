import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  errorsApi, kbApi, qualityApi, quizApi, request, systemApi, textbooksApi, wordsApi,
} from '../../api/client'
import {
  Alert, AnimatedNumber, Badge, Button, Card, CardHead, PageHeader, Ring,
  Skeleton, Spinner, Tile, cx,
} from '../ui'
import {
  Activity, AlertCircle, ArrowRight, BookOpen, ChevronRight, Clock, Database,
  FileText, Folder, Layers, LineChart, RefreshCw, Sparkles, Target, Type,
} from '../icons'
import '../styles/admin-core-v3.css'

/* ============================================================
   数据中心 / 管理总览（/admin/overview）

   每个数据域都绑定一个真实接口，失败时保留错误原文，不吞异常。
   页面同时汇总全站真实规模，并给管理员一条最近的评测活动流。
   ============================================================ */

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : null)

const pct = (v) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(1)}%`
}

const fmtTime = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

const KIND_LABEL = {
  recognition_policy: '识别口径',
  recognition: '识别精度',
  qa: '答疑模型',
  corpus_probe: '语料体检',
  doc_lock: '文档诊断',
}

function buildTasks() {
  return [
    {
      key: 'health', domain: '后端服务', icon: Activity, to: null,
      endpoint: 'GET /api/health',
      load: () => systemApi.health(),
      summary: (d) => (d?.status ? `状态 ${d.status}` : '服务已响应'),
      count: () => null,
      unit: '',
    },
    {
      key: 'documents', domain: '文档知识库', icon: Folder, to: '/documents',
      endpoint: 'GET /api/kb/health',
      load: () => kbApi.health(),
      summary: (d) => {
        const total = num(d?.documents?.total) ?? 0
        const chunks = num(d?.chunks?.total) ?? 0
        const issues = Array.isArray(d?.issues) ? d.issues.length : 0
        return `${total} 篇文档 · ${chunks} 个分块${issues ? ` · ${issues} 个待修问题` : ''}`
      },
      count: (d) => num(d?.documents?.total) ?? 0,
      unit: '篇',
    },
    {
      key: 'quiz', domain: '题库', icon: BookOpen, to: '/quiz',
      endpoint: 'GET /api/quiz/stats',
      load: () => quizApi.stats(),
      summary: (d) => `可作答 ${num(d?.answerable_total) ?? 0} 题 · 可见 ${num(d?.visible_total ?? d?.total_questions) ?? 0} 题`,
      count: (d) => num(d?.visible_total ?? d?.total_questions) ?? 0,
      unit: '题',
    },
    {
      key: 'errors', domain: '错题库', icon: FileText, to: '/quiz?tab=review',
      endpoint: 'GET /api/errors/stats',
      load: () => errorsApi.stats(),
      summary: (d) => `活跃 ${num(d?.active_errors) ?? 0} 道 · 今日待复习 ${num(d?.due_errors) ?? 0} 道`,
      count: (d) => num(d?.active_errors) ?? 0,
      unit: '道',
    },
    {
      key: 'words', domain: '单词', icon: Type, to: '/words',
      endpoint: 'GET /api/words/stats',
      load: () => wordsApi.stats(),
      // 后端字段是 due_today；保留 due 兼容旧快照
      summary: (d) => `今日待复习 ${num(d?.due_today ?? d?.due) ?? 0} 个 · 已掌握 ${num(d?.mastered) ?? 0} 个`,
      count: (d) => num(d?.total) ?? 0,
      unit: '词',
    },
    {
      key: 'textbooks', domain: '教材目录', icon: Layers, to: '/textbooks',
      endpoint: 'GET /api/textbooks/stats/overview',
      load: () => textbooksApi.stats(),
      summary: (d) => `覆盖 ${Array.isArray(d?.by_subject) ? d.by_subject.length : 0} 个科目`,
      count: (d) => num(d?.total) ?? 0,
      unit: '本',
    },
    {
      key: 'schools', domain: '院校数据', icon: Target, to: '/kaoyan/schools',
      endpoint: 'GET /api/kaoyan/schools',
      load: () => request('/kaoyan/schools', { params: { page: 1, page_size: 1 } }),
      summary: (d) => `院校库 ${num(d?.total) ?? 0} 所 · 采集范围可在「院校采集源」调整`,
      count: (d) => num(d?.total) ?? 0,
      unit: '所',
    },
    {
      key: 'codebank', domain: '复试代码题库', icon: Database, to: '/codebank',
      endpoint: 'GET /api/codebank/subjects',
      load: () => request('/codebank/subjects'),
      summary: (d) => {
        const list = Array.isArray(d) ? d : []
        const total = list.reduce((n, s) => n + (Number(s?.question_count) || 0), 0)
        return `${list.length} 个科目 · ${total} 道题`
      },
      count: (d) => (Array.isArray(d) ? d.length : 0),
      unit: '科',
    },
  ]
}

function MetricTile({ icon, label, value, unit, hint, warn }) {
  return (
    <Tile className={cx('v3-admin-stat', warn && 'is-warn')}>
      <span className="v3-tile__label">{icon}{label}</span>
      <span className="v3-tile__value">
        {value == null ? (
          <span className="v3-admin-nil">—</span>
        ) : (
          <>
            <AnimatedNumber value={value} format={(n) => Math.round(n).toLocaleString('zh-CN')} />
            <em>{unit}</em>
          </>
        )}
      </span>
      <span className="v3-tile__hint">{hint}</span>
    </Tile>
  )
}

export default function DataCenter() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [checkedAt, setCheckedAt] = useState('')
  const [nodes, setNodes] = useState({ status: 'loading', list: [], error: '' })
  const [activity, setActivity] = useState({ status: 'loading', items: [], error: '' })

  const run = useCallback(async () => {
    setLoading(true)
    setNodes((n) => ({ ...n, status: 'loading' }))
    setActivity((a) => ({ ...a, status: 'loading' }))

    /* 算力节点与评测活动互不阻塞：任何一个接口挂了，其它区块仍可用。 */
    systemApi.computeNodes()
      .then((d) => setNodes({ status: 'ok', list: Array.isArray(d?.nodes) ? d.nodes : [], error: '' }))
      .catch((e) => setNodes({ status: 'error', list: [], error: e?.message || '请求失败' }))

    qualityApi.evalRuns({ limit: 6 })
      .then((d) => setActivity({ status: 'ok', items: (d?.items || []).slice(0, 6), error: '' }))
      .catch((e) => setActivity({ status: 'error', items: [], error: e?.message || '请求失败' }))

    const tasks = buildTasks()
    const results = await Promise.all(tasks.map(async (t) => {
      const started = performance.now()
      try {
        const data = await t.load()
        return { ...t, data, ok: true, ms: Math.round(performance.now() - started), error: '' }
      } catch (e) {
        return {
          ...t, data: null, ok: false,
          ms: Math.round(performance.now() - started),
          error: e?.message || '请求失败',
        }
      }
    }))
    setRows(results)
    setCheckedAt(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
    setLoading(false)
  }, [])

  useEffect(() => { run() }, [run])

  const okCount = rows.filter((r) => r.ok).length
  const failedCount = rows.length - okCount

  const getRow = (key) => rows.find((r) => r.key === key)
  const dataOf = (key) => {
    const r = getRow(key)
    return r?.ok ? r.data : null
  }
  const hintOf = (key, okText) => {
    const r = getRow(key)
    if (!r) return loading ? '正在检查…' : '暂无检查结果'
    return r.ok ? okText : '接口异常，详见接口明细'
  }

  const docs = dataOf('documents')
  const quiz = dataOf('quiz')
  const errs = dataOf('errors')
  const words = dataOf('words')
  const textbooks = dataOf('textbooks')
  const schools = dataOf('schools')

  const docTotal = docs ? num(docs.documents?.total) : null
  const docChunks = docs ? num(docs.chunks?.total) ?? 0 : 0
  const docIssues = docs && Array.isArray(docs.issues) ? docs.issues.length : 0
  const quizTotal = quiz ? num(quiz.visible_total ?? quiz.total_questions) : null
  const quizAnswerable = quiz ? num(quiz.answerable_total) ?? 0 : 0
  const errorTotal = errs ? num(errs.active_errors) : null
  const errorDue = errs ? num(errs.due_errors) ?? 0 : 0
  const wordTotal = words ? num(words.total) : null
  const wordDue = words ? num(words.due_today ?? words.due) ?? 0 : 0
  const wordMastered = words ? num(words.mastered) ?? 0 : 0
  const bookTotal = textbooks ? num(textbooks.total) : null
  const bookSubjects = textbooks && Array.isArray(textbooks.by_subject) ? textbooks.by_subject.length : 0
  const schoolTotal = schools ? num(schools.total) : null

  const heroTitle = loading
    ? '正在逐项检查接口…'
    : rows.length === 0
      ? '尚未执行检查'
      : failedCount
        ? `${failedCount} 个接口异常`
        : '全部接口正常'

  return (
    <div className="v3-admin-page">
      <PageHeader
        eyebrow="ADMIN · 数据连通"
        title="数据中心"
        sub="每个数据域的真实接口、可用数量与健康状态；页面为什么是空的，看这里最快。"
        actions={(
          <div className="v3-row" style={{ alignItems: 'center', gap: 12 }}>
            {checkedAt ? <span className="v3-caption">最近检查 {checkedAt}</span> : null}
            <Button
              variant="outline"
              icon={<RefreshCw size={15} />}
              loading={loading}
              onClick={run}
            >
              {loading ? '检查中…' : '重新检查'}
            </Button>
          </div>
        )}
      />

      <Tile variant="gradient" className="v3-admin-dc-hero">
        <div className="v3-admin-dc-hero__copy">
          <span className="v3-admin-dc-hero__eyebrow"><Sparkles size={13} /> 数据连通性巡检</span>
          <h2 className="v3-admin-dc-hero__title">{heroTitle}</h2>
          <p className="v3-admin-dc-hero__sub">
            {loading
              ? '依次请求每个数据域的统计接口，单项失败不会中断其它检查。'
              : `已连通 ${okCount} / ${rows.length} 个数据域。异常项保留错误原文，便于对照后端日志。`}
          </p>
          <div className="v3-admin-dc-hero__meta">
            <span className="v3-caption" style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
              <span className={cx('v3-admin-dot', !loading && (failedCount ? 'is-bad' : 'is-ok'))} />
              {loading ? '检查进行中' : failedCount ? '需要关注' : '数据就绪'}
            </span>
            {!loading && rows.length > 0 ? (
              <span className="v3-caption">异常 {failedCount} 项 · 正常 {okCount} 项</span>
            ) : null}
          </div>
        </div>
        <div className="v3-admin-dc-hero__ring">
          <Ring value={rows.length ? (okCount / rows.length) * 100 : 0} size={132} stroke={10}>
            <div className="v3-admin-dc-ring-center">
              <strong>{rows.length ? `${okCount}/${rows.length}` : '—'}</strong>
              <span>数据域连通</span>
            </div>
          </Ring>
        </div>
      </Tile>

      <div className="v3-admin-stats">
        <MetricTile
          icon={<Folder size={14} />}
          label="文档知识库"
          value={docTotal}
          unit="篇"
          hint={hintOf('documents', `${docChunks} 个分块${docIssues ? ` · ${docIssues} 个待修` : ' · 状态良好'}`)}
        />
        <MetricTile
          icon={<BookOpen size={14} />}
          label="题库总量"
          value={quizTotal}
          unit="题"
          hint={hintOf('quiz', `可作答 ${quizAnswerable.toLocaleString('zh-CN')} 题`)}
        />
        <MetricTile
          icon={<FileText size={14} />}
          label="活跃错题"
          value={errorTotal}
          unit="道"
          hint={hintOf('errors', `今日待复习 ${errorDue.toLocaleString('zh-CN')} 道`)}
        />
        <MetricTile
          icon={<Type size={14} />}
          label="单词词库"
          value={wordTotal}
          unit="词"
          hint={hintOf('words', `今日待复习 ${wordDue.toLocaleString('zh-CN')} · 已掌握 ${wordMastered.toLocaleString('zh-CN')}`)}
        />
        <MetricTile
          icon={<Layers size={14} />}
          label="教材目录"
          value={bookTotal}
          unit="本"
          hint={hintOf('textbooks', `覆盖 ${bookSubjects} 个科目`)}
        />
        <MetricTile
          icon={<Target size={14} />}
          label="院校数据"
          value={schoolTotal}
          unit="所"
          hint={hintOf('schools', '院校库可直接用于择校对比')}
        />
      </div>

      <div className="v3-admin-dc-grid">
        {loading && rows.length === 0
          ? Array.from({ length: 8 }).map((_, i) => (
            <div className="v3-admin-dc-domain" key={`sk-${i}`} aria-hidden="true">
              <div className="v3-admin-dc-skeleton">
                <Skeleton width="46%" height={14} />
                <Skeleton width="62%" height={32} />
                <Skeleton width="90%" height={12} />
                <Skeleton width="100%" height={10} />
              </div>
            </div>
          ))
          : rows.map((r) => {
            const Icon = r.icon
            const count = r.ok ? r.count(r.data) : null
            return (
              <div className={cx('v3-admin-dc-domain', !r.ok && 'is-error')} key={r.key}>
                <div className="v3-admin-dc-domain__head">
                  <span className="v3-admin-dc-domain__icon"><Icon size={17} /></span>
                  <span className="v3-admin-dc-domain__name">{r.domain}</span>
                  <span
                    className={cx('v3-admin-dot', 'v3-admin-dc-domain__dot', r.ok ? 'is-ok' : 'is-bad')}
                    title={r.ok ? '接口正常' : '接口异常'}
                  />
                </div>
                <div className="v3-admin-dc-domain__value">
                  {count == null ? <span className="v3-admin-nil">—</span> : (
                    <>
                      {Number(count).toLocaleString('zh-CN')}
                      {r.unit ? <small>{r.unit}</small> : null}
                    </>
                  )}
                </div>
                <div className="v3-admin-dc-domain__desc">
                  {r.ok ? r.summary(r.data) : (loading ? '正在检查…' : r.error)}
                </div>
                <div className="v3-admin-dc-domain__foot">
                  <code className="v3-admin-endpoint" title={r.endpoint}>{r.endpoint}</code>
                  {r.to ? (
                    <Link className="v3-admin-dc-link" to={r.to} aria-label={`打开${r.domain}`}>
                      打开<ChevronRight size={13} />
                    </Link>
                  ) : null}
                </div>
              </div>
            )
          })}
      </div>

      <div className="v3-admin-dc-lower">
        <Card className="v3-admin-panel">
          <div className="v3-admin-panel__head">
            <CardHead
              title="外部算力节点"
              sub="OCR / 重排 / 本地模型跑在算力节点上；离线时自动走降级链，不影响主站可用。"
            />
          </div>
          <div className="v3-admin-table-wrap">
            <table className="v3-admin-table">
              <thead>
                <tr><th>节点</th><th>状态</th><th className="is-right">延迟</th><th>离线时</th></tr>
              </thead>
              <tbody>
                {nodes.status === 'loading' ? (
                  <tr>
                    <td colSpan={4} className="v3-admin-table__empty">
                      <span className="v3-row" style={{ justifyContent: 'center', gap: 8 }}>
                        <Spinner size={16} /> 探测中…
                      </span>
                    </td>
                  </tr>
                ) : null}
                {nodes.status === 'error' ? (
                  <tr>
                    <td colSpan={4} className="v3-admin-table__empty">
                      <strong>节点探测失败</strong>
                      {nodes.error}
                    </td>
                  </tr>
                ) : null}
                {nodes.status === 'ok' && nodes.list.length === 0 ? (
                  <tr><td colSpan={4} className="v3-admin-table__empty">未配置外部算力节点，全部任务走本机。</td></tr>
                ) : null}
                {nodes.status === 'ok' ? nodes.list.map((n) => (
                  <tr key={n.key}>
                    <td className="is-strong">{n.label}</td>
                    <td>
                      <Badge tone={n.status === 'online' ? 'success' : 'warning'}>
                        {n.status === 'online' ? '在线' : '已降级'}
                      </Badge>
                    </td>
                    <td className="is-right is-tabular is-muted">
                      {n.latency_ms == null ? '—' : `${n.latency_ms} ms`}
                    </td>
                    <td className="is-muted">{n.status === 'online' ? '—' : (n.fallback || '—')}</td>
                  </tr>
                )) : null}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="v3-admin-panel">
          <div className="v3-admin-panel__head">
            <CardHead
              title="最近评测活动"
              sub="来自 eval_runs 的真实运行记录"
              actions={(
                <Link className="v3-admin-dc-link" to="/admin/quality">
                  全部评测<ArrowRight size={13} />
                </Link>
              )}
            />
          </div>
          <div className="v3-admin-activity">
            {activity.status === 'loading' && activity.items.length === 0 ? (
              <>
                {[0, 1, 2].map((i) => (
                  <div className="v3-admin-activity__row" key={i} aria-hidden="true">
                    <span className="v3-admin-activity__icon"><LineChart size={15} /></span>
                    <span className="v3-admin-activity__main">
                      <Skeleton width="70%" height={12} />
                      <Skeleton width="46%" height={9} style={{ marginTop: 4 }} />
                    </span>
                  </div>
                ))}
              </>
            ) : null}
            {activity.status === 'error' && activity.items.length === 0 ? (
              <div className="v3-admin-activity__empty">
                <div className="v3-caption" style={{ marginBottom: 6 }}>
                  <AlertCircle size={14} style={{ verticalAlign: '-3px', marginRight: 5 }} />
                  评测记录加载失败
                </div>
                <div className="v3-caption" style={{ color: 'var(--v3-danger)' }}>{activity.error}</div>
              </div>
            ) : null}
            {activity.status === 'ok' && activity.items.length === 0 ? (
              <div className="v3-admin-activity__empty">
                <div className="v3-caption">还没有评测运行记录。</div>
              </div>
            ) : null}
            {activity.items.map((r) => (
              <Link className="v3-admin-activity__row" to="/admin/quality" key={r.id}>
                <span className="v3-admin-activity__icon"><LineChart size={15} /></span>
                <span className="v3-admin-activity__main">
                  <span className="v3-admin-activity__title">
                    {KIND_LABEL[r.kind] || r.kind || '未知类型'} · {r.arm || '未命名口径'}
                  </span>
                  <span className="v3-admin-activity__meta">
                    #{r.id} · 主指标 {pct(r.primary_metric)} · {(num(r.n_samples) ?? 0).toLocaleString('zh-CN')} 样本 · {fmtTime(r.created_at)}
                  </span>
                </span>
                <ChevronRight size={14} />
              </Link>
            ))}
          </div>
        </Card>
      </div>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            title="接口明细"
            sub="延迟为本机浏览器实测，仅用于判断连通性。"
          />
        </div>
        <div className="v3-admin-table-wrap">
          <table className="v3-admin-table">
            <thead>
              <tr><th>数据域</th><th>接口</th><th>状态</th><th className="is-right">延迟</th><th>说明</th></tr>
            </thead>
            <tbody>
              {loading && rows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="v3-admin-table__empty">
                    <span className="v3-row" style={{ justifyContent: 'center', gap: 8 }}>
                      <Spinner size={16} /> 接口检查中…
                    </span>
                  </td>
                </tr>
              ) : null}
              {rows.map((r) => (
                <tr key={r.key} className={r.ok ? undefined : 'v3-admin-row-error'}>
                  <td className="is-nowrap is-strong">{r.domain}</td>
                  <td><code className="v3-admin-mono">{r.endpoint}</code></td>
                  <td>
                    <Badge tone={r.ok ? 'success' : 'danger'}>{r.ok ? '正常' : '失败'}</Badge>
                  </td>
                  <td className="is-right is-tabular is-muted">{loading ? '—' : `${r.ms} ms`}</td>
                  <td className={cx('is-wrap', r.ok ? 'is-muted' : 'v3-admin-danger-text')}>
                    {r.ok ? r.summary(r.data) : r.error}
                  </td>
                </tr>
              ))}
              {!loading && rows.length === 0 ? (
                <tr><td colSpan={5} className="v3-admin-table__empty">没有可检查的接口</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      <Alert tone="info" icon={<Clock size={18} />}>
        <b>怎么用这张表：</b>
        某个页面显示「暂无数据」时，先看对应数据域的计数是否为 0。计数为 0 代表库内确实没有数据，
        需要去导入或录入；计数正常但页面空，才是页面筛选或接口参数的问题。
      </Alert>
    </div>
  )
}
