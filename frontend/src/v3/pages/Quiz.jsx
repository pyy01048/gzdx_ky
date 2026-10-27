import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { toast } from '../../components/UI'
import { quizApi, fetchAllPages } from '../../api/client'
import {
  normQ, loadFavs, saveFavs, SOURCE_KINDS, SOURCE_KIND_LABEL,
} from './quizShared'
import { hydrateFavs, migrateLocalFavs } from '../../api/quizFavSync'
import QuizHome from './QuizHome'
import QuizPractice from './QuizPractice'
import QuizResult from './QuizResult'
import '../styles/quiz-container.css'

/* =====================================================================
 * 刷题中心（V9 重做）· 容器 / 会话引擎
 * 信息架构移植自参考件 D:\桌面\1（Next.js 纯选择题训练）：
 *   首页 Hero+统计带 / 三入口 Tab（知识点·年份·错题收藏）/
 *   右侧答题卡 / 先选后提交 / 练习·背题双模式 / 键盘快捷键 /
 *   收藏星标 / 结果报告（正确率大字+知识点掌握+重练错题）。
 * 视觉全部走 V8 学术蓝设计令牌（quiz-container.css 新增 class，不碰 global/v2）。
 *
 * V10 工程拆分（结构重构，行为不变）：
 *   Quiz.jsx          容器：视图路由 + 会话引擎（beginSession/startWithFilter）
 *                     + 跨视图共享状态（session/records/favs/kpFilter/tutorMode 等）
 *   QuizHome.jsx      首页：Hero 统计 / 来源 Tab / 三入口 / 自定义练习设置
 *   QuizYear.jsx      按年份：真题套卷索引 / 年份聚合 / 题号网格（懒加载分组）
 *   QuizReview.jsx    错题与收藏：错题本 / 收藏列表 / 错题闭环面板
 *   QuizPractice.jsx  答题区：单题作答 / 判分 / 答题卡 / 键盘快捷键 / AI 生成解析
 *   QuizResult.jsx    复盘：正确率报告 / 章节掌握 / 重练错题 / AI 讲题
 *   quizShared.js     纯函数与 localStorage 工具（原 Quiz.jsx 模块级定义原样拆出）
 * 纯函数/存储工具集中维护于 quizShared.js，此处转供以保持既有导入面不变。
 * ===================================================================== */
export * from './quizShared'

