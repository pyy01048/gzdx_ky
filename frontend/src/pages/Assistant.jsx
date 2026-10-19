import React, { useEffect, useRef, useState } from 'react'
import useStore from '../store/useStore'
import { uid } from '../utils/date'
import { examDaysLeft, resolveExamDate } from '../utils/exam'
import { Modal, toast } from '../components/UI'
import { chatCompletion, defaultProvider, hasAiConfigured, recordUsage } from '../utils/api'
import { aiApi, aiChatStream } from '../api/client'
import { useSubjectConfig } from '../hooks/useSubjectConfig'
import DeepTools from '../components/DeepTools'

/* ============================================================
   AI 助手（V2 冷蓝）
   引擎（批次1-2：移除恒不可用的 CodeBuddy Agent 引擎，其 9 个端点后端零实现）：
   1) 自定义 AI API（设置中配置的多服务商，SSE 流式 + RAG）—— 走 /api/ai/chat/stream
   2) 本地画像规则引擎（离线兜底）

   V2 新增：
   · RAG 引用 chip —— 每轮提问同步检索本地知识库，命中片段以 chip 展示、可点开原文
   · 多轮上下文摘要 —— 一键把长对话压成摘要，后续提问只带「摘要 + 最近 2 轮」，省 token 又不丢上下文
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
    // 专业课话术必须来自用户配置的科目：此前这里写死了"贵州大学 834（数电+模电）"，
    // 换一所学校/一个方向，这段"建议"就成了别人的备考信息。
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

/* 快捷提问里那条"专业课重点"用真实科目名替换：写死科目码会让芯片上出现
   用户根本没考的科目，且点出来的建议与他无关。 */
function quickPrompts(subjects) {
  const first = (subjects || []).filter(Boolean)[0]
  if (!first) return QUICK
  return QUICK.map((q) => (q === '专业课重点是什么？' ? `${first} 重点是什么？` : q))
}

const ENGINES = [
  { key: 'api', name: 'API', full: '自定义 AI API' },
  { key: 'local', name: '本地', full: '本地规则模式' }
]

/* 本地摘要兜底：无 AI 配置时也能生成可读的上下文摘要 */
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

