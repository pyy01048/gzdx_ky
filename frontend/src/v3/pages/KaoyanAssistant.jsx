import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { aiApi } from '../../api/client'
import { kaoyanApi } from '../../api/kaoyanApi'
import { useAuth } from '../../auth/AuthContext'
import useStore from '../../store/useStore'
import {
  Alert, Badge, Button, Chip, Empty, IconButton, PageHeader, Tile,
} from '../ui'
import {
  ArrowRight, Bot, Brain, Database, Lightbulb, RotateCcw, Send, Sparkles, User,
} from '../icons'
import '../styles/kaoyan-aux-v3.css'

const GREETING = '你好！我是考研择校 AI 助手。你可以问我分数线、院校推荐、复录比、招生人数等问题。试试点击下方预设问题，或直接输入你的问题。'
const AI_SYSTEM_PROMPT = '你是考研择校顾问，请基于下方引擎结论做简洁深度解读，给出选校策略建议。用中文，3-5 句话。'
const UNVERIFIED_RE = /分数线|复录比|招生|拟招|录取/

function num(value, digits = 0) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return digits ? n.toFixed(digits) : String(Math.round(n))
}

function ParsedConditions({ parsed }) {
  if (!parsed) return null
  const chips = []
  if (parsed.score) chips.push({ key: 'score', label: `${parsed.score} 分` })
  if (parsed.level) chips.push({ key: 'level', label: parsed.level })
  if (parsed.province) chips.push({ key: 'province', label: parsed.province })
  if (parsed.retest_intent) chips.push({ key: 'retest', label: '关注复录比' })
  if (parsed.admission_intent) chips.push({ key: 'admission', label: '关注招生人数' })
  if (!chips.length) return null
  return (
    <div className="v3-ky-msg__parsed">
      <span>解析条件</span>
      {chips.map((chip) => <em key={chip.key}>{chip.label}</em>)}
    </div>
  )
}

function Recommendations({ items }) {
  if (!Array.isArray(items) || !items.length) return null
  return (
    <div className="v3-ky-msg__recs">
      <span className="v3-ky-msg__recs-label"><Sparkles size={13} /> 推荐院校</span>
      <div className="v3-ky-msg__recs-grid">
        {items.map((item, index) => {
          const body = (
            <>
              <b>{item.name || '未命名院校'}</b>
              <span>{item.level || '层级未标注'} · {item.province || '省份未标注'}</span>
              <em>
                {item.total_line != null ? `线 ${item.total_line} · ` : ''}
                {item.gap != null ? `分差 ${Number(item.gap) > 0 ? '+' : ''}${item.gap}` : `综合分 ${item.score ?? '—'}`}
              </em>
            </>
          )
          return item.school_id ? (
            <Link key={`${item.school_id}-${index}`} className="v3-ky-msg__rec" to={`/kaoyan/schools/${item.school_id}`}>
              {body}
              <ArrowRight size={13} />
            </Link>
          ) : (
            <div key={`${item.name}-${index}`} className="v3-ky-msg__rec is-static">{body}</div>
          )
        })}
      </div>
    </div>
  )
}

function Message({ message }) {
  const isUser = message.role === 'user'
  const isAi = message.kind === 'ai' || message.kind === 'ai-error'
  const isError = message.kind === 'error' || message.kind === 'ai-error'

  if (isUser) {
    return (
      <div className="v3-ky-msg v3-ky-msg--user">
        <div className="v3-ky-msg__bubble">
          <p>{message.content}</p>
        </div>
        <span className="v3-ky-msg__avatar v3-ky-msg__avatar--user" aria-hidden="true"><User size={16} /></span>
      </div>
    )
  }

  return (
    <div className={`v3-ky-msg v3-ky-msg--assistant${isAi ? ' is-ai' : ''}${isError ? ' is-error' : ''}`}>
      <span className="v3-ky-msg__avatar" aria-hidden="true">
        {isAi ? <Sparkles size={16} /> : <Bot size={17} />}
      </span>
      <div className="v3-ky-msg__body">
        <div className="v3-ky-msg__label">
          {isAi ? <><Brain size={12} /> AI 深度解读</> : <><Database size={12} /> 择校引擎</>}
          {message.kind === 'ai-error' ? <em>降级提示</em> : null}
        </div>
        <div className="v3-ky-msg__bubble">
          <p>{message.content}</p>
        </div>
        {!isAi ? <ParsedConditions parsed={message.parsed} /> : null}
        {!isAi ? <Recommendations items={message.recommendations} /> : null}
      </div>
    </div>
  )
}

