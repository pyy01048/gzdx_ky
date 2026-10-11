/**
 * 核心类型定义 V3.0
 * 供 TypeScript 迁移使用
 */

// 通用分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// 任务
export interface Task {
  id: string | number
  title: string
  subject?: string
  due_date?: string
  due?: string
  priority?: number
  status?: 'pending' | 'doing' | 'done'
  done?: boolean
  ai?: boolean
  created_at?: string
  createdAt?: string
}

// 单词
export interface Word {
  id: string | number
  word: string
  meaning?: string
  phonetic?: string
  example?: string
  deck?: string
  deck_id?: string | number
  status: 'new' | 'learning' | 'reviewing' | 'mastered'
  ease_factor?: number
  ef?: number
  interval?: number
  reps?: number
  lapses?: number
  due_date?: string
  due?: string
  last_review?: string
  lastReview?: string
  history?: Array<{ date: string; grade: number }>
}

// 词库
export interface WordDeck {
  id: string | number
  name: string
  count?: number
  source?: string
  description?: string
}

// 记忆卡片
export interface Flashcard {
  id: string | number
  front: string
  back: string
  packId?: string | number
  pack_id?: string | number
  status: 'new' | 'learning' | 'reviewing' | 'mastered'
  ease_factor?: number
  ef?: number
  interval?: number
  reps?: number
  lapses?: number
  due_date?: string
  due?: string
  last_review?: string
}

// 卡包
export interface CardPack {
  id: string | number
  name: string
  subject?: string
  color?: number
  count?: number
}

// 错题记录
export interface ErrorRecord {
  id: string | number
  subject: string
  question?: string
  content?: string
  answer?: string
  correct_answer?: string
  analysis?: string
  reason?: string
  error_reason?: string
  mastery?: number
  accuracy?: number
  tags?: string[]
  status?: 'active' | 'graduated'
  created_at?: string
  createdAt?: string
  last_review?: string
  lastReview?: string
  reviews?: Array<{ date: string; correct: boolean }>
}

// 题目
export interface QuizQuestion {
  id: string | number
  type: 'single' | 'multiple' | 'judge' | 'fill' | 'essay'
  question: string
  options?: string[]
  answer: string
  analysis?: string
  subject?: string
  difficulty?: 'easy' | 'medium' | 'hard'
  tags?: string[]
}

// 文档
export interface Document {
  id: string | number
  title: string
  file_name?: string
  file_type?: string
  file_size?: number
  subject?: string
  source?: string
  status?: 'pending' | 'parsing' | 'ready' | 'failed'
  index_status?: string
  content?: string
  parse_progress?: number
  uploaded_at?: string
  parsed_at?: string
}

// 学习会话
export interface StudySession {
  id: string | number
  date: string
  duration: number
  subject?: string
  task_type?: string
  remark?: string
  created_at?: string
}

// Dashboard统计
export interface DashboardStats {
  total_study_minutes: number
  today_minutes: number
  week_minutes: number
  by_subject: Record<string, number>
  seven_day_trend: Array<{ date: string; minutes: number }>
  tasks_completed_this_week: number
}

// AI服务商
export interface AIProvider {
  id: string
  key?: string
  name: string
  baseUrl: string
  model: string
  apiKey?: string
  enabled: boolean
  default?: boolean
  vision?: boolean
  proxy?: string
  test?: 'success' | 'fail' | null
}

// 聊天消息
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: string
  references?: Array<{ document: string; chunk: string }>
}

// 网盘文件
export interface NetdiskFile {
  id: string | number
  name: string
  file_name?: string
  type?: string
  size?: number
  category?: string
  cat?: string
  description?: string
  desc?: string
  url?: string
  synced?: boolean
  date?: string
  fs_id?: string
  path?: string
  local_path?: string
}

// 自定义链接
export interface CustomLink {
  id: string | number
  name: string
  url: string
  icon?: string
  category?: string
  order?: number
}

// 学期
export interface Semester {
  id: string | number
  name: string
  start_date: string
  end_date: string
  current_week?: number
}

// 课程
export interface Course {
  id: string | number
  title: string
  day: number
  slot: number
  color?: number
  location?: string
  teacher?: string
  weeks?: number[]
}

// 同步状态
export type SyncStatus = 'idle' | 'syncing' | 'synced' | 'error'

// 设置
export interface AppSettings {
  school?: string
  major?: string
  examDate: string
  targetScore: number
  dailyTarget?: number
  theme: 'light' | 'dark'
  aiName?: string
  aiProviders?: AIProvider[]
  aiUsage?: {
    calls: number
    promptTokens: number
    completionTokens: number
    lastTest?: string | null
  }
}