/* P0-5：AI 失败 → 用户可见文案。
   过去 SSE 的 error 事件被 utils/api.js 当成「非 JSON 噪声」吞掉，界面既不出现
   回答也不报错，用户只能以为"卡住了"。现在 api/client.js 的 aiChatStream 会抛出
   带 code 的 ApiError，这里按 code 给出**可操作**的提示（区别于笼统一句"失败"）。 */
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
  /* 字段级选择器：store 其他字段变化不再触发本页重渲染（actions 引用稳定，不会引发额外渲染） */
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
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [mode, setMode] = useState('答疑') // 答疑 | 规划
  const [engine, setEngine] = useState('api') // api | local（批次1-2：移除恒不可用的 agent 引擎）
  const [useRag, setUseRag] = useState(true) // API 引擎下是否启用本地知识库 RAG
  // T4 电路读图：待发送的图片（{path, name, preview}），发送后自动清除
  const [image, setImage] = useState(null)
  const [imgUploading, setImgUploading] = useState(false)
  const fileRef = useRef(null)

  const onPickImage = async (e) => {
    const f = e.target.files?.[0]
    e.target.value = '' // 允许连续选同一张
    if (!f) return
    setImgUploading(true)
    try {
      const r = await aiApi.uploadImage(f)
      setImage({ path: r.path, name: f.name, preview: URL.createObjectURL(f) })
      toast('图片已附加：发送后将自动启用电路读图分析（较慢，请耐心等待）')
    } catch (err) {
      toast(`图片上传失败：${err.message}`)
    }
    setImgUploading(false)
  }
  // 批次1-2：会话管理改本地持久化（列表挂在 store 的 ai.localSessions，随 zustand persist 落 localStorage）
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [showTools, setShowTools] = useState(false)
  const endRef = useRef(null)

  /* 新功能① RAG 引用 */
  const [refs, setRefs] = useState(null) // { query, hits: [] }
  const [refLoading, setRefLoading] = useState(false)
  const [refDetail, setRefDetail] = useState(null)

  /* 新功能② 多轮上下文摘要 */
  const [summary, setSummary] = useState('')
  const [summarizing, setSummarizing] = useState(false)
  const [useSummary, setUseSummary] = useState(false)
  const [showSummary, setShowSummary] = useState(false)

  const settings = useStore((s) => s.settings)
  const countdown = useStore((s) => s.countdown)
  /* 专业课建议的话术来源：用户在「设置 → 备考科目」配置的科目，不写死学校与科目码 */
  const { active: configuredSubjects } = useSubjectConfig()
  // 未设置初试日期时 days 为 null，各文案统一用 ctx.when（"未设置初试日期"），不再假装有天数
  // 优先使用本地设置（实时更新），后端仅作为初始值和离线兜底
  const effectiveDate = settings.examDate || countdown?.exam_date;
  const days = examDaysLeft(resolveExamDate(effectiveDate, null))
  const ctx = {
    days,
    when: days == null ? '未设置初试日期' : `距考试 ${days} 天`,
    // 已配置科目就取真实配置；未配置（后端不可达）时传空数组，让文案自己承认不知道
    subjects: configuredSubjects,
  }

  /* 批次1-2：把会话列表与激活 id 写回 store（ai.localSessions / ai.activeSessionId），随 persist 落 localStorage */
  const persistSessions = (list, activeId) => {
    useStore.setState({ ai: { ...useStore.getState().ai, localSessions: list, activeSessionId: activeId } })
  }
  /* 由首条用户消息推导会话标题（本地自动命名） */
  const titleFromMessages = (msgs) => {
    const u = (msgs || []).find((m) => m.role === 'user')
    const t = (u?.content || '').trim()
    return t ? (t.length > 18 ? t.slice(0, 18) + '…' : t) : '新会话'
  }

  /* 初始化：从 store 恢复本地会话列表与当前会话（批次1-2：不再探测后端 Agent） */
  useEffect(() => {
    const ai = useStore.getState().ai
    setSessions(ai.localSessions || [])
    setActiveSession(ai.activeSessionId || null)
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [ai.messages, typing])

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

  /* ---------- 新功能① 本地知识库引用检索（真实调用 /api/ai/rag-search） ---------- */
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

  /* ---------- 新功能② 多轮上下文摘要 ---------- */
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
        try { recordUsage(r.usage, provider?.key) } catch { /* ignore */ }
      } else {
        setSummary(localSummary(msgs))
      }
      setUseSummary(true)
      setShowSummary(true)
      toast('已生成上下文摘要，后续提问将自动携带')
    } catch (e) {
      setSummary(localSummary(msgs))
      setUseSummary(true)
      setShowSummary(true)
      toast(`AI 摘要失败，已改用本地摘要：${e.message}`)
    }
    setSummarizing(false)
  }

  /* 失败气泡：显式错误态 + 重试入口（P0-5）。
     error=true 的气泡走 .as-bubble.error 红色样式，并在下方带「重试」按钮；
     重试时先清掉所有错误气泡，再原样重发上一条提问。 */
  const pushError = (text, retryText) => {
    const st = useStore.getState()
    useStore.setState({
      ai: { ...st.ai, messages: [...st.ai.messages, { role: 'bot', content: text, error: true, retry: retryText || '' }] }
    })
  }
  const retrySend = (text) => {
    const st = useStore.getState()
    useStore.setState({ ai: { ...st.ai, messages: st.ai.messages.filter((m) => !m.error) } })
    send(text)
  }

  const send = async (text) => {
    const q = (text ?? input).trim()
    if ((!q && !image) || typing) return
    const question = q || '请分析这张电路图'
    sendAi(question + (image ? ' 图片' : ''))
    setInput('')
    // 并行检索本地知识库引用，不阻塞对话
    loadRefs(q)

    // T4 电路读图：带图走后端智能路由（Agentic 状态机 → circuit_analysis/qwen2.5vl）。
    // 非流式：链路含 VLM 载入可能要数分钟，期间 typing 状态阻止重复发送
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
        replyAi(`${r.content || '（模型未返回内容）'}${steps ? `\n\n---\n搜索 推理链：${steps}` : ''}`)
      } catch (e) {
        replyAi(`注意 读图分析失败：${e.message}\n\n可尝试：① 确认本地 Ollama 已启动；② 稍后重试（批量答案回填期间 GPU 繁忙会显著拖慢读图）。`)
      }
      setTyping(false)
      return
    }

    // 流式追加 bot 回复（SSE delta 逐段拼接）
    const streamAppend = (delta) => {
      const st = useStore.getState()
      const msgs = st.ai.messages
      const last = msgs[msgs.length - 1]
      // 上一条是错误气泡时另起一条正常回复，避免把答案拼到错误文案后面
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
      // API模式总是可用：前端配置了provider用前端的，否则后端使用默认provider
      if (engine === 'api') {
        const summaryBlock = useSummary && summary ? `\n\n【此前对话摘要（已压缩上下文）】\n${summary}` : ''
        const profile = [
          [settings.school, settings.major].filter(Boolean).join(' '),
          settings.targetScore ? `目标 ${settings.targetScore} 分` : '',
          // 已配置科目直接给模型：否则它只能猜，答案会飘到别的专业方向上
          ctx.subjects.length ? `备考科目：${ctx.subjects.join('、')}` : '',
          ctx.days == null ? '' : `距考研 ${ctx.days} 天`
        ].filter(Boolean).join('，')
        const system = `你是考研备考助手「${ai.persona}」。${profile ? `用户正在备考 ${profile}。` : ''}当前模式：${mode}。${mode === '规划' ? '请给出分阶段可执行的复习计划。' : '请专业、简洁地解答考研相关问题，必要时用列表。'}${summaryBlock}`
        // 开启摘要后只带最近 4 条原文，其余靠摘要承载
        const keep = useSummary && summary ? -4 : -8
        // 错误气泡不进历史上下文（否则下一轮会把报错文案当成模型说过的话）
        const history = ai.messages.filter((m) => !m.error).slice(keep)
          .map((m) => ({ role: m.role === 'bot' ? 'assistant' : 'user', content: m.content }))
        // SSE 流式输出 + 本地知识库 RAG
        let streamed = false
        try {
          const streamBody = {
            messages: [{ role: 'system', content: system }, ...history, { role: 'user', content: q }],
            use_rag: useRag,
          }
          // 前端配置了服务商时随流覆盖，否则交给后端默认服务商（与旧 chatStream 口径一致）
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
          await aiChatStream(streamBody, {
            onDelta: (ev) => {
              if (ev.content) {
                streamed = true
                streamAppend(ev.content)
              }
            }
          })
        } catch (e) {
          if (!streamed) throw e // 一个字都没吐出来：走统一失败分支，给用户完整原因
          replyAi(`\n\n注意 流式中断：${e.message}`)
        }
        // 有些服务商会返回 200 空流：不报错、也没有 delta。这里必须显式提示，
        // 否则用户只会看到“消息发出去了但没有任何回答”。
        if (!streamed) {
          throw new Error('模型未返回任何内容（可能是服务商额度、模型名或流式配置问题）')
        }
        // 结束流式光标
        const st = useStore.getState()
        const msgs = st.ai.messages
        useStore.setState({
          ai: { ...st.ai, messages: msgs.map((m, i) => (i === msgs.length - 1 ? { ...m, streaming: false } : m)) }
        })
      } else {
        // 本地规则模式是同步计算出来的，不装"网络延迟"：过去这里用 700+random(500)ms
        // 伪装成模型在思考，让人把等待时间当成真实推理耗时。
        replyAi(think(q))
        setTyping(false)
      }
    } catch (e) {
      // 失败时不再自动拼一段本地规则文案冒充 AI 回答：只报错，本地内容由用户显式切换引擎获得。
      // P0-5：气泡 + toast 双通道提示，并带上「重试」按钮，绝不静默。
      pushError(aiFailBubble(e), question)
      toast(aiFailToast(e))
    }
    setTyping(false)
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
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
    toast(ENGINES.find((e) => e.key === key)?.full + ' 引擎已启用')
  }

  /* 新建会话：先把当前对话快照进旧会话（首次使用则把已有对话归档为一条历史），再开空白本地会话 */
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

  /* 切换会话：把当前对话快照进原会话，再载入目标会话历史（全程本地 store 闭环，不依赖后端） */
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

  const doRename = (s) => {
    const title = window.prompt('会话标题', s.title || '')
    if (title === null) return
    const t = title.trim()
    if (!t) return
    const list = sessions.map((it) => (it.id === s.id ? { ...it, title: t } : it))
    setSessions(list)
    persistSessions(list, activeSession)
    toast('已重命名')
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
        // 删空了：开一个全新空白会话
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

  return (
    <div>
      <style>{`
        .as-grid { display: grid; grid-template-columns: minmax(0,1fr) 322px; gap: 16px; align-items: start; }
        @media (max-width: 1080px) { .as-grid { grid-template-columns: 1fr; } }
        .as-scroll { max-height: 54vh; min-height: 300px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
        .as-msg { display: flex; gap: 10px; align-items: flex-start; }
        .as-msg.user { flex-direction: row-reverse; }
        .as-bubble { max-width: 78%; padding: 11px 14px; border-radius: var(--radius-md); font-size: 13.5px; line-height: 1.85; white-space: pre-wrap; word-break: break-word; }
        .as-msg.bot .as-bubble { background: var(--surface-2); color: var(--fg); border: 1px solid var(--border); }
        .as-msg.user .as-bubble { background: var(--accent); color: #fff; }
        /* P0-5 错误气泡：沿用 tokens 的危险色，不新增配色 */
        .as-bubble.error { background: var(--danger-soft); color: var(--danger-ink); border: 1px solid var(--danger-border); }
        .as-av { width: 32px; height: 32px; font-size: 12.5px; }
        .as-caret { display: inline-block; width: 7px; animation: as-blink 1s steps(2) infinite; }
        @keyframes as-blink { 50% { opacity: 0 } }
        .as-side { position: sticky; top: 12px; }
        @media (max-width: 1080px) { .as-side { position: static; } }
      `}</style>

      <div className="page-head">
        <div>
          <h1 className="page-title">AI 助手</h1>
          <p className="page-sub">
            <span className="badge info">会话保存在本机浏览器</span>
            <span style={{ marginLeft: 'var(--space-2)' }}>当前引擎：{engineLabel}</span>
          </p>
        </div>
        <div className="page-actions">
          <div className="segmented">
            {ENGINES.map((e) => (
              <button key={e.key} className={`seg ${engine === e.key ? 'active' : ''}`} onClick={() => switchEngine(e.key)} title={e.full}>{e.name}</button>
            ))}
          </div>
          <div className="segmented">
            {['答疑', '规划'].map((m) => (
              <button key={m} className={`seg ${mode === m ? 'active' : ''}`} onClick={() => switchMode(m)}>{m}</button>
            ))}
          </div>
          <button className="btn ghost" onClick={() => { clearAi(); setRefs(null); toast('已清空对话') }}>清空</button>
        </div>
      </div>

      {/* DeepStudent 智能学习工具（保留） */}
      <div className="toolbar" style={{ marginBottom: 'var(--space-3)' }}>
        <div className="left">
          <button className="btn ghost" onClick={() => setShowTools((v) => !v)}>{showTools ? '收起' : '展开'} DeepStudent 智能学习工具 ▾</button>
          <span className="badge info">作文批改 / 翻译 / 错题讲解 / 知识导图 / 知识库问答 / 一键转卡</span>
        </div>
      </div>
      {showTools && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <DeepTools send={send} notebook={notebook} pan={pan} words={words} cards={cards} packs={packs} addCard={addCard} />
        </div>
      )}

      <div className="as-grid">
        {/* ============ 左：对话主区 ============ */}
        <div className="stack">
          <div className="card">
            <div className="card-head">
              <div className="card-title">与「{ai.persona}」对话</div>
              <div className="row" style={{ gap: 'var(--space-2)' }}>
                <span className="badge">{ai.messages.length} 条消息</span>
                {useSummary && summary && <span className="badge accent">摘要上下文已启用</span>}
                {useRag && <span className="badge info">RAG</span>}
              </div>
            </div>
            <div className="card-body as-scroll">
              {ai.messages.length === 0 && !typing && (
                <div className="empty">
                  <div className="e-ico">学习</div>
                  <div className="e-title">你好，我是你的考研画像助手「{ai.persona}」</div>
                  <div className="e-text">
                    已知你在备考 {[settings.school, settings.major].filter(Boolean).join(' ') || '（尚未设置目标院校，去设置填写）'}
                    {settings.targetScore ? `（目标 ${settings.targetScore} 分）` : ''}，{ctx.when}。<br />
                    可以问我学习方法、阶段规划、科目难点，或点右侧快捷问题。
                  </div>
                </div>
              )}
              {ai.messages.map((m, i) => (
                <div key={i} className={`as-msg ${m.role}`}>
                  <div className="avatar as-av">{m.role === 'bot' ? '档' : '我'}</div>
                  <div className={`as-bubble${m.error ? ' error' : ''}`}>
                    {m.content}{m.streaming && <span className="as-caret">▍</span>}
                    {/* P0-5：错误气泡保留重试入口，用户不必手动重打一遍问题 */}
                    {m.error && m.retry && (
                      <div style={{ marginTop: 'var(--space-2)' }}>
                        <button className="btn mini ghost" onClick={() => retrySend(m.retry)}>重试</button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {typing && (
                <div className="as-msg bot">
                  <div className="avatar as-av">档</div>
                  <div className="as-bubble"><span className="loading-inline"><i />正在思考…</span></div>
                </div>
              )}
              <div ref={endRef} />
            </div>

            {/* 新功能① RAG 引用 chip */}
            {(refLoading || (refs && refs.hits.length > 0)) && (
              <div className="card-foot" style={{ display: 'block' }}>
                <div className="sec-title" style={{ margin: '0 0 var(--space-2)' }}>
                  <h3 style={{ fontSize: 'var(--text-sm)' }}>附件 本轮引用 · 本地知识库</h3>
                  {refLoading
                    ? <span className="loading-inline"><i />检索中</span>
                    : <span className="badge info">{refs.hits.length} 条命中</span>}
                </div>
                {refs && refs.hits.length > 0 && (
                  <div className="row" style={{ flexWrap: 'wrap', gap: 'var(--space-2)' }}>
                    {refs.hits.map((h, i) => (
                      <button key={`${h.chunk_id || h.doc_id || 'h'}-${i}`} className="chip active" onClick={() => setRefDetail(h)} title={(h.content || '').slice(0, 100)}>
                        [{i + 1}] {(h.title || h.source || '知识片段').slice(0, 18)}{h.subject ? ` · ${h.subject}` : ''}
                      </button>
                    ))}
                  </div>
                )}
                {refs && refs.hits.length > 0 && (
                  <p style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', margin: 'var(--space-2) 0 0' }}>点击引用可查看原文片段；这些片段已随本轮提问注入 AI 上下文。</p>
                )}
              </div>
            )}
          </div>

          {/* 输入区 */}
          <div className="card">
            <div className="card-body">
              <div className="field">
                <textarea
                  className="textarea"
                  rows={3}
                  aria-label="向 AI 助手提问"
                  placeholder={`向「${ai.persona}」提问…（Enter 发送，Shift+Enter 换行）`}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={onKey}
                />
              </div>

              {/* T4 电路读图：图片附加。发送后走智能路由的电路分析分支 */}
              {image && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', margin: 'var(--space-2) 0 0', padding: 'var(--space-2) var(--space-3)', border: '1px dashed var(--border)', borderRadius: 8, background: 'var(--surface-2)' }}>
                  <img src={image.preview} alt="待分析图片" style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 6 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>图片 {image.name}</div>
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>发送后将自动启用电路读图分析（VLM 读图较慢，请耐心等待）</div>
                  </div>
                  <button className="mini-btn" onClick={() => setImage(null)}>移除</button>
                </div>
              )}
              <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/bmp" aria-label="选择图片文件" hidden onChange={onPickImage} />

              <div className="toolbar" style={{ marginTop: 'var(--space-3)' }}>
                <div className="left">
                  <span className="row" style={{ gap: 'var(--space-2)' }}>
                    <button
                      className="mini-btn"
                      title="附加电路图/题目图片，发送后自动启用电路读图分析"
                      disabled={imgUploading}
                      onClick={() => fileRef.current?.click()}>
                      {imgUploading ? '上传中…' : '图片 图片'}
                    </button>
                  </span>
                  <span className="row" style={{ gap: 'var(--space-2)' }}>
                    <span style={{ fontSize: 'var(--text-xs)', color: 'var(--fg-2)' }}>知识库增强</span>
                    <span
                      className={`switch ${useRag ? 'on' : ''}`}
                      role="switch"
                      aria-checked={useRag}
                      title="开启后 AI 回答会参考你导入的考研资料，并展示引用来源"
                      onClick={() => { setUseRag((v) => !v); toast(useRag ? '已关闭本地知识库增强（RAG）' : '已开启本地知识库增强（RAG）') }}
                    ><i className="knob" /></span>
                  </span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>{useSummary && summary ? '上下文：摘要 + 最近 2 轮' : '上下文：最近 4 轮原文'}</span>
                </div>
                <div className="right">
                  <button className="btn primary" onClick={() => send()} disabled={typing || !input.trim()}>{typing ? '生成中…' : '发送'}</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ============ 右：侧栏 ============ */}
        <div className="stack as-side">
          {/* 新功能② 多轮上下文摘要 */}
          <div className="card">
            <div className="card-head">
              <div className="card-title">模块 上下文摘要</div>
              <span className="row" style={{ gap: 'var(--space-2)' }}>
                <span style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>启用</span>
                <span
                  className={`switch ${useSummary && summary ? 'on' : ''}`}
                  role="switch"
                  aria-checked={!!(useSummary && summary)}
                  title="启用后提问只携带「摘要 + 最近 2 轮」，节省 token"
                  onClick={() => {
                    if (!summary) { toast('请先生成摘要'); return }
                    setUseSummary((v) => !v)
                    toast(useSummary ? '已停用摘要上下文' : '已启用摘要上下文')
                  }}
                ><i className="knob" /></span>
              </span>
            </div>
            <div className="card-body">
              {summary ? (
                <>
                  <p style={{ fontSize: 'var(--text-xs)', lineHeight: 1.8, color: 'var(--fg-2)', whiteSpace: 'pre-wrap', margin: 0, maxHeight: 132, overflow: 'hidden' }}>{summary}</p>
                  <div className="row" style={{ gap: 'var(--space-2)', marginTop: 'var(--space-3)' }}>
                    <button className="btn ghost" onClick={() => setShowSummary(true)}>查看全文</button>
                    <button className="btn ghost" onClick={makeSummary} disabled={summarizing}>{summarizing ? '重生成中…' : '重新生成'}</button>
                  </div>
                </>
              ) : (
                <>
                  <p style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', lineHeight: 1.8, margin: '0 0 var(--space-3)' }}>
                    对话变长后，把历史压成一段摘要：后续提问只带「摘要 + 最近 2 轮」，既省 token 又不丢上下文。未配置 AI 时自动生成本地摘要。
                  </p>
                  <button className="btn primary" style={{ width: '100%' }} onClick={makeSummary} disabled={summarizing || ai.messages.length < 2}>
                    {summarizing ? '生成中…' : '生成摘要'}
                  </button>
                </>
              )}
            </div>
          </div>

          {/* 会话列表（批次1-2：改本地持久化，保留原 UI，不再依赖后端 Agent） */}
          <div className="card">
            <div className="card-head">
              <div className="card-title">对话 会话记录</div>
              <div className="row" style={{ gap: 'var(--space-2)' }}>
                <button className="btn primary" onClick={newChat}>+ 新建</button>
              </div>
            </div>
            <div className="card-body">
              {sessions.length === 0 ? (
                <p style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', margin: 0 }}>暂无会话，点「+ 新建」开始</p>
              ) : (
                <div className="list">
                  {sessions.map((s) => (
                    <div key={s.id} className={`list-row ${activeSession === s.id ? 'active' : ''}`} onClick={() => selectSession(s.id)} style={{ cursor: 'pointer' }}>
                      <div className="lr-main">
                        <div className="lr-title" style={{ fontSize: 'var(--text-sm)' }}>{s.title || '未命名会话'}</div>
                        <div className="lr-meta">{(s.messages || []).length} 条消息</div>
                      </div>
                      <div className="lr-actions">
                        <button className="btn ghost" onClick={(e) => { e.stopPropagation(); doRename(s) }}>改名</button>
                        <button className="btn ghost danger" onClick={(e) => { e.stopPropagation(); removeSession(s.id) }}>删</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', marginTop: 'var(--space-3)', marginBottom: 0 }}>会话与多轮上下文保存在本机浏览器，切换会话可继续之前的话题。</p>
            </div>
          </div>

          {/* 快捷问题 */}
          <div className="card">
            <div className="card-head"><div className="card-title">快速 快捷提问</div></div>
            <div className="card-body">
              <div className="row" style={{ flexWrap: 'wrap', gap: 'var(--space-2)' }}>
                {quickPrompts(ctx.subjects).map((q) => <button key={q} className="chip" onClick={() => send(q)} disabled={typing}>{q}</button>)}
              </div>
            </div>
          </div>

          {/* 画像信息 */}
          <div className="card">
            <div className="card-head"><div className="card-title">我的画像</div></div>
            <div className="card-body stack" style={{ gap: 'var(--space-2)' }}>
              <div className="spread"><span style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>目标院校</span><b style={{ fontSize: 'var(--text-xs)' }}>{settings.school || '未设置'}</b></div>
              <div className="spread"><span style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>专业</span><b style={{ fontSize: 'var(--text-xs)' }}>{settings.major || '未设置'}</b></div>
              <div className="spread"><span style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>目标分数</span><b style={{ fontSize: 'var(--text-xs)' }}>{settings.targetScore || '—'}</b></div>
              <div className="spread"><span style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>距考研</span><span className={`badge ${ctx.days == null ? 'neutral' : 'warning'}`}>{ctx.days == null ? '未设置' : `${ctx.days} 天`}</span></div>
              <div className="hr" />
              <div className="spread"><span style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>错题 / 单词 / 卡片</span><b style={{ fontSize: 'var(--text-xs)' }}>{notebook.length} / {words.length} / {cards.length}</b></div>
            </div>
          </div>
        </div>
      </div>

      {/* 引用原文 Modal */}
      <Modal
        open={!!refDetail}
        title={refDetail ? (refDetail.title || refDetail.source || '知识片段') : ''}
        onClose={() => setRefDetail(null)}
        footer={refDetail ? (
          <>
            <button className="btn ghost" onClick={() => setRefDetail(null)}>关闭</button>
            <button
              className="btn primary"
              onClick={() => {
                const seg = (refDetail.content || '').slice(0, 160)
                setInput(`结合这段资料继续讲解：\n「${seg}」\n请说明它在考试中怎么考、易错点是什么。`)
                setRefDetail(null)
                toast('已填入输入框，可直接发送追问')
              }}
            >追问这段</button>
          </>
        ) : null}
      >
        {refDetail && (
          <div className="stack" style={{ gap: 'var(--space-3)' }}>
            <div className="row" style={{ flexWrap: 'wrap', gap: 'var(--space-2)' }}>
              <span className="badge info">{refDetail.source || '知识分块'}</span>
              {refDetail.subject && <span className="badge">{refDetail.subject}</span>}
              {refDetail.score != null && <span className="badge success">相关度 {Number(refDetail.score).toFixed(2)}</span>}
              {refDetail.doc_id != null && <span className="badge">文档 #{refDetail.doc_id}</span>}
            </div>
            <div style={{ fontSize: 'var(--text-sm)', lineHeight: 1.9, color: 'var(--fg)', whiteSpace: 'pre-wrap', maxHeight: '46vh', overflowY: 'auto', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)' }}>
              {refDetail.content || '（该片段无正文内容）'}
            </div>
          </div>
        )}
      </Modal>

      {/* 摘要全文 Modal */}
      <Modal
        open={showSummary && !!summary}
        title="多轮上下文摘要"
        onClose={() => setShowSummary(false)}
        footer={
          <>
            <button className="btn ghost" onClick={() => { navigator.clipboard?.writeText(summary); toast('摘要已复制') }}>复制</button>
            <button className="btn primary" onClick={() => setShowSummary(false)}>知道了</button>
          </>
        }
      >
        <div style={{ fontSize: 'var(--text-sm)', lineHeight: 1.95, color: 'var(--fg)', whiteSpace: 'pre-wrap' }}>{summary}</div>
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', marginTop: 'var(--space-3)', marginBottom: 0 }}>
          启用后，向「自定义 API」引擎提问时会把这段摘要写入 system 提示，并只附带最近 2 轮原文。
        </p>
      </Modal>
    </div>
  )
}
