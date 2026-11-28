import React, { useState } from 'react'
import { Button, Textarea, cx, toast, toastOk, toastErr } from './index'

/**
 * C-FEEDBACK-API@1：AI 答疑回答反馈三键组件。
 *
 * 三键：有用（helpful）/ 无用（unhelpful）/ 纠错（correction，展开文本框）。
 * - 重复反馈（同 answer_id + user_id）后端返回 409，前端按已反馈处理（幂等）。
 * - 未登录返回 401，提示登录。
 * - feedback_type 不合法返回 422，提示内容不合法。
 * answer_id 为前端生成的 UUID/时间戳字符串，不依赖 answers 表存在。
 */
const FEEDBACK_TYPES = ['helpful', 'unhelpful', 'correction']
const FEEDBACK_LABELS = { helpful: '有用', unhelpful: '无用', correction: '纠错' }

export default function AnswerFeedbackBar({ answerId, className = '' }) {
  const [submitted, setSubmitted] = useState(null)
  const [pending, setPending] = useState(false)
  const [showCorrection, setShowCorrection] = useState(false)
  const [correctionText, setCorrectionText] = useState('')

  if (!answerId) return null

  const submit = async (feedbackType, text = null) => {
    if (pending || submitted) return
    // 纠错首次点击仅展开文本框，不立即提交
    if (feedbackType === 'correction' && !showCorrection) {
      setShowCorrection(true)
      return
    }
    if (feedbackType === 'correction' && !String(text || '').trim()) {
      toast('请填写纠正内容后再提交')
      return
    }
    setPending(true)
    try {
      const res = await fetch(`/api/ai/answers/${encodeURIComponent(answerId)}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          feedback_type: feedbackType,
          correction_text: feedbackType === 'correction' ? text : null,
        }),
      })
      if (res.status === 401) {
        toastErr('请先登录后再反馈')
        return
      }
      if (res.status === 409) {
        setSubmitted(feedbackType)
        setShowCorrection(false)
        toast('该回答你已反馈过')
        return
      }
      if (res.status === 422) {
        toastErr('反馈内容不合法')
        return
      }
      if (!res.ok) {
        toastErr(`反馈提交失败（${res.status}）`)
        return
      }
      setSubmitted(feedbackType)
      setShowCorrection(false)
      toastOk(`已记录反馈：${FEEDBACK_LABELS[feedbackType]}`)
    } catch (e) {
      toastErr(`反馈提交失败：${e?.message || '网络异常'}`)
    } finally {
      setPending(false)
    }
  }

  return (
    <div
      className={cx('v3-asst-feedback', className)}
      data-answer-feedback="1"
      style={{
        margin: '8px 18px 12px',
        padding: 0,
        fontSize: 'var(--v3-fs-12, 12px)',
        color: 'var(--v3-text-2, #4b5563)',
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
        <span style={{ marginRight: 4 }}>这条回答对你有帮助吗？</span>
        <div style={{ display: 'inline-flex', gap: 6 }}>
          {FEEDBACK_TYPES.map((t) => (
            <Button
              key={t}
              variant={submitted === t ? 'filled' : 'tonal'}
              size="sm"
              disabled={pending || (!!submitted && submitted !== t)}
              onClick={() => submit(t, correctionText)}
            >
              {FEEDBACK_LABELS[t]}
            </Button>
          ))}
        </div>
      </div>
      {showCorrection && !submitted ? (
        <div style={{ marginTop: 8 }}>
          <Textarea
            rows={3}
            aria-label="纠正内容"
            placeholder="请描述这条回答哪里有误、缺什么或可改进的地方（必填）"
            value={correctionText}
            onChange={(e) => setCorrectionText(e.target.value)}
            maxLength={1000}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 6 }}>
            <Button
              variant="text"
              size="sm"
              disabled={pending}
              onClick={() => { setShowCorrection(false); setCorrectionText('') }}
            >
              取消
            </Button>
            <Button
              variant="gradient"
              size="sm"
              disabled={pending || !correctionText.trim()}
              onClick={() => submit('correction', correctionText)}
            >
              {pending ? '提交中…' : '提交纠错'}
            </Button>
          </div>
        </div>
      ) : null}
      {submitted ? (
        <span style={{ display: 'inline-block', marginTop: 6, color: 'var(--v3-success, #16a34a)' }}>
          已反馈：{FEEDBACK_LABELS[submitted]}，感谢你的反馈
        </span>
      ) : null}
    </div>
  )
}
