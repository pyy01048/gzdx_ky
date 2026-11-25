import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, act, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const api = vi.hoisted(() => ({
  flashcards: {
    list: vi.fn(),
    create: vi.fn(),
    review: vi.fn(),
    remove: vi.fn(),
  },
  words: {
    listDecks: vi.fn(),
    list: vi.fn(),
    stats: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    flashcardsApi: api.flashcards,
    wordsApi: api.words,
    taxonomyApi: {
      ...actual.taxonomyApi,
      subjects: vi.fn().mockResolvedValue({ subjects: [{ subject: '数学' }] }),
    },
  }
})

import useStore from '../store/useStore'
import Cards from '../v3/pages/Cards'
import Words from '../v3/pages/Words'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  api.flashcards.list.mockResolvedValue({ total: 0, page: 1, page_size: 200, total_pages: 1, items: [] })
  api.flashcards.create.mockResolvedValue({ id: 900 })
  api.words.listDecks.mockResolvedValue([])
  api.words.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200, total_pages: 1 })
  api.words.stats.mockResolvedValue({ today_new: 0, today_review: 0 })
  api.words.get.mockResolvedValue(null)
  useStore.setState({
    cards: [],
    packs: [{ id: 'pack-1', name: '数学卡包', subject: '数学', count: 0 }],
    notebook: [],
    words: [],
    decks: [],
  })
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

describe('Words 总结区图标', () => {
  it('学习总结可渲染本轮错词区，AlertTriangle 已正确导入', async () => {
    render(<MemoryRouter><Words /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('tab', { name: '学习总结' }))
    expect(await screen.findByText(/本轮错词 0 个/)).toBeInTheDocument()
  })
})

describe('Cards 创建唯一 owner 与 ID adoption', () => {
  it('手工新建只 POST 一次，完整携带 hint/deck_id，并在响应前乐观插入', async () => {
    const request = deferred()
    api.flashcards.create.mockReturnValue(request.promise)
    render(<MemoryRouter><Cards /></MemoryRouter>)

    fireEvent.click((await screen.findAllByRole('button', { name: '新建卡片' }))[0])
    fireEvent.click(screen.getByLabelText('选择卡包'))
    fireEvent.click(screen.getByRole('option', { name: '数学卡包' }))
    fireEvent.change(screen.getByLabelText('卡片正面（问题）'), { target: { value: '什么是极限？' } })
    fireEvent.change(screen.getByLabelText('卡片背面（答案）'), { target: { value: '描述无限接近的过程。' } })
    fireEvent.change(screen.getByLabelText('卡片提示（可选）'), { target: { value: '注意 ε-δ 定义' } })
    expect(screen.getByLabelText('选择卡包')).toHaveTextContent('数学卡包')
    expect(screen.getByLabelText('卡片正面（问题）')).toHaveValue('什么是极限？')
    expect(screen.getByLabelText('卡片背面（答案）')).toHaveValue('描述无限接近的过程。')
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '添加' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('请选择卡包')).not.toBeInTheDocument()
    expect(screen.queryByText('请补全卡片正面与背面的内容')).not.toBeInTheDocument()
    expect(useStore.getState().cards).toHaveLength(1)
    expect(api.flashcards.create).toHaveBeenCalledTimes(1)
    expect(api.flashcards.create).toHaveBeenCalledWith({
      front: '什么是极限？',
      back: '描述无限接近的过程。',
      hint: '注意 ε-δ 定义',
      deck_id: 'pack-1',
    })
    expect(useStore.getState().cards).toHaveLength(1)
    expect(useStore.getState().cards[0]).toMatchObject({
      front: '什么是极限？', hint: '注意 ε-δ 定义', packId: 'pack-1', status: 'new',
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await act(async () => { request.resolve({ id: 901 }) })
    await waitFor(() => expect(useStore.getState().cards[0].id).toBe('901'))
    expect(useStore.getState().packs[0].count).toBe(1)
  })

  it('错题转卡片也只由 store 创建一次，并保留解析为 hint', async () => {
    useStore.setState({
      notebook: [{ id: 11, question: '错题题干', answer: '正确答案', analysis: '错因提示', subject: '数学' }],
    })
    render(<MemoryRouter><Cards /></MemoryRouter>)

    fireEvent.click((await screen.findAllByRole('button', { name: '错题转卡片' }))[0])
    fireEvent.click(await screen.findByRole('button', { name: /错题题干/ }))
    await act(async () => { await Promise.resolve() })

    expect(api.flashcards.create).toHaveBeenCalledTimes(1)
    expect(api.flashcards.create).toHaveBeenCalledWith({
      front: '错题题干', back: '正确答案', hint: '错因提示', deck_id: 'pack-1',
    })
    expect(useStore.getState().cards[0]).toMatchObject({ sourceNoteId: 11, packId: 'pack-1' })
  })

  it('并发创建乱序返回时，后端 ID 只 adoption 到各自本地卡片', async () => {
    const requests = []
    api.flashcards.create.mockImplementation(() => {
      const request = deferred()
      requests.push(request)
      return request.promise
    })

    act(() => {
      useStore.getState().addCard({ front: '第一张', back: '答案一', hint: '提示一', packId: 'pack-1' })
      useStore.getState().addCard({ front: '第二张', back: '答案二', hint: '提示二', packId: 'pack-1' })
    })
    expect(requests).toHaveLength(2)
    const firstLocalId = useStore.getState().cards.find((c) => c.front === '第一张').id
    const secondLocalId = useStore.getState().cards.find((c) => c.front === '第二张').id

    await act(async () => { requests[1].resolve({ id: 8202 }) })
    await waitFor(() => {
      expect(useStore.getState().cards.find((c) => c.front === '第二张').id).toBe('8202')
      expect(useStore.getState().cards.find((c) => c.front === '第一张').id).toBe(firstLocalId)
    })

    await act(async () => { requests[0].resolve({ id: 8201 }) })
    await waitFor(() => {
      expect(useStore.getState().cards.find((c) => c.front === '第一张').id).toBe('8201')
      expect(useStore.getState().cards.find((c) => c.front === '第二张').id).toBe('8202')
    })
    expect(useStore.getState().cards.some((c) => c.id === secondLocalId)).toBe(false)
    expect(useStore.getState().packs[0].count).toBe(2)
  })
})
