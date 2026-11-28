import { useState } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PersonalQuestionBank from '../v3/pages/PersonalQuestionBank'
import QuizPractice from '../v3/pages/QuizPractice'
import { quizApi } from '../api/client'
import { ukey } from '../utils/userKeys'

const { personalQuestionBankApi } = vi.hoisted(() => {
  const api = {}
  for (const name of [
    'sets', 'createSet', 'updateSet', 'deleteSet',
    'addQuestion', 'removeQuestion', 'questions',
    'createQuestion', 'updateQuestion', 'deleteQuestion', 'setMastery',
    'practice', 'createPracticeSession', 'submit', 'publicQuestions',
  ]) api[name] = vi.fn()
  return { personalQuestionBankApi: api }
})

// 只替换个人题库网络边界；client 的其他导出保持真实模块行为。
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  personalQuestionBankApi,
}))

const BANK = {
  id: 11,
  name: '数学专项',
  description: '错题与自建题',
  question_count: 3,
  mastered_count: 1,
}
const MANAGEMENT_QUESTION = {
  id: 21,
  bank_id: 11,
  content: '管理列表中的题目：1+1 等于多少？',
  question_type: 'single',
  options: ['2', '3'],
  answer: 'B',
  analysis: '不得出现在练习反馈前：1+1 等于 2。',
  subject: '数学',
  chapter: '极限',
  difficulty: 3,
  mastery_state: 'unmastered',
}
const PRACTICE_QUESTION = {
  id: 21,
  bank_id: 11,
  content: '练习题目：2 的平方是多少？',
  question_type: 'single',
  options: ['甲', '乙'],
  subject: '数学',
  mastery_state: 'unmastered',
  // 练习接口按契约不返回 answer / analysis。
}
const PRACTICE_SESSION = {
  session_id: 77,
  title: '数学专项练习',
  mode: 'practice',
  status: 'in_progress',
  basis: { kind: 'personal_question_bank', bank_id: 11 },
  filters: { bank_id: 11 },
  questions: [{ ...PRACTICE_QUESTION, answer: null, analysis: null }],
  current_index: 0,
  version: 1,
  drafts: {},
  text_drafts: {},
  self_scores: {},
  marked: {},
  duration_seconds: 0,
  records: {},
}

function questionPage(items, summary = { total: items.length, mastered: 0, unmastered: items.length }) {
  return { items, total: items.length, page: 1, page_size: 20, summary }
}

function apiError(message, status = 500) {
  return Object.assign(new Error(message), { name: 'ApiError', status, code: 'http_error' })
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function pendingProgress(sessionId) {
  const pending = JSON.parse(localStorage.getItem(ukey('quiz-session-pending')) || '{}')
  return pending[String(sessionId)] || null
}

function renderBank(entry = '/personal-question-bank') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <PersonalQuestionBank />
    </MemoryRouter>,
  )
}

function PracticeHarness({ session, submitAnswer, onRecord, onGoHome = () => {}, onFinish = () => {} }) {
  const [submitting, setSubmitting] = useState(false)
  return (
    <QuizPractice
      session={session}
      records={{}}
      basis={null}
      favs={{}}
      kpFilter={null}
      backendOk
      tutorMode="auto"
      setTutorMode={() => {}}
      submitting={submitting}
      setSubmitting={setSubmitting}
      submitAnswer={submitAnswer}
      manualChoiceSubmit
      showFavorites={false}
      onRecord={onRecord}
      onToggleFav={() => {}}
      onGoHome={onGoHome}
      onFinish={onFinish}
    />
  )
}

function practiceView(session, submitAnswer, onRecord, callbacks = {}) {
  return (
    <MemoryRouter>
      <PracticeHarness session={session} submitAnswer={submitAnswer} onRecord={onRecord} {...callbacks} />
    </MemoryRouter>
  )
}

async function selectBank() {
  fireEvent.click(await screen.findByRole('button', { name: /数学专项/ }))
  await waitFor(() => expect(personalQuestionBankApi.questions).toHaveBeenCalled())
}

async function enterPractice() {
  await selectBank()
  fireEvent.click(await screen.findByRole('button', { name: '开始刷题' }))
  await screen.findByText(PRACTICE_QUESTION.content)
}

