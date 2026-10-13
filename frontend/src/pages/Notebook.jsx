import React, { useMemo, useState, useCallback, useEffect, useRef } from 'react'
import useStore from '../store/useStore'
import { fmtDateCN, todayStr } from '../utils/date'
import { toApiId } from '../utils/id'
import { SubTag, Modal, Segmented, Empty, toast, CountUp } from '../components/UI'
import { errorsApi, flashcardsApi, taxonomyApi } from '../api/client'
import { fileToCompressedDataUrl, dataUrlToFile } from '../utils/image'

/* ---------- 将后端错题对象映射为前端视图模型 ---------- */
function mapError(e) {
  let tags = []
  if (typeof e.tags === 'string') {
    try { tags = JSON.parse(e.tags || '[]') } catch { tags = [] }
  } else if (Array.isArray(e.tags)) tags = e.tags
  return {
    id: String(e.id),
    subject: e.subject || 'major',
    question: e.content || '',
    answer: e.correct_answer || '',
    myAnswer: e.my_answer || '',
    analysis: e.analysis || '',
    reason: e.error_reason || '',
    status: e.status || 'active',
    tags,
    reviewCount: e.review_count || 0,
    lastReview: e.last_review,
    nextReview: e.next_review,
    createdAt: e.created_at
  }
}

/* 本地相似题占位（后端未返回时使用） */
function genSimilar(n) {
  const q = (n.question || '').slice(0, 18)
  return [
    { title: `变式训练：${q}…（同考点不同条件）`, kind: '同考点' },
    { title: `思路复述：请口述 ${q}… 的解题步骤`, kind: '思路' },
    { title: `拓展迁移：将本题结论推广到一般情形并证明`, kind: '拓展' }
  ]
}

/* 旧英文科目码 → 中文（历史数据兼容）；真实科目（数字电子技术/模拟电子技术/专业课/政治/数学/英语…）
   本身即中文，直接原样显示，不再退化成错误的「专业课」。 */
const SUBJECT_CODE_MAP = { math: '数学', english: '英语', politics: '政治', major: '专业课' }
const subjectName = (s) => SUBJECT_CODE_MAP[s] || s || '专业课'

// 掌握度饼图组件
function MasteryPie({ level, size = 32 }) {
  const percentage = Math.min(level / 7 * 100, 100)
  const color = percentage >= 80 ? 'var(--green)' : percentage >= 50 ? 'var(--gold)' : percentage >= 20 ? 'var(--orange)' : 'var(--red)'
  const circumference = 2 * Math.PI * 14
  const offset = circumference - (percentage / 100) * circumference
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" style={{ flexShrink: 0 }}>
      <circle cx="16" cy="16" r="14" fill="none" stroke="var(--surface-3)" strokeWidth="3" />
      <circle cx="16" cy="16" r="14" fill="none" stroke={color} strokeWidth="3"
        strokeDasharray={circumference} strokeDashoffset={offset}
        strokeLinecap="round" transform="rotate(-90 16 16)"
        style={{ transition: 'stroke-dashoffset 0.5s ease' }} />
    </svg>
  )
}

