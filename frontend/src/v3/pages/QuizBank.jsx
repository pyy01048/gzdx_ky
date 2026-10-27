import React, { useCallback, useEffect, useState } from 'react'
import {
  AnimatedNumber, Badge, Button, Card, CardHead, Dialog, Empty, Field,
  IconButton, Input, PageHeader, Select, Skeleton, Textarea, Tile, toast,
  useConfirm,
} from '../ui'
import {
  BookOpen, CheckCircle2, ChevronLeft, ChevronRight, Database, Edit, FileText,
  GraduationCap, Plus, RefreshCw, Search, Target, Trash,
} from '../icons'
import { quizApi, taxonomyApi } from '../../api/client'
import { normalizeOptions, optionText, imageList } from '../../utils/optionText'
import '../styles/admin-core-v3.css'
import '../styles/quiz-v3.css'

/* =====================================================================
 * 题库管理中心（v3）
 *
 * 后台题目库的浏览、检索、添加、编辑、删除与预览。
 * 所有筛选参数、统计口径、表单字段与保存/删除请求均沿用旧版，
 * 仅将容器换成 v3 admin 页面骨架。
 * ===================================================================== */

/* 题型固定 6 种（与后端 question_type 枚举对齐） */
const QUESTION_TYPES = [
  { value: 'all', label: '全部题型' },
  { value: 'single', label: '单选' },
  { value: 'judge', label: '判断' },
  { value: 'fill', label: '填空' },
  { value: 'essay', label: '简答' },
  { value: 'calc', label: '计算' },
  { value: 'draw', label: '作图' },
]
const TYPE_LABEL = Object.fromEntries(QUESTION_TYPES.map((t) => [t.value, t.label]))

/* 难度为后端整数 1-5 */
const DIFFICULTY_OPTIONS = [
  { value: 'all', label: '全部难度' },
  { value: '1', label: '难度 1 · 最简单' },
  { value: '2', label: '难度 2 · 较易' },
  { value: '3', label: '难度 3 · 中等' },
  { value: '4', label: '难度 4 · 较难' },
  { value: '5', label: '难度 5 · 最难' },
]

/* 清洗选项：库内存在「数组非空但元素全空」的题，直接渲染会得到空白行 */
const cleanOptions = (opts) => normalizeOptions(opts)

const PAGE_SIZE = 20

