import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

import {
  useSubjectConfig,
  refreshSubjectConfig,
  subjectLabel,
} from '../hooks/useSubjectConfig'
import Analysis from '../pages/Analysis'

/* ------------------------------------------------------------------ *
 * 科目配置单一来源（hooks/useSubjectConfig）
 *
 * Analysis / Pan / Planner 的科目下拉、分类页签与进度分母原本各写死一份，
 * 现在统一由 GET /api/goals/subjects 驱动。这里锁住两条底线：
 *   ① 后端不可达时必须退回静态口径 —— 否则页面变成「没有科目」；
 *   ② 后端返回残缺体时不能覆盖已生效口径 —— 否则一次 500 就把列表清空。
 * ------------------------------------------------------------------ */

const apiMocks = vi.hoisted(() => ({
  goalsSubjects: vi.fn(),
  analysisLectures: vi.fn(),
}))

vi.mock('../api/client', () => ({
  goalsApi: { subjects: apiMocks.goalsSubjects },
  analysisApi: { lectures: apiMocks.analysisLectures },
}))

const CONFIG = {
  exam_subjects: ['数学', '英语', '数据结构'],
  support_subjects: ['操作系统', '白名单外的脏值'],
  all_known: ['数学', '英语', '数据结构', '操作系统'],
  using_default: false,
}

function Probe() {
  const cfg = useSubjectConfig()
  return (
    <div data-testid="probe">
      {JSON.stringify({ exam: cfg.exam, support: cfg.support, active: cfg.active, ready: cfg.ready })}
    </div>
  )
}

async function readProbe() {
  const el = await screen.findByTestId('probe')
  return JSON.parse(el.textContent)
}

describe('subjectLabel', () => {
  it('长科目名转简称，未知科目原样返回', () => {
    expect(subjectLabel('数字电子技术')).toBe('数电')
    expect(subjectLabel('模拟电子技术')).toBe('模电')
    expect(subjectLabel('计算机学科专业基础408')).toBe('408')
    expect(subjectLabel('真题综合')).toBe('真题')
    expect(subjectLabel('数据结构')).toBe('数据结构')
  })
})

describe('useSubjectConfig', () => {
  beforeEach(() => {
    cleanup()
    apiMocks.goalsSubjects.mockReset()
    apiMocks.analysisLectures.mockReset().mockResolvedValue({ items: [] })
  })

  it('接口挂掉时退回静态口径，且 ready=false', async () => {
    apiMocks.goalsSubjects.mockRejectedValue(new Error('backend down'))
    await refreshSubjectConfig(true)
    render(<Probe />)
    const cfg = await readProbe()
    expect(cfg.ready).toBe(false)
    expect(cfg.exam.length).toBeGreaterThan(0)
    expect(cfg.exam).toContain('数学')
  })

  it('接口正常时以配置为准，并过滤掉 taxonomy 不认识的支撑科目', async () => {
    apiMocks.goalsSubjects.mockResolvedValue(CONFIG)
    await refreshSubjectConfig(true)
    render(<Probe />)
    const cfg = await readProbe()
    expect(cfg.ready).toBe(true)
    expect(cfg.exam).toEqual(['数学', '英语', '数据结构'])
    expect(cfg.support).toEqual(['操作系统'])
    expect(cfg.active).toEqual(['数学', '英语', '数据结构', '操作系统'])
  })

  it('残缺体（exam 为空）不覆盖已生效口径', async () => {
    apiMocks.goalsSubjects.mockResolvedValue(CONFIG)
    await refreshSubjectConfig(true)
    apiMocks.goalsSubjects.mockResolvedValue({ exam_subjects: [], support_subjects: [] })
    await refreshSubjectConfig(true)
    render(<Probe />)
    const cfg = await readProbe()
    expect(cfg.exam).toEqual(['数学', '英语', '数据结构'])
  })
})

describe('Analysis 页科目选项跟随配置', () => {
  it('分段器渲染配置里的考试科目，而不是页面写死的旧列表', async () => {
    apiMocks.goalsSubjects.mockResolvedValue(CONFIG)
    await refreshSubjectConfig(true)
    render(<Analysis />)
    expect(await screen.findByText('数据结构')).toBeInTheDocument()
    expect(screen.getByLabelText('支撑科目')).toBeInTheDocument()
    // 写死时代的产物不应再出现
    expect(screen.queryByText('数电')).not.toBeInTheDocument()
  })
})