beforeEach(() => {
  for (const fn of Object.values(personalQuestionBankApi)) fn.mockReset()
  personalQuestionBankApi.sets.mockResolvedValue({ items: [], total: 0 })
  personalQuestionBankApi.createSet.mockResolvedValue({ ...BANK, id: 99 })
  personalQuestionBankApi.updateSet.mockResolvedValue({ ok: true })
  personalQuestionBankApi.deleteSet.mockResolvedValue({ ok: true })
  personalQuestionBankApi.addQuestion.mockResolvedValue({ ok: true })
  personalQuestionBankApi.removeQuestion.mockResolvedValue({ ok: true })
  personalQuestionBankApi.questions.mockResolvedValue(questionPage([]))
  personalQuestionBankApi.createQuestion.mockResolvedValue({ ...MANAGEMENT_QUESTION, id: 88 })
  personalQuestionBankApi.updateQuestion.mockResolvedValue({ ok: true })
  personalQuestionBankApi.deleteQuestion.mockResolvedValue({ ok: true })
  personalQuestionBankApi.setMastery.mockResolvedValue({ ok: true })
  personalQuestionBankApi.practice.mockResolvedValue({ items: [PRACTICE_QUESTION], total: 1 })
  personalQuestionBankApi.createPracticeSession.mockResolvedValue(PRACTICE_SESSION)
  vi.spyOn(quizApi, 'patchSession').mockResolvedValue({ version: 2 })
  vi.spyOn(quizApi, 'completeSession').mockResolvedValue({ status: 'completed' })
  personalQuestionBankApi.submit.mockResolvedValue({
    correct: true,
    correct_answer: 'A',
    analysis: '2 的平方等于 4，对应选项甲。',
    needs_review: false,
  })
  personalQuestionBankApi.publicQuestions.mockResolvedValue({ items: [], total: 0 })
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('我的题库：个人题库与题目的用户行为契约', () => {
  it('新账号显示真实空态和可用入口，不伪造题库或题目', async () => {
    renderBank()

    expect(await screen.findByRole('heading', { name: '我的题库' })).toBeInTheDocument()
    expect(await screen.findByText('还没有个人题目')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '新建题库' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '自建题目' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '去题库选题' })).toBeEnabled()
    expect(screen.queryByText(BANK.name)).not.toBeInTheDocument()
    expect(screen.queryByText(MANAGEMENT_QUESTION.content)).not.toBeInTheDocument()
    expect(screen.queryByText(/示例题库|演示题目/)).not.toBeInTheDocument()
  })

  it('首次加载只请求当前分页，不循环拉取全部题目', async () => {
    personalQuestionBankApi.questions.mockResolvedValue(questionPage(
      Array.from({ length: 20 }, (_, index) => ({ ...MANAGEMENT_QUESTION, id: 100 + index })),
      { total: 500, mastered: 0, unmastered: 500 },
    ))
    renderBank()

    await screen.findByRole('heading', { name: '我的题库' })
    await waitFor(() => expect(personalQuestionBankApi.questions).toHaveBeenCalledTimes(1))
    expect(personalQuestionBankApi.questions).toHaveBeenCalledWith({ page: 1, page_size: 20 })
  })

  it('通过持久会话开始练习，并在交卷时调用 complete', async () => {
    vi.spyOn(quizApi, 'patchSession').mockResolvedValue({ version: 2 })
    const complete = vi.spyOn(quizApi, 'completeSession').mockResolvedValue({ status: 'completed' })
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    renderBank()
    await enterPractice()

    expect(personalQuestionBankApi.createPracticeSession).toHaveBeenCalledWith({ bank_id: 11 })
    expect(personalQuestionBankApi.practice).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(await screen.findByText(/回答正确|答对了/)).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])

    await waitFor(() => expect(complete).toHaveBeenCalledWith(77))
    expect(await screen.findByText('本次练习报告')).toBeInTheDocument()
  })

  it('刷新深链恢复原会话与草稿，不创建新会话', async () => {
    const getSession = vi.spyOn(quizApi, 'getSession').mockResolvedValue({
      ...PRACTICE_SESSION,
      version: 4,
      drafts: { 21: 0 },
      marked: { 21: true },
    })
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    renderBank('/personal-question-bank?bankId=11&view=practice&sessionId=77')

    expect(await screen.findByText(PRACTICE_QUESTION.content)).toBeInTheDocument()
    expect(getSession).toHaveBeenCalledWith(77)
    expect(personalQuestionBankApi.createPracticeSession).not.toHaveBeenCalled()
    expect(screen.getByRole('radio', { name: /A.*甲/ })).toBeChecked()
  })

  it('无题库会话的刷新深链按 NULL 题库口径恢复，不误判不匹配', async () => {
    const getSession = vi.spyOn(quizApi, 'getSession').mockResolvedValue({
      ...PRACTICE_SESSION,
      basis: { kind: 'personal_question_bank', bank_id: null },
    })
    renderBank('/personal-question-bank?view=practice&sessionId=77')

    expect(await screen.findByText(PRACTICE_QUESTION.content)).toBeInTheDocument()
    expect(getSession).toHaveBeenCalledWith(77)
    expect(personalQuestionBankApi.createPracticeSession).not.toHaveBeenCalled()
    expect(screen.queryByText('会话与题库不匹配')).not.toBeInTheDocument()
  })

  it('完成会话的结果深链恢复真实作答记录，不丢失用户答案', async () => {
    vi.spyOn(quizApi, 'getSession').mockResolvedValue({
      ...PRACTICE_SESSION,
      status: 'completed',
      records: {
        21: {
          my_answer: 'A', correct: true, correct_answer: 'A', analysis: '服务端保存的解析', needs_review: false,
        },
      },
    })
    renderBank('/personal-question-bank?bankId=11&view=result&sessionId=77')

    expect(await screen.findByText('本次练习报告')).toBeInTheDocument()
    expect(screen.getByText('你的答案：A')).toBeInTheDocument()
    expect(screen.getByText('解析：服务端保存的解析')).toBeInTheDocument()
    expect(personalQuestionBankApi.createPracticeSession).not.toHaveBeenCalled()
  })

  it('同一题提交重试复用 client_attempt_id，避免重复落账', async () => {
    personalQuestionBankApi.submit
      .mockRejectedValueOnce(apiError('网络开小差了，请重试'))
      .mockResolvedValueOnce({ correct: true, correct_answer: 'A', analysis: '解析', needs_review: false })
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    renderBank()
    await enterPractice()
    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('网络开小差了')

    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    await waitFor(() => expect(personalQuestionBankApi.submit).toHaveBeenCalledTimes(2))
    const first = personalQuestionBankApi.submit.mock.calls[0][0]
    const second = personalQuestionBankApi.submit.mock.calls[1][0]
    expect(first.session_id).toBe(77)
    expect(second.client_attempt_id).toBe(first.client_attempt_id)
  })

  it('公共题选择器始终请求 public_only，避免混入本人私有题', async () => {
    renderBank()
    await screen.findByText('还没有个人题目')

    fireEvent.click(screen.getByRole('button', { name: '去题库选题' }))

    await waitFor(() => expect(personalQuestionBankApi.publicQuestions).toHaveBeenCalledWith(
      expect.objectContaining({ public_only: true, page: 1, page_size: 10 }),
    ))
  })

  it('创建题库后立即展示名称、真实题数与掌握数，并刷新列表', async () => {
    personalQuestionBankApi.sets
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [BANK], total: 1 })
    personalQuestionBankApi.createSet.mockResolvedValue(BANK)
    renderBank()
    await screen.findByText('还没有个人题目')

    fireEvent.click(screen.getByRole('button', { name: '新建题库' }))
    const dialog = await screen.findByRole('dialog', { name: /新建题库/ })
    fireEvent.change(within(dialog).getByLabelText(/题库名称/), { target: { value: '  数学专项  ' } })
    fireEvent.change(within(dialog).getByLabelText(/题库描述/), { target: { value: '  错题与自建题  ' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /保存|创建/ }))

    expect(await screen.findByText(BANK.name)).toBeInTheDocument()
    expect(screen.getByText(/3\s*(道)?题/)).toBeInTheDocument()
    expect(screen.getByText(/已掌握\s*1\s*(道)?题?/)).toBeInTheDocument()
    expect(screen.queryByText('还没有个人题目')).not.toBeInTheDocument()
    expect(personalQuestionBankApi.createSet).toHaveBeenCalledWith({
      name: '数学专项',
      description: '错题与自建题',
    })
    await waitFor(() => expect(personalQuestionBankApi.sets).toHaveBeenCalledTimes(2))
  })

  it('选择题库后切换未掌握筛选，以题库、掌握状态和分页参数刷新题目', async () => {
    const mastered = { ...MANAGEMENT_QUESTION, id: 22, content: '已经掌握的题目', mastery_state: 'mastered' }
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.questions.mockImplementation(({ mastery } = {}) => Promise.resolve(
      questionPage(mastery === 'unmastered' ? [MANAGEMENT_QUESTION] : [MANAGEMENT_QUESTION, mastered], {
        total: 2, mastered: 1, unmastered: 1,
      }),
    ))
    renderBank()
    await selectBank()

    expect(screen.getByText('全部题目')).toBeInTheDocument()
    expect(screen.getByText('未掌握')).toBeInTheDocument()
    expect(screen.getByText('已掌握')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '未掌握' }))

    await waitFor(() => expect(personalQuestionBankApi.questions).toHaveBeenLastCalledWith(
      expect.objectContaining({ bank_id: 11, mastery: 'unmastered', page: 1, page_size: 20 }),
    ))
    expect(await screen.findByText(MANAGEMENT_QUESTION.content)).toBeInTheDocument()
    expect(screen.queryByText(mastered.content)).not.toBeInTheDocument()
  })

  it('手动标记已掌握后再取消，调用正确状态并刷新出对应题目', async () => {
    const unmastered = { ...MANAGEMENT_QUESTION, mastery_state: 'unmastered' }
    const mastered = { ...MANAGEMENT_QUESTION, mastery_state: 'mastered' }
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.questions
      .mockResolvedValueOnce(questionPage([unmastered], { total: 1, mastered: 0, unmastered: 1 }))
      .mockResolvedValueOnce(questionPage([unmastered], { total: 1, mastered: 0, unmastered: 1 }))
      .mockResolvedValueOnce(questionPage([mastered], { total: 1, mastered: 1, unmastered: 0 }))
      .mockResolvedValueOnce(questionPage([unmastered], { total: 1, mastered: 0, unmastered: 1 }))
    renderBank()
    await selectBank()

    fireEvent.click(await screen.findByRole('button', { name: '标记已掌握' }))
    await waitFor(() => expect(personalQuestionBankApi.setMastery).toHaveBeenNthCalledWith(1, 21, 'mastered'))
    fireEvent.click(await screen.findByRole('button', { name: '取消掌握' }))
    await waitFor(() => expect(personalQuestionBankApi.setMastery).toHaveBeenNthCalledWith(2, 21, 'unmastered'))
    expect(await screen.findByRole('button', { name: '标记已掌握' })).toBeInTheDocument()
    expect(personalQuestionBankApi.questions).toHaveBeenCalledTimes(4)
  })

  it('自建题提交时清理文本、规范化选项与难度，并携带所选题库', async () => {
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    renderBank()
    await selectBank()
    fireEvent.click(screen.getByRole('button', { name: '自建题目' }))

    const dialog = await screen.findByRole('dialog', { name: /自建题目/ })
    fireEvent.change(within(dialog).getByLabelText('题目内容'), {
      target: { value: '  下列哪项是 1+1 的结果？  ' },
    })
    fireEvent.change(within(dialog).getByLabelText(/选项/), {
      target: { value: 'A. 2\n B、3\n\n' },
    })
    fireEvent.change(within(dialog).getByLabelText('标准答案'), { target: { value: 'A' } })
    fireEvent.change(within(dialog).getByLabelText('答案解析'), {
      target: { value: '  基础加法。  ' },
    })
    fireEvent.change(within(dialog).getByLabelText('科目'), { target: { value: '数学' } })
    fireEvent.change(within(dialog).getByLabelText('章节'), { target: { value: '  极限  ' } })
    fireEvent.change(within(dialog).getByLabelText('难度'), { target: { value: '4' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /保存|创建/ }))

    await waitFor(() => expect(personalQuestionBankApi.createQuestion).toHaveBeenCalledTimes(1))
    const [body] = personalQuestionBankApi.createQuestion.mock.calls[0]
    expect(body).toMatchObject({
      bank_id: 11,
      content: '下列哪项是 1+1 的结果？',
      question_type: 'single',
      options: ['2', '3'],
      answer: 'A',
      analysis: '基础加法。',
      subject: '数学',
      chapter: '极限',
      difficulty: 4,
    })
    expect(body).not.toHaveProperty('optionsText')
    expect(await screen.findByText(/题目已(保存|创建|添加)/)).toBeInTheDocument()
  })

  it('练习时隐藏答案与解析，提交后收到反馈才揭示', async () => {
    const pending = deferred()
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.questions.mockResolvedValue(questionPage([MANAGEMENT_QUESTION]))
    personalQuestionBankApi.submit.mockReturnValue(pending.promise)
    renderBank()
    await enterPractice()

    expect(personalQuestionBankApi.createPracticeSession).toHaveBeenCalledWith(
      expect.objectContaining({ bank_id: 11 }),
    )
    expect(screen.queryByText(MANAGEMENT_QUESTION.answer)).not.toBeInTheDocument()
    expect(screen.queryByText(MANAGEMENT_QUESTION.analysis)).not.toBeInTheDocument()
    expect(screen.queryByText(/标准答案|答案解析/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    await waitFor(() => expect(personalQuestionBankApi.submit).toHaveBeenCalledWith(
      expect.objectContaining({ question_id: 21, my_answer: 'A' }),
    ))
    expect(screen.queryByText(/答案[：:]\s*A/)).not.toBeInTheDocument()
    expect(screen.queryByText(/2 的平方等于 4/)).not.toBeInTheDocument()

    await act(async () => {
      pending.resolve({ correct: true, correct_answer: 'A', analysis: '2 的平方等于 4，对应选项甲。', needs_review: false })
    })
    expect(await screen.findByText(/回答正确|答对了/)).toBeInTheDocument()
    expect(screen.getByText(/答案[：:]\s*A/)).toBeInTheDocument()
    expect(screen.getByText('2 的平方等于 4，对应选项甲。')).toBeInTheDocument()
  })

  it('练习加载时显示可读加载态，完成后才进入空结果', async () => {
    const pending = deferred()
    personalQuestionBankApi.sets.mockReturnValue(pending.promise)
    renderBank()

    expect(screen.getByText(/正在加载|加载中/)).toBeInTheDocument()
    expect(screen.queryByText('还没有个人题目')).not.toBeInTheDocument()
    await act(async () => { pending.resolve({ items: [], total: 0 }) })
    expect(await screen.findByText('还没有个人题目')).toBeInTheDocument()
    expect(screen.queryByText(/正在加载|加载中/)).not.toBeInTheDocument()
  })

  it('题库接口失败时显示错误与重试，重试成功后进入空态', async () => {
    personalQuestionBankApi.sets
      .mockRejectedValueOnce(apiError('服务暂时不可用，请稍后再试'))
      .mockResolvedValueOnce({ items: [], total: 0 })
    renderBank()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('服务暂时不可用，请稍后再试')
    expect(screen.queryByText('还没有个人题目')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('还没有个人题目')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(personalQuestionBankApi.sets).toHaveBeenCalledTimes(2)
  })

  it('题库内无匹配题目时显示空结果，而不是初始空态或伪造题目', async () => {
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.questions.mockResolvedValue(questionPage([]))
    renderBank()
    await selectBank()

    expect(await screen.findByText(/没有符合条件的题目|暂无题目/)).toBeInTheDocument()
    expect(screen.queryByText('还没有个人题目')).not.toBeInTheDocument()
    expect(screen.queryByText(MANAGEMENT_QUESTION.content)).not.toBeInTheDocument()
  })

  it('越权访问显示可读权限错误，不展示数据或成功提示', async () => {
    personalQuestionBankApi.sets.mockRejectedValue(apiError('无权访问该题库', 403))
    renderBank()

    expect(await screen.findByRole('alert')).toHaveTextContent('无权访问该题库')
    expect(screen.queryByText(BANK.name)).not.toBeInTheDocument()
    expect(screen.queryByText(MANAGEMENT_QUESTION.content)).not.toBeInTheDocument()
    expect(screen.queryByText('还没有个人题目')).not.toBeInTheDocument()
    expect(screen.queryByText(/创建成功|保存成功|加载成功/)).not.toBeInTheDocument()
  })

  it('练习提交失败显示可读错误，不显示成功或答案解析', async () => {
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.submit.mockRejectedValue(apiError('提交失败：网络开小差了，请重试'))
    renderBank()
    await enterPractice()

    fireEvent.click(screen.getByRole('radio', { name: /B.*乙/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('提交失败：网络开小差了，请重试')
    expect(screen.queryByText(/回答正确|回答错误|提交成功/)).not.toBeInTheDocument()
    expect(screen.queryByText(/答案[：:]\s*[AB]/)).not.toBeInTheDocument()
    expect(screen.queryByText(/2 的平方等于 4/)).not.toBeInTheDocument()
  })
})

describe('我的题库：答题与资产边界回归', () => {
  it('服务端返回 correct=null 时显示待确认，不判错、不记错题、不标红选项', async () => {
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.submit.mockResolvedValue({
      correct: null,
      needs_review: true,
      correct_answer: 'A',
      analysis: '答案置信度不足，请人工核对。',
    })
    renderBank()
    await enterPractice()

    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))

    expect(await screen.findByText(/答案待人工核对|待确认/)).toBeInTheDocument()
    expect(screen.queryByText(/回答错误/)).not.toBeInTheDocument()
    expect(screen.queryByText(/已计入错题本/)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(document.querySelector('.v3-quiz-reveal')).not.toHaveClass('is-bad')
    expect(screen.getByRole('radio', { name: /A.*甲/ })).not.toHaveClass('is-bad')
    expect(screen.getByRole('button', { name: '第 1 题，待确认' })).not.toHaveClass('is-bad')
    expect(personalQuestionBankApi.setMastery).not.toHaveBeenCalled()

    fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])
    expect(await screen.findByText('本次练习报告')).toBeInTheDocument()
    expect(document.querySelector('.pqb-result__score')).toHaveTextContent(/0\s*\/\s*1 题正确/)
    expect(document.querySelector('.pqb-result__item')).toHaveTextContent('待确认')
    expect(document.querySelector('.pqb-result__item')).not.toHaveClass('is-bad')
  })

  it('开始刷题时把科目、章节、题型和掌握状态筛选一并交给服务端', async () => {
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.questions.mockResolvedValue(questionPage([MANAGEMENT_QUESTION]))
    renderBank()
    await selectBank()
    await screen.findByText(MANAGEMENT_QUESTION.content)

    fireEvent.click(screen.getByRole('combobox', { name: '科目' }))
    fireEvent.click(screen.getByRole('option', { name: '数学', exact: true }))
    await waitFor(() => expect(personalQuestionBankApi.questions).toHaveBeenLastCalledWith(expect.objectContaining({ subject: '数学' })))
    fireEvent.click(screen.getByRole('combobox', { name: '章节' }))
    fireEvent.click(screen.getByRole('option', { name: '极限', exact: true }))
    await waitFor(() => expect(personalQuestionBankApi.questions).toHaveBeenLastCalledWith(expect.objectContaining({ subject: '数学', chapter: '极限' })))
    fireEvent.click(screen.getByRole('combobox', { name: '题型' }))
    fireEvent.click(screen.getByRole('option', { name: '单选', exact: true }))
    await waitFor(() => expect(personalQuestionBankApi.questions).toHaveBeenLastCalledWith(expect.objectContaining({ subject: '数学', chapter: '极限', question_type: 'single' })))
    fireEvent.click(screen.getByRole('button', { name: '未掌握' }))
    await waitFor(() => {
      expect(personalQuestionBankApi.questions).toHaveBeenLastCalledWith(expect.objectContaining({
        subject: '数学',
        chapter: '极限',
        question_type: 'single',
        mastery_state: 'unmastered',
      }))
      expect(screen.getByRole('combobox', { name: '科目' })).toHaveTextContent('数学')
      expect(screen.getByRole('combobox', { name: '章节' })).toHaveTextContent('极限')
      expect(screen.getByRole('combobox', { name: '题型' })).toHaveTextContent('单选')
    })

    fireEvent.click(await screen.findByRole('button', { name: '开始刷题' }))
    await waitFor(() => expect(personalQuestionBankApi.createPracticeSession).toHaveBeenCalledWith({
      bank_id: 11,
      subject: '数学',
      chapter: '极限',
      question_type: 'single',
      mastery_state: 'unmastered',
    }))
  })

  it('未分题库的 user_created 自建题可被识别，并能在不指定题库时开始刷题', async () => {
    const ownQuestion = {
      ...MANAGEMENT_QUESTION,
      bank_id: null,
      is_personal: undefined,
      source_kind: 'user_created',
    }
    personalQuestionBankApi.questions.mockResolvedValue(questionPage([ownQuestion], {
      total: 1,
      mastered: 0,
      unmastered: 1,
    }))
    renderBank()

    expect(await screen.findByRole('heading', { name: '未分题库的题目' })).toBeInTheDocument()
    expect(screen.queryByText('公共题')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '编辑题目' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '开始刷题' }))

    await waitFor(() => expect(personalQuestionBankApi.createPracticeSession).toHaveBeenCalledWith({}))
    expect(await screen.findByText(PRACTICE_QUESTION.content)).toBeInTheDocument()
  })

  it('编辑未分题库视图里的题目时省略 bank_id，不改变既有成员关系', async () => {
    const ownQuestion = {
      ...MANAGEMENT_QUESTION,
      bank_id: null,
      bank_ids: [11],
      is_personal: undefined,
      source_kind: 'user_created',
    }
    personalQuestionBankApi.questions.mockResolvedValue(questionPage([ownQuestion]))
    renderBank()
    fireEvent.click(await screen.findByRole('button', { name: '编辑题目' }))
    fireEvent.change(screen.getByLabelText('答案解析'), { target: { value: '补充解析' } })
    fireEvent.click(screen.getByRole('button', { name: '保存题目' }))

    await waitFor(() => expect(personalQuestionBankApi.updateQuestion).toHaveBeenCalled())
    const body = personalQuestionBankApi.updateQuestion.mock.calls[0][1]
    expect(body.analysis).toBe('补充解析')
    expect(body).not.toHaveProperty('bank_id')
  })

  it('答案提交未完成时禁用返回和交卷，响应落账后才允许结束', async () => {
    const pending = deferred()
    const submitAnswer = vi.fn(() => pending.promise)
    const onRecord = vi.fn()
    const onFinish = vi.fn()
    const session = {
      session_id: null, questions: [PRACTICE_QUESTION], records: {}, noAnswer: false,
      drafts: {}, text_drafts: {}, self_scores: {}, marked: {}, version: 1, duration_seconds: 0,
    }
    render(practiceView(session, submitAnswer, onRecord, { onFinish }))
    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))

    expect(await screen.findByRole('button', { name: '返回题库' })).toBeDisabled()
    const finishButtons = screen.getAllByRole('button', { name: '交卷并查看报告' })
    expect(finishButtons[0]).toBeDisabled()
    fireEvent.click(finishButtons[0])
    expect(onFinish).not.toHaveBeenCalled()
    expect(submitAnswer).toHaveBeenCalledTimes(1)

    await act(async () => pending.resolve({ correct: true, correct_answer: 'A', analysis: '解析' }))
    await waitFor(() => expect(onRecord).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: '返回题库' })).not.toBeDisabled()
    fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])
    await waitFor(() => expect(onFinish).toHaveBeenCalledTimes(1))
  })

  it('个人题库外层返回入口在提交期间同样禁用', async () => {
    const pending = deferred()
    personalQuestionBankApi.submit.mockReturnValue(pending.promise)
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.questions.mockResolvedValue(questionPage([MANAGEMENT_QUESTION]))
    renderBank()
    await enterPractice()
    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))

    const backButtons = await screen.findAllByRole('button', { name: '返回题库' })
    expect(backButtons).toHaveLength(2)
    expect(backButtons.every((button) => button.disabled)).toBe(true)
    await act(async () => pending.resolve({ correct: true, correct_answer: 'A', analysis: '解析' }))
  })

  it('交卷等待保存时禁止开始新作答', async () => {
    const saved = deferred()
    const patchSession = vi.spyOn(quizApi, 'patchSession').mockReturnValue(saved.promise)
    vi.spyOn(quizApi, 'completeSession').mockResolvedValue({ status: 'completed' })
    const submitAnswer = vi.fn().mockResolvedValue({ correct: true, correct_answer: 'A', analysis: '解析' })
    const onFinish = vi.fn()
    const second = { ...PRACTICE_QUESTION, id: 22, content: '第二道练习题' }
    const session = {
      session_id: 77,
      questions: [PRACTICE_QUESTION, second],
      records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
      version: 1, duration_seconds: 0, status: 'in_progress',
    }
    render(practiceView(session, submitAnswer, vi.fn(), { onFinish }))
    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    await waitFor(() => expect(submitAnswer).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByRole('button', { name: '交卷并查看报告' })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: '交卷并查看报告' }))
    await waitFor(() => expect(patchSession).toHaveBeenCalledTimes(1))
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(submitAnswer).toHaveBeenCalledTimes(1)
    expect(onFinish).not.toHaveBeenCalled()

    await act(async () => saved.resolve({ version: 2 }))
    await waitFor(() => expect(onFinish).toHaveBeenCalledTimes(1))
  })

  it('旧会话迟到的保存响应不改变新会话版本', async () => {
    const oldSave = deferred()
    const patchSession = vi.spyOn(quizApi, 'patchSession').mockImplementation((sessionId) => (
      sessionId === 77 ? oldSave.promise : Promise.resolve({ version: 2 })
    ))
    const first = {
      session_id: 77, questions: [PRACTICE_QUESTION, { ...PRACTICE_QUESTION, id: 22 }],
      records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
      version: 1, duration_seconds: 0, status: 'in_progress',
    }
    const rendered = render(practiceView(first, vi.fn(), vi.fn()))
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    await waitFor(() => expect(patchSession).toHaveBeenCalledWith(77, expect.any(Object)))

    const second = { ...first, session_id: 88, version: 1 }
    rendered.rerender(practiceView(second, vi.fn(), vi.fn()))
    await act(async () => oldSave.resolve({ version: 9 }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    await waitFor(() => expect(patchSession).toHaveBeenCalledWith(88, expect.objectContaining({ version: 1 })))
  })

  it('旧实例迟到的保存响应不删除新实例的待保存草稿', async () => {
  const oldSave = deferred()
  const newSave = deferred()
  const patchSession = vi.spyOn(quizApi, 'patchSession')
    .mockReturnValueOnce(oldSave.promise)
    .mockReturnValueOnce(newSave.promise)
  const session = {
    session_id: 77, questions: [PRACTICE_QUESTION],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  const first = render(practiceView(session, vi.fn(), vi.fn()))
  fireEvent(window, new Event('beforeunload'))
  await waitFor(() => expect(patchSession).toHaveBeenCalledTimes(1))
  first.unmount()

  render(practiceView(session, vi.fn(), vi.fn()))
  fireEvent(window, new Event('beforeunload'))
  await waitFor(() => expect(patchSession).toHaveBeenCalledTimes(2))
  expect(pendingProgress(77)).not.toBeNull()

  await act(async () => oldSave.resolve({ version: 9 }))
  await act(async () => newSave.reject(apiError('新会话保存失败')))
  expect(pendingProgress(77)).not.toBeNull()
})

it('旧会话未决保存不阻塞新会话保存、返回或交卷', async () => {
  const oldSave = deferred()
  const newSave = deferred()
  const patchSession = vi.spyOn(quizApi, 'patchSession').mockImplementation((sessionId) => (
    sessionId === 77 ? oldSave.promise : newSave.promise
  ))
  vi.spyOn(quizApi, 'completeSession').mockResolvedValue({ status: 'completed' })
  const first = {
    session_id: 77, questions: [PRACTICE_QUESTION],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  const onFinish = vi.fn()
  const rendered = render(practiceView(first, vi.fn(), vi.fn(), { onFinish }))
  fireEvent(window, new Event('beforeunload'))
  await waitFor(() => expect(patchSession).toHaveBeenCalledWith(77, expect.any(Object)))

  rendered.rerender(practiceView({ ...first, session_id: 88 }, vi.fn(), vi.fn(), { onFinish }))
  fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])
  expect(screen.getByRole('button', { name: '问 AI' })).toBeDisabled()
  await waitFor(() => expect(patchSession).toHaveBeenCalledWith(88, expect.any(Object)))
  expect(onFinish).not.toHaveBeenCalled()

  await act(async () => newSave.resolve({ version: 2 }))
  await waitFor(() => expect(onFinish).toHaveBeenCalledTimes(1))
  await act(async () => oldSave.resolve({ version: 9 }))
  expect(onFinish).toHaveBeenCalledTimes(1)
})

it('保存失败时保留本地草稿，不交卷也不清除待保存快照', async () => {
  vi.spyOn(quizApi, 'patchSession').mockRejectedValue(apiError('保存失败'))
  const completeSession = vi.spyOn(quizApi, 'completeSession').mockResolvedValue({ status: 'completed' })
  const onFinish = vi.fn()
  const session = {
    session_id: 77, questions: [PRACTICE_QUESTION],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  render(practiceView(session, vi.fn(), vi.fn(), { onFinish }))
  fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])

  expect(await screen.findByText(/进度保存失败：保存失败/)).toBeInTheDocument()
  expect(completeSession).not.toHaveBeenCalled()
  expect(onFinish).not.toHaveBeenCalled()
  expect(pendingProgress(77)).not.toBeNull()
})

it('旧实例迟到的交卷完成响应不删除新实例的待保存草稿', async () => {
  const oldComplete = deferred()
  const newSave = deferred()
  vi.spyOn(quizApi, 'patchSession')
    .mockResolvedValueOnce({ version: 2 })
    .mockReturnValueOnce(newSave.promise)
  vi.spyOn(quizApi, 'completeSession').mockReturnValue(oldComplete.promise)
  const session = {
    session_id: 77, questions: [PRACTICE_QUESTION],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  const first = render(practiceView(session, vi.fn(), vi.fn()))
  fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])
  await waitFor(() => expect(quizApi.completeSession).toHaveBeenCalledWith(77))
  first.unmount()

  render(practiceView(session, vi.fn(), vi.fn()))
  fireEvent(window, new Event('beforeunload'))
  await waitFor(() => expect(quizApi.patchSession).toHaveBeenCalledTimes(2))
  expect(pendingProgress(77)).not.toBeNull()

  await act(async () => oldComplete.resolve({ status: 'completed' }))
  expect(pendingProgress(77)).not.toBeNull()
  await act(async () => newSave.resolve({ version: 3 }))
})

