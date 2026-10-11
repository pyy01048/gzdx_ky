import React, { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import useStore from '../store/useStore'
import { chatCompletion, chatVision, defaultProvider, hasAiConfigured, extractJson, recordUsage } from '../utils/api'
import { fileToCompressedDataUrl } from '../utils/image'
import { toast } from './UI'

/* 页面上下文映射：让 AI 感知当前所处模块 */
const PAGE_CTX = {
  '/': { name: '仪表盘', desc: '你在总控驾驶舱，可帮你解读今日任务、倒计时与复习提醒' },
  '/tasks': { name: '任务打卡', desc: '你在任务管理页，可帮你规划任务、解析文档生成任务清单' },
  '/kbmap': { name: '知识地图', desc: '你在知识地图页，能看到章节→知识点→题型三级结构与复习进度，可帮你定位薄弱考点' },
  '/notebook': { name: '电子错题本', desc: '你在错题本页，可帮你 OCR 识别题目、讲解错题、规划复习' },
  '/assistant': { name: 'AI 助手', desc: '你已打开 AI 助手页，全局面板与它能力一致' },
  '/pan': { name: '网盘联动', desc: '你在网盘资料页，可帮你整理资料、关联考点' },
  '/settings': { name: '设置', desc: '你在设置页，可帮你理解各配置项、排查 API 连接' }
}

/* 本地兜底回答（未配置 API 时） */
function localReply(ctx, q) {
  return `【全局 AI · 本地模式】\n当前在「${ctx.name}」页面，${ctx.desc}。\n\n我目前运行在本地规则模式（未接入真实 AI 大模型）。要获得更强的理解与解答能力，请到「设置 → AI 服务」填写一个 API Key（支持 DeepSeek / 豆包 / 通义 / 智谱 / OpenAI），配置成功后我会自动切换为智能模式，且全站页面都能随时唤起我。`
}

export default function GlobalAI() {
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [msgs, setMsgs] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)

  const ctx = PAGE_CTX[location.pathname] || PAGE_CTX['/']

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs, busy])

  const ask = async (text) => {
    const q = (text ?? input).trim()
    if (!q || busy) return
    setMsgs((m) => [...m, { role: 'user', content: q }])
    setInput('')
    setBusy(true)
    const provider = defaultProvider()
    const system = `你是考研备考助手，正在帮助一位备考贵州大学电子信息专硕(0854)的学生。当前用户所在页面：${ctx.name}（${ctx.desc}）。结合页面上下文给出简洁、可执行的建议，必要时用 markdown 列表。`
    try {
      // 批次1-2：CodeBuddy Agent 已下线（9 个端点后端零实现）。统一走后端代理 /api/ai/chat；未配置则本地兜底。
      if (hasAiConfigured()) {
        const r = await chatCompletion(provider, [
          { role: 'system', content: system },
          ...msgs.filter((m) => m.role === 'user').slice(-6).map((m) => ({ role: 'user', content: m.content })),
          { role: 'user', content: q }
        ])
        recordUsage(r.usage, provider.id)
        setMsgs((m) => [...m, { role: 'bot', content: r.text }])
      } else {
        setMsgs((m) => [...m, { role: 'bot', content: localReply(ctx, q) }])
      }
    } catch (e) {
      setMsgs((m) => [...m, { role: 'bot', content: `⚠ ${e.message}` }])
    }
    setBusy(false)
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      ask()
    }
  }

  /* ---------- OCR 识别题目并收录错题本 ---------- */
  const ocrUpload = async (file) => {
    const provider = defaultProvider()
    if (!hasAiConfigured()) {
      toast('请先在「设置 → AI 服务」配置 API Key（推荐支持视觉的模型）')
      return
    }
    setBusy(true)
    setMsgs((m) => [...m, { role: 'user', content: `[OCR] 上传题目图片：${file.name}` }])
    try {
      const dataUrl = await fileToCompressedDataUrl(file)
      const prompt = `请识别这张考研题目图片中的完整内容，并严格输出 JSON（不要多余文字），格式：{"question":"题目","options":["A.…","B.…","C.…","D.…"]或null,"answer":"正确答案及简要解析","analysis":"考点与易错点","reason":"可能的错误原因","subject":"math|english|politics|major 选一个","tags":["标签"]}。识别不清的地方尽力推断。`
      const r = await chatVision(provider, prompt, dataUrl)
      recordUsage(r.usage, provider.id)
      const data = extractJson(r.text)
      if (!data || !data.question) throw new Error('未能从图片中提取题目结构')
      // 组合选项到题干/答案
      let question = data.question
      if (Array.isArray(data.options) && data.options.length) question += '\n' + data.options.join('\n')
      useStore.getState().addNote({
        question,
        answer: data.answer || '',
        analysis: data.analysis || '',
        reason: data.reason || '',
        subject: ['math', 'english', 'politics', 'major'].includes(data.subject) ? data.subject : 'major',
        tags: Array.isArray(data.tags) ? data.tags : []
      })
      setMsgs((m) => [...m, { role: 'bot', content: `已通过 OCR 识别并收录到错题本：\n【题目】${question.slice(0, 80)}${question.length > 80 ? '…' : ''}\n\n【答案】${data.answer || '—'}\n\n可到「电子错题本」查看完整条目与艾宾浩斯复习排期。` }])
      toast('OCR 识别成功，已收录错题')
    } catch (e) {
      setMsgs((m) => [...m, { role: 'bot', content: `⚠ OCR 失败：${e.message}` }])
    }
    setBusy(false)
  }

  /* ---------- 解析文档生成任务 ---------- */
  const docImport = async (file) => {
    // 动态引入解析层，避免 pdfjs/mammoth 进入首屏主包
    const { parseDocument, isSupported } = await import('../utils/parser')
    if (!isSupported(file.name)) {
      toast('支持 PDF / DOCX / MD / TXT 文档')
      return
    }
    setBusy(true)
    setMsgs((m) => [...m, { role: 'user', content: `[文档导入] 解析「${file.name}」生成任务清单` }])
    try {
      const text = await parseDocument(file)
      if (!text || text.length < 8) throw new Error('文档内容为空或无法提取文字（可能是扫描版 PDF，建议用 OCR 图片）')
      const provider = defaultProvider()
      let tasks = null
      if (hasAiConfigured()) {
        const prompt = `下面是一份考研复习文档的文本。请提炼其中的复习要点/章节/待办，输出 JSON：{"tasks":[{"title":"任务标题","subject":"math|english|politics|major 选一个"}]}，最多 8 项，title 用一句话描述可执行任务。文档内容：\n${text.slice(0, 4000)}`
        const r = await chatCompletion(provider, [{ role: 'user', content: prompt }], { temperature: 0.3, maxTokens: 800 })
        recordUsage(r.usage, provider.id)
        const d = extractJson(r.text)
        if (d && Array.isArray(d.tasks) && d.tasks.length) tasks = d.tasks.map((t) => ({ title: t.title, subject: ['math', 'english', 'politics', 'major'].includes(t.subject) ? t.subject : 'major' }))
      }
      if (!tasks) {
        // 本地兜底：按段落拆任务
        tasks = text.split(/\n+/).map((l) => l.trim()).filter((l) => l.length > 6 && l.length < 40).slice(0, 8)
          .map((t) => ({ title: t, subject: 'major' }))
      }
      useStore.getState().importTasks(tasks)
      setMsgs((m) => [...m, { role: 'bot', content: `已解析文档（${text.length} 字），提取 ${tasks.length} 项任务并导入任务打卡：\n${tasks.map((t) => `· ${t.title}`).join('\n')}` }])
      toast(`已导入 ${tasks.length} 项任务`)
    } catch (e) {
      setMsgs((m) => [...m, { role: 'bot', content: `⚠ 解析失败：${e.message}` }])
    }
    setBusy(false)
  }

  /* 页面快捷动作 */
  const actionByPage = {
    '/notebook': [
      { label: 'OCR 上传题目', run: () => fileRef('image').click() },
      { label: '如何高效整理错题？', run: () => ask('我在错题本页面，如何高效整理错题、按艾宾浩斯复习？') }
    ],
    '/tasks': [
      { label: '解析文档生成任务', run: () => fileRef('doc').click() },
      { label: '帮我规划今日任务', run: () => ask('请基于我的备考情况（贵州大学电子信息0854）帮我规划今天的学习任务') }
    ],
    '/kbmap': [
      { label: '我哪些考点最薄弱', run: () => ask('请分析我的错题和复习记录，告诉我最薄弱的考点是哪些，并按章节给出复习优先级') },
      { label: '今天该复习什么', run: () => ask('结合我的复习进度，帮我列出今天应该优先复习的知识点') }
    ],
    '/pan': [
      { label: '整理资料建议', run: () => ask('帮我分析网盘资料该如何分类整理，才能更好配合复习') }
    ],
    '/settings': [
      { label: '如何配置 AI API？', run: () => ask('如何配置 AI API 服务？支持哪些平台？') }
    ],
    '/': [
      { label: '今日学习复盘', run: () => ask('请帮我做今日学习复盘，并给出明日建议') }
    ]
  }
  const actions = actionByPage[location.pathname] || actionByPage['/']

  const fileRef = (kind) => {
    // 动态创建隐藏 input，避免组件内多个 ref
    const input = document.createElement('input')
    input.type = 'file'
    if (kind === 'image') input.accept = 'image/*'
    else input.accept = '.pdf,.docx,.md,.txt'
    input.style.display = 'none'
    document.body.appendChild(input)
    input.onchange = () => {
      const f = input.files[0]
      if (f) (kind === 'image' ? ocrUpload(f) : docImport(f))
      document.body.removeChild(input)
    }
    input.click()
  }

  if (!open) {
    return (
      <button className="fab" onClick={() => setOpen(true)} title="全局 AI 助手">
        <span className="fab-ico">✦</span>
      </button>
    )
  }

  return (
    <div className="global-ai">
      <div className="gai-mask" onClick={() => setOpen(false)} />
      <div className="gai-panel">
        <div className="gai-head">
          <div>
            <strong>全局 AI 助手</strong>
            <span className="gai-ctx">当前在「{ctx.name}」· {ctx.desc}</span>
          </div>
          <button className="gai-close" onClick={() => setOpen(false)}>✕</button>
        </div>

        <div className="gai-actions">
          {actions.map((a) => (
            <button key={a.label} className="chip" onClick={a.run}>{a.label}</button>
          ))}
        </div>

        <div className="gai-chat">
          {msgs.length === 0 && !busy && (
            <div className="gai-empty">
              你好，我在任何页面都能帮你。<br />
              可以直接提问，或使用上方快捷操作：<br />
              · 错题本页：OCR 拍照/截图识别题目并收录<br />
              · 任务页：解析 PDF / DOCX / MD 生成任务清单
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`ai-msg ${m.role}`}>
              {m.role === 'bot' && <div className="ai-avatar">档</div>}
              <div className="ai-bubble" style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
            </div>
          ))}
          {busy && (
            <div className="ai-msg bot">
              <div className="ai-avatar">档</div>
              <div className="ai-bubble">正在处理…</div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        <div className="gai-input">
          <textarea rows={1} placeholder={`在「${ctx.name}」页面向 AI 提问…`} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} />
          <button className="btn primary" style={{ height: 42, minWidth: 66 }} onClick={() => ask()} disabled={busy || !input.trim()}>发送</button>
        </div>
      </div>
    </div>
  )
}
