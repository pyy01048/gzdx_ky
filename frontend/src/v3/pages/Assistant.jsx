import React, { useEffect, useRef, useState } from 'react'
import useStore from '../../store/useStore'
import { uid } from '../../utils/date'
import { examDaysLeft, resolveExamDate } from '../../utils/exam'
import { chatCompletion, defaultProvider, hasAiConfigured, recordUsage } from '../../utils/api'
import { aiApi, aiChatStream } from '../../api/client'
import { useSubjectConfig } from '../../hooks/useSubjectConfig'
import DeepTools from '../../components/DeepTools'
import MathText from '../../components/MathText'
import {
  Avatar, Badge, Button, Card, CardHead, Chip, Dialog, Empty, Field, IconButton, Input,
  PageHeader, Segmented, Skeleton, SparkleBadge, Switch, Textarea, cx, toast, toastErr, toastOk,
} from '../ui'
import {
  AlertTriangle, Bot, Brain, Check, ChevronDown, Copy, Edit, Image, Lightbulb, Loader,
  MessageSquare, Paperclip, Pause, Plus, RefreshCw, Send, Sparkles, Trash, User, Wand, X,
} from '../icons'
import '../styles/assistant-v3.css'

/* ============================================================
   AI 助手（Aurora v3）
   引擎（与旧版一致）：
   1) 自定义 AI API（设置中配置的多服务商，SSE 流式 + RAG）—— /api/ai/chat/stream
   2) 本地画像规则引擎（离线兜底）

   功能面：会话快照 / 多轮上下文摘要 / 本地知识库引用 / 电路读图 /
   SSE 流式生成与停止 / 失败气泡与重试 / DeepTools 学习工具。
   ============================================================ */

const KB = [
  {
    keys: ['极限', '泰勒', '等价无穷小', '洛必达'],
    reply: (ctx) => `【数学 · 极限】\n1. 先看类型：0/0、∞/∞ 用洛必达或等价无穷小；\n2. 常见等价无穷小务必熟记：x→0 时 sinx~x、tanx~x、1-cosx~x²/2、ln(1+x)~x、eˣ-1~x；\n3. 泰勒展开兜底：ln(1+x)、eˣ 展开到与分母同阶。\n建议：每天抽 10 分钟默写等价无穷小表，配合 1800 题极限部分。`
  },
  {
    keys: ['英语', '单词', '词汇', '真题', '阅读', '作文'],
    reply: (ctx) => `【英语 · 备考策略】\n1. 词汇：每天 100 个（快速过 + 睡前回顾），重点背真题高频词；\n2. 真题：近 20 年真题精读，每篇做完逐句翻译、标记生词；\n3. 作文：大小作文各背 3 套模板 + 万能替换句，考前 2 个月每周写 1 篇。\n当前${ctx.when}，真题精读建议按「每天 2 篇 + 复盘 1 篇」推进。`
  },
  {
    keys: ['政治', '马原', '毛概', '史纲', '思修', '肖'],
    reply: (ctx) => `【政治 · 复习节奏】\n1. 现阶段（${ctx.when}）：主攻选择题，刷《1000题》选择题，马原重理解；\n2. 中后期：肖八选择题 + 肖四大题背诵，结合时政；\n3. 技巧：马原大题「原理 + 方法论 + 材料」三段式作答。\n建议每天政治 1.5h，安排在上午或晚间注意力中等时段。`
  },
  {
    keys: ['专业课', '初复试', '大纲', '考纲'],
    keysOf: (ctx) => ['专业课', '初复试', '大纲', '考纲', ...(ctx.subjects || [])],
    reply: (ctx) => {
      const subs = (ctx.subjects || []).filter(Boolean)
      if (!subs.length) {
        return '【专业课 · 还没配置科目】\n本地规则模式不知道你的专业课方向，只能给通用流程：\n1. 先在「设置 → 备考科目」填上专业课（例如 数字电子技术），本页的专业课建议会按你的科目重写；\n2. 方向未定前，公共课（数学/英语/政治）可以先按大纲推进；\n3. 已收录的错题会按艾宾浩斯自动排期，可以先从错题复盘开始。'
      }
      return `【专业课 · ${subs.join(' + ')}】\n1. 考纲优先：按 ${subs.join('/')} 的**目标院校官方大纲**圈定范围，不要拿别校真题当范围依据；\n2. 真题为王：近 8-10 年真题至少刷两遍，第二遍按题型归纳（哪些是必考计算、哪些是概念辨析）；\n3. 计算与证明：写规范步骤练速度，别只看答案；\n${ctx.when === '未设置初试日期' ? '建议先在设置里填写初试日期，规划模式才能按剩余天数拆阶段。' : `当前${ctx.when}，建议每天固定一个整块时间专攻专业课。`}\n你已收录的错题会按艾宾浩斯自动排期。`
    }
  },
  {
    keys: ['计划', '规划', '安排', '时间表', '每天', '作息'],
    reply: (ctx) => `【学习计划建议】\n${ctx.when}，推荐每日节奏（约 9h 有效学习）：\n· 08:00-09:40  数学（上午头脑最清醒）\n· 10:00-11:40  专业课\n· 13:30-15:10  英语真题\n· 15:30-17:10  政治\n· 18:30-20:00  专业课强化 / 错题\n· 20:10-21:40  数学刷题 + 错题复盘\n· 21:50-22:30  单词 + 睡前回顾\n建议每 50 分钟休息 10 分钟。要不要我把这套计划加入任务打卡？`
  },
  {
    keys: ['焦虑', '压力', '坚持', '心态', '放弃', '累'],
    reply: (ctx) => `【心态调整】\n${ctx.when}，焦虑是很正常的信号，说明你在乎。\n1. 把大目标拆成今天能完成的小事——完成一件就划掉一件；\n2. 每天固定「复盘 10 分钟」，看到自己的进步；\n3. 每周留半天彻底休息，不内疚。\n你已经在用错题本和知识地图记录进度，这就比大多数人强了。继续就好。`
  }
]