it('409合并使用请求在途产生的最新编辑，不回滚草稿', async () => {
  const firstSave = deferred()
  const patchSession = vi.spyOn(quizApi, 'patchSession')
    .mockReturnValueOnce(firstSave.promise)
    .mockResolvedValueOnce({ version: 6 })
  vi.spyOn(quizApi, 'getSession').mockResolvedValue({
    status: 'in_progress', version: 5, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
  })
  const session = {
    session_id: 77, questions: [PRACTICE_QUESTION],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  render(practiceView(session, vi.fn(), vi.fn()))
  fireEvent(window, new Event('beforeunload'))
  await waitFor(() => expect(patchSession).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))

  await act(async () => firstSave.reject(apiError('版本冲突', 409)))
  await waitFor(() => expect(patchSession).toHaveBeenCalledTimes(2))
  expect(patchSession.mock.calls[1][1].drafts).toEqual({ 21: 0 })
  expect(screen.getByRole('radio', { name: /A.*甲/ })).toBeChecked()
})

it('旧会话未决保存不阻塞新会话返回', async () => {
  const oldSave = deferred()
  const newSave = deferred()
  const patchSession = vi.spyOn(quizApi, 'patchSession').mockImplementation((sessionId) => (
    sessionId === 77 ? oldSave.promise : newSave.promise
  ))
  const first = {
    session_id: 77, questions: [PRACTICE_QUESTION],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  const onGoHome = vi.fn()
  const rendered = render(practiceView(first, vi.fn(), vi.fn(), { onGoHome }))
  fireEvent(window, new Event('beforeunload'))
  await waitFor(() => expect(patchSession).toHaveBeenCalledWith(77, expect.any(Object)))

  rendered.rerender(practiceView({ ...first, session_id: 88 }, vi.fn(), vi.fn(), { onGoHome }))
  fireEvent.click(screen.getByRole('button', { name: '返回题库' }))
  await waitFor(() => expect(patchSession).toHaveBeenCalledWith(88, expect.any(Object)))
  expect(onGoHome).not.toHaveBeenCalled()

  await act(async () => newSave.resolve({ version: 2 }))
  await waitFor(() => expect(onGoHome).toHaveBeenCalledTimes(1))
  await act(async () => oldSave.resolve({ version: 9 }))
  expect(onGoHome).toHaveBeenCalledTimes(1)
})

it.each([
  { action: '返回题库', callback: 'onGoHome' },
  { action: '交卷并查看报告', callback: 'onFinish' },
])('$action 保存等待期间禁止继续编辑文本题', async ({ action, callback }) => {
  const saved = deferred()
  const patchSession = vi.spyOn(quizApi, 'patchSession').mockReturnValue(saved.promise)
  vi.spyOn(quizApi, 'completeSession').mockResolvedValue({ status: 'completed' })
  const onDone = vi.fn()
  const session = {
    session_id: 77,
    questions: [{ ...PRACTICE_QUESTION, question_type: 'essay', answer: '参考答案' }],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  render(practiceView(session, vi.fn(), vi.fn(), { [callback]: onDone }))
  const input = screen.getByRole('textbox', { name: '作答输入框' })
  fireEvent.change(input, { target: { value: '保存前的答案' } })
  fireEvent.click(action === '返回题库'
    ? screen.getByRole('button', { name: action })
    : screen.getAllByRole('button', { name: action })[0])
  await waitFor(() => expect(patchSession).toHaveBeenCalledTimes(1))

  expect(input).toBeDisabled()
  fireEvent.change(input, { target: { value: '保存后的答案' } })
  expect(input).toHaveValue('保存前的答案')
  expect(patchSession.mock.calls[0][1].text_drafts).toEqual({ 21: '保存前的答案' })

  await act(async () => saved.resolve({ version: 2 }))
  await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
})

it('409后的重试保存失败显示错误并阻止交卷', async () => {
  vi.spyOn(quizApi, 'patchSession')
    .mockRejectedValueOnce(apiError('版本冲突', 409))
    .mockRejectedValueOnce(apiError('重试保存失败'))
  vi.spyOn(quizApi, 'getSession').mockResolvedValue({
    status: 'in_progress', version: 5, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
  })
  const completeSession = vi.spyOn(quizApi, 'completeSession').mockResolvedValue({ status: 'completed' })
  const onFinish = vi.fn()
  const session = {
    session_id: 77, questions: [PRACTICE_QUESTION],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  render(practiceView(session, vi.fn(), vi.fn(), { onFinish }))
  fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])

  expect(await screen.findByText(/进度保存失败：重试保存失败/)).toBeInTheDocument()
  expect(completeSession).not.toHaveBeenCalled()
  expect(onFinish).not.toHaveBeenCalled()
  expect(pendingProgress(77)).not.toBeNull()
})

it('409后读取会话失败显示错误、保留草稿并阻止交卷', async () => {
  vi.spyOn(quizApi, 'patchSession').mockRejectedValueOnce(apiError('版本冲突', 409))
  vi.spyOn(quizApi, 'getSession').mockRejectedValue(apiError('读取会话失败'))
  const completeSession = vi.spyOn(quizApi, 'completeSession').mockResolvedValue({ status: 'completed' })
  const onFinish = vi.fn()
  const session = {
    session_id: 77, questions: [PRACTICE_QUESTION],
    records: {}, noAnswer: false, drafts: {}, text_drafts: {}, self_scores: {}, marked: {},
    version: 1, duration_seconds: 0, status: 'in_progress',
  }
  render(practiceView(session, vi.fn(), vi.fn(), { onFinish }))
  fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])

  expect(await screen.findByText(/进度保存失败：读取会话失败/)).toBeInTheDocument()
  expect(completeSession).not.toHaveBeenCalled()
  expect(onFinish).not.toHaveBeenCalled()
  expect(pendingProgress(77)).not.toBeNull()
})

