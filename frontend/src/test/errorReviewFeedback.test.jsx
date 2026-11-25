/**
 * C2 / QA-05：错题 AI 归因三态反馈契约。
 *
 * 关键不变量：未经确认的 AI 文本绝不覆盖人工 reason；标「错误」后 AI归因 tag 失效。
 */
import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, fireEvent } from '@testing-library/react'
import {
  resolveAttributionReason, shouldKeepAiTag, visibleErrorTags, AiFeedbackBar,
} from '../v3/pages/ErrorReview'

const source = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

describe('人工 reason 的唯一写入口径', () => {
  it('未确认时原样保留人工 reason，AI 文本不渗入', () => {
    const reason = resolveAttributionReason({
      aiText: 'AI 说这是概念混淆', feedback: null, humanReason: '我自己的错因',
    })
    expect(reason).toBe('我自己的错因')
    expect(reason).not.toMatch(/AI 说/)
  })

  it('准确 / 部分准确 带确认前缀写入', () => {
    expect(resolveAttributionReason({
      aiText: '概念混淆', feedback: 'accurate', humanReason: '旧错因',
    })).toMatch(/已确认准确.*概念混淆/)
    expect(resolveAttributionReason({
      aiText: '概念混淆', feedback: 'partial', humanReason: '旧错因',
    })).toMatch(/部分采纳.*概念混淆/)
  })

  it('标错误后只有人工改写文本才写入；未改写仍保留人工 reason', () => {
    expect(resolveAttributionReason({
      aiText: 'AI 原文', feedback: 'wrong', rewriteText: '正确错因是计算失误', humanReason: '旧错因',
    })).toBe('人工改写：正确错因是计算失误')
    expect(resolveAttributionReason({
      aiText: 'AI 原文', feedback: 'wrong', rewriteText: '', humanReason: '旧错因',
    })).toBe('旧错因')
  })
})

describe('AI归因 tag 失效', () => {
  it('只有准确 / 部分准确保留 AI归因背书', () => {
    expect(shouldKeepAiTag('accurate')).toBe(true)
    expect(shouldKeepAiTag('partial')).toBe(true)
    expect(shouldKeepAiTag('wrong')).toBe(false)
    expect(shouldKeepAiTag(null)).toBe(false)
  })

  it('标错误后列表中不再出现 AI归因 tag，其它 tag 保留', () => {
    const tags = ['薄弱', 'AI归因']
    expect(visibleErrorTags(tags, 'wrong')).toEqual(['薄弱'])
    expect(visibleErrorTags(tags, 'accurate')).toEqual(['薄弱', 'AI归因'])
    expect(visibleErrorTags(tags, null)).toEqual(['薄弱', 'AI归因'])
  })
})

describe('三态反馈按钮', () => {
  it('按钮数恒为 3，文案与验收一致', () => {
    render(<AiFeedbackBar value={null} onChange={() => {}} />)
    const group = screen.getByRole('group', { name: 'AI 归因反馈' })
    const buttons = Array.from(group.querySelectorAll('button'))
    expect(buttons).toHaveLength(3)
    expect(buttons.map((b) => b.textContent.trim())).toEqual(['准确', '部分准确', '错误 + 一键改写'])
  })

  it('点击每个按钮回调对应 kind，选中态通过 aria-pressed 暴露', () => {
    const onChange = vi.fn()
    const { rerender } = render(<AiFeedbackBar value={null} onChange={onChange} />)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[0])
    fireEvent.click(buttons[1])
    fireEvent.click(buttons[2])
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(['accurate', 'partial', 'wrong'])

    rerender(<AiFeedbackBar value="wrong" onChange={onChange} />)
    expect(screen.getAllByRole('button').map((b) => b.getAttribute('aria-pressed')))
      .toEqual(['false', 'false', 'true'])
  })
})

describe('评估记录持久化与接入', () => {
  it('评估记录按 uid 键写入 localStorage', () => {
    const code = source('src/v3/pages/ErrorReview.jsx')
    expect(code).toMatch(/localStorage\.setItem\(ukey\(AI_FEEDBACK_KEY\)/)
    expect(code).toMatch(/errorsApi\.aiAnalyze\(selectedId\)/)
  })

  it('置信度徽标与共享证据卡都已接入 AI 归因区', () => {
    const code = source('src/v3/pages/ErrorReview.jsx')
    expect(code).toMatch(/<ConfidenceBadge confidence=\{ai\.confidence\} \/>/)
    expect(code).toMatch(/<AiFeedbackBar/)
    expect(code).toMatch(/<AiEvidenceCard/)
  })
})
