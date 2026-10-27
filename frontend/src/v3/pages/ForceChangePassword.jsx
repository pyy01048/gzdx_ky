import React, { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { Button, Field, Input } from '../ui'
import {
  ArrowRight, BookOpen, CheckCircle2, KeyRound, Lock, Shield, Sparkles,
} from '../icons'
import '../styles/aux-v3.css'

const MIN_LEN = 8

export default function ForceChangePassword() {
  const { status, user, changePassword, logout } = useAuth()
  const navigate = useNavigate()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  /* P1-5：独立页面的 title 同步（应用壳不覆盖此路由） */
  useEffect(() => {
    document.title = '首次登录 · 修改密码 · 硕途考研'
    return () => { document.title = '硕途 · 考研学习平台' }
  }, [])

  if (status === 'anon') return <Navigate to="/login" replace />
  if (status === 'ready') return <Navigate to="/" replace />

  const submit = async (e) => {
    e.preventDefault()
    if (newPassword.length < MIN_LEN) { setError(`新密码至少 ${MIN_LEN} 位`); return }
    if (newPassword !== confirm) { setError('两次输入的新密码不一致'); return }
    setBusy(true)
    setError('')
    try {
      await changePassword(oldPassword, newPassword)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err?.message || '修改失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="v3-aux-auth">
      <div className="v3-aux-aurora" aria-hidden="true">
        <i className="a1" /><i className="a2" /><i className="a3" />
      </div>

      <header className="v3-aux-auth__top">
        <Link to="/" className="v3-aux-brand" aria-label="硕途首页">
          <span className="v3-aux-brand__mark"><Sparkles size={18} /></span>
          <span className="v3-aux-brand__text"><strong>硕途</strong><em>STUDY OS</em></span>
        </Link>
        <span className="v3-aux-security"><Shield size={14} />安全验证</span>
      </header>

      <main className="v3-aux-auth__main">
        <section className="v3-aux-auth__aside">
          <div className="v3-aux-eyebrow"><Lock size={13} /> 首次登录安全校验</div>
          <h1 className="v3-aux-auth__title">
            换一个只有你知道的密码，<br />
            <span className="v3-gradient-text">继续今天的备考。</span>
          </h1>
          <p className="v3-aux-auth__lead">
            当前账号仍在使用初始或重置后的密码。设置新密码后，你的学习记录会立即恢复访问。
          </p>
          <ul className="v3-aux-auth__list">
            <li>
              <span className="v3-aux-auth__list-icon"><KeyRound size={15} /></span>
              <span><b>至少 {MIN_LEN} 位</b><em>长度是服务端校验的第一道门槛</em></span>
            </li>
            <li>
              <span className="v3-aux-auth__list-icon"><Shield size={15} /></span>
              <span><b>不能与当前密码相同</b><em>换一个全新的密码，避免被轻易猜到</em></span>
            </li>
            <li>
              <span className="v3-aux-auth__list-icon"><BookOpen size={15} /></span>
              <span><b>账号与学习记录保持不变</b><em>只更新登录凭据，不影响已有数据</em></span>
            </li>
          </ul>
          <div className="v3-aux-auth__aside-note">
            <CheckCircle2 size={14} />
            修改成功后会自动进入首页
          </div>
        </section>

        <section className="v3-aux-auth__panel">
          <div className="v3-aux-auth__panel-head">
            <span className="v3-aux-auth__panel-icon"><Lock size={20} /></span>
            <div>
              <h2>修改初始密码</h2>
              <p>
                {user?.username ? `账号 ${user.username} ` : ''}使用的是初始或重置后的密码，修改后才能继续使用。
              </p>
            </div>
          </div>

          <form className="v3-aux-auth__form" onSubmit={submit} noValidate>
            <Field label="当前密码" htmlFor="pwd-old">
              <Input
                id="pwd-old"
                type="password"
                autoComplete="current-password"
                autoFocus
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
              />
            </Field>
            <Field
              label="新密码"
              htmlFor="pwd-new"
              hint={`至少 ${MIN_LEN} 位，且不能与当前密码相同`}
            >
              <Input
                id="pwd-new"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </Field>
            <Field label="确认新密码" htmlFor="pwd-confirm">
              <Input
                id="pwd-confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </Field>

            {error ? <div className="v3-alert v3-alert--danger" role="alert">{error}</div> : null}

            <Button
              type="submit"
              variant="gradient"
              size="lg"
              block
              loading={busy}
              trailingIcon={busy ? null : <ArrowRight size={17} />}
            >
              {busy ? '提交中…' : '确认修改'}
            </Button>
            <Button type="button" variant="text" block onClick={logout}>
              退出登录
            </Button>
          </form>

          <div className="v3-aux-auth__foot">
            <Shield size={13} />
            密码由服务端加密保存
          </div>
        </section>
      </main>

      <footer className="v3-aux-auth__copyright">硕途 · 账号安全 · 学习记录始终属于你</footer>
    </div>
  )
}