export default function Notebook() {
  const notebook = useStore((s) => s.notebook)
  const packs = useStore((s) => s.packs)
  const [backendOk, setBackendOk] = useState(false)
  const [filter, setFilter] = useState('all')
  const [subject, setSubject] = useState('all')
  const [subjectOptions, setSubjectOptions] = useState([])
  const [q, setQ] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [viewMode, setViewMode] = useState('grid') // 'list' | 'grid'
  const [form, setForm] = useState({ question: '', answer: '', analysis: '', reason: '', subject: '', tags: '' })
  const [ocrBusy, setOcrBusy] = useState(false)
  const [aiBusy, setAiBusy] = useState(false)
  const ocrRef = useRef(null)
  const captureRef = useRef(null)
  const ocrBatchRef = useRef(null)
  const today = todayStr()

  /* 批量 OCR 相关 */
  const [selectedIds, setSelectedIds] = useState([])
  const [showOcrBatch, setShowOcrBatch] = useState(false)
  const [ocrBatchBusy, setOcrBatchBusy] = useState(false)
  const [ocrProgress, setOcrProgress] = useState(0)

  /* 详情弹窗 + 相似题 */
  const [showDetail, setShowDetail] = useState(null)
  const [detailShowAnswer, setDetailShowAnswer] = useState(false)
  const [similarMap, setSimilarMap] = useState({})

  /* V2.0 复习模式 + 四档评分 + 复习总结 */
  const [reviewMode, setReviewMode] = useState(false)
  const [reviewQueue, setReviewQueue] = useState([])
  const [reviewIdx, setReviewIdx] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [reviewStats, setReviewStats] = useState({ again: 0, hard: 0, good: 0, easy: 0, startTime: null })

  /* ---- 从后端加载错题（成功则写入 store） ---- */
  const refresh = useCallback(async () => {
    try {
      const data = await errorsApi.list({ page: 1, page_size: 200 })
      const list = data.errors || data.items || []
      if (Array.isArray(list)) {
        const mapped = list.map(mapError)
        useStore.setState({ notebook: mapped })
        setBackendOk(true)
      }
    } catch {
      setBackendOk(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  /* 动态加载科目（V8：GET /api/taxonomy/subjects → 数组 [{subject,...}]，兼容旧 {items} 形态）。
     合并当前错题里出现、但题库尚未统计到的科目，避免筛选器把真实科目漏掉。 */
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const r = await taxonomyApi.subjects()
        const items = Array.isArray(r) ? r : (r && (r.subjects || r.items)) || []
        if (alive) setSubjectOptions(items.map((x) => x.subject).filter(Boolean))
      } catch { /* 后端不可用时退化为仅用错题自身科目 */ }
    })()
    return () => { alive = false }
  }, [])

  const allSubjects = useMemo(() => {
    const set = new Set(subjectOptions)
    notebook.forEach((n) => { if (n.subject) set.add(n.subject) })
    return Array.from(set)
  }, [subjectOptions, notebook])

  const list = useMemo(() => {
    let arr = notebook.map((n) => ({
      ...n,
      rs: {
        status: n.status === 'graduated' ? 'mastered' : (n.status === 'done' ? 'mastered' : (n.status === 'active' ? 'due' : 'reviewing')),
        due: n.status === 'active'
      }
    }))
    if (filter === 'active') arr = arr.filter((x) => x.status !== 'graduated')
    if (filter === 'graduated') arr = arr.filter((x) => x.status === 'graduated')
    if (subject !== 'all') arr = arr.filter((x) => x.subject === subject)
    if (q.trim()) arr = arr.filter((x) => (x.question + x.answer + (x.tags || []).join('')).toLowerCase().includes(q.toLowerCase()))
    return arr
  }, [notebook, filter, subject, q])

  const counts = useMemo(() => ({
    total: notebook.length,
    due: notebook.filter((n) => n.status === 'active').length,
    reviewing: notebook.filter((n) => n.status === 'active' && (n.review_count || 0) > 0).length,
    mastered: notebook.filter((n) => n.status === 'graduated').length
  }), [notebook])

  const toggleSelect = (id) => {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
  }

  const patchError = async (id, patch) => {
    if (backendOk) {
      try { await errorsApi.update(Number(id), patch) } catch {}
    }
    useStore.setState({ notebook: useStore.getState().notebook.map((x) => (x.id === id ? { ...x, ...patch } : x)) })
  }

  const submit = async () => {
    if (!form.question.trim() || !form.answer.trim()) return toast('请填写题干与答案')
    if (!form.subject) return toast('请选择科目')
    if (backendOk) {
      try {
        await errorsApi.create({
          content: form.question.trim(),
          correct_answer: form.answer.trim(),
          analysis: form.analysis.trim() || null,
          error_reason: form.reason.trim() || null,
          subject: form.subject,
          tags: form.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
        })
        await refresh()
        toast('错题已收录到云端，按艾宾浩斯排入复习')
      } catch (e) {
        toast(`后端保存失败：${e.message}`)
      }
    } else {
      const st = useStore.getState()
      useStore.setState({
        notebook: [{ id: 'n' + Date.now(), status: 'active', createdAt: today, lastReview: null, reviewCount: 0, question: form.question.trim(), answer: form.answer.trim(), analysis: form.analysis.trim(), reason: form.reason.trim(), subject: form.subject, tags: form.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean), myAnswer: '' }, ...st.notebook]
      })
      toast('错题已收录（本地模式）')
    }
    setForm({ question: '', answer: '', analysis: '', reason: '', subject: '', tags: '' })
    setShowAdd(false)
  }

  const reviewFlow = async (id, correct) => {
    if (backendOk) {
      try {
        await errorsApi.update(Number(id), { status: correct ? 'graduated' : 'active', review_count: (notebook.find(n => String(n.id) === String(id))?.review_count || 0) + (correct ? 1 : -1) })
        await refresh()
      } catch (e) {
        toast(`同步失败：${e.message}`)
      }
    } else {
      const st = useStore.getState()
      useStore.setState({
        notebook: st.notebook.map((n) => (n.id === id ? { ...n, status: correct ? 'graduated' : 'active', lastReview: today } : n))
      })
    }
    toast(correct ? '回答正确，已推进复习进度' : '答错了，稍后再复习')
  }

  /* V2.0 四档评分复习 */
  const startReview = () => {
    const dueList = notebook.filter(n => n.status === 'active')
    if (dueList.length === 0) return toast('今日没有待复习的错题')
    setReviewQueue(dueList)
    setReviewIdx(0)
    setShowAnswer(false)
    setReviewStats({ again: 0, hard: 0, good: 0, easy: 0, startTime: Date.now() })
    setReviewMode(true)
    setFilter('active')
  }

  const reviewWithGrade = async (grade) => {
    const current = reviewQueue[reviewIdx]
    if (!current) return
    // 更新统计
    const gradeKey = grade === 1 ? 'again' : grade === 2 ? 'hard' : grade === 3 ? 'good' : 'easy'
    setReviewStats(prev => ({ ...prev, [gradeKey]: prev[gradeKey] + 1 }))
    // 根据评分更新掌握度和状态
    const newReviewCount = (current.reviewCount || 0) + (grade >= 3 ? 1 : 0)
    const newStatus = grade === 4 && newReviewCount >= 4 ? 'graduated' : 'active'
    await patchError(current.id, {
      review_count: newReviewCount,
      status: newStatus,
      last_review: today
    })
    setShowAnswer(false)
    // 下一题或结束
    if (reviewIdx + 1 < reviewQueue.length) {
      setReviewIdx(reviewIdx + 1)
    } else {
      // 复习完成，显示总结
      setReviewMode(false)
      refresh()
      toast(`复习完成！共 ${reviewQueue.length} 道题`)
    }
  }

  const exitReview = () => {
    setReviewMode(false)
    setReviewQueue([])
    setReviewIdx(0)
    setShowAnswer(false)
  }

  const graduate = async (id) => {
    if (backendOk) {
      try {
        await errorsApi.update(Number(id), { status: 'graduated' })
        await refresh()
        toast('已毕业移出')
      } catch { toast('操作失败') }
    } else {
      const st = useStore.getState()
      useStore.setState({ notebook: st.notebook.map((n) => (n.id === id ? { ...n, status: 'graduated' } : n)) })
      toast('已毕业移出')
    }
  }

  const remove = async (id) => {
    if (backendOk) {
      try {
        await errorsApi.remove(Number(id))
        await refresh()
        toast('已删除')
      } catch { toast('删除失败') }
    } else {
      useStore.setState({ notebook: useStore.getState().notebook.filter((n) => n.id !== id) })
      toast('已删除')
    }
    setSelectedIds((prev) => prev.filter((x) => x !== id))
  }

  /* AI 深度分析 + 相似题推荐 */
  const aiAnalyze = async (n) => {
    if (!backendOk) { setSimilarMap((m) => ({ ...m, [n.id]: genSimilar(n) })); return toast('需连接后端后使用 AI 分析，已展示本地推荐') }
    setAiBusy(true)
    try {
      const apiId = toApiId(n.id)
      const r = await errorsApi.aiAnalyze(apiId)
      useStore.setState({
        notebook: useStore.getState().notebook.map((x) => (x.id === n.id ? { ...x, analysis: r.analysis } : x))
      })
      const sim = r.similar_questions || r.similar || genSimilar(n)
      setSimilarMap((m) => ({ ...m, [n.id]: sim }))
      toast('AI 分析完成')
    } catch (e) {
      setSimilarMap((m) => ({ ...m, [n.id]: genSimilar(n) }))
      toast(`AI 分析失败：${e.message}`)
    }
    setAiBusy(false)
  }

  /* 错题 → 记忆卡片 */
  const toCard = async (n) => {
    if (backendOk) {
      try {
        await flashcardsApi.create({ front: n.question, back: n.answer, hint: n.analysis || n.reason || '', subject: n.subject, knowledge_point_id: null })
        toast('已生成记忆卡片')
      } catch (e) { toast(`转卡失败：${e.message}`) }
    } else {
      if (!packs.length) return toast('请先在「记忆卡片」页创建卡包')
      useStore.getState().addCard({ front: n.question, back: n.answer, hint: n.analysis || n.reason || '', subject: n.subject, packId: packs[0].id })
      toast('已生成记忆卡片')
    }
  }

  /* OCR 上传（后端 RapidOCR，单条）
     手机场景：先做 EXIF 方向纠正 + 压缩，再上传。
     否则竖拍照片会躺倒，OCR 基本认不出；且原图 5-8MB 上传很慢。 */
  const ocrUpload = async (file) => {
    if (!file) return
    if (!backendOk) return toast('需先连接后端（8000）才能使用 OCR')
    setOcrBusy(true)
    try {
      let upload = file
      try {
        const { dataUrl } = await fileToCompressedDataUrl(file, { maxSide: 1800, quality: 0.85 })
        upload = dataUrlToFile(dataUrl, (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg')
      } catch (e) {
        // 压缩失败（如 HEIC）时明确提示，而不是让它变成一个看不懂的 OCR 错误
        toast(e.message)
        setOcrBusy(false)
        if (ocrRef.current) ocrRef.current.value = ''
        return
      }
      const fd = new FormData()
      fd.append('file', upload)
      const r = await errorsApi.ocr(fd)
      if (r.raw_text) {
        setForm({ ...form, question: r.raw_text.slice(0, 800) })
        setShowAdd(true)
        toast(`OCR 识别成功（识别到 ${r.count || 0} 道题），请核对收录`)
      } else {
        toast('OCR 未识别到内容')
      }
    } catch (e) {
      toast(`OCR 失败：${e.message}`)
    }
    setOcrBusy(false)
    if (ocrRef.current) ocrRef.current.value = ''
  }

  /* 批量 OCR：对选中错题依次调用 errorsApi.ocr */
  const applyOcrBatch = async (files) => {
    if (!backendOk) return toast('需连接后端（8000）才能使用批量 OCR')
    if (!files || !files.length) return
    const ids = [...selectedIds]
    setOcrBatchBusy(true)
    setOcrProgress(0)
    try {
      for (let i = 0; i < files.length; i++) {
        const fd = new FormData()
        fd.append('file', files[i])
        const r = await errorsApi.ocr(fd)
        const text = (r.raw_text || '').slice(0, 800)
        setOcrProgress(i + 1)
        const id = ids[i]
        if (id != null && text) {
          const n = useStore.getState().notebook.find((x) => String(x.id) === String(id))
          if (n) {
            const newQ = (n.question ? n.question + '\n' : '') + text
            await patchError(id, { question: newQ })
          }
        }
      }
      toast(`批量识别完成（${files.length} 张图片）`)
    } catch (e) {
      toast(`批量 OCR 失败：${e.message}`)
    } finally {
      setOcrBatchBusy(false)
      setSelectedIds([])
      setShowOcrBatch(false)
      refresh()
    }
  }

  const openDetail = (n) => {
    setShowDetail(n)
    setDetailShowAnswer(false)
    if (!similarMap[n.id]) setSimilarMap((m) => ({ ...m, [n.id]: genSimilar(n) }))
  }

  return (
    <div className="container stack">
      <div className="page-head">
        <div>
          <h1 className="page-title">错题本</h1>
          <p className="page-sub">
            七刷机制 + 艾宾浩斯遗忘曲线 · 答错自动入册，答对提升掌握度
            {backendOk ? <span className="live-dot"> · 后端已连接</span> : <span className="offline-dot"> · 本地模式</span>}
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" disabled={ocrBusy} onClick={() => captureRef.current?.click()}>
            {ocrBusy ? '识别中…' : '📷 拍照收录'}
          </button>
          <button className="btn ghost" disabled={ocrBusy} onClick={() => ocrRef.current?.click()}>
            {ocrBusy ? '识别中…' : '🖼 相册上传'}
          </button>
          {/* capture=environment 让手机直接调后置摄像头；桌面端会退化为选文件 */}
          <input ref={captureRef} type="file" accept="image/*" capture="environment"
            style={{ display: 'none' }} onChange={(e) => ocrUpload(e.target.files[0])} />
          <input ref={ocrRef} type="file" accept="image/*" style={{ display: 'none' }}
            onChange={(e) => ocrUpload(e.target.files[0])} />
          <button className="btn ghost" onClick={() => setShowAdd(true)}>+ 手动录入</button>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-tile"><span className="st-ico blue">📚</span><span className="st-val"><CountUp value={counts.total} /></span><span className="st-label">全部错题</span></div>
        <div className="stat-tile"><span className="st-ico red">🔴</span><span className="st-val" style={{ color: 'var(--red)' }}><CountUp value={counts.due} /></span><span className="st-label">待复习</span></div>
        <div className="stat-tile"><span className="st-ico amber">🔁</span><span className="st-val" style={{ color: 'var(--gold)' }}><CountUp value={counts.reviewing} /></span><span className="st-label">七刷中</span></div>
        <div className="stat-tile"><span className="st-ico green">✅</span><span className="st-val" style={{ color: 'var(--green)' }}><CountUp value={counts.mastered} /></span><span className="st-label">已毕业</span></div>
      </div>

      {/* 今日待复习汇总条 */}
      <div className="card" style={{ background: 'var(--accent-soft)', borderColor: 'rgba(30,111,217,0.25)' }}>
        <div className="spread">
          <div>
            <div className="card-title" style={{ color: 'var(--accent)' }}>今日待复习：{counts.due} 道</div>
            <div className="card-sub">错题 {counts.due} · 按艾宾浩斯曲线自动排入复习</div>
          </div>
          <button className="btn primary" onClick={startReview}>▷ 开始今日复习</button>
        </div>
      </div>

      <div className="toolbar">
        <div className="left">
          <Segmented
            options={[{ label: '全部', value: 'all' }, { label: '未毕业', value: 'active' }, { label: '已毕业', value: 'graduated' }]}
            value={filter} onChange={setFilter}
          />
          <select className="select" style={{ width: 130 }} value={subject} onChange={(e) => setSubject(e.target.value)}>
            <option value="all">全部科目</option>
            {allSubjects.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <div className="search">
            <span>🔍</span>
            <input placeholder="搜索题干 / 答案 / 标签" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        <div className="right">
          <Segmented options={[{ label: '☰ 列表', value: 'list' }, { label: '▦ 卡片', value: 'grid' }]} value={viewMode} onChange={setViewMode} />
        </div>
      </div>

      {/* V2.0 复习模式界面 */}
      {reviewMode && reviewQueue.length > 0 && (
        <div className="card" style={{ borderColor: 'var(--accent)', borderWidth: 2 }}>
          <div className="spread" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <MasteryPie level={reviewQueue[reviewIdx]?.reviewCount || 0} size={32} />
              <span className="badge accent">复习模式</span>
              <SubTag subject={reviewQueue[reviewIdx]?.subject} />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="badge neutral">{reviewIdx + 1} / {reviewQueue.length}</span>
              <button className="btn sm ghost" onClick={exitReview}>退出复习</button>
            </div>
          </div>

          {/* 进度条 */}
          <div className="progress thin" style={{ marginBottom: 16 }}>
            <i style={{ width: `${((reviewIdx + 1) / reviewQueue.length) * 100}%` }} />
          </div>

          {/* 题目显示 */}
          <div style={{ marginBottom: 16 }}>
            <div className="card-sub" style={{ marginBottom: 8 }}>题干</div>
            <div style={{ fontSize: 16, lineHeight: 1.8, padding: 16, background: 'var(--surface-2)', borderRadius: 8 }}>
              {reviewQueue[reviewIdx]?.question}
            </div>
          </div>

          {/* 答案显示 */}
          {showAnswer && (
            <div style={{ marginBottom: 16 }}>
              <div className="card-sub" style={{ marginBottom: 8 }}>答案</div>
              <div style={{ fontSize: 15, lineHeight: 1.7, padding: 16, background: 'var(--green-soft)', borderRadius: 8, borderLeft: '4px solid var(--green)' }}>
                {reviewQueue[reviewIdx]?.answer}
              </div>
              {reviewQueue[reviewIdx]?.analysis && (
                <div style={{ marginTop: 8, padding: 12, background: 'var(--gold-soft)', borderRadius: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--gold)', marginBottom: 4 }}>解析</div>
                  <div style={{ fontSize: 13, lineHeight: 1.6 }}>{reviewQueue[reviewIdx]?.analysis}</div>
                </div>
              )}
            </div>
          )}

          {/* 操作按钮 */}
          {!showAnswer ? (
            <button className="btn primary block" style={{ fontSize: 16, padding: '12px' }} onClick={() => setShowAnswer(true)}>
              显示答案
            </button>
          ) : (
            <div>
              <div className="grid-4" style={{ gap: 8, marginBottom: 8 }}>
                <button className="btn" onClick={() => reviewWithGrade(1)}
                  style={{ background: 'var(--red-soft)', color: 'var(--red)', border: 'none', padding: '12px 4px' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>忘记</div>
                  <div style={{ fontSize: 11, opacity: 0.8 }}>重新学习</div>
                </button>
                <button className="btn" onClick={() => reviewWithGrade(2)}
                  style={{ background: 'var(--gold-soft)', color: 'var(--gold)', border: 'none', padding: '12px 4px' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>模糊</div>
                  <div style={{ fontSize: 11, opacity: 0.8 }}>1天后复习</div>
                </button>
                <button className="btn" onClick={() => reviewWithGrade(3)}
                  style={{ background: 'var(--accent-soft)', color: 'var(--accent)', border: 'none', padding: '12px 4px' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>记得</div>
                  <div style={{ fontSize: 11, opacity: 0.8 }}>3天后复习</div>
                </button>
                <button className="btn primary" onClick={() => reviewWithGrade(4)} style={{ padding: '12px 4px' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>简单</div>
                  <div style={{ fontSize: 11, opacity: 0.8 }}>7天后复习</div>
                </button>
              </div>
              <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--ink-3)' }}>
                快捷键：1=忘记 2=模糊 3=记得 4=简单
              </div>
            </div>
          )}
        </div>
      )}

      {/* V2.0 复习总结页（复习完成后显示） */}
      {!reviewMode && reviewStats.startTime && reviewQueue.length > 0 && reviewIdx >= reviewQueue.length && (
        <div className="card" style={{ padding: 24, borderColor: 'var(--green)', borderWidth: 2 }}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>🎉</div>
            <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 4 }}>本轮复习完成！</h2>
            <p className="card-sub">共复习 {reviewQueue.length} 道错题</p>
          </div>
          <div className="stat-grid" style={{ marginBottom: 24 }}>
            <div className="stat-tile"><span className="st-ico red">🔴</span><span className="st-val" style={{ color: 'var(--red)' }}>{reviewStats.again}</span><span className="st-label">忘记</span></div>
            <div className="stat-tile"><span className="st-ico amber">🟡</span><span className="st-val" style={{ color: 'var(--gold)' }}>{reviewStats.hard}</span><span className="st-label">模糊</span></div>
            <div className="stat-tile"><span className="st-ico blue">🔵</span><span className="st-val" style={{ color: 'var(--accent)' }}>{reviewStats.good}</span><span className="st-label">记得</span></div>
            <div className="stat-tile"><span className="st-ico green">🟢</span><span className="st-val" style={{ color: 'var(--green)' }}>{reviewStats.easy}</span><span className="st-label">简单</span></div>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button className="btn primary" style={{ flex: 1 }} onClick={startReview}>再来一轮</button>
            <button className="btn ghost" style={{ flex: 1 }} onClick={() => { setReviewStats({ again: 0, hard: 0, good: 0, easy: 0, startTime: null }); setReviewQueue([]); setReviewIdx(0) }}>返回列表</button>
          </div>
        </div>
      )}

      {/* 批量操作条 */}
      {selectedIds.length > 0 && (
        <div className="card" style={{ background: 'var(--blue-soft)' }}>
          <div className="spread">
            <span className="card-sub">已选择 {selectedIds.length} 道错题</span>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn primary sm" onClick={() => setShowOcrBatch(true)}>批量识别</button>
              <button className="btn ghost sm" onClick={() => setSelectedIds([])}>取消选择</button>
            </div>
          </div>
        </div>
      )}

      {list.length === 0 ? (
        <Empty icon={<span style={{ fontSize: 36 }}>📝</span>} title="没有匹配的错题" desc="调整筛选条件，或点击「收录错题」记录一道" />
      ) : viewMode === 'grid' ? (
        <div className="grid-3">
          {list.map((n) => (
            <div key={n.id} className="card">
              <div className="card-head">
                <div className="row" style={{ gap: 8 }}>
                  <MasteryPie level={n.reviewCount || 0} size={28} />
                  <input type="checkbox" checked={selectedIds.includes(n.id)} onChange={() => toggleSelect(n.id)} aria-label="选择" />
                  <SubTag subject={n.subject} />
                </div>
                <span className={`badge ${n.status === 'graduated' ? 'success' : 'warning'}`}>{n.status === 'graduated' ? '已毕业' : '待复习'}</span>
              </div>
              <div className="lr-title" style={{ marginBottom: 8, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{n.question}</div>
              <div className="lr-meta">复习 {n.reviewCount || 0} 次 · {subjectName(n.subject)}</div>
              <div className="hr" />
              <div className="row wrap" style={{ gap: 6 }}>
                <button className="btn sm ghost" onClick={() => reviewFlow(n.id, true)}>答对</button>
                <button className="btn sm ghost" onClick={() => reviewFlow(n.id, false)}>答错</button>
                <button className="btn sm outline" onClick={() => toCard(n)}>转卡</button>
                <button className="btn sm ghost" onClick={() => openDetail(n)}>详情</button>
                <button className="btn sm danger" onClick={() => remove(n.id)}>删除</button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="list">
          {list.map((n) => (
            <div key={n.id} className="list-row">
              <input type="checkbox" checked={selectedIds.includes(n.id)} onChange={() => toggleSelect(n.id)} aria-label="选择" />
              <span className="lr-ico" style={{ background: 'var(--surface-2)', color: 'var(--accent)' }}>{subjectName(n.subject).slice(0, 1)}</span>
              <div className="lr-main" onClick={() => openDetail(n)} style={{ cursor: 'pointer' }}>
                <div className="lr-title">{n.question}</div>
                <div className="lr-meta">复习 {n.reviewCount} 次 · {n.lastReview ? `上次 ${fmtDateCN(n.lastReview.slice(0, 10))}` : '未复习'}</div>
              </div>
              <div className="lr-actions">
                <button className="btn sm ghost" onClick={() => toCard(n)}>转卡</button>
                <button className="btn sm outline" disabled={aiBusy} onClick={() => aiAnalyze(n)}>{aiBusy ? '分析中…' : 'AI 精讲'}</button>
                <button className="btn sm ghost" onClick={() => graduate(n.id)}>毕业</button>
                <button className="btn sm danger" onClick={() => remove(n.id)}>删除</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal open={showAdd} title="收录错题" onClose={() => setShowAdd(false)}
        footer={<React.Fragment><button className="btn ghost" onClick={() => setShowAdd(false)}>取消</button><button className="btn primary" onClick={submit}>收录</button></React.Fragment>}>
        <label>科目
          <select className="input" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })}>
            <option value="" disabled>请选择科目</option>
            {allSubjects.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>题目
          <textarea className="input" rows={3} value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} placeholder="原题或题干" />
        </label>
        <label>正确答案
          <textarea className="input" rows={2} value={form.answer} onChange={(e) => setForm({ ...form, answer: e.target.value })} placeholder="完整答案" />
        </label>
        <label>解析（可选）
          <textarea className="input" rows={2} value={form.analysis} onChange={(e) => setForm({ ...form, analysis: e.target.value })} placeholder="考点、易错点分析" />
        </label>
        <label>失分原因（可选）
          <input className="input" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="如：概念混淆" />
        </label>
        <label>标签（逗号分隔）
          <input className="input" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder="极限, 等价无穷小" />
        </label>
      </Modal>

      {/* 批量 OCR 弹窗 */}
      <Modal open={showOcrBatch} title="批量识别（OCR）" onClose={() => !ocrBatchBusy && setShowOcrBatch(false)}
        footer={<button className="btn ghost" onClick={() => setShowOcrBatch(false)} disabled={ocrBatchBusy}>关闭</button>}>
        <p className="card-sub" style={{ marginBottom: 12 }}>为选中的 {selectedIds.length} 道错题上传图片，系统将逐张识别并回填到对应错题题干。</p>
        <div className="dropzone" onClick={() => ocrBatchRef.current?.click()}>
          <div style={{ fontSize: 30 }}>🖼️</div>
          <div>点击选择多张图片（按顺序对应选中错题）</div>
          <input ref={ocrBatchRef} type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={(e) => applyOcrBatch(Array.from(e.target.files || []))} />
        </div>
        {ocrBatchBusy && (
          <div className="loading-inline">识别中… {ocrProgress} / {selectedIds.length}</div>
        )}
      </Modal>

      {/* 错题详情 + AI 相似题推荐 */}
      <Modal open={!!showDetail} title="错题详情" onClose={() => setShowDetail(null)}>
        {showDetail && (
          <div className="stack">
            {/* 上一题/下一题导航 */}
            {(() => {
              const curIdx = list.findIndex(n => n.id === showDetail.id)
              const hasPrev = curIdx > 0
              const hasNext = curIdx >= 0 && curIdx < list.length - 1
              return (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'var(--surface-2)', borderRadius: 8, marginBottom: 12 }}>
                  <button className="btn sm ghost" onClick={() => { if (hasPrev) { setShowDetail(list[curIdx - 1]); setDetailShowAnswer(false) } }} disabled={!hasPrev}>← 上一题</button>
                  <span style={{ fontSize: 13, color: 'var(--ink-3)' }}>{curIdx >= 0 ? `第 ${curIdx + 1} / ${list.length} 题` : ''}</span>
                  <button className="btn sm ghost" onClick={() => { if (hasNext) { setShowDetail(list[curIdx + 1]); setDetailShowAnswer(false) } }} disabled={!hasNext}>下一题 →</button>
                </div>
              )
            })()}
            <div className="row" style={{ gap: 8 }}>
              <SubTag subject={showDetail.subject} />
              <span className={`badge ${showDetail.status === 'graduated' ? 'success' : 'warning'}`}>{showDetail.status === 'graduated' ? '已毕业' : '待复习'}</span>
            </div>
            <div>
              <div className="card-sub">题干</div>
              <div style={{ fontSize: 14, lineHeight: 1.6 }}>{showDetail.question}</div>
            </div>
            <button className="btn sm ghost" onClick={() => setDetailShowAnswer((v) => !v)}>
              {detailShowAnswer ? '收起答案 / 解析 ▲' : '显示答案 / 解析 ▼'}
            </button>
            {detailShowAnswer && (
              <>
                <div>
                  <div className="card-sub">答案</div>
                  <div style={{ fontSize: 14 }}>{showDetail.answer}</div>
                </div>
                {showDetail.analysis && <div><div className="card-sub">解析</div><div style={{ fontSize: 13.5, color: 'var(--gold)' }}>{showDetail.analysis}</div></div>}
              </>
            )}
            {showDetail.reason && <div><div className="card-sub">失分原因</div><div style={{ fontSize: 13.5, color: 'var(--ink-3)' }}>{showDetail.reason}</div></div>}
            <div className="hr" />
            <div className="sec-title"><h3>AI 相似题推荐</h3><button className="btn sm ghost" disabled={aiBusy} onClick={() => aiAnalyze(showDetail)}>{aiBusy ? '生成中…' : '刷新推荐'}</button></div>
            <div className="list">
              {(similarMap[showDetail.id] || genSimilar(showDetail)).map((s, i) => (
                <div key={i} className="list-row">
                  <span className="lr-ico" style={{ background: 'var(--violet-soft)', color: 'var(--violet)' }}>💡</span>
                  <div className="lr-main"><div className="lr-title">{s.title}</div><div className="lr-meta">{s.kind}</div></div>
                </div>
              ))}
            </div>
            <div className="row wrap" style={{ gap: 8 }}>
              <button className="btn sm ghost" onClick={() => reviewFlow(showDetail.id, true)}>答对 +1</button>
              <button className="btn sm outline" onClick={() => toCard(showDetail)}>转记忆卡片</button>
              <button className="btn sm ghost" onClick={() => graduate(showDetail.id)}>毕业</button>
              <button className="btn sm danger" onClick={() => { remove(showDetail.id); setShowDetail(null) }}>删除</button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
