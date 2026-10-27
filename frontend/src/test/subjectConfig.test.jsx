import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { subjectLabel } from '../hooks/useSubjectConfig'

/* ------------------------------------------------------------------ *
 * 科目配置单一来源（hooks/useSubjectConfig）
 *
 * Analysis / Pan / Planner 的科目下拉、分类页签与进度分母原本各写死一份，
 * 现在统一由 GET /api/goals/subjects 驱动。这里锁住三条底线：
 *   ① 拿不到配置时**不编造科目**（页面呈现"未配置/读取中"，而不是别人的科目）；
 *   ② 真正的残缺响应（连字段都没有）不能把已生效口径清空；
 *   ③ "字段存在且为空数组"是合法答复：用户就是还没配科目。
 *
 * 隔离说明：snapshot 是模块级单例，用 vi.resetModules() + 动态 import 让每个用例
 * 拿到一份干净的 hook 状态，否则前一个用例的成功响应会漂到下一个用例里。
 * ------------------------------------------------------------------ */

const apiMocks = vi.hoisted(() => ({
  goalsSubjects: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => ({
  // 派生真实模块的导出清单：client.js 新增导出（如 fetchAllPages）不必再回来补枚举，
  // 否则页面一 import 就报 "No export is defined on the mock"。
  ...(await importOriginal()),
  favoritesApi: {
    list: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    add: vi.fn().mockResolvedValue({ ok: true, id: 1 }),
    check: vi.fn().mockResolvedValue({ favorited: false, id: null }),
    toggle: vi.fn().mockResolvedValue({ favorited: false }),
    remove: vi.fn().mockResolvedValue({ ok: true }),
  },
  growthApi: { timeline: vi.fn().mockResolvedValue({ days: 30, streak_days: 0, active_days: 0, timeline: [], subject_breakdown: [] }) },
  goalsApi: { subjects: apiMocks.goalsSubjects },
}))

const CONFIG = {
  exam_subjects: ['数学', '英语', '数据结构'],
  support_subjects: ['操作系统', '白名单外的脏值'],
  all_known: ['数学', '英语', '数据结构', '操作系统'],
  using_default: false,
}

/* 未配置：后端此时返回空数组 + using_default=true，并把内置目录放在 core_defaults 里备用 */
const UNCONFIGURED = {
  exam_subjects: [],
  support_subjects: [],
  active_subjects: [],
  all_known: ['数学', '英语', '数字电子技术'],
  core_defaults: ['数字电子技术', '模拟电子技术', '数学', '英语', '政治', '真题综合'],
  using_default: true,
}

async function freshHook() {
  vi.resetModules()
  return import('../hooks/useSubjectConfig')
}

function makeProbe(mod) {
  return function Probe() {
    const cfg = mod.useSubjectConfig()
    return (
      <div data-testid="probe">
        {JSON.stringify({ exam: cfg.exam, support: cfg.support, active: cfg.active, ready: cfg.ready, usingDefault: cfg.usingDefault })}
      </div>
    )
  }
}

async function readProbe() {
  const el = await screen.findByTestId('probe')
  return JSON.parse(el.textContent)
}

describe('subjectLabel', () => {
  /* 简称表是纯函数，静态 import 即可（不依赖模块级 snapshot） */
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
    localStorage.clear()
  })

  it('接口挂掉时不编造科目：exam 为空且 ready=false', async () => {
    const mod = await freshHook()
    apiMocks.goalsSubjects.mockRejectedValue(new Error('backend down'))
    await mod.refreshSubjectConfig(true)
    const Probe = makeProbe(mod)
    render(<Probe />)
    const cfg = await readProbe()
    expect(cfg.ready).toBe(false)
    expect(cfg.exam).toEqual([])
    expect(cfg.active).toEqual([])
  })

  it('接口正常时以配置为准，并过滤掉 taxonomy 不认识的支撑科目', async () => {
    const mod = await freshHook()
    apiMocks.goalsSubjects.mockResolvedValue(CONFIG)
    await mod.refreshSubjectConfig(true)
    const Probe = makeProbe(mod)
    render(<Probe />)
    const cfg = await readProbe()
    expect(cfg.ready).toBe(true)
    expect(cfg.exam).toEqual(['数学', '英语', '数据结构'])
    expect(cfg.support).toEqual(['操作系统'])
    expect(cfg.active).toEqual(['数学', '英语', '数据结构', '操作系统'])
  })

  it('已连通但未配置：ready=true、科目为空（不是内置默认那一套）', async () => {
    const mod = await freshHook()
    apiMocks.goalsSubjects.mockResolvedValue(UNCONFIGURED)
    await mod.refreshSubjectConfig(true)
    const Probe = makeProbe(mod)
    render(<Probe />)
    const cfg = await readProbe()
    expect(cfg.ready).toBe(true)
    expect(cfg.usingDefault).toBe(true)
    expect(cfg.exam).toEqual([])
    // 曾经这里会看到 数电/模电 —— 那是内置目录，不是这位用户的科目
    expect(cfg.active).not.toContain('数字电子技术')
  })

  it('残缺响应（两个字段都不存在）不覆盖已生效口径', async () => {
    const mod = await freshHook()
    apiMocks.goalsSubjects.mockResolvedValue(CONFIG)
    await mod.refreshSubjectConfig(true)
    apiMocks.goalsSubjects.mockResolvedValue({ message: 'ok' })
    await mod.refreshSubjectConfig(true)
    const Probe = makeProbe(mod)
    render(<Probe />)
    const cfg = await readProbe()
    expect(cfg.exam).toEqual(['数学', '英语', '数据结构'])
  })
})

