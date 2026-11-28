import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import MathText from '../../components/MathText'
import {
  Alert,
  Button,
  Card,
  CardHead,
  Input,
  Progress,
  Select,
  Sheet,
  Textarea,
  toast,
  useConfirm,
  useMedia,
} from '../ui'
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Keyboard,
  ListChecks,
  MessageSquare,
  Sparkles,
  Star,
  X,
} from '../icons'
import { quizApi, request, wordsApi } from '../../api/client'
import { optionText } from '../../utils/optionText'
import { ukey } from '../../utils/userKeys'
import {
  TYPE_LABELS,
  LETTERS,
  letterOf,
  addWrong,
  pushRec,
  isChoiceQ,
  isMultiQ,
  isTextQuestion,
  isChoiceWithoutOptions,
  isCorrectOption,
  stripOptLabel,
  dependsOnFigure,
  questionMark,
} from './quizShared'
import '../styles/quiz-v3.css'
import '../styles/study-glass.css'

/* =====================================================================
 * 刷题中心 · 答题区（v3）
 * 单题作答（点选即判 / 多选提交 / 文本题对照自评）+ 右侧答题卡
 * + 键盘快捷键（A–F 选择 · Enter 提交/下一题 · ← → 切换）
 * + 收藏星标 + AI 生成解析（仅前端展示、不落库）。
 * 会话级状态（idx/drafts/textDraft/selfCheck）就近下沉在本组件：
 * 每次进入练习都是新挂载，等效于拆分前 beginSession 时的重置。
 * ===================================================================== */

/* 题目配图 URL：后端 quiz_questions.images[].path 是仓内相对路径
 * （形如 question_pages/271_p0009.png），由后端 /media/images 挂载对外提供。
 * 已是绝对地址/站内绝对路径的原样返回，避免重复加前缀。 */
const MEDIA_IMAGES_PREFIX = '/media/images/'
const PENDING_PROGRESS_KEY = 'quiz-session-pending'

/** 读取本地暂存的会话进度（断网/刷新后恢复作答）。 */
function readPendingProgress(sessionId) {
  try {
    const pending = JSON.parse(localStorage.getItem(ukey(PENDING_PROGRESS_KEY)) || '{}')
    return pending?.[String(sessionId)] || null
  } catch {
    return null
  }
}

/** 写入本地暂存的会话进度。 */
function writePendingProgress(sessionId, progress) {
  try {
    const key = ukey(PENDING_PROGRESS_KEY)
    const pending = JSON.parse(localStorage.getItem(key) || '{}')
    pending[String(sessionId)] = progress
    localStorage.setItem(key, JSON.stringify(pending))
  } catch { /* 隐私模式或存储配额不足时仍由服务端保存兜底 */ }
}

/** 清除本地暂存的会话进度（服务端保存成功后调用）。 */
function clearPendingProgress(sessionId, revision) {
  try {
    const key = ukey(PENDING_PROGRESS_KEY)
    const pending = JSON.parse(localStorage.getItem(key) || '{}')
    const current = pending?.[String(sessionId)]
    if (!current || (revision != null && current.revision !== revision)) return
    delete pending[String(sessionId)]
    if (Object.keys(pending).length) localStorage.setItem(key, JSON.stringify(pending))
    else localStorage.removeItem(key)
  } catch { /* 本地清理失败不阻断已成功的服务端保存 */ }
}

