/**
 * 预置示例数据（Mock数据）
 * 围绕「贵州大学 电子信息 0854」考研场景
 * 仅在开发/演示或无后端数据时使用
 */
import { todayStr, addDays } from '../utils/date'
import { sm2Schedule, today as spacedToday } from '../utils/spaced'
import { CORE_WORDS, SEED_PACKS } from '../utils/words'

export const SEED = {
  settings: {
    school: '贵州大学',
    major: '电子信息（0854）',
    examDate: '2027-12-25',
    targetScore: 360,
    dailyTarget: 4,
    theme: 'light',
    aiName: '研友·小档',
    initialized: true,
    aiProviders: [
      { id: 'p_default_deepseek', key: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat', apiKey: '', enabled: true, default: true, vision: false, proxy: '', test: null }
    ],
    aiUsage: { calls: 0, promptTokens: 0, completionTokens: 0, lastTest: null }
  },
  tasks: [
    { id: 't1', title: '数学强化：汤家凤 1800 概率章节', subject: 'math', due: todayStr(), done: false, ai: false, createdAt: addDays(todayStr(), -3) },
    { id: 't2', title: '英语真题 2018 Text3 精读', subject: 'english', due: todayStr(), done: false, ai: false, createdAt: addDays(todayStr(), -2) },
    { id: 't3', title: '政治：马原第二章框架梳理', subject: 'politics', due: todayStr(), done: true, ai: false, createdAt: addDays(todayStr(), -2) },
    { id: 't4', title: '834 数电：逻辑代数章节刷题 30 道', subject: 'major', due: todayStr(), done: false, ai: false, createdAt: addDays(todayStr(), -1) },
    { id: 't5', title: '英语单词 100 个（恋恋有词 Unit 12）', subject: 'english', due: addDays(todayStr(), 1), done: false, ai: true, createdAt: todayStr() },
    { id: 't6', title: '数学错题本整理 + 重做', subject: 'math', due: addDays(todayStr(), 1), done: false, ai: false, createdAt: todayStr() },
    { id: 't7', title: '834 模电：放大电路章节回顾', subject: 'major', due: addDays(todayStr(), 2), done: false, ai: false, createdAt: todayStr() }
  ],
  notebook: [
    {
      id: 'n1', subject: 'math',
      question: '求极限 lim(x→0) (1-cosx)/x²',
      answer: '等价无穷小：1-cosx ~ x²/2，故极限 = 1/2',
      analysis: '考察等价无穷小替换，注意 1-cosx ~ x²/2 而不是 x²。',
      reason: '与 1-cosx ~ x 混淆，忘记平方项',
      mastery: 3, tags: ['极限', '无穷小'], createdAt: addDays(todayStr(), -12), lastReview: addDays(todayStr(), -5), reviews: []
    },
    {
      id: 'n2', subject: 'english',
      question: 'virtual 在"virtual reality"与"virtual all"中的含义差异',
      answer: '前者=虚拟的；后者=几乎、事实上（virtually all = 几乎所有）',
      analysis: '一词多义，考研高频。注意词性引申：virtual(几乎的) 与 virtual(虚拟的)。',
      reason: '只记住了"虚拟的"一个义项',
      mastery: 4, tags: ['一词多义', '词汇'], createdAt: addDays(todayStr(), -8), lastReview: addDays(todayStr(), -1), reviews: []
    },
    {
      id: 'n3', subject: 'politics',
      question: '矛盾的基本属性及其关系',
      answer: '斗争性（绝对）与同一性（相对）相互联结、不可分割，构成事物的矛盾运动。',
      analysis: '高频辨析点：同一性是有条件的、相对的；斗争性是无条件的、绝对的。',
      reason: '把"同一性相对、斗争性绝对"记反了',
      mastery: 2, tags: ['马原', '辩证法'], createdAt: addDays(todayStr(), -15), lastReview: addDays(todayStr(), -3), reviews: []
    },
    {
      id: 'n4', subject: 'major',
      question: 'TCP 三次握手为什么不是两次？',
      answer: '防止已失效的连接请求报文段突然又传到服务端，造成资源浪费与错误连接。',
      analysis: '核心是"失效报文段"问题：两次握手可能让服务端误开连接。',
      reason: '只背结论不理解原因',
      mastery: 5, tags: ['网络', 'TCP'], createdAt: addDays(todayStr(), -20), lastReview: addDays(todayStr(), -8), reviews: []
    },
    {
      id: 'n5', subject: 'math',
      question: '二阶常系数线性齐次方程特征根为重根时的通解形式',
      answer: 'y = (C1 + C2·x)·e^(rx)，注意出现 x 因子。',
      analysis: '重根情形通解需乘以 x，与单根情形对比记忆。',
      reason: '通解漏乘 x 因子',
      mastery: 6, tags: ['微分方程'], createdAt: addDays(todayStr(), -30), lastReview: addDays(todayStr(), -10), reviews: []
    },
    {
      id: 'n6', subject: 'major',
      question: '哈希冲突的开放定址法如何处理删除？',
      answer: '采用"标记删除"（惰性删除）而非物理删除，否则会破坏探测链。',
      analysis: '开放定址法删除元素必须打标记，否则查找会提前终止。',
      reason: '误以为可直接删除节点',
      mastery: 1, tags: ['数据结构', '哈希'], createdAt: addDays(todayStr(), -2), lastReview: null, reviews: []
    }
  ],
  pan: [
    { id: 'p1', name: '834 数据结构 历年真题 2018-2026.pdf', type: 'pdf', size: 28400, cat: '真题', desc: '贵州大学 834 数据结构真题合集，含解析。', url: '', synced: true, date: addDays(todayStr(), -30) },
    { id: 'p2', name: '汤家凤 1800 概率部分笔记.pdf', type: 'pdf', size: 15400, cat: '数学', desc: '高数强化阶段手写笔记扫描版。', url: '', synced: true, date: addDays(todayStr(), -20) },
    { id: 'p3', name: '恋恋有词 Unit10-15 精讲.mp4', type: 'video', size: 512000, cat: '英语', desc: '词汇精讲视频，建议 1.5 倍速。', url: '', synced: false, date: addDays(todayStr(), -12) },
    { id: 'p4', name: '马原思维导图 全章节.pdf', type: 'pdf', size: 8600, cat: '政治', desc: '马原全章节思维导图，冲刺阶段背诵用。', url: '', synced: true, date: addDays(todayStr(), -8) },
    { id: 'p5', name: '计算机网络 考点总结.docx', type: 'doc', size: 3200, cat: '专业课', desc: '834 计算机网络考点总结，含常考计算题模板。', url: '', synced: false, date: addDays(todayStr(), -5) },
    { id: 'p6', name: '英语作文模板 大作文.zip', type: 'zip', size: 12800, cat: '英语', desc: '大小作文模板与替换句，含 PDF 与 Word 版。', url: '', synced: true, date: addDays(todayStr(), -3) },
    { id: 'p7', name: '数学冲刺 660 题精选题库.pdf', type: 'pdf', size: 19000, cat: '数学', desc: '冲刺阶段重点题型筛选。', url: '', synced: false, date: todayStr() }
  ],
  ai: {
    persona: '考研档案',
    messages: []
  },
  words: CORE_WORDS.map((w, i) => ({
    id: 'w' + (i + 1),
    ...w,
    deck: 'core',
    status: 'new',
    ef: 2.5,
    interval: 0,
    reps: 0,
    lapses: 0,
    due: spacedToday(),
    lastReview: null,
    history: []
  })),
  decks: [
    { id: 'core', name: '考研核心词', count: CORE_WORDS.length, source: '预置' }
  ],
  cards: [],
  packs: SEED_PACKS.map((p) => ({ ...p, count: 0 }))
}
