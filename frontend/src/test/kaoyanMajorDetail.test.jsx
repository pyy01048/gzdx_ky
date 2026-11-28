import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

const authState = vi.hoisted(() => ({ user: null }))
const majorDetailMock = vi.hoisted(() => vi.fn())
vi.mock('../auth/AuthContext', () => ({ useAuth: () => authState }))
vi.mock('../api/kaoyanApi', () => ({ kaoyanApi: { majorDetail: majorDetailMock } }))

import KaoyanMajorDetail, {
  buildMajorDetailPath, buildMajorPracticePath, safeExternalUrl,
} from '../v3/pages/KaoyanMajorDetail'

const DETAIL = {
  major: {
    id: 11, school_id: 1, code: '0812', name: '计算机科学与技术',
    degree_type: '工学硕士', research_direction: '人工智能', subject_code: '0812',
  },
  school: { id: 1, name: '甲大学', province: '贵州', city: '贵阳', data_source: 'school_official' },
  discipline: { id: 8, code: '0812', name: '计算机科学与技术' },
  matched_subjects: [
    {
      id: 101, code: '201', name: '数学一', short_name: '数一', question_count: 3,
      exam_subject_codes: ['101'], exam_subject_names: ['数学'], confidence: 0.96,
      match_sources: [{ method: 'official' }],
    },
    {
      id: 102, code: '408', name: '计算机学科专业基础综合', short_name: '408', question_count: 0,
      exam_subject_codes: ['408'], exam_subject_names: ['计算机专业基础'], confidence: 1,
      match_sources: [{ method: 'manual' }],
    },
  ],
  selected_subject_id: 101,
  question_count_total: 3,
  resource_pack: {
    status: 'ready', scope: 'major_subject', total: 1,
    items: [{
      id: 900, major_id: 11, subject_id: 101, resource_type: 'textbook', title: '高等数学',
      url: 'https://example.edu/resource',
      description: '专业明确登记的资源', source: { source_name: '院校研招网' },
      source_url: 'https://example.edu/source', verification_status: 'verified', visibility: 'public',
      textbook: { id: 3, title: '高等数学（第七版）', authors: ['同济大学数学系'], publisher: '高等教育出版社' },
    }],
  },
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function renderPage(route = '/kaoyan/majors/11?school_id=1&major_id=11&subject_id=101') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/kaoyan/majors/:id" element={<KaoyanMajorDetail />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  authState.user = null
  majorDetailMock.mockResolvedValue(DETAIL)
})

afterEach(() => cleanup())

