import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { personalQuestionBankApi, quizApi } from '../../api/client'
import { ROUTE_META } from '../../nav/navConfig'
import {
  Button,
  Card,
  Dialog,
  Empty,
  Field,
  IconButton,
  Input,
  LoadingState,
  PageHeader,
  Pager,
  Select,
  Textarea,
  useConfirm,
} from '../ui'
import {
  BookOpen,
  Check,
  ChevronLeft,
  Edit,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash,
} from '../icons'
import QuizPractice from './QuizPractice'
import { TYPE_LABELS } from './quizShared'
import '../styles/personal-question-bank.css'

const PAGE_META = ROUTE_META['/personal-question-bank']
const EMPTY_FILTERS = { subject: '', chapter: '', question_type: '', mastery: '' }
const PAGE_SIZE = 20
const CHOICE_TYPES = ['single', 'multiple', 'judge']

function itemsOf(data) {
  if (Array.isArray(data)) return data
  return data?.items || data?.questions || data?.sets || []
}

function questionPageOf(data) {
  return {
    items: itemsOf(data),
    total: Number(data?.total ?? data?.total_count ?? itemsOf(data).length),
    page: Number(data?.page || 1),
    page_size: Number(data?.page_size || PAGE_SIZE),
    summary: data?.summary || null,
  }
}

function errorText(error, fallback) {
  if (error?.status === 403) return error?.message || '无权访问该题库'
  return error?.message || fallback
}

function optionLines(options) {
  if (!Array.isArray(options)) return ''
  return options.map((option) => {
    const text = typeof option === 'string' ? option : (option?.text ?? option?.label ?? '')
    return String(text)
  }).join('\n')
}

function normalizeOptions(text) {
  return text.split(/\r?\n/)
    .map((line) => line.trim().replace(/^\s*[（(]?\s*[A-Ha-h]\s*[）).、．:：]\s*/, '').trim())
    .filter(Boolean)
}

function optionPreview(options) {
  if (!Array.isArray(options) || !options.length) return ''
  return options.map((option, index) => {
    const text = typeof option === 'string' ? option : (option?.text ?? option?.label ?? '')
    return `${String.fromCharCode(65 + index)}. ${String(text).replace(/^\s*[A-Ha-h][.、．:：]\s*/, '')}`
  }).join('  ')
}

function isPersonalQuestion(question) {
  return question?.is_personal === true
    || question?.personal === true
    || question?.is_own === true
    || question?.source_kind === 'personal'
    || question?.source_kind === 'custom'
    || question?.source_kind === 'user_created'
    || question?.source === 'personal'
    || question?.origin === 'personal'
    || question?.owner_id != null
    || (!question?.source_kind && !question?.source)
}

function practiceQuestion(question) {
  const {
    answer: _answer,
    analysis: _analysis,
    correct_answer: _correctAnswer,
    reference_answer: _referenceAnswer,
    ...safe
  } = question
  return {
    ...safe,
    id: String(question.id),
    content: question.content || '',
    options: Array.isArray(question.options) ? question.options : [],
    question_type: question.question_type || (Array.isArray(question.options) && question.options.length ? 'single' : 'essay'),
  }
}

function practiceRecord(record) {
  if (!record) return record
  return {
    ...record,
    selected: record.selected ?? record.my_answer ?? '',
    correctAnswer: record.correctAnswer ?? record.correct_answer ?? '',
    analysis: record.analysis ?? '',
    needsReview: record.needsReview ?? record.needs_review ?? record.correct === null,
    syncStatus: record.syncStatus ?? 'synced',
    syncError: record.syncError ?? '',
  }
}

function newQuestionDraft() {
  return {
    content: '',
    question_type: 'single',
    optionsText: '',
    answer: '',
    analysis: '',
    subject: '',
    chapter: '',
    difficulty: 3,
  }
}

