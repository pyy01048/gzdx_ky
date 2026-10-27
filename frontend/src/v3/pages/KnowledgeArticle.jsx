import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { taxonomyApi, quizApi, reviewApi } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, Badge, Button, Card, CardHead, Empty, IconButton, PageHeader, Progress, Ring,
  Skeleton, Spinner, cx, toastErr, toastOk,
} from '../ui'
import {
  AlertCircle, BookOpen, Brain, CalendarClock, ChevronDown, ChevronLeft, ChevronRight,
  Clock, FileText, Lightbulb, Map, Play, Quote, RefreshCw, Sparkles, Target,
} from '../icons'
import '../styles/kb-v3.css'

/* ==========================================================================
   知识点精读 · Aurora v3

   阅读动线完全沿用旧版：
     考纲要求 → 教材原文（OCR 质量门）→ 主动回忆 → 关联真题 → 掌握度自评
   左栏目录随滚动高亮，右栏给同章节知识点、前后篇与复习留痕。
   数据来源：/taxonomy/knowledge-points/{id}、/quiz/questions、/taxonomy/tree。
   ========================================================================== */

const STATE_LABEL = { unlearned: '未学', weak: '薄弱', mastered: '已掌握' }

const STATE_BADGE = {
  unlearned: undefined,
  weak: 'warning',
  mastered: 'success',
}

const TYPE_LABEL = {
  single: '单选',
  judge: '判断',
  fill: '填空',
  essay: '简答',
  calc: '计算',
  draw: '作图',
}

const RESULT_META = {
  mastered: { label: '会', tone: 'ok' },
  fuzzy: { label: '模糊', tone: 'warn' },
  forgotten: { label: '不会', tone: 'danger' },
}

/** 6 级自评（对齐 SM-2 的 q=0..5），文案面向考研场景而非算法术语 */
const GRADES = [
  { q: 0, key: '完全不会', desc: '重新学', tone: 'again' },
  { q: 1, key: '想不起来', desc: '1 天后', tone: 'hard' },
  { q: 2, key: '很吃力', desc: '2 天后', tone: 'hard' },
  { q: 3, key: '勉强记得', desc: '4 天后', tone: 'mid' },
  { q: 4, key: '基本掌握', desc: '7 天后', tone: 'good' },
  { q: 5, key: '脱口而出', desc: '15 天后', tone: 'easy' },
]

function typeLabel(t) {
  return TYPE_LABEL[t] || t || ''
}

function pointState(kp) {
  if (kp && STATE_LABEL[kp.state]) return kp.state
  const m = Number(kp && kp.mastery) || 0
  if (m >= 70) return 'mastered'
  return kp && kp.review_count > 0 ? 'weak' : 'unlearned'
}