export default function KaoyanAssistant() {
  const { user } = useAuth()
  const myMajor = useStore((s) => s.settings.major)
  const [messages, setMessages] = useState(() => [{
    id: 0, role: 'assistant', kind: 'engine', content: GREETING,
  }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [phase, setPhase] = useState('')
  const [stats, setStats] = useState(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsError, setStatsError] = useState('')
  const scrollRef = useRef(null)
  const inputRef = useRef(null)
  const idRef = useRef(1)

  const nextId = () => {
    const id = idRef.current
    idRef.current += 1
    return id
  }

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    setStatsError('')
    try {
      const d = await kaoyanApi.stats()
      setStats(d || null)
    } catch (e) {
      setStatsError(e?.message || '统计数据加载失败')
      setStats(null)
    } finally {
      setStatsLoading(false)
    }
  }, [])

  useEffect(() => { loadStats() }, [loadStats])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, loading, phase])

  const presets = [
    '推荐几所稳妥的学校',
    '哪些985院校复录比较低？',
    myMajor ? `${myMajor}专业哪些学校招生人数多？` : '我报考的专业哪些学校招生人数多？',
    '帮我分析北京地区的院校难度',
  ]

  const send = async (raw) => {
    const text = String(raw || '').trim()
    if (!text || loading) return
    setMessages((prev) => [...prev, { id: nextId(), role: 'user', content: text }])
    setInput('')
    setLoading(true)
    setPhase('engine')

    try {
      const res = await kaoyanApi.assistantQuery(text)
      const recs = Array.isArray(res?.recommendations) ? res.recommendations : []
      const content = res?.answer || '抱歉，暂时无法回答这个问题。'
      setMessages((prev) => [...prev, {
        id: nextId(),
        role: 'assistant',
        kind: 'engine',
        content,
        recommendations: recs,
        parsed: res?.parsed || null,
      }])

      setPhase('ai')
      try {
        const aiRes = await aiApi.chat({
          messages: [
            { role: 'system', content: AI_SYSTEM_PROMPT },
            { role: 'user', content: `问题：${text}\n\n引擎结论：\n${content}` },
          ],
          use_rag: false,
        })
        const reply = aiRes?.reply || aiRes?.content
        if (reply) {
          const reliesOnUnverified = recs.length > 0 || UNVERIFIED_RE.test(content)
          const sourceNote = reliesOnUnverified ? '\n\n数据来源：第三方聚合，未核验' : ''
          setMessages((prev) => [...prev, {
            id: nextId(),
            role: 'assistant',
            kind: 'ai',
            content: `【AI 深度解读】\n${reply}${sourceNote}`,
          }])
        }
      } catch (e) {
        const hint = e?.status === 502
          ? '\n常见原因：AI 服务商 API Key 未配置/失效，或本地 Ollama 未启动（详见「设置 → AI 服务」）。'
          : ''
        setMessages((prev) => [...prev, {
          id: nextId(),
          role: 'assistant',
          kind: 'ai-error',
          content: `【AI 深度解读】暂时不可用：${e?.message || '未知错误'}${hint}\n\n上面的择校结论来自本地引擎，可正常使用。`,
        }])
      }
    } catch (e) {
      setMessages((prev) => [...prev, {
        id: nextId(),
        role: 'assistant',
        kind: 'error',
        content: `出错了：${e?.message || '择校引擎暂时不可用，请稍后重试。'}`,
      }])
    } finally {
      setLoading(false)
      setPhase('')
      if (inputRef.current) inputRef.current.focus()
    }
  }

  const resetChat = () => {
    if (loading) return
    setMessages([{ id: 0, role: 'assistant', kind: 'engine', content: GREETING }])
    setInput('')
    if (inputRef.current) inputRef.current.focus()
  }

  if (!user) {
    return (
      <div className="v3-stack v3-ky">
        <PageHeader
          eyebrow="ASSISTANT · 登录可用"
          title="择校 AI 助手"
          sub="登录后即可结合本地院校库提问，问题与推荐结果仅在你的账号内使用"
          actions={<Link className="v3-btn v3-btn--gradient" to="/login">去登录 <ArrowRight size={15} /></Link>}
        />
        <Tile span={12} className="v3-ky-chat-gate">
          <Empty
            icon={<Bot size={28} />}
            title="登录后使用择校助手"
            text="助手会读取本地院校库的分数线、复录比与招生数据来回答你的问题，需要登录账号。"
            action={<Link className="v3-btn v3-btn--gradient" to="/login">登录账号</Link>}
          />
        </Tile>
      </div>
    )
  }

  const phaseText = phase === 'ai' ? '正在生成 AI 深度解读…' : phase === 'engine' ? '正在检索院校库与分数线…' : 'AI 思考中…'

  return (
    <div className="v3-stack v3-ky">
      <PageHeader
        eyebrow="ASSISTANT · 自然语言择校"
        title="择校 AI 助手"
        sub={stats
          ? `本地库 ${stats.school_count ?? 0} 所院校 · ${stats.major_count ?? 0} 个专业 · ${stats.scoreline_records ?? 0} 条分数线记录`
          : statsError ? '数据概览加载失败，问答仍可使用' : '读取本地院校库，按你的问题给出可核验的择校结论'}
        actions={(
          <>
            <IconButton
              label="重新开始对话"
              icon={<RotateCcw size={17} />}
              onClick={resetChat}
              disabled={loading}
            />
            <Link className="v3-btn v3-btn--tonal" to="/kaoyan/recommend">
              打开推荐页 <ArrowRight size={15} />
            </Link>
          </>
        )}
      />

      <Tile span={12} variant="hero" className="v3-ky-hero">
        <div className="v3-ky-hero__body">
          <div className="v3-ky-hero__copy">
            <span className="v3-eyebrow v3-ky-hero__eyebrow"><Sparkles size={13} /> 本地引擎 + AI 解读</span>
            <h2>把「我能上哪」，<br />直接问出来。</h2>
            <p>
              先用本地择校引擎检索真实分数线、复录比与招生记录，再按需叠加 AI 深度解读。
              引擎结论始终可见，AI 只是补充，不会替代可核验的数据。
            </p>
            <div className="v3-ky-hero__actions">
              <span className="v3-ky-hero__pill"><Database size={14} /> 本地数据优先</span>
              <span className="v3-ky-hero__pill"><Brain size={14} /> AI 解读可降级</span>
              <span className="v3-ky-hero__pill"><Lightbulb size={14} /> 支持自然语言</span>
            </div>
          </div>
          <div className="v3-ky-hero__stats">
            <div className="v3-ky-hero__stat">
              <b>{statsLoading ? '—' : stats?.school_count ?? '—'}</b>
              <span>院校数</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{statsLoading ? '—' : stats?.major_count ?? '—'}</b>
              <span>专业方向</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{statsLoading ? '—' : stats?.scoreline_records ?? '—'}</b>
              <span>分数线记录</span>
            </div>
            <div className="v3-ky-hero__stat">
              <b>{statsLoading ? '—' : stats?.admission_records ?? '—'}</b>
              <span>招生记录</span>
            </div>
          </div>
        </div>
      </Tile>

      {statsError ? (
        <Alert tone="warning" className="v3-ky-chat-stats-alert">
          数据概览加载失败：{statsError}。不影响问答；择校引擎会在每次提问时重新读取库内数据。
          <Button size="sm" variant="text" onClick={loadStats} disabled={statsLoading}>重试</Button>
        </Alert>
      ) : null}

      <Tile span={12} className="v3-ky-chat">
        <div className="v3-ky-chat__head">
          <div className="v3-ky-chat__identity">
            <span className="v3-ky-chat__avatar"><Bot size={20} /></span>
            <div>
              <h2>择校助手</h2>
              <p><i /> 本地引擎在线 · 回答基于库内真实记录</p>
            </div>
          </div>
          <Badge tone="outline">问题 {messages.filter((m) => m.role === 'user').length} 轮</Badge>
        </div>

        <div className="v3-ky-chat__presets">
          <span className="v3-ky-chat__presets-label"><Lightbulb size={13} /> 试试这样问</span>
          <div className="v3-ky-chat__preset-list">
            {presets.map((preset, index) => (
              <Chip
                key={index}
                className="v3-ky-preset"
                disabled={loading}
                onClick={() => send(preset)}
              >
                {preset}
              </Chip>
            ))}
          </div>
        </div>

        <div className="v3-ky-chat__scroll" ref={scrollRef} aria-live="polite">
          <div className="v3-ky-chat__messages">
            {messages.map((message) => <Message key={message.id} message={message} />)}
            {loading ? (
              <div className="v3-ky-msg v3-ky-msg--assistant is-typing">
                <span className="v3-ky-msg__avatar" aria-hidden="true"><Bot size={17} /></span>
                <div className="v3-ky-msg__body">
                  <div className="v3-ky-msg__label"><Database size={12} /> 择校引擎</div>
                  <div className="v3-ky-msg__bubble v3-ky-typing">
                    <span /><span /><span />
                    <em>{phaseText}</em>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="v3-ky-composer">
          <textarea
            ref={inputRef}
            className="v3-ky-composer__input"
            aria-label="输入你的择校问题"
            rows={2}
            value={input}
            placeholder="输入你的择校问题，如：350分能上哪些211？"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                send(input)
              }
            }}
          />
          <div className="v3-ky-composer__foot">
            <span>Enter 发送 · Shift + Enter 换行{myMajor ? ` · 已识别报考专业「${myMajor}」` : ''}</span>
            <Button
              variant="gradient"
              icon={<Send size={16} />}
              loading={loading}
              disabled={!input.trim() || loading}
              onClick={() => send(input)}
            >
              {loading ? '思考中' : '发送'}
            </Button>
          </div>
        </div>
      </Tile>

      <p className="v3-ky-footnote">
        <Database size={13} /> 分数线、复录比与招生数据来自第三方聚合，未经官网逐条核验；AI 深度解读仅为策略建议，请以院校官网口径为准。
      </p>
    </div>
  )
}