export default function Quiz() {
  const [searchParams] = useSearchParams()
  const routeParams = useParams()
  const urlSubject = searchParams.get('subject') || ''
  /* 真题深链：/exam/:year/:paper/:qno —— 刷新/分享都能回到同一套卷、同一题 */
  const urlYear = routeParams.year || ''
  const urlPaper = routeParams.paper || ''
  const urlQno = routeParams.qno || ''
  const urlChapter = searchParams.get('chapter') || ''
  const urlType = searchParams.get('question_type') || ''
  /* 知识点级精确筛选（M1-3 全景页 startPractice 传入）。
     存在 kp_id 时按知识点拉题，否则保持原有 subject/chapter 降级逻辑不变。 */
  const urlKpId = searchParams.get('kp_id') || ''
  const urlKpName = searchParams.get('kp_name') || ''

  /* ---------- M0 刷题中心：来源大类（真题 / 教材题 分页隔离） ---------- */
  /* 默认 'exam'：真题与教材题**不混在一个列表里**；用户显式切到 'all' 才混合。 */
  const urlSourceKind = searchParams.get('source_kind') || ''
  const [sourceKind, setSourceKind] = useState(
    SOURCE_KINDS.some((s) => s.id === urlSourceKind) ? urlSourceKind : 'exam'
  )
  /* P0-6 的默认来源探测放在 QuizHome 里（sourceKind 的 UI 归属页，且那里已有
     一次 exam 探测，避免两处各发一遍相同请求）。本页只负责持有 sourceKind。 */

  /* ---------- 视图与跨视图共享状态 ---------- */
  const [view, setView] = useState('home')            // home | practice | result
  const [mode, setMode] = useState('practice')       // practice | memorize
  const [backendOk, setBackendOk] = useState(true)
  /* 提交中：首页「整科练习」按钮禁用 与 答题区判分按钮共用同一把锁 */
  const [submitting, setSubmitting] = useState(false)

  /* ---------- 练习会话（practice / result 共享） ---------- */
  const [session, setSession] = useState(null)      // {title, questions:[], mode, noAnswer, startIdx}
  const [basis, setBasis] = useState(null)
  const [records, setRecords] = useState({})        // 已判分 {qid:{correct,selected,correctAnswer,analysis}}
  const startedFromRef = useRef(null)               // 记录会话来源，便于「再练一次」

  /* ---------- 收藏 / 知识点筛选标识 / 讲题模式（跨视图共享） ---------- */
  const [favs, setFavs] = useState(loadFavs)
  const [kpFilter, setKpFilter] = useState(null)    // { id, name } | null
  /* 知识点筛选无题时的空态（避免白屏）：{ name } | null */
  const [kpEmpty, setKpEmpty] = useState(null)
  const [tutorMode, setTutorMode] = useState('auto')

  /* 收藏切换 */
  const toggleFav = (q) => {
    setFavs((prev) => {
      const next = { ...prev }
      if (next[q.id]) delete next[q.id]
      else next[q.id] = { content: q.content, subject: q.subject, chapter: q.chapter, type: q.question_type }
      saveFavs(next)
      return next
    })
  }

  /* 判分结果写回（QuizPractice → 容器，供 Result 复盘消费） */
  const onRecord = useCallback((qid, entry) => {
    setRecords((prev) => ({ ...prev, [qid]: entry }))
  }, [])

  /* ================= 会话开始 ================= */
  const beginSession = useCallback((title, questions, modeUsed, startIdx = 0, noAnswer = false, basisInfo = null) => {
    if (!questions || !questions.length) { toast('当前筛选条件下暂无题目'); return }
    const si = Math.max(0, Math.min(startIdx, questions.length - 1))
    setSession({ title, questions, mode: modeUsed || mode, noAnswer, startIdx: si })
    /* 依据明示：本次练习的来源/科目/知识点/可作答口径，练习页顶部原样展示 */
    setBasis(basisInfo)
    setRecords({})
    startedFromRef.current = { title, questions, mode: modeUsed || mode }
    setView('practice')
    window.scrollTo({ top: 0 })
  }, [mode])

  /* 按筛选条件向后端拉题并开始（真题/教材题分区 · 知识点精确 · 章节 · 整科）。

     统一口径（M0）：所有入口只走这**一个** quizApi.questions 调用，参数收敛为
     `subject / source_kind / answerable / kp_id / chapter / question_type / year / paper / mode`。
     source_kind 由顶部「历年真题 / 教材题 / 全部来源」Tab 决定（真题与教材题默认分离）。

     科目严格隔离（双保险）：后端已按 subject 精确过滤，这里再做一次**前端一致性校验**——
     凡返回题目 subject 与请求 subject 不一致的（历史脏数据/关联串科目）直接剔除并提示，
     杜绝「切到数电却刷出政治题」的混用。 */
  const startWithFilter = useCallback(async ({ subject, chapter, question_type, kp_id, kp_name, title, source_kind }) => {
    setSubmitting(true)
    const sk = source_kind !== undefined ? source_kind : sourceKind
    const baseParams = {
      subject: subject || undefined,
      chapter: chapter || undefined,
      question_type: question_type || undefined,
      kp_id: kp_id || undefined,
      source_kind: sk && sk !== 'all' ? sk : undefined,
    }
    try {
      const d = await quizApi.questions({ ...baseParams, answerable: true, page: 1, page_size: 100 })
      let qs = (d?.questions || d?.items || []).map(normQ)
      let answerableCount = d?.answerable_count ?? qs.length
      let totalCount = d?.total_count ?? qs.length
      let noAnswer = false
      /* 可作答题为 0（多数科目题库尚未回填标准答案）时，回退取全部题进入「浏览模式」，
         避免「点开始练习无反应」；浏览模式不判分、不进错题本（见 gradeChoice/applyGrade）。 */
      if (!qs.length) {
        const d2 = await quizApi.questions({ ...baseParams, answerable: false, page: 1, page_size: 100 })
        const qs2 = (d2?.questions || d2?.items || []).map(normQ)
        if (d2?.total_count != null) totalCount = d2.total_count
        answerableCount = d2?.answerable_count ?? 0
        if (qs2.length) { qs = qs2; noAnswer = true }
      }
      /* 来源回退（M0 体验修复）：当前「真题/教材题」Tab 下该科目 0 题（如数电/模电/
         数据结构等科目题目全部来自教材/开源题库，默认「真题」Tab 恒为空），自动切到
         「全部来源」再取一次，避免用户选科后看到「暂无题目」误以为选科不生效。
         仅在 subject 级入口触发；显式带 kp_id/chapter 时同样受益（0 题则回退）。 */
      let sourceFallback = false
      if (!qs.length && sk && sk !== 'all') {
        const allParams = { ...baseParams, source_kind: undefined }
        const dAll = await quizApi.questions({ ...allParams, answerable: true, page: 1, page_size: 100 })
        let qsAll = (dAll?.questions || dAll?.items || []).map(normQ)
        if (!qsAll.length) {
          const dAll2 = await quizApi.questions({ ...allParams, answerable: false, page: 1, page_size: 100 })
          qsAll = (dAll2?.questions || dAll2?.items || []).map(normQ)
          if (dAll2?.total_count != null) totalCount = dAll2.total_count
          answerableCount = dAll2?.answerable_count ?? 0
          if (qsAll.length) { qs = qsAll; noAnswer = true }
        } else {
          totalCount = dAll?.total_count ?? qsAll.length
          answerableCount = dAll?.answerable_count ?? qsAll.length
          qs = qsAll
        }
        if (qsAll.length) sourceFallback = true
      }
      /* —— 前端科目一致性校验（科目严格隔离的第二道闸）—— */
      let dropped = 0
      if (subject) {
        const before = qs.length
        qs = qs.filter((x) => x.subject === subject)
        dropped = before - qs.length
        if (dropped > 0) toast(`已隔离 ${dropped} 道科目不符的题目（当前科目：${subject}）`)
      }
      setBackendOk(true)
      /* 记录本次是否为知识点级筛选，供界面标识与空态判断使用 */
      const kp = kp_id ? { id: String(kp_id), name: kp_name || `#${kp_id}` } : null
      setKpFilter(kp)
      /* 知识点级筛选命中 0 题：给出显式 Empty 兜底，不进入空会话（避免白屏） */
      if (kp && !qs.length) {
        setKpEmpty({ name: kp.name })
        setSubmitting(false)
        return
      }
      setKpEmpty(null)
      if (noAnswer) toast('该筛选下暂无标准答案题，已载入题库题目（浏览模式：不判分、不进错题本）')
      if (sourceFallback) {
        toast(`当前「${SOURCE_KIND_LABEL[sk] || sk}」下该科目 0 题，已自动切换为全部来源（${totalCount || qs.length} 题）`)
      }
      const basisInfo = {
        title,
        subject: subject || null,
        chapter: chapter || null,
        kpName: kp?.name || null,
        sourceKind: sourceFallback ? 'all' : (sk || 'all'),
        sourceKindLabel: sourceFallback ? '全部来源' : (SOURCE_KIND_LABEL[sk] || '全部来源'),
        sourceFallback,
        noAnswer,
        loaded: qs.length,
        answerableCount: answerableCount || 0,
        totalCount: totalCount || qs.length,
        dropped,
      }
      beginSession(title, qs, mode, 0, noAnswer, basisInfo)
    } catch (e) {
      setBackendOk(false)
      /* 后端不可用时不启动会话。以前这里塞两道本地演示题（LOCAL_FALLBACK）：
         页面呈现为一个正常练习，用户做完还拿到判分与正确率，而那分数毫无意义。 */
      setKpEmpty(null)
      toast(`题库加载失败：${e.message || '后端不可用'}，请确认后端已启动后重试`)
    } finally { setSubmitting(false) }
  }, [beginSession, mode, sourceKind])

  /* 收藏统一（S7）：把历史 localStorage 收藏与后端 favorites 表对齐。
     1) hydrateFavs 拉后端全量、与本地取并集回填缓存（另一端的收藏也能看到）；
     2) 若发现"本地有、后端无"的（历史遗留），一次性补推上去。
     全程静默：失败就保持纯离线可用，不打断刷题。 */
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const { localOnly } = await hydrateFavs()
        if (!alive || !localOnly) return
        const { migrated } = await migrateLocalFavs()
        if (alive && migrated > 0) {
          // 迁移成功才刷新 UI 态，避免无变更时的无谓重渲染
          setFavs(loadFavs())
        }
      } catch {
        /* 网络/后端不可用：本地缓存仍可正常工作 */
      }
    })()
    return () => { alive = false }
  }, [])

  /* 真题深链：/exam/2024/数学一/3 直接载入整套并定位第 3 题。
     数据仍走 /api/quiz/questions 的 year/paper 过滤，不另造一套真题数据源。 */
  useEffect(() => {
    if (!urlYear && !urlPaper) return
    let alive = true
    ;(async () => {
      try {
        const rows = await fetchAllPages(
          (p) => quizApi.questions({
            ...p,
            year: urlYear || undefined,
            paper: urlPaper || undefined,
            source_kind: 'exam',
            mode: 'sequential',
          }),
          { keys: ['questions'] },
        )
        if (!alive) return
        if (!rows.length) {
          toast('该套真题暂无题目数据')
          return
        }
        const qs = rows.map(normQ)
        const startIdx = Math.max(0, Math.min((parseInt(urlQno, 10) || 1) - 1, qs.length - 1))
        const title = [urlYear && `${urlYear} 年`, urlPaper].filter(Boolean).join(' · ')
        beginSession(title || '真题套卷', qs, mode, startIdx, false, {
          title, subject: null, chapter: null, kpName: null,
          sourceKind: 'exam', sourceKindLabel: '历年真题',
          noAnswer: false, loaded: qs.length,
          answerableCount: null, totalCount: qs.length, dropped: 0,
        })
      } catch (e) {
        if (alive) toast(`真题加载失败：${e?.message || '后端不可用'}`)
      }
    })()
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlYear, urlPaper, urlQno])

  /* QuizSection 深链：?subject=&chapter= 直达该章练习；
     ?kp_id=&kp_name= 直达该知识点精确刷题。 */
  useEffect(() => {
    if ((urlChapter || urlKpId) && view === 'home') {
      const title = urlKpName
        ? `知识点 · ${urlKpName}`
        : `${urlSubject || ''} · ${urlChapter || ''}`.trim()
      startWithFilter({
        subject: urlSubject,
        chapter: urlChapter,
        question_type: urlType,
        kp_id: urlKpId,
        kp_name: urlKpName,
        title
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /* ---------- 视图切换 ---------- */
  const goHome = () => { setView('home'); setSession(null); window.scrollTo({ top: 0 }) }
  const finishSession = () => { setView('result'); window.scrollTo({ top: 0 }) }
  /* 清除知识点筛选：清标识 + 清空态 + 回首页（与拆分前两个入口的点击效果一致） */
  const clearKpFilter = () => { setKpFilter(null); setKpEmpty(null); goHome() }

  return (
    <>
      {/* 首页常驻挂载（仅 visible 时渲染）：tab/选中科目/分组缓存等首页状态跨练习保留，
          与拆分前「返回题库不重置首页」的行为一致 */}
      <QuizHome
        visible={view === 'home'}
        mode={mode}
        setMode={setMode}
        sourceKind={sourceKind}
        setSourceKind={setSourceKind}
        backendOk={backendOk}
        setBackendOk={setBackendOk}
        kpFilter={kpFilter}
        kpEmpty={kpEmpty}
        favs={favs}
        submitting={submitting}
        onBeginSession={beginSession}
        onStartWithFilter={startWithFilter}
        onClearKp={clearKpFilter}
      />
      {view === 'practice' && session && (
        <QuizPractice
          session={session}
          records={records}
          basis={basis}
          favs={favs}
          kpFilter={kpFilter}
          backendOk={backendOk}
          tutorMode={tutorMode}
          setTutorMode={setTutorMode}
          submitting={submitting}
          setSubmitting={setSubmitting}
          onRecord={onRecord}
          onToggleFav={toggleFav}
          onGoHome={goHome}
          onFinish={finishSession}
        />
      )}
      {view === 'result' && session && (
        <QuizResult
          session={session}
          records={records}
          startedFromRef={startedFromRef}
          tutorMode={tutorMode}
          setTutorMode={setTutorMode}
          onBeginSession={beginSession}
          onGoHome={goHome}
        />
      )}
    </>
  )
}
