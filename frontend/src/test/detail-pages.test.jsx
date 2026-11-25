import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { setUser } from '../utils/userKeys'
import { readAiAnswer, saveAiAnswer } from '../utils/aiAnswerArchive'

const api = vi.hoisted(() => ({
  getError: vi.fn(),
  knowledgePoints: vi.fn(),
  aiAnalyze: vi.fn(),
  recommend: vi.fn(),
  schoolDetail: vi.fn(),
  schoolScores: vi.fn(),
  schoolAdmissions: vi.fn(),
  setGoal: vi.fn(),
}))
let currentUser = null

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  errorsApi: {
    get: api.getError,
    knowledgePoints: api.knowledgePoints,
    aiAnalyze: api.aiAnalyze,
  },
}))
vi.mock('../api/kaoyanApi', () => ({
  kaoyanApi: {
    recommend: api.recommend,
    schoolDetail: api.schoolDetail,
    schoolScores: api.schoolScores,
    schoolAdmissions: api.schoolAdmissions,
    setGoal: api.setGoal,
  },
}))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: currentUser }),
}))

import ErrorDetail from '../v3/pages/ErrorDetail'
import AssistantAnswer from '../v3/pages/AssistantAnswer'
import KaoyanRecommendDetail, { recommendParamsFromSearch } from '../v3/pages/KaoyanRecommendDetail'
import { buildRecommendDetailUrl } from '../v3/pages/KaoyanRecommend'

const recommendation = {
  school_id: 42,
  name: '测试院校',
  score: 78.5,
  safety: '稳妥',
  gap: 18,
  retest_ratio: 1.25,
  admit_avg_score: 365,
  confidence: 'medium',
  score_breakdown: { gap: 36, retest_ratio: 16, admit_avg: 17, region: 6, subject: 3.5 },
}
const errorRecord = {
  id: 42,
  content: '求极限 $\\lim_{x\\to 0} \\frac{\\sin x}{x}$',
  my_answer: '0',
  correct_answer: '1',
  error_reason: '等价无穷小条件不清',
  subject: '数学',
  accuracy: 0.4,
  review_count: 2,
  next_review: '2026-11-28T00:00:00Z',
  mastery_label: '巩固中',
  status: 'active',
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function renderAt(path, pattern) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/assistant/answers/:id" element={<AssistantAnswer />} />
        <Route path="/kaoyan/recommend/:schoolId" element={<KaoyanRecommendDetail />} />
        <Route path={pattern} element={<ErrorDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  localStorage.clear()
  setUser(7)
  currentUser = null
  vi.clearAllMocks()
  api.getError.mockResolvedValue(errorRecord)
  api.knowledgePoints.mockResolvedValue({ items: [{ knowledge_point_id: 9, name: '等价无穷小', subject: '数学', chapter: '极限' }] })
  api.aiAnalyze.mockResolvedValue({ analysis: '先判断无穷小类型', category: '概念不清', confidence: 'high' })
  api.recommend.mockResolvedValue({ recommendations: [recommendation], year: 2025, algorithm: '五维权重' })
  api.schoolDetail.mockResolvedValue({ name: '测试院校' })
  api.schoolScores.mockResolvedValue([{ id: 1, year: 2025, major_name: '电子技术', total_line: 335, source: '聚合数据' }])
  api.schoolAdmissions.mockResolvedValue([
    { id: 1, year: 2025, major_name: '电子技术', enroll_count: null, admit_count: 12 },
    { id: 2, year: 2024, major_name: '电子技术', enroll_count: 10, admit_count: 9 },
  ])
  api.setGoal.mockResolvedValue({})
})
afterEach(() => { cleanup(); localStorage.clear(); setUser(null) })