export default function PersonalQuestionBank() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialRef = useRef({
    bankId: Number(searchParams.get('bankId')) || null,
    sessionId: Number(searchParams.get('sessionId')) || null,
    view: ['bank', 'practice', 'result'].includes(searchParams.get('view'))
      ? searchParams.get('view')
      : 'list',
  })
  const [view, setView] = useState(initialRef.current.view)
  const [activeBankId, setActiveBankId] = useState(initialRef.current.bankId)
  const activeBankIdRef = useRef(initialRef.current.bankId)
  activeBankIdRef.current = activeBankId
  const [sets, setSets] = useState([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [initialError, setInitialError] = useState('')
  const [questionPage, setQuestionPage] = useState({ items: [], total: 0, page: 1, page_size: PAGE_SIZE, summary: null })
  const [knownQuestions, setKnownQuestions] = useState([])
  const [assetSummary, setAssetSummary] = useState(null)
  const [bankLoaded, setBankLoaded] = useState(false)
  const [questionLoading, setQuestionLoading] = useState(false)
  const [questionError, setQuestionError] = useState('')
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [successMessage, setSuccessMessage] = useState('')
  const [setDialog, setSetDialog] = useState(null)
  const [setSaving, setSetSaving] = useState(false)
  const [setError, setSetError] = useState('')
  const [questionDialog, setQuestionDialog] = useState(null)
  const [questionDraft, setQuestionDraft] = useState(newQuestionDraft)
  const [questionSaving, setQuestionSaving] = useState(false)
  const [questionDialogError, setQuestionDialogError] = useState('')
  const [masteryBusy, setMasteryBusy] = useState(null)
  const [publicOpen, setPublicOpen] = useState(false)
  const [publicBankId, setPublicBankId] = useState(null)
  const [publicFilters, setPublicFilters] = useState(EMPTY_FILTERS)
  const [publicKeyword, setPublicKeyword] = useState('')
  const [publicPage, setPublicPage] = useState({ items: [], total: 0, page: 1, page_size: 10 })
  const [publicLoading, setPublicLoading] = useState(false)
  const [publicError, setPublicError] = useState('')
  const [publicBusy, setPublicBusy] = useState(null)
  const [practiceLoading, setPracticeLoading] = useState(false)
  const [practiceError, setPracticeError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [practiceSession, setPracticeSession] = useState(null)
  const [records, setRecords] = useState({})
  const questionRequest = useRef(0)
  const publicRequest = useRef(0)
  const practiceRequest = useRef(0)
  const attemptIdsRef = useRef({})
  const attemptSessionRef = useRef(null)
  const [confirm, confirmDialog] = useConfirm()

  const activeBank = sets.find((set) => String(set.id) === String(activeBankId)) || null
  const allQuestions = questionPage.items
  const localBankQuestions = activeBankId && !bankLoaded
    ? allQuestions.filter((question) => {
      const bankIds = Array.isArray(question.bank_ids) && question.bank_ids.length
        ? question.bank_ids
        : [question.bank_id]
      return bankIds.some((id) => String(id) === String(activeBankId))
    })
    : allQuestions
  const localPage = Number(filters.page || 1)
  const visibleQuestions = activeBankId && !bankLoaded
    ? localBankQuestions.slice((localPage - 1) * PAGE_SIZE, localPage * PAGE_SIZE)
    : allQuestions
  const visibleTotal = activeBankId && !bankLoaded
    ? Number(activeBank?.question_count ?? localBankQuestions.length)
    : questionPage.total
  const initialEmpty = !sets.length && Number(assetSummary?.total ?? questionPage.total) === 0 && !activeBankId
  const subjects = [...new Set(knownQuestions.map((question) => question?.subject).filter(Boolean))]
  const chapters = [...new Set(knownQuestions.map((question) => question?.chapter).filter(Boolean))]

  function syncUrl(nextView, bankId = activeBankId, sessionId = null) {
    const params = new URLSearchParams()
    if (bankId) params.set('bankId', String(bankId))
    if (nextView !== 'list') params.set('view', nextView)
    if (sessionId) params.set('sessionId', String(sessionId))
    setSearchParams(params, { replace: true })
  }

  function showView(nextView, bankId = activeBankId, sessionId = null) {
    activeBankIdRef.current = bankId
    setView(nextView)
    setActiveBankId(bankId)
    setSuccessMessage('')
    syncUrl(nextView, bankId, sessionId)
  }

  function applyPracticeSession(data) {
    const sessionId = Number(data.session_id) || null
    if (attemptSessionRef.current !== sessionId) {
      attemptIdsRef.current = {}
      attemptSessionRef.current = sessionId
    }
    const items = itemsOf(data).map(practiceQuestion)
    const restoredRecords = Object.fromEntries(
      Object.entries(data.records || {}).map(([id, record]) => [id, practiceRecord(record)]),
    )
    setRecords(restoredRecords)
    setPracticeSession({
      ...data,
      questions: items,
      startIdx: Number(data.current_index) || 0,
    })
    return items.length
  }

  function backToBank() {
    practiceRequest.current += 1
    setPracticeLoading(false)
    setPracticeError('')
    setPracticeSession(null)
    setRecords({})
    attemptIdsRef.current = {}
    attemptSessionRef.current = null
    showView('bank')
    void Promise.all([
      fetchQuestions({ page: 1 }),
      personalQuestionBankApi.sets().then((data) => setSets(itemsOf(data))),
    ])
  }

  async function restorePractice(sessionId, bankId = activeBankId, updateUrl = true, resultView = false) {
    const requestId = ++practiceRequest.current
    activeBankIdRef.current = bankId
    setView('practice')
    setActiveBankId(bankId)
    setPracticeLoading(true)
    setPracticeError('')
    setSubmitting(false)
    setPracticeSession(null)
    setRecords({})
    setSuccessMessage('')
    if (updateUrl) syncUrl('practice', bankId, sessionId)
    try {
      const data = await quizApi.getSession(sessionId)
      if (requestId !== practiceRequest.current) return
      if (data?.basis?.kind !== 'personal_question_bank') {
        throw Object.assign(new Error('该会话不是个人题库练习'), { status: 404 })
      }
      const sessionBankId = Number(data.basis?.bank_id) || null
      const sessionBankKey = sessionBankId == null ? '' : String(sessionBankId)
      const requestedBankKey = bankId == null ? '' : String(bankId)
      if (sessionBankKey !== requestedBankKey) {
        throw Object.assign(new Error('会话与题库不匹配'), { status: 404 })
      }
      applyPracticeSession(data)
      if (data.status === 'completed' || resultView) showView('result', sessionBankId, sessionId)
      else if (updateUrl) syncUrl('practice', sessionBankId, sessionId)
    } catch (error) {
      if (requestId !== practiceRequest.current) return
      setPracticeError(errorText(error, '练习会话恢复失败，请重试'))
    } finally {
      if (requestId === practiceRequest.current) setPracticeLoading(false)
    }
  }

  async function beginPractice(bankId = activeBankId, updateUrl = true) {
    const requestId = ++practiceRequest.current
    activeBankIdRef.current = bankId
    setView('practice')
    setActiveBankId(bankId)
    setPracticeLoading(true)
    setPracticeError('')
    setSubmitting(false)
    setRecords({})
    setPracticeSession(null)
    setSuccessMessage('')
    if (updateUrl) syncUrl('practice', bankId)
    try {
      const params = {}
      if (bankId) params.bank_id = bankId
      if (filters.subject) params.subject = filters.subject
      if (filters.chapter) params.chapter = filters.chapter
      if (filters.question_type) params.question_type = filters.question_type
      if (filters.mastery) params.mastery_state = filters.mastery
      const data = await personalQuestionBankApi.createPracticeSession(params)
      if (requestId !== practiceRequest.current) return
      applyPracticeSession(data)
      syncUrl('practice', bankId, data.session_id)
    } catch (error) {
      if (requestId !== practiceRequest.current) return
      setPracticeError(errorText(error, '练习题加载失败，请重试'))
    } finally {
      if (requestId === practiceRequest.current) setPracticeLoading(false)
    }
  }

  function submitPersonalAnswer(body) {
    const sessionId = Number(practiceSession?.session_id) || null
    if (!sessionId) return Promise.reject(new Error('练习会话尚未创建，请返回后重试'))
    if (attemptSessionRef.current !== sessionId) {
      attemptIdsRef.current = {}
      attemptSessionRef.current = sessionId
    }
    const questionId = String(body.question_id)
    if (!attemptIdsRef.current[questionId]) {
      attemptIdsRef.current[questionId] = globalThis.crypto?.randomUUID?.()
        || `${sessionId}-${questionId}-${Date.now()}-${Math.random().toString(36).slice(2)}`
    }
    return personalQuestionBankApi.submit({
      ...body,
      session_id: sessionId,
      client_attempt_id: attemptIdsRef.current[questionId],
      mode: 'personal',
    })
  }

  async function fetchQuestions({
    bankId = activeBankId,
    nextFilters = filters,
    page = nextFilters.page || 1,
    pageSize = PAGE_SIZE,
  } = {}) {
    const requestId = ++questionRequest.current
    const params = { bank_id: bankId ?? undefined, page, page_size: pageSize }
    if (nextFilters.subject) params.subject = nextFilters.subject
    if (nextFilters.chapter) params.chapter = nextFilters.chapter
    if (nextFilters.question_type) params.question_type = nextFilters.question_type
    if (nextFilters.mastery) {
      params.mastery = nextFilters.mastery
      params.mastery_state = nextFilters.mastery
    }
    setQuestionLoading(true)
    setQuestionError('')
    try {
      const data = await personalQuestionBankApi.questions(params)
      if (requestId !== questionRequest.current) return
      if (String(activeBankIdRef.current ?? '') !== String(bankId ?? '')) return
      const nextPage = questionPageOf(data)
      setQuestionPage(nextPage)
      setKnownQuestions((current) => {
        const merged = new Map(current.map((question) => [String(question.id), question]))
        nextPage.items.forEach((question) => merged.set(String(question.id), question))
        return [...merged.values()]
      })
      setAssetSummary(nextPage.summary)
      setBankLoaded(true)
    } catch (error) {
      if (requestId !== questionRequest.current) return
      if (String(activeBankIdRef.current ?? '') !== String(bankId ?? '')) return
      setQuestionError(errorText(error, '题目加载失败，请重试'))
    } finally {
      if (requestId === questionRequest.current
        && String(activeBankIdRef.current ?? '') === String(bankId ?? '')) {
        setQuestionLoading(false)
      }
    }
  }

  async function loadInitial() {
    questionRequest.current += 1
    practiceRequest.current += 1
    setQuestionLoading(false)
    setInitialLoading(true)
    setInitialError('')
    try {
      const [setsData, firstQuestions] = await Promise.all([
        personalQuestionBankApi.sets(),
        personalQuestionBankApi.questions({ page: 1, page_size: PAGE_SIZE }),
      ])
      const nextPage = questionPageOf(firstQuestions)
      const nextSets = itemsOf(setsData)
      setSets(nextSets)
      setQuestionPage(nextPage)
      setKnownQuestions(nextPage.items)
      setAssetSummary(nextPage.summary)
      const deepBank = initialRef.current.bankId
      const deepSession = initialRef.current.sessionId
      if (deepBank) {
        await fetchQuestions({ bankId: deepBank, nextFilters: EMPTY_FILTERS, page: 1 })
      }
      if (deepSession && (initialRef.current.view === 'practice' || initialRef.current.view === 'result')) {
        await restorePractice(deepSession, deepBank, false, initialRef.current.view === 'result')
      } else if (initialRef.current.view === 'practice') {
        await beginPractice(deepBank, false)
      } else if (initialRef.current.view === 'result') {
        const fallbackView = deepBank ? 'bank' : 'list'
        setView(fallbackView)
        syncUrl(fallbackView, deepBank)
      }
    } catch (error) {
      setInitialError(errorText(error, '我的题库加载失败，请重试'))
    } finally {
      setInitialLoading(false)
    }
  }

  useEffect(() => {
    void loadInitial()
    // 深链只在首次挂载解析，后续视图切换通过 URL 同步。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function selectBank(bank) {
    setFilters(EMPTY_FILTERS)
    setBankLoaded(false)
    setQuestionError('')
    setQuestionPage({ items: [], total: 0, page: 1, page_size: PAGE_SIZE, summary: null })
    setAssetSummary(null)
    showView('bank', bank.id)
    void fetchQuestions({ bankId: bank.id, nextFilters: EMPTY_FILTERS, page: 1 })
  }

  function openCreateSet() {
    setSetError('')
    setSetSaving(false)
    setSetDialog({ mode: 'create', name: '', description: '' })
  }

  function openEditSet(set) {
    setSetError('')
    setSetSaving(false)
    setSetDialog({ mode: 'edit', id: set.id, name: set.name || '', description: set.description || '' })
  }

  async function saveSet(event) {
    event.preventDefault()
    if (!setDialog || setSaving) return
    const name = setDialog.name.trim()
    if (!name) {
      setSetError('请填写题库名称')
      return
    }
    const body = { name, description: setDialog.description.trim() }
    setSetSaving(true)
    setSetError('')
    try {
      const result = setDialog.mode === 'create'
        ? await personalQuestionBankApi.createSet(body)
        : await personalQuestionBankApi.updateSet(setDialog.id, body)
      setSetDialog(null)
      if (setDialog.mode === 'create') {
        const bankId = result?.id ?? setDialog.id
        setBankLoaded(false)
        showView('bank', bankId)
        setSuccessMessage('题库已创建')
        await loadInitial()
      } else {
        setSuccessMessage('题库已保存')
        const data = await personalQuestionBankApi.sets()
        setSets(itemsOf(data))
      }
    } catch (error) {
      setSetError(errorText(error, '题库保存失败，请重试'))
    } finally {
      setSetSaving(false)
    }
  }

  async function removeSet(set) {
    const ok = await confirm({
      title: '删除题库',
      text: `确定删除「${set.name}」吗？公共题仅移出题库；个人自建题会保留在未分题库题目中，可在题目管理中单独删除。`,
      confirmText: '删除题库',
      danger: true,
    })
    if (!ok) return
    try {
      await personalQuestionBankApi.deleteSet(set.id)
      setBankLoaded(false)
      showView('list', null)
      setSuccessMessage('题库已删除')
      await loadInitial()
    } catch (error) {
      setQuestionError(errorText(error, '题库删除失败，请重试'))
    }
  }

  function openCreateQuestion() {
    setQuestionDialogError('')
    setQuestionSaving(false)
    setQuestionDraft(newQuestionDraft())
    setQuestionDialog({ mode: 'create' })
  }

  function openEditQuestion(question) {
    setQuestionDialogError('')
    setQuestionSaving(false)
    setQuestionDraft({
      content: question.content || '',
      question_type: question.question_type || 'single',
      optionsText: optionLines(question.options),
      answer: question.answer || '',
      analysis: question.analysis || '',
      subject: question.subject || '',
      chapter: question.chapter || '',
      difficulty: Number(question.difficulty) || 3,
    })
    setQuestionDialog({ mode: 'edit', question })
  }

  async function saveQuestion(event) {
    event.preventDefault()
    if (!questionDialog || questionSaving) return
    const content = questionDraft.content.trim()
    if (!content) {
      setQuestionDialogError('请填写题目内容')
      return
    }
    const choice = CHOICE_TYPES.includes(questionDraft.question_type)
    const options = choice ? normalizeOptions(questionDraft.optionsText) : []
    if (choice && !options.length) {
      setQuestionDialogError('请填写选项，每行一个')
      return
    }
    if (!questionDraft.answer.trim()) {
      setQuestionDialogError('请填写标准答案')
      return
    }
    const body = {
      ...(questionDialog.mode === 'create' ? { bank_id: activeBankId ?? null } : {}),
      content,
      question_type: questionDraft.question_type,
      options,
      answer: questionDraft.answer.trim(),
      analysis: questionDraft.analysis.trim(),
      subject: questionDraft.subject.trim(),
      chapter: questionDraft.chapter.trim(),
      difficulty: Number(questionDraft.difficulty) || 1,
    }
    setQuestionSaving(true)
    setQuestionDialogError('')
    try {
      if (questionDialog.mode === 'create') {
        await personalQuestionBankApi.createQuestion(body)
      } else {
        await personalQuestionBankApi.updateQuestion(questionDialog.question.id, body)
      }
      setQuestionDialog(null)
      setSuccessMessage('题目已保存')
      await Promise.all([
        fetchQuestions({ page: 1 }),
        personalQuestionBankApi.sets().then((data) => setSets(itemsOf(data))),
      ])
    } catch (error) {
      setQuestionDialogError(errorText(error, '题目保存失败，请重试'))
    } finally {
      setQuestionSaving(false)
    }
  }

  async function removeQuestion(question) {
    const personal = isPersonalQuestion(question)
    const ok = await confirm({
      title: personal ? '删除题目' : '移出题库',
      text: personal ? '确定软删除这道自建题吗？' : '确定将这道公共题移出当前题库吗？公共题库中的原题不会被删除。',
      confirmText: personal ? '删除题目' : '移出题库',
      danger: true,
    })
    if (!ok) return
    try {
      if (personal) await personalQuestionBankApi.deleteQuestion(question.id)
      else await personalQuestionBankApi.removeQuestion(activeBankId, question.id)
      setSuccessMessage(personal ? '题目已删除' : '题目已移出题库')
      await Promise.all([
        fetchQuestions(),
        personalQuestionBankApi.sets().then((data) => setSets(itemsOf(data))),
      ])
    } catch (error) {
      setQuestionError(errorText(error, '题目移除失败，请重试'))
    }
  }

  async function toggleMastery(question) {
    if (masteryBusy) return
    const state = question.mastery_state === 'mastered' ? 'unmastered' : 'mastered'
    setMasteryBusy(question.id)
    setQuestionError('')
    try {
      await personalQuestionBankApi.setMastery(question.id, state)
      await Promise.all([
        fetchQuestions(),
        personalQuestionBankApi.sets().then((data) => setSets(itemsOf(data))),
      ])
    } catch (error) {
      setQuestionError(errorText(error, '掌握状态更新失败，请重试'))
    } finally {
      setMasteryBusy(null)
    }
  }

  function changeFilter(key, value) {
    const nextFilters = { ...filters, [key]: value, page: 1 }
    setFilters(nextFilters)
    void fetchQuestions({ nextFilters, page: 1 })
  }

  function changePage(page) {
    const nextFilters = { ...filters, page }
    setFilters(nextFilters)
    void fetchQuestions({ nextFilters, page })
  }

  async function loadPublic(next = {}) {
    const requestId = ++publicRequest.current
    const bankId = next.bankId ?? publicBankId
    const nextFilters = next.filters || publicFilters
    const page = next.page || 1
    const params = { page, page_size: 10, public_only: true }
    if (bankId) params.bank_id = bankId
    if (nextFilters.subject) params.subject = nextFilters.subject
    if (nextFilters.chapter) params.chapter = nextFilters.chapter
    if (nextFilters.question_type) params.question_type = nextFilters.question_type
    if (next.keyword?.trim()) params.q = next.keyword.trim()
    setPublicLoading(true)
    setPublicError('')
    try {
      const data = await personalQuestionBankApi.publicQuestions(params)
      if (requestId !== publicRequest.current) return
      setPublicPage({
        items: itemsOf(data),
        total: Number(data?.total ?? itemsOf(data).length),
        page: Number(data?.page || page),
        page_size: Number(data?.page_size || 10),
      })
    } catch (error) {
      if (requestId !== publicRequest.current) return
      setPublicError(errorText(error, '公共题库加载失败，请重试'))
    } finally {
      if (requestId === publicRequest.current) setPublicLoading(false)
    }
  }

  function openPublicPicker() {
    setPublicOpen(true)
    setPublicBankId(activeBankId || sets[0]?.id || null)
    setPublicFilters(EMPTY_FILTERS)
    setPublicKeyword('')
    setPublicError('')
    void loadPublic({ bankId: activeBankId || sets[0]?.id || null, filters: EMPTY_FILTERS, page: 1, keyword: '' })
  }

  async function addPublicQuestion(question) {
    if (!publicBankId || publicBusy) return
    setPublicBusy(question.id)
    setPublicError('')
    try {
      await personalQuestionBankApi.addQuestion(publicBankId, question.id)
      setFilters(EMPTY_FILTERS)
      setBankLoaded(false)
      showView('bank', publicBankId)
      setSuccessMessage('题目已加入题库')
      await Promise.all([
        fetchQuestions({ bankId: publicBankId, nextFilters: EMPTY_FILTERS, page: 1 }),
        personalQuestionBankApi.sets().then((data) => setSets(itemsOf(data))),
      ])
    } catch (error) {
      setPublicError(errorText(error, '加入题库失败，请重试'))
    } finally {
      setPublicBusy(null)
    }
  }

  function updateDraft(key, value) {
    setQuestionDraft((draft) => ({ ...draft, [key]: value }))
  }

  const headerActions = initialEmpty ? null : (
    <>
      <Button variant="tonal" icon={<Plus size={15} />} onClick={openCreateSet}>新建题库</Button>
      <Button variant="tonal" icon={<Edit size={15} />} onClick={openCreateQuestion}>自建题目</Button>
      <Button icon={<BookOpen size={15} />} onClick={openPublicPicker}>去题库选题</Button>
    </>
  )

  const pageHeader = (
    <PageHeader
      eyebrow="练习 / 个人资产"
      title={PAGE_META.h1}
      sub="整理自己的题库，追踪掌握状态，只练习你选中的题目。"
      actions={headerActions}
    />
  )

  if (initialLoading) {
    return (
      <main className="pqb-page">
        {pageHeader}
        <LoadingState text="正在加载我的题库…" />
      </main>
    )
  }

  if (initialError) {
    return (
      <main className="pqb-page">
        {pageHeader}
        <div className="pqb-alert" role="alert">
          <span>{initialError}</span>
          <Button icon={<RefreshCw size={15} />} onClick={() => void loadInitial()}>重试</Button>
        </div>
      </main>
    )
  }

  if (view === 'practice') {
    return (
      <main className="pqb-page pqb-page--practice">
        {pageHeader}
        <div className="pqb-viewbar">
          <Button variant="ghost" icon={<ChevronLeft size={15} />} disabled={submitting} onClick={backToBank}>返回题库</Button>
          <span>{activeBank?.name || '个人题库练习'}</span>
        </div>
        {practiceLoading ? <LoadingState text="正在加载练习题…" /> : null}
        {!practiceLoading && practiceError ? (
          <div className="pqb-alert" role="alert">
            <span>{practiceError}</span>
            <Button onClick={() => {
              const sessionId = Number(searchParams.get('sessionId')) || null
              if (sessionId) void restorePractice(sessionId, activeBankId)
              else void beginPractice()
            }}>重试</Button>
          </div>
        ) : null}
        {!practiceLoading && !practiceError && practiceSession && !practiceSession.questions.length ? (
          <Empty
            title="暂无练习题"
            text="这个题库还没有可练习的题目，请先加入公共题或自建题目。"
            action={<Button onClick={backToBank}>返回题库</Button>}
          />
        ) : null}
        {!practiceLoading && !practiceError && practiceSession?.questions.length ? (
          <QuizPractice
            session={practiceSession}
            records={records}
            basis={null}
            favs={{}}
            kpFilter={null}
            backendOk
            tutorMode="auto"
            setTutorMode={() => {}}
            submitting={submitting}
            setSubmitting={setSubmitting}
            submitAnswer={submitPersonalAnswer}
            manualChoiceSubmit
            showFavorites={false}
            onRecord={(id, record) => setRecords((current) => ({ ...current, [id]: record }))}
            onToggleFav={() => {}}
            onGoHome={backToBank}
            onFinish={() => showView('result', activeBankId, practiceSession?.session_id)}
          />
        ) : null}
      </main>
    )
  }

  if (view === 'result') {
    const submitted = (practiceSession?.questions || [])
      .map((question, index) => ({ question, index, record: records[question.id] }))
      .filter((entry) => entry.record)
    const correctCount = submitted.filter(({ record }) => record.correct === true).length
    return (
      <main className="pqb-page">
        {pageHeader}
        <Card className="pqb-result">
          <div className="pqb-result__head">
            <div>
              <span className="pqb-eyebrow">本次练习报告</span>
              <h2>{activeBank?.name || '个人题库'}</h2>
              <p>仅统计已成功提交的题目，未提交题目不展示答案。</p>
            </div>
            <div className="pqb-result__score">
              <strong>{correctCount}</strong>
              <span>/ {submitted.length} 题正确</span>
            </div>
          </div>
          {!submitted.length ? (
            <Empty title="还没有已提交的题目" text="完成一次练习后，这里会展示真实判分结果。" />
          ) : (
            <div className="pqb-result__list">
              {submitted.map(({ question, index, record }) => {
                const needsReview = record.correct === null || record.needsReview === true
                return (
                  <article key={question.id} className={`pqb-result__item ${needsReview ? 'is-review' : record.correct ? 'is-ok' : 'is-bad'}`}>
                    <div className="pqb-result__label">
                      <span>第 {index + 1} 题</span>
                      <strong>{needsReview ? '待确认' : record.correct ? '回答正确' : '回答错误'}</strong>
                    </div>
                    <p>{question.content || `题目 #${question.id}`}</p>
                    <div>你的答案：{record.selected || '—'}</div>
                    <div>{needsReview ? '参考答案（待核对）' : '答案'}：{record.correctAnswer || '—'}</div>
                    {record.analysis ? <div>解析：{record.analysis}</div> : null}
                  </article>
                )
              })}
            </div>
          )}
          <div className="pqb-row-actions">
            <Button variant="tonal" onClick={backToBank}>返回题库</Button>
            <Button icon={<Play size={15} />} onClick={() => void beginPractice()}>再练一次</Button>
          </div>
        </Card>
      </main>
    )
  }

  return (
    <main className="pqb-page">
      {pageHeader}
      {successMessage ? <div className="pqb-success" role="status">{successMessage}</div> : null}
      <section className="pqb-summary" aria-label="个人资产摘要">
        <Card><span>个人题目</span><strong>{assetSummary?.total ?? '—'}</strong></Card>
        <Card><span>已掌握题目</span><strong>{assetSummary?.mastered ?? '—'}</strong></Card>
        <Card><span>未掌握题目</span><strong>{assetSummary?.unmastered ?? '—'}</strong></Card>
      </section>

      {initialEmpty ? (
        <Card className="pqb-empty-card">
          <Empty
            title="还没有个人题目"
            text="创建自己的题库，或从公共题库主动加入题目。这里不会自动生成示例数据。"
            action={(
              <div className="pqb-row-actions">
                <Button variant="tonal" icon={<Plus size={15} />} onClick={openCreateSet}>新建题库</Button>
                <Button variant="tonal" icon={<Edit size={15} />} onClick={openCreateQuestion}>自建题目</Button>
                <Button icon={<BookOpen size={15} />} onClick={openPublicPicker}>去题库选题</Button>
              </div>
            )}
          />
        </Card>
      ) : (
        <div className="pqb-workspace">
          <aside className="pqb-sidebar" aria-label="我的题库列表">
            <div className="pqb-sidebar__head">
              <div>
                <span className="pqb-eyebrow">题库</span>
                <h2>{sets.length} 个题库</h2>
              </div>
              <IconButton label="新建题库" icon={<Plus size={17} />} onClick={openCreateSet} />
            </div>
            <div className="pqb-bank-list">
              {sets.map((set, index) => (
                <div key={set.id} className={`pqb-bank ${String(activeBankId) === String(set.id) ? 'is-active' : ''}`}>
                  <button type="button" className="pqb-bank__main" onClick={() => selectBank(set)}>
                    <span className="pqb-bank__name">{set.name}</span>
                    {set.description ? <span className="pqb-bank__desc">{set.description}</span> : null}
                    <span className="pqb-bank__meta">
                      {Number(set.question_count) || 0} 题 · 已掌握 {Number(set.mastered_count) || 0} 题
                    </span>
                  </button>
                  <div className="pqb-bank__actions">
                    <IconButton label={`编辑第 ${index + 1} 个题库`} size="sm" icon={<Edit size={14} />} onClick={() => openEditSet(set)} />
                    <IconButton label={`删除第 ${index + 1} 个题库`} size="sm" icon={<Trash size={14} />} onClick={() => void removeSet(set)} />
                  </div>
                </div>
              ))}
              {!sets.length ? <p className="pqb-muted">还没有题库，可先新建题库或自建题目。</p> : null}
            </div>
          </aside>

          <section className="pqb-content" aria-label="题目管理">
            {activeBank ? (
              <div className="pqb-content__head">
                <div>
                  <span className="pqb-eyebrow">当前题库</span>
                  <h2>{activeBank.name} · 题目管理</h2>
                  <p>{activeBank.description || '整理题目与掌握进度'}</p>
                </div>
                <div className="pqb-row-actions">
                  <Button icon={<Play size={15} />} onClick={() => void beginPractice()}>开始刷题</Button>
                </div>
              </div>
            ) : (
              <div className="pqb-content__head">
                <div>
                  <span className="pqb-eyebrow">个人题目</span>
                  <h2>{sets.length ? '选择题库开始管理' : '未分题库的题目'}</h2>
                  <p>{sets.length ? '选择题库后可筛选、练习或加入公共题。' : '自建题目会保存在这里，可随后加入题库。'}</p>
                </div>
                <div className="pqb-row-actions">
                  {!activeBank && questionPage.total > 0 ? (
                    <Button icon={<Play size={15} />} onClick={() => void beginPractice()}>开始刷题</Button>
                  ) : null}
                </div>
              </div>
            )}

            <div className="pqb-filters">
              <div className="pqb-mastery-tabs" aria-label="掌握状态筛选">
                {[
                  ['', '全部题目'],
                  ['unmastered', '未掌握'],
                  ['mastered', '已掌握'],
                ].map(([value, label]) => (
                  <Button
                    key={value}
                    size="sm"
                    variant={filters.mastery === value ? 'filled' : 'tonal'}
                    aria-pressed={filters.mastery === value}
                    onClick={() => changeFilter('mastery', value)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
              <div className="pqb-filter-grid">
                <Field label="科目">
                  <Select value={filters.subject} onChange={(event) => changeFilter('subject', event.target.value)}>
                    <option value="">全部科目</option>
                    {subjects.map((subject) => <option key={subject} value={subject}>{subject}</option>)}
                  </Select>
                </Field>
                <Field label="章节">
                  <Select value={filters.chapter} onChange={(event) => changeFilter('chapter', event.target.value)}>
                    <option value="">全部章节</option>
                    {chapters.map((chapter) => <option key={chapter} value={chapter}>{chapter}</option>)}
                  </Select>
                </Field>
                <Field label="题型">
                  <Select value={filters.question_type} onChange={(event) => changeFilter('question_type', event.target.value)}>
                    <option value="">全部题型</option>
                    {Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </Select>
                </Field>
              </div>
            </div>

            {questionError ? (
              <div className="pqb-alert" role="alert">
                <span>{questionError}</span>
                <Button onClick={() => void fetchQuestions()}>重试</Button>
              </div>
            ) : null}
            {questionLoading ? <LoadingState text="正在加载题目…" /> : null}
            {!questionLoading && !questionError && !visibleQuestions.length ? (
              <Empty
                title="没有符合条件的题目"
                text={activeBank ? '调整筛选条件，或从公共题库加入新的题目。' : '调整筛选条件后再试。'}
                action={activeBank ? <Button onClick={openPublicPicker}>去题库选题</Button> : null}
              />
            ) : null}
            {!questionLoading && !questionError && visibleQuestions.length ? (
              <div className="pqb-question-list">
                {visibleQuestions.map((question) => {
                  const mastered = question.mastery_state === 'mastered'
                  const personal = isPersonalQuestion(question)
                  return (
                    <article key={question.id} className="pqb-question">
                      <div className="pqb-question__top">
                        <div className="pqb-tags">
                          <span>{TYPE_LABELS[question.question_type] || question.question_type || '题目'}</span>
                          {question.subject ? <span>{question.subject}</span> : null}
                          {question.chapter ? <span>{question.chapter}</span> : null}
                          <span className={mastered ? 'is-mastered' : ''}>{mastered ? '掌握状态：已掌握' : '掌握状态：未掌握'}</span>
                          {!personal ? <span>公共题</span> : null}
                        </div>
                        <span className="pqb-muted">#{question.id}</span>
                      </div>
                      <h3>{question.content}</h3>
                      {optionPreview(question.options) ? <p className="pqb-question__options">{optionPreview(question.options)}</p> : null}
                      <div className="pqb-question__actions">
                        <Button
                          size="sm"
                          variant={mastered ? 'tonal' : 'ghost'}
                          icon={mastered ? <RefreshCw size={14} /> : <Check size={14} />}
                          disabled={masteryBusy === question.id}
                          onClick={() => void toggleMastery(question)}
                        >
                          {mastered ? '取消掌握' : '标记已掌握'}
                        </Button>
                        {personal ? (
                          <>
                            <Button size="sm" variant="ghost" icon={<Edit size={14} />} onClick={() => openEditQuestion(question)}>编辑题目</Button>
                            <Button size="sm" variant="ghost" icon={<Trash size={14} />} onClick={() => void removeQuestion(question)}>删除题目</Button>
                          </>
                        ) : activeBank ? (
                          <Button size="sm" variant="ghost" icon={<Trash size={14} />} onClick={() => void removeQuestion(question)}>移出题库</Button>
                        ) : null}
                      </div>
                    </article>
                  )
                })}
              </div>
            ) : null}
            {!questionLoading && visibleTotal > PAGE_SIZE ? (
              <Pager
                page={questionPage.page || filters.page || 1}
                pageSize={PAGE_SIZE}
                total={visibleTotal}
                onChange={changePage}
                disabled={questionLoading}
                label="个人题目分页"
              />
            ) : null}
          </section>
        </div>
      )}

      <Dialog
        open={!!setDialog}
        title={setDialog?.mode === 'edit' ? '编辑题库' : '新建题库'}
        sub="题库名称用于区分不同的练习范围。"
        onClose={() => !setSaving && setSetDialog(null)}
        footer={(
          <>
            <Button variant="text" disabled={setSaving} onClick={() => setSetDialog(null)}>取消</Button>
            <Button type="submit" form="pqb-set-form" loading={setSaving}>{setDialog?.mode === 'edit' ? '保存' : '创建'}</Button>
          </>
        )}
      >
        <form id="pqb-set-form" className="pqb-form" onSubmit={saveSet}>
          <Field label="题库名称">
            <Input aria-label="题库名称" value={setDialog?.name || ''} onChange={(event) => setSetDialog((dialog) => ({ ...dialog, name: event.target.value }))} placeholder="例如：数学专项" />
          </Field>
          <Field label="题库描述">
            <Textarea aria-label="题库描述" value={setDialog?.description || ''} onChange={(event) => setSetDialog((dialog) => ({ ...dialog, description: event.target.value }))} placeholder="可选，例如：错题与自建题" />
          </Field>
          {setError ? <div className="pqb-alert" role="alert">{setError}</div> : null}
        </form>
      </Dialog>

      <Dialog
        open={!!questionDialog}
        title={questionDialog?.mode === 'edit' ? '编辑自建题目' : '自建题目'}
        sub="答案与解析仅用于提交后的练习反馈。"
        onClose={() => !questionSaving && setQuestionDialog(null)}
        wide
        footer={(
          <>
            <Button variant="text" disabled={questionSaving} onClick={() => setQuestionDialog(null)}>取消</Button>
            <Button type="submit" form="pqb-question-form" loading={questionSaving}>保存题目</Button>
          </>
        )}
      >
        <form id="pqb-question-form" className="pqb-form" onSubmit={saveQuestion}>
          <Field label="题目内容">
            <Textarea aria-label="题目内容" value={questionDraft.content} onChange={(event) => updateDraft('content', event.target.value)} placeholder="输入完整题干" />
          </Field>
          <div className="pqb-form-grid">
            <Field label="题型">
              <Select aria-label="题型" value={questionDraft.question_type} onChange={(event) => updateDraft('question_type', event.target.value)}>
                {Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </Select>
            </Field>
            <Field label="难度">
              <Input aria-label="难度" type="number" min={1} max={5} value={questionDraft.difficulty} onChange={(event) => updateDraft('difficulty', event.target.value)} />
            </Field>
            <Field label="科目">
              <Input aria-label="科目" value={questionDraft.subject} onChange={(event) => updateDraft('subject', event.target.value)} placeholder="例如：数学" />
            </Field>
            <Field label="章节">
              <Input aria-label="章节" value={questionDraft.chapter} onChange={(event) => updateDraft('chapter', event.target.value)} placeholder="例如：极限" />
            </Field>
          </div>
          {CHOICE_TYPES.includes(questionDraft.question_type) ? (
            <Field label="选项" hint="每行一个，可带 A.、B、 等前缀，保存时会自动清理。">
              <Textarea aria-label="选项" value={questionDraft.optionsText} onChange={(event) => updateDraft('optionsText', event.target.value)} placeholder={'A. 2\nB. 3'} />
            </Field>
          ) : null}
          <Field label="标准答案">
            <Input aria-label="标准答案" value={questionDraft.answer} onChange={(event) => updateDraft('answer', event.target.value)} placeholder={CHOICE_TYPES.includes(questionDraft.question_type) ? '例如：A；多选可填 AB' : '输入参考答案'} />
          </Field>
          <Field label="答案解析">
            <Textarea aria-label="答案解析" value={questionDraft.analysis} onChange={(event) => updateDraft('analysis', event.target.value)} placeholder="可选，提交练习后展示" />
          </Field>
          {questionDialogError ? <div className="pqb-alert" role="alert">{questionDialogError}</div> : null}
        </form>
      </Dialog>

      <Dialog
        open={publicOpen}
        title="从公共题库选题"
        sub="筛选后主动加入所选题库；重复加入由服务端保证幂等。"
        wide
        onClose={() => setPublicOpen(false)}
        footer={<Button variant="text" onClick={() => setPublicOpen(false)}>关闭</Button>}
      >
        <div className="pqb-public">
          <Field label="加入题库">
            <Select aria-label="加入题库" value={publicBankId ?? ''} onChange={(event) => {
              setPublicBankId(Number(event.target.value) || null)
              void loadPublic({ bankId: Number(event.target.value) || null, page: 1 })
            }}>
              <option value="">请先新建题库</option>
              {sets.map((set) => <option key={set.id} value={set.id}>{set.name}</option>)}
            </Select>
          </Field>
          {!sets.length ? (
            <div className="pqb-public__notice">请先新建题库，再加入公共题。<Button size="sm" onClick={openCreateSet}>新建题库</Button></div>
          ) : null}
          <div className="pqb-filter-grid pqb-filter-grid--public">
            <Field label="科目">
              <Input aria-label="公共题科目" value={publicFilters.subject} onChange={(event) => setPublicFilters((current) => ({ ...current, subject: event.target.value }))} placeholder="全部科目" />
            </Field>
            <Field label="章节">
              <Input aria-label="公共题章节" value={publicFilters.chapter} onChange={(event) => setPublicFilters((current) => ({ ...current, chapter: event.target.value }))} placeholder="全部章节" />
            </Field>
            <Field label="题型">
              <Select aria-label="公共题目型" value={publicFilters.question_type} onChange={(event) => setPublicFilters((current) => ({ ...current, question_type: event.target.value }))}>
                <option value="">全部题型</option>
                {Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </Select>
            </Field>
            <Field label="关键词">
              <Input aria-label="公共题关键词" value={publicKeyword} onChange={(event) => setPublicKeyword(event.target.value)} placeholder="搜索题干" />
            </Field>
          </div>
          <Button icon={<Search size={15} />} onClick={() => void loadPublic({ page: 1, keyword: publicKeyword })}>筛选公共题</Button>
          {publicError ? <div className="pqb-alert" role="alert">{publicError}</div> : null}
          {publicLoading ? <LoadingState text="正在加载公共题库…" /> : null}
          {!publicLoading && !publicError && !publicPage.items.length ? <Empty title="没有符合条件的公共题" text="调整筛选条件后再试。" /> : null}
          {!publicLoading && !publicError && publicPage.items.length ? (
            <div className="pqb-public__list">
              {publicPage.items.map((question) => (
                <article key={question.id} className="pqb-public__item">
                  <div className="pqb-tags">
                    <span>{TYPE_LABELS[question.question_type] || '题目'}</span>
                    {question.subject ? <span>{question.subject}</span> : null}
                    {question.chapter ? <span>{question.chapter}</span> : null}
                  </div>
                  <h3>{question.content}</h3>
                  {optionPreview(question.options) ? <p className="pqb-question__options">{optionPreview(question.options)}</p> : null}
                  <Button
                    size="sm"
                    icon={<Plus size={14} />}
                    disabled={!publicBankId || publicBusy === question.id}
                    onClick={() => void addPublicQuestion(question)}
                  >
                    {publicBusy === question.id ? '加入中…' : '加入题库'}
                  </Button>
                </article>
              ))}
            </div>
          ) : null}
          {!publicLoading && publicPage.total > 10 ? (
            <Pager
              page={publicPage.page}
              pageSize={10}
              total={publicPage.total}
              onChange={(page) => {
                setPublicPage((current) => ({ ...current, page }))
                void loadPublic({ page, keyword: publicKeyword })
              }}
              label="公共题分页"
            />
          ) : null}
        </div>
      </Dialog>
      {confirmDialog}
    </main>
  )
}
