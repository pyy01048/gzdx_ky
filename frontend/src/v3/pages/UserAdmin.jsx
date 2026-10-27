import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react'
import { adminUsersApi } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, AnimatedNumber, Avatar, Badge, Button, Card, CardHead, Chip, Dialog,
  Empty, Field, IconButton, Input, PageHeader, Select, Skeleton, Tile, toastErr,
  toastOk, useConfirm,
} from '../ui'
import {
  CheckCircle2, Copy, KeyRound, Lock, Plus, RefreshCw, RotateCcw, Search,
  Shield, Trash, User,
} from '../icons'
import '../styles/admin-core-v3.css'

const ROLE_LABEL = { admin: '管理员', user: '普通用户' }
const EMPTY_FORM = { username: '', display_name: '', role: 'user', password: '' }

const fmt = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function TableSkeleton() {
  return (
    <div className="v3-admin-table-wrap">
      <table className="v3-admin-table">
        <thead>
          <tr><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>最近登录</th><th className="is-right">操作</th></tr>
        </thead>
        <tbody>
          {Array.from({ length: 6 }).map((_, i) => (
            <tr key={i} aria-hidden="true">
              <td>
                <div className="v3-admin-user-cell">
                  <Skeleton width={30} height={30} radius="50%" />
                  <Skeleton width={`${58 + (i % 3) * 10}%`} height={12} />
                </div>
              </td>
              <td><Skeleton width="56%" height={12} /></td>
              <td><Skeleton width={92} height={30} radius={10} /></td>
              <td><Skeleton width={58} height={20} radius={999} /></td>
              <td><Skeleton width="72%" height={12} /></td>
              <td><Skeleton width={120} height={12} style={{ marginLeft: 'auto' }} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function UserAdmin() {
  const { user: me } = useAuth()
  const [confirm, confirmDialog] = useConfirm()
  const [rows, setRows] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)
  const [q, setQ] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formErr, setFormErr] = useState('')
  const [busy, setBusy] = useState(false)
  /* 临时密码只在创建 / 重置响应里出现一次，后端不存明文 */
  const [secret, setSecret] = useState(null)
  const usernameRef = useRef(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadErr('')
    try {
      const r = await adminUsersApi.list({
        page: 1,
        page_size: 200,
        ...(showDeleted ? { include_deleted: true } : {}),
      })
      setRows(Array.isArray(r?.items) ? r.items : [])
      return true
    } catch (e) {
      setLoadErr(e?.message || '加载失败')
      setRows([])
      return false
    } finally {
      setLoading(false)
    }
  }, [showDeleted])

  useEffect(() => { load() }, [load])

  const refresh = async () => {
    const ok = await load()
    if (ok) toastOk('用户列表已刷新')
    else toastErr('刷新失败，请检查后端服务后重试')
  }

  const replaceRow = (u) => {
    if (!u) return
    setRows((rs) => (rs || []).map((r) => (r.id === u.id ? u : r)))
  }

  const filtered = useMemo(() => {
    const list = rows || []
    const kw = q.trim().toLowerCase()
    if (!kw) return list
    return list.filter((u) => String(u.username || '').toLowerCase().includes(kw)
      || String(u.display_name || '').toLowerCase().includes(kw))
  }, [rows, q])

  const stats = useMemo(() => {
    if (!rows) return { total: null, admins: null, disabled: null, pending: null, deleted: 0 }
    const live = rows.filter((u) => !u.deleted_at)
    return {
      total: rows.length,
      admins: live.filter((u) => u.role === 'admin').length,
      disabled: live.filter((u) => !u.is_active).length,
      pending: live.filter((u) => u.must_change_password).length,
      deleted: rows.length - live.length,
    }
  }, [rows])

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setFormErr('')
    setCreateOpen(true)
  }

  const closeCreate = () => {
    if (busy) return
    setCreateOpen(false)
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
      setRows((rs) => [...(rs || []), r.user])
      setForm(EMPTY_FORM)
      setSecret({
        username: r.user.username,
        password: r.temporary_password || typedPassword,
        generated: !!r.temporary_password,
      })
      setCreateOpen(false)
      toastOk(`已创建用户 ${r.user.username}`)
    } catch (e2) {
      setFormErr(e2?.message || '创建失败')
    } finally {
      setBusy(false)
    }
  }

  const patch = async (u, body, okMsg) => {
    try {
      const res = await adminUsersApi.update(u.id, body)
      replaceRow(res?.user || res)
      toastOk(okMsg)
    } catch (e) {
      toastErr(`操作失败：${e?.message || e}`)
    }
  }

  const toggleActive = async (u) => {
    if (u.is_active) {
      const ok = await confirm({
        title: '禁用用户',
        message: `禁用后 ${u.username} 的所有会话立即失效，确认？`,
        confirmText: '禁用',
        danger: true,
      })
      if (!ok) return
    }
    patch(u, { is_active: !u.is_active }, u.is_active ? '已禁用' : '已启用')
  }

  const resetPassword = async (u) => {
    const ok = await confirm({
      title: '重置密码',
      message: `将为 ${u.username} 生成临时密码，其下次登录须修改，确认？`,
      confirmText: '重置',
      danger: true,
    })
    if (!ok) return
    try {
      const r = await adminUsersApi.resetPassword(u.id)
      replaceRow(r?.user || r)
      setSecret({
        username: (r?.user || r)?.username || u.username,
        password: r?.temporary_password,
        generated: true,
      })
    } catch (e) {
      toastErr(`重置失败：${e?.message || e}`)
    }
  }

  /* 软删除：账号从列表隐藏、登录被拒、所有会话立即失效，但数据可恢复 */
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
      if (showDeleted) await load()
      else setRows((rs) => (rs || []).filter((r) => r.id !== u.id))
      toastOk(`已删除用户 ${u.username}`)
    } catch (e) {
      toastErr(`删除失败：${e?.message || e}`)
    }
  }

  const restore = async (u) => {
    try {
      const res = await adminUsersApi.restore(u.id)
      // 后端返回 {success, user}，不能把整个包装对象塞进列表
      replaceRow(res?.user || res)
      toastOk(`已恢复用户 ${u.username}`)
    } catch (e) {
      toastErr(`恢复失败：${e?.message || e}`)
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

  return (
    <div className="v3-admin-page">
      <PageHeader
        eyebrow="ADMIN · 账号与权限"
        title="用户管理"
        sub="创建账号、调整角色、禁用与重置密码；新账号首次登录须修改密码。删除为软删除，可恢复。"
        actions={(
          <div className="v3-row" style={{ gap: 8 }}>
            <Button
              variant="outline"
              icon={<RefreshCw size={15} />}
              loading={loading}
              onClick={refresh}
            >
              刷新
            </Button>
            <Button variant="filled" icon={<Plus size={15} />} onClick={openCreate}>
              新建用户
            </Button>
          </div>
        )}
      />

      {secret ? (
        <Alert tone="warning" icon={<KeyRound size={18} />} className="v3-admin-secret">
          <div className="v3-admin-secret__inner">
            <div className="v3-admin-secret__text">
              {secret.generated ? (
                <>
                  用户 <b>{secret.username}</b> 的临时密码已生成，只显示这一次，请立即转交。
                </>
              ) : (
                <>用户 <b>{secret.username}</b> 已按你填写的初始密码创建。</>
              )}
            </div>
            {secret.generated ? (
              <span className="v3-admin-secret__code">
                <code>{secret.password}</code>
                <IconButton
                  label="复制临时密码"
                  size="sm"
                  icon={<Copy size={14} />}
                  onClick={() => copyPassword(secret.password)}
                />
              </span>
            ) : null}
            <Button variant="text" size="sm" onClick={() => setSecret(null)}>我已记下</Button>
          </div>
        </Alert>
      ) : null}

      <div className="v3-admin-stats">
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><User size={14} />账号总数</span>
          <span className="v3-tile__value">
            {stats.total == null ? <span className="v3-admin-nil">—</span> : (
              <><AnimatedNumber value={stats.total} /><em>个</em></>
            )}
          </span>
          <span className="v3-tile__hint">
            {showDeleted ? `${stats.deleted} 个已删除账号可见` : '默认不含已删除账号'}
          </span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><Shield size={14} />管理员</span>
          <span className="v3-tile__value">
            {stats.admins == null ? <span className="v3-admin-nil">—</span> : (
              <><AnimatedNumber value={stats.admins} /><em>位</em></>
            )}
          </span>
          <span className="v3-tile__hint">拥有后台管理权限的账号</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><Lock size={14} />已禁用</span>
          <span className="v3-tile__value">
            {stats.disabled == null ? <span className="v3-admin-nil">—</span> : (
              <><AnimatedNumber value={stats.disabled} /><em>个</em></>
            )}
          </span>
          <span className="v3-tile__hint">禁用后所有会话立即失效</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><KeyRound size={14} />待改密</span>
          <span className="v3-tile__value">
            {stats.pending == null ? <span className="v3-admin-nil">—</span> : (
              <><AnimatedNumber value={stats.pending} /><em>个</em></>
            )}
          </span>
          <span className="v3-tile__hint">首次登录或重置后的临时密码</span>
        </Tile>
      </div>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            icon={<User size={16} />}
            title="账号列表"
            sub="角色变更即时生效；禁用或删除会立即撤销该用户的全部会话。"
            actions={<Badge tone="outline">{rows ? `${rows.length} 个账号` : '加载中'}</Badge>}
          />
        </div>

        <div className="v3-admin-panel__toolbar">
          <div className="v3-admin-toolbar">
            <div className="v3-admin-toolbar__grow">
              <Input
                icon={<Search size={16} />}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="搜索用户名或显示名"
                aria-label="搜索用户名或显示名"
              />
            </div>
            {q ? <Button variant="text" size="sm" onClick={() => setQ('')}>清空搜索</Button> : null}
            <span className="v3-admin-toolbar__spacer" />
            <div className="v3-admin-toolbar__chips">
              <Chip
                active={showDeleted}
                icon={<Trash size={13} />}
                onClick={() => setShowDeleted((v) => !v)}
                aria-pressed={showDeleted}
                title="包含软删除账号，可随时恢复"
              >
                显示已删除
              </Chip>
            </div>
            <span className="v3-admin-toolbar__meta">
              {loading ? '同步中…' : `${filtered.length} / ${rows?.length || 0} 个账号`}
            </span>
          </div>
        </div>

        {loading ? <TableSkeleton /> : null}

        {!loading && loadErr ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<RefreshCw size={28} />}
              title="用户列表加载失败"
              text={loadErr}
              action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={load}>重试</Button>}
            />
          </div>
        ) : null}

        {!loading && !loadErr && rows && rows.length === 0 ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<User size={30} />}
              title="暂无账号"
              text={showDeleted ? '当前没有账号，也没有已删除账号。' : '创建第一个账号，开始分配角色与权限。'}
              action={<Button variant="filled" icon={<Plus size={15} />} onClick={openCreate}>新建用户</Button>}
            />
          </div>
        ) : null}

        {!loading && !loadErr && rows && rows.length > 0 && filtered.length === 0 ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<Search size={28} />}
              title="没有匹配的账号"
              text={`没有找到包含「${q}」的用户名或显示名。`}
              action={<Button variant="outline" onClick={() => setQ('')}>清空搜索</Button>}
            />
          </div>
        ) : null}

        {!loading && !loadErr && filtered.length > 0 ? (
          <div className="v3-admin-table-wrap">
            <table className="v3-admin-table">
              <thead>
                <tr>
                  <th>用户名</th>
                  <th>显示名</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>最近登录</th>
                  <th className="is-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((u) => {
                  const self = me && u.id === me.id
                  const gone = !!u.deleted_at
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
                              ID {u.id}{gone ? ` · 删除于 ${fmt(u.deleted_at)}` : ''}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className={u.display_name ? undefined : 'is-muted'}>{u.display_name || '—'}</td>
                      <td>
                        <Select
                          className="v3-admin-user-role"
                          aria-label={`${u.username} 的角色`}
                          value={u.role}
                          disabled={gone}
                          onChange={(e) => patch(u, { role: e.target.value }, '角色已更新')}
                          options={Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))}
                        />
                      </td>
                      <td>
                        <div className="v3-admin-user-status">
                          {gone ? (
                            <Badge tone="danger">已删除</Badge>
                          ) : (
                            <Badge tone={u.is_active ? 'success' : 'danger'}>{u.is_active ? '启用' : '已禁用'}</Badge>
                          )}
                          {!gone && u.must_change_password ? <Badge tone="warning">待改密</Badge> : null}
                        </div>
                      </td>
                      <td className="is-nowrap is-muted">{fmt(u.last_login_at)}</td>
                      <td>
                        <div className="v3-admin-user-actions">
                          {gone ? (
                            <Button
                              variant="text"
                              size="sm"
                              icon={<RotateCcw size={14} />}
                              aria-label={`恢复用户 ${u.username}`}
                              onClick={() => restore(u)}
                            >
                              恢复
                            </Button>
                          ) : (
                            <>
                              <Button
                                variant="text"
                                size="sm"
                                icon={u.is_active ? <Lock size={14} /> : <CheckCircle2 size={14} />}
                                disabled={self && u.is_active}
                                title={self && u.is_active ? '不能禁用当前登录账号' : undefined}
                                aria-label={`${u.is_active ? '禁用' : '启用'}用户 ${u.username}`}
                                onClick={() => toggleActive(u)}
                              >
                                {u.is_active ? '禁用' : '启用'}
                              </Button>
                              <Button
                                variant="text"
                                size="sm"
                                icon={<KeyRound size={14} />}
                                aria-label={`重置 ${u.username} 的密码`}
                                onClick={() => resetPassword(u)}
                              >
                                重置密码
                              </Button>
                              <Button
                                variant="text"
                                size="sm"
                                icon={<Trash size={14} />}
                                className="v3-admin-danger-text"
                                disabled={self}
                                title={self ? '不能删除当前登录账号' : undefined}
                                aria-label={`删除用户 ${u.username}`}
                                onClick={() => remove(u)}
                              >
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

        {!loading && !loadErr && filtered.length > 0 ? (
          <div className="v3-admin-q-table-note">
            当前登录账号不能禁用或删除自己；所有破坏性操作都需要二次确认，且会立即撤销目标用户的会话。
          </div>
        ) : null}
      </Card>

      <Dialog
        open={createOpen}
        title="新建用户"
        sub="新账号首次登录须修改密码；留空密码会自动生成一次性临时密码。"
        onClose={busy ? undefined : closeCreate}
        footer={(
          <>
            <Button variant="text" onClick={closeCreate} disabled={busy}>取消</Button>
            <Button type="submit" form="v3-create-user" variant="filled" loading={busy}>创建用户</Button>
          </>
        )}
      >
        <form id="v3-create-user" className="v3-admin-user-form" onSubmit={submitCreate}>
          {formErr ? <Alert tone="danger">{formErr}</Alert> : null}
          <Field label="用户名" hint="2–64 位，可使用字母、数字、下划线、点和短横线。" htmlFor="v3-new-username">
            <Input
              id="v3-new-username"
              ref={usernameRef}
              value={form.username}
              onChange={setField('username')}
              placeholder="如：zhangsan"
              required
              minLength={2}
              maxLength={64}
              pattern="[A-Za-z0-9_.-]+"
              autoComplete="off"
            />
          </Field>
          <Field label="显示名" hint="可选，用于界面展示。" htmlFor="v3-new-display">
            <Input
              id="v3-new-display"
              value={form.display_name}
              onChange={setField('display_name')}
              placeholder="如：张三"
              maxLength={64}
              autoComplete="off"
            />
          </Field>
          <Field label="角色" hint="管理员可进入后台并管理账号。" htmlFor="v3-new-role">
            <Select id="v3-new-role" value={form.role} onChange={setField('role')}>
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
            </Select>
          </Field>
          <Field label="初始密码" hint="留空自动生成；手动填写至少 8 位。" htmlFor="v3-new-password">
            <Input
              id="v3-new-password"
              type="password"
              value={form.password}
              onChange={setField('password')}
              placeholder="留空自动生成"
              minLength={8}
              autoComplete="new-password"
            />
          </Field>
        </form>
      </Dialog>
      {confirmDialog}
    </div>
  )
}
