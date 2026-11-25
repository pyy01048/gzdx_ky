import React, { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { readAiAnswer } from '../../utils/aiAnswerArchive'
import MathText from '../../components/MathText'
import AiEvidenceCard from '../ai/AiEvidenceCard'
import { Badge, Button, Card, CardHead, Empty, PageHeader, toastErr, toastOk } from '../ui'
import { AlertCircle, ArrowRight, BookOpen, Copy, Database, Sparkles } from '../icons'
import '../styles/detail-pages.css'

export default function AssistantAnswer() {
  const { id } = useParams()
  const [copied, setCopied] = useState(false)
  const record = useMemo(() => readAiAnswer(id), [id])
  const followUp = record
    ? `请结合这条回答继续讲清楚：\n问题：${record.question}\n回答：${record.answer}\n请补充考试中的应用、易错点和验证方法。`
    : ''

  const copy = async () => {
    if (!record) return
    try {
      await navigator.clipboard.writeText(`问题：${record.question}\n\n回答：${record.answer}`)
      setCopied(true)
      toastOk('问题与回答已复制')
    } catch {
      toastErr('复制失败，浏览器未允许剪贴板访问')
    }
  }

  if (!record) {
    return (
      <div className="v3-stack v3-answer-detail">
        <PageHeader eyebrow="AI ANSWER · 证据快照" title="回答与引用详情" sub="当前账号没有找到对应的本地回答记录。" />
        <Card className="v3-detail-state">
          <Empty
            icon={<AlertCircle size={28} />}
            title="当前账号没有这条回答记录"
            text="回答详情仅保存在生成它的账号与本机浏览器中；清除站点数据、切换账号后无法恢复。"
            action={<Link className="v3-btn v3-btn--tonal" to="/assistant">返回 AI 助手</Link>}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="v3-stack v3-answer-detail">
      <nav className="v3-detail-breadcrumb" aria-label="面包屑"><Link to="/assistant">AI 助手</Link><span>/</span><span>回答与引用详情</span></nav>
      <header className="v3-detail-hero">
        <div>
          <span className="v3-eyebrow"><Sparkles size={13} /> AI ANSWER · 证据快照</span>
          <h1>回答与引用详情</h1>
          <p>固定保存这次提问、完整回答和 AI 服务实际返回的引用，不随下一轮对话改变。</p>
        </div>
        <Badge tone="outline">{new Date(record.createdAt).toLocaleString('zh-CN')}</Badge>
      </header>

      <Card>
        <CardHead icon={<BookOpen size={17} />} title="我的问题" />
        <div className="v3-answer-detail__question v3-rp-prose">{record.question || '（问题为空）'}</div>
        <CardHead icon={<Sparkles size={17} />} title="AI 回答" />
        <div className="v3-answer-detail__answer">
          {record.degraded ? <Badge tone="warning">离线资料 · 非模型生成</Badge> : null}
          <MathText className="v3-rp-prose" text={record.answer} />
          <AiEvidenceCard
            title="本次生成信息"
            engine={record.engine || '未提供'}
            model={record.model || '不提供'}
            rag={record.rag}
            hits={record.citations.length}
            elapsedMs={record.elapsedMs}
            degradeReason={record.degraded ? '在线与本地模型均不可用，已降级为知识片段展示' : ''}
          />
        </div>
      </Card>

      <Card className="v3-detail-card">
        <CardHead icon={<Database size={17} />} title={`权威引用（${record.citations.length}）`} sub="来自 AI 服务 meta（元数据）事件" />
        <div className="v3-detail-card__body v3-answer-detail__citations">
          {record.citations.length ? record.citations.map((citation, index) => (
            <AiEvidenceCard
              key={`${citation.chunkId || citation.docId || 'citation'}-${index}`}
              index={index + 1}
              title={citation.title}
              source={citation.source}
              subject={citation.subject}
              docId={citation.docId}
              score={citation.score}
              snippet={citation.content}
            />
          )) : <p className="v3-caption">本次回答没有返回引用，不展示其他轮次的检索结果。</p>}
        </div>
      </Card>

      <div className="v3-answer-detail__actions">
        <Button variant="outline" icon={<Copy size={15} />} onClick={copy}>{copied ? '已复制' : '复制问题与回答'}</Button>
        <Link className="v3-btn v3-btn--gradient" to={`/assistant?q=${encodeURIComponent(followUp)}`}>基于这条回答追问 <ArrowRight size={15} /></Link>
        <Link className="v3-btn v3-btn--text" to="/assistant">返回会话</Link>
      </div>
    </div>
  )
}