describe('AI 回答归档与三级详情', () => {
  it('按账号隔离、去重并保留本次权威引用', () => {
    expect(saveAiAnswer({ id: 'a1', question: '问题', answer: '回答', citations: [{ title: '教材', chunk_id: 8 }] })).toBe('a1')
    saveAiAnswer({ id: 'a1', question: '更新问题', answer: '更新回答', citations: [] })
    expect(readAiAnswer('a1')).toMatchObject({ question: '更新问题', answer: '更新回答', citations: [] })

    setUser(8)
    expect(readAiAnswer('a1')).toBeNull()
    saveAiAnswer({ id: 'a1', question: '另一账号', answer: '独立回答' })
    expect(readAiAnswer('a1').question).toBe('另一账号')
    setUser(7)
    expect(readAiAnswer('a1').question).toBe('更新问题')
  })

  it('无记录与切号均显示无法恢复，不泄漏其他账号回答', () => {
    setUser(7)
    saveAiAnswer({ id: 'a1', question: '私密问题', answer: '私密回答', citations: [{ title: '引用一', content: '原文' }] })
    renderAt('/assistant/answers/a1', '/assistant/answers/:id')
    expect(screen.getByRole('heading', { name: '回答与引用详情' })).toBeInTheDocument()
    expect(screen.getByText('私密问题')).toBeInTheDocument()
    expect(screen.getByText('引用一')).toBeInTheDocument()
    const followUp = decodeURIComponent(screen.getByRole('link', { name: /基于这条回答追问/ }).getAttribute('href'))
    expect(followUp).toContain('私密问题')
    cleanup()

    setUser(8)
    renderAt('/assistant/answers/a1', '/assistant/answers/:id')
    expect(screen.getByText('当前账号没有这条回答记录')).toBeInTheDocument()
    expect(screen.queryByText('私密回答')).toBeNull()
  })
})

describe('错题单题工作台', () => {
  it('通过单条接口直链加载，并串联知识点与 AI 追问', async () => {
    renderAt('/error-review/42', '/error-review/:id')
    expect(await screen.findByRole('heading', { name: '错题详情与 AI 加固' })).toBeInTheDocument()
    expect(api.getError).toHaveBeenCalledWith('42')
    expect(api.knowledgePoints).toHaveBeenCalledWith('42')
    expect(screen.getByRole('link', { name: /等价无穷小/ })).toHaveAttribute('href', '/knowledge/9')

    fireEvent.click(screen.getByRole('button', { name: '开始 AI 归因' }))
    expect(await screen.findByText('先判断无穷小类型')).toBeInTheDocument()
    const followUp = screen.getByRole('link', { name: /继续追问 AI/ })
    expect(followUp.getAttribute('href')).toContain('/assistant?q=')
    expect(decodeURIComponent(followUp.getAttribute('href'))).toContain('我的答案：0')
  })

  it('知识点缺少 ID 时保留文字，不生成 undefined 深链', async () => {
    api.knowledgePoints.mockResolvedValue({ items: [{ name: '未编号知识点', subject: '数学' }] })
    renderAt('/error-review/42', '/error-review/:id')
    expect(await screen.findByText('未编号知识点')).toBeInTheDocument()
    expect(document.querySelector('a[href="/knowledge/undefined"]')).toBeNull()
    expect(screen.queryByRole('link', { name: /未编号知识点/ })).toBeNull()
  })

  it('404 显示不存在或不属于当前账号', async () => {
    api.getError.mockRejectedValue(Object.assign(new Error('错题不存在'), { status: 404 }))
    renderAt('/error-review/999', '/error-review/:id')
    expect(await screen.findByText('这条错题不存在或不属于当前账号')).toBeInTheDocument()
    expect(screen.queryByText('求极限')).toBeNull()
  })

  it('切换 ID 时旧请求与旧 AI 分析不能覆盖新记录', async () => {
    const first = deferred()
    api.getError.mockImplementation((id) => id === '42' ? first.promise : Promise.resolve({ ...errorRecord, id: 43, content: '第二道题' }))
    function ErrorSwitch() {
      const navigate = useNavigate()
      return <><button onClick={() => navigate('/error-review/43')}>切换到第二题</button><ErrorDetail /></>
    }
    render(
      <MemoryRouter initialEntries={['/error-review/42']}>
        <Routes><Route path="/error-review/:id" element={<ErrorSwitch />} /></Routes>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: '切换到第二题' }))
    expect(await screen.findByText('第二道题')).toBeInTheDocument()
    first.resolve(errorRecord)
    await Promise.resolve()
    expect(screen.getByText('第二道题')).toBeInTheDocument()
    expect(screen.queryByText('求极限')).toBeNull()
  })
})

