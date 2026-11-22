/**
 * 知识库统一入口（W2 信息架构融合）
 *
 * 「学习文库」（/library · IMA 资料库）与「文档知识库」（/documents · 个人文档）
 * 原本各占一个导航入口、各带一套导入入口，用户要在两处之间来回找资料。
 * 这里只合并 **前端信息架构**：同一页面两个视图（Segmented 切换，?view= 可深链），
 * 底下仍是原来两套后端能力（documents 共享资料库 / 个人文档知识库），不新增后端。
 * 旧链接 /documents 重定向到本页并自动切到「文档知识库」视图。
 *
 * 访客（未登录）没有个人文档库，也不该被个人端点的 401 刷屏 —— 直接只渲染
 * 共享的学习文库，不出第二个 tab。
 */
import React from 'react'
import { useSearchParams } from 'react-router-dom'
import { Segmented } from '../ui'
import { useAuth } from '../../auth/AuthContext'
import Library from './Library'
import Documents from './Documents'

const VIEW_OPTIONS = [
  { value: 'library', label: '学习文库' },
  { value: 'documents', label: '文档知识库' },
]

export default function KnowledgeHome() {
  const [params, setParams] = useSearchParams()
  const { user } = useAuth()
  const view = params.get('view') === 'documents' ? 'documents' : 'library'

  if (!user) return <Library />

  const setView = (v) => {
    const next = new URLSearchParams(params)
    if (v === 'documents') next.set('view', 'documents')
    else next.delete('view')
    setParams(next, { replace: true })
  }

  return (
    <div className="v3-stack" style={{ gap: 14 }}>
      <Segmented options={VIEW_OPTIONS} value={view} onChange={setView} ariaLabel="知识库视图" />
      {view === 'documents' ? <Documents /> : <Library />}
    </div>
  )
}
