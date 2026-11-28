import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { engineering08Api, fetchAllPages } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Empty, Field, LoadingState, Select } from '../ui'
import { TYPE_LABELS, normQ } from './quizShared'
import '../styles/engineering08-practice.css'

const EMPTY_CATALOG = { disciplines: [], schools: [], majors: [], subjects: [] }
const SOURCE_OPTIONS = [
  { value: 'past_exam', label: '历年真题' },
  { value: 'textbook', label: '教材' },
  { value: 'chapter_exercise', label: '章节习题' },
  { value: 'mock_exam', label: '模拟题' },
  { value: 'ai_generated', label: 'AI 生成' },
  { value: 'user_created', label: '用户自建' },
  { value: 'external_import', label: '外部导入' },
]
const DIFFICULTY_OPTIONS = [
  { value: '1', label: '难度 1 · 最简单' },
  { value: '2', label: '难度 2 · 较易' },
  { value: '3', label: '难度 3 · 中等' },
  { value: '4', label: '难度 4 · 较难' },
  { value: '5', label: '难度 5 · 最难' },
]
const YEAR_OPTIONS = Array.from({ length: new Date().getFullYear() - 1900 + 1 }, (_, index) => {
  const year = new Date().getFullYear() - index
  return { value: String(year), label: String(year) }
})

function positiveId(value) {
  return /^\d+$/.test(value || '') && Number(value) > 0 ? Number(value) : ''
}

function querySelection(params) {
  return {
    school_id: positiveId(params.get('school_id')),
    major_id: positiveId(params.get('major_id')),
    subject_id: positiveId(params.get('subject_id')),
  }
}

export function subjectsForMajor(major, catalog) {
  if (!major) return []
  const subjects = catalog?.subjects || []
  // 新目录必须提供 major_subjects 才能建立专业—科目约束；旧目录仅做兼容。
  if (!Array.isArray(catalog?.major_subjects)) return subjects
  const allowed = new Set(catalog.major_subjects
    .filter((row) => row.major_id === major.id)
    .map((row) => Number(row.subject_id)))
  return subjects.filter((row) => allowed.has(Number(row.id)))
}

function normalizeSelection(raw, catalog) {
  const school = catalog.schools.find((row) => row.id === positiveId(raw?.school_id)) || null
  const major = school && catalog.majors.find((row) => row.id === positiveId(raw?.major_id) && row.school_id === school.id) || null
  const subject = subjectsForMajor(major, catalog).find((row) => row.id === positiveId(raw?.subject_id)) || null
  return {
    school_id: school?.id || '',
    major_id: major?.id || '',
    subject_id: subject?.id || '',
  }
}

function readStoredSelection(ownerKey) {
  try {
    const raw = window.localStorage.getItem(`engineering08_learning_space:${ownerKey}`)
    const value = raw ? JSON.parse(raw) : null
    return value && typeof value === 'object' ? value : {}
  } catch {
    return {}
  }
}

function storeSelection(ownerKey, selection) {
  try {
    const key = `engineering08_learning_space:${ownerKey}`
    if (Object.values(selection).some(Boolean)) window.localStorage.setItem(key, JSON.stringify(selection))
    else window.localStorage.removeItem(key)
  } catch {
    // 隐私模式或存储被禁用时，URL 仍是当前会话的可靠状态源。
  }
}

