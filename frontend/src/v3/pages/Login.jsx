import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { authApi, goalsApi } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { BrandMark } from '../shell'
import { Button, Field, Input, cx } from '../ui'
import { ScrambleText, Typewriter, useMagnetic, usePointerFx, useParallax, useReducedMotion } from '../motion'
import { Eye, EyeOff, Sparkles, ArrowRight, ChevronLeft, BookOpen, Map, Target, Bot, Mail, KeyRound, CheckCircle2 } from '../icons'
import '../styles/pages.css'
import { crumbName, routeMeta } from '../../nav/navConfig'
import { passwordCategories } from '../../utils/password'
import { PasswordStrength } from '../ui/PasswordStrength'

/* C3（QA-04）：登录页 4 张主视觉卡不宣传需登录的能力 —— 文案不含「AI」字样，
   卡片保持不可点击；AI 能力的「需登录」说明放在卡片列表之后，不占首屏主视觉位。 */
const FEATURES = [
  { icon: Map, title: '院校库', text: '分数线、招生计划、院校对比，一次看清。' },
  { icon: Target, title: '真题题库', text: '按年份与考点刷题，错题自动归集。' },
  { icon: Sparkles, title: '复习规划', text: '每日任务与复习节奏，登录后自动安排。' },
  { icon: Bot, title: '资料文库', text: '资料入库与全文检索，登录后解锁更多能力。' },
]

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

function SentPanel({ icon: Icon, title, text, email, onResend, resendBusy, cooldown, onBack }) {
  return (
    <div className="v3-login__sent">
      <span className="v3-login__sent-icon"><Icon size={26} /></span>
      <h2>{title}</h2>
      <p>{text}</p>
      {email ? <p className="v3-login__sent-mail"><Mail size={14} /> {email}</p> : null}
      <div className="v3-login__sent-actions">
        {onResend ? (
          <Button variant="outline" block loading={resendBusy} disabled={cooldown > 0} onClick={onResend}>
            {cooldown > 0 ? `重新发送（${cooldown}s）` : '没收到？重新发送'}
          </Button>
        ) : null}
        <Button variant="text" block onClick={onBack}>返回登录</Button>
      </div>
      <p className="v3-login__sent-tip">收不到邮件？请检查垃圾箱；本机部署未配置 SMTP 时，邮件在服务器 data/outbox/ 目录。</p>
    </div>
  )
}