/** 题目配图 URL：已是绝对地址原样返回，仓内相对路径加 /media/images/ 前缀。 */
function mediaSrc(img) {
  const raw = img?.url || img?.path || img?.src || ''
  if (!raw) return ''
  if (/^(?:[a-z]+:)?\/\//i.test(raw) || raw.startsWith('/')) return raw
  return MEDIA_IMAGES_PREFIX + raw.replace(/^\/+/, '')
}

/* ---------- P0-1 生词提取辅助 ---------- */
const EN_RE = /[A-Za-z]/
/** 是否为英语题：科目为「英语」或题干含英文字母。 */
function isEnglishQuestion(q) {
  if (!q) return false
  if (q.subject === '英语') return true
  return EN_RE.test(String(q.content || ''))
}

/** 生词来源标签：真题刷题 + 年份/试卷/来源信息，写入词条 tag。 */
function buildSourceLabel(q) {
  const parts = []
  if (q?.year) parts.push(`${q.year}年`)
  if (q?.paper) parts.push(q.paper)
  if (q?.source) parts.push(String(q.source).replace(/^真题[:：]/, '真题'))
  parts.push('真题刷题')
  return [...new Set(parts.filter(Boolean))].join(' · ').slice(0, 50)
}

/** 按词的来源位置取对应原文片段作为例句。 */
function sourceTextFor(source, q) {
  if (source === '选项') return (q?.options || []).map((o) => optionText(o)).join('；')
  if (source === '解析') return q?.analysis || q?.content || ''
  return q?.content || ''
}

/**
 * 刷题中心答题区（v3）。
 * 单题作答（点选即判 / 多选提交 / 文本题对照自评）+ 答题卡 + 键盘快捷键
 * + 收藏星标 + AI 生成解析（仅前端展示、不落库）。
 * 会话级状态就近下沉在本组件，每次进入练习都是新挂载。
 */
export default function QuizPractice({
  session,
  records,
  basis,
  favs,
  kpFilter,
  backendOk,
  tutorMode,
  setTutorMode,
  submitting,
  setSubmitting,
  submitAnswer,
  manualChoiceSubmit = false,
  showFavorites = true,
  onRecord,
  onToggleFav,
  onGoHome,
  onFinish,
}) {
  const navigate = useNavigate()
  const adaptedSubmit = typeof submitAnswer === 'function'
  const manualChoices = manualChoiceSubmit || adaptedSubmit
  const isMobile = useMedia('(max-width: 1080px)')
  const mainRef = useRef(null)
  const submitLock = useRef(false)
  const pendingSubmitRef = useRef(null)
  const finishingRef = useRef(false)
  const attemptIdsRef = useRef({})
  const versionRef = useRef(session.version || 1)
  const saveSnapshotRef = useRef(null)
  const saveQueuesRef = useRef(new Map())
  const saveReadyRef = useRef(false)
  const saveRevisionRef = useRef(0)
  const durationBaseRef = useRef(session.duration_seconds || 0)
  const activeSinceRef = useRef(document.visibilityState === 'visible' ? Date.now() : null)
  const mountedRef = useRef(false)
  const activeSessionRef = useRef(session)
  activeSessionRef.current = session
  const isCurrentRequest = useCallback((requestSession) => (
    mountedRef.current && activeSessionRef.current === requestSession
  ), [])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    submitLock.current = false
    pendingSubmitRef.current = null
    finishingRef.current = false
    setFinishing(false)
    setSubmitting(false)
    setIdx(session.startIdx ?? session.current_index ?? 0)
    setDrafts(session.drafts || {})
    setTextDraft(session.text_drafts || {})
    setSelfScores(session.self_scores || {})
    setStuckMarked(session.marked || {})
    versionRef.current = session.version || 1
    durationBaseRef.current = session.duration_seconds || 0
    activeSinceRef.current = document.visibilityState === 'visible' ? Date.now() : null
    saveReadyRef.current = false
    saveQueuesRef.current = new Map()
    attemptIdsRef.current = {}
    setSelfCheck(null)
    setSubmitError('')
    setSaveError('')
    const pending = session.session_id ? readPendingProgress(session.session_id) : null
    const pendingTime = Date.parse(pending?.saved_at || '') || 0
    const serverTime = Date.parse(session.updated_at || '') || 0
    if (pending && pendingTime > serverTime) {
      setIdx(Math.max(0, Math.min(Number(pending.current_index) || 0, session.questions.length - 1)))
      setDrafts({ ...(session.drafts || {}), ...(pending.drafts || {}) })
      setTextDraft({ ...(session.text_drafts || {}), ...(pending.text_drafts || {}) })
      setSelfScores({ ...(session.self_scores || {}), ...(pending.self_scores || {}) })
      setStuckMarked({ ...(session.marked || {}), ...(pending.marked || {}) })
      durationBaseRef.current = Math.max(session.duration_seconds || 0, Number(pending.duration_seconds) || 0)
    }
    setAiAnalyses({})
    setAiGrades({})
    setWordLoading(false)
    setSheetOpen(false)
  }, [session, setSubmitting])

  /* ---------- 练习会话（本视图独占，随挂载自然重置） ---------- */
  const [idx, setIdx] = useState(session.startIdx ?? 0)
  const [drafts, setDrafts] = useState({}) // 选择题提交前草稿
  const [textDraft, setTextDraft] = useState({}) // 文本题草稿
  const [selfScores, setSelfScores] = useState({})
  const [selfCheck, setSelfCheck] = useState(null) // 文本题对照 {qid,myAns,correctAnswer,analysis}
  const [submitError, setSubmitError] = useState('')
  const [saveError, setSaveError] = useState('')
  /* AI 生成解析（复用现有 /ai/tutoring/explain，仅前端展示、不落库） */
  const [aiAnalyses, setAiAnalyses] = useState({}) // { [qid]: {content, provider, loading, error} }
  /* P0-2 AI 批改结果：{ [qid]: {score, max_score, evaluation, reference_answer, loading, error} } */
  const [aiGrades, setAiGrades] = useState({})
  /* P0-1 生词提取/导入的按钮 loading 锁（避免重复点击） */
  const [wordLoading, setWordLoading] = useState(false)
  /* 仍未理解 → 盲点池（闭环：AI 产出回流学习数据主线） */
  const [stuckMarked, setStuckMarked] = useState({}) // { [qid]: true }
  const [sheetOpen, setSheetOpen] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const busy = submitting || finishing
  const [confirm, confirmDialog] = useConfirm()

  /* ================= 作答与判分 ================= */
  /* 多选仍需逐个勾选后判分；单选/判断在 toggleDraft 里点选即判。 */
  const toggleDraft = (qid, i) => {
    const q = session.questions[idx]
    if (records[qid] || busy || submitLock.current) return
    if (isMultiQ(q)) {
      setDrafts((prev) => {
        const cur = Array.isArray(prev[qid]) ? prev[qid] : []
        const next = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort((a, b) => a - b)
        return { ...prev, [qid]: next }
      })
      return
    }
    // 单选/判断：公共题保留点选即判；个人题库先选后提交
    setDrafts((prev) => ({ ...prev, [qid]: i }))
    setSubmitError('')
    if (!manualChoices) gradeChoice(q, i)
  }

  const sessionAttemptFields = (qid) => {
    if (!session?.session_id || adaptedSubmit) return {}
    if (!attemptIdsRef.current[qid]) {
      attemptIdsRef.current[qid] = globalThis.crypto?.randomUUID?.() || `${session.session_id}-${qid}-${Date.now()}-${Math.random().toString(36).slice(2)}`
    }
    const errorId = Number(session.question_error_ids?.[String(qid)] || session.basis?.question_error_ids?.[String(qid)])
    return {
      session_id: session.session_id,
      client_attempt_id: attemptIdsRef.current[qid],
      ...(Number.isInteger(errorId) && errorId > 0 ? { error_id: errorId } : {}),
    }
  }

  const gradeWithAdapter = async (q, myAns, extra = {}) => {
    if (!adaptedSubmit || records[q.id] || busy || submitLock.current) return
    const requestSession = activeSessionRef.current
    submitLock.current = true
    setSubmitting(true)
    setSubmitError('')
    let completion
    try {
      const request = submitAnswer({ question_id: Number(q.id), my_answer: myAns, ...extra })
      completion = Promise.resolve(request).catch(() => {})
      pendingSubmitRef.current = completion
      const result = await request
      if (!isCurrentRequest(requestSession)) return
      if (!result || (typeof result.correct !== 'boolean' && result.correct !== null)) {
        throw new Error('提交未返回判分结果，请重试')
      }
      const needsReview = result.correct === null || result.needs_review === true
      applyGrade(q, needsReview ? null : result.correct, myAns, result.correct_answer ?? '', result.analysis ?? '', {
        syncStatus: 'synced', syncError: '', needsReview,
      })
    } catch (err) {
      if (isCurrentRequest(requestSession)) setSubmitError(err?.message || '提交失败，请稍后重试')
    } finally {
      if (pendingSubmitRef.current === completion) pendingSubmitRef.current = null
      if (isCurrentRequest(requestSession)) {
        submitLock.current = false
        setSubmitting(false)
      }
    }
  }

  /* 选择题判分。sel 为下标或下标数组（多选）。 */
  const gradeChoice = async (q, sel) => {
    if (records[q.id] || selfCheck || busy || submitLock.current) return
    const requestSession = activeSessionRef.current
    const myAns = Array.isArray(sel) ? sel.map(letterOf).join('') : letterOf(sel)
    if (adaptedSubmit) {
      await gradeWithAdapter(q, myAns)
      return
    }
    // 浏览模式（无标准答案题）：不调用判分接口、不写错题本，仅记录用户作答供自检
    if (session?.noAnswer) {
      onRecord(q.id, { selfCheckOnly: true, selected: myAns, correctAnswer: '', analysis: '' })
      toast('浏览模式：本题暂无标准答案，请对照教材/解析自检')
      return
    }
    submitLock.current = true
    let correct = false,
      correctAnswer = q.answer,
      analysis = q.analysis
    let sync = {
      syncStatus: 'local',
      syncError: backendOk ? '本地题目未同步' : '后端暂不可用',
    }
    if (backendOk && !String(q.id).startsWith('l')) {
      let completion
      setSubmitting(true)
      try {
        const request = quizApi.submit({ question_id: Number(q.id), my_answer: myAns, ...sessionAttemptFields(q.id) })
        completion = Promise.resolve(request).catch(() => {})
        pendingSubmitRef.current = completion
        const r = await request
        if (!isCurrentRequest(requestSession)) return
        const needsReview = r.correct === null || r.needs_review === true
        correct = needsReview ? null : !!r.correct
        correctAnswer = r.correct_answer ?? correctAnswer
        analysis = r.analysis ?? analysis
        sync = { syncStatus: 'synced', syncError: '', needsReview }
      } catch (err) {
        if (!isCurrentRequest(requestSession)) return
        setSubmitError(err?.message || '提交失败，请稍后重试')
        return
      } finally {
        if (pendingSubmitRef.current === completion) pendingSubmitRef.current = null
        if (isCurrentRequest(requestSession)) {
          setSubmitting(false)
          submitLock.current = false
        }
      }
    } else {
      correct = String(myAns).toUpperCase() === String(q.answer).toUpperCase()
      submitLock.current = false
    }
    if (isCurrentRequest(requestSession)) applyGrade(q, correct, myAns, correctAnswer, analysis, sync)
  }

  const applyGrade = (q, correct, selected, correctAnswer, analysis, sync = {}) => {
    if (session?.noAnswer) {
      onRecord(q.id, { selfCheckOnly: true, selected, correctAnswer: '', analysis: '' })
      return
    }
    const needsReview = correct === null || sync.needsReview === true
    const syncStatus = sync.syncStatus || 'synced'
    const syncError = sync.syncError || ''
    onRecord(q.id, { correct: needsReview ? null : !!correct, needsReview, selected, correctAnswer, analysis, syncStatus, syncError })
    if (needsReview) {
      toast('答案待人工核对，暂不判定对错')
      return
    }
    if (adaptedSubmit) {
      toast(correct ? '回答正确' : '回答错误')
      return
    }
    pushRec(q.id, correct) // V10 本地作答累计（做过次数 + 最近对错）
    if (correct) {
      toast(syncStatus === 'synced' ? '回答正确' : '本地判分：回答正确（后端未同步）')
    } else {
      addWrong(q.id)
      toast(syncStatus === 'synced'
        ? '答错已计入错题本'
        : `本地判分：错题仅记录在本机，后端未同步${syncError ? `（${syncError}）` : ''}`)
    }
  }

  const doSubmit = async () => {
    if (!session) return
    const q = session.questions[idx]
    if (records[q.id] || selfCheck) return
    if (busy) return

    /* ---- 手动模式选择题：勾选后提交 ---- */
    if (isChoiceQ(q) && (isMultiQ(q) || manualChoices)) {
      const sel = drafts[q.id]
      const empty = sel == null || (Array.isArray(sel) && !sel.length)
      if (empty) {
        toast('请至少选择一个选项')
        return
      }
      await gradeChoice(q, sel)
      return
    }

    /* ---- 文本题（填空/简答/计算/作图）：输入 → 对照 → 自评 ---- */
    const txt = (textDraft[q.id] || '').trim()
    if (!txt) {
      toast('请先输入你的作答，再点「对照答案」')
      return
    }
    if (adaptedSubmit) {
      const maxScore = Number(q.max_score) || Number(q.score) || 10
      const rawScore = selfScores[q.id]
      const score = Number(rawScore)
      if (rawScore == null || String(rawScore).trim() === '' || !Number.isFinite(score) || score < 0 || score > maxScore) {
        toast(`请填写 0–${maxScore} 的自评分`)
        return
      }
      await gradeWithAdapter(q, txt, { self_score: score, max_score: maxScore })
      return
    }
    // 对照答案只展示本地题库内容；真正提交延迟到用户自评，避免一次作答落两条记录。
    setSelfCheck({ qid: q.id, myAns: txt, correctAnswer: q.answer, analysis: q.analysis })
  }

  /* 文本题自评落分：按后端契约携带 self_score，只提交一次。 */
  const selfGrade = async (correct) => {
    if (!selfCheck || busy || submitLock.current || records[selfCheck.qid]) return
    const requestSession = activeSessionRef.current
    const q = session.questions.find((x) => x.id === selfCheck.qid)
    if (!q) return
    const maxScore = Number(q.max_score) || Number(q.score) || 10
    let finalCorrect = correct
    let correctAnswer = selfCheck.correctAnswer
    let analysis = selfCheck.analysis
    let sync = {
      syncStatus: 'local',
      syncError: backendOk ? '本地题目未同步' : '后端暂不可用',
    }
    if (backendOk && !String(q.id).startsWith('l')) {
      let completion
      submitLock.current = true
      setSubmitting(true)
      setSubmitError('')
      try {
        const request = quizApi.submit({
          question_id: Number(q.id),
          my_answer: selfCheck.myAns,
          self_score: correct ? maxScore : 0,
          max_score: maxScore,
          ...sessionAttemptFields(q.id),
        })
        completion = Promise.resolve(request).catch(() => {})
        pendingSubmitRef.current = completion
        const r = await request
        if (!isCurrentRequest(requestSession)) return
        if (r.correct === null || r.needs_review === true) finalCorrect = null
        else if (typeof r.correct === 'boolean') finalCorrect = r.correct
        correctAnswer = r.correct_answer ?? correctAnswer
        analysis = r.analysis ?? analysis
        sync = {
          syncStatus: 'synced',
          syncError: '',
          needsReview: r.correct === null || r.needs_review === true,
        }
      } catch (err) {
        if (!isCurrentRequest(requestSession)) return
        setSubmitError(err?.message || '提交失败，请稍后重试')
        return
      } finally {
        if (pendingSubmitRef.current === completion) pendingSubmitRef.current = null
        if (isCurrentRequest(requestSession)) {
          setSubmitting(false)
          submitLock.current = false
        }
      }
    }
    if (isCurrentRequest(requestSession)) {
      applyGrade(q, finalCorrect, selfCheck.myAns, correctAnswer, analysis, sync)
      setSelfCheck(null)
    }
  }

  /* P0-2 主观题 AI 批改：调用 /api/quiz/grade-subjective，结果仅作为参考展示，
     不覆盖自评判分流程。score 为 null 时（LLM 不可用）展示兜底提示。 */
  const gradeAI = async () => {
    if (!q) return
    const qid = q.id
    const txt = (textDraft[qid] || '').trim()
    if (!txt) {
      toast('请先输入你的作答，再点「AI 批改」')
      return
    }
    if (aiGrades[qid]?.loading) return
    const requestSession = activeSessionRef.current
    setAiGrades((m) => ({ ...m, [qid]: { ...(m[qid] || {}), loading: true, error: '' } }))
    try {
      const maxScore = Number(q.max_score) || Number(q.score) || 10
      const r = await quizApi.gradeSubjective({
        question_id: Number(qid),
        my_answer: txt,
        max_score: maxScore,
      })
      if (!isCurrentRequest(requestSession)) return
      setAiGrades((m) => ({
        ...m,
        [qid]: {
          score: r?.score ?? null,
          max_score: r?.max_score ?? maxScore,
          evaluation: r?.evaluation || '',
          reference_answer: r?.reference_answer || q.answer || '',
          verification: r?.verification || null,
          loading: false,
          error: '',
        },
      }))
    } catch (e) {
      if (!isCurrentRequest(requestSession)) return
      setAiGrades((m) => ({
        ...m,
        [qid]: { ...(m[qid] || {}), loading: false, error: e?.message || 'AI 批改失败，请稍后重试' },
      }))
    }
  }

  /* P0-1 生词一键进词库：提取候选词 → 过滤已在词库的 → 确认后批量导入。
     已存在的词跳过（不提交，避免后端 409 冲突）。 */
  const addWordsToVocab = async () => {
    if (!q?.id || wordLoading) return
    const qid = q.id
    setWordLoading(true)
    try {
      const data = await quizApi.extractWords(Number(qid))
      const words = Array.isArray(data?.words) ? data.words : []
      const fresh = words.filter((w) => w && !w.exists)
      const skipped = words.length - fresh.length
      if (!fresh.length) {
        toast(skipped ? `${skipped} 个词已在词库` : '没有可添加的生词')
        return
      }
      const label = buildSourceLabel(q)
      const wordItems = fresh.map((w) => ({
        word: w.word,
        meaning: `（${w.source || '真题'}生词，待补充释义）`,
        example: sourceTextFor(w.source, q).slice(0, 200),
        source_label: label,
      }))
      const preview = fresh
        .slice(0, 10)
        .map((w) => `· ${w.word}（${w.source}）`)
        .join('\n')
      const ok = await confirm({
        title: '加入生词本',
        text: `将 ${fresh.length} 个生词加入词库？${skipped ? `（${skipped} 个已在词库，自动跳过）` : ''}`,
        confirmText: '加入',
        content: (
          <pre className="v3-quiz-word-preview">
            {preview}
            {fresh.length > 10 ? `\n…等 ${fresh.length} 个` : ''}
          </pre>
        ),
      })
      if (!ok) return
      await wordsApi.batchImport({ deck_id: null, words: wordItems })
      toast(`已加入 ${fresh.length} 个生词${skipped ? `（${skipped} 个已在词库）` : ''}`)
    } catch (e) {
      toast(`加入生词本失败：${e?.message || '请稍后重试'}`)
    } finally {
      setWordLoading(false)
    }
  }

  const go = useCallback(
    (n) => {
      if (!session || finishingRef.current) return
      if (n < 0 || n >= session.questions.length) return
      setIdx(n)
      setSelfCheck(null)
      setSubmitError('')
      window.scrollTo({ top: 0, behavior: 'smooth' })
      mainRef.current?.scrollTo?.({ top: 0, behavior: 'smooth' })
    },
    [session],
  )

  saveSnapshotRef.current = { idx, drafts, textDraft, selfScores, marked: stuckMarked }

  const persistProgress = useCallback(() => {
    if (!session?.session_id || session.status === 'completed') return Promise.resolve(true)
    const requestSession = activeSessionRef.current
    const elapsed = durationBaseRef.current + (activeSinceRef.current == null ? 0 : Math.floor((Date.now() - activeSinceRef.current) / 1000))
    const body = {
      current_index: saveSnapshotRef.current.idx,
      version: versionRef.current,
      drafts: saveSnapshotRef.current.drafts,
      text_drafts: saveSnapshotRef.current.textDraft,
      self_scores: saveSnapshotRef.current.selfScores,
      marked: saveSnapshotRef.current.marked,
      duration_seconds: Math.max(0, elapsed),
    }
    const revision = ++saveRevisionRef.current
    writePendingProgress(session.session_id, { ...body, revision, saved_at: new Date().toISOString() })
    const saveQueues = saveQueuesRef.current
    const previousSave = saveQueues.get(requestSession) || Promise.resolve()
    const saveRequest = previousSave.catch(() => {}).then(async () => {
      if (!isCurrentRequest(requestSession)) return false
      const markSaved = (saved, savedBody = body, savedRevision = revision) => {
        if (!isCurrentRequest(requestSession)) return false
        clearPendingProgress(requestSession.session_id, savedRevision)
        versionRef.current = saved?.version || savedBody.version + 1
        durationBaseRef.current = savedBody.duration_seconds
        activeSinceRef.current = document.visibilityState === 'visible' ? Date.now() : null
        setSaveError('')
        return true
      }
      try {
        const saved = await quizApi.patchSession(requestSession.session_id, body)
        return markSaved(saved)
      } catch (err) {
        if (err?.status === 409) {
          let latest
          try {
            latest = await quizApi.getSession(requestSession.session_id)
          } catch (readErr) {
            if (isCurrentRequest(requestSession)) setSaveError(`进度保存失败：${readErr?.message || '后端不可用'}。已保留在本机，将自动重试。`)
            return false
          }
          if (!isCurrentRequest(requestSession)) return false
          if (latest?.status === 'in_progress') {
            const currentSnapshot = saveSnapshotRef.current
            const currentRevision = saveRevisionRef.current
            const currentElapsed = durationBaseRef.current + (activeSinceRef.current == null ? 0 : Math.floor((Date.now() - activeSinceRef.current) / 1000))
            const merged = {
              ...body,
              current_index: currentSnapshot.idx,
              version: latest.version,
              drafts: { ...(latest.drafts || {}), ...(currentSnapshot.drafts || {}) },
              text_drafts: { ...(latest.text_drafts || {}), ...(currentSnapshot.textDraft || {}) },
              self_scores: { ...(latest.self_scores || {}), ...(currentSnapshot.selfScores || {}) },
              marked: { ...(latest.marked || {}), ...(currentSnapshot.marked || {}) },
              duration_seconds: Math.max(body.duration_seconds, currentElapsed, latest.duration_seconds || 0),
            }
            versionRef.current = latest.version
            setDrafts(merged.drafts)
            setTextDraft(merged.text_drafts)
            setSelfScores(merged.self_scores)
            setStuckMarked(merged.marked)
            writePendingProgress(requestSession.session_id, { ...merged, revision: currentRevision, saved_at: new Date().toISOString() })
            try {
              const saved = await quizApi.patchSession(requestSession.session_id, merged)
              return markSaved(saved, merged, currentRevision)
            } catch (retryErr) {
              if (isCurrentRequest(requestSession)) setSaveError(`进度保存失败：${retryErr?.message || '后端不可用'}。已保留在本机，将自动重试。`)
              return false
            }
          }
        }
        if (isCurrentRequest(requestSession)) setSaveError(`进度保存失败：${err?.message || '后端不可用'}。已保留在本机，将自动重试。`)
        return false
      }
    })
    saveQueues.set(requestSession, saveRequest)
    return saveRequest
  }, [session?.session_id, session.status, isCurrentRequest])

  useEffect(() => {
    if (finishing) return
    if (!saveReadyRef.current) { saveReadyRef.current = true; return }
    const timer = setTimeout(persistProgress, 700)
    return () => clearTimeout(timer)
  }, [idx, drafts, textDraft, selfScores, stuckMarked, persistProgress, finishing])

  useEffect(() => {
    const onVisibility = () => {
      activeSinceRef.current = document.visibilityState === 'visible' ? Date.now() : null
      if (document.visibilityState === 'hidden' && !finishingRef.current) persistProgress()
    }
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible' && !finishingRef.current) persistProgress()
    }, 15000)
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('beforeunload', persistProgress)
    window.addEventListener('pagehide', persistProgress)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('beforeunload', persistProgress)
      window.removeEventListener('pagehide', persistProgress)
    }
  }, [persistProgress])

  const leavePractice = useCallback(async () => {
    const requestSession = activeSessionRef.current
    if (busy || finishingRef.current) return
    finishingRef.current = true
    setFinishing(true)
    setSubmitting(true)
    try {
      const saveRequest = persistProgress()
      await pendingSubmitRef.current
      await saveRequest
      if (isCurrentRequest(requestSession)) onGoHome()
    } finally {
      if (isCurrentRequest(requestSession)) {
        finishingRef.current = false
        setFinishing(false)
        setSubmitting(false)
      }
    }
  }, [busy, persistProgress, isCurrentRequest, onGoHome, setSubmitting])

  const finishPractice = useCallback(async () => {
    const requestSession = activeSessionRef.current
    if (busy || finishingRef.current) return
    finishingRef.current = true
    setFinishing(true)
    setSubmitting(true)
    try {
      const saveRequest = persistProgress()
      await pendingSubmitRef.current
      if (!(await saveRequest)) return
      if (!isCurrentRequest(requestSession)) return
      if (requestSession?.session_id) {
        try {
          await quizApi.completeSession(requestSession.session_id)
          if (!isCurrentRequest(requestSession)) return
          clearPendingProgress(requestSession.session_id)
        } catch { /* 报告仍可查看，进度由后续自动保存重试 */ }
      }
      if (isCurrentRequest(requestSession)) onFinish()
    } finally {
      if (isCurrentRequest(requestSession)) {
        finishingRef.current = false
        setFinishing(false)
        setSubmitting(false)
      }
    }
  }, [busy, persistProgress, isCurrentRequest, onFinish, setSubmitting])

  /* “AI 生成解析”：复用项目现有 AI 讲题路由 POST /api/ai/tutoring/explain
     （angle=solution）。该路由真实存在且已在用，生成的解析**只在前端展示、不落库**，
     因此显式标注「AI 生成 · 未入库」，不做“已写回题库”的假承诺。 */
  const generateAnalysis = useCallback(
    async (q) => {
      if (!q?.id) return
      const requestSession = activeSessionRef.current
      const qid = q.id
      setAiAnalyses((m) => ({ ...m, [qid]: { loading: true, content: '', provider: '' } }))
      try {
        const r = await request('/ai/tutoring/explain', {
          method: 'POST',
          body: {
            question_id: Number(qid),
            angle: 'solution',
            source_kind: tutorMode === 'auto' ? undefined : tutorMode,
          },
        })
        if (!isCurrentRequest(requestSession)) return
        setAiAnalyses((m) => ({
          ...m,
          [qid]: { loading: false, content: r?.content || '', provider: r?.provider || 'AI', mode: r?.mode },
        }))
      } catch (e) {
        if (!isCurrentRequest(requestSession)) return
        setAiAnalyses((m) => ({
          ...m,
          [qid]: { loading: false, content: '', provider: '', error: e?.message || 'AI 生成解析失败' },
        }))
      }
    },
    [isCurrentRequest, tutorMode],
  )

  /* 「仍未理解，加入盲点池」：把 AI 讲题后仍未搞懂的知识点沉淀到盲区池，
     反哺复习队列与周会议题（POST /api/ai/tutoring/stuck）。 */
  const markStuck = useCallback(
    async (q) => {
      if (!q?.id || stuckMarked[q.id]) return
      try {
        await request('/ai/tutoring/stuck', {
          method: 'POST',
          body: { question_id: Number(q.id), note: 'AI 生成解析后仍未理解', angle: 'solution' },
        })
        setStuckMarked((m) => ({ ...m, [q.id]: true }))
        toast('已加入盲点池：将进入复习队列 / 周会议题安排巩固')
      } catch (e) {
        toast(e?.message || '加入盲点池失败，请稍后重试')
      }
    },
    [stuckMarked],
  )

  /* 键盘快捷键：A–F 选择 · Enter 提交/下一题 · ← → 切换 */
  useEffect(() => {
    const onKey = (e) => {
      if (!session || busy) return
      const t = e.target
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      const q = session.questions[idx]
      if (!q) return
      if (isChoiceQ(q) && !records[q.id]) {
        const k = e.key.toUpperCase()
        const i = LETTERS.indexOf(k)
        if (i >= 0 && i < q.options.length) {
          toggleDraft(q.id, i)
          return
        }
      }
      if (e.key === 'Enter') {
        // 残缺选择题（无选项不可作答）按 Enter 直接跳下一题
        if (isChoiceWithoutOptions(q)) {
          if (idx + 1 < session.questions.length) go(idx + 1)
          else finishPractice()
        } else if (!records[q.id] && !selfCheck) doSubmit()
        else if (idx + 1 < session.questions.length) go(idx + 1)
        else finishPractice()
      } else if (e.key === 'ArrowLeft') go(idx - 1)
      else if (e.key === 'ArrowRight') go(idx + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (!session) return null
  const q = session.questions[idx]
  const total = session.questions.length
  const rec = records[q.id]
  const needsReview = !!rec && (rec.correct === null || rec.needsReview === true)
  const memorize = session.mode === 'memorize'
  const revealed = memorize || !!rec
  const draft = drafts[q.id]
  const answeredCount = Object.keys(records).length
  // total=0（这道题集没载到题）时进度必须是 0，不能让 NaN 流进 style.width
  const pct = total > 0 ? Math.round(((memorize ? idx + 1 : answeredCount) / total) * 100) : 0
  const favOn = !!favs[q.id]
  const multiChoice = isMultiQ(q)

  const pickSheetCell = (i) => {
    go(i)
    setSheetOpen(false)
  }

  const renderSheetContent = () => (
    <>
      <div className="v3-quiz-sheet-grid">
        {session.questions.map((qq, i) => {
          const r = records[qq.id]
          const skipped = isChoiceWithoutOptions(qq)
          const needsReview = !!r && (r.correct === null || r.needsReview === true)
          let cls = 'v3-quiz-sheet-cell'
          if (skipped) cls += ' is-skip'
          else if (needsReview) cls += ' is-review'
          else if (r) cls += r.correct ? ' is-ok' : ' is-bad'
          else if (drafts[qq.id] != null || textDraft[qq.id]) cls += ' is-draft'
          if (i === idx) cls += ' is-cur'
          return (
            <button
              key={qq.id}
              type="button"
              className={cls}
              onClick={() => pickSheetCell(i)}
              aria-label={`第 ${i + 1} 题${skipped ? '，无选项不可作答' : needsReview ? '，待确认' : r ? (r.correct ? '，正确' : '，错误') : ''}`}
            >
              {i + 1}
            </button>
          )
        })}
      </div>
      <ul className="v3-quiz-legend">
        <li>
          <span className="v3-quiz-dot is-ok" />
          正确
        </li>
        <li>
          <span className="v3-quiz-dot is-bad" />
          错误
        </li>
        <li>
          <span className="v3-quiz-dot is-review" />
          待确认
        </li>
        <li>
          <span className="v3-quiz-dot is-todo" />
          未做
        </li>
        <li>
          <span className="v3-quiz-dot is-skip" />
          无选项
        </li>
      </ul>
      <Button block variant="ghost" className="v3-quiz-sheet-finish" disabled={busy} onClick={finishPractice}>
        {memorize ? '结束背题' : '交卷并查看报告'}
      </Button>
    </>
  )

  return (
    <div className="v3-quiz-practice v3-glasspage">
      <article ref={mainRef} className="v3-card v3-quiz-practice__main">
        <div className="v3-quiz-practice__meta">
          <Button size="sm" variant="ghost" icon={<ChevronLeft size={15} />} disabled={busy} onClick={leavePractice}>
            返回题库
          </Button>
          <span className="v3-quiz-practice__title" title={session.title}>
            {session.title}
          </span>
          {/* 知识点级筛选标识：明确告知用户当前按知识点精确出题 */}
          {kpFilter && (
            <span className="v3-quiz-tag" title={`知识点 ID ${kpFilter.id}`}>
              <Star size={11} /> 知识点 · {kpFilter.name}
            </span>
          )}
          <span className="v3-quiz-tag">{memorize ? '背题模式' : '练习模式'}</span>
          <span className="v3-quiz-tag">{TYPE_LABELS[q.question_type] || q.question_type || '题目'}</span>
          {q.subject && <span className="v3-quiz-tag">{q.subject}</span>}
          {q.chapter && <span className="v3-quiz-tag">{q.chapter}</span>}
          {session.noAnswer && (
            <span
              className="v3-quiz-tag"
              style={{
                background: 'var(--v3-warning-container)',
                color: 'var(--v3-on-warning-container)',
                borderColor: 'transparent',
              }}
            >
              浏览模式 · 暂不可判分
            </span>
          )}
          {showFavorites && (
            <Button
              className="v3-quiz-favbtn"
              size="sm"
              variant={favOn ? 'tonal' : 'ghost'}
              icon={<Star size={15} />}
              onClick={() => onToggleFav(q)}
            >
              {favOn ? '已收藏' : '收藏'}
            </Button>
          )}
        </div>

        {session.noAnswer && (
          <Alert tone="warning" className="v3-quiz-basis">
            当前为浏览模式：该科目/章节题库尚未回填标准答案，题目仅用于浏览与自检，不会判分、也不会进入错题本。可在「题库管理」为题目补全答案后恢复正常练习。
          </Alert>
        )}

        {/* 依据明示（M0）：本次练习按什么条件出题 + 可作答/总量口径，一眼可见 */}
        {basis && (
          <Alert tone="info" className="v3-quiz-basis">
            当前依据：
            <strong>{basis.sourceKindLabel}</strong>
            {basis.subject ? ` · 科目 ${basis.subject}` : ''}
            {basis.chapter ? ` · 章节 ${basis.chapter}` : ''}
            {basis.kpName ? ` · 知识点 ${basis.kpName}` : ''}
            {' · '}可作答 {basis.answerableCount}
            {basis.totalCount ? ` / 共 ${basis.totalCount}` : ''} 题
            {basis.dropped > 0 ? ` · 已隔离 ${basis.dropped} 道科目不符题` : ''}
            {basis.noAnswer ? ' · 已回退浏览模式（不判分）' : ''}
          </Alert>
        )}

        {/* 单题可用性标记：仅记忆参考 / 不可作答（不渲染空白选项按钮） */}
        {questionMark(q) && (
          <Alert tone="warning" className="v3-quiz-mark">
            本题标记：<strong>{questionMark(q).label}</strong> —— {questionMark(q).desc}
          </Alert>
        )}

        <div className="v3-quiz-body">
          <div className="v3-quiz-progress">
            <Progress value={pct} />
            <span className="v3-quiz-progress__num">
              {memorize ? `${idx + 1}` : `${answeredCount}`}/{total}
            </span>
          </div>

          <p className="v3-quiz-stem">
            <span className="v3-quiz-stem__no">{idx + 1}.</span>
            <MathText text={q.content} />
          </p>

          {submitError && (
            <div role="alert" className="v3-quiz-submit-error">
              {submitError}
            </div>
          )}
          {saveError && (
            <div role="alert" className="v3-quiz-submit-error">
              {saveError}
              <Button size="sm" variant="text" onClick={persistProgress}>重试保存</Button>
            </div>
          )}

          {/* 题目配图：OCR/人工录入产出的 figure_crop 或原页图 */}
          {Array.isArray(q.images) && q.images.length > 0 && (
            <div className="v3-quiz-figs">
              {q.images.map((img, i) => (
                <img key={`${img.url}-${i}`} src={mediaSrc(img)} alt={`题目配图 ${i + 1}`} loading="lazy" />
              ))}
            </div>
          )}

          {/* 依赖原书插图的题目给出提示，避免用户对着「见下图」困惑 */}
          {q.figure_missing ? (
            <Alert tone="warning" className="v3-quiz-mark">
              本题题干含图，但原图尚未入库 —— 可先按文字作答，答案与解析不受影响。
            </Alert>
          ) : dependsOnFigure(q) && !(Array.isArray(q.images) && q.images.length) ? (
            <p className="v3-quiz-fig-note">本题依赖原书插图，答案见原书。</p>
          ) : null}

          {/* 选择题：点选即判 */}
          {isChoiceQ(q) && (
            <div
              className="v3-quiz-options"
              role={multiChoice ? 'group' : manualChoices ? 'radiogroup' : undefined}
              aria-label={multiChoice || manualChoices ? `${multiChoice ? '多选' : '单选'}题选项` : undefined}
            >
              {q.options.map((o, i) => {
                const isAns = !needsReview && isCorrectOption(i, rec?.correctAnswer ?? q.answer)
                const picked = Array.isArray(draft) ? draft.includes(i) : draft === i
                const wasBad =
                  revealed &&
                  !needsReview &&
                  !isAns &&
                  (Array.isArray(rec?.selected)
                    ? rec.selected.includes(letterOf(i))
                    : String(rec?.selected || '')
                        .toUpperCase()
                        .includes(letterOf(i)))
                let cls = 'v3-quiz-opt'
                if (!revealed && picked) cls += ' is-sel'
                if (revealed) {
                  if (isAns) cls += ' is-ok'
                  else if (wasBad) cls += ' is-bad'
                  else if (needsReview && picked) cls += ' is-review'
                  else cls += ' is-muted'
                  cls += ' is-disabled'
                }
                const content = (
                  <>
                    <span className="v3-quiz-opt__letter">
                      {revealed && isAns ? (
                        <CheckCircle2 size={16} />
                      ) : revealed && wasBad ? (
                        <X size={16} />
                      ) : manualChoices ? (
                        `${letterOf(i)}.`
                      ) : (
                        letterOf(i)
                      )}
                    </span>
                    <span className="v3-quiz-opt__body">
                      <MathText text={stripOptLabel(o)} />
                    </span>
                  </>
                )
                if (multiChoice) {
                  return (
                    <label key={i} className={cls}>
                      <input
                        className="v3-quiz-opt__input"
                        type="checkbox"
                        name={`question-${q.id}`}
                        checked={!!picked}
                        disabled={revealed}
                        onChange={() => toggleDraft(q.id, i)}
                      />
                      {content}
                    </label>
                  )
                }
                return (
                  <button
                    key={i}
                    type="button"
                    className={cls}
                    role={manualChoices ? 'radio' : undefined}
                    aria-checked={manualChoices ? !!picked : undefined}
                    disabled={revealed}
                    onClick={() => toggleDraft(q.id, i)}
                  >
                    {content}
                  </button>
                )
              })}
            </div>
          )}

          {/* 残缺选择题：答案是字母但 options 为空/全空。只读展示，**不渲染空白选项按钮**，禁止作答 */}
          {!isChoiceQ(q) && isChoiceWithoutOptions(q) && (
            <div className="v3-quiz-opt-none">
              <b>
                {questionMark(q)?.label === '不可作答' ? '本题不可作答' : '本题无选项'}
                {adaptedSubmit
                  ? '，暂无可显示答案'
                  : q.answer ? `，答案：${q.answer}` : '，且无参考答案'}
              </b>
              <span>{questionMark(q)?.desc || '题库缺少该题选项内容，仅供记忆参考，不可作答。'}</span>
            </div>
          )}

          {/* 文本题：输入 + 对照自评 */}
          {isTextQuestion(q) && (
            <div>
              <Textarea
                className="v3-quiz-textarea"
                aria-label="作答输入框"
                placeholder="在此输入你的作答（填空 / 简答 / 计算过程 / 作图描述）…"
                value={textDraft[q.id] || ''}
                disabled={revealed || busy}
                onChange={(e) => {
                  if (revealed || busy || finishingRef.current) return
                  setTextDraft((p) => ({ ...p, [q.id]: e.target.value }))
                }}
              />
              {!revealed && !selfCheck && (
                <div className="v3-quiz-text-row">
                  {adaptedSubmit ? (
                    <>
                      <Input
                        type="number"
                        min={0}
                        max={Number(q.max_score) || Number(q.score) || 10}
                        aria-label="自评分"
                        placeholder="自评分"
                        value={selfScores[q.id] ?? ''}
                        disabled={busy}
                        onChange={(e) => {
                          setSelfScores((p) => ({ ...p, [q.id]: e.target.value }))
                          setSubmitError('')
                        }}
                      />
                      <Button
                        variant="filled"
                        disabled={busy || !(textDraft[q.id] || '').trim()}
                        onClick={doSubmit}
                      >
                        提交答案
                      </Button>
                      <span className="v3-quiz-keyhint">填写自评分后提交，服务端返回后再展示答案与解析</span>
                    </>
                  ) : (
                    <>
                      <Button variant="filled" disabled={busy} onClick={doSubmit}>
                        对照答案
                      </Button>
                      <Button
                        variant="tonal"
                        icon={<Sparkles size={14} />}
                        disabled={busy || !(textDraft[q.id] || '').trim() || !!aiGrades[q.id]?.loading}
                        onClick={gradeAI}
                      >
                        {aiGrades[q.id]?.loading ? 'AI 批改中…' : 'AI 批改'}
                      </Button>
                      <span className="v3-quiz-keyhint">对照后展开参考答案与解析，自评时才提交并携带自评分</span>
                    </>
                  )}
                </div>
              )}
              {/* P0-2 AI 批改结果（未判分/未自评时也直接展示在作答区下方） */}
              {!adaptedSubmit && aiGrades[q.id] &&
                (aiGrades[q.id].loading || aiGrades[q.id].error || aiGrades[q.id].evaluation) && (
                  <div className="v3-quiz-ai v3-quiz-ai-grade">
                    <div className="v3-quiz-ai-grade__head">
                      <Sparkles size={14} /> AI 批改建议
                      {aiGrades[q.id].score != null && (
                        <span className="v3-quiz-ai-grade__score">
                          AI 建议分：{Number(aiGrades[q.id].score)} / {aiGrades[q.id].max_score}
                        </span>
                      )}
                    </div>
                    {aiGrades[q.id].loading ? (
                      <span>AI 批改中…</span>
                    ) : aiGrades[q.id].error ? (
                      <span style={{ color: 'var(--v3-danger)' }}>{aiGrades[q.id].error}</span>
                    ) : (
                      <>
                        {aiGrades[q.id].score == null && (
                          <div style={{ color: 'var(--v3-text-3)' }}>AI 暂不可用，请参考标准答案自评。</div>
                        )}
                        <div>{aiGrades[q.id].evaluation}</div>
                        {/* P0-B 批改评分卡：verification 存在且非降级时展示 */}
                        <VerificationCard verification={aiGrades[q.id].verification} />
                      </>
                    )}
                  </div>
                )}
            </div>
          )}

          {/* 揭示区：判分结果 / 背题答案 / 文本题对照 */}
          {(revealed || selfCheck) && (
            <div className={`v3-quiz-reveal ${rec ? (needsReview ? 'is-review' : rec.correct ? 'is-ok' : 'is-bad') : ''}`}>
              <div className="v3-quiz-reveal__row">
                <span>
                  {adaptedSubmit ? (
                    <span className={`v3-quiz-reveal__ans${needsReview ? ' is-review' : ''}`}>
                      {needsReview ? '参考答案（待核对）' : '正确答案'}：{(rec?.correctAnswer ?? q.answer) || '—'}
                    </span>
                  ) : (
                    <>
                      {needsReview ? '参考答案（待核对）' : '正确答案'}：
                      <span className={`v3-quiz-reveal__ans${needsReview ? ' is-review' : ''}`}>{(rec?.correctAnswer ?? q.answer) || '—'}</span>
                    </>
                  )}
                </span>
                {rec && (
                  <span className={needsReview ? 'v3-quiz-reveal__review' : rec.correct ? 'v3-quiz-reveal__ok' : 'v3-quiz-reveal__bad'}>
                    {needsReview
                      ? '· 待确认 · 答案待人工核对，暂不判定对错'
                      : `· ${rec.correct ? '回答正确' : `你选了 ${rec.selected || '—'}`}${rec.syncStatus === 'local'
                        ? ` · 本地判分，后端未同步${rec.syncError ? `（${rec.syncError}）` : ''}`
                        : (!rec.correct ? ' · 已计入错题本' : '')}`}
                  </span>
                )}
                {selfCheck && <span>· 你的作答：{selfCheck.myAns}</span>}
              </div>

              {/* —— 解析区（M0）——
                  有 analysis 正常展示；没有则明确「暂无解析」，并给出「AI 生成解析」入口。
                  该入口复用项目现有 POST /api/ai/tutoring/explain，生成结果只在前端展示
                  且标注「未入库」，不做已写回题库的假承诺。 */}
              {(() => {
                const raw = rec?.analysis || selfCheck?.analysis || q.analysis
                const ai = aiAnalyses[q.id]
                return (
                  <div className="v3-quiz-reveal__analysis">
                    {raw ? (
                      <span>
                        解析：
                        <MathText text={raw} />
                      </span>
                    ) : (
                      <div>
                        <span style={{ color: 'var(--v3-text-3)' }}>解析：暂无解析</span>
                        {!ai?.content && (
                          <>
                            <Select
                              style={{ marginLeft: 12, fontSize: 'var(--v3-fs-12)' }}
                              aria-label="AI 生成解析的讲解模式"
                              value={tutorMode}
                              onChange={(e) => setTutorMode(e.target.value)}
                              title="AI 生成解析的讲解模式：真题=评分视角，教材=理解视角"
                            >
                              <option value="auto">自动（按题目来源）</option>
                              <option value="exam">真题模式（评分视角）</option>
                              <option value="textbook">教材模式（理解视角）</option>
                            </Select>
                            <Button
                              size="sm"
                              variant="ghost"
                              style={{ marginLeft: 8 }}
                              disabled={ai?.loading}
                              onClick={() => generateAnalysis(q)}
                            >
                              {ai?.loading ? 'AI 生成中…' : 'AI 生成解析'}
                            </Button>
                          </>
                        )}
                        {ai?.error && (
                          <span style={{ marginLeft: 12, color: 'var(--v3-danger)' }}>{ai.error}</span>
                        )}
                      </div>
                    )}
                    {ai?.content && (
                      <div className="v3-quiz-ai">
                        <div className="v3-quiz-ai__meta">
                          AI 生成解析（来源 {ai.provider || 'AI'} · 未入库，仅供参考
                          {ai.mode
                            ? ` · 按${ai.mode === 'exam' ? '真题模式（评分视角）' : ai.mode === 'textbook' ? '教材模式（理解视角）' : '通用模式'}讲解`
                            : ''}
                          ）
                        </div>
                        {ai.content}
                        {stuckMarked[q.id] ? (
                          <div className="v3-quiz-ai__stuck v3-quiz-stuck-ok">
                            ✓ 已加入盲点池：将在复习队列 / 周会议题中安排巩固
                          </div>
                        ) : (
                          <div className="v3-quiz-ai__stuck">
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={ai?.loading}
                              onClick={() => markStuck(q)}
                            >
                              仍未理解，加入盲点池
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })()}

              {/* P0-2 AI 批改结果：仅作为参考展示，不覆盖自评流程 */}
              {!adaptedSubmit && aiGrades[q.id] &&
                (aiGrades[q.id].loading || aiGrades[q.id].error || aiGrades[q.id].evaluation) && (
                  <div className="v3-quiz-ai v3-quiz-ai-grade">
                    <div className="v3-quiz-ai-grade__head">
                      <Sparkles size={14} /> AI 批改建议
                      {aiGrades[q.id].score != null && (
                        <span className="v3-quiz-ai-grade__score">
                          AI 建议分：{Number(aiGrades[q.id].score)} / {aiGrades[q.id].max_score}
                        </span>
                      )}
                    </div>
                    {aiGrades[q.id].loading ? (
                      <span>AI 批改中…</span>
                    ) : aiGrades[q.id].error ? (
                      <span style={{ color: 'var(--v3-danger)' }}>{aiGrades[q.id].error}</span>
                    ) : (
                      <>
                        {aiGrades[q.id].score == null && (
                          <div style={{ color: 'var(--v3-text-3)' }}>AI 暂不可用，请参考标准答案自评。</div>
                        )}
                        <div>{aiGrades[q.id].evaluation}</div>
                        {/* P0-B 批改评分卡：verification 存在且非降级时展示 */}
                        <VerificationCard verification={aiGrades[q.id].verification} />
                      </>
                    )}
                  </div>
                )}

              {/* P0-1 加入生词本：仅英语题/含英文单词的题展示 */}
              {isEnglishQuestion(q) && (
                <div className="v3-quiz-reveal__words">
                  <Button size="sm" variant="tonal" disabled={wordLoading} onClick={addWordsToVocab}>
                    {wordLoading ? '提取中…' : '加入生词本'}
                  </Button>
                  <span className="v3-quiz-keyhint">把本题出现的英文生词一键加入你的词库</span>
                </div>
              )}

              {selfCheck && (
                <div className="v3-quiz-text-row">
                  <Button variant="filled" disabled={busy} onClick={() => selfGrade(true)}>
                    我答对了
                  </Button>
                  <Button variant="danger" disabled={busy} onClick={() => selfGrade(false)}>
                    我答错了
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* 未作答提示：单选/判断点选即判；手动模式与多选仍需提交 */}
          {!revealed && !selfCheck && isChoiceQ(q) && (isMultiQ(q) || manualChoices) && (
            <p className="v3-quiz-keyhint">
              {isMultiQ(q) ? '勾选所有正确选项后，点「提交答案」判分。' : '选择答案后，点「提交答案」判分。'}
            </p>
          )}
        </div>

        <div className="v3-quiz-foot">
          <Button
            variant="ghost"
            icon={<ChevronLeft size={15} />}
            onClick={() => go(idx - 1)}
            disabled={idx === 0}
          >
            上一题
          </Button>
          <span className="v3-quiz-keyhint">
            <Keyboard size={13} /> 快捷键：A–F 选择 · Enter 提交/下一题 · ← → 切换
          </span>
          <div className="v3-quiz-foot__btns">
            <Button variant="ghost" icon={<Sparkles size={15} />} disabled={busy} onClick={() => navigate('/assistant')}>
              问 AI
            </Button>
            {!revealed && !selfCheck && isChoiceQ(q) && (isMultiQ(q) || manualChoices) && (
              <Button variant="filled" disabled={busy} onClick={doSubmit}>
                提交答案
              </Button>
            )}
            {/* 残缺选择题不可作答，允许直接跳到下一题 */}
            {isChoiceWithoutOptions(q) &&
              (idx + 1 < total ? (
                <Button
                  variant="filled"
                  trailingIcon={<ChevronRight size={15} />}
                  onClick={() => go(idx + 1)}
                >
                  下一题
                </Button>
              ) : (
                <Button variant="filled" onClick={finishPractice}>
                  {memorize ? '完成背题' : '交卷并查看报告'}
                </Button>
              ))}
            {(revealed || selfCheck) && idx + 1 < total && (
              <Button variant="filled" trailingIcon={<ChevronRight size={15} />} onClick={() => go(idx + 1)}>
                下一题
              </Button>
            )}
            {(revealed || selfCheck) && idx + 1 >= total && (
              <Button variant="filled" onClick={finishPractice}>
                {memorize ? '完成背题' : '交卷并查看报告'}
              </Button>
            )}
          </div>
        </div>
      </article>

      {/* 右侧答题卡（移动端折叠为底部抽屉） */}
      <Card className="v3-quiz-practice__sheet">
        <CardHead
          title="答题卡"
          sub={`${answeredCount}/${total} 已作答`}
          actions={<MessageSquare size={15} style={{ color: 'var(--v3-text-3)' }} />}
        />
        {renderSheetContent()}
      </Card>

      {isMobile && (
        <>
          {createPortal(
            <button type="button" className="v3-quiz-sheet-fab" onClick={() => setSheetOpen(true)}>
              <ListChecks size={16} />
              答题卡 {answeredCount}/{total}
            </button>,
            document.body,
          )}
          <Sheet open={sheetOpen} title="答题卡" onClose={() => setSheetOpen(false)}>
            <div className="v3-quiz-mobile-sheet">{renderSheetContent()}</div>
          </Sheet>
        </>
      )}
      {confirmDialog}
    </div>
  )
}

/* =====================================================================
 * P0-B 批改评分卡
 * 后端 /api/quiz/grade-subjective 的 verification 字段：
 *   {
 *     verified_score, dimensions: {accuracy, logic, format, completeness},
 *     sandbox: {verified, usable, value, expr}, summary
 *   }
 * - dimensions 每项可能是 {score, comment} 或 {score, reason}，兼容两种键名。
 * - verification 缺失 / dimensions 为空对象（降级）时不渲染卡片，不报错。
 * ===================================================================== */
const DIMENSION_LABELS = [
  ['accuracy', '准确性'],
  ['logic', '逻辑性'],
  ['format', '规范性'],
  ['completeness', '完整性'],
]

function VerificationCard({ verification }) {
  // 缺失或降级（dimensions 为空对象）时返回 null，不渲染卡片
  if (!verification || typeof verification !== 'object') return null
  const dims = verification.dimensions
  const hasDims = dims && typeof dims === 'object' && Object.keys(dims).length > 0
  const hasSummary = !!verification.summary
  const hasScore = verification.verified_score != null
  const sandbox = verification.sandbox
  const sandboxOk = sandbox && sandbox.verified === true && sandbox.usable === true
  if (!hasDims && !hasSummary && !hasScore && !sandbox) return null

  return (
    <div className="v3-quiz-verification">
      {(hasScore || hasSummary) && (
        <div className="v3-quiz-verification__head">
          <span className="v3-quiz-verification__title">批改评分卡</span>
          {hasScore && (
            <span className="v3-quiz-verification__score">
              复核得分：{Number(verification.verified_score)} /{' '}
              {verification.max_score != null ? verification.max_score : '—'}
            </span>
          )}
        </div>
      )}
      {hasSummary && <div className="v3-quiz-verification__summary">{verification.summary}</div>}

      {hasDims && (
        <div className="v3-quiz-verification__grid">
          {DIMENSION_LABELS.map(([key, label]) => {
            const item = dims[key]
            if (!item || typeof item !== 'object') return null
            const score = item.score != null ? Number(item.score) : null
            const comment = item.comment || item.reason || ''
            return (
              <div key={key} className="v3-quiz-verification__dim">
                <span className="v3-quiz-verification__dim-name">{label}</span>
                <span className="v3-quiz-verification__dim-score">{score != null ? score : '—'}</span>
                <span className="v3-quiz-verification__dim-comment">{comment}</span>
              </div>
            )
          })}
        </div>
      )}

      {sandbox && (
        <div className={`v3-quiz-verification__sandbox ${sandboxOk ? 'is-ok' : 'is-na'}`}>
          {sandboxOk
            ? `沙箱验算通过：${sandbox.expr || ''} = ${sandbox.value != null ? sandbox.value : '—'}`
            : '沙箱验算不可用'}
        </div>
      )}
    </div>
  )
}
