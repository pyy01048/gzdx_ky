import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { request } from '../../api/client'
import { kaoyanApi } from '../../api/kaoyanApi'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, Badge, Button, Card, CardHead, Empty, IconButton, Input, PageHeader,
  Select, Skeleton, Spinner, Textarea, toastErr, toastOk, toastWarn, cx,
} from '../ui'
import {
  AlertCircle, BookOpen, Calendar, Check, CheckCircle2, Clock, GraduationCap,
  RefreshCw, Shield, Sparkles, Trophy, X,
} from '../icons'

/* ============================================================================
 * 经验卡审核（AdminExperiences）
 *
 * 仅 admin 角色可访问。按状态（待审核 / 已审核 / 已驳回）分标签页浏览
 * 经验卡，可执行批准 / 驳回操作。
 * 数据源：GET  /api/experiences?status=pending|approved|rejected
 *         POST /api/experiences/{id}/approve
 *         POST /api/experiences/{id}/reject
 * ========================================================================== */

const PAGE_SIZE = 10

const STATUS_TABS = [
  { key: 'pending', label: '待审核', tone: 'warning', icon: Clock },
  { key: 'approved', label: '已审核', tone: 'success', icon: CheckCircle2 },
  { key: 'rejected', label: '已驳回', tone: 'danger', icon: X },
]

const STATUS_LABEL = {
  pending: '待审核',
  approved: '已审核',
  rejected: '已驳回',
}

