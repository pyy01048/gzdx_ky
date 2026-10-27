/**
 * Store 初始值
 *
 * 这里只放「配置默认值」，任何用户数据域一律从空开始。
 * 曾经预置过三批假数据：7 条假任务 / 6 条假错题 / 7 个假网盘文件；
 * 以及「随应用分发的内置内容」——CORE_WORDS 20 个英语词 + 2 个词库骨架。
 * 后者同样必须清空：词表进 store 后，仪表盘「待复习单词」按 due 算出 20 条
 * （Dashboard.jsx dueCards(words)），全新用户被提示去复习自己从未背过的词，
 * 而 api/sync.js 没有 words 域，这份假数据不会被后端覆盖。
 * 内置词表仍然随应用分发，但必须由用户在单词页显式「导入」才落库
 * （走 wordsApi.importText 真实导入链路，会生成真实的创建时间与调度状态）。
 */
export const SEED = {
  settings: {
    school: '',
    major: '',
    examDate: null,
    targetScore: null,
    dailyTarget: 4,
    theme: 'light',
    aiName: '研友·小档',
    aiProviders: [
      { id: 'p_default_deepseek', key: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat', apiKey: '', enabled: true, default: true, vision: false, proxy: '', test: null }
    ],
    aiUsage: { calls: 0, promptTokens: 0, completionTokens: 0, lastTest: null }
  },
  tasks: [],
  notebook: [],
  pan: [],
  ai: {
    persona: '考研档案',
    messages: []
  },
  words: [],
  decks: [],
  cards: [],
  packs: []
}
