import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

/* 成长体系页：清库后（无任何学习事件）应当说明「积分从哪来」，
   而不是摆五张 +0 卡片冒充明细。这是空态即交付物的一环。 */
vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: {
    growthSummary: vi.fn(),
    growthBadges: vi.fn().mockResolvedValue({ badges: [] }),
    growthAchievements: vi.fn().mockResolvedValue({ achievements: [] }),
  },
}))

import { kaoyanApi } from '../api/kaoyanApi'
import GrowthPage from '../v3/pages/GrowthPage'

const FRESH = {
  level: { level: 1, name: '起步', points: 0, progress: 0, next: { name: '入门', threshold: 100 } },
  stats: { answer_total: 0, answer_correct: 0, submit_total: 0, review_total: 0, study_seconds: 0, active_days: 0 },
  points_detail: [
    { source: '答题答对', count: 0, unit: 10, points: 0 },
    { source: '答题答错', count: 0, unit: 3, points: 0 },
    { source: '交卷/模拟', count: 0, unit: 5, points: 0 },
    { source: '复习', count: 0, unit: 4, points: 0 },
    { source: '学习时长', count: 0, unit: '1/分钟', points: 0 },
  ],
  badge_count: 0,
  achievement_count: 0,
}

const ACTIVE = {
  ...FRESH,
  level: { level: 2, name: '入门', points: 160, progress: 20, next: { name: '进阶', threshold: 300 } },
  points_detail: FRESH.points_detail.map((d, i) => (i === 0 ? { ...d, count: 12, points: 120 } : d)),
}

beforeEach(() => {
  vi.clearAllMocks()
  kaoyanApi.growthBadges.mockResolvedValue({ badges: [] })
  kaoyanApi.growthAchievements.mockResolvedValue({ achievements: [] })
})

describe('成长体系空态', () => {
  it('全 0 明细时显示来源说明，不渲染 +0 卡片', async () => {
    kaoyanApi.growthSummary.mockResolvedValue(FRESH)
    render(<GrowthPage />)
    expect(await screen.findByText('还没有积分')).toBeInTheDocument()
    expect(screen.queryByText('+0')).not.toBeInTheDocument()
  })

  it('有积分后按来源渲染明细', async () => {
    kaoyanApi.growthSummary.mockResolvedValue(ACTIVE)
    render(<GrowthPage />)
    expect(await screen.findByText('+120')).toBeInTheDocument()
    expect(screen.queryByText('还没有积分')).not.toBeInTheDocument()
  })
})