/** 把知识点正文按空行切成段落，保留教材原文的行内结构 */
function toParagraphs(text) {
  return (text || '')
    .split(/\n{2,}/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/**
 * 教材原文可用性判定（与旧版一致，保守，宁可少显示也不误导）：
 *   · 中文占比 < 45% 且长度 > 40 → 严重乱码
 *   · 连续 3 个以上非中非 ASCII 罕见符号 → 严重乱码
 * 轻度夹杂仍展示，因为主体内容可读。
 */
function isReadable(text) {
  const t = (text || '').trim()
  if (t.length < 12) return false
  const cjk = (t.match(/[\u4e00-\u9fff]/g) || []).length
  const ratio = cjk / t.length
  if (t.length > 40 && ratio < 0.45) return false
  if (/[^\u4e00-\u9fff\w\s。，、；：？！（）《》“”‘’…—－·+=×÷∑∫√≤≥≈∞πΩμ°±→←↑↓％%\/\\()\[\]{}<>.,;:'"?!-]{3,}/.test(t)) {
    return false
  }
  return true
}

/**
 * 从知识点元数据生成主动回忆问题。
 * 只生成能从已有字段可靠回答的问题，不编造内容。
 */
function buildRecall(kp) {
  const out = []
  if (kp.description) {
    out.push({
      q: `「${kp.name}」的考纲要求是什么？`,
      a: kp.description,
    })
  }
  if ((kp.question_types || []).length) {
    out.push({
      q: '这一考点在考试中通常以哪些题型出现？',
      a: `常见题型：${kp.question_types.join('、')}。复习时应按题型分别训练作答节奏。`,
    })
  }
  if (kp.review_count > 0) {
    out.push({
      q: '我目前的掌握情况如何？',
      a: `已复习 ${kp.review_count} 次，当前掌握度 ${kp.mastery}%，`
        + `当前复习间隔 ${kp.interval || 0} 天，难度系数 ${Number(kp.ease_factor || 2.5).toFixed(2)}。`,
    })
  }
  if (!out.length) {
    out.push({ q: '本知识点暂无可用于自测的结构化信息。', a: '请先补充教材资料或考纲说明。' })
  }
  return out
}

function fmtDate(value) {
  return value ? String(value).slice(0, 10) : '—'
}

export default function KnowledgeArticle() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()

  const [kp, setKp] = useState(null)
  const [status, setStatus] = useState('loading')
  const [errMsg, setErrMsg] = useState('')
  const [errStatus, setErrStatus] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  const [quiz, setQuiz] = useState([])
  const [quizTotal, setQuizTotal] = useState(null)
  const [quizState, setQuizState] = useState('idle')
  const [quizError, setQuizError] = useState('')
  const [quizReloadKey, setQuizReloadKey] = useState(0)

  const [siblings, setSiblings] = useState([])
  const [neighbors, setNeighbors] = useState({ prev: null, next: null })

  const [activeAnchor, setActiveAnchor] = useState('')
  const [openRecall, setOpenRecall] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const loadSeq = useRef(0)

  const load = useCallback(async ({ silent = false } = {}) => {
    const seq = ++loadSeq.current
    if (silent) setRefreshing(true)
    else setStatus('loading')
    setErrMsg('')
    setErrStatus(null)
    try {
      const d = await taxonomyApi.knowledgePoint(id)
      if (seq !== loadSeq.current) return
      // HTTP 200 + 空响应体也可能发生，此时走「未找到」空态而不是崩成白屏
      if (!d) {
        setStatus('error')
        setErrStatus(404)
        setErrMsg('未找到该知识点（可能已被删除）')
        return
      }
      setKp(d)
      setStatus('ok')
    } catch (e) {
      if (seq !== loadSeq.current) return
      setStatus('error')
      setErrStatus(e?.status || null)
      setErrMsg(e?.message || '知识点加载失败')
    } finally {
      if (seq === loadSeq.current) setRefreshing(false)
    }
  }, [id])

  useEffect(() => {
    setKp(null)
    setActiveAnchor('')
    setOpenRecall(null)
    setSiblings([])
    setNeighbors({ prev: null, next: null })
    try {
      window.scrollTo({ top: 0 })
    } catch {
      /* 非浏览器环境（如测试）没有滚动实现，忽略即可 */
    }
    load()
  }, [load])

  /* 关联题目：按知识点 id 精准取；未登录访客不请求登录态接口 */
  useEffect(() => {
    let alive = true
    setQuiz([])
    setQuizTotal(null)
    setQuizError('')
    if (!user) {
      setQuizState('guest')
      return () => { alive = false }
    }
    setQuizState('loading')
    quizApi.questions({ kp_id: id, page_size: 6 })
      .then((d) => {
        if (!alive) return
        const items = Array.isArray(d) ? d : (d?.questions || d?.items || [])
        setQuiz(items)
        setQuizTotal(
          !Array.isArray(d) && typeof d?.total === 'number' ? d.total : items.length,
        )
        setQuizState('ok')
      })
      .catch((e) => {
        if (!alive) return
        setQuiz([])
        setQuizState('error')
        setQuizError(e?.message || '关联题目加载失败')
      })
    return () => { alive = false }
  }, [id, user, quizReloadKey])

  /* 同章节知识点：形成「接着阅读」动线；后端章节字段是 title（兼容老数据的 name） */
  useEffect(() => {
    let alive = true
    if (!kp?.chapter || !kp?.subject) {
      setSiblings([])
      setNeighbors({ prev: null, next: null })
      return () => { alive = false }
    }
    taxonomyApi.tree(kp.subject)
      .then((payload) => {
        if (!alive) return
        // 后端返回 { tree: [...] }；兼容旧测试夹具直接给数组的写法
        const nodes = Array.isArray(payload) ? payload : (payload?.tree || [])
        const node = nodes.find((n) => n.subject === kp.subject)
        const ch = (node?.chapters || []).find((c) => (c.title ?? c.name) === kp.chapter)
        const list = ch?.knowledge_points || []
        const i = list.findIndex((x) => String(x.id) === String(kp.id))
        setSiblings(list)
        setNeighbors({
          prev: i > 0 ? list[i - 1] : null,
          next: i >= 0 && i < list.length - 1 ? list[i + 1] : null,
        })
      })
      .catch(() => {
        if (!alive) return
        setSiblings([])
        setNeighbors({ prev: null, next: null })
      })
    return () => { alive = false }
  }, [kp?.subject, kp?.chapter, kp?.id])

  /* 正文段落（教材原文）—— 过滤 OCR 严重乱码块 */
  const sourceParagraphs = useMemo(() => {
    const chunks = kp?.related_chunks || []
    return chunks
      .filter((c) => isReadable(c.text))
      .map((c) => ({
        text: c.text || '',
        doc: c.doc_name || '',
        docId: c.document_id,
        chunkId: c.chunk_id,
      }))
  }, [kp])

  /** 被质量门拦下的原文块数（如实告知，而不是静默隐藏） */
  const droppedCount = useMemo(() => {
    const chunks = kp?.related_chunks || []
    return chunks.filter((c) => c.text && !isReadable(c.text)).length
  }, [kp])

  const recallQuestions = useMemo(() => (kp ? buildRecall(kp) : []), [kp])
  const reviewHistory = useMemo(
    () => (Array.isArray(kp?.review_history) ? kp.review_history : []),
    [kp],
  )
  const relatedPoints = useMemo(
    () => siblings
      .filter((p) => String(p.id) !== String(kp?.id))
      .slice(0, 8),
    [siblings, kp?.id],
  )

  const quizVisible = quiz.length > 0
    || (!!user && (quizState === 'loading' || quizState === 'error'))
    // 已登录且明确查到 0 题：也渲染区块，给出「暂无关联题 + 去全部题」友好空态
    || (!!user && quizState === 'ok' && quizTotal === 0)

  /* 本页目录：由实际渲染的区块动态生成 */
  const sections = useMemo(() => {
    const out = []
    if (kp?.description) out.push({ id: 'sec-require', label: '考纲要求' })
    out.push({ id: 'sec-source', label: '教材原文' })
    out.push({ id: 'sec-recall', label: '主动回忆' })
    if (quizVisible) out.push({ id: 'sec-quiz', label: '关联真题' })
    out.push({ id: 'sec-mastery', label: '掌握度自评' })
    return out
  }, [kp, quizVisible])

  const sectionNo = useCallback((sectionId) => {
    const i = sections.findIndex((s) => s.id === sectionId)
    return i >= 0 ? i + 1 : 1
  }, [sections])

  /* 滚动高亮目录：IntersectionObserver 而非 scroll 事件 */
  useEffect(() => {
    if (status !== 'ok' || typeof IntersectionObserver === 'undefined') return undefined
    const nodes = sections
      .map((s) => document.getElementById(s.id))
      .filter(Boolean)
    if (!nodes.length) return undefined
    const ob = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActiveAnchor(visible[0].target.id)
      },
      { rootMargin: '-96px 0px -58% 0px', threshold: [0, 1] },
    )
    nodes.forEach((n) => ob.observe(n))
    return () => ob.disconnect()
  }, [sections, status])

  const scrollToSection = useCallback((sectionId) => {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  /** 提交掌握度自评 → 后端重排下次复习时间 */
  const submitGrade = async (q) => {
    if (!user) {
      navigate('/login')
      return
    }
    if (submitting) return
    setSubmitting(true)
    try {
      // 六档自评 → 旧三档 result（决定掌握度）+ FSRS 四档 rating（决定间隔）
      const mapping = q <= 1
        ? { result: 'forgotten', rating: 1 }
        : q === 2
          ? { result: 'fuzzy', rating: 2 }
          : q === 3
            ? { result: 'fuzzy', rating: 3 }
            : { result: 'mastered', rating: 4 }
      const r = await reviewApi.submit({
        item_type: 'knowledge',
        item_id: Number(id),
        ...mapping,
      })
      const days = r?.fsrs?.interval_days ?? r?.interval
      const grade = GRADES.find((g) => g.q === q)
      toastOk(
        `已记录：${grade?.key || ''}，`
        + (days ? `下次复习在 ${days} 天后` : '下次复习已重排'),
      )
      try {
        const fresh = await taxonomyApi.knowledgePoint(id)
        if (fresh) setKp(fresh)
      } catch {
        /* 记录已成功，刷新失败时保留当前展示 */
      }
    } catch {
      toastErr('记录失败，请确认后端服务可用')
    } finally {
      setSubmitting(false)
    }
  }

  const mapHref = useCallback((options = {}) => {
    if (!kp) return '/knowledge'
    const opts = typeof options === 'boolean'
      ? { withKp: options }
      : options
    const withChapter = opts.withChapter !== false
    const withKp = opts.withKp === true
    const p = new URLSearchParams()
    if (kp.subject) p.set('subject', kp.subject)
    if (withChapter && kp.chapter) p.set('chapter', kp.chapter)
    if (withKp && kp.id != null) p.set('kp_id', kp.id)
    const qs = p.toString()
    return qs ? `/knowledge?${qs}` : '/knowledge'
  }, [kp])

  const practice = useCallback(() => {
    if (!kp) return
    const p = new URLSearchParams()
    if (kp.subject) p.set('subject', kp.subject)
    if (kp.chapter) p.set('chapter', kp.chapter)
    p.set('kp_id', kp.id ?? id)
    if (kp.name) p.set('kp_name', kp.name)
    navigate(`/quiz?${p.toString()}`)
  }, [kp, id, navigate])

  const backAction = (
    <Button
      variant="tonal"
      icon={<ChevronLeft size={16} />}
      onClick={() => navigate(kp ? mapHref(true) : '/knowledge')}
    >
      知识地图
    </Button>
  )

  const refreshAction = (
    <IconButton
      label="刷新知识点"
      icon={<RefreshCw size={17} className={cx(refreshing && 'v3-ka-spin')} />}
      onClick={() => load({ silent: status === 'ok' })}
      disabled={status === 'loading' || refreshing}
    />
  )

  if (status === 'loading') {
    return (
      <div className="v3-stack v3-ka-page">
        <PageHeader
          eyebrow="KNOWLEDGE · 知识点精读"
          title="知识点精读"
          sub="正在加载考纲要求、教材原文与复习状态…"
          actions={<>{backAction}{refreshAction}</>}
        />
        <div className="v3-ka-layout">
          <Card className="v3-ka-toc v3-ka-skeleton-card">
            <Skeleton height={12} width="46%" />
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} height={14} width={`${82 - i * 9}%`} />
            ))}
          </Card>
          <Card className="v3-ka-sheet">
            <div className="v3-ka-sheet__inner v3-ka-skeleton-sheet">
              <Skeleton height={30} width="62%" />
              <Skeleton height={13} width="38%" />
              <Skeleton height={92} />
              <Skeleton height={15} width="92%" />
              <Skeleton height={15} width="86%" />
              <Skeleton height={15} width="74%" />
              <Skeleton height={110} />
            </div>
          </Card>
          <div className="v3-ka-rail">
            {Array.from({ length: 2 }).map((_, i) => (
              <Card key={i} className="v3-ka-rail-card">
                <Skeleton height={16} width="48%" />
                <Skeleton height={44} />
                <Skeleton height={44} />
              </Card>
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (status === 'error') {
    const notFound = errStatus === 404
    return (
      <div className="v3-stack v3-ka-page">
        <PageHeader
          eyebrow="KNOWLEDGE · 知识点精读"
          title="知识点精读"
          sub="单点阅读：考纲 → 原文 → 回忆 → 自评"
          actions={<>{backAction}{refreshAction}</>}
        />
        <Card className="v3-ka-error-card">
          <Empty
            icon={<AlertCircle size={26} />}
            title={notFound ? '知识点不存在' : '知识点加载失败'}
            text={notFound
              ? '该知识点不存在或已被删除，请返回知识地图查看其他知识点。'
              : (errMsg || '请确认后端服务已启动后重试。')}
            action={(
              <div className="v3-ka-empty-actions">
                {notFound ? null : (
                  <Button variant="gradient" icon={<RefreshCw size={16} />} onClick={() => load()}>
                    重新加载
                  </Button>
                )}
                <Button variant="text" icon={<ChevronLeft size={16} />} onClick={() => navigate('/knowledge')}>
                  返回知识地图
                </Button>
              </div>
            )}
          />
        </Card>
      </div>
    )
  }

  if (!kp) return null

  const state = pointState(kp)
  const mastery = Math.min(100, Math.max(0, Number(kp.mastery) || 0))
  const questionTypes = kp.question_types || []

  return (
    <div className="v3-stack v3-ka-page">
      <nav className="v3-ka-crumb" aria-label="面包屑">
        <Link to="/knowledge" className="v3-ka-crumb__link">
          <Map size={13} />
          知识地图
        </Link>
        <ChevronRight size={12} className="v3-ka-crumb__sep" />
        <Link to={mapHref({ withChapter: false })} className="v3-ka-crumb__link">
          {kp.subject || '未分类'}
        </Link>
        <ChevronRight size={12} className="v3-ka-crumb__sep" />
        <Link to={mapHref({ withChapter: true })} className="v3-ka-crumb__link">
          {kp.chapter || '未分章'}
        </Link>
        <ChevronRight size={12} className="v3-ka-crumb__sep" />
        <span className="v3-ka-crumb__current" aria-current="page">{kp.name}</span>
      </nav>

      <PageHeader
        eyebrow="KNOWLEDGE · 知识点精读"
        title={kp.name}
        sub={`${kp.subject || '未分类'}${kp.chapter ? ` · ${kp.chapter}` : ''} · 考纲要求 → 教材原文 → 主动回忆 → 掌握度自评`}
        actions={<>{backAction}{refreshAction}</>}
      />

      {!user ? (
        <Alert tone="info" className="v3-ka-guest">
          <div className="v3-ka-guest__inner">
            <span>访客模式：考纲、教材原文与主动回忆可直接阅读；登录后可记录自评、查看关联真题与复习轨迹。</span>
            <Button size="sm" variant="text" onClick={() => navigate('/login')}>去登录</Button>
          </div>
        </Alert>
      ) : null}

      {/* 文章元信息 */}
      <Card variant="tonal" className="v3-ka-meta-card">
        <div className="v3-ka-meta">
          <Ring value={mastery} size={72} stroke={7} gradient>
            <div className="v3-ka-ring-center">
              <strong>{mastery}<em>%</em></strong>
              <span>掌握度</span>
            </div>
          </Ring>
          <div className="v3-ka-meta__main">
            <div className="v3-ka-meta__badges">
              <Badge tone={STATE_BADGE[state]}>{STATE_LABEL[state]}</Badge>
              {questionTypes.slice(0, 5).map((t) => (
                <Badge key={t} tone="outline">{typeLabel(t)}</Badge>
              ))}
              <Badge tone="outline">#{kp.id}</Badge>
            </div>
            <div className="v3-ka-meta__facts">
              <div>
                <span><Brain size={12} /> 复习</span>
                <b>{kp.review_count ?? 0} 次</b>
              </div>
              <div>
                <span><CalendarClock size={12} /> 下次复习</span>
                <b>{fmtDate(kp.next_review)}</b>
              </div>
              <div>
                <span><Sparkles size={12} /> 考频</span>
                <b>{kp.exam_frequency ?? '—'}</b>
              </div>
              <div>
                <span><Target size={12} /> 难度</span>
                <b>{kp.difficulty ?? '—'}</b>
              </div>
            </div>
          </div>
          <div className="v3-ka-meta__actions">
            <Button variant="gradient" icon={<Play size={15} />} onClick={practice}>
              开始练习
            </Button>
            <Button
              variant="text"
              icon={<Target size={15} />}
              onClick={() => scrollToSection('sec-mastery')}
            >
              自评掌握度
            </Button>
          </div>
        </div>
      </Card>

      <div className="v3-ka-layout">
        {/* 左栏：本页目录 */}
        <Card as="aside" className="v3-ka-toc" aria-label="本页目录">
          <div className="v3-ka-toc__head">
            <span className="v3-eyebrow">ON THIS PAGE</span>
            <span className="v3-ka-toc__title">本页内容</span>
          </div>
          <nav className="v3-ka-toc__list">
            {sections.map((s, i) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className={cx('v3-ka-toc__item', activeAnchor === s.id && 'is-active')}
                aria-current={activeAnchor === s.id ? 'true' : undefined}
                onClick={(e) => {
                  e.preventDefault()
                  scrollToSection(s.id)
                }}
              >
                <span className="v3-ka-toc__n">{String(i + 1).padStart(2, '0')}</span>
                <span>{s.label}</span>
              </a>
            ))}
          </nav>
          <div className="v3-ka-toc__foot">
            <span>约 {sourceParagraphs.length + recallQuestions.length + quiz.length + 2} 个阅读区块</span>
          </div>
        </Card>

        {/* 中栏：正文 */}
        <Card as="article" className="v3-ka-sheet">
          <div className="v3-ka-sheet__inner">
            <div className="v3-ka-sheet__kicker">
              <span><BookOpen size={13} /> {kp.subject || '未分类'} · {kp.chapter || '未分章'}</span>
              <span className="v3-ka-sheet__kicker-state">{STATE_LABEL[state]} · {mastery}%</span>
            </div>

            {/* 1. 考纲要求 */}
            {kp.description ? (
              <section className="v3-ka-section" id="sec-require">
                <h2 className="v3-ka-section__title">
                  <span className="v3-ka-section__idx">{String(sectionNo('sec-require')).padStart(2, '0')}</span>
                  考纲要求
                </h2>
                <div className="v3-ka-lead">
                  <span className="v3-ka-lead__label"><Sparkles size={12} /> 考纲原文</span>
                  <p>{kp.description}</p>
                </div>
              </section>
            ) : null}

            {/* 2. 教材原文 */}
            <section className="v3-ka-section" id="sec-source">
              <h2 className="v3-ka-section__title">
                <span className="v3-ka-section__idx">{String(sectionNo('sec-source')).padStart(2, '0')}</span>
                教材原文
                <span className="v3-ka-section__count">{sourceParagraphs.length} 段</span>
              </h2>
              {sourceParagraphs.length === 0 ? (
                <Empty
                  icon={<BookOpen size={22} />}
                  title="暂无可用教材原文"
                  text={droppedCount > 0
                    ? `该知识点关联的 ${droppedCount} 段教材原文因识别质量不达标已隐藏，建议在「文档知识库」重新导入清晰版本。`
                    : '该知识点暂未关联教材正文。可在「文档知识库」补充资料后重新抽取。'}
                />
              ) : (
                <div className="v3-ka-source-list">
                  {sourceParagraphs.map((p, i) => (
                    <div className="v3-ka-source" key={p.chunkId ?? i}>
                      <div className="v3-ka-source__body">
                        {toParagraphs(p.text).map((para, j) => (
                          <p key={j}>{para}</p>
                        ))}
                      </div>
                      {p.doc ? (
                        <div className="v3-ka-source__foot">
                          <Quote size={13} />
                          {p.docId ? (
                            <Link to={`/documents?doc=${p.docId}`} className="v3-ka-source__doc">
                              出处：{p.doc}
                            </Link>
                          ) : (
                            <span className="v3-ka-source__doc">出处：{p.doc}</span>
                          )}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
              {droppedCount > 0 && sourceParagraphs.length > 0 ? (
                <p className="v3-ka-note">
                  另有 {droppedCount} 段原文因识别质量问题未展示。
                </p>
              ) : null}
            </section>

            {/* 3. 主动回忆 */}
            <section className="v3-ka-section" id="sec-recall">
              <h2 className="v3-ka-section__title">
                <span className="v3-ka-section__idx">{String(sectionNo('sec-recall')).padStart(2, '0')}</span>
                主动回忆
              </h2>
              <p className="v3-ka-intro">
                先在心里作答，再展开核对。回忆比重复阅读更能形成长期记忆。
              </p>
              <div className="v3-ka-recall-list">
                {recallQuestions.map((item, i) => {
                  const open = openRecall === i
                  return (
                    <div className={cx('v3-ka-recall', open && 'is-open')} key={i}>
                      <button
                        type="button"
                        className="v3-ka-recall__q"
                        onClick={() => setOpenRecall(open ? null : i)}
                        aria-expanded={open}
                        aria-controls={`recall-a-${i}`}
                      >
                        <span className="v3-ka-recall__mark">{String(i + 1).padStart(2, '0')}</span>
                        <span className="v3-ka-recall__text">{item.q}</span>
                        <ChevronDown
                          size={16}
                          className={cx('v3-ka-recall__chev', open && 'is-open')}
                        />
                      </button>
                      {open ? (
                        <div className="v3-ka-recall__a" id={`recall-a-${i}`}>{item.a}</div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </section>

            {/* 4. 关联真题 */}
            {quizVisible ? (
              <section className="v3-ka-section" id="sec-quiz">
                <h2 className="v3-ka-section__title">
                  <span className="v3-ka-section__idx">{String(sectionNo('sec-quiz')).padStart(2, '0')}</span>
                  关联真题
                  {quizTotal != null ? <span className="v3-ka-section__count">共 {quizTotal} 题</span> : null}
                </h2>
                {quizState === 'loading' ? (
                  <div className="v3-ka-quiz-loading">
                    <Spinner size={16} /> 正在读取关联题目…
                  </div>
                ) : quizState === 'error' ? (
                  <Alert tone="danger">
                    <div className="v3-ka-quiz-error">
                      <span>关联题目加载失败：{quizError}</span>
                      <Button size="sm" variant="tonal" onClick={() => setQuizReloadKey((k) => k + 1)}>
                        重试
                      </Button>
                    </div>
                  </Alert>
                ) : quiz.length === 0 && quizTotal === 0 ? (
                  <div className="v3-ka-quiz-empty">
                    <p>该知识点暂无关联题目，可先去该科目题库刷全部题。</p>
                    <Button
                      size="sm"
                      variant="tonal"
                      icon={<Play size={15} />}
                      onClick={() => navigate(`/quiz?subject=${encodeURIComponent(kp?.subject || '')}`)}
                    >
                      去全部题
                    </Button>
                  </div>
                ) : (
                  <div className="v3-ka-quiz-list">
                    {quiz.map((q, i) => (
                      <Link key={q.id} to={`/quiz?kp_id=${id}&q=${q.id}`} className="v3-ka-quiz">
                        <span className="v3-ka-quiz__no">{String(i + 1).padStart(2, '0')}</span>
                        <span className={cx('v3-ka-quiz__tag', q.source_kind === 'exam' && 'is-exam')}>
                          {q.source_kind === 'exam' ? '真题' : '教材'}
                        </span>
                        <span className="v3-ka-quiz__text">
                          {(q.content || '（无题干）').slice(0, 64)}
                        </span>
                        <ChevronRight size={14} className="v3-ka-quiz__chev" />
                      </Link>
                    ))}
                  </div>
                )}
                {quizTotal != null && quizTotal > quiz.length ? (
                  <p className="v3-ka-note">仅展示前 {quiz.length} 题，去题库继续练习。</p>
                ) : null}
              </section>
            ) : null}

            {/* 5. 掌握度自评 */}
            <section className="v3-ka-review" id="sec-mastery">
              <div className="v3-ka-review__head">
                <h2 className="v3-ka-section__title">
                  <span className="v3-ka-section__idx">{String(sectionNo('sec-mastery')).padStart(2, '0')}</span>
                  掌握度自评
                </h2>
                <span className="v3-ka-review__hint">
                  选择后按记忆曲线重排下次复习时间
                </span>
              </div>
              {user ? (
                <>
                  <div className="v3-ka-grades" role="group" aria-label="掌握度自评">
                    {GRADES.map((g) => (
                      <button
                        key={g.q}
                        type="button"
                        className={cx('v3-ka-grade', `is-${g.tone}`)}
                        onClick={() => submitGrade(g.q)}
                        disabled={submitting}
                        title={`q=${g.q}，下次复习在 ${g.desc}`}
                      >
                        <span className="v3-ka-grade__key">{g.key}</span>
                        <span className="v3-ka-grade__desc">{g.desc}</span>
                      </button>
                    ))}
                  </div>
                  <p className="v3-ka-note">
                    六档自评会换算为 FSRS 四档评分：完全不会 / 想不起来 → 重来，很吃力 → 困难，勉强记得 → 良好，基本掌握 / 脱口而出 → 轻松。
                  </p>
                </>
              ) : (
                <Alert tone="info">
                  <div className="v3-ka-guest__inner">
                    <span>访客不写入复习记录。登录后可自评「完全不会 → 脱口而出」，系统会重排下次复习时间。</span>
                    <Button size="sm" variant="tonal" onClick={() => navigate('/login')}>登录后自评</Button>
                  </div>
                </Alert>
              )}
            </section>

            {/* 上/下篇 */}
            <nav className="v3-ka-pager" aria-label="同章节前后知识点">
              {neighbors.prev ? (
                <Link to={`/knowledge/${neighbors.prev.id}`} className="v3-ka-pager__link">
                  <span className="v3-ka-pager__dir"><ChevronLeft size={12} /> 上一篇</span>
                  <span className="v3-ka-pager__name">{neighbors.prev.name}</span>
                </Link>
              ) : <span className="v3-ka-pager__ghost" />}
              {neighbors.next ? (
                <Link to={`/knowledge/${neighbors.next.id}`} className="v3-ka-pager__link is-next">
                  <span className="v3-ka-pager__dir">下一篇 <ChevronRight size={12} /></span>
                  <span className="v3-ka-pager__name">{neighbors.next.name}</span>
                </Link>
              ) : <span className="v3-ka-pager__ghost" />}
            </nav>
          </div>
        </Card>

        {/* 右栏：相关知识点 / 学习动线 / 复习留痕 */}
        <aside className="v3-ka-rail">
          <Card className="v3-ka-rail-card">
            <CardHead
              icon={<BookOpen size={16} />}
              title="同章节知识点"
              sub={neighbors.prev || neighbors.next ? '按章节顺序排列' : '同章节暂无其他知识点'}
              actions={<Badge tone="outline">{relatedPoints.length}</Badge>}
            />
            {relatedPoints.length === 0 ? (
              <p className="v3-ka-note">当前章节只有这一个知识点。</p>
            ) : (
              <div className="v3-ka-related">
                {relatedPoints.map((p) => {
                  const st = pointState(p)
                  return (
                    <Link key={p.id} to={`/knowledge/${p.id}`} className="v3-ka-related__item">
                      <span className={cx('v3-ka-dot', `is-${st}`)} aria-hidden="true" />
                      <span className="v3-ka-related__name">{p.name}</span>
                      <span className="v3-ka-related__pct">
                        {st === 'unlearned' ? '未学' : `${Math.min(100, Math.max(0, Number(p.mastery) || 0))}%`}
                      </span>
                    </Link>
                  )
                })}
              </div>
            )}
            {siblings.length > 9 ? (
              <p className="v3-ka-note">本章节共 {siblings.length} 个知识点，此处展示最近的 {relatedPoints.length} 个。</p>
            ) : null}
          </Card>

          <Card className="v3-ka-rail-card">
            <CardHead icon={<Map size={16} />} title="学习动线" sub="回到地图，或继续同章阅读" />
            <div className="v3-ka-move">
              {neighbors.prev ? (
                <Link to={`/knowledge/${neighbors.prev.id}`} className="v3-ka-move__item">
                  <span><ChevronLeft size={14} /> 上一篇</span>
                  <b>{neighbors.prev.name}</b>
                </Link>
              ) : null}
              {neighbors.next ? (
                <Link to={`/knowledge/${neighbors.next.id}`} className="v3-ka-move__item is-next">
                  <span>下一篇 <ChevronRight size={14} /></span>
                  <b>{neighbors.next.name}</b>
                </Link>
              ) : null}
              <Button
                variant="tonal"
                block
                icon={<Map size={15} />}
                onClick={() => navigate(mapHref(true))}
              >
                回到知识地图
              </Button>
              <Button
                variant="text"
                block
                icon={<FileText size={15} />}
                onClick={() => scrollToSection('sec-source')}
              >
                重读教材原文
              </Button>
            </div>
          </Card>

          {user && reviewHistory.length > 0 ? (
            <Card className="v3-ka-rail-card">
              <CardHead
                icon={<Clock size={16} />}
                title="复习轨迹"
                sub="最近 180 天"
                actions={<Badge tone="outline">{reviewHistory.length}</Badge>}
              />
              <div className="v3-ka-history">
                {reviewHistory.slice(0, 5).map((h) => {
                  const meta = RESULT_META[h.result] || { label: h.result || '—', tone: 'mid' }
                  return (
                    <div className="v3-ka-history__item" key={h.id}>
                      <div className="v3-ka-history__top">
                        <span className={`v3-ka-history__result is-${meta.tone}`}>{meta.label}</span>
                        <span className="v3-ka-history__date">{fmtDate(h.created_at)}</span>
                      </div>
                      <div className="v3-ka-history__meta">
                        <span>
                          掌握度 {h.mastery_before ?? '—'} → {h.mastery_after ?? '—'}
                        </span>
                        {h.interval_after != null ? <span>间隔 {h.interval_after} 天</span> : null}
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
          ) : null}

          <Card className="v3-ka-rail-card v3-ka-tip-card">
            <div className="v3-ka-tip">
              <Lightbulb size={18} />
              <p>先合上答案做一次主动回忆，再回到原文核对，最后完成掌握度自评 —— 这一轮比重复阅读更有效。</p>
            </div>
          </Card>
        </aside>
      </div>
    </div>
  )
}
