import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorsApi } from '../../api/client'
import useStore from '../../store/useStore'
import { ukey } from '../../utils/userKeys'
import MathText from '../../components/MathText'
import AiEvidenceCard, { ConfidenceBadge } from '../ai/AiEvidenceCard'
import { AiFeedbackBar, resolveAttributionReason, shouldKeepAiTag } from './ErrorReview'
import {
  Alert, Badge, Button, Card, CardHead, Empty, PageHeader, Spinner, Textarea, Tile, toast,
} from '../ui'
import {
  AlertCircle, ArrowRight, BookOpen, Brain, CheckCircle2, ExternalLink,
  RefreshCw, Target, Wand,
} from '../icons'
import '../styles/review-pages.css'
import '../styles/detail-pages.css'

const FEEDBACK_KEY = 'kaoyan-ai-attribution-feedback-v1'
const blankAi = { state: 'idle', text: '', error: '', meta: null }

/** 读取本账号 AI 归因反馈记录（按 uid 隔离）。 */
function readFeedback() {
  try { return JSON.parse(localStorage.getItem(ukey(FEEDBACK_KEY)) || '{}') } catch { return {} }
}

/**
 * 错题单题工作台：从错因定位到知识点、AI 讲解与复练，保留在同一条可分享链路里。
 * 数据源：errorsApi.get / knowledgePoints / aiAnalyze。
 * @returns {JSX.Element} 错题详情页
 */
