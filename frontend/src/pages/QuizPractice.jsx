import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from '../components/UI'
import MathText from '../components/MathText'
import { quizApi, request } from '../api/client'
import {
  TYPE_LABELS, LETTERS, letterOf, addWrong, pushRec,
  isChoiceQ, isMultiQ, isTextQuestion, isChoiceWithoutOptions,
  isCorrectOption, stripOptLabel, dependsOnFigure, questionMark,
} from './quizShared'

/* =====================================================================
 * 刷题中心 · 答题区（自 Quiz.jsx 拆出）
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
function mediaSrc(img) {
  const raw = img?.url || img?.path || img?.src || ''
  if (!raw) return ''
  if (/^(?:[a-z]+:)?\/\//i.test(raw) || raw.startsWith('/')) return raw
  return MEDIA_IMAGES_PREFIX + raw.replace(/^\/+/, '')
}

export default function QuizPractice({
  session, records, basis, favs, kpFilter, backendOk,
  tutorMode, setTutorMode, submitting, setSubmitting,
  onRecord, onToggleFav, onGoHome, onFinish,
}) {
  const navigate = useNavigate()
  /* ---------- 练习会话（本视图独占，随挂载自然重置） ---------- */
  const [idx, setIdx] = useState(session.startIdx ?? 0)
  const [drafts, setDrafts] = useState({})         // 选择题提交前草稿
  const [textDraft, setTextDraft] = useState({})      // 文本题草稿
  const [selfCheck, setSelfCheck] = useState(null)   // 文本题对照 {qid,myAns,correctAnswer,analysis}
  /* AI 生成解析（复用现有 /ai/tutoring/explain，仅前端展示、不落库） */
  const [aiAnalyses, setAiAnalyses] = useState({})   // { [qid]: {content, provider, loading, error} }

  /* ================= 作答与判分 ================= */
  /* 多选仍需逐个勾选后判分；单选/判断在 toggleDraft 里点选即判。 */
  const toggleDraft = (qid, i) => {
    const q = session.questions[idx]
    if (records[qid]) return
    if (isMultiQ(q)) {
      setDrafts((prev) => {
        const cur = Array.isArray(prev[qid]) ? prev[qid] : []
        const next = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort((a, b) => a - b)
        return { ...prev, [qid]: next }
      })
      return
    }
    // 单选/判断：记录草稿并立即判分，点选即给反馈，不等提交
    setDrafts((prev) => ({ ...prev, [qid]: i }))
    gradeChoice(q, i)
  }

  /* 选择题判分。sel 为下标或下标数组（多选）。 */
  const gradeChoice = async (q, sel) => {
    if (records[q.id] || selfCheck || submitting) return
    const myAns = Array.isArray(sel) ? sel.map(letterOf).join('') : letterOf(sel)
    // 浏览模式（无标准答案题）：不调用判分接口、不写错题本，仅记录用户作答供自检
    if (session?.noAnswer) {
      onRecord(q.id, { selfCheckOnly: true, selected: myAns, correctAnswer: '', analysis: '' })
      toast('浏览模式：本题暂无标准答案，请对照教材/解析自检')
      return
    }
    let correct = false, correctAnswer = q.answer, analysis = q.analysis
    if (backendOk && !q.id.startsWith('l')) {
      setSubmitting(true)
      try {
        const r = await quizApi.submit({ question_id: Number(q.id), my_answer: myAns })
        correct = !!r.correct
        correctAnswer = r.correct_answer ?? correctAnswer
        analysis = r.analysis ?? analysis
      } catch {
        correct = String(myAns).toUpperCase() === String(q.answer).toUpperCase()
      } finally { setSubmitting(false) }
    } else {
      correct = String(myAns).toUpperCase() === String(q.answer).toUpperCase()
    }
    applyGrade(q, correct, myAns, correctAnswer, analysis)
  }

  const applyGrade = (q, correct, selected, correctAnswer, analysis) => {
    if (session?.noAnswer) {
      onRecord(q.id, { selfCheckOnly: true, selected, correctAnswer: '', analysis: '' })
      return
    }
    onRecord(q.id, { correct, selected, correctAnswer, analysis })
    pushRec(q.id, correct)   // V10 本地作答累计（做过次数 + 最近对错）
    if (correct) toast('回答正确')
    else { addWrong(q.id); toast('答错已加入错题本') }
  }

  const doSubmit = async () => {
    if (!session) return
    const q = session.questions[idx]
    if (records[q.id] || selfCheck) return
    if (submitting) return

    /* ---- 多选题：勾选后提交 ---- */
    if (isChoiceQ(q) && isMultiQ(q)) {
      const sel = drafts[q.id]
      const empty = sel == null || (Array.isArray(sel) && !sel.length)
      if (empty) { toast('请至少选择一个选项'); return }
      await gradeChoice(q, sel)
      return
    }

    /* ---- 文本题（填空/简答/计算/作图）：输入 → 对照 → 自评 ---- */
    const txt = (textDraft[q.id] || '').trim()
    if (!txt) { toast('请先输入你的作答，再点「对照答案」'); return }
    let correctAnswer = q.answer, analysis = q.analysis
    if (backendOk && !q.id.startsWith('l')) {
      setSubmitting(true)
      try {
        const r = await quizApi.submit({ question_id: Number(q.id), my_answer: txt })
        correctAnswer = r.correct_answer ?? correctAnswer
        analysis = r.analysis ?? analysis
      } catch { /* 自评模式，后端不可用不影响 */ } finally { setSubmitting(false) }
    }
    setSelfCheck({ qid: q.id, myAns: txt, correctAnswer, analysis })
  }

  /* 文本题自评落分 */
  const selfGrade = (correct) => {
    if (!selfCheck) return
    const q = session.questions.find((x) => x.id === selfCheck.qid)
    if (!q) return
    applyGrade(q, correct, selfCheck.myAns, selfCheck.correctAnswer, selfCheck.analysis)
    setSelfCheck(null)
  }

  const go = useCallback((n) => {
    if (!session) return
    if (n < 0 || n >= session.questions.length) return
    setIdx(n); setSelfCheck(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [session])

  /* “AI 生成解析”：复用项目现有 AI 讲题路由 POST /api/ai/tutoring/explain
     （angle=solution）。该路由真实存在且已在用，生成的解析**只在前端展示、不落库**，
     因此显式标注「AI 生成 · 未入库」，不做“已写回题库”的假承诺。 */
  const generateAnalysis = useCallback(async (q) => {
    if (!q?.id) return
    const qid = q.id
    setAiAnalyses((m) => ({ ...m, [qid]: { loading: true, content: '', provider: '' } }))
    try {
      const r = await request('/ai/tutoring/explain', {
        method: 'POST',
        body: { question_id: Number(qid), angle: 'solution',
                source_kind: tutorMode === 'auto' ? undefined : tutorMode },
      })
      setAiAnalyses((m) => ({ ...m, [qid]: { loading: false, content: r?.content || '', provider: r?.provider || 'AI', mode: r?.mode } }))
    } catch (e) {
      setAiAnalyses((m) => ({ ...m, [qid]: { loading: false, content: '', provider: '', error: e?.message || 'AI 生成解析失败' } }))
    }
  }, [tutorMode])

  /* 键盘快捷键：A–F 选择 · Enter 提交/下一题 · ← → 切换 */
  useEffect(() => {
    const onKey = (e) => {
      if (!session) return
      const t = e.target
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      const q = session.questions[idx]
      if (!q) return
      if (isChoiceQ(q) && !records[q.id]) {
        const k = e.key.toUpperCase()
        const i = LETTERS.indexOf(k)
        if (i >= 0 && i < q.options.length) { toggleDraft(q.id, i); return }
      }
      if (e.key === 'Enter') {
        // 残缺选择题（无选项不可作答）按 Enter 直接跳下一题
        if (isChoiceWithoutOptions(q)) {
          if (idx + 1 < session.questions.length) go(idx + 1)
          else onFinish()
        } else if (!records[q.id] && !selfCheck) doSubmit()
        else if (idx + 1 < session.questions.length) go(idx + 1)
        else onFinish()
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
  const memorize = session.mode === 'memorize'
  const revealed = memorize || !!rec
  const draft = drafts[q.id]
  const answeredCount = Object.keys(records).length
  // total=0（这道题集没载到题）时进度必须是 0，不能让 NaN 流进 style.width
  const pct = total > 0 ? Math.round(((memorize ? idx + 1 : answeredCount) / total) * 100) : 0
  const favOn = !!favs[q.id]

  return (
    <div className="container">
      <div className="qprac-layout">
        <article className="qprac-article">
          <div className="qprac-meta">
            <button className="btn mini ghost" onClick={onGoHome}>‹ 返回题库</button>
            <span>{session.title}</span>
            {/* 知识点级筛选标识：明确告知用户当前按知识点精确出题 */}
            {kpFilter && <span className="chip kp" title={`知识点 ID ${kpFilter.id}`}>收藏 知识点 · {kpFilter.name}</span>}
            <span className="chip">{memorize ? '背题模式' : '练习模式'}</span>
            <span className="chip">{TYPE_LABELS[q.question_type] || q.question_type || '题目'}</span>
            {q.subject && <span className="chip">{q.subject}</span>}
            {q.chapter && <span className="chip">{q.chapter}</span>}
            {session.noAnswer && (
              <span className="chip" style={{ background: 'var(--warn-soft)', color: 'var(--warn-ink)', border: '1px solid var(--warn-border)' }}>
                浏览模式 · 暂不可判分
              </span>
            )}
            <button className={`qstar ${favOn ? 'on' : ''}`} onClick={() => onToggleFav(q)}>
              {favOn ? '已收藏' : '收藏'}
            </button>
          </div>
          {session.noAnswer && (
            <div className="qnote" style={{ marginTop: 'var(--space-2)' }}>
              当前为浏览模式：该科目/章节题库尚未回填标准答案，题目仅用于浏览与自检，不会判分、也不会进入错题本。可在「题库管理」为题目补全答案后恢复正常练习。
            </div>
          )}

          {/* 依据明示（M0）：本次练习按什么条件出题 + 可作答/总量口径，一眼可见 */}
          {basis && (
            <div className="qnote" style={{ marginTop: 'var(--space-2)' }}>
              当前依据：
              <strong>{basis.sourceKindLabel}</strong>
              {basis.subject ? ` · 科目 ${basis.subject}` : ''}
              {basis.chapter ? ` · 章节 ${basis.chapter}` : ''}
              {basis.kpName ? ` · 知识点 ${basis.kpName}` : ''}
              {' · '}可作答 {basis.answerableCount}{basis.totalCount ? ` / 共 ${basis.totalCount}` : ''} 题
              {basis.dropped > 0 ? ` · 已隔离 ${basis.dropped} 道科目不符题` : ''}
              {basis.noAnswer ? ' · 已回退浏览模式（不判分）' : ''}
            </div>
          )}

          {/* 单题可用性标记：仅记忆参考 / 不可作答（不渲染空白选项按钮） */}
          {questionMark(q) && (
            <div className="qnote" style={{ marginTop: 'var(--space-2)', color: 'var(--warn-ink)' }}>
              本题标记：<strong>{questionMark(q).label}</strong> —— {questionMark(q).desc}
            </div>
          )}

          <div className="qprac-body">
            <div className="qprac-progress">
              <span className="progress thin"><i style={{ width: `${pct}%` }} /></span>
              <span className="qprac-progress-num">{memorize ? `${idx + 1}` : `${answeredCount}`}/{total}</span>
            </div>

            <p className="qprac-stem">
              <span className="no">{idx + 1}.</span><MathText text={q.content} />
            </p>

            {/* 题目配图：OCR/人工录入产出的 figure_crop 或原页图 */}
            {Array.isArray(q.images) && q.images.length > 0 && (
              <div className="qfig-list">
                {q.images.map((img, i) => (
                  <img
                    key={`${img.url}-${i}`}
                    src={mediaSrc(img)}
                    alt={`题目配图 ${i + 1}`}
                    loading="lazy"
                  />
                ))}
              </div>
            )}

            {/* 依赖原书插图的题目给出提示，避免用户对着「见下图」困惑 */}
            {dependsOnFigure(q) && (
              <p className="qfig-note">本题依赖原书插图，答案见原书。</p>
            )}

            {/* 选择题：点选即判 */}
            {isChoiceQ(q) && (
              <div className="qopt-list">
                {q.options.map((o, i) => {
                  const isAns = isCorrectOption(i, rec?.correctAnswer ?? q.answer)
                  const picked = Array.isArray(draft) ? draft.includes(i) : draft === i
                  const wasBad = revealed && !isAns && (
                    Array.isArray(rec?.selected)
                      ? rec.selected.includes(letterOf(i))
                      : String(rec?.selected || '').toUpperCase().includes(letterOf(i))
                  )
                  let cls = 'qopt'
                  if (!revealed && picked) cls += ' sel'
                  if (revealed) {
                    if (isAns) cls += ' ok'
                    else if (wasBad) cls += ' bad'
                  }
                  return (
                    <button key={i} className={cls} disabled={revealed} onClick={() => toggleDraft(q.id, i)}>
                      <span className="qopt-letter">
                        {revealed && isAns ? '已完成' : revealed && wasBad ? '错误' : letterOf(i)}
                      </span>
                      <span className="qopt-body"><MathText text={stripOptLabel(o)} /></span>
                    </button>
                  )
                })}
              </div>
            )}

            {/* 残缺选择题：答案是字母但 options 为空/全空。只读展示，**不渲染空白选项按钮**，禁止作答 */}
            {!isChoiceQ(q) && isChoiceWithoutOptions(q) && (
              <div className="qopt-none">
                <span className="qopt-none-t">
                  {questionMark(q)?.label === '不可作答' ? '本题不可作答' : '本题无选项'}
                  {q.answer ? `，答案：${q.answer}` : '，且无参考答案'}
                </span>
                <span className="qopt-none-d">{questionMark(q)?.desc || '题库缺少该题选项内容，仅供记忆参考，不可作答。'}</span>
              </div>
            )}

            {/* 文本题：输入 + 对照自评 */}
            {isTextQuestion(q) && (
              <div className="qtext-area">
                <textarea className="qtext-input" aria-label="作答输入框" placeholder="在此输入你的作答（填空 / 简答 / 计算过程 / 作图描述）…"
                  value={textDraft[q.id] || ''} disabled={revealed}
                  onChange={(e) => setTextDraft((p) => ({ ...p, [q.id]: e.target.value }))} />
                {!revealed && !selfCheck && (
                  <div className="qtext-row">
                    <button className="btn primary" disabled={submitting} onClick={doSubmit}>对照答案</button>
                    <span className="qkey-hint">提交后展开参考答案与解析，再由你自评对错</span>
                  </div>
                )}
              </div>
            )}

            {/* 揭示区：判分结果 / 背题答案 / 文本题对照 */}
            {(revealed || selfCheck) && (
              <div className={`qreveal ${rec ? (rec.correct ? 'ok' : 'bad') : (selfCheck ? 'plain' : 'plain')}`}>
                <div className="qreveal-row">
                  <span>正确答案：<span className="ans">{(rec?.correctAnswer ?? q.answer) || '—'}</span></span>
                  {rec && <span>{rec.correct ? '· 回答正确 已完成' : `· 你的答案 ${rec.selected || ''}，回答错误 错误`}</span>}
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
                    <div className="qreveal-row" style={{ display: 'block' }}>
                      {raw ? (
                        <span>解析：<MathText text={raw} /></span>
                      ) : (
                        <div>
                          <span style={{ color: 'var(--muted)' }}>解析：暂无解析</span>
                          {!ai?.content && (
                            <>
                              <select className="select" style={{ width: 'auto', marginLeft: 'var(--space-3)', fontSize: 'var(--text-xs)' }}
                                aria-label="AI 生成解析的讲解模式"
                                value={tutorMode} onChange={(e) => setTutorMode(e.target.value)}
                                title="AI 生成解析的讲解模式：真题=评分视角，教材=理解视角">
                                <option value="auto">自动（按题目来源）</option>
                                <option value="exam">真题模式（评分视角）</option>
                                <option value="textbook">教材模式（理解视角）</option>
                              </select>
                              <button className="btn sm ghost" style={{ marginLeft: 'var(--space-2)' }}
                                disabled={ai?.loading} onClick={() => generateAnalysis(q)}>
                                {ai?.loading ? 'AI 生成中…' : 'AI 生成解析'}
                              </button>
                            </>
                          )}
                          {ai?.error && <span style={{ marginLeft: 'var(--space-3)', color: 'var(--danger)' }}>{ai.error}</span>}
                        </div>
                      )}
                      {ai?.content && (
                        <div style={{ marginTop: 'var(--space-2)', paddingTop: 'var(--space-2)', borderTop: '1px dashed var(--border)' }}>
                          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', marginBottom: 'var(--space-1)' }}>
                            AI 生成解析（来源 {ai.provider || 'AI'} · 未入库，仅供参考
                            {ai.mode ? ` · 按${ai.mode === 'exam' ? '真题模式（评分视角）' : ai.mode === 'textbook' ? '教材模式（理解视角）' : '通用模式'}讲解` : ''}）
                          </div>
                          <div style={{ whiteSpace: 'pre-wrap' }}>{ai.content}</div>
                        </div>
                      )}
                    </div>
                  )
                })()}

                {selfCheck && (
                  <div className="qtext-row">
                    <button className="btn primary" onClick={() => selfGrade(true)}>已完成 我答对了</button>
                    <button className="btn danger" onClick={() => selfGrade(false)}>错误 我答错了</button>
                  </div>
                )}
              </div>
            )}

            {/* 未作答提示：单选/判断点选即判；多选仍需提交 */}
            {!revealed && !selfCheck && isChoiceQ(q) && isMultiQ(q) && (
              <p className="qkey-hint">勾选所有正确选项后，点「提交答案」判分。</p>
            )}
          </div>

          <div className="qprac-foot">
            <button className="btn ghost" onClick={() => go(idx - 1)} disabled={idx === 0}>‹ 上一题</button>
            <span className="qkey-hint">快捷键：A–F 选择 · Enter 提交/下一题 · ← → 切换</span>
            <div className="qprac-foot-btns">
              <button className="btn ghost" onClick={() => navigate('/assistant')}>智能 问 AI</button>
              {!revealed && !selfCheck && isChoiceQ(q) && isMultiQ(q) && (
                <button className="btn primary" disabled={submitting} onClick={doSubmit}>提交答案</button>
              )}
              {/* 残缺选择题不可作答，允许直接跳到下一题 */}
              {isChoiceWithoutOptions(q) && (
                idx + 1 < total ? (
                  <button className="btn primary" onClick={() => go(idx + 1)}>下一题 ›</button>
                ) : (
                  <button className="btn primary" onClick={onFinish}>{memorize ? '完成背题' : '交卷并查看报告'}</button>
                )
              )}
              {(revealed || selfCheck) && idx + 1 < total && (
                <button className="btn primary" onClick={() => go(idx + 1)}>下一题 ›</button>
              )}
              {(revealed || selfCheck) && idx + 1 >= total && (
                <button className="btn primary" onClick={onFinish}>{memorize ? '完成背题' : '交卷并查看报告'}</button>
              )}
            </div>
          </div>
        </article>

        {/* 右侧答题卡 */}
        <aside className="qsheet">
          <div className="qsheet-t">答题卡</div>
          <div className="qsheet-grid">
            {session.questions.map((qq, i) => {
              const r = records[qq.id]
              const skipped = isChoiceWithoutOptions(qq)
              let cls = 'qsheet-cell'
              if (skipped) cls += ' skip'
              else if (r) cls += r.correct ? ' ok' : ' bad'
              else if (drafts[qq.id] != null || textDraft[qq.id]) cls += ' draft'
              if (i === idx) cls += ' cur'
              return (
                <button key={qq.id} className={cls} onClick={() => go(i)}
                  aria-label={`第 ${i + 1} 题${skipped ? '，无选项不可作答' : r ? (r.correct ? '，正确' : '，错误') : ''}`}>
                  {i + 1}
                </button>
              )
            })}
          </div>
          <ul className="qsheet-legend">
            <li><span className="qsheet-dot ok" />正确</li>
            <li><span className="qsheet-dot bad" />错误</li>
            <li><span className="qsheet-dot todo" />未做</li>
            <li><span className="qsheet-dot skip" />无选项</li>
          </ul>
          <button className="btn ghost qsheet-finish" onClick={onFinish}>
            {memorize ? '结束背题' : '交卷并查看报告'}
          </button>
        </aside>
      </div>
    </div>
  )
}
