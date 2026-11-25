import React, { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../../api/client'
import { Button } from '../ui'
import { CheckCircle2, AlertCircle, Mail } from '../icons'
import '../styles/pages.css'

/* 邮箱验证落地页：邮件链接 /verify-email?token=... 指向这里。
   token 只在挂载时消费一次（StrictMode 双调用用 ref 挡住）。 */
export default function VerifyEmail() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [state, setState] = useState({ phase: token ? 'busy' : 'missing', message: '' })
  const consumed = useRef(false)

  useEffect(() => {
    /* P1（F-06）：title 由 App 的 RouteTitle 从 ROUTE_META 统一派生 */
    if (!token || consumed.current) return
    consumed.current = true
    authApi.verifyEmail(token)
      .then((r) => setState({ phase: 'ok', message: r?.message || '邮箱验证成功。' }))
      .catch((e) => setState({ phase: 'bad', message: e?.message || '验证链接无效或已过期。' }))
  }, [token])

  return (
    <div className="v3-auth-landing">
      <div className="v3-auth-landing__card" role="status" aria-live="polite">
        {state.phase === 'busy' ? (
          <>
            <span className="v3-auth-landing__icon is-wait"><Mail size={26} /></span>
            <h1>正在验证邮箱…</h1>
            <p>请稍候，正在确认你的验证链接。</p>
          </>
        ) : null}
        {state.phase === 'ok' ? (
          <>
            <span className="v3-auth-landing__icon is-ok"><CheckCircle2 size={28} /></span>
            <h1>邮箱验证成功</h1>
            <p>{state.message}</p>
            <Link to="/login"><Button variant="gradient" block>去登录</Button></Link>
          </>
        ) : null}
        {state.phase === 'bad' || state.phase === 'missing' ? (
          <>
            <span className="v3-auth-landing__icon is-bad"><AlertCircle size={28} /></span>
            <h1>{state.phase === 'missing' ? '缺少验证参数' : '验证失败'}</h1>
            <p>{state.phase === 'missing' ? '请从验证邮件中的链接进入本页面。' : state.message}</p>
            <p>链接有效期 24 小时。过期可在登录页选择「邮箱注册」重新提交同一邮箱，系统会补发验证邮件。</p>
            <Link to="/login"><Button variant="outline" block>返回登录</Button></Link>
          </>
        ) : null}
      </div>
    </div>
  )
}