export default function Login() {
  const { status, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState('login') // login | register | forgot | sent-verify | sent-reset
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [nickname, setNickname] = useState('')
  const [regPwd, setRegPwd] = useState('')
  const [showPwd, setShowPwd] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  const from = location.state?.from?.pathname || '/'
  const fromName = location.state?.from?.crumb || crumbName(from)

  /* P1（F-06）：document.title 由 App 的 RouteTitle 统一从 ROUTE_META 派生，
     登录页不再自己写一份；回跳提示仍用 fromName（与 title 无关）。 */

  useEffect(() => {
    if (cooldown <= 0) return undefined
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000)
    return () => clearTimeout(t)
  }, [cooldown])

  const regPwdOk = useMemo(() => regPwd.length >= 8 && passwordCategories(regPwd) >= 3, [regPwd])

  const reduced = useReducedMotion()
  const mag = useMagnetic(4)
  const panelFx = usePointerFx({ spotlight: true, disabled: reduced })
  const auroraRef = useParallax(0.1, 30)

  /* busy 期间不早退：submitLogin 登录成功后还要拉 /goals 判断是否首跑，
     若此处提前 <Navigate to={from}> 会抢在判断之前把用户带走 */
  if (status === 'ready' && !busy) return <Navigate to={from} replace />
  if (status === 'must-change') return <Navigate to="/force-change-password" replace />

  const switchMode = (m) => { setMode(m); setError(''); setNotice('') }

  const submitLogin = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入用户名/邮箱和密码')
      return
    }
    setBusy(true)
    setError('')
    try {
      const r = await login(username.trim(), password)
      if (r.must_change_password) {
        navigate('/force-change-password', { replace: true })
        return
      }
      /* 首跑判断：目标档案未配置 → 初始化向导；拉取失败不阻塞登录 */
      let dest = from
      try {
        const g = await goalsApi.list()
        const goal = Array.isArray(g) ? (g[0] || null) : (g || null)
        if (goal && goal.configured === false) dest = '/onboarding'
      } catch { /* 后端目标接口不可达：按原目的地进入 */ }
      navigate(dest, { replace: true })
    } catch (err) {
      setError(err?.message || '登录失败')
    } finally {
      setBusy(false)
    }
  }

  const submitRegister = async (e) => {
    e.preventDefault()
    const mail = email.trim().toLowerCase()
    if (!EMAIL_RE.test(mail)) { setError('请输入正确的邮箱地址'); return }
    if (!regPwdOk) { setError('密码需 8 位以上，且包含大小写字母、数字、特殊字符中的至少 3 类'); return }
    setBusy(true)
    setError('')
    try {
      const r = await authApi.register(mail, regPwd, nickname.trim())
      setNotice(r?.message || '')
      setMode('sent-verify')
      setCooldown(60)
    } catch (err) {
      setError(err?.message || '注册失败')
    } finally {
      setBusy(false)
    }
  }

  const submitForgot = async (e) => {
    e.preventDefault()
    const mail = email.trim().toLowerCase()
    if (!EMAIL_RE.test(mail)) { setError('请输入正确的邮箱地址'); return }
    setBusy(true)
    setError('')
    try {
      const r = await authApi.forgotPassword(mail)
      setNotice(r?.message || '')
      setMode('sent-reset')
    } catch (err) {
      setError(err?.message || '请求失败')
    } finally {
      setBusy(false)
    }
  }

  const resendVerification = async () => {
    setBusy(true)
    try {
      await authApi.resendVerification(email.trim().toLowerCase())
      setCooldown(60)
      setNotice('如果该邮箱可用，验证邮件已发送，请查收（记得看看垃圾箱）。')
    } catch (err) {
      setError(err?.message || '发送失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="v3-login">
      <div className="v3-login__aurora v3-parallax" ref={auroraRef} aria-hidden="true">
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
            <span className="v3-gradient-text"><ScrambleText text="放在同一张地图上。" duration={800} /></span>
          </h1>
          <p className="v3-login__lead">
            <Typewriter text="院校数据、真题练习、AI 规划与个人知识库，一个账号打通备考全过程。" speed={28} startDelay={900} />
          </p>
          <ul className="v3-login__features v3-stagger">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title}>
                <span className="v3-login__feature-icon"><Icon size={17} /></span>
                <span><b>{title}</b><em>{text}</em></span>
              </li>
            ))}
          </ul>
          <p className="v3-login__note"><Bot size={14} /> AI 助手与 AI 问答需登录后使用（卡片不可点击，不占主视觉位）</p>
          <div className="v3-login__note"><BookOpen size={14} /> 完全免费 · 无会员 · 无付费墙</div>
        </section>

        <section className={cx('v3-login__panel', 'v3-spotlight')} {...panelFx}>
          <h1 className="v3-login__mobile-title">{routeMeta('/login').h1}</h1>
          {from && from !== '/' && from !== '/login' && mode === 'login' ? (
            <div className="v3-login__hint">
              <BookOpen size={15} />
              <span>访问「{fromName}」需要登录，登录后自动回到原页面。</span>
              <button type="button" className="v3-login__back-link" onClick={() => navigate(-1)}>
                <ChevronLeft size={13} /> 返回上页
              </button>
            </div>
          ) : null}

          {mode === 'sent-verify' ? (
            <SentPanel
              icon={Mail} title="验证邮件已发送" email={email}
              text={notice || '如果该邮箱可用，验证邮件已发送。点击邮件中的链接完成验证（24 小时内有效）。'}
              onResend={resendVerification} resendBusy={busy} cooldown={cooldown}
              onBack={() => switchMode('login')}
            />
          ) : null}

          {mode === 'sent-reset' ? (
            <SentPanel
              icon={KeyRound} title="重置邮件已发送" email={email}
              text={notice || '如果该邮箱已注册且已验证，重置邮件已发送。链接 60 分钟内有效，仅可使用一次。'}
              onBack={() => switchMode('login')}
            />
          ) : null}

          {mode === 'login' || mode === 'register' || mode === 'forgot' ? (
            <>
              <div className="v3-login__tabs" role="tablist" aria-label="登录或注册">
                <button type="button" role="tab" aria-selected={mode === 'login'}
                  className={mode === 'login' ? 'is-active' : ''} onClick={() => switchMode('login')}>
                  登录
                </button>
                <button type="button" role="tab" aria-selected={mode === 'register'}
                  className={mode === 'register' ? 'is-active' : ''} onClick={() => switchMode('register')}>
                  邮箱注册
                </button>
              </div>

              {mode === 'login' ? (
                <>
                  <div className="v3-login__panel-head">
                    <h2>欢迎回来</h2>
                    <p>登录后继续今天的备考。</p>
                  </div>
                  <form className="v3-login__form" onSubmit={submitLogin} noValidate>
                    <Field label="用户名 / 邮箱" htmlFor="v3-username">
                      <Input
                        id="v3-username"
                        autoComplete="username"
                        autoFocus
                        placeholder="请输入用户名或邮箱"
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
                    <Button {...mag} type="submit" size="lg" variant="gradient" block loading={busy} trailingIcon={<ArrowRight size={17} />}>
                      {busy ? '登录中…' : '登录'}
                    </Button>
                  </form>
                  <div className="v3-login__foot">
                    <button type="button" className="v3-login__linkbtn" onClick={() => switchMode('forgot')}>
                      忘记密码？
                    </button>
                    <Link to="/">返回首页</Link>
                  </div>
                </>
              ) : null}

              {mode === 'register' ? (
                <>
                  <div className="v3-login__panel-head">
                    <h2>创建账号</h2>
                    <p>用邮箱注册，验证后即可上传资料与找回密码。</p>
                  </div>
                  <form className="v3-login__form" onSubmit={submitRegister} noValidate>
                    <Field label="邮箱" htmlFor="v3-reg-email">
                      <Input
                        id="v3-reg-email" type="email" autoComplete="email" autoFocus
                        placeholder="you@example.com"
                        value={email} onChange={(e) => setEmail(e.target.value)}
                      />
                    </Field>
                    <Field label="昵称（可选）" htmlFor="v3-reg-nick">
                      <Input
                        id="v3-reg-nick" autoComplete="nickname" maxLength={64}
                        placeholder="仅用于站内展示"
                        value={nickname} onChange={(e) => setNickname(e.target.value)}
                      />
                    </Field>
                    <Field label="密码" htmlFor="v3-reg-pwd">
                      <div className="v3-login__pwd">
                        <Input
                          id="v3-reg-pwd"
                          type={showPwd ? 'text' : 'password'}
                          autoComplete="new-password"
                          placeholder="8 位以上，至少 3 类字符"
                          value={regPwd} onChange={(e) => setRegPwd(e.target.value)}
                        />
                        <button type="button" className="v3-login__eye"
                          aria-label={showPwd ? '隐藏密码' : '显示密码'}
                          onClick={() => setShowPwd((v) => !v)}>
                          {showPwd ? <EyeOff size={17} /> : <Eye size={17} />}
                        </button>
                      </div>
                      <PasswordStrength value={regPwd} />
                    </Field>
                    {error ? <div className="v3-alert v3-alert--danger" role="alert">{error}</div> : null}
                    <Button {...mag} type="submit" size="lg" variant="gradient" block loading={busy}
                      disabled={!regPwdOk} trailingIcon={<ArrowRight size={17} />}>
                      {busy ? '提交中…' : '注册并发送验证邮件'}
                    </Button>
                  </form>
                  <div className="v3-login__foot">
                    <span>已有账号？</span>
                    <button type="button" className="v3-login__linkbtn" onClick={() => switchMode('login')}>直接登录</button>
                  </div>
                </>
              ) : null}

              {mode === 'forgot' ? (
                <>
                  <div className="v3-login__panel-head">
                    <h2>找回密码</h2>
                    <p>输入注册邮箱，我们会发送一封重置邮件（60 分钟内有效）。</p>
                  </div>
                  <form className="v3-login__form" onSubmit={submitForgot} noValidate>
                    <Field label="注册邮箱" htmlFor="v3-forgot-email">
                      <Input
                        id="v3-forgot-email" type="email" autoComplete="email" autoFocus
                        placeholder="you@example.com"
                        value={email} onChange={(e) => setEmail(e.target.value)}
                      />
                    </Field>
                    {error ? <div className="v3-alert v3-alert--danger" role="alert">{error}</div> : null}
                    <Button {...mag} type="submit" size="lg" variant="gradient" block loading={busy} trailingIcon={<Mail size={17} />}>
                      {busy ? '发送中…' : '发送重置邮件'}
                    </Button>
                  </form>
                  <div className="v3-login__foot">
                    <button type="button" className="v3-login__linkbtn" onClick={() => switchMode('login')}>
                      <ChevronLeft size={13} /> 想起密码了？返回登录
                    </button>
                  </div>
                  <p className="v3-login__sent-tip">
                    <CheckCircle2 size={13} /> 出于安全考虑，无论邮箱是否注册，页面提示都一致；只有已验证邮箱的账号才会收到重置邮件。
                  </p>
                </>
              ) : null}
            </>
          ) : null}
        </section>
      </main>

      <footer className="v3-login__copyright">硕途 · 个人备考平台 · 免费使用</footer>
    </div>
  )
}
