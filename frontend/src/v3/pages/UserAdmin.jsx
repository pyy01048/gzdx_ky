import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react'
import { adminUsersApi } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, AnimatedNumber, Avatar, Badge, Button, Card, CardHead, Chip, Dialog,
  Empty, Field, IconButton, Input, PageHeader, Select, Skeleton, Tabs, Textarea,
  Tile, toastErr, toastOk, useConfirm,
} from '../ui'
import {
  CheckCircle2, ChevronLeft, ChevronRight, Clock, Copy, FileText, KeyRound,
  Lock, Mail, Plus, RefreshCw, RotateCcw, Search, Shield, Trash, User,
} from '../icons'
import '../styles/admin-core-v3.css'

/* 《用户管理界面.md》§5.2：筛选 + 详情 + 禁用（必填原因）+ 角色 + 强制重置
   （临时密码 / 邮件）+ 只读审计。全部走服务端筛选与分页，不再前端拉全量。 */

const ROLE_LABEL = { admin: '管理员', doc_admin: '文档管理员', user: '普通用户' }
const ROLE_OPTIONS = Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))

const STATUS_META = {
  active: { label: '正常', tone: 'success' },
  unverified: { label: '邮箱未验证', tone: 'warning' },
  disabled: { label: '已禁用', tone: 'danger' },
  pending_deletion: { label: '待注销', tone: 'warning' },
  deleted: { label: '已删除', tone: 'danger' },
}

const EVENT_LABEL = {
  login_success: '登录成功',
  login_failure: '登录失败',
  login_blocked_disabled: '登录被拒（已禁用）',
  register: '邮箱注册',
  register_attempt_existing: '注册尝试（邮箱已存在）',
  verification_resent: '补发验证邮件',
  verification_send_throttled: '验证邮件被限流',
  email_verified: '邮箱验证成功',
  password_reset_no_account: '找回密码（邮箱未注册）',
  password_reset_blocked_disabled: '找回被拒（已禁用）',
  password_reset_blocked_unverified: '找回被拒（邮箱未验证）',
  password_reset_requested: '发送重置邮件',
  password_reset_success: '重置密码成功',
  deletion_requested: '申请注销账号',
  deletion_cancelled: '撤销注销申请',
  admin_force_reset_email: '管理员重置（邮件）',
  admin_force_reset_temp: '管理员重置（临时密码）',
  admin_insert: '管理员新建账号',
  admin_update: '管理员修改账号',
  admin_delete: '管理员删除账号',
}

const EMPTY_FORM = { username: '', display_name: '', role: 'user', password: '' }
const PAGE_SIZE = 20

const fmt = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

const statusOf = (u) => u.status || (u.deleted_at ? 'deleted' : (u.is_active ? 'active' : 'disabled'))

function StatusBadges({ u }) {
  const s = statusOf(u)
  const meta = STATUS_META[s] || { label: s, tone: 'outline' }
  return (
    <div className="v3-admin-user-status">
      <Badge tone={meta.tone}>{meta.label}</Badge>
      {s !== 'deleted' && u.must_change_password ? <Badge tone="warning">待改密</Badge> : null}
    </div>
  )
}

function Pager({ page, total, pageSize = PAGE_SIZE, onChange }) {
  const pages = Math.max(1, Math.ceil((total || 0) / pageSize))
  if (pages <= 1) return null
  return (
    <div className="v3-admin-pager">
      <span className="v3-admin-pager__meta">共 {total} 条 · 第 {page} / {pages} 页</span>
      <Button variant="outline" size="sm" icon={<ChevronLeft size={14} />}
        disabled={page <= 1} onClick={() => onChange(page - 1)}>上一页</Button>
      <Button variant="outline" size="sm" trailingIcon={<ChevronRight size={14} />}
        disabled={page >= pages} onClick={() => onChange(page + 1)}>下一页</Button>
    </div>
  )
}