const DEFAULT_REPLY = (ctx) => `收到。这个问题先帮你拆解一下：\n1. 明确考查目标：结合你当前复习阶段（${ctx.when}），建议先回归教材/真题定位；\n2. 拆成可执行的小步骤，同步到「任务打卡」里；\n3. 相关错题可收录进「错题本」，我会按艾宾浩斯帮你安排复习。\n你可以更具体地描述问题（比如涉及哪个科目、哪个考点），我给出更精准的解答。`

const QUICK = ['怎么安排每天的复习？', '英语真题怎么刷最有效？', '专业课重点是什么？', '数学极限总出错怎么办？', '最近有点焦虑怎么办？']

function quickPrompts(subjects) {
  const first = (subjects || []).filter(Boolean)[0]
  if (!first) return QUICK
  return QUICK.map((q) => (q === '专业课重点是什么？' ? `${first} 重点是什么？` : q))
}

const ENGINES = [
  { key: 'api', name: 'API', full: '自定义 AI API' },
  { key: 'local', name: '本地', full: '本地规则模式' }
]

const TOPIC_WORDS = ['数学', '英语', '政治', '专业课', '极限', '泰勒', '导数', '积分', '概率', '线代', '真题', '作文', '单词', '阅读', '翻译', '数据结构', '计算机网络', '操作系统', '组成原理', '计划', '作息', '焦虑', '心态', '复习', '错题', '背诵', '模考', '报名', '复试', '分数线']

function topKeywords(text, n = 5) {
  const stat = TOPIC_WORDS.map((w) => ({ w, c: (text.split(w).length - 1) })).filter((x) => x.c > 0)
  stat.sort((a, b) => b.c - a.c)
  return stat.slice(0, n).map((x) => `${x.w}×${x.c}`)
}

function localSummary(messages) {
  const users = messages.filter((m) => m.role === 'user').map((m) => (m.content || '').trim()).filter(Boolean)
  const bots = messages.filter((m) => m.role === 'bot')
  if (!users.length) return ''
  const topics = users.slice(-6).map((q, i) => `${i + 1}. ${q.length > 42 ? q.slice(0, 42) + '…' : q}`)
  const kw = topKeywords(users.join(' '))
  return `本地摘要（${users.length} 轮提问 / ${bots.length} 条回复）\n近期话题：\n${topics.join('\n')}${kw.length ? `\n高频关键词：${kw.join('、')}` : ''}`
}

function aiFailBubble(e) {
  const code = e?.code || ''
  const msg = e?.message || '未知错误'
  if (code === 'network') {
    return `注意 网络错误：${msg}\n\nAI 服务连接不上（后端未启动 / 网络中断 / 请求超时）。可点下方「重试」，或切换到「本地」引擎先拿离线建议。`
  }
  if (code === 'ai_stream_error' || code === 'http_error') {
    return `注意 AI 服务报错：${msg}\n\n可点下方「重试」；若反复失败，到「设置 → AI 服务」检查服务商配置（API Key、模型名，以及本地 Ollama 是否已启动）。`
  }
  if (code === 'ai_empty_stream') {
    return `注意 AI 返回了空回复：${msg}\n\n接口返回 200，但整条流没有任何内容（常见于模型名不存在、额度耗尽或服务商流式配置异常）。可点下方「重试」，或切换到「本地」引擎。`
  }
  return `注意 AI 调用失败：${msg}\n\n可点下方「重试」，或切换到「本地」引擎查看离线规则建议。`
}

function aiFailToast(e) {
  const code = e?.code || ''
  if (code === 'network') return `AI 连接失败：${e?.message || '网络异常'}`
  if (code === 'ai_empty_stream') return 'AI 返回了空回复，未生成任何内容'
  if (code === 'ai_stream_error' || code === 'http_error') return `AI 服务报错：${e?.message || '接口异常'}`
  return `AI 调用失败：${e?.message || '未知错误'}`
}

