import React from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../ui'
import { AlertCircle, ArrowRight, Lock, Shield } from '../icons'
import '../styles/aux-v3.css'

export default function Forbidden() {
  return (
    <div className="v3-aux-standalone v3-forbidden">
      <div className="v3-aux-aurora" aria-hidden="true">
        <i className="a1" /><i className="a2" /><i className="a3" />
      </div>

      <Card className="v3-forbidden-card">
        <div className="v3-forbidden-watermark" aria-hidden="true">403</div>

        <span className="v3-forbidden-orb" aria-hidden="true">
          <Shield size={34} />
          <span className="v3-forbidden-orb__dot"><AlertCircle size={15} /></span>
        </span>

        <div className="v3-aux-eyebrow"><Lock size={13} /> 403 · 权限不足</div>
        <h1 className="v3-forbidden-title">没有访问权限</h1>
        <p className="v3-forbidden-text">
          该页面仅管理员可用。如需使用，请联系管理员调整账号角色。
        </p>

        <div className="v3-forbidden-actions">
          <Link className="v3-btn v3-btn--gradient v3-forbidden-home" to="/">
            返回首页
            <ArrowRight size={16} />
          </Link>
        </div>

        <div className="v3-forbidden-note">
          <Shield size={14} />
          权限由账号角色控制 · 如刚调整角色，请重新登录
        </div>
      </Card>
    </div>
  )
}