/* 后端 images[].path 形如 question_pages/xxx.png，对外挂在 /media/images 下 */
const mediaSrc = (img) => {
  const raw = img?.url || img?.path || img?.src || ''
  if (!raw) return ''
  if (/^(?:[a-z]+:)?\/\//i.test(raw) || raw.startsWith('/')) return raw
  return '/media/images/' + raw.replace(/^\/+/, '')
}

/* 来源大类过滤（与刷题中心口径一致）：真题 / 教材题 / 全部 */
const SOURCE_KIND_OPTIONS = [
  { value: 'all', label: '全部来源' },
  { value: 'exam', label: '历年真题' },
  { value: 'textbook', label: '教材题' },
]

const EMPTY_FORM = {
  content: '', optionsText: '', imagesText: '', answer: '', analysis: '',
  subject: '', chapter: '', knowledge_point: '', source: '',
  difficulty: '3', question_type: 'single',
}

const difficultyTone = (d) => {
  const n = Number(d)
  if (n <= 2) return 'success'
  if (n === 3) return 'warning'
  return 'danger'
}

function TableSkeleton() {
  return (
    <div className="v3-admin-table-wrap">
      <table className="v3-admin-table" aria-hidden="true">
        <thead>
          <tr>
            <th>题目</th>
            <th>分类</th>
            <th>题型</th>
            <th>难度</th>
            <th>来源</th>
            <th className="is-right">操作</th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: 6 }).map((_, i) => (
            <tr key={i}>
              <td><Skeleton width={`${64 + (i % 3) * 10}%`} height={12} /></td>
              <td><Skeleton width={92} height={12} /></td>
              <td><Skeleton width={52} height={20} radius={999} /></td>
              <td><Skeleton width={52} height={20} radius={999} /></td>
              <td><Skeleton width={76} height={12} /></td>
              <td><Skeleton width={96} height={12} style={{ marginLeft: 'auto' }} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function QuizBank() {
  const [confirm, confirmDialog] = useConfirm()
  const [questions, setQuestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [subject, setSubject] = useState('all')
  const [sourceKind, setSourceKind] = useState('all')
  const [onlyAnswerable, setOnlyAnswerable] = useState(true)
  const [qType, setQType] = useState('all')
  const [difficulty, setDifficulty] = useState('all')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  const [subjects, setSubjects] = useState([])   // 后端动态科目列表
  const [chapters, setChapters] = useState([])   // 常用章节（datalist）
  const [stats, setStats] = useState({
    total: 0, visible: 0, answerable: 0, junk: 0, active: 0, mastered: 0, graduated: 0,
  })
  const [bankTotal, setBankTotal] = useState(null)   /* 题库总量：与列表同口径（可作答题） */
  const [loadError, setLoadError] = useState('')     /* 题目列表错误就地态 */

  const [preview, setPreview] = useState(null)
  const [previewRevealed, setPreviewRevealed] = useState(false)
  const [revealed, setRevealed] = useState(() => new Set())

  const [editor, setEditor] = useState({ open: false, mode: 'create', id: null, form: EMPTY_FORM })

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  /* 拉真实科目与章节（科目走 taxonomy 科目接口；章节仍走 quizApi.sections 数据驱动） */
  useEffect(() => {
    taxonomyApi.subjects()
      .then((d) => setSubjects(Array.isArray(d) ? d : (d && (d.subjects || d.items)) || []))
      .catch((e) => { setSubjects([]); toast('科目列表加载失败：' + (e?.message || '未知错误')) })
    quizApi.sections()
      .then((d) => setChapters((d && d.items) || []))
      .catch((e) => { setChapters([]); toast('章节列表加载失败：' + (e?.message || '未知错误')) })
  }, [])

  /* 全局统计（一次即可）：
     /stats 给出 visible_total（排除 OCR 碎片）/ answerable_total（可判分）/ junk_total，
     前端不再自造数字，直接引用具名字段并标注口径。 */
  useEffect(() => {
    quizApi.stats()
      .then((d) => {
        if (!d) return
        setStats({
          total: d.total_questions ?? d.visible_total ?? 0,
          visible: d.visible_total ?? d.total_questions ?? 0,
          answerable: d.answerable_total ?? 0,
          junk: d.junk_total ?? 0,
          active: d.active_errors ?? 0,
          mastered: Math.round(d.accuracy_rate ?? 0),
          graduated: d.graduated_errors ?? 0,
        })
      })
      .catch((e) => toast('题库统计加载失败：' + (e?.message || '未知错误')))
  }, [])

  /* 题库总量：与列表接口同口径（默认 answerable=true，仅返回可作答题）。
     优先取 /stats.answerable_total；缺失时回退列表接口的 answerable_count。 */
  useEffect(() => {
    quizApi.questions({ page: 1, page_size: 1 })
      .then((d) => {
        if (!d) return
        if (typeof d.answerable_count === 'number') setBankTotal(d.answerable_count)
        else if (typeof d.total === 'number') setBankTotal(d.total)
      })
      .catch((e) => toast('题库总量统计失败：' + (e?.message || '未知错误')))
  }, [])

  const loadQuestions = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (subject !== 'all') params.subject = subject
      if (sourceKind !== 'all') params.source_kind = sourceKind
      if (qType !== 'all') params.question_type = qType
      if (difficulty !== 'all') params.difficulty = Number(difficulty)
      if (q) params.q = q
      // 默认只看可作答题；取消勾选时传 answerable=false 拉全量（缺答案/空题，供排查补全）
      if (!onlyAnswerable) params.answerable = false

      const data = await quizApi.questions(params)
      const list = (data && data.questions) || data?.items || []
      setQuestions(list)
      setTotal((data && typeof data.total === 'number') ? data.total : list.length)
    } catch (e) {
      setLoadError(e.message || '加载题目失败')
      toast('加载题目失败：' + e.message)
    } finally {
      setLoading(false)
    }
  }, [subject, sourceKind, qType, difficulty, q, page, onlyAnswerable])

  useEffect(() => { loadQuestions() }, [loadQuestions])

  /* 筛选/搜索变化时回到第一页 */
  useEffect(() => { setPage(1) }, [subject, sourceKind, qType, difficulty, q, onlyAnswerable])

  /* 删除后若当前页已空且非首页，回退一页 */
  useEffect(() => {
    if (!loading && questions.length === 0 && page > 1) setPage(page - 1)
  }, [questions, loading, page])

  const toggleReveal = (id) => {
    setRevealed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const handleDelete = async (id) => {
    const ok = await confirm({
      title: '删除题目',
      message: '确定删除这道题目吗？',
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await quizApi.remove(id)
      toast('题目已删除')
      loadQuestions()
    } catch (e) {
      toast('删除失败：' + e.message)
    }
  }

  /* ---------- 添加 / 编辑 ---------- */
  const openCreate = () => {
    setEditor({
      open: true, mode: 'create', id: null,
      form: {
        ...EMPTY_FORM,
        subject: subject !== 'all' ? subject : (subjects[0]?.subject || ''),
      },
    })
  }

  const openEdit = (item) => {
    setEditor({
      open: true, mode: 'edit', id: item.id,
      form: {
        content: item.content || '',
        optionsText: normalizeOptions(item.options).join('\n'),
        imagesText: imageList(item.images).map((img) => img.url).join('\n'),
        answer: item.answer || '',
        analysis: item.analysis || '',
        subject: item.subject || '',
        chapter: item.chapter || '',
        knowledge_point: item.knowledge_point || '',
        source: item.source || '',
        difficulty: String(item.difficulty ?? 3),
        question_type: item.question_type || 'single',
      },
    })
  }

  const closeEditor = () => setEditor((e) => ({ ...e, open: false }))

  const handleSubmit = async () => {
    const f = editor.form
    if (!f.content.trim()) { toast('请填写题目内容'); return }
    const body = {
      content: f.content.trim(),
      options: f.optionsText.split('\n').map((s) => s.trim()).filter(Boolean)
        .map((opt, i) => String(opt).replace(/^[A-F][\.、:：]\s*/, '') || String(opt)),
      images: (f.imagesText || '').split('\n').map((s) => s.trim()).filter(Boolean),
      answer: f.answer.trim() || null,
      analysis: f.analysis.trim() || null,
      subject: f.subject || null,
      chapter: f.chapter.trim() || null,
      knowledge_point: f.knowledge_point.trim() || null,
      difficulty: Number(f.difficulty) || 3,
      source: f.source.trim() || null,
      question_type: f.question_type,
    }
    try {
      if (editor.mode === 'create') {
        await quizApi.create(body)
        toast('题目已添加')
      } else {
        await quizApi.update(editor.id, body)
        toast('题目已更新')
      }
      closeEditor()
      loadQuestions()
    } catch (e) {
      toast('保存失败：' + e.message)
    }
  }

  const answerableShown = bankTotal == null ? (stats.answerable || '—') : bankTotal
  const visibleShown = stats.visible ?? '—'

  return (
    <div className="v3-admin-page">
      <PageHeader
        eyebrow="ADMIN · 题库管理"
        title="题库管理中心"
        sub={`预览、查询和管理数据库中的所有题目，共 ${total} 道`}
        icon={<Database size={26} />}
        actions={(
          <div className="v3-row" style={{ gap: 8 }}>
            <Button
              variant="outline"
              icon={<RefreshCw size={15} />}
              loading={loading}
              onClick={loadQuestions}
            >
              刷新
            </Button>
            <Button variant="filled" icon={<Plus size={15} />} onClick={openCreate}>
              添加题目
            </Button>
          </div>
        )}
      />

      {/* 统计卡片：口径与旧版一致 */}
      <div className="v3-admin-stats">
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><BookOpen size={14} />可作答题</span>
          <span className="v3-tile__value">
            {answerableShown === '—' ? <span className="v3-admin-nil">—</span> : (
              <><AnimatedNumber value={answerableShown} /><em>道</em></>
            )}
          </span>
          <span className="v3-tile__hint">有答案可自动判分，与列表默认口径一致</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><FileText size={14} />可见题</span>
          <span className="v3-tile__value">
            {visibleShown === '—' ? <span className="v3-admin-nil">—</span> : (
              <><AnimatedNumber value={visibleShown} /><em>道</em></>
            )}
          </span>
          <span className="v3-tile__hint">排除 OCR 碎片题后的题库总量</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><Target size={14} />待攻克题</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={stats.active} /><em>道</em>
          </span>
          <span className="v3-tile__hint">活跃错题数（全库）</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><CheckCircle2 size={14} />正确率 %</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={stats.mastered} /><em>%</em>
          </span>
          <span className="v3-tile__hint">答对次数 / 答题总次数（全库）</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><GraduationCap size={14} />已掌握题</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={stats.graduated} /><em>道</em>
          </span>
          <span className="v3-tile__hint">已毕业错题数（全库）</span>
        </Tile>
      </div>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            icon={<BookOpen size={16} />}
            title="题目列表"
            sub="按科目、来源、题型与难度筛选；展开行可查看答案与解析，或进入预览弹窗。"
            actions={<Badge tone="outline">共 {total} 道</Badge>}
          />
        </div>

        <div className="v3-admin-panel__toolbar">
          <div className="v3-admin-toolbar">
            <div className="v3-quiz-bank-search">
              <Input
                icon={<Search size={16} />}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="搜索题目内容、答案、知识点..."
                aria-label="搜索题目内容、答案、知识点"
              />
            </div>
            <Select
              className="v3-quiz-bank-select"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              aria-label="按科目过滤"
            >
              <option value="all">全部科目</option>
              {subjects.map((s) => (
                <option key={s.subject} value={s.subject}>{s.subject}</option>
              ))}
            </Select>
            <Select
              className="v3-quiz-bank-select"
              value={sourceKind}
              onChange={(e) => setSourceKind(e.target.value)}
              aria-label="按来源过滤"
              title="按来源大类过滤：真题与教材题分开展示"
            >
              {SOURCE_KIND_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </Select>
            <Select
              className="v3-quiz-bank-select"
              value={qType}
              onChange={(e) => setQType(e.target.value)}
              aria-label="按题型过滤"
            >
              {QUESTION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </Select>
            <Select
              className="v3-quiz-bank-select"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
              aria-label="按难度过滤"
            >
              {DIFFICULTY_OPTIONS.map((d) => (
                <option key={d.value} value={d.value}>{d.label}</option>
              ))}
            </Select>
          </div>

          {/* 口径提示：列表默认只列「可作答」题；可切换查看不可作答（缺选项/缺答案）以排查补全 */}
          <div className="v3-admin-meta-row" style={{ marginTop: 10 }}>
            <label className="v3-quiz-bank-check">
              <input
                type="checkbox"
                checked={onlyAnswerable}
                onChange={(e) => setOnlyAnswerable(e.target.checked)}
              />
              只看可作答题（有答案且可用；取消勾选可查看缺答案/空题）
            </label>
            <span>本页 {questions.length} / 共 {total} 题（第 {page} / {totalPages} 页）</span>
          </div>
        </div>

        {loading ? <TableSkeleton /> : null}

        {!loading && loadError ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<RefreshCw size={28} />}
              title="题目列表加载失败"
              text={loadError}
              action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={loadQuestions}>重试</Button>}
            />
          </div>
        ) : null}

        {!loading && !loadError && questions.length === 0 ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<BookOpen size={30} />}
              title="暂无题目"
              text="手动录入一道题，或到文档知识库从 PDF / 图片中提取题目。"
              action={(
                <div className="v3-row">
                  <Button variant="filled" icon={<Plus size={15} />} onClick={openCreate}>添加题目</Button>
                  <a className="v3-btn v3-btn--outline" href="#/documents">
                    <FileText size={15} />
                    <span>从文档提取</span>
                  </a>
                </div>
              )}
            />
          </div>
        ) : null}

        {!loading && !loadError && questions.length > 0 ? (
          <>
            <div className="v3-admin-table-wrap">
              <table className="v3-admin-table">
                <thead>
                  <tr>
                    <th>题目</th>
                    <th>分类</th>
                    <th>题型</th>
                    <th>难度</th>
                    <th>来源</th>
                    <th className="is-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {questions.map((item, idx) => {
                    const isOpen = revealed.has(item.id)
                    const opts = cleanOptions(item.options)
                    const imgs = imageList(item.images)
                    const seq = (page - 1) * PAGE_SIZE + idx + 1
                    return (
                      <tr key={item.id || idx}>
                        <td>
                          <div className="v3-quiz-bank-q">
                            <div className="v3-row" style={{ flexWrap: 'wrap', gap: 6 }}>
                              {item.is_available === false || item.quality === 'incomplete' ? (
                                <Badge tone="danger">不可作答</Badge>
                              ) : null}
                              {item.is_available !== false && item.quality !== 'incomplete' && opts.length === 0 ? (
                                <Badge tone="warning">仅记忆参考</Badge>
                              ) : null}
                              <Badge tone="outline">#{item.id ?? '—'}</Badge>
                            </div>
                            <div className="v3-quiz-bank-q__content">
                              <span className="v3-quiz-bank-q__no">{seq}.</span>
                              {item.content || '无题目内容'}
                            </div>
                            {imgs.length > 0 ? (
                              <div className="v3-quiz-bank-images">
                                {imgs.map((img, i) => (
                                  <img
                                    key={i}
                                    src={mediaSrc(img)}
                                    alt={`题目配图 ${i + 1}`}
                                    loading="lazy"
                                  />
                                ))}
                              </div>
                            ) : null}
                            {opts.length > 0 ? (
                              <div className="v3-quiz-bank-options">
                                {opts.map((opt, i) => {
                                  const letter = String.fromCharCode(65 + i)
                                  const correct = isOpen && item.answer === letter
                                  return (
                                    <div
                                      key={i}
                                      className={correct ? 'v3-quiz-bank-opt is-correct' : 'v3-quiz-bank-opt'}
                                    >
                                      {letter}. {optionText(opt).replace(/^[A-F][\.、:：]\s*/, '')}
                                      {correct ? <span> · 正确答案</span> : null}
                                    </div>
                                  )
                                })}
                              </div>
                            ) : null}
                            {isOpen && item.answer && opts.length === 0 ? (
                              <div className="v3-quiz-bank-answer">答案：{item.answer}</div>
                            ) : null}
                            {isOpen && item.analysis ? (
                              <div className="v3-quiz-bank-analysis">
                                <strong>解析：</strong>{item.analysis}
                              </div>
                            ) : null}
                            <div>
                              <Button
                                variant="text"
                                size="sm"
                                onClick={() => toggleReveal(item.id)}
                              >
                                {isOpen ? '收起答案/解析' : '显示答案/解析'}
                              </Button>
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="v3-quiz-bank-meta">
                            <Badge tone="primary">{item.subject || '未分类'}</Badge>
                            {item.chapter ? <small>章节：{item.chapter}</small> : null}
                            {item.knowledge_point ? <small>知识点：{item.knowledge_point}</small> : null}
                          </div>
                        </td>
                        <td className="is-nowrap">
                          {item.question_type ? (
                            <Badge tone="outline">{TYPE_LABEL[item.question_type] || item.question_type}</Badge>
                          ) : <span className="v3-admin-nil">—</span>}
                        </td>
                        <td className="is-nowrap">
                          {item.difficulty != null ? (
                            <Badge tone={difficultyTone(item.difficulty)}>难度 {item.difficulty}</Badge>
                          ) : <span className="v3-admin-nil">—</span>}
                        </td>
                        <td className="is-truncate" title={item.source || undefined}>
                          {item.source || <span className="v3-admin-nil">—</span>}
                        </td>
                        <td>
                          <div className="v3-admin-table__actions">
                            <IconButton
                              label="预览详情"
                              size="sm"
                              icon={<FileText size={15} />}
                              onClick={() => { setPreview(item); setPreviewRevealed(false) }}
                            />
                            <IconButton
                              label="编辑题目"
                              size="sm"
                              icon={<Edit size={15} />}
                              onClick={() => openEdit(item)}
                            />
                            <IconButton
                              label="删除题目"
                              size="sm"
                              className="v3-admin-danger-text"
                              icon={<Trash size={15} />}
                              onClick={() => handleDelete(item.id)}
                            />
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <div className="v3-quiz-bank-pager">
              <Button
                variant="outline"
                size="sm"
                icon={<ChevronLeft size={14} />}
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </Button>
              <span>第 {page} / {totalPages} 页 · 共 {total} 题</span>
              <Button
                variant="outline"
                size="sm"
                trailingIcon={<ChevronRight size={14} />}
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                下一页
              </Button>
            </div>
          </>
        ) : null}
      </Card>

      {/* 预览弹窗（答案/解析折叠） */}
      <Dialog open={!!preview} title="题目详情" onClose={() => setPreview(null)} wide>
        {preview ? (
          <div className="v3-quiz-bank-preview">
            <div>
              <strong>题目内容：</strong>
              <div className="v3-quiz-bank-preview__box" style={{ marginTop: 8 }}>
                {preview.content}
              </div>
            </div>

            {imageList(preview.images).length > 0 ? (
              <div className="v3-quiz-bank-images">
                {imageList(preview.images).map((img, i) => (
                  <img key={i} src={mediaSrc(img)} alt={`题目配图 ${i + 1}`} loading="lazy" />
                ))}
              </div>
            ) : null}

            {cleanOptions(preview.options).length > 0 ? (
              <div>
                <strong>选项：</strong>
                <div className="v3-quiz-bank-options" style={{ marginTop: 8, gap: 4 }}>
                  {cleanOptions(preview.options).map((opt, i) => {
                    const letter = String.fromCharCode(65 + i)
                    const correct = previewRevealed && preview.answer === letter
                    return (
                      <div
                        key={i}
                        className={correct ? 'v3-quiz-bank-opt is-correct' : 'v3-quiz-bank-opt'}
                        style={{
                          padding: '6px 10px',
                          borderRadius: 'var(--v3-r-xs)',
                          background: correct ? 'var(--v3-success-container)' : 'var(--v3-surface-1)',
                        }}
                      >
                        {letter}. {optionText(opt).replace(/^[A-F][\.、:：]\s*/, '')}
                        {correct ? <span> · 正确答案</span> : null}
                      </div>
                    )
                  })}
                </div>
              </div>
            ) : null}

            <div>
              <Button variant="text" size="sm" onClick={() => setPreviewRevealed((v) => !v)}>
                {previewRevealed ? '收起答案/解析' : '显示答案/解析'}
              </Button>
            </div>

            {previewRevealed ? (
              <>
                <div>
                  <strong>正确答案：</strong>
                  <span className="v3-quiz-bank-answer" style={{ marginLeft: 8 }}>{preview.answer || '-'}</span>
                </div>
                {preview.analysis ? (
                  <div>
                    <strong>答案解析：</strong>
                    <div className="v3-quiz-bank-preview__box" style={{ marginTop: 8 }}>
                      {preview.analysis}
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}

            <div className="v3-quiz-bank-preview__meta">
              <div><strong>科目：</strong>{preview.subject || '-'}</div>
              <div><strong>难度：</strong>{preview.difficulty != null ? preview.difficulty : '-'}</div>
              <div><strong>题型：</strong>{TYPE_LABEL[preview.question_type] || preview.question_type || '-'}</div>
              <div><strong>知识点：</strong>{preview.knowledge_point || '-'}</div>
              <div><strong>来源：</strong>{preview.source || '-'}</div>
              <div><strong>ID：</strong>{preview.id}</div>
            </div>
          </div>
        ) : null}
      </Dialog>

      {/* 添加 / 编辑题目弹窗 */}
      <Dialog
        open={editor.open}
        title={editor.mode === 'create' ? '添加题目' : '编辑题目'}
        onClose={closeEditor}
        wide
        footer={(
          <>
            <Button variant="text" onClick={closeEditor}>取消</Button>
            <Button variant="filled" onClick={handleSubmit}>保存</Button>
          </>
        )}
      >
        <div className="v3-quiz-bank-form">
          <Field label="题目内容 *">
            <Textarea
              rows={3}
              aria-label="题目内容"
              aria-required="true"
              value={editor.form.content}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, content: e.target.value } }))}
              placeholder="输入题干..."
            />
          </Field>

          <Field label="题目配图（每行一个 URL/路径，可留空）">
            <Textarea
              rows={2}
              aria-label="题目配图"
              value={editor.form.imagesText || ''}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, imagesText: e.target.value } }))}
              placeholder={'每行一个图片地址，例如：\n/static/question_images/123_p42_fig1.png'}
            />
          </Field>

          <Field label="选项（每行一个，客观题填写）">
            <Textarea
              rows={4}
              aria-label="选项"
              value={editor.form.optionsText}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, optionsText: e.target.value } }))}
              placeholder={'每行一个选项，例如：\n选项一\n选项二\n选项三'}
            />
          </Field>

          <div className="v3-quiz-bank-form__grid">
            <Field label="答案">
              <Input
                aria-label="答案"
                value={editor.form.answer}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, answer: e.target.value } }))}
                placeholder="如 A / 对 / 填空答案"
              />
            </Field>
            <Field label="题型">
              <Select
                aria-label="题型"
                value={editor.form.question_type}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, question_type: e.target.value } }))}
              >
                {QUESTION_TYPES.filter((t) => t.value !== 'all').map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </Select>
            </Field>
          </div>

          <Field label="答案解析">
            <Textarea
              rows={3}
              aria-label="答案解析"
              value={editor.form.analysis}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, analysis: e.target.value } }))}
              placeholder="可选"
            />
          </Field>

          <div className="v3-quiz-bank-form__grid">
            <Field label="科目">
              <Select
                aria-label="科目"
                value={editor.form.subject}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, subject: e.target.value } }))}
              >
                <option value="">未分类</option>
                {subjects.map((s) => <option key={s.subject} value={s.subject}>{s.subject}</option>)}
              </Select>
            </Field>
            <Field label="难度（1-5）">
              <Select
                aria-label="难度"
                value={editor.form.difficulty}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, difficulty: e.target.value } }))}
              >
                {DIFFICULTY_OPTIONS.filter((d) => d.value !== 'all').map((d) => (
                  <option key={d.value} value={d.value}>{d.label}</option>
                ))}
              </Select>
            </Field>
          </div>

          <div className="v3-quiz-bank-form__grid">
            <Field label="章节">
              <Input
                list="qb-chapters"
                aria-label="章节"
                value={editor.form.chapter}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, chapter: e.target.value } }))}
                placeholder="可选"
              />
              <datalist id="qb-chapters">
                {chapters.map((c) => <option key={c.chapter} value={c.chapter} />)}
              </datalist>
            </Field>
            <Field label="知识点">
              <Input
                aria-label="知识点"
                value={editor.form.knowledge_point}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, knowledge_point: e.target.value } }))}
                placeholder="可选"
              />
            </Field>
          </div>

          <Field label="来源">
            <Input
              aria-label="来源"
              value={editor.form.source}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, source: e.target.value } }))}
              placeholder="可选，如 真题2024"
            />
          </Field>
        </div>
      </Dialog>

      {confirmDialog}
    </div>
  )
}