export default function Assistant() {
  const ai = useStore((s) => s.ai)
  const sendAi = useStore((s) => s.sendAi)
  const replyAi = useStore((s) => s.replyAi)
  const clearAi = useStore((s) => s.clearAi)
  const setAiPersona = useStore((s) => s.setAiPersona)
  const notebook = useStore((s) => s.notebook)
  const pan = useStore((s) => s.pan)
  const words = useStore((s) => s.words)
  const cards = useStore((s) => s.cards)
  const packs = useStore((s) => s.packs)
  const addCard = useStore((s) => s.addCard)
  const settings = useStore((s) => s.settings)
  const countdown = useStore((s) => s.countdown)

  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [mode, setMode] = useState('答疑')
  const [engine, setEngine] = useState('api')
  const [useRag, setUseRag] = useState(true)
  const [image, setImage] = useState(null)
  const [imgUploading, setImgUploading] = useState(false)
  const [canStop, setCanStop] = useState(false)
  // 2026-10-23 P0：推理型模型（u2-flash）首 token 可达 30s+，用 thinkingText
  // 展示「模型思考中…/正在检索知识库…」，避免用户长时间只看到「生成中…」。
  const [thinkingText, setThinkingText] = useState('')
  const fileRef = useRef(null)
  const abortRef = useRef(null)

  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [showTools, setShowTools] = useState(false)
  const [renameTarget, setRenameTarget] = useState(null)
  const [renameValue, setRenameValue] = useState('')

  const [refs, setRefs] = useState(null)
  const [refLoading, setRefLoading] = useState(false)
  const [refDetail, setRefDetail] = useState(null)

  const [summary, setSummary] = useState('')
  const [summarizing, setSummarizing] = useState(false)
  const [useSummary, setUseSummary] = useState(false)
  const [showSummary, setShowSummary] = useState(false)

  const { active: configuredSubjects } = useSubjectConfig()
  const effectiveDate = settings.examDate || countdown?.exam_date
  const days = examDaysLeft(resolveExamDate(effectiveDate, null))
  const ctx = {
    days,
    when: days == null ? '未设置初试日期' : `距考试 ${days} 天`,
    subjects: configuredSubjects,
  }

  const bodyRef = useRef(null)

  const persistSessions = (list, activeId) => {
    useStore.setState({ ai: { ...useStore.getState().ai, localSessions: list, activeSessionId: activeId } })
  }

  const titleFromMessages = (msgs) => {
    const u = (msgs || []).find((m) => m.role === 'user')
    const t = (u?.content || '').trim()
    return t ? (t.length > 18 ? t.slice(0, 18) + '…' : t) : '新会话'
  }

  useEffect(() => {
    const current = useStore.getState().ai
    setSessions(current.localSessions || [])
    setActiveSession(current.activeSessionId || null)
  }, [])

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [ai.messages, typing])

  useEffect(() => () => {
    if (abortRef.current) abortRef.current.abort()
  }, [])

  const think = (q) => {
    const lower = q.toLowerCase()
    const hit = KB.find((k) => (k.keysOf ? k.keysOf(ctx) : k.keys).some((key) => lower.includes(key)))
    if (hit) return hit.reply(ctx)
    if (mode === '规划') {
      if (ctx.days == null) {
        return '【规划 · 缺少初试日期】\n本地规则模式按剩余天数拆分阶段，请先在「设置」里填写考研初试日期；也可以切换到 API 引擎，由 AI 结合你的科目直接给规划。'
      }
      const schoolLine = [settings.school, settings.major].filter(Boolean).join(' ')
      return `【${ctx.days} 天冲刺规划 · 生成中】\n${schoolLine ? `基于你当前数据：${schoolLine}${settings.targetScore ? `，目标 ${settings.targetScore} 分` : ''}。\n` : ''}· 阶段一（${Math.max(1, Math.round(ctx.days * 0.5))} 天）：基础强化，主攻数学与专业课，英语真题精读；\n· 阶段二（${Math.max(1, Math.round(ctx.days * 0.3))} 天）：真题模考 + 错题集中攻克；\n· 阶段三（${Math.max(1, Math.round(ctx.days * 0.2))} 天）：政治大题背诵 + 全真模拟。\n建议：错题坚持七刷，定期看知识地图的薄弱考点。需要我细化某阶段吗？`
    }
    return DEFAULT_REPLY(ctx)
  }

  const loadRefs = async (q) => {
    if (!useRag || !q) { setRefs(null); return }
    setRefLoading(true)
    try {
      const r = await aiApi.ragSearch({ query: q, limit: 6 })
      const hits = Array.isArray(r?.hits) ? r.hits : []
      setRefs({ query: q, hits })
    } catch {
      setRefs(null)
    } finally {
      setRefLoading(false)
    }
  }

  const makeSummary = async () => {
    const msgs = useStore.getState().ai.messages
    if (msgs.length < 2) { toast('对话还太短，暂时不需要摘要'); return }
    setSummarizing(true)
    try {
      const provider = defaultProvider()
      if (hasAiConfigured()) {
        const transcript = msgs.slice(-20).map((m) => `${m.role === 'bot' ? 'AI' : '我'}：${m.content}`).join('\n')
        const r = await chatCompletion(provider, [
          { role: 'system', content: '你是对话摘要助手。请用不超过 200 字、分 3 点总结下面这段考研备考对话：①用户关注的核心问题 ②已给出的关键结论 ③待跟进事项。直接输出要点，不要客套话。' },
          { role: 'user', content: transcript }
        ], { maxTokens: 400, temperature: 0.3 })
        const text = (r.text || '').trim()
        setSummary(text || localSummary(msgs))
        try { recordUsage(r.usage, provider?.key) } catch { /* usage 记录失败不影响摘要 */ }
      } else {
        setSummary(localSummary(msgs))
      }
      setUseSummary(true)
      setShowSummary(true)
      toastOk('已生成上下文摘要，后续提问将自动携带')
    } catch (e) {
      setSummary(localSummary(msgs))
      setUseSummary(true)
      setShowSummary(true)
      toastErr(`AI 摘要失败，已改用本地摘要：${e.message}`)
    }
    setSummarizing(false)
  }

  const pushError = (text, retryText) => {
    const st = useStore.getState()
    useStore.setState({
      ai: { ...st.ai, messages: [...st.ai.messages, { role: 'bot', content: text, error: true, retry: retryText || '' }] }
    })
  }

  const finalizeStreaming = () => {
    const st = useStore.getState()
    if (!st.ai.messages.some((m) => m.streaming)) return
    useStore.setState({
      ai: { ...st.ai, messages: st.ai.messages.map((m) => (m.streaming ? { ...m, streaming: false } : m)) }
    })
  }

  const retrySend = (text) => {
    const st = useStore.getState()
    useStore.setState({ ai: { ...st.ai, messages: st.ai.messages.filter((m) => !m.error) } })
    send(text)
  }

  const onPickImage = async (e) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    setImgUploading(true)
    try {
      const r = await aiApi.uploadImage(f)
      setImage({ path: r.path, name: f.name, preview: URL.createObjectURL(f) })
      toast('图片已附加：发送后将自动启用电路读图分析（较慢，请耐心等待）')
    } catch (err) {
      toastErr(`图片上传失败：${err.message}`)
    }
    setImgUploading(false)
  }

  const send = async (text) => {
    const q = (text ?? input).trim()
    if ((!q && !image) || typing) return
    const question = q || '请分析这张电路图'
    sendAi(question + (image ? ' 图片' : ''))
    setInput('')
    loadRefs(q)

    if (image) {
      setTyping(true)
      const img = image
      setImage(null)
      try {
        const r = await aiApi.chatRouter({
          messages: [{ role: 'user', content: question }],
          use_rag: true,
          image_path: img.path,
        })
        const steps = (r.reasoning_steps || []).map((s) => s.step).join(' → ')
        replyAi(`${r.content || '（模型未返回内容）'}${steps ? `\n\n---\n推理链：${steps}` : ''}`)
      } catch (e) {
        replyAi(`注意 读图分析失败：${e.message}\n\n可尝试：① 确认本地 Ollama 已启动；② 稍后重试（批量答案回填期间 GPU 繁忙会显著拖慢读图）。`)
      }
      setTyping(false)
      return
    }

    const streamAppend = (delta) => {
      const st = useStore.getState()
      const msgs = st.ai.messages
      const last = msgs[msgs.length - 1]
      if (!last || last.role !== 'bot' || last.error) {
        useStore.setState({ ai: { ...st.ai, messages: [...msgs, { role: 'bot', content: delta, streaming: true }] } })
      } else {
        useStore.setState({
          ai: { ...st.ai, messages: msgs.map((m, i) => (i === msgs.length - 1 ? { ...m, content: m.content + delta } : m)) }
        })
      }
    }

    setTyping(true)
    try {
      const provider = defaultProvider()
      if (engine === 'api') {
        const summaryBlock = useSummary && summary ? `\n\n【此前对话摘要（已压缩上下文）】\n${summary}` : ''
        const profile = [
          [settings.school, settings.major].filter(Boolean).join(' '),
          settings.targetScore ? `目标 ${settings.targetScore} 分` : '',
          ctx.subjects.length ? `备考科目：${ctx.subjects.join('、')}` : '',
          ctx.days == null ? '' : `距考研 ${ctx.days} 天`
        ].filter(Boolean).join('，')
        const system = `你是考研备考助手「${ai.persona}」。${profile ? `用户正在备考 ${profile}。` : ''}当前模式：${mode}。${mode === '规划' ? '请给出分阶段可执行的复习计划。' : '请专业、简洁地解答考研相关问题，必要时用列表。'}${summaryBlock}`
        const keep = useSummary && summary ? -4 : -8
        const history = ai.messages.filter((m) => !m.error).slice(keep)
          .map((m) => ({ role: m.role === 'bot' ? 'assistant' : 'user', content: m.content }))
        let streamed = false
        try {
          const streamBody = {
            messages: [{ role: 'system', content: system }, ...history, { role: 'user', content: q }],
            use_rag: useRag,
          }
          if (provider && provider.apiKey && provider.baseUrl && provider.model) {
            streamBody.provider_override = {
              base_url: provider.baseUrl,
              api_key: provider.apiKey,
              model: provider.model,
              name: provider.name || provider.key,
              provider_type: provider.key === 'claude' ? 'claude' : 'openai',
              temperature: provider.temperature ?? 0.6,
            }
          }
          const controller = new AbortController()
          abortRef.current = controller
          setCanStop(true)
          setThinkingText('模型思考中…')
          await aiChatStream(streamBody, {
            signal: controller.signal,
            onDelta: (ev) => {
              if (ev.meta) {
                setThinkingText(ev.rag ? '正在检索知识库…' : '模型思考中…')
                return
              }
              if (ev.provider) {
                setThinkingText('已连接模型，思考中…')
                return
              }
              if (ev.type === 'status') {
                setThinkingText(ev.status === 'thinking' ? '模型思考中…' : '生成中…')
                return
              }
              if (ev.content) {
                setThinkingText('')
                streamed = true
                streamAppend(ev.content)
              }
            }
          })
        } catch (e) {
          if (e?.code === 'aborted') {
            finalizeStreaming()
            return
          }
          if (!streamed) throw e
          replyAi(`\n\n注意 流式中断：${e.message}`)
        } finally {
          abortRef.current = null
          setCanStop(false)
        }
        if (!streamed) {
          throw new Error('模型未返回任何内容（可能是服务商额度、模型名或流式配置问题）')
        }
        finalizeStreaming()
      } else {
        replyAi(think(q))
      }
    } catch (e) {
      pushError(aiFailBubble(e), question)
      toastErr(aiFailToast(e))
    } finally {
      setTyping(false)
      setThinkingText('')
      abortRef.current = null
      setCanStop(false)
    }
  }

  const stopGenerating = () => {
    if (!abortRef.current) return
    abortRef.current.abort()
    abortRef.current = null
    setCanStop(false)
    setTyping(false)
    toast('已停止生成')
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent?.isComposing) {
      e.preventDefault()
      send()
    }
  }

  const switchMode = (m) => {
    setMode(m)
    setAiPersona(m)
    toast(m === '规划' ? '已切换为规划模式，为你生成阶段计划' : '已切换为答疑模式，专注解答问题')
  }

  const switchEngine = (key) => {
    setEngine(key)
    toast(`${ENGINES.find((e) => e.key === key)?.full} 引擎已启用`)
  }

  const newChat = () => {
    const cur = useStore.getState().ai.messages
    let next = sessions
    if (activeSession) {
      next = sessions.map((s) => (s.id === activeSession ? { ...s, messages: cur, title: s.title || titleFromMessages(cur), updatedAt: Date.now() } : s))
    } else if (cur.length) {
      next = [{ id: uid(), title: titleFromMessages(cur), messages: cur, updatedAt: Date.now() }, ...next]
    }
    const s = { id: uid(), title: '', messages: [], updatedAt: Date.now() }
    const list = [s, ...next]
    setSessions(list)
    setActiveSession(s.id)
    clearAi()
    setRefs(null)
    setSummary('')
    setUseSummary(false)
    persistSessions(list, s.id)
  }

  const selectSession = (id) => {
    if (id === activeSession) return
    const cur = useStore.getState().ai.messages
    let next = sessions
    if (activeSession) {
      next = sessions.map((s) => (s.id === activeSession ? { ...s, messages: cur, title: s.title || titleFromMessages(cur), updatedAt: Date.now() } : s))
    }
    const target = next.find((s) => s.id === id)
    const history = (target?.messages || []).map((m) => ({ role: m.role === 'assistant' ? 'bot' : 'user', content: m.content }))
    setSessions(next)
    setActiveSession(id)
    useStore.setState({ ai: { ...useStore.getState().ai, messages: history } })
    setRefs(null)
    setSummary('')
    setUseSummary(false)
    persistSessions(next, id)
  }

  const openRename = (s) => {
    setRenameTarget(s)
    setRenameValue(s.title || '')
  }

  const submitRename = () => {
    if (!renameTarget) return
    const t = renameValue.trim()
    if (!t) return
    const list = sessions.map((it) => (it.id === renameTarget.id ? { ...it, title: t } : it))
    setSessions(list)
    persistSessions(list, activeSession)
    setRenameTarget(null)
    toastOk('已重命名')
  }

  const removeSession = (id) => {
    const rest = sessions.filter((s) => s.id !== id)
    if (activeSession === id) {
      if (rest.length) {
        const target = rest[0]
        const history = (target.messages || []).map((m) => ({ role: m.role === 'assistant' ? 'bot' : 'user', content: m.content }))
        setSessions(rest)
        setActiveSession(target.id)
        useStore.setState({ ai: { ...useStore.getState().ai, messages: history } })
        persistSessions(rest, target.id)
      } else {
        const s = { id: uid(), title: '', messages: [], updatedAt: Date.now() }
        setSessions([s])
        setActiveSession(s.id)
        clearAi()
        persistSessions([s], s.id)
      }
    } else {
      setSessions(rest)
      persistSessions(rest, activeSession)
    }
    toast('已删除会话')
  }

  const engineLabel = engine === 'api' ? '自定义 AI API（SSE 流式）' : '本地规则模式（离线）'
  const prompts = quickPrompts(ctx.subjects)

  return (
    <div className="v3-asst">
      <PageHeader
        eyebrow="AI STUDY COMPANION"
        title="AI 助手"
        sub="基于你的备考画像与本地知识库作答，会话保存在本机浏览器。"
        icon={<Sparkles size={22} />}
        actions={(
          <>
            <Segmented
              ariaLabel="推理引擎"
              value={engine}
              onChange={switchEngine}
              options={ENGINES.map((e) => ({
                value: e.key,
                label: e.name,
                icon: e.key === 'api' ? <Wand size={14} /> : <Brain size={14} />,
              }))}
            />
            <Segmented
              ariaLabel="问答模式"
              value={mode}
              onChange={switchMode}
              options={['答疑', '规划']}
            />
            <Button variant="tonal" icon={<Plus size={16} />} onClick={newChat}>新会话</Button>
          </>
        )}
      />

      <div className="v3-asst-status">
        <Badge tone={engine === 'api' ? 'gradient' : 'outline'}>{engineLabel}</Badge>
        {useRag ? <SparkleBadge>知识库增强</SparkleBadge> : null}
        {useSummary && summary ? <Badge tone="success">摘要上下文</Badge> : null}
        <span className="v3-asst-status__hint">
          <span className={cx('v3-asst-status__dot', engine === 'api' && 'is-on')} aria-hidden="true" />
          {hasAiConfigured() ? '已配置 API 服务' : '未配置 API：可在「设置 → AI 服务」接入'}
        </span>
      </div>

      <Card className="v3-asst-tools" variant="tonal">
        <button type="button" className="v3-asst-tools__toggle" onClick={() => setShowTools((v) => !v)} aria-expanded={showTools}>
          <span className="v3-asst-tools__icon"><Wand size={17} /></span>
          <span className="v3-asst-tools__text">
            <strong>DeepStudent 智能学习工具</strong>
            <small>作文批改 / 翻译 / 错题讲解 / 知识导图 / 知识库问答 / 一键转卡</small>
          </span>
          <span className={cx('v3-asst-tools__chev', showTools && 'is-open')}><ChevronDown size={16} /></span>
        </button>
        {showTools ? (
          <div className="v3-asst-tools__body">
            <DeepTools send={send} notebook={notebook} pan={pan} words={words} cards={cards} packs={packs} addCard={addCard} />
          </div>
        ) : null}
      </Card>

      <div className="v3-asst-layout">
        <div className="v3-asst-main">
          <Card className="v3-asst-chat">
            <CardHead
              icon={<Bot size={17} />}
              title={`与「${ai.persona}」对话`}
              sub={`${ai.messages.length} 条消息 · ${mode}模式`}
              actions={(
                <>
                  {useRag ? <Badge tone="primary">RAG</Badge> : null}
                  <IconButton
                    label="清空对话"
                    icon={<RefreshCw size={16} />}
                    onClick={() => { clearAi(); setRefs(null); toast('已清空对话') }}
                  />
                </>
              )}
            />
            <div ref={bodyRef} className="v3-asst-chat__body" aria-live="polite">
              {ai.messages.length === 0 && !typing && (
                <Empty
                  className="v3-asst-empty"
                  icon={<Sparkles size={28} />}
                  title={`你好，我是你的考研画像助手「${ai.persona}」`}
                  text={(
                    <>
                      已知你在备考 {[settings.school, settings.major].filter(Boolean).join(' ') || '（尚未设置目标院校，去设置填写）'}
                      {settings.targetScore ? `（目标 ${settings.targetScore} 分）` : ''}，{ctx.when}。<br />
                      可以问我学习方法、阶段规划、科目难点，或点下面的快捷问题。
                    </>
                  )}
                  action={(
                    <div className="v3-asst-empty__prompts">
                      {prompts.slice(0, 3).map((q) => (
                        <Chip key={q} icon={<Sparkles size={13} />} onClick={() => send(q)}>{q}</Chip>
                      ))}
                    </div>
                  )}
                />
              )}

              {ai.messages.map((m, i) => (
                <div key={i} className={cx('v3-asst-msg', m.role === 'user' && 'is-user')}>
                  {m.role === 'bot'
                    ? <span className={cx('v3-asst-avatar', 'is-bot', m.error && 'is-error')} aria-hidden="true">{m.error ? <AlertTriangle size={15} /> : <Sparkles size={15} />}</span>
                    : <Avatar name="我" size="sm" className="v3-asst-avatar is-user" />}
                  <div className={cx('v3-asst-bubble', m.role === 'user' ? 'is-user' : 'is-bot', m.error && 'is-error')}>
                    {m.role === 'bot'
                      ? <MathText text={m.content} className="v3-asst-bubble__content" />
                      : <span className="v3-asst-bubble__content">{m.content}</span>}
                    {m.streaming && <span className="v3-asst-caret" />}
                    {m.error && m.retry && (
                      <div className="v3-asst-bubble__retry">
                        <Button variant="text" size="sm" icon={<RefreshCw size={14} />} onClick={() => retrySend(m.retry)}>重试</Button>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {typing && (
                <div className="v3-asst-msg">
                  <span className="v3-asst-avatar is-bot" aria-hidden="true"><Sparkles size={15} /></span>
                  <div className="v3-asst-bubble is-bot v3-asst-typing" role="status" aria-label="AI 正在输入">
                    <i /><i /><i />
                    <em>{canStop ? '正在生成回答…' : '正在分析…'}</em>
                  </div>
                </div>
              )}
            </div>

            {(refLoading || (refs && refs.hits.length > 0)) && (
              <div className="v3-asst-refs">
                <div className="v3-asst-refs__head">
                  <span className="v3-asst-refs__title"><Paperclip size={14} /> 本轮引用 · 本地知识库</span>
                  {refLoading
                    ? <Skeleton width={64} height={18} radius="999px" />
                    : <Badge tone="primary">{refs.hits.length} 条命中</Badge>}
                </div>
                {refLoading ? (
                  <div className="v3-asst-refs__loading">
                    <Skeleton width="72%" height={26} radius="999px" />
                    <Skeleton width="54%" height={26} radius="999px" />
                  </div>
                ) : (
                  <div className="v3-asst-refs__list">
                    {refs.hits.map((h, i) => (
                      <Chip key={`${h.chunk_id || h.doc_id || 'h'}-${i}`} active onClick={() => setRefDetail(h)} title={(h.content || '').slice(0, 100)}>
                        [{i + 1}] {(h.title || h.source || '知识片段').slice(0, 18)}{h.subject ? ` · ${h.subject}` : ''}
                      </Chip>
                    ))}
                  </div>
                )}
                {refs && refs.hits.length > 0 ? (
                  <p className="v3-asst-refs__hint">点击引用可查看原文片段；这些片段已随本轮提问注入 AI 上下文。</p>
                ) : null}
              </div>
            )}
          </Card>

          <Card className="v3-asst-composer">
            <Textarea
              rows={3}
              aria-label="向 AI 助手提问"
              placeholder={`向「${ai.persona}」提问…（Enter 发送，Shift+Enter 换行）`}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
            />

            {image && (
              <div className="v3-asst-attach">
                <img src={image.preview} alt="待分析图片" />
                <div className="v3-asst-attach__meta">
                  <strong>{image.name}</strong>
                  <span>发送后自动启用电路读图分析（VLM 读图较慢，请耐心等待）</span>
                </div>
                <IconButton label="移除图片" icon={<X size={16} />} onClick={() => setImage(null)} />
              </div>
            )}
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/bmp" aria-label="选择图片文件" hidden onChange={onPickImage} />

            <div className="v3-asst-composer__bar">
              <div className="v3-asst-composer__left">
                <Button
                  variant="text"
                  size="sm"
                  icon={<Image size={15} />}
                  title="附加电路图/题目图片，发送后自动启用电路读图分析"
                  disabled={imgUploading}
                  onClick={() => fileRef.current?.click()}
                >
                  {imgUploading ? '上传中…' : '图片'}
                </Button>
                <span className="v3-asst-rag">
                  <span>知识库增强</span>
                  <Switch
                    checked={useRag}
                    label="知识库增强"
                    onChange={() => { setUseRag((v) => !v); toast(useRag ? '已关闭本地知识库增强（RAG）' : '已开启本地知识库增强（RAG）') }}
                  />
                </span>
                <span className="v3-asst-composer__hint">
                  {useSummary && summary ? '上下文：摘要 + 最近 2 轮' : '上下文：最近 4 轮原文'}
                </span>
              </div>
              <div className="v3-asst-composer__right">
                {typing && canStop ? (
                  <Button variant="danger" size="sm" icon={<Pause size={15} />} onClick={stopGenerating}>停止</Button>
                ) : null}
                <Button
                  variant={typing ? 'tonal' : 'gradient'}
                  icon={typing ? <Loader size={16} /> : <Send size={16} />}
                  onClick={() => send()}
                  disabled={typing || (!input.trim() && !image)}
                >
                  {typing ? (thinkingText || '生成中…') : '发送'}
                </Button>
              </div>
            </div>
            {thinkingText ? (
              <div className="v3-asst-thinking" role="status">{thinkingText}</div>
            ) : null}
          </Card>
        </div>

        <aside className="v3-asst-rail">
          <Card className="v3-asst-panel">
            <CardHead
              icon={<Brain size={17} />}
              title="上下文摘要"
              actions={(
                <Switch
                  checked={!!(useSummary && summary)}
                  label="启用摘要上下文"
                  onChange={() => {
                    if (!summary) { toast('请先生成摘要'); return }
                    setUseSummary((v) => !v)
                    toast(useSummary ? '已停用摘要上下文' : '已启用摘要上下文')
                  }}
                />
              )}
            />
            <div className="v3-asst-panel__body">
              {summary ? (
                <>
                  <p className="v3-asst-summary">{summary}</p>
                  <div className="v3-asst-panel__actions">
                    <Button variant="text" size="sm" onClick={() => setShowSummary(true)}>查看全文</Button>
                    <Button variant="text" size="sm" onClick={makeSummary} disabled={summarizing}>{summarizing ? '重生成中…' : '重新生成'}</Button>
                  </div>
                </>
              ) : (
                <>
                  <p className="v3-asst-panel__hint">
                    对话变长后，把历史压成一段摘要：后续提问只带「摘要 + 最近 2 轮」，既省 token 又不丢上下文。未配置 AI 时自动生成本地摘要。
                  </p>
                  <Button variant="gradient" size="sm" className="v3-asst-panel__cta" onClick={makeSummary} disabled={summarizing || ai.messages.length < 2}>
                    {summarizing ? '生成中…' : '生成摘要'}
                  </Button>
                </>
              )}
            </div>
          </Card>

          <Card className="v3-asst-panel">
            <CardHead
              icon={<MessageSquare size={17} />}
              title="会话记录"
              actions={<Button variant="tonal" size="sm" icon={<Plus size={14} />} onClick={newChat}>新建</Button>}
            />
            <div className="v3-asst-sessions">
              {sessions.length === 0 ? (
                <p className="v3-asst-panel__hint">暂无会话，点「新建」开始。</p>
              ) : sessions.map((s) => (
                <div
                  key={s.id}
                  role="button"
                  tabIndex={0}
                  className={cx('v3-asst-session', activeSession === s.id && 'is-active')}
                  onClick={() => selectSession(s.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectSession(s.id) }
                  }}
                >
                  <div className="v3-asst-session__main">
                    <span className="v3-asst-session__title">{s.title || '未命名会话'}</span>
                    <span className="v3-asst-session__meta">{(s.messages || []).length} 条消息</span>
                  </div>
                  <span className="v3-asst-session__actions">
                    <IconButton label="改名" size="sm" icon={<Edit size={14} />} onClick={(e) => { e.stopPropagation(); openRename(s) }} />
                    <IconButton label="删除会话" size="sm" icon={<Trash size={14} />} onClick={(e) => { e.stopPropagation(); removeSession(s.id) }} />
                  </span>
                </div>
              ))}
            </div>
            <p className="v3-asst-panel__hint">会话与多轮上下文保存在本机浏览器，切换会话可继续之前的话题。</p>
          </Card>

          <Card className="v3-asst-panel">
            <CardHead icon={<Lightbulb size={17} />} title="快捷提问" />
            <div className="v3-asst-quick">
              {prompts.map((q) => (
                <Chip key={q} disabled={typing} onClick={() => send(q)}>{q}</Chip>
              ))}
            </div>
          </Card>

          <Card className="v3-asst-panel">
            <CardHead icon={<User size={17} />} title="我的画像" />
            <dl className="v3-asst-profile">
              <div><dt>目标院校</dt><dd>{settings.school || '未设置'}</dd></div>
              <div><dt>专业</dt><dd>{settings.major || '未设置'}</dd></div>
              <div><dt>目标分数</dt><dd>{settings.targetScore || '—'}</dd></div>
              <div>
                <dt>距考研</dt>
                <dd>
                  <Badge tone={ctx.days == null ? 'outline' : 'warning'}>{ctx.days == null ? '未设置' : `${ctx.days} 天`}</Badge>
                </dd>
              </div>
              <div className="is-wide"><dt>错题 / 单词 / 卡片</dt><dd>{notebook.length} / {words.length} / {cards.length}</dd></div>
            </dl>
          </Card>
        </aside>
      </div>

      <Dialog
        open={!!refDetail}
        title={refDetail ? (refDetail.title || refDetail.source || '知识片段') : ''}
        onClose={() => setRefDetail(null)}
        wide
        footer={refDetail ? (
          <>
            <Button variant="text" onClick={() => setRefDetail(null)}>关闭</Button>
            <Button
              variant="gradient"
              onClick={() => {
                const seg = (refDetail.content || '').slice(0, 160)
                setInput(`结合这段资料继续讲解：\n「${seg}」\n请说明它在考试中怎么考、易错点是什么。`)
                setRefDetail(null)
                toast('已填入输入框，可直接发送追问')
              }}
            >追问这段</Button>
          </>
        ) : null}
      >
        {refDetail && (
          <div className="v3-asst-stack">
            <div className="v3-asst-refmeta">
              <Badge tone="primary">{refDetail.source || '知识分块'}</Badge>
              {refDetail.subject && <Badge tone="outline">{refDetail.subject}</Badge>}
              {refDetail.score != null && <Badge tone="success">相关度 {Number(refDetail.score).toFixed(2)}</Badge>}
              {refDetail.doc_id != null && <Badge tone="outline">文档 #{refDetail.doc_id}</Badge>}
            </div>
            <div className="v3-asst-refdetail">
              {refDetail.content || '（该片段无正文内容）'}
            </div>
          </div>
        )}
      </Dialog>

      <Dialog
        open={showSummary && !!summary}
        title="多轮上下文摘要"
        onClose={() => setShowSummary(false)}
        footer={(
          <>
            <Button
              variant="text"
              icon={<Copy size={15} />}
              onClick={() => { navigator.clipboard?.writeText(summary); toastOk('摘要已复制') }}
            >复制</Button>
            <Button variant="filled" icon={<Check size={15} />} onClick={() => setShowSummary(false)}>知道了</Button>
          </>
        )}
      >
        <div className="v3-asst-summary-full">{summary}</div>
        <p className="v3-asst-panel__hint">
          启用后，向「自定义 API」引擎提问时会把这段摘要写入 system 提示，并只附带最近 2 轮原文。
        </p>
      </Dialog>

      <Dialog
        open={!!renameTarget}
        title="重命名会话"
        onClose={() => setRenameTarget(null)}
        footer={(
          <>
            <Button variant="text" onClick={() => setRenameTarget(null)}>取消</Button>
            <Button variant="gradient" onClick={submitRename} disabled={!renameValue.trim()}>保存</Button>
          </>
        )}
      >
        <Field label="会话标题" hint="留空不会保存；标题仅保存在本机浏览器。">
          <Input
            value={renameValue}
            maxLength={60}
            placeholder="给这段对话起个名字"
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); submitRename() } }}
          />
        </Field>
      </Dialog>
    </div>
  )
}