describe('择校推荐依据三级详情', () => {
  it('推荐深链保留全部筛选条件，参数边界明确', () => {
    const url = buildRecommendDetailUrl(recommendation, {
      score: 350, level: '211', province: '贵州', subject_code: '085401',
      target_avg_score: '365', max_retest_ratio: '1.2', year: 2025,
    })
    const params = new URL(url, 'https://local.test').searchParams
    expect(recommendParamsFromSearch(params)).toEqual({
      score: 350, level: '211', province: '贵州', subject_code: '085401',
      target_avg_score: '365', max_retest_ratio: '1.2', year: '2025',
    })
    expect(recommendParamsFromSearch(new URLSearchParams('score=0'))).toBeNull()
    expect(recommendParamsFromSearch(new URLSearchParams('score=350.5'))).toBeNull()
    expect(recommendParamsFromSearch(new URLSearchParams('score=501'))).toBeNull()
  })

  it('访客可看真实推荐依据，年份筛选生效且缺失人数不补 0', async () => {
    renderAt('/kaoyan/recommend/42?score=350&year=2025&province=贵州', '/kaoyan/recommend/:schoolId')
    expect(await screen.findByRole('heading', { name: '测试院校，为什么推荐给你？' })).toBeInTheDocument()
    expect(api.recommend).toHaveBeenCalledWith(expect.objectContaining({ score: 350, year: '2025', province: '贵州' }))
    expect(api.schoolScores).toHaveBeenCalledWith('42', { year: 2025 })
    expect(screen.getByText('评分拆解')).toBeInTheDocument()
    expect(screen.getByText('贵州')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '登录后设置' })).toHaveAttribute('href', '/login')
    expect(screen.getAllByRole('table')[0]).toBeInTheDocument()
    const admissionTable = screen.getAllByRole('table')[1]
    const admissionCells = admissionTable.querySelectorAll('tbody td')
    expect(admissionCells[2]).toHaveTextContent('—')
    expect(admissionCells[3]).toHaveTextContent('12')
    expect(admissionTable.textContent).not.toContain('2024')
  })

  it('登录用户按本次分数设置目标，失败有可见反馈', async () => {
    currentUser = { id: 7, role: 'user' }
    api.setGoal.mockRejectedValue(new Error('暂时无法保存'))
    renderAt('/kaoyan/recommend/42?score=350', '/kaoyan/recommend/:schoolId')
    fireEvent.click(await screen.findByRole('button', { name: '设为目标院校' }))
    await waitFor(() => expect(api.setGoal).toHaveBeenCalledWith('42', 350))
    expect(await screen.findByText(/设置目标失败：暂时无法保存/)).toBeInTheDocument()
  })

  it('A 院校设目标未完成时切到 B，旧提示不会串到新页面', async () => {
    currentUser = { id: 7, role: 'user' }
    const pendingGoal = deferred()
    api.setGoal.mockReturnValue(pendingGoal.promise)
    api.recommend.mockResolvedValue({
      recommendations: [recommendation, { ...recommendation, school_id: 43, name: '第二院校' }],
      year: 2025,
    })
    function SchoolSwitch() {
      const navigate = useNavigate()
      return <><button onClick={() => navigate('/kaoyan/recommend/43?score=350')}>切换到第二院校</button><KaoyanRecommendDetail /></>
    }
    render(
      <MemoryRouter initialEntries={['/kaoyan/recommend/42?score=350']}>
        <Routes><Route path="/kaoyan/recommend/:schoolId" element={<SchoolSwitch />} /></Routes>
      </MemoryRouter>,
    )
    fireEvent.click(await screen.findByRole('button', { name: '设为目标院校' }))
    fireEvent.click(screen.getByRole('button', { name: '切换到第二院校' }))
    expect(await screen.findByRole('heading', { name: '第二院校，为什么推荐给你？' })).toBeInTheDocument()
    await act(async () => {
      pendingGoal.resolve({})
      await pendingGoal.promise
    })
    expect(screen.queryByText(/已将「测试院校」设为目标院校/)).toBeNull()
    expect(screen.queryByText(/已将「第二院校」设为目标院校/)).toBeNull()
    expect(screen.getByRole('button', { name: '设为目标院校' })).toBeEnabled()
  })

  it('不在推荐结果与接口失败分别显示可行动空态', async () => {
    api.recommend.mockResolvedValue({ recommendations: [], year: 2025 })
    const { unmount } = renderAt('/kaoyan/recommend/42?score=350', '/kaoyan/recommend/:schoolId')
    expect(await screen.findByText('这所院校不在当前推荐结果中')).toBeInTheDocument()
    unmount()

    api.recommend.mockRejectedValue(new Error('服务不可用'))
    renderAt('/kaoyan/recommend/42?score=350', '/kaoyan/recommend/:schoolId')
    expect(await screen.findByText('推荐详情加载失败')).toBeInTheDocument()
    expect(screen.getByText('服务不可用')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })
})
