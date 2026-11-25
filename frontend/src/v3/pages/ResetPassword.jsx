import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi } from '../../api/client'
import { Button, Field, Input } from '../ui'
import { Eye, EyeOff, KeyRound, CheckCircle2, AlertCircle, Shield } from '../icons'
import { passwordCategories } from '../../utils/password'
import { PasswordStrength } from '../ui/PasswordStrength'
import '../styles/pages.css'

/* 重置密码落地页：后端 GET /api/auth/reset-link 校验后把 token 放进 httpOnly
   cookie 并 302 到本页（地址栏不留 token）；也兼容 ?token= 直达与 ?error=invalid。 */
export default function ResetPassword() {
  const [params] = useSearchParams()
  const urlToken = params.get('token') || ''
  const linkError = params.get('error')
  const navigate = useNavigate()
  const [inspect, setInspect] = useState({ phase: 'busy' }) // busy | ok | bad
  const [pwd, setPwd] = useState('')
  const [pwd2, setPwd2] = useState('')
  const [showPwd, setShowPwd] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const checked = useRef(false)

  /* P1（F-06）：title 由 App 的 RouteTitle 从 ROUTE_META 统一派生 */

  useEffect(() => {
    if (checked.current) return
    checked.current = true
    if (linkError) {
      setInspect({ phase: 'bad', message: '重置链接无效、已过期或已被使用。请重新发起找回密码。' })
      return
    }
    authApi.inspectReset(urlToken || undefined)
      .then((r) => {
        if (r?.valid) setInspect({ phase: 'ok', email: r.email_masked || '' })
        else setInspect({ phase: 'bad', message: '重置链接无效、已过期或已被使用。请重新发起找回密码。' })
      })
      .catch((e) => setInspect({ phase: 'bad', message: e?.message || '重置链接校验失败。' }))
  }, [linkError, urlToken])

  const pwdOk = useMemo(() => pwd.length >= 8 && passwordCategories(pwd) >= 3, [pwd])

  const submit = async (e) => {
    e.preventDefault()
    if (!pwdOk) { setError('密码需 8 位以上，且包含大小写字母、数字、特殊字符中的至少 3 类'); return }
    if (pwd !== pwd2) { setError('两次输入的密码不一致'); return }
    setBusy(true)
    setError('')
    try {
      await authApi.resetPassword(pwd, urlToken || undefined)
      setDone(true)
      setTimeout(() => navigate('/login', { replace: true }), 2500)
    } catch (err) {
      setError(err?.message || '重置失败，链接可能已失效，请重新发起找回密码。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="v3-auth-landing">
      <div className="v3-auth-landing__card">
        {inspect.phase === 'busy' ? (
          <div role="status" aria-live="polite">
            <span className="v3-auth-landing__icon is-wait"><KeyRound size={26} /></span>
            <h1>正在校验重置链接…</h1>
            <p>请稍候。</p>
          </div>
        ) : null}

        {done ? (
          <div role="status" aria-live="polite">
            <span className="v3-auth-landing__icon is-ok"><CheckCircle2 size={28} /></span>
            <h1>密码已重置</h1>
            <p>所有设备上的旧登录已失效，即将跳转到登录页，请用新密码登录。</p>
            <Link to="/login"><Button variant="gradient" block>立即登录</Button></Link>
          </div>
        ) : null}

        {!done && inspect.phase === 'bad' ? (
          <div role="alert">
            <span className="v3-auth-landing__icon is-bad"><AlertCircle size={28} /></span>
            <h1>链接不可用</h1>
            <p>{inspect.message}</p>
            <p>重置链接 60 分钟内有效、仅可使用一次；修改过密码后旧链接会自动失效。</p>
            <Link to="/login"><Button variant="outline" block>返回登录，重新找回</Button></Link>
          </div>
        ) : null}

        {!done && inspect.phase === 'ok' ? (
          <>
            <span className="v3-auth-landing__icon is-wait"><Shield size={26} /></span>
            <h1>设置新密码</h1>
            <p>{inspect.email ? `账号：${inspect.email}` : '请为该账号设置一个新密码。'}</p>
            <form className="v3-auth-landing__form" onSubmit={submit} noValidate>
              <Field label="新密码" htmlFor="v3-reset-pwd">
                <div className="v3-login__pwd">
                  <Input
                    id="v3-reset-pwd" type={showPwd ? 'text' : 'password'}
                    autoComplete="new-password" autoFocus
                    placeholder="8 位以上，至少 3 类字符"
                    value={pwd} onChange={(e) => setPwd(e.target.value)}
                  />
                  <button type="button" className="v3-login__eye"
                    aria-label={showPwd ? '隐藏密码' : '显示密码'}
                    onClick={() => setShowPwd((v) => !v)}>
                    {showPwd ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
                <PasswordStrength value={pwd} />
              </Field>
              <Field label="确认新密码" htmlFor="v3-reset-pwd2">
                <Input
                  id="v3-reset-pwd2" type={showPwd ? 'text' : 'password'}
                  autoComplete="new-password" placeholder="再输入一次"
                  value={pwd2} onChange={(e) => setPwd2(e.target.value)}
                />
              </Field>
              {error ? <div className="v3-alert v3-alert--danger" role="alert">{error}</div> : null}
              <Button type="submit" variant="gradient" size="lg" block loading={busy} disabled={!pwdOk || !pwd2}>
                {busy ? '提交中…' : '重置密码'}
              </Button>
            </form>
            <p className="v3-login__sent-tip">重置成功后，所有已登录设备都会被退出，需要用新密码重新登录。</p>
          </>
        ) : null}
      </div>
    </div>
  )
}
