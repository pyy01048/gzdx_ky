/**
 * Store 初始值
 *
 * 这里只放「配置默认值」和「随应用分发的内置内容」（核心词表/词库骨架）。
 * 用户数据（任务、错题、网盘、卡片）一律从空开始，由 api/sync.js 从后端回填——
 * 曾经这里预置过 7 条假任务/6 条假错题/7 个假网盘文件，它们会伪装成真实学习记录
 * 进入仪表盘、统计和 AI 上下文，属于必须清除的假数据。
 */
import { today as spacedToday } from '../utils/spaced'
import { CORE_WORDS, SEED_PACKS } from '../utils/words'

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
    { id: 'core', name: '考研核心词', count: CORE_WORDS.length, source: '内置' }
  ],
  cards: [],
  packs: SEED_PACKS.map((p) => ({ ...p, count: 0 }))
}