export default function Engineering08Practice({ visible, mode, onBeginSession }) {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const ownerKey = user?.id == null ? 'anonymous' : String(user.id)
  const [catalogState, setCatalogState] = useState({ ownerKey: null, data: null })
  const [catalogError, setCatalogError] = useState('')
  const [reloadToken, setReloadToken] = useState(0)
  const [hydratedOwner, setHydratedOwner] = useState(null)
  const initializedOwnerRef = useRef(null)
  const [editing, setEditing] = useState(() => !(
    searchParams.get('school_id') && searchParams.get('major_id') && searchParams.get('subject_id')
  ))
  const [resultState, setResultState] = useState(null)
  const [resultReloadToken, setResultReloadToken] = useState(0)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState('')
  const resultRequestRef = useRef(0)
  const startOperationRef = useRef(0)
  const startContextRef = useRef(null)
  const catalog = catalogState.ownerKey === ownerKey ? catalogState.data : null
  const selection = querySelection(searchParams)
  const facets = {
    subject_id: selection.subject_id,
    year: /^\d{4}$/.test(searchParams.get('year') || '') ? searchParams.get('year') : '',
    question_type: TYPE_LABELS[searchParams.get('question_type')] ? searchParams.get('question_type') : '',
    source_kind: SOURCE_OPTIONS.some((option) => option.value === searchParams.get('source_kind'))
      ? searchParams.get('source_kind')
      : '',
    difficulty: DIFFICULTY_OPTIONS.some((option) => option.value === searchParams.get('difficulty'))
      ? searchParams.get('difficulty')
      : '',
  }

  useEffect(() => {
    if (!visible) return undefined
    let alive = true
    setCatalogState({ ownerKey, data: null })
    setCatalogError('')
    engineering08Api.catalog()
      .then((data) => {
        if (alive) setCatalogState({ ownerKey, data: { ...EMPTY_CATALOG, ...data } })
      })
      .catch((error) => {
        if (alive) setCatalogError(error?.message || '学习空间目录加载失败')
      })
    return () => { alive = false }
  }, [visible, ownerKey, reloadToken])

  const school = catalog?.schools.find((row) => row.id === selection.school_id) || null
  const major = school && catalog?.majors.find((row) => row.id === selection.major_id && row.school_id === school.id) || null
  const subjectOptions = useMemo(() => (
    major ? subjectsForMajor(major, catalog) : (catalog?.subjects || [])
  ), [catalog, major])
  const subject = subjectOptions.find((row) => row.id === selection.subject_id) || null
  const complete = !!(school && major && subject)
  const summary = complete
    ? `${school.name} · ${major.code} ${major.name} · ${subject.short_name || subject.name}`
    : '工科08 · 选择院校/专业'
  const pageNumber = Math.max(1, Number.parseInt(searchParams.get('page') || '1', 10) || 1)
  const requestParams = useMemo(() => ({
    school_id: school?.id,
    major_id: major?.id,
    subject_id: subject?.id,
    year: facets.year ? Number(facets.year) : undefined,
    question_type: facets.question_type || undefined,
    source_kind: facets.source_kind || undefined,
    difficulty: facets.difficulty ? Number(facets.difficulty) : undefined,
    page: pageNumber,
    page_size: 20,
  }), [
    school?.id, major?.id, subject?.id, facets.year, facets.question_type,
    facets.source_kind, facets.difficulty, pageNumber,
  ])
  const requestKey = JSON.stringify({ ownerKey, ...requestParams })
  startContextRef.current = { key: requestKey, ownerKey }

  const updateQuery = useCallback((patch, clear = []) => {
    setSearchParams((previous) => {
      const params = new URLSearchParams(previous)
      for (const key of clear) params.delete(key)
      for (const [key, value] of Object.entries(patch)) {
        if (value === '' || value == null) params.delete(key)
        else params.set(key, String(value))
      }
      return params
    }, { replace: true })
  }, [setSearchParams])

  useEffect(() => {
    if (!catalog || initializedOwnerRef.current === ownerKey) return
    const switchingUser = initializedOwnerRef.current != null
    initializedOwnerRef.current = ownerKey
    const hasLearningUrl = searchParams.get('school_id') || searchParams.get('major_id')
    let raw = selection
    if (switchingUser || !hasLearningUrl) {
      const stored = readStoredSelection(ownerKey)
      raw = {
        ...stored,
        ...(!switchingUser && searchParams.get('subject_id')
          ? { subject_id: positiveId(searchParams.get('subject_id')) }
          : {}),
      }
    }
    const next = normalizeSelection(raw, catalog)
    updateQuery(next)
    setEditing(!(next.school_id && next.major_id && next.subject_id))
    setHydratedOwner(ownerKey)
  }, [catalog, ownerKey, searchParams, selection, updateQuery])

  useEffect(() => {
    if (!catalog || hydratedOwner !== ownerKey) return
    storeSelection(ownerKey, normalizeSelection(selection, catalog))
  }, [catalog, hydratedOwner, ownerKey, selection])

  useEffect(() => {
    if (!visible || !complete) return undefined
    const controller = new AbortController()
    const requestId = ++resultRequestRef.current
    setResultState((previous) => previous?.key === requestKey
      ? { ...previous, loading: true, error: '' }
      : { key: requestKey, items: [], total: 0, totalPages: 1, loading: true, error: '' })
    engineering08Api.questions(requestParams, { signal: controller.signal })
      .then((response) => {
        if (requestId !== resultRequestRef.current) return
        const items = Array.isArray(response?.items) ? response.items : []
        setResultState({
          key: requestKey,
          items,
          total: Number.isFinite(response?.total) ? response.total : items.length,
          totalPages: Math.max(1, Number(response?.total_pages) || 1),
          loading: false,
          error: '',
        })
      })
      .catch((error) => {
        if (requestId !== resultRequestRef.current || error?.name === 'AbortError') return
        setResultState({
          key: requestKey,
          items: [],
          total: 0,
          totalPages: 1,
          loading: false,
          error: error?.message || '题目加载失败',
        })
      })
    return () => {
      controller.abort()
      if (requestId === resultRequestRef.current) resultRequestRef.current += 1
    }
  }, [
    visible, complete, requestKey, resultReloadToken, ownerKey, requestParams,
  ])

  useEffect(() => {
    startOperationRef.current += 1
    setStarting(false)
    setStartError('')
  }, [requestKey])

  const selectSchool = (value) => {
    updateQuery({ school_id: positiveId(value), page: '' }, ['major_id', 'subject_id'])
    setEditing(true)
  }
  const selectMajor = (value) => {
    updateQuery({ major_id: positiveId(value), page: '' }, ['subject_id'])
    setEditing(true)
  }
  const selectSubject = (value) => {
    updateQuery({ subject_id: positiveId(value), page: '' })
    if (school && major && value) setEditing(false)
  }
  const clearSelection = () => {
    updateQuery({ page: '' }, ['school_id', 'major_id', 'subject_id'])
    setEditing(true)
  }
  const selectFacet = (key, value) => updateQuery({ [key]: value, page: '' })

  const beginPractice = async () => {
    if (!complete || starting) return
    const context = { key: requestKey, ownerKey }
    const operation = ++startOperationRef.current
    const snapshot = { ...requestParams, page: 1, page_size: 20 }
    const title = `工科08 · ${school.name} · ${subject.name} 练习`
    setStarting(true)
    setStartError('')
    try {
      const rows = await fetchAllPages(
        (pagination) => engineering08Api.questions({ ...snapshot, ...pagination }),
        { pageSize: 20, maxItems: Number.MAX_SAFE_INTEGER, keys: ['items', 'questions'] },
      )
      if (startContextRef.current?.key !== context.key || startContextRef.current?.ownerKey !== context.ownerKey) return
      const seen = new Set()
      const questions = rows
        .filter((question) => /^\d+$/.test(String(question?.id ?? '')) && Number(question.id) > 0)
        .filter((question) => {
          const id = String(question.id)
          if (seen.has(id)) return false
          seen.add(id)
          return true
        })
        .map(normQ)
      if (!questions.length) {
        setStartError('当前筛选下没有可开始练习的题目')
        return
      }
      const basis = {
        kind: 'engineering08',
        engineering08: true,
        school_id: school.id,
        major_id: major.id,
        subject_id: subject.id,
        facets: {
          subject_id: subject.id,
          ...(facets.year ? { year: Number(facets.year) } : {}),
          ...(facets.question_type ? { question_type: facets.question_type } : {}),
          ...(facets.source_kind ? { source_kind: facets.source_kind } : {}),
          ...(facets.difficulty ? { difficulty: Number(facets.difficulty) } : {}),
        },
        question_count: questions.length,
        all_pages_fetched: true,
      }
      await onBeginSession(title, questions, mode || 'practice', 0, false, basis)
    } catch (error) {
      if (startContextRef.current?.key === context.key && startContextRef.current?.ownerKey === context.ownerKey) {
        setStartError(error?.message || '练习创建失败，请重试')
      }
    } finally {
      if (operation === startOperationRef.current) setStarting(false)
    }
  }

  const majorOptions = useMemo(() => (school
    ? catalog.majors.filter((row) => row.school_id === school.id)
    : []), [catalog, school])
  const majorDetailParams = new URLSearchParams({
    school_id: String(school?.id || ''),
    major_id: String(major?.id || ''),
  })
  if (subject?.id) majorDetailParams.set('subject_id', String(subject.id))
  const majorDetailPath = major?.id ? `/kaoyan/majors/${major.id}?${majorDetailParams}` : ''

  if (!visible) return null
  const currentResult = resultState?.key === requestKey ? resultState : null

  return (
    <section className="e08-practice" aria-label="工科08学习空间">
      <header className="e08-spacebar">
        <div className="e08-spacebar__identity">
          <span className="e08-spacebar__eyebrow">ENGINEERING 08</span>
          <strong aria-live="polite">{summary}</strong>
        </div>
        <div className="e08-spacebar__actions">
          {complete && !editing ? (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>切换</Button>
          ) : null}
          {complete ? (
            <Link className="v3-btn v3-btn--ghost v3-btn--sm" to={majorDetailPath}>专业详情</Link>
          ) : null}
          {complete ? (
            <Button size="sm" variant="ghost" onClick={clearSelection}>清空</Button>
          ) : null}
        </div>
        {(editing || !complete) && (
          <div className="e08-spacebar__selectors">
            <Field label="院校">
              <Select
                aria-label="院校"
                value={school?.id ? String(school.id) : ''}
                onChange={(event) => selectSchool(event.target.value)}
                options={[
                  { value: '', label: '选择院校' },
                  ...(catalog?.schools || []).map((row) => ({ value: String(row.id), label: row.name })),
                ]}
              />
            </Field>
            <Field label="专业">
              <Select
                aria-label="专业"
                value={major?.id ? String(major.id) : ''}
                onChange={(event) => selectMajor(event.target.value)}
                disabled={!school}
                options={[
                  { value: '', label: school ? '选择专业' : '请先选择院校' },
                  ...majorOptions.map((row) => ({ value: String(row.id), label: `${row.code} ${row.name}` })),
                ]}
              />
            </Field>
            <Field label="考试科目">
              <Select
                aria-label="考试科目"
                value={subject?.id ? String(subject.id) : ''}
                onChange={(event) => selectSubject(event.target.value)}
                disabled={!major}
                options={[
                  { value: '', label: major ? '选择考试科目' : '请先选择专业' },
                  ...(subjectOptions.map((row) => ({
                    value: String(row.id),
                    label: row.short_name ? `${row.name}（${row.short_name}）` : row.name,
                  }))),
                ]}
              />
            </Field>
          </div>
        )}
      </header>

      {!catalog && !catalogError ? <LoadingState text="正在加载工科08学习空间…" /> : null}
      {catalogError ? (
        <Card>
          <Empty
            title="学习空间目录加载失败"
            text={catalogError}
            action={<Button onClick={() => setReloadToken((value) => value + 1)}>重试</Button>}
          />
        </Card>
      ) : null}

      {catalog && (
        <>
          <Card className="e08-filters">
            <div className="e08-filters__head">
              <div>
                <h2>同屏筛选</h2>
                <p>五个筛选轴同时生效，结果数量随筛选实时更新。</p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => updateQuery({}, ['year', 'question_type', 'source_kind', 'difficulty'])}>
                重置筛选
              </Button>
            </div>
            <div className="e08-filters__grid">
              <Field label="科目">
                <Select
                  aria-label="科目"
                  value={facets.subject_id ? String(facets.subject_id) : ''}
                  onChange={(event) => selectFacet('subject_id', event.target.value)}
                  options={[
                    { value: '', label: '全部科目' },
                    ...subjectOptions.map((row) => ({ value: String(row.id), label: row.name })),
                  ]}
                />
              </Field>
              <Field label="年份">
                <Select
                  aria-label="年份"
                  value={facets.year}
                  onChange={(event) => selectFacet('year', event.target.value)}
                  options={[{ value: '', label: '全部年份' }, ...YEAR_OPTIONS]}
                />
              </Field>
              <Field label="题型">
                <Select
                  aria-label="题型"
                  value={facets.question_type}
                  onChange={(event) => selectFacet('question_type', event.target.value)}
                  options={[{ value: '', label: '全部题型' }, ...Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }))]}
                />
              </Field>
              <Field label="来源">
                <Select
                  aria-label="来源"
                  value={facets.source_kind}
                  onChange={(event) => selectFacet('source_kind', event.target.value)}
                  options={[{ value: '', label: '全部来源' }, ...SOURCE_OPTIONS]}
                />
              </Field>
              <Field label="难度">
                <Select
                  aria-label="难度"
                  value={facets.difficulty}
                  onChange={(event) => selectFacet('difficulty', event.target.value)}
                  options={[{ value: '', label: '全部难度' }, ...DIFFICULTY_OPTIONS]}
                />
              </Field>
            </div>
          </Card>
          <Card className="e08-results">
            <div className="e08-results__head">
              <div>
                <h2>题目结果</h2>
                <p aria-live="polite">
                  {complete && currentResult && !currentResult.loading && !currentResult.error
                    ? `共 ${currentResult.total} 道题`
                    : complete ? '正在更新当前筛选结果…' : '完成学习空间选择后显示题目'}
                </p>
              </div>
              <div className="e08-results__actions">
                <Button
                  onClick={beginPractice}
                  loading={starting}
                  disabled={!currentResult || currentResult.loading || !!currentResult.error || currentResult.items.length === 0 || starting}
                >
                  开始练习
                </Button>
                {currentResult && !currentResult.loading && currentResult.totalPages > 1 ? (
                  <div className="e08-results__pagination">
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={pageNumber <= 1}
                      onClick={() => updateQuery({ page: pageNumber - 1 > 1 ? pageNumber - 1 : '' })}
                    >
                      上一页
                    </Button>
                    <span>{pageNumber} / {currentResult.totalPages}</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={pageNumber >= currentResult.totalPages}
                      onClick={() => updateQuery({ page: pageNumber + 1 })}
                    >
                      下一页
                    </Button>
                  </div>
                ) : null}
              </div>
            </div>
            {startError ? <p className="e08-results__error" role="alert">{startError}</p> : null}
            {!complete ? (
              <Empty title="请先完成学习空间选择" text="题目范围由院校、专业和考试科目共同确定。" />
            ) : !currentResult || currentResult.loading ? (
              <LoadingState text="正在加载题目…" />
            ) : currentResult.error ? (
              <Empty
                title="题目加载失败"
                text={currentResult.error}
                action={<Button onClick={() => setResultReloadToken((value) => value + 1)}>重试</Button>}
              />
            ) : currentResult.items.length === 0 ? (
              <Empty title="没有符合条件的题目" text="请调整年份、题型、来源或难度后重试。" />
            ) : (
              <ul className="e08-results__list" aria-label="工科08题目结果">
                {currentResult.items.map((question) => {
                  const questionSubject = catalog.subjects.find((row) => row.id === question.subject_id)
                  const sourceKind = SOURCE_OPTIONS.find((option) => option.value === question.source_kind)
                  const difficulty = DIFFICULTY_OPTIONS.find((option) => option.value === String(question.difficulty))
                  return (
                    <li key={question.id} className="e08-result-row">
                      <p className="e08-result-row__stem">{question.content || '题干暂不可用'}</p>
                      <div className="e08-result-row__meta">
                        <span>{questionSubject?.name || question.subject || '科目未知'}</span>
                        <span>{question.year || '年份未知'}</span>
                        <span>{TYPE_LABELS[question.question_type] || question.question_type || '题型未知'}</span>
                        <span>{sourceKind?.label || question.source || question.source_kind || '来源未知'}</span>
                        <span>{difficulty?.label || `难度 ${question.difficulty ?? '未知'}`}</span>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </Card>
        </>
      )}
    </section>
  )
}