export default function ErrorDetail() {
  const { id } = useParams()
  const addNote = useStore((s) => s.addNote)
  const [record, setRecord] = useState(null)
  const [state, setState] = useState('loading')
  const [error, setError] = useState('')
  const [kps, setKps] = useState({ state: 'loading', items: [], error: '' })
  const [ai, setAi] = useState(blankAi)
  const [feedback, setFeedback] = useState(readFeedback)
  const [rewrite, setRewrite] = useState('')
  const seq = useRef(0)
  const aiSeq = useRef(0)

  /** 加载错题详情与关联知识点，使用 seq 防止竞态。 */
  const load = useCallback(async () => {
    const current = ++seq.current
    aiSeq.current += 1
    setState('loading')
    setError('')
    setAi(blankAi)
    setKps({ state: 'loading', items: [], error: '' })
    try {
      const row = await errorsApi.get(id)
      if (current !== seq.current) return
      setRecord(row)
      setState('ok')
      try {
        const linked = await errorsApi.knowledgePoints(id)
        if (current !== seq.current) return
        setKps({ state: 'ok', items: Array.isArray(linked?.items) ? linked.items : [], error: '' })
      } catch (e) {
        if (current === seq.current) setKps({ state: 'error', items: [], error: e?.message || '知识点关联加载失败' })
      }
    } catch (e) {
      if (current !== seq.current) return
      setRecord(null)
      setError(e?.message || '错题加载失败')
      setState(e?.status === 404 ? 'missing' : 'error')
    }
  }, [id])

  useEffect(() => { load() }, [load])

  /** 触发 AI 归因分析并刷新本地缓存。 */
  const analyze = useCallback(async () => {
    if (!record) return
    const current = ++aiSeq.current
    setAi({ ...blankAi, state: 'loading' })
    try {
      const result = await errorsApi.aiAnalyze(id)
      if (current !== aiSeq.current) return
      setAi({ state: 'ok', text: result?.analysis || '接口已返回，但没有可展示的分析文本。', error: '', meta: result || {} })
      setRecord((prev) => prev ? { ...prev, analysis: result?.analysis || prev.analysis } : prev)
      const next = { ...feedback }
      delete next[id]
      setFeedback(next)
      try { localStorage.setItem(ukey(FEEDBACK_KEY), JSON.stringify(next)) } catch { /* 隐私模式 */ }
      setRewrite('')
    } catch (e) {
      if (current === aiSeq.current) setAi({ ...blankAi, state: 'error', error: e?.message || 'AI 分析失败' })
    }
  }, [record, id, feedback])

  /** 记录用户对 AI 归因的三态反馈。 */
  const evaluate = useCallback((kind) => {
    const next = { ...feedback, [id]: { kind, at: Date.now(), text: ai.text } }
    setFeedback(next)
    if (kind === 'wrong') setRewrite(ai.text)
    try { localStorage.setItem(ukey(FEEDBACK_KEY), JSON.stringify(next)) } catch { /* 隐私模式 */ }
    toast(`已记录：${kind === 'accurate' ? '准确' : kind === 'partial' ? '部分准确' : '错误'}`)
  }, [feedback, id, ai.text])

  /** 确认记入错题本：未经用户确认不覆盖人工 reason。 */
  const saveReason = useCallback(() => {
    if (!record || !feedback[id]?.kind) {
      toast('请先评价 AI 归因，确认前不会覆盖人工错因')
      return
    }
    const keepAi = shouldKeepAiTag(feedback[id].kind)
    addNote({
      question: record.content || '',
      answer: record.correct_answer || '',
      analysis: ai.text || record.analysis || '',
      reason: resolveAttributionReason({
        aiText: ai.text,
        feedback: feedback[id].kind,
        rewriteText: rewrite,
        humanReason: record.error_reason || '',
      }),
      subject: record.subject || '',
      tags: keepAi ? ['AI归因'] : ['人工复核'],
    })
    toast(keepAi ? '已记入错题本' : '人工改写已记入错题本，AI 归因标记已失效')
  }, [record, feedback, id, ai.text, rewrite, addNote])

  const followUp = useMemo(() => {
    if (!record) return ''
    return `请讲解这道错题，并给出易错点和一道同类练习：\n${record.content || ''}\n我的答案：${record.my_answer || '—'}\n正确答案：${record.correct_answer || '—'}`
  }, [record])

  if (state === 'loading') {
    return <div className="v3-detail-loading" role="status"><Spinner size={22} /><span>正在加载错题详情…</span></div>
  }

  if (state !== 'ok' || !record) {
    return (
      <div className="v3-stack v3-detail-page">
        <PageHeader eyebrow="ERROR REVIEW · 单题工作台" title="错题详情" sub={state === 'loading' ? '正在读取这条错题…' : '查看记录状态并返回错题复盘。'} />
        <Card className="v3-detail-state">
          <Empty
            icon={<AlertCircle size={28} />}
            title={state === 'missing' ? '这条错题不存在或不属于当前账号' : '错题详情加载失败'}
            text={state === 'missing' ? '记录可能已被删除，或链接属于其他账号。' : error}
            action={<div className="v3-row"><Link className="v3-btn v3-btn--tonal" to="/error-review">返回错题复盘</Link>{state === 'error' ? <Button icon={<RefreshCw size={15} />} onClick={load}>重试</Button> : null}</div>}
          />
        </Card>
      </div>
    )
  }

  const meta = ai.meta || {}
  return (
    <div className="v3-stack v3-detail-page">
      <nav className="v3-detail-breadcrumb" aria-label="面包屑">
        <Link to="/error-review">错题复盘</Link><span>/</span><span>错题 #{record.id}</span>
      </nav>
      <header className="v3-detail-hero">
        <div>
          <span className="v3-eyebrow">ERROR REVIEW · 单题工作台</span>
          <h1>错题详情与 AI 加固</h1>
          <p>从错因定位到知识点、AI 讲解与复练，保留在同一条可分享链路里。</p>
        </div>
        <div className="v3-detail-hero__badges">
          <Badge tone="outline">{record.subject || '未分类'}</Badge>
          <Badge tone="warning">{record.mastery_label || '掌握度未提供'}</Badge>
          <Badge tone={record.status === 'graduated' ? 'success' : 'primary'}>{record.status === 'graduated' ? '已毕业' : record.status === 'archived' ? '已归档' : '在练'}</Badge>
        </div>
      </header>

      <div className="v3-detail-grid">
        <main className="v3-detail-main">
          <Card className="v3-detail-card">
            <CardHead icon={<BookOpen size={17} />} title="题目与答案" sub={`记录 #${record.id}`} />
            <div className="v3-detail-card__body">
              <MathText className="v3-rp-prose v3-detail-question" text={record.content || '（题干为空）'} />
              <div className="v3-detail-answers">
                <div><span>我的答案</span><MathText className="v3-rp-prose" text={record.my_answer || '—'} /></div>
                <div><span>正确答案</span><MathText className="v3-rp-prose" text={record.correct_answer || '—'} /></div>
              </div>
              <dl className="v3-detail-facts">
                <div><dt>人工错因</dt><dd>{record.error_reason || '—'}</dd></div>
                <div><dt>正确率</dt><dd>{record.accuracy == null ? '—' : `${Math.round(Number(record.accuracy) * 100)}%`}</dd></div>
                <div><dt>复习次数</dt><dd>{record.review_count ?? '—'}</dd></div>
                <div><dt>下次复习</dt><dd>{record.next_review ? new Date(record.next_review).toLocaleString('zh-CN') : '—'}</dd></div>
              </dl>
            </div>
          </Card>

          <Card className="v3-detail-card">
            <CardHead
              icon={<Brain size={17} />}
              title="AI 归因与加固"
              sub="AI 结论独立展示，确认前不覆盖人工错因"
              actions={<Button variant="gradient" size="sm" icon={<Wand size={15} />} loading={ai.state === 'loading'} disabled={ai.state === 'loading'} onClick={analyze}>{ai.state === 'loading' ? '分析中…' : record.analysis ? '重新分析' : '开始 AI 归因'}</Button>}
            />
            <div className="v3-detail-card__body">
              {ai.state === 'loading' ? <div className="v3-detail-loading" role="status"><Spinner size={18} /><span>正在定位错因与薄弱知识点…</span></div> : null}
              {ai.state === 'error' ? <Alert tone="danger">{ai.error}</Alert> : null}
              {ai.state === 'ok' ? (
                <div className="v3-detail-ai">
                  <div className="v3-detail-tags">
                    {meta.category ? <Badge tone="warning">错因 {meta.category}</Badge> : null}
                    {meta.knowledge_point ? <Badge tone="primary">考点 {meta.knowledge_point}</Badge> : null}
                    <ConfidenceBadge confidence={meta.confidence} />
                  </div>
                  <MathText className="v3-rp-prose" text={ai.text} />
                  {meta.suggestion ? <div className="v3-detail-callout"><strong>纠正建议</strong><MathText className="v3-rp-prose" text={meta.suggestion} /></div> : null}
                  <AiEvidenceCard title="AI 归因证据" confidence={meta.confidence} engine={meta.engine || '未提供'} model={meta.model || '不提供'} fields={[['错因分类', meta.category || '暂无记录'], ['知识点', meta.knowledge_point || '暂无记录']]} />
                  <AiFeedbackBar value={feedback[id]?.kind || null} onChange={evaluate} />
                  {feedback[id]?.kind === 'wrong' ? <Textarea rows={3} aria-label="改写后的错因" value={rewrite} placeholder="写下你认可的人工错因…" onChange={(e) => setRewrite(e.target.value)} /> : null}
                  <div className="v3-row">
                    <Button variant="outline" size="sm" onClick={saveReason}>确认记入错题本</Button>
                    <Link className="v3-btn v3-btn--tonal v3-btn--sm" to={`/assistant?q=${encodeURIComponent(followUp)}`}>继续追问 AI <ArrowRight size={14} /></Link>
                  </div>
                  {Array.isArray(meta.practice_questions) && meta.practice_questions.length ? (
                    <section className="v3-detail-practice">
                      <h3>推荐复练</h3>
                      {meta.practice_questions.map((p, i) => (
                        <details key={p.question_id ?? i}><summary><Badge tone="outline">练习 {i + 1}</Badge><span>{p.content || '题目内容为空'}</span></summary><div><MathText className="v3-rp-prose" text={p.answer || '—'} /></div></details>
                      ))}
                    </section>
                  ) : null}
                </div>
              ) : record.analysis ? (
                <div className="v3-detail-callout"><strong>已有分析</strong><MathText className="v3-rp-prose" text={record.analysis} /></div>
              ) : (
                <Empty icon={<Brain size={26} />} title="还没有 AI 归因" text="可先人工标注错因，也可以让 AI 给出分类、纠正建议和复练方向。" action={<Button variant="tonal" size="sm" onClick={analyze}>开始分析</Button>} />
              )}
            </div>
          </Card>
        </main>

        <aside className="v3-detail-side">
          <Card className="v3-detail-card">
            <CardHead icon={<Target size={17} />} title="关联知识点" sub={`${kps.items.length} 条关联`} />
            <div className="v3-detail-card__body v3-stack">
              {kps.state === 'loading' ? <Spinner size={18} /> : null}
              {kps.state === 'error' ? <Alert tone="warning">{kps.error}</Alert> : null}
              {kps.state === 'ok' && !kps.items.length ? <p className="v3-caption">尚未关联知识点，可在错题复盘页手动挂接。</p> : null}
              {kps.items.map((kp) => {
                const kpId = kp.knowledge_point_id ?? kp.id
                const content = (
                  <span><strong>{kp.name || '未命名知识点'}</strong><small>{[kp.subject, kp.chapter].filter(Boolean).join(' · ') || '章节未提供'}</small></span>
                )
                return kpId == null || kpId === '' ? (
                  <div className="v3-detail-kp" key={kpId ?? kp.name}>{content}</div>
                ) : (
                  <Link className="v3-detail-kp" key={kpId} to={`/knowledge/${kpId}`}>
                    {content}
                    <ExternalLink size={15} />
                  </Link>
                )
              })}
            </div>
          </Card>
          <Tile className="v3-detail-next">
            <CheckCircle2 size={22} />
            <h3>下一步</h3>
            <p>先完成 AI 归因，再按建议复练同类题；已经掌握的记录可在错题复盘页标记毕业。</p>
            <Link className="v3-btn v3-btn--outline" to={`/quiz?subject=${encodeURIComponent(record.subject || '')}`}>去刷题巩固 <ArrowRight size={15} /></Link>
          </Tile>
        </aside>
      </div>
    </div>
  )
}