function fmtDate(s) {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/* 依据 evidence_json 渲染为键值对列表；后端可能返回对象或字符串，均容错 */
function evidenceEntries(ev) {
  if (!ev) return []
  if (typeof ev === 'string') return ev.trim() ? [['详情', ev]] : []
  if (Array.isArray(ev)) return ev.filter(Boolean).map((v, i) => [`依据 ${i + 1}`, String(v)])
  if (typeof ev === 'object') {
    return Object.entries(ev)
      .filter(([, v]) => v != null && String(v).trim() !== '')
      .map(([k, v]) => [k, String(v)])
  }
  return []
}

export default function AdminExperiences() {
  const { user, status: authStatus } = useAuth()

  const [tab, setTab] = useState('pending')
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [page, setPage] = useState(1)
  const [schoolFilter, setSchoolFilter] = useState('')
  const [actingId, setActingId] = useState(null)
  const [rejecting, setRejecting] = useState(null) // { id, reason }

  const [schools, setSchools] = useState([])
  const [schoolsLoading, setSchoolsLoading] = useState(false)

  const reqRef = useRef(0)

  /* 院校候选：进入页面时拉一次，供筛选 */
  const loadSchools = useCallback(async () => {
    setSchoolsLoading(true)
    try {
      const d = await kaoyanApi.schools({ page_size: 200, page: 1 })
      const items = Array.isArray(d) ? d : (d?.items || [])
      setSchools(items)
    } catch {
      setSchools([])
    } finally {
      setSchoolsLoading(false)
    }
  }, [])

  const load = useCallback(async () => {
    const requestId = ++reqRef.current
    setLoading(true)
    setError('')
    try {
      const params = { status: tab, page, page_size: PAGE_SIZE }
      if (schoolFilter) params.school_id = schoolFilter
      const d = await request('/experiences', { params })
      if (requestId !== reqRef.current) return
      const items = Array.isArray(d) ? d : (d?.items || [])
      setRows(items)
      setTotal(Array.isArray(d) ? items.length : (Number(d?.total) || items.length))
    } catch (e) {
      if (requestId === reqRef.current) setError(e?.message || '经验卡加载失败')
      setRows([])
      setTotal(0)
    } finally {
      if (requestId === reqRef.current) setLoading(false)
    }
  }, [tab, page, schoolFilter])

  useEffect(() => { loadSchools() }, [loadSchools])
  useEffect(() => { load() }, [load])

  const schoolMap = useMemo(() => {
    const m = {}
    schools.forEach((s) => { m[s.id] = s.name })
    return m
  }, [schools])

  const schoolOptions = useMemo(
    () => [{ value: '', label: '全部院校' }, ...schools.map((s) => ({ value: String(s.id), label: s.name }))],
    [schools],
  )

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const curPage = Math.min(page, totalPages)

  const switchTab = (next) => {
    setTab(next)
    setPage(1)
  }

  const applySchoolFilter = (v) => {
    setSchoolFilter(v)
    setPage(1)
  }

  const refresh = async () => {
    await load()
    toastOk('已刷新审核列表')
  }

  const approve = async (id) => {
    setActingId(id)
    try {
      await request(`/experiences/${id}/approve`, { method: 'POST' })
      toastOk(`经验卡 #${id} 已批准，已纳入 RAG 知识检索`)
      // 批准后从待审核列表移除；如不在当前页则刷新
      setRows((prev) => prev.filter((r) => r.id !== id))
      setTotal((prev) => Math.max(0, prev - 1))
    } catch (e) {
      toastErr(e?.message || '批准失败，请稍后重试')
    } finally {
      setActingId(null)
    }
  }

  const submitReject = async () => {
    if (!rejecting) return
    const { id, reason } = rejecting
    setActingId(id)
    try {
      await request(`/experiences/${id}/reject`, {
        method: 'POST',
        body: reason.trim() ? { reason: reason.trim() } : undefined,
      })
      toastWarn(`经验卡 #${id} 已驳回`)
      setRows((prev) => prev.filter((r) => r.id !== id))
      setTotal((prev) => Math.max(0, prev - 1))
      setRejecting(null)
    } catch (e) {
      toastErr(e?.message || '驳回失败，请稍后重试')
    } finally {
      setActingId(null)
    }
  }

  const header = (
    <PageHeader
      eyebrow="ADMIN · 经验卡审核"
      title="经验卡审核"
      sub="审核已上岸用户提交的经验卡 · 批准后纳入 RAG 知识检索"
      actions={(
        <IconButton label="刷新列表" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading} />
      )}
    />
  )

  /* ---------- 鉴权 ---------- */
  if (authStatus === 'loading') {
    return (
      <div className="v3-stack admin-exp-page">
        {header}
        <Card><Skeleton height={120} /></Card>
      </div>
    )
  }

  if (!user || user.role !== 'admin') {
    return (
      <div className="v3-stack admin-exp-page">
        {header}
        <Alert tone="danger" icon={<Shield size={18} />}>
          <p>仅管理员（admin 角色）可访问经验卡审核页面。当前账号{user ? `角色为 ${user.role || '未知'}` : '未登录'}。</p>
        </Alert>
        <Card>
          <Empty
            icon={<Shield size={26} />}
            title="权限不足"
            text="经验卡审核功能仅对管理员开放。"
          />
        </Card>
      </div>
    )
  }

  /* ---------- 驳回弹层 ---------- */
  const rejectDialog = rejecting ? (
    <div className="admin-exp-modal" role="dialog" aria-modal="true" aria-labelledby="reject-title">
      <div className="admin-exp-modal__backdrop" onClick={() => setRejecting(null)} />
      <Card className="admin-exp-modal__card">
        <CardHead
          icon={<X size={17} />}
          title="驳回经验卡"
          sub={`将驳回经验卡 #${rejecting.id}，请填写驳回原因（可选）`}
        />
        <Textarea
          rows={3}
          placeholder="驳回原因，将反馈给提交者（可选）"
          value={rejecting.reason}
          onChange={(e) => setRejecting((prev) => ({ ...prev, reason: e.target.value }))}
          style={{ width: '100%' }}
          autoFocus
        />
        <div className="admin-exp-modal__actions">
          <Button
            variant="danger"
            icon={<X size={15} />}
            loading={actingId === rejecting.id}
            disabled={actingId === rejecting.id}
            onClick={submitReject}
          >
            确认驳回
          </Button>
          <Button variant="text" onClick={() => setRejecting(null)} disabled={actingId === rejecting.id}>取消</Button>
        </div>
      </Card>
    </div>
  ) : null

  /* ---------- 加载骨架 ---------- */
  if (loading && rows.length === 0) {
    return (
      <div className="v3-stack admin-exp-page">
        {header}
        <Card>
          <Skeleton height={44} />
        </Card>
        <div className="v3-stack">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} variant="tonal">
              <Skeleton height={20} width="50%" />
              <div style={{ height: 8 }} />
              <Skeleton height={12} width="80%" />
              <Skeleton height={12} width="70%" />
              <div style={{ height: 8 }} />
              <Skeleton height={60} />
            </Card>
          ))}
        </div>
      </div>
    )
  }

  /* ---------- 错误 ---------- */
  if (error && rows.length === 0) {
    return (
      <div className="v3-stack admin-exp-page">
        {header}
        <Card>
          <Empty
            icon={<AlertCircle size={26} />}
            title="加载失败"
            text={error}
            action={<Button variant="tonal" icon={<RefreshCw size={16} />} onClick={load}>重新加载</Button>}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="v3-stack admin-exp-page">
      {header}

      <Alert tone="info" icon={<Shield size={18} />}>
        <p>审核通过的经验卡将公开展示并写入 RAG 知识库（<code>source_type=experience</code>）供其他同学检索。请核验内容真实性与依据完整性后再批准。</p>
      </Alert>

      {/* 状态标签页 */}
      <div className="admin-exp-tabs" role="tablist">
        {STATUS_TABS.map((t) => {
          const Icon = t.icon
          const active = tab === t.key
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active}
              className={cx('admin-exp-tabs__btn', active && 'is-active')}
              onClick={() => switchTab(t.key)}
            >
              <Icon size={15} />
              <span>{t.label}</span>
              {active ? <Badge tone={t.tone}>{total}</Badge> : null}
            </button>
          )
        })}
      </div>

      {/* 筛选 */}
      <Card className="admin-exp-filter">
        <div className="admin-exp-filter__row">
          <Select
            aria-label="按院校筛选"
            value={schoolFilter}
            onChange={(e) => applySchoolFilter(e.target.value)}
            options={schoolOptions}
            disabled={schoolsLoading}
            className="admin-exp-filter__school"
          />
          <span className="admin-exp-filter__hint">
            {loading ? <span><Spinner size={12} /> 加载中…</span> : `共 ${total} 条 · 第 ${curPage}/${totalPages} 页`}
          </span>
          <Button variant="text" icon={<RefreshCw size={14} />} onClick={load} disabled={loading}>刷新</Button>
        </div>
      </Card>

      {/* 列表 */}
      {rows.length === 0 ? (
        <Card>
          <Empty
            icon={<GraduationCap size={26} />}
            title={tab === 'pending' ? '没有待审核的经验卡' : `没有${STATUS_LABEL[tab]}的经验卡`}
            text={tab === 'pending'
              ? '当前没有等待审核的投稿。已上岸用户提交后会出现在这里。'
              : `当前状态下没有经验卡，可切换到其他标签页查看。`}
          />
        </Card>
      ) : (
        <div className="v3-stack">
          {rows.map((item) => (
            <AdminExperienceRow
              key={item.id}
              item={item}
              schoolMap={schoolMap}
              tab={tab}
              actingId={actingId}
              onApprove={approve}
              onReject={(id) => setRejecting({ id, reason: '' })}
            />
          ))}

          {totalPages > 1 ? (
            <nav className="admin-exp-pager" aria-label="审核列表分页">
              <button type="button" aria-label="上一页" disabled={curPage <= 1} onClick={() => setPage(curPage - 1)}>«</button>
              <span className="admin-exp-pager__info">第 {curPage} / {totalPages} 页 · 共 {total} 条</span>
              <button type="button" aria-label="下一页" disabled={curPage >= totalPages} onClick={() => setPage(curPage + 1)}>»</button>
            </nav>
          ) : null}
        </div>
      )}

      {rejectDialog}
    </div>
  )
}

