import React, { useState, useEffect, useCallback } from 'react'
import { toast, Empty, Modal } from '../components/UI'
import { quizApi, taxonomyApi } from '../api/client'
import {
  Search, Trash, Book, Target, CheckCircle, GraduationCap, FileText,
  Plus, Edit, RefreshCw, ChevronLeft, ChevronRight,
} from '../components/Icon'

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
const TYPE_LABEL = Object.fromEntries(QUESTION_TYPES.map(t => [t.value, t.label]))

/* 难度为后端整数 1-5（旧版中文「简单/中等/困难」与后端不符，过滤失效） */
const DIFFICULTY_OPTIONS = [
  { value: 'all', label: '全部难度' },
  { value: '1', label: '难度 1 · 最简单' },
  { value: '2', label: '难度 2 · 较易' },
  { value: '3', label: '难度 3 · 中等' },
  { value: '4', label: '难度 4 · 较难' },
  { value: '5', label: '难度 5 · 最难' },
]

/* 清洗选项：库内存在「数组非空但元素全空」的题，直接渲染会得到空白行 */
const cleanOptions = (opts) =>
  (Array.isArray(opts) ? opts.map((o) => String(o ?? '').trim()).filter(Boolean) : [])

const PAGE_SIZE = 20

/* 来源大类过滤（与刷题中心口径一致）：真题 / 教材题 / 全部 */
const SOURCE_KIND_OPTIONS = [
  { value: 'all', label: '全部来源' },
  { value: 'exam', label: '历年真题' },
  { value: 'textbook', label: '教材题' },
]

const EMPTY_FORM = {
  content: '', optionsText: '', answer: '', analysis: '',
  subject: '', chapter: '', knowledge_point: '', source: '',
  difficulty: '3', question_type: 'single',
}

