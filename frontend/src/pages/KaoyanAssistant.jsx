import React, { useState, useRef, useEffect } from 'react'
import { kaoyanApi } from '../api/kaoyanApi'
import { aiApi } from '../api/client'
import useStore from '../store/useStore'
import { toast } from '../components/UI'

export default function KaoyanAssistant() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: '你好！我是考研择校 AI 助手。你可以问我分数线、院校推荐、复录比、招生人数等问题。试试点击下方预设问题，或直接输入你的问题。' }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState(null)
  const scrollRef = useRef(null)

  useEffect(() => {
    kaoyanApi.stats().then(setStats).catch(() => toast('统计数据加载失败'))
  }, [])

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages])

  // 预设问题：专业取自用户在「设置」里填报的报考专业。
  // 此前写死「电子信息」和「我考320分」，等于替每个用户假设专业方向与分数。
  const myMajor = useStore((s) => s.settings.major)
  const presets = [
    '推荐几所稳妥的学校',
    '哪些985院校复录比较低？',
    myMajor ? `${myMajor}专业哪些学校招生人数多？` : '我报考的专业哪些学校招生人数多？',
    '帮我分析北京地区的院校难度',
  ]

  // 发送问题：主走 D4 新引擎（本地规则+真实数据，稳定可用），AI 深度解读作为可选补充
  const send = async (text) => {
    if (!text.trim() || loading) return
    const userMsg = { role: 'user', content: text }
    setMessages(m => [...m, userMsg])
    setInput('')
    setLoading(true)

    try {
      // 1. 调用后端自然语言择校问答引擎
      const res = await kaoyanApi.assistantQuery(text)
      let content = res.answer || '抱歉，暂时无法回答这个问题。'
      // 推荐院校转成可点击链接
      const recs = res.recommendations || []
      if (recs.length) {
        content += '\n\n【推荐院校】\n' + recs.map(r => r.name).join('、')
      }
      setMessages(m => [...m, { role: 'assistant', content }])

      // 2. AI 深度解读（失败不阻塞，仅降级提示）
      try {
        const aiRes = await aiApi.chat({
          messages: [
            { role: 'system', content: '你是考研择校顾问，请基于下方引擎结论做简洁深度解读，给出选校策略建议。用中文，3-5 句话。' },
            { role: 'user', content: `问题：${text}\n\n引擎结论：\n${content}` },
          ],
          use_rag: false,
        })
        const reply = aiRes.reply || aiRes.content
        if (reply) {
          // B-3（§6.3/§6.5 方案A）：D4 引擎给出的分数线/复录比/招生人数几乎全部来自
          // 第三方聚合（scorelines 97.29% 为 unverified，admissions 99.16% 来自 txkyer.cn）。
          // 只要引擎结论引用了这些具体数据，AI 深度解读就必须在末尾显式标注来源可信度，
          // 让用户知道看到的是"软数据"，而不是官网口径。
          const reliesOnUnverified = recs.length > 0 || /分数线|复录比|招生|拟招|录取/.test(content)
          const sourceNote = reliesOnUnverified ? '\n\n数据来源：第三方聚合，未核验' : ''
          setMessages(m => [...m, { role: 'assistant', content: `【AI 深度解读】\n${reply}${sourceNote}` }])
        }
      } catch (e) {
        // P0-5：这里原来是空的 `catch {}` —— /api/ai/chat 返回 502 时界面完全静默，
        // 用户只看到引擎结论、看不到任何"AI 解读失败"的提示，只能以为卡住了。
        // 502 多为服务商 Key 未配置或本地 Ollama 未启动（后端现已把原因码放进 detail）。
        const hint = e?.status === 502
          ? '\n常见原因：AI 服务商 API Key 未配置/失效，或本地 Ollama 未启动（详见「设置 → AI 服务」）。'
          : ''
        setMessages(m => [...m, {
          role: 'assistant',
          content: `【AI 深度解读】暂时不可用：${e?.message || '未知错误'}${hint}\n\n上面的择校结论来自本地引擎，可正常使用。`,
        }])
      }
    } catch (e) {
      setMessages(m => [...m, { role: 'assistant', content: `出错了：${e.message}` }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="ky-page" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
      <h1 style={{ marginBottom: 'var(--space-1)' }}>择校 AI 助手</h1>
      <p style={{ color: 'var(--muted)', marginBottom: 'var(--space-4)' }}>
        {stats
          ? `基于本地库 ${stats.school_count} 所院校 / ${stats.major_count} 个专业 / ${stats.scoreline_records} 条分数线记录`
          : '数据概览加载中…'}
      </p>

      {/* 预设问题 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
        {presets.map((p, i) => (
          <button key={i} onClick={() => send(p)} disabled={loading}
            style={{
              padding: 'var(--space-2) var(--space-4)', borderRadius: '20px', border: '1px solid var(--border)',
              background: 'var(--surface)', cursor: loading ? 'default' : 'pointer',
              fontSize: 'var(--text-sm)', color: 'var(--fg-2)',
            }}>
            {p}
          </button>
        ))}
      </div>

      {/* 消息区 */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: 'var(--space-4)', background: 'var(--surface)', borderRadius: '12px', border: '1px solid var(--border)', marginBottom: 'var(--space-3)' }}>
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 'var(--space-3)', display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              maxWidth: '75%', padding: 'var(--space-3) var(--space-4)', borderRadius: '12px',
              background: m.role === 'user' ? 'var(--accent)' : 'var(--surface-2)',
              color: m.role === 'user' ? '#fff' : 'var(--fg)',
              whiteSpace: 'pre-wrap', fontSize: 'var(--text-base)', lineHeight: '1.6',
            }}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && <div style={{ color: 'var(--muted)', fontSize: 'var(--text-sm)' }}>AI 思考中…</div>}
      </div>

      {/* 输入区 */}
      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <input
          value={input}
          aria-label="输入你的择校问题"
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send(input)}
          placeholder="输入你的择校问题，如：350分能上哪些211？"
          style={{ flex: 1, padding: 'var(--space-3) var(--space-4)', borderRadius: '8px', border: '1px solid var(--border)' }}
        />
        <button onClick={() => send(input)} disabled={loading || !input.trim()}
          style={{
            padding: 'var(--space-3) var(--space-6)', borderRadius: '8px', border: 'none', cursor: (loading || !input.trim()) ? 'default' : 'pointer',
            background: (loading || !input.trim()) ? 'var(--surface-2)' : 'var(--accent)',
            color: (loading || !input.trim()) ? 'var(--muted)' : '#fff',
          }}>
          {loading ? '发送中' : '发送'}
        </button>
      </div>
    </div>
  )
}
