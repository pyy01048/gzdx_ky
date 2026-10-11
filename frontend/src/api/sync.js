/* ============================================================
   考研档案 · 数据同步层（P0-1）
   后端优先：应用挂载时从 FastAPI 拉取真实数据回填 zustand store，
   覆盖 localStorage 中的 SEED/历史数据；后端不可用则静默保留本地。
   写操作的后端同步已内联在 useStore.js 各 action 中（fire-and-forget）。
   ============================================================ */

import { tasksApi, errorsApi, flashcardsApi, netdiskApi, goalsApi, aiApi } from './client'
import useStore from '../store/useStore'
import { todayStr } from '../utils/date'

/* 后端字段 → 前端 store 字段映射 */
function toTask(t) {
  return {
    id: String(t.id),
    title: t.title,
    subject: t.subject || 'major',
    due: (t.due_date || todayStr()).slice(0, 10),
    done: t.status === 'done' || t.status === 'completed',
    ai: !!t.is_ai,
    reviewCount: t.review_count || 0
  }
}

function toNote(n) {
  return {
    id: String(n.id),
    subject: n.subject || 'other',
    question: n.content || n.question || '',
    answer: n.correct_answer || n.answer || '',
    analysis: n.analysis || '',
    reason: n.error_reason || '',
    mastery: Math.min(Math.max(Number(n.accuracy) >= 0.8 ? 5 : Number(n.review_count || 0) % 7, 0), 7),
    tags: n.tags || [],
    createdAt: (n.created_at || todayStr()).slice(0, 10),
    lastReview: n.last_review ? n.last_review.slice(0, 10) : null,
    reviews: []
  }
}

function toCard(c) {
  const masteryMap = { new: 'new', learning: 'new', mastered: 'mastered', review: 'learning' }
  return {
    id: String(c.id),
    front: c.front,
    back: c.back,
    hint: '',
    // 后端卡片无卡组概念，统一归入“全部卡组”
    packId: 'all',
    status: masteryMap[c.mastery] || 'new',
    ef: c.ease_factor || 2.5,
    interval: c.interval || 0,
    reps: c.review_count || 0,
    lapses: 0,
    due: c.next_review ? c.next_review.slice(0, 10) : todayStr(),
    lastReview: null
  }
}

function toPan(f) {
  const typeMap = { pdf: 'pdf', video: 'video', doc: 'doc', zip: 'zip' }
  return {
    id: String(f.id),
    name: f.file_name,
    type: typeMap[f.file_type] || 'other',
    size: f.size || 0,
    cat: f.category || '专业课',
    desc: f.path || '',
    url: f.download_link || '',
    synced: true,
    date: (f.created_at || todayStr()).slice(0, 10),
    remote: true,
    fsId: f.fs_id
  }
}

function toProvider(p) {
  return {
    id: String(p.id),
    key: p.provider_type || 'custom',
    name: p.name,
    baseUrl: p.base_url || '',
    model: p.model_name || '',
    apiKey: p.api_key || '',
    enabled: p.is_enabled !== false,
    default: !!p.is_default,
    vision: false,
    proxy: '',
    test: null
  }
}

/* 各数据域拉取与回填（后端可用即覆盖本地 SEED，不可用静默跳过） */
const LOADERS = {
  tasks: async () => {
    const d = await tasksApi.list({ page: 1, page_size: 500 })
    const list = d.items || d.tasks || (Array.isArray(d) ? d : [])
    if (Array.isArray(list) && list.length) useStore.setState({ tasks: list.map(toTask) })
  },
  notebook: async () => {
    const d = await errorsApi.list({ page: 1, page_size: 500 })
    const list = d.errors || d.items || (Array.isArray(d) ? d : [])
    if (Array.isArray(list) && list.length) useStore.setState({ notebook: list.map(toNote) })
  },
  cards: async () => {
    const d = await flashcardsApi.list({ page: 1, page_size: 500 })
    const list = d.cards || d.items || (Array.isArray(d) ? d : [])
    if (Array.isArray(list) && list.length) useStore.setState({ cards: list.map(toCard) })
  },
  pan: async () => {
    const d = await netdiskApi.files({ page: 1, page_size: 200 })
    const list = d.local_files || d.items || (Array.isArray(d) ? d : [])
    if (Array.isArray(list) && list.length) useStore.setState({ pan: list.map(toPan) })
  },
  settings: async () => {
    const g = await goalsApi.list()
    const goal = Array.isArray(g) ? (g[0] || null) : (g || null)
    if (goal) {
      const patch = {}
      if (goal.university) patch.school = goal.university
      if (goal.major) patch.major = goal.major
      if (goal.exam_date) patch.examDate = String(goal.exam_date).slice(0, 10)
      if (goal.total_score_target != null) patch.targetScore = goal.total_score_target
      useStore.setState((s) => ({ settings: { ...s.settings, ...patch } }))
    }
  },
  aiProviders: async () => {
    const d = await aiApi.providers()
    const list = d.providers || d.items || (Array.isArray(d) ? d : [])
    if (Array.isArray(list) && list.length) {
      useStore.setState((s) => ({ settings: { ...s.settings, aiProviders: list.map(toProvider) } }))
    }
  }
}

/**
 * 从后端全量拉取各数据域并回填 store。
 * 仅做“后端优先”，任何单域失败不影响其它域；全部失败则保持本地兜底。
 */
export async function hydrate() {
  const results = await Promise.allSettled(Object.values(LOADERS).map((fn) => fn()))
  const ok = results.filter((r) => r.status === 'fulfilled').length
  useStore.setState({ backendOnline: ok > 0 })
  return { online: ok > 0, total: results.length, ok }
}