it('结果页按练习中的原题号展示，只答第二题时仍显示第二题', async () => {
    const secondQuestion = {
      ...PRACTICE_QUESTION,
      id: 22,
      content: '第二题：3 的平方是多少？',
    }
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.createPracticeSession.mockResolvedValue({
      ...PRACTICE_SESSION,
      questions: [PRACTICE_QUESTION, secondQuestion],
    })
    renderBank()
    await selectBank()
    fireEvent.click(await screen.findByRole('button', { name: '开始刷题' }))
    await screen.findByText(PRACTICE_QUESTION.content)

    fireEvent.click(screen.getByRole('button', { name: '第 2 题' }))
    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(await screen.findByText(/回答正确|答对了/)).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '交卷并查看报告' })[0])

    expect(await screen.findByText('本次练习报告')).toBeInTheDocument()
    expect(document.querySelector('.pqb-result__item')).toHaveTextContent('第 2 题')
    expect(document.querySelector('.pqb-result__item')).not.toHaveTextContent('第 1 题')
  })

  it('同一道题加入多个题库时，切换到第二个题库仍按 bank_ids 显示', async () => {
    const secondBank = { ...BANK, id: 12, name: '英语强化', description: '跨题库题目' }
    const sharedQuestion = {
      ...MANAGEMENT_QUESTION,
      bank_id: 11,
      bank_ids: [11, 12],
    }
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK, secondBank], total: 2 })
    personalQuestionBankApi.questions.mockResolvedValue(questionPage([sharedQuestion]))
    renderBank()
    await selectBank()

    fireEvent.click(screen.getByRole('button', { name: /英语强化/ }))
    expect(await screen.findByText(sharedQuestion.content)).toBeInTheDocument()
  })

  it('提交等待期间连续点击只发送一次请求，并在成功后解除锁定', async () => {
    const pending = deferred()
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    personalQuestionBankApi.submit.mockReturnValue(pending.promise)
    renderBank()
    await enterPractice()

    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    const submitButton = screen.getByRole('button', { name: '提交答案' })
    fireEvent.click(submitButton)
    fireEvent.click(submitButton)
    expect(personalQuestionBankApi.submit).toHaveBeenCalledTimes(1)
    expect(submitButton).toBeDisabled()

    await act(async () => {
      pending.resolve({ correct: true, correct_answer: 'A', analysis: '提交完成。', needs_review: false })
    })
    expect(await screen.findByText(/回答正确|答对了/)).toBeInTheDocument()
  })

  it('删除题库前明确自建题会保留在未分题库，不承诺连带软删除', async () => {
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK], total: 1 })
    renderBank()
    fireEvent.click(await screen.findByRole('button', { name: '删除第 1 个题库' }))

    const dialog = await screen.findByRole('dialog', { name: /删除题库/ })
    expect(dialog).toHaveTextContent('个人自建题会保留在未分题库题目中')
    expect(dialog).not.toHaveTextContent('个人自建题也会软删除')
    expect(personalQuestionBankApi.deleteSet).not.toHaveBeenCalled()
  })

  it('切换到新练习后，上一轮迟到的提交不写答案也不解除新一轮提交锁', async () => {
    const firstPending = deferred()
    const secondPending = deferred()
    const submitAnswer = vi.fn()
      .mockReturnValueOnce(firstPending.promise)
      .mockReturnValueOnce(secondPending.promise)
    const onRecord = vi.fn()
    const firstSession = { title: '第一轮', mode: 'personal', questions: [{ ...PRACTICE_QUESTION, id: 21 }] }
    const secondQuestion = { ...PRACTICE_QUESTION, id: 22, content: '新一轮题目' }
    const secondSession = { title: '第二轮', mode: 'personal', questions: [secondQuestion] }
    const { rerender } = render(practiceView(firstSession, submitAnswer, onRecord))

    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(submitAnswer).toHaveBeenCalledTimes(1)

    rerender(practiceView(secondSession, submitAnswer, onRecord))
    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(submitAnswer).toHaveBeenCalledTimes(2)

    await act(async () => {
      firstPending.resolve({ correct: false, correct_answer: 'B', analysis: '上一轮答案', needs_review: false })
    })
    expect(onRecord).not.toHaveBeenCalled()
    expect(screen.queryByText('上一轮答案')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交答案' })).toBeDisabled()

    await act(async () => {
      secondPending.resolve({ correct: true, correct_answer: 'A', analysis: '新一轮答案', needs_review: false })
    })
    expect(onRecord).toHaveBeenCalledTimes(1)
    expect(onRecord).toHaveBeenCalledWith(22, expect.objectContaining({ analysis: '新一轮答案' }))
  })

  it('练习卸载后，迟到的提交不再回调写入作答记录', async () => {
    const pending = deferred()
    const onRecord = vi.fn()
    const session = { title: '待卸载练习', mode: 'personal', questions: [PRACTICE_QUESTION] }
    const { unmount } = render(practiceView(session, vi.fn().mockReturnValue(pending.promise), onRecord))

    fireEvent.click(screen.getByRole('radio', { name: /A.*甲/ }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    unmount()
    await act(async () => {
      pending.resolve({ correct: true, correct_answer: 'A', analysis: '卸载后返回', needs_review: false })
    })
    expect(onRecord).not.toHaveBeenCalled()
  })

  it('多选题使用原生复选框与分组语义，不误报为单选', () => {
    const question = { ...PRACTICE_QUESTION, question_type: 'multiple' }
    const session = { title: '多选练习', mode: 'personal', questions: [question] }
    render(practiceView(session, vi.fn(), vi.fn()))

    expect(screen.getByRole('group', { name: '多选题选项' })).toBeInTheDocument()
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    const option = screen.getByRole('checkbox', { name: /A.*甲/ })
    expect(option.tagName).toBe('INPUT')
    expect(option).toHaveAttribute('type', 'checkbox')
    fireEvent.click(option)
    expect(option).toBeChecked()
  })

  it('快速切换题库时，旧题库迟到响应不能覆盖新题库题目', async () => {
    const secondBank = { ...BANK, id: 12, name: '英语强化', description: '跨题库题目' }
    const firstQuestion = { ...MANAGEMENT_QUESTION, bank_id: 11 }
    const secondQuestion = { ...MANAGEMENT_QUESTION, id: 22, bank_id: 12, content: '只属于英语题库的题目' }
    const firstPending = deferred()
    personalQuestionBankApi.sets.mockResolvedValue({ items: [BANK, secondBank], total: 2 })
    personalQuestionBankApi.questions.mockImplementation(({ bank_id } = {}) => {
      if (!bank_id) return Promise.resolve(questionPage([]))
      if (Number(bank_id) === 11) return firstPending.promise
      return Promise.resolve(questionPage([secondQuestion]))
    })
    renderBank()
    fireEvent.click(await screen.findByRole('button', { name: /数学专项/ }))
    fireEvent.click(screen.getByRole('button', { name: /英语强化/ }))

    expect(await screen.findByText(secondQuestion.content)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /英语强化 · 题目管理/ })).toBeInTheDocument()
    await act(async () => { firstPending.resolve(questionPage([firstQuestion])) })
    expect(screen.getByText(secondQuestion.content)).toBeInTheDocument()
    expect(screen.queryByText(firstQuestion.content)).not.toBeInTheDocument()
  })
})