function TableSkeleton({ cols = 7 }) {
  return (
    <div className="v3-admin-table-wrap">
      <table className="v3-admin-table">
        <thead>
          <tr>{Array.from({ length: cols }).map((_, i) => <th key={i}><Skeleton width="60%" height={12} /></th>)}</tr>
        </thead>
        <tbody>
          {Array.from({ length: 6 }).map((_, i) => (
            <tr key={i} aria-hidden="true">
              {Array.from({ length: cols }).map((__, j) => (
                <td key={j}><Skeleton width={`${55 + ((i + j) % 3) * 12}%`} height={12} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 账号列表                                                            */
/* ------------------------------------------------------------------ */
function UsersTab({ me }) {
  const [confirm, confirmDialog] = useConfirm()
  const [rows, setRows] = useState(null)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  /* 服务端筛选（§5.2：关键词 / 角色 / 状态 / 注册时间段） */
  const [q, setQ] = useState('')
  const [kw, setKw] = useState('')
  const [role, setRole] = useState('')
  const [statusF, setStatusF] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)
  const [stats, setStats] = useState(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formErr, setFormErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [secret, setSecret] = useState(null)
  const [disableTarget, setDisableTarget] = useState(null)
  const [reason, setReason] = useState('')
  const [disableErr, setDisableErr] = useState('')
  const [resetTarget, setResetTarget] = useState(null)
  const [resetMode, setResetMode] = useState('temp')
  const [detail, setDetail] = useState(null)
  const [detailErr, setDetailErr] = useState('')
  const usernameRef = useRef(null)

  /* 关键词防抖：输入停顿 350ms 后才发请求 */
  useEffect(() => {
    const t = setTimeout(() => { setKw(q.trim()); setPage(1) }, 350)
    return () => clearTimeout(t)
  }, [q])

  const load = useCallback(async () => {
    setLoading(true)
    setLoadErr('')
    try {
      const r = await adminUsersApi.list({
        page, page_size: PAGE_SIZE,
        ...(kw ? { keyword: kw } : {}),
        ...(role ? { role } : {}),
        ...(statusF ? { status_filter: statusF } : {}),
        ...(from ? { registered_from: from } : {}),
        ...(to ? { registered_to: to } : {}),
        ...(showDeleted ? { include_deleted: true } : {}),
      })
      setRows(Array.isArray(r?.items) ? r.items : [])
      setTotal(Number(r?.total) || 0)
      return true
    } catch (e) {
      setLoadErr(e?.message || '加载失败')
      setRows([])
      setTotal(0)
      return false
    } finally {
      setLoading(false)
    }
  }, [page, kw, role, statusF, from, to, showDeleted])

  /* 统计口径是服务端 count（page_size=1 只取 total），不受当前筛选影响 */
  const loadStats = useCallback(async () => {
    try {
      const [all, unv, dis, pend] = await Promise.all([
        adminUsersApi.list({ page: 1, page_size: 1 }),
        adminUsersApi.list({ page: 1, page_size: 1, status_filter: 'unverified' }),
        adminUsersApi.list({ page: 1, page_size: 1, status_filter: 'disabled' }),
        adminUsersApi.list({ page: 1, page_size: 1, status_filter: 'pending_deletion' }),
      ])
      setStats({
        total: Number(all?.total) || 0,
        unverified: Number(unv?.total) || 0,
        disabled: Number(dis?.total) || 0,
        pendingDeletion: Number(pend?.total) || 0,
      })
    } catch {
      setStats(null)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadStats() }, [loadStats])

  const refresh = async () => {
    // 列表与统计互不依赖：并行发请求，避免刷新按钮串行等两段网络（async-parallel）
    const [ok] = await Promise.all([load(), loadStats()])
    if (ok) toastOk('用户列表已刷新')
    else toastErr('刷新失败，请检查后端服务后重试')
  }

  const afterMutation = () => { load(); loadStats() }

  const patch = async (u, body, okMsg) => {
    try {
      const res = await adminUsersApi.update(u.id, body)
      const nu = res?.user || res
      if (nu?.id) setRows((rs) => (rs || []).map((r) => (r.id === nu.id ? nu : r)))
      toastOk(okMsg)
      loadStats()
      return true
    } catch (e) {
      toastErr(`操作失败：${e?.message || e}`)
      return false
    }
  }

  /* 禁用必须给原因（§5.2），原因会在对方登录时展示 */
  const openDisable = (u) => { setDisableTarget(u); setReason(''); setDisableErr('') }
  const submitDisable = async (e) => {
    e.preventDefault()
    const text = reason.trim()
    if (!text) { setDisableErr('请填写禁用原因，该原因会在用户登录时展示'); return }
    setBusy(true)
    const ok = await patch(disableTarget, { is_active: false, disabled_reason: text }, '已禁用，该用户所有会话已失效')
    setBusy(false)
    if (ok) setDisableTarget(null)
  }

  const enable = async (u) => {
    const ok = await confirm({
      title: '启用用户',
      message: `启用后 ${u.username} 可以重新登录。确认启用？`,
      confirmText: '启用',
    })
    if (!ok) return
    patch(u, { is_active: true }, '已启用')
  }

  const openReset = (u) => { setResetTarget(u); setResetMode(u.email ? 'email' : 'temp') }
  const submitReset = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await adminUsersApi.resetPassword(resetTarget.id, resetMode)
      const nu = r?.user || r
      if (nu?.id) setRows((rs) => (rs || []).map((x) => (x.id === nu.id ? nu : x)))
      if (resetMode === 'email') {
        toastOk(`重置邮件已发送到 ${r?.email_masked || resetTarget.email}（60 分钟内有效）`)
      } else {
        setSecret({
          username: nu?.username || resetTarget.username,
          password: r?.temporary_password,
          generated: true,
        })
      }
      setResetTarget(null)
      loadStats()
    } catch (err) {
      toastErr(`重置失败：${err?.message || err}`)
    } finally {
      setBusy(false)
    }
  }

  const openDetail = async (u) => {
    setDetail({ user: u, recent_events: null })
    setDetailErr('')
    try {
      const r = await adminUsersApi.detail(u.id)
      setDetail({ user: r?.user || u, recent_events: Array.isArray(r?.recent_events) ? r.recent_events : [] })
    } catch (e) {
      setDetailErr(e?.message || '详情加载失败')
      setDetail((d) => (d ? { ...d, recent_events: [] } : d))
    }
  }

  const remove = async (u) => {
    const ok = await confirm({
      title: '删除用户',
      message: `删除后 ${u.username} 将无法登录，其所有会话立即失效。`
        + '这是软删除，勾选「显示已删除」可以随时恢复。确认删除？',
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await adminUsersApi.remove(u.id)
      toastOk(`已删除用户 ${u.username}`)
      afterMutation()
    } catch (e) {
      toastErr(`删除失败：${e?.message || e}`)
    }
  }

  const restore = async (u) => {
    try {
      await adminUsersApi.restore(u.id)
      toastOk(`已恢复用户 ${u.username}`)
      afterMutation()
    } catch (e) {
      toastErr(`恢复失败：${e?.message || e}`)
    }
  }

  const submitCreate = async (e) => {
    e.preventDefault()
    setFormErr('')
    const username = form.username.trim()
    const typedPassword = form.password
    if (!username) {
      setFormErr('请填写用户名')
      usernameRef.current?.focus()
      return
    }
    if (!/^[A-Za-z0-9_.-]+$/.test(username)) {
      setFormErr('用户名只能使用字母、数字、下划线、点和短横线')
      return
    }
    if (typedPassword && typedPassword.length < 8) {
      setFormErr('初始密码至少 8 位，或留空由系统自动生成')
      return
    }
    setBusy(true)
    try {
      const body = { username, role: form.role }
      if (form.display_name.trim()) body.display_name = form.display_name.trim()
      if (typedPassword) body.password = typedPassword
      const r = await adminUsersApi.create(body)
      setSecret({
        username: r.user.username,
        password: r.temporary_password || typedPassword,
        generated: !!r.temporary_password,
      })
      setForm(EMPTY_FORM)
      setCreateOpen(false)
      toastOk(`已创建用户 ${r.user.username}`)
      afterMutation()
    } catch (e2) {
      setFormErr(e2?.message || '创建失败')
    } finally {
      setBusy(false)
    }
  }

  const copyPassword = async (text) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        const el = document.createElement('textarea')
        el.value = text
        el.setAttribute('readonly', '')
        el.style.position = 'fixed'
        el.style.opacity = '0'
        document.body.appendChild(el)
        el.select()
        document.execCommand('copy')
        el.remove()
      }
      toastOk('临时密码已复制')
    } catch {
      toastErr('复制失败，请手动选择密码')
    }
  }

  const setField = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const hasFilter = !!(kw || role || statusF || from || to)
  const clearFilters = () => { setQ(''); setRole(''); setStatusF(''); setFrom(''); setTo(''); setPage(1) }

  const statTiles = [
    { icon: User, label: '账号总数', value: stats?.total, unit: '个', hint: '不含已删除账号' },
    { icon: Mail, label: '邮箱未验证', value: stats?.unverified, unit: '个', hint: '可登录浏览，不可上传资料' },
    { icon: Lock, label: '已禁用', value: stats?.disabled, unit: '个', hint: '禁用须填原因，登录时展示' },
    { icon: Clock, label: '待注销', value: stats?.pendingDeletion, unit: '个', hint: '7 天冷静期内可撤销' },
  ]

  return (
    <>
      {secret ? (
        <Alert tone="warning" icon={<KeyRound size={18} />} className="v3-admin-secret">
          <div className="v3-admin-secret__inner">
            <div className="v3-admin-secret__text">
              {secret.generated ? (
                <>用户 <b>{secret.username}</b> 的临时密码已生成，只显示这一次，请立即转交。</>
              ) : (
                <>用户 <b>{secret.username}</b> 已按你填写的初始密码创建。</>
              )}
            </div>
            {secret.generated && secret.password ? (
              <span className="v3-admin-secret__code">
                <code>{secret.password}</code>
                <IconButton label="复制临时密码" size="sm" icon={<Copy size={14} />}
                  onClick={() => copyPassword(secret.password)} />
              </span>
            ) : null}
            <Button variant="text" size="sm" onClick={() => setSecret(null)}>我已记下</Button>
          </div>
        </Alert>
      ) : null}

      <div className="v3-admin-stats">
        {statTiles.map(({ icon: Icon, label, value, unit, hint }) => (
          <Tile className="v3-admin-stat" key={label}>
            <span className="v3-tile__label"><Icon size={14} />{label}</span>
            <span className="v3-tile__value">
              {value == null ? <span className="v3-admin-nil">—</span> : (
                <><AnimatedNumber value={value} /><em>{unit}</em></>
              )}
            </span>
            <span className="v3-tile__hint">{hint}</span>
          </Tile>
        ))}
      </div>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            icon={<User size={16} />}
            title="账号列表"
            sub="角色变更即时生效；禁用或删除会立即撤销该用户的全部会话。"
            actions={(
              <div className="v3-row" style={{ gap: 8 }}>
                <Button variant="outline" size="sm" icon={<RefreshCw size={14} />} loading={loading} onClick={refresh}>刷新</Button>
                <Button variant="filled" size="sm" icon={<Plus size={14} />} onClick={() => { setForm(EMPTY_FORM); setFormErr(''); setCreateOpen(true) }}>新建用户</Button>
              </div>
            )}
          />
        </div>

        <div className="v3-admin-panel__toolbar">
          <div className="v3-admin-toolbar">
            <div className="v3-admin-toolbar__grow">
              <Input
                icon={<Search size={16} />}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="搜索用户名、显示名或邮箱"
                aria-label="搜索用户名、显示名或邮箱"
              />
            </div>
            <Select aria-label="按角色筛选" value={role}
              onChange={(e) => { setRole(e.target.value); setPage(1) }}
              options={[{ value: '', label: '全部角色' }, ...ROLE_OPTIONS]} />
            <Select aria-label="按状态筛选" value={statusF}
              onChange={(e) => { setStatusF(e.target.value); setPage(1) }}
              options={[
                { value: '', label: '全部状态' },
                { value: 'active', label: '正常' },
                { value: 'unverified', label: '邮箱未验证' },
                { value: 'disabled', label: '已禁用' },
                { value: 'pending_deletion', label: '待注销' },
                ...(showDeleted ? [{ value: 'deleted', label: '已删除' }] : []),
              ]} />
            <div className="v3-admin-daterange">
              <Input type="date" aria-label="注册起始日期" value={from}
                onChange={(e) => { setFrom(e.target.value); setPage(1) }} />
              <span>至</span>
              <Input type="date" aria-label="注册截止日期" value={to}
                onChange={(e) => { setTo(e.target.value); setPage(1) }} />
            </div>
            <Chip active={showDeleted} icon={<Trash size={13} />}
              onClick={() => { setShowDeleted((v) => !v); setPage(1) }}
              aria-pressed={showDeleted} title="包含软删除账号，可随时恢复">
              显示已删除
            </Chip>
            {hasFilter ? <Button variant="text" size="sm" onClick={clearFilters}>清空筛选</Button> : null}
            <span className="v3-admin-toolbar__meta">
              {loading ? '同步中…' : `${total} 个账号`}
            </span>
          </div>
        </div>

        {loading ? <TableSkeleton /> : null}

        {!loading && loadErr ? (
          <div className="v3-admin-panel__body">
            <Empty icon={<RefreshCw size={28} />} title="用户列表加载失败" text={loadErr}
              action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={load}>重试</Button>} />
          </div>
        ) : null}

        {!loading && !loadErr && rows && rows.length === 0 ? (
          <div className="v3-admin-panel__body">
            {hasFilter ? (
              <Empty icon={<Search size={28} />} title="没有匹配的账号"
                text="当前筛选条件下没有账号，试试放宽条件。"
                action={<Button variant="outline" onClick={clearFilters}>清空筛选</Button>} />
            ) : (
              <Empty icon={<User size={30} />} title="暂无账号"
                text={showDeleted ? '当前没有账号，也没有已删除账号。' : '创建第一个账号，或让用户通过邮箱自助注册。'}
                action={<Button variant="filled" icon={<Plus size={15} />}
                  onClick={() => { setForm(EMPTY_FORM); setFormErr(''); setCreateOpen(true) }}>新建用户</Button>} />
            )}
          </div>
        ) : null}

        {!loading && !loadErr && rows && rows.length > 0 ? (
          <div className="v3-admin-table-wrap">
            <table className="v3-admin-table">
              <thead>
                <tr>
                  <th>用户</th>
                  <th>邮箱</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>注册时间</th>
                  <th>最近登录</th>
                  <th className="is-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((u) => {
                  const self = me && u.id === me.id
                  const gone = statusOf(u) === 'deleted'
                  const active = !!u.is_active && !gone
                  return (
                    <tr key={u.id} className={gone ? 'v3-admin-user-row is-deleted' : undefined}>
                      <td>
                        <div className="v3-admin-user-cell">
                          <Avatar name={u.display_name || u.username} size="sm" />
                          <div className="v3-admin-user-main">
                            <span className="v3-admin-user-name">
                              {u.username}
                              {self ? <Badge tone="primary">我</Badge> : null}
                            </span>
                            <span className="v3-admin-user-sub">
                              {u.display_name ? `${u.display_name} · ` : ''}ID {u.id}
                              {gone && u.deleted_at ? ` · 删除于 ${fmt(u.deleted_at)}` : ''}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td>
                        {u.email ? (
                          <div className="v3-admin-email-cell">
                            <span className="v3-admin-email" title={u.email}>{u.email}</span>
                            {u.email_verified_at
                              ? <Badge tone="success">已验证</Badge>
                              : <Badge tone="warning">未验证</Badge>}
                          </div>
                        ) : <span className="is-muted is-nowrap">未绑定</span>}
                      </td>
                      <td>
                        <Select
                          className="v3-admin-user-role"
                          aria-label={`${u.username} 的角色`}
                          value={u.role}
                          disabled={gone}
                          onChange={(e) => patch(u, { role: e.target.value }, '角色已更新')}
                          options={ROLE_OPTIONS}
                        />
                      </td>
                      <td><StatusBadges u={u} /></td>
                      <td className="is-nowrap is-muted">{fmt(u.created_at)}</td>
                      <td className="is-nowrap is-muted">
                        {fmt(u.last_login_at)}
                        {u.login_count ? <span className="v3-admin-user-sub">累计 {u.login_count} 次</span> : null}
                      </td>
                      <td>
                        <div className="v3-admin-user-actions">
                          <Button variant="text" size="sm" icon={<FileText size={14} />}
                            aria-label={`查看 ${u.username} 的详情`} onClick={() => openDetail(u)}>
                            详情
                          </Button>
                          {gone ? (
                            <Button variant="text" size="sm" icon={<RotateCcw size={14} />}
                              aria-label={`恢复用户 ${u.username}`} onClick={() => restore(u)}>
                              恢复
                            </Button>
                          ) : (
                            <>
                              <Button variant="text" size="sm"
                                icon={active ? <Lock size={14} /> : <CheckCircle2 size={14} />}
                                disabled={self && active}
                                title={self && active ? '不能禁用当前登录账号' : undefined}
                                aria-label={`${active ? '禁用' : '启用'}用户 ${u.username}`}
                                onClick={() => (active ? openDisable(u) : enable(u))}>
                                {active ? '禁用' : '启用'}
                              </Button>
                              <Button variant="text" size="sm" icon={<KeyRound size={14} />}
                                aria-label={`重置 ${u.username} 的密码`} onClick={() => openReset(u)}>
                                重置密码
                              </Button>
                              <Button variant="text" size="sm" icon={<Trash size={14} />}
                                className="v3-admin-danger-text"
                                disabled={self}
                                title={self ? '不能删除当前登录账号' : undefined}
                                aria-label={`删除用户 ${u.username}`} onClick={() => remove(u)}>
                                删除
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}

        {!loading && !loadErr ? <Pager page={page} total={total} onChange={setPage} /> : null}

        {!loading && !loadErr && rows && rows.length > 0 ? (
          <div className="v3-admin-q-table-note">
            当前登录账号不能禁用或删除自己；禁用必须填写原因（登录时向用户展示）；所有破坏性操作都会立即撤销目标用户的会话。
          </div>
        ) : null}
      </Card>

      {/* 新建用户 */}
      <Dialog
        open={createOpen}
        title="新建用户"
        sub="新账号首次登录须修改密码；留空密码会自动生成一次性临时密码。用户也可以从登录页邮箱自助注册。"
        onClose={busy ? undefined : () => setCreateOpen(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setCreateOpen(false)} disabled={busy}>取消</Button>
            <Button type="submit" form="v3-create-user" variant="filled" loading={busy}>创建用户</Button>
          </>
        )}
      >
        <form id="v3-create-user" className="v3-admin-user-form" onSubmit={submitCreate}>
          {formErr ? <Alert tone="danger">{formErr}</Alert> : null}
          <Field label="用户名" hint="2–64 位，可使用字母、数字、下划线、点和短横线。" htmlFor="v3-new-username">
            <Input id="v3-new-username" ref={usernameRef} value={form.username}
              onChange={setField('username')} placeholder="如：zhangsan"
              required minLength={2} maxLength={64} pattern="[A-Za-z0-9_.-]+" autoComplete="off" />
          </Field>
          <Field label="显示名" hint="可选，用于界面展示。" htmlFor="v3-new-display">
            <Input id="v3-new-display" value={form.display_name} onChange={setField('display_name')}
              placeholder="如：张三" maxLength={64} autoComplete="off" />
          </Field>
          <Field label="角色" hint="文档管理员可审核资料，但不能管理用户；管理员拥有全部权限。" htmlFor="v3-new-role">
            <Select id="v3-new-role" value={form.role} onChange={setField('role')} options={ROLE_OPTIONS} />
          </Field>
          <Field label="初始密码" hint="留空自动生成；手动填写至少 8 位。" htmlFor="v3-new-password">
            <Input id="v3-new-password" type="password" value={form.password}
              onChange={setField('password')} placeholder="留空自动生成" minLength={8} autoComplete="new-password" />
          </Field>
        </form>
      </Dialog>

      {/* 禁用（必填原因） */}
      <Dialog
        open={!!disableTarget}
        title={`禁用用户 ${disableTarget?.username || ''}`}
        sub="禁用后该用户所有会话立即失效；原因会在其登录时展示，请写清楚。"
        onClose={busy ? undefined : () => setDisableTarget(null)}
        footer={(
          <>
            <Button variant="text" onClick={() => setDisableTarget(null)} disabled={busy}>取消</Button>
            <Button type="submit" form="v3-disable-user" variant="filled" loading={busy}>确认禁用</Button>
          </>
        )}
      >
        <form id="v3-disable-user" className="v3-admin-user-form" onSubmit={submitDisable}>
          {disableErr ? <Alert tone="danger">{disableErr}</Alert> : null}
          <Field label="禁用原因（必填）" hint="最多 500 字，用户登录被拒时会看到这段文字。" htmlFor="v3-disable-reason">
            <Textarea id="v3-disable-reason" value={reason} maxLength={500} rows={3}
              onChange={(e) => setReason(e.target.value)}
              placeholder="如：发布违规内容，暂停账号使用" autoFocus />
          </Field>
        </form>
      </Dialog>

      {/* 强制重置密码：临时密码 / 重置邮件 */}
      <Dialog
        open={!!resetTarget}
        title={`重置 ${resetTarget?.username || ''} 的密码`}
        sub="两种方式都会使该用户现有会话全部失效，并记录审计。"
        onClose={busy ? undefined : () => setResetTarget(null)}
        footer={(
          <>
            <Button variant="text" onClick={() => setResetTarget(null)} disabled={busy}>取消</Button>
            <Button type="submit" form="v3-reset-user" variant="filled" loading={busy}>
              {resetMode === 'email' ? '发送重置邮件' : '生成临时密码'}
            </Button>
          </>
        )}
      >
        <form id="v3-reset-user" className="v3-admin-user-form" onSubmit={submitReset}>
          <div className="v3-admin-reset-modes" role="radiogroup" aria-label="重置方式">
            <label className={resetMode === 'email' ? 'is-on' : ''}>
              <input type="radio" name="v3-reset-mode" value="email"
                checked={resetMode === 'email'} disabled={!resetTarget?.email}
                onChange={() => setResetMode('email')} />
              <span>
                <b><Mail size={14} /> 发送重置邮件</b>
                <em>
                  {resetTarget?.email
                    ? `发到 ${resetTarget.email}，链接 60 分钟有效，用户自助设置新密码。`
                    : '该账号未绑定邮箱，无法使用此方式。'}
                </em>
              </span>
            </label>
            <label className={resetMode === 'temp' ? 'is-on' : ''}>
              <input type="radio" name="v3-reset-mode" value="temp"
                checked={resetMode === 'temp'} onChange={() => setResetMode('temp')} />
              <span>
                <b><KeyRound size={14} /> 生成临时密码</b>
                <em>只显示一次，需线下转交；用户下次登录必须改密。</em>
              </span>
            </label>
          </div>
        </form>
      </Dialog>

      {/* 用户详情 + 最近安全事件 */}
      <Dialog
        open={!!detail}
        title={detail ? `用户详情 · ${detail.user.username}` : '用户详情'}
        sub="账号信息与最近 20 条安全事件（只读）。"
        onClose={() => setDetail(null)}
        footer={<Button variant="text" onClick={() => setDetail(null)}>关闭</Button>}
      >
        {detail ? (
          <div className="v3-admin-detail">
            <div className="v3-admin-detail__grid">
              <div><em>显示名</em><b>{detail.user.display_name || '—'}</b></div>
              <div><em>角色</em><b>{ROLE_LABEL[detail.user.role] || detail.user.role}</b></div>
              <div><em>状态</em><b><StatusBadges u={detail.user} /></b></div>
              <div><em>邮箱</em><b>{detail.user.email || '未绑定'}{detail.user.email && !detail.user.email_verified_at ? '（未验证）' : ''}</b></div>
              <div><em>注册时间</em><b>{fmt(detail.user.created_at)}</b></div>
              <div><em>最近登录</em><b>{fmt(detail.user.last_login_at)}</b></div>
              <div><em>最近登录 IP</em><b>{detail.user.last_login_ip || '—'}</b></div>
              <div><em>累计登录</em><b>{detail.user.login_count || 0} 次</b></div>
              {detail.user.disabled_reason ? (
                <div className="is-wide"><em>禁用原因</em><b>{detail.user.disabled_reason}</b></div>
              ) : null}
              {detail.user.deletion_requested_at ? (
                <div className="is-wide"><em>注销申请时间</em><b>{fmt(detail.user.deletion_requested_at)}（7 天冷静期）</b></div>
              ) : null}
            </div>
            <h4 className="v3-admin-detail__events-title"><Clock size={14} /> 最近安全事件</h4>
            {detailErr ? <Alert tone="danger">{detailErr}</Alert> : null}
            {detail.recent_events == null ? (
              <Skeleton width="100%" height={80} />
            ) : detail.recent_events.length === 0 ? (
              <p className="v3-admin-detail__empty">暂无安全事件记录。</p>
            ) : (
              <ul className="v3-admin-detail__events">
                {detail.recent_events.map((ev) => (
                  <li key={ev.id}>
                    <Badge tone={ev.success ? 'success' : 'danger'}>{ev.success ? '成功' : '失败'}</Badge>
                    <span className="v3-admin-detail__ev-name">{EVENT_LABEL[ev.event_type] || ev.event_type}</span>
                    <span className="v3-admin-detail__ev-meta">
                      {fmt(ev.created_at)}{ev.ip ? ` · ${ev.ip}` : ''}{ev.detail ? ` · ${ev.detail}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </Dialog>
      {confirmDialog}
    </>
  )
}

/* ------------------------------------------------------------------ */
/* 审计日志（只读）                                                     */
/* ------------------------------------------------------------------ */
function EventsTab() {
  const [rows, setRows] = useState(null)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [type, setType] = useState('')
  const [q, setQ] = useState('')
  const [kw, setKw] = useState('')

  useEffect(() => {
    const t = setTimeout(() => { setKw(q.trim()); setPage(1) }, 350)
    return () => clearTimeout(t)
  }, [q])

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      const r = await adminUsersApi.authEvents({
        page, page_size: PAGE_SIZE,
        ...(type ? { event_type: type } : {}),
        ...(kw ? { keyword: kw } : {}),
      })
      setRows(Array.isArray(r?.items) ? r.items : [])
      setTotal(Number(r?.total) || 0)
    } catch (e) {
      setErr(e?.message || '加载失败')
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [page, type, kw])

  useEffect(() => { load() }, [load])

  return (
    <Card className="v3-admin-panel">
      <div className="v3-admin-panel__head">
        <CardHead
          icon={<Shield size={16} />}
          title="安全审计"
          sub="注册、登录、验证、找回密码与管理操作的全量流水，只读，不可修改或删除。"
          actions={<Button variant="outline" size="sm" icon={<RefreshCw size={14} />} loading={loading} onClick={load}>刷新</Button>}
        />
      </div>
      <div className="v3-admin-panel__toolbar">
        <div className="v3-admin-toolbar">
          <div className="v3-admin-toolbar__grow">
            <Input icon={<Search size={16} />} value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="按邮箱搜索" aria-label="按邮箱搜索审计事件" />
          </div>
          <Select aria-label="按事件类型筛选" value={type}
            onChange={(e) => { setType(e.target.value); setPage(1) }}
            options={[{ value: '', label: '全部事件' },
              ...Object.entries(EVENT_LABEL).map(([value, label]) => ({ value, label }))]} />
          {type || kw ? <Button variant="text" size="sm" onClick={() => { setType(''); setQ('') }}>清空筛选</Button> : null}
          <span className="v3-admin-toolbar__meta">{loading ? '同步中…' : `${total} 条记录`}</span>
        </div>
      </div>

      {loading ? <TableSkeleton cols={6} /> : null}
      {!loading && err ? (
        <div className="v3-admin-panel__body">
          <Empty icon={<RefreshCw size={28} />} title="审计日志加载失败" text={err}
            action={<Button variant="outline" onClick={load}>重试</Button>} />
        </div>
      ) : null}
      {!loading && !err && rows && rows.length === 0 ? (
        <div className="v3-admin-panel__body">
          <Empty icon={<Shield size={28} />} title="暂无审计记录"
            text={type || kw ? '当前筛选条件下没有记录。' : '发生注册、登录、找回密码等操作后，这里会自动留下流水。'} />
        </div>
      ) : null}
      {!loading && !err && rows && rows.length > 0 ? (
        <div className="v3-admin-table-wrap">
          <table className="v3-admin-table">
            <thead>
              <tr><th>时间</th><th>事件</th><th>账号</th><th>结果</th><th>IP</th><th>详情</th></tr>
            </thead>
            <tbody>
              {rows.map((ev) => (
                <tr key={ev.id}>
                  <td className="is-nowrap is-muted">{fmt(ev.created_at)}</td>
                  <td className="is-nowrap">{EVENT_LABEL[ev.event_type] || ev.event_type}</td>
                  <td>{ev.email || (ev.user_id != null ? `UID ${ev.user_id}` : '—')}</td>
                  <td><Badge tone={ev.success ? 'success' : 'danger'}>{ev.success ? '成功' : '失败'}</Badge></td>
                  <td className="is-nowrap is-muted">{ev.ip || '—'}</td>
                  <td className="v3-admin-event-detail" title={ev.detail || ''}>{ev.detail || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {!loading && !err ? <Pager page={page} total={total} onChange={setPage} /> : null}
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* 角色与权限（只读，映射存 role_permission 表）                        */
/* ------------------------------------------------------------------ */
const PERM_LABEL = {
  'user:list': '查看用户列表', 'user:manage': '管理用户', 'audit:view': '查看审计',
  'doc:review': '审核资料', 'doc:unpublish': '下架资料', 'doc:edit_metadata': '编辑资料元数据',
  'doc:view_stats': '查看资料统计', 'doc:upload': '上传资料', 'doc:download': '下载资料',
  'profile:edit_self': '编辑个人资料',
}

function RolesTab() {
  const [roles, setRoles] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await adminUsersApi.roles()
      setRoles(Array.isArray(r?.items) ? r.items : [])
    } catch (e) {
      setErr(e?.message || '加载失败')
      setRoles([])
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <Card className="v3-admin-panel">
      <div className="v3-admin-panel__head">
        <CardHead
          icon={<Shield size={16} />}
          title="角色与权限"
          sub="权限映射存于数据库 role_permission 表（迁移 116 种子），此视图只读；管理员默认拥有全部权限。"
          actions={<Button variant="outline" size="sm" icon={<RefreshCw size={14} />} onClick={load}>刷新</Button>}
        />
      </div>
      <div className="v3-admin-panel__body">
        {roles == null ? <Skeleton width="100%" height={120} /> : null}
        {err ? <Alert tone="danger">{err}</Alert> : null}
        {roles && roles.length === 0 && !err ? (
          <Empty icon={<Shield size={28} />} title="暂无角色数据" text="role_permission 表为空，请确认迁移 116 已执行。" />
        ) : null}
        {roles && roles.length > 0 ? (
          <div className="v3-admin-role-cards">
            {roles.map((r) => (
              <div className="v3-admin-role-card" key={r.role}>
                <div className="v3-admin-role-card__head">
                  <b>{r.label || ROLE_LABEL[r.role] || r.role}</b>
                  <code>{r.role}</code>
                </div>
                {r.description ? <p>{r.description}</p> : null}
                <div className="v3-admin-role-card__perms">
                  {r.role === 'admin' ? (
                    <Badge tone="primary">全部权限（兜底）</Badge>
                  ) : (r.permissions || []).map((p) => (
                    <Badge tone="outline" key={p} title={p}>{PERM_LABEL[p] || p}</Badge>
                  ))}
                  {r.role !== 'admin' && (!r.permissions || r.permissions.length === 0) ? (
                    <span className="is-muted">无操作级权限</span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
export default function UserAdmin() {
  const { user: me } = useAuth()
  const [tab, setTab] = useState('users')

  return (
    <div className="v3-admin-page">
      <PageHeader
        title="用户管理"
        sub="邮箱自助注册 + 找回密码已上线；这里管理账号、角色、禁用与强制重置，并可查看只读安全审计。"
      />
      <Tabs
        className="v3-admin-tabs"
        ariaLabel="用户管理视图"
        value={tab}
        onChange={setTab}
        options={[
          { value: 'users', label: '账号列表', icon: <User size={14} /> },
          { value: 'events', label: '安全审计', icon: <Shield size={14} /> },
          { value: 'roles', label: '角色与权限', icon: <KeyRound size={14} /> },
        ]}
      />
      {tab === 'users' ? <UsersTab me={me} /> : null}
      {tab === 'events' ? <EventsTab /> : null}
      {tab === 'roles' ? <RolesTab /> : null}
    </div>
  )
}