/* ---------- 单条经验卡（管理员视图） ---------- */
function AdminExperienceRow({ item, schoolMap, tab, actingId, onApprove, onReject }) {
  const schoolName = schoolMap[item.school_id] || item.school_name || `院校 #${item.school_id || '?'}`
  const majorName = item.major_name || (item.major_id ? `专业 #${item.major_id}` : '未指定')
  const evidence = evidenceEntries(item.evidence_json || item.evidence)
  const acting = actingId === item.id

  return (
    <Card variant="tonal" className="admin-exp-row">
      <CardHead
        icon={<GraduationCap size={17} />}
        title={(
          <span className="admin-exp-row__title">
            <span>#{item.id ?? '?'} · {schoolName}</span>
            <Badge tone="outline">{item.year || '—'} 届</Badge>
            <Badge tone={tab === 'pending' ? 'warning' : tab === 'approved' ? 'success' : 'danger'}>
              {STATUS_LABEL[item.status] || item.status}
            </Badge>
          </span>
        )}
        sub={`${majorName}${item.score != null ? ` · 总分 ${item.score}` : ''}${item.author_name ? ` · 提交者：${item.author_name}` : ''}`}
        actions={tab === 'pending' ? (
          <div className="admin-exp-row__head-actions">
            <Button
              variant="gradient"
              icon={<Check size={15} />}
              size="sm"
              loading={acting}
              disabled={acting}
              onClick={() => onApprove(item.id)}
            >
              批准
            </Button>
            <Button
              variant="danger"
              icon={<X size={15} />}
              size="sm"
              disabled={acting}
              onClick={() => onReject(item.id)}
            >
              驳回
            </Button>
          </div>
        ) : null}
      />

      {item.content ? <p className="admin-exp-row__content">{item.content}</p> : null}

      {item.methodology ? (
        <div className="admin-exp-row__section">
          <div className="admin-exp-row__label"><BookOpen size={13} /> 方法论</div>
          <p className="admin-exp-row__text">{item.methodology}</p>
        </div>
      ) : null}

      {evidence.length > 0 ? (
        <div className="admin-exp-row__section">
          <div className="admin-exp-row__label"><Sparkles size={13} /> 备考依据（{evidence.length} 项）</div>
          <dl className="admin-exp-row__evidence">
            {evidence.map(([k, v], i) => (
              <div key={i} className="admin-exp-row__ev-row">
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      {item.reject_reason ? (
        <div className="admin-exp-row__section">
          <div className="admin-exp-row__label"><AlertCircle size={13} /> 驳回原因</div>
          <p className="admin-exp-row__text admin-exp-row__reject-reason">{item.reject_reason}</p>
        </div>
      ) : null}

      <div className="admin-exp-row__foot">
        {item.created_at ? <span className="admin-exp-row__date"><Calendar size={12} /> 提交于 {fmtDate(item.created_at)}</span> : null}
        {item.reviewed_at ? <span className="admin-exp-row__date"><CheckCircle2 size={12} /> 审核于 {fmtDate(item.reviewed_at)}</span> : null}
      </div>

      {tab === 'pending' ? (
        <div className="admin-exp-row__mobile-actions">
          <Button
            variant="gradient"
            icon={<Check size={15} />}
            loading={acting}
            disabled={acting}
            onClick={() => onApprove(item.id)}
            style={{ flex: 1 }}
          >
            批准
          </Button>
          <Button
            variant="danger"
            icon={<X size={15} />}
            disabled={acting}
            onClick={() => onReject(item.id)}
            style={{ flex: 1 }}
          >
            驳回
          </Button>
        </div>
      ) : null}
    </Card>
  )
}