export default function QuizBank() {
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
  const [chapters, setChapters] = useState([])    // 常用章节（datalist）
  const [stats, setStats] = useState({ total: 0, visible: 0, answerable: 0, junk: 0, active: 0, mastered: 0, graduated: 0 })
  const [bankTotal, setBankTotal] = useState(null)   /* 题库总量：与列表同口径（可作答题） */
  const [loadError, setLoadError] = useState('')   /* 阶段2：题目列表错误就地态 */

  const [preview, setPreview] = useState(null)
  const [previewRevealed, setPreviewRevealed] = useState(false)
  const [revealed, setRevealed] = useState(() => new Set())

  const [editor, setEditor] = useState({ open: false, mode: 'create', id: null, form: EMPTY_FORM })

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  /* 拉真实科目与章节（V8：科目走 taxonomy 科目接口；章节仍走 quizApi.sections 数据驱动） */
  useEffect(() => {
    taxonomyApi.subjects()
      .then((d) => setSubjects(Array.isArray(d) ? d : (d && (d.subjects || d.items)) || []))
      .catch((e) => { setSubjects([]); toast('科目列表加载失败：' + (e?.message || '未知错误')) })
    quizApi.sections()
      .then((d) => setChapters((d && d.items) || []))
      .catch((e) => { setChapters([]); toast('章节列表加载失败：' + (e?.message || '未知错误')) })
  }, [])

  /* 全局统计（一次即可）。
     口径显式化（M0-103①）：/stats 给出 visible_total（排除 OCR 碎片）/ answerable_total
     （可判分）/ junk_total，前端不再自造数字，直接引用具名字段并标注口径。 */
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
    if (!confirm('确定删除这道题目吗？')) return
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
        optionsText: Array.isArray(item.options) ? item.options.join('\n') : '',
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

  const diffColor = (d) => {
    const n = Number(d)
    if (n <= 2) return ['var(--green-soft)', 'var(--green)']
    if (n === 3) return ['var(--gold-soft)', 'var(--gold)']
    return ['var(--red-soft)', 'var(--red)']
  }

  const statCards = [
    {
      icon: <Book size={28} />, label: '可作答题', value: bankTotal == null ? (stats.answerable || '—') : bankTotal,
      color: 'var(--accent)',
      title: '可作答 = 有答案可自动判分（= /api/quiz/stats.answerable_total）。与下方列表默认口径一致。',
    },
    {
      icon: <FileText size={28} />, label: '可见题', value: stats.visible ?? '—',
      color: 'var(--violet)',
      title: '可见题 = 排除 OCR 碎片题后的题库总量（= /api/quiz/stats.visible_total）',
    },
    { icon: <Target size={28} />, label: '待攻克题', value: stats.active, color: 'var(--red)', title: '活跃错题数（全库）' },
    { icon: <CheckCircle size={28} />, label: '正确率 %', value: stats.mastered, color: 'var(--green)', title: '答对次数 / 答题总次数（全库）' },
    { icon: <GraduationCap size={28} />, label: '已掌握题', value: stats.graduated, color: 'var(--gold)', title: '已毕业错题数（全库）' },
  ]

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h2>题库管理中心</h2>
          <p style={{ fontSize: 13, color: 'var(--ink-3)', marginTop: 4 }}>
            预览、查询和管理数据库中的所有题目，共 {total} 道
          </p>
        </div>
      </div>

      {/* 统计卡片 */}
      <div className="stats-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 24 }}>
        {statCards.map((s, i) => (
          <div key={i} className="stat-card" title={s.title} style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 16,
            padding: '20px 24px',
            textAlign: 'center',
            transition: 'transform 0.2s, box-shadow 0.2s',
          }}>
            <div style={{ color: s.color, marginBottom: 8 }}>{s.icon}</div>
            <div style={{ fontSize: 32, fontWeight: 700, color: 'var(--ink)', marginBottom: 4 }}>{s.value}</div>
            <div style={{ fontSize: 13, color: 'var(--ink-3)' }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* 筛选工具栏 */}
      <div className="toolbar" style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 200 }}>
          <Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-3)' }} />
          <input
            className="input"
            style={{ paddingLeft: 36 }}
            placeholder="搜索题目内容、答案、知识点..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <select className="select" style={{ width: 150 }} value={subject} onChange={(e) => setSubject(e.target.value)}>
          <option value="all">全部科目</option>
          {subjects.map((s) => <option key={s.subject} value={s.subject}>{s.subject}</option>)}
        </select>
        <select className="select" style={{ width: 140 }} value={sourceKind} onChange={(e) => setSourceKind(e.target.value)}
          title="按来源大类过滤：真题与教材题分开展示">
          {SOURCE_KIND_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select className="select" style={{ width: 130 }} value={qType} onChange={(e) => setQType(e.target.value)}>
          {QUESTION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <select className="select" style={{ width: 150 }} value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
          {DIFFICULTY_OPTIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
        </select>
        <button className="btn ghost" onClick={loadQuestions} disabled={loading}>
          {loading ? '加载中...' : <><RefreshCw size={14} /> 刷新</>}
        </button>
        <button className="btn primary" onClick={openCreate}>
          <Plus size={14} /> 添加题目
        </button>
      </div>

      {/* 口径提示：列表默认只列「可作答」题；可切换查看不可作答（缺选项/缺答案）以排查补全 */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, fontSize: 13, color: 'var(--ink-3)' }}>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
          <input type="checkbox" checked={onlyAnswerable} onChange={(e) => setOnlyAnswerable(e.target.checked)} />
          只看可作答题（有答案且可用；取消勾选可查看缺答案/空题）
        </label>
        <span>当前列出 {total} 题</span>
      </div>

      {/* 题目列表 */}
      {loading ? (
        <div className="loading-inline">加载中...</div>
      ) : loadError ? (
        <div className="empty-state">
          <div className="empty-state-title">题目列表加载失败</div>
          <div className="empty-state-desc">{loadError}</div>
          <div className="empty-state-action">
            <button className="btn ghost" onClick={loadQuestions}>重试</button>
          </div>
        </div>
      ) : questions.length === 0 ? (
        <Empty icon={<Book size={48} />} title="暂无题目" desc="可点击右上角「添加题目」手动录入，或从文档中提取题目" />
      ) : (
        <div className="question-list" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {questions.map((item, idx) => {
            const isOpen = revealed.has(item.id)
            const [diffBg, diffFg] = diffColor(item.difficulty)
            return (
              <div key={item.id || idx} className="question-card" style={{
                background: 'var(--surface)',
                border: '1px solid var(--line)',
                borderRadius: 12,
                padding: '16px 20px',
                transition: 'box-shadow 0.2s',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                      <span className="tag" style={{
                        background: 'var(--accent-soft)',
                        color: 'var(--accent)',
                        padding: '2px 10px',
                        borderRadius: 20,
                        fontSize: 12,
                        fontWeight: 500,
                      }}>{item.subject || '未分类'}</span>
                      {item.difficulty != null && (
                        <span className="tag" style={{
                          background: diffBg,
                          color: diffFg,
                          padding: '2px 10px',
                          borderRadius: 20,
                          fontSize: 12,
                          fontWeight: 500,
                        }}>难度 {item.difficulty}</span>
                      )}
                      {item.question_type && (
                        <span className="tag" style={{
                          background: 'var(--surface-3)',
                          color: 'var(--ink-2)',
                          padding: '2px 10px',
                          borderRadius: 20,
                          fontSize: 12,
                        }}>{TYPE_LABEL[item.question_type] || item.question_type}</span>
                      )}
                      {item.knowledge_point && (
                        <span className="tag" style={{
                          background: 'var(--violet-soft)',
                          color: 'var(--violet)',
                          padding: '2px 10px',
                          borderRadius: 20,
                          fontSize: 12,
                        }}>{item.knowledge_point}</span>
                      )}
                      {/* 可用性标记：不可作答（空题假题）/ 仅记忆参考（无选项有答案） */}
                      {(item.is_available === false || item.quality === 'incomplete') && (
                        <span className="tag" style={{ background: 'var(--red-soft)', color: 'var(--red)', padding: '2px 10px', borderRadius: 20, fontSize: 12 }}>
                          不可作答
                        </span>
                      )}
                      {(item.is_available !== false && item.quality !== 'incomplete'
                        && cleanOptions(item.options).length === 0) && (
                        <span className="tag" style={{ background: 'var(--gold-soft)', color: 'var(--gold)', padding: '2px 10px', borderRadius: 20, fontSize: 12 }}>
                          仅记忆参考
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 15, color: 'var(--ink)', lineHeight: 1.6, marginBottom: 8 }}>
                      <span style={{ color: 'var(--ink-3)', marginRight: 8 }}>{(page - 1) * PAGE_SIZE + idx + 1}.</span>
                      {item.content || '无题目内容'}
                    </div>
                    {cleanOptions(item.options).length > 0 && (
                      <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.8 }}>
                        {cleanOptions(item.options).map((opt, i) => {
                          const letter = String.fromCharCode(65 + i)
                          const correct = isOpen && item.answer === letter
                          return (
                            <div key={i} style={{ marginBottom: 2 }}>
                              {letter}. {String(opt).replace(/^[A-F][\.、:：]\s*/, '')}
                              {correct && (
                                <span style={{ color: 'var(--green)', marginLeft: 8, fontWeight: 600 }}>✓ 正确答案</span>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                    {isOpen && item.answer && cleanOptions(item.options).length === 0 && (
                      <div style={{ fontSize: 13, color: 'var(--green)', marginTop: 4 }}>
                        答案：{item.answer}
                      </div>
                    )}
                    {isOpen && item.analysis && (
                      <div style={{
                        fontSize: 13, color: 'var(--ink-2)', marginTop: 8,
                        padding: 10, background: 'var(--surface-2)', borderRadius: 8, lineHeight: 1.7,
                      }}>
                        <strong>解析：</strong>{item.analysis}
                      </div>
                    )}
                    <button className="btn sm ghost" style={{ marginTop: 8 }} onClick={() => toggleReveal(item.id)}>
                      {isOpen ? '收起答案/解析' : '显示答案/解析'}
                    </button>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
                    <button className="btn sm ghost" onClick={() => { setPreview(item); setPreviewRevealed(false) }} title="预览详情">
                      <FileText size={14} /> 预览
                    </button>
                    <button className="btn sm ghost" onClick={() => openEdit(item)} title="编辑题目">
                      <Edit size={14} /> 编辑
                    </button>
                    <button className="btn sm danger" onClick={() => handleDelete(item.id)} title="删除题目">
                      <Trash size={14} /> 删除
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* 分页控件 */}
      {!loading && questions.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16, marginTop: 24 }}>
          <button className="btn ghost sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            <ChevronLeft size={14} /> 上一页
          </button>
          <span style={{ fontSize: 13, color: 'var(--ink-3)' }}>
            第 {page} / {totalPages} 页 · 共 {total} 题
          </span>
          <button className="btn ghost sm" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
            下一页 <ChevronRight size={14} />
          </button>
        </div>
      )}

      {/* 预览弹窗（答案/解析折叠） */}
      <Modal open={!!preview} title="题目详情" onClose={() => setPreview(null)}>
        {preview && (
          <div style={{ fontSize: 14, lineHeight: 1.8 }}>
            <div style={{ marginBottom: 16 }}>
              <strong style={{ color: 'var(--ink-2)' }}>题目内容：</strong>
              <div style={{ marginTop: 8, padding: 12, background: 'var(--surface-2)', borderRadius: 8 }}>
                {preview.content}
              </div>
            </div>
            {cleanOptions(preview.options).length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <strong style={{ color: 'var(--ink-2)' }}>选项：</strong>
                <div style={{ marginTop: 8 }}>
                  {cleanOptions(preview.options).map((opt, i) => {
                    const letter = String.fromCharCode(65 + i)
                    const correct = previewRevealed && preview.answer === letter
                    return (
                      <div key={i} style={{
                        padding: '6px 12px', marginBottom: 4, borderRadius: 6,
                        background: correct ? 'var(--green-soft)' : 'var(--surface-2)',
                      }}>
                        {letter}. {String(opt).replace(/^[A-F][\.、:：]\s*/, '')}
                        {correct && <span style={{ color: 'var(--green)', marginLeft: 8 }}>✓</span>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            <button className="btn sm ghost" style={{ marginBottom: 16 }} onClick={() => setPreviewRevealed((v) => !v)}>
              {previewRevealed ? '收起答案/解析' : '显示答案/解析'}
            </button>
            {previewRevealed && (
              <>
                <div style={{ marginBottom: 16 }}>
                  <strong style={{ color: 'var(--ink-2)' }}>正确答案：</strong>
                  <span style={{ color: 'var(--green)', marginLeft: 8, fontWeight: 600 }}>{preview.answer || '-'}</span>
                </div>
                {preview.analysis && (
                  <div style={{ marginBottom: 16 }}>
                    <strong style={{ color: 'var(--ink-2)' }}>答案解析：</strong>
                    <div style={{ marginTop: 8, padding: 12, background: 'var(--surface-2)', borderRadius: 8 }}>
                      {preview.analysis}
                    </div>
                  </div>
                )}
              </>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 13 }}>
              <div><strong>科目：</strong>{preview.subject || '-'}</div>
              <div><strong>难度：</strong>{preview.difficulty != null ? preview.difficulty : '-'}</div>
              <div><strong>题型：</strong>{TYPE_LABEL[preview.question_type] || preview.question_type || '-'}</div>
              <div><strong>知识点：</strong>{preview.knowledge_point || '-'}</div>
              <div><strong>来源：</strong>{preview.source || '-'}</div>
              <div><strong>ID：</strong>{preview.id}</div>
            </div>
          </div>
        )}
      </Modal>

      {/* 添加 / 编辑题目弹窗 */}
      <Modal
        open={editor.open}
        title={editor.mode === 'create' ? '添加题目' : '编辑题目'}
        onClose={closeEditor}
        footer={(
          <>
            <button className="btn ghost" onClick={closeEditor}>取消</button>
            <button className="btn primary" onClick={handleSubmit}>保存</button>
          </>
        )}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
          <div>
            <strong style={{ color: 'var(--ink-2)' }}>题目内容 *</strong>
            <textarea
              className="input"
              rows={3}
              style={{ width: '100%', marginTop: 6, resize: 'vertical' }}
              value={editor.form.content}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, content: e.target.value } }))}
              placeholder="输入题干..."
            />
          </div>
          <div>
            <strong style={{ color: 'var(--ink-2)' }}>选项（每行一个，客观题填写）</strong>
            <textarea
              className="input"
              rows={4}
              style={{ width: '100%', marginTop: 6, resize: 'vertical' }}
              value={editor.form.optionsText}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, optionsText: e.target.value } }))}
              placeholder={'每行一个选项，例如：\n选项一\n选项二\n选项三'}
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <strong style={{ color: 'var(--ink-2)' }}>答案</strong>
              <input
                className="input"
                style={{ width: '100%', marginTop: 6 }}
                value={editor.form.answer}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, answer: e.target.value } }))}
                placeholder="如 A / 对 / 填空答案"
              />
            </div>
            <div>
              <strong style={{ color: 'var(--ink-2)' }}>题型</strong>
              <select
                className="select"
                style={{ width: '100%', marginTop: 6 }}
                value={editor.form.question_type}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, question_type: e.target.value } }))}
              >
                {QUESTION_TYPES.filter((t) => t.value !== 'all').map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <strong style={{ color: 'var(--ink-2)' }}>答案解析</strong>
            <textarea
              className="input"
              rows={3}
              style={{ width: '100%', marginTop: 6, resize: 'vertical' }}
              value={editor.form.analysis}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, analysis: e.target.value } }))}
              placeholder="可选"
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <strong style={{ color: 'var(--ink-2)' }}>科目</strong>
              <select
                className="select"
                style={{ width: '100%', marginTop: 6 }}
                value={editor.form.subject}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, subject: e.target.value } }))}
              >
                <option value="">未分类</option>
                {subjects.map((s) => <option key={s.subject} value={s.subject}>{s.subject}</option>)}
              </select>
            </div>
            <div>
              <strong style={{ color: 'var(--ink-2)' }}>难度（1-5）</strong>
              <select
                className="select"
                style={{ width: '100%', marginTop: 6 }}
                value={editor.form.difficulty}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, difficulty: e.target.value } }))}
              >
                {DIFFICULTY_OPTIONS.filter((d) => d.value !== 'all').map((d) => (
                  <option key={d.value} value={d.value}>{d.label}</option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <strong style={{ color: 'var(--ink-2)' }}>章节</strong>
              <input
                className="input"
                list="qb-chapters"
                style={{ width: '100%', marginTop: 6 }}
                value={editor.form.chapter}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, chapter: e.target.value } }))}
                placeholder="可选"
              />
              <datalist id="qb-chapters">
                {chapters.map((c) => <option key={c.chapter} value={c.chapter} />)}
              </datalist>
            </div>
            <div>
              <strong style={{ color: 'var(--ink-2)' }}>知识点</strong>
              <input
                className="input"
                style={{ width: '100%', marginTop: 6 }}
                value={editor.form.knowledge_point}
                onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, knowledge_point: e.target.value } }))}
                placeholder="可选"
              />
            </div>
          </div>
          <div>
            <strong style={{ color: 'var(--ink-2)' }}>来源</strong>
            <input
              className="input"
              style={{ width: '100%', marginTop: 6 }}
              value={editor.form.source}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, source: e.target.value } }))}
              placeholder="可选，如 真题2024"
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
