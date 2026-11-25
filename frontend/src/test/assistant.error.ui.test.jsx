import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, fireEvent, waitFor, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import useStore from '../store/useStore'
import { readAiAnswer } from '../utils/aiAnswerArchive'

/* ------------------------------------------------------------------ *
 * P0-5 回归（界面层）：AI 助手失败时必须「看得见」
 *
 * 线上现象：点快捷问题后界面既不出回答也不出错误提示，用户只能以为卡住了。
 * 本测试分别注入三种失败，断言界面**真的**出现错误气泡 + 「重试」按钮：
 *   ① SSE error 事件（ai_stream_error）
 *   ② 200 空流（ai_empty_stream）
 *   ③ 网络错误（network）
 * ------------------------------------------------------------------ */

let failWith = null
let streamWith = null

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  aiChatStream: (...args) => {
    if (failWith) return Promise.reject(failWith)
    return streamWith ? streamWith(...args) : Promise.resolve({ text: 'ok' })
  },
  aiApi: {
    chat: vi.fn().mockResolvedValue({ content: '' }),
    chatRouter: vi.fn().mockResolvedValue({ content: '' }),
    ragSearch: vi.fn().mockResolvedValue({ hits: [], count: 0 }),
    localStatus: vi.fn().mockResolvedValue({ available: false }),
    getRouting: vi.fn().mockResolvedValue({ mode: 'local' }),
  },
}))

vi.mock('../components/DeepTools', () => ({ default: () => null }))

function makeErr(code, message) {
  const e = new Error(message)
  e.name = 'ApiError'
  e.code = code
  e.status = code === 'http_error' ? 502 : 0
  return e
}

beforeEach(() => {
  localStorage.clear()
  failWith = null
  streamWith = null
  // store 是模块级单例，用例之间必须手动清空对话，否则上一个用例的错误气泡会残留
  const st = useStore.getState()
  useStore.setState({ ai: { ...st.ai, messages: [] } })
})
afterEach(() => { cleanup(); localStorage.clear() })

async function askAnything() {
  const Assistant = (await import('../v3/pages/Assistant')).default
  render(<MemoryRouter><Assistant /></MemoryRouter>)
  const input = document.querySelector('textarea, input[type="text"], input')
  fireEvent.change(input, { target: { value: '怎么安排每天的复习？' } })
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
}

/** 取页面上「标红的错误气泡」——这就是 P0-5 要求必须出现的错误态。 */
async function errorBubble() {
  await waitFor(() => {
    expect(document.querySelector('.v3-asst-bubble.is-error')).toBeTruthy()
  })
  expect(screen.queryByRole('link', { name: '查看回答与引用详情' })).toBeNull()
  return document.querySelector('.v3-asst-bubble.is-error')
}

describe('AI 助手失败态必须可见（P0-5）', () => {
  it('④ 正常完成后归档本次引用，只在有详情记录时显示入口', async () => {
    streamWith = async (_body, handlers) => {
      handlers.onDelta({ meta: true, rag: true, rag_hits: 1, citations: [{ title: '高等数学', chunk_id: 9, content: '等价无穷小' }] })
      handlers.onDelta({ type: 'done', content: '使用等价无穷小，极限为 1。' })
    }
    await askAnything()
    const link = await screen.findByRole('link', { name: '查看回答与引用详情' })
    expect(link.getAttribute('href')).toMatch(/^\/assistant\/answers\//)
    expect(document.body.textContent).toContain('本轮权威引用（1）')
    const answerId = link.getAttribute('href').split('/').pop()
    expect(readAiAnswer(answerId)).toMatchObject({
      answer: '使用等价无穷小，极限为 1。',
      citations: [{ title: '高等数学', chunkId: 9 }],
    })
  })

  it('⑤ 中止生成后不归档，也不产生详情死链', async () => {
    streamWith = (_body, { signal, onDelta }) => new Promise((_resolve, reject) => {
      onDelta({ content: '尚未完成的回答' })
      signal.addEventListener('abort', () => {
        reject(Object.assign(new Error('已停止'), { code: 'aborted' }))
      }, { once: true })
    })
    await askAnything()
    fireEvent.click(await screen.findByRole('button', { name: '停止' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: '停止' })).toBeNull())
    expect(screen.queryByRole('link', { name: '查看回答与引用详情' })).toBeNull()
    expect(document.querySelector('.v3-asst-bubble')).not.toHaveTextContent('本轮权威引用')
  })

  it('⑥ 本机归档写入失败时不产生详情死链', async () => {
    streamWith = async (_body, handlers) => {
      handlers.onDelta({ type: 'done', content: '回答已生成，但浏览器拒绝本地保存。' })
    }
    const original = Storage.prototype.setItem
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (key, value) {
      if (String(key).includes('kaoyan-ai-answer-archive')) throw new DOMException('QuotaExceededError')
      return original.call(this, key, value)
    })
    try {
      await askAnything()
      expect(await screen.findByText('回答已生成，但浏览器拒绝本地保存。')).toBeInTheDocument()
      expect(screen.queryByRole('link', { name: '查看回答与引用详情' })).toBeNull()
    } finally {
      setItem.mockRestore()
    }
  })

  it('① SSE error 事件：出现「AI 服务报错」气泡 + 重试按钮', async () => {
    failWith = makeErr('ai_stream_error', 'AI 服务暂时不可用（provider_auth）：已配置服务商的 API Key 缺失或无效（上游返回 401/403）。')
    await askAnything()

    const bubble = await errorBubble()
    expect(bubble.textContent).toContain('AI 服务报错')
    // 后端分类后的原因码必须一路透到用户眼前，而不是一句笼统的"失败"
    expect(bubble.textContent).toContain('provider_auth')
    expect(bubble.textContent).toContain('重试')
  })

  it('② 200 空流：出现「空回复」气泡 + 重试按钮', async () => {
    failWith = makeErr('ai_empty_stream', 'AI 服务返回了空回复（HTTP 200 但没有输出任何内容）')
    await askAnything()

    const bubble = await errorBubble()
    expect(bubble.textContent).toContain('返回了空回复')
    expect(bubble.textContent).toContain('重试')
  })

  it('③ 网络错误：出现「网络错误」气泡 + 重试按钮', async () => {
    failWith = makeErr('network', '网络异常，无法连接 AI 服务（Failed to fetch）')
    await askAnything()

    const bubble = await errorBubble()
    expect(bubble.textContent).toContain('网络错误')
    expect(bubble.textContent).toContain('重试')
  })
})
