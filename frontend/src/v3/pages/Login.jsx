import React, { useEffect, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { BrandMark } from '../shell'
import { Button, Field, Input } from '../ui'
import { Eye, EyeOff, Sparkles, ArrowRight, ChevronLeft, BookOpen, Map, Target, Bot } from '../icons'
import '../styles/pages.css'
import { crumbName } from '../../nav/navConfig'

const FEATURES = [
  { icon: Map, title: '院校库', text: '分数线、招生计划、院校对比，一次看清。' },
  { icon: Target, title: '真题题库', text: '按年份与考点刷题，错题自动归集。' },
  { icon: Sparkles, title: 'AI 规划', text: '每日任务与复习节奏自动安排。' },
  { icon: Bot, title: '知识库', text: '资料入库、全文检索、AI 问答。' },
]

export default function Login() {
  const { status, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPwd, setShowPwd] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const from = location.state?.from?.pathname || '/'
  const fromName = location.state?.from?.crumb || crumbName(from)

  /* P1-5：登录页独立于应用壳，路由切换不会触发壳内的 title 同步 */
  useEffect(() => {
    document.title = from && from !== '/' && from !== '/login'
      ? `登录 · ${fromName} · 硕途考研`
      : '登录 · 硕途考研'
    return () => { document.title = '硕途 · 考研学习平台' }
  }, [from, fromName])

  if (status === 'ready') return <Navigate to={from} replace />
  if (status === 'must-change') return <Navigate to="/force-change-password" replace />

  const submit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setBusy(true)
    setError('')
    try {
      const r = await login(username.trim(), password)
      navigate(r.must_change_password ? '/force-change-password' : from, { replace: true })
    } catch (err) {
      setError(err?.message || '登录失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="v3-login">
      <div className="v3-login__aurora" aria-hidden="true">
        <i className="a1" /><i className="a2" /><i className="a3" />
      </div>

      <header className="v3-login__top">
        <Link to="/" className="v3-login__brand">
          <BrandMark size={34} />
          <span><strong>硕途</strong><em>STUDY OS</em></span>
        </Link>
        <Link to="/kaoyan" className="v3-login__back">先随便看看 <ArrowRight size={14} /></Link>
      </header>

      <main className="v3-login__shell">
        <section className="v3-login__aside">
          <div className="v3-login__eyebrow"><Sparkles size={14} /> 从择校到冲刺，同一张地图</div>
          <h1 className="v3-login__title">
            把考研的每一步，<br />
            <span className="v3-gradient-text">放在同一张地图上。</span>
          </h1>
          <p className="v3-login__lead">
            院校数据、真题练习、AI 规划与个人知识库，一个账号打通备考全过程。
          </p>
          <ul className="v3-login__features">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title}>
                <span className="v3-login__feature-icon"><Icon size={17} /></span>
                <span><b>{title}</b><em>{text}</em></span>
              </li>
            ))}
          </ul>
          <div className="v3-login__note"><BookOpen size={14} /> 完全免费 · 无会员 · 无付费墙</div>
        </section>

        <section className="v3-login__panel">
          {from && from !== '/' && from !== '/login' ? (
            <div className="v3-login__hint">
              <BookOpen size={15} />
              <span>访问「{fromName}」需要登录，登录后自动回到原页面。</span>
              <button type="button" className="v3-login__back-link" onClick={() => navigate(-1)}>
                <ChevronLeft size={13} /> 返回上页
              </button>
            </div>
          ) : null}
          <div className="v3-login__panel-head">
            <h2>欢迎回来</h2>
            <p>登录后继续今天的备考。</p>
          </div>
          <form className="v3-login__form" onSubmit={submit} noValidate>
            <Field label="用户名" htmlFor="v3-username">
              <Input
                id="v3-username"
                autoComplete="username"
                autoFocus
                placeholder="请输入用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </Field>
            <Field label="密码" htmlFor="v3-password">
              <div className="v3-login__pwd">
                <Input
                  id="v3-password"
                  type={showPwd ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="请输入密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  className="v3-login__eye"
                  aria-label={showPwd ? '隐藏密码' : '显示密码'}
                  onClick={() => setShowPwd((v) => !v)}
                >
                  {showPwd ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </Field>
            {error ? <div className="v3-alert v3-alert--danger" role="alert">{error}</div> : null}
            <Button type="submit" size="lg" variant="gradient" block loading={busy} trailingIcon={<ArrowRight size={17} />}>
              {busy ? '登录中…' : '登录'}
            </Button>
          </form>
          <div className="v3-login__foot">
            <span>忘记密码请联系管理员重置</span>
            <Link to="/">返回首页</Link>
          </div>
        </section>
      </main>

      <footer className="v3-login__copyright">硕途 · 个人备考平台 · 免费使用</footer>
    </div>
  )
}