describe('专业详情深链', () => {
  it('按 school_id/major_id/subject_id 请求并展示真实字段、资源与练习 CTA', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: '计算机科学与技术' })).toBeInTheDocument()
    expect(majorDetailMock).toHaveBeenCalledWith(
      11, { school_id: 1, subject_id: 101 }, expect.objectContaining({ signal: expect.anything() }),
    )
    expect(screen.getByText('人工智能')).toBeInTheDocument()
    expect(screen.getByText(/学院归属未做名称推断/)).toBeInTheDocument()
    expect(screen.getByText('高等数学')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /进入该科练习/ })).toHaveAttribute(
      'href', '/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=101',
    )
    expect(screen.getByRole('link', { name: /打开资源/ })).toHaveAttribute('target', '_blank')
  })

  it('切换 matched 科目写回 URL，并刷新该科目资源与 CTA', async () => {
    majorDetailMock.mockImplementation((_id, params) => Promise.resolve({
      ...DETAIL,
      selected_subject_id: params?.subject_id || 101,
      resource_pack: {
        status: 'ready', scope: 'major_subject', total: params?.subject_id === 102 ? 1 : 0,
        items: params?.subject_id === 102 ? [{
          ...DETAIL.resource_pack.items[0], id: 901, subject_id: 102,
          title: '408 复习提纲', resource_type: 'outline', verification_status: 'unverified',
        }] : DETAIL.resource_pack.items,
      },
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /计算机学科专业基础综合/ }))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('subject_id=102'))
    expect(await screen.findByText('408 复习提纲')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /进入该科练习/ })).toHaveAttribute(
      'href', '/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=102',
    )
  })

  it('matched 科目为空时明确阻止练习 CTA', async () => {
    majorDetailMock.mockResolvedValue({
      ...DETAIL, matched_subjects: [], selected_subject_id: null, question_count_total: 0,
      resource_pack: { status: 'ready', scope: 'major_subject', total: 0, items: [] },
    })
    renderPage()

    expect(await screen.findByText('暂无已匹配的考试科目')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '暂无可进入的匹配科目' })).toBeDisabled()
    expect(screen.queryByRole('link', { name: /进入该科练习/ })).not.toBeInTheDocument()
  })

  it('有科目但无资源时说明学校级教材不能替代专业证据', async () => {
    majorDetailMock.mockResolvedValue({
      ...DETAIL, resource_pack: { status: 'ready', scope: 'major_subject', total: 0, items: [] },
    })
    renderPage()

    expect(await screen.findByText('该科目暂无专业级教材或资源')).toBeInTheDocument()
    expect(screen.getByText(/textbook_schools 只证明学校使用过教材/)).toBeInTheDocument()
  })

  it('210 未执行时显示迁移待执行空态', async () => {
    majorDetailMock.mockResolvedValue({
      ...DETAIL, resource_pack: { status: 'migration_pending', scope: 'major_subject', total: 0, items: [] },
    })
    renderPage()

    expect(await screen.findByText(/专业资源表尚未执行 210 迁移/)).toBeInTheDocument()
  })

  it('404 与错误链接参数都有明确空态', async () => {
    majorDetailMock.mockRejectedValue({ status: 404, message: '专业不存在' })
    const view = renderPage()
    expect(await screen.findByText('专业详情不存在或不在当前范围')).toBeInTheDocument()

    view.unmount()
    majorDetailMock.mockClear()
    renderPage('/kaoyan/majors/11?school_id=1&major_id=12&subject_id=101')
    expect(await screen.findByText('链接中的 major_id 与专业路径不一致')).toBeInTheDocument()
    expect(majorDetailMock).not.toHaveBeenCalled()
  })

  it('登录用户变化会重新请求，不复用访客资源响应', async () => {
    const view = renderPage()
    await screen.findByText('高等数学')

    authState.user = { id: 2 }
    majorDetailMock.mockResolvedValueOnce({ ...DETAIL, resource_pack: { status: 'ready', total: 0, items: [] } })
    view.rerender(
      <MemoryRouter initialEntries={['/kaoyan/majors/11?school_id=1&major_id=11&subject_id=101']}>
        <Routes><Route path="/kaoyan/majors/:id" element={<KaoyanMajorDetail />} /></Routes>
        <LocationProbe />
      </MemoryRouter>,
    )

    await waitFor(() => expect(majorDetailMock).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('该科目暂无专业级教材或资源')).toBeInTheDocument()
    expect(screen.queryByText('高等数学')).not.toBeInTheDocument()
  })
})

describe('专业深链纯函数', () => {
  it('构造保留实体 ID 的专业页与练习页', () => {
    expect(buildMajorDetailPath({ majorId: 11, schoolId: 1, subjectId: 102 }))
      .toBe('/kaoyan/majors/11?school_id=1&major_id=11&subject_id=102')
    expect(buildMajorPracticePath({ majorId: 11, schoolId: 1, subjectId: 102 }))
      .toBe('/quiz?tab=engineering08&school_id=1&major_id=11&subject_id=102')
    expect(buildMajorPracticePath({ majorId: 11, schoolId: 1, subjectId: '' })).toBe('')
  })

  it('只允许 http/https 外链', () => {
    expect(safeExternalUrl('https://example.edu/a')).toBe('https://example.edu/a')
    expect(safeExternalUrl('javascript:alert(1)')).toBe('')
    expect(safeExternalUrl('/relative')).toBe('')
  })
})
