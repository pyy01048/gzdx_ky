import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { analysisApi } from '../api/client'
import { SubTag, Segmented, Empty, toast } from '../components/UI'
import { useSubjectConfig, subjectLabel } from '../hooks/useSubjectConfig'

const PREFERS = [
  { value: 'auto', label: '自动' },
  { value: 'local', label: '本地模型' },
  { value: 'cloud', label: '云端 API' }
]

function renderLatexText(s) {
  if (!s) return ''
  return String(s)
}

export default function Analysis() {
  const { exam, support } = useSubjectConfig()
  const [subject, setSubject] = useState('')
  const [prefer, setPrefer] = useState('auto')
  const [question, setQuestion] = useState('')
  const [imagePath, setImagePath] = useState('')
  const [busy, setBusy] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [analysis, setAnalysis] = useState(null)
  const [lecturePath, setLecturePath] = useState('')
  const [lectures, setLectures] = useState([])
  const [loadLectures, setLoadLectures] = useState(false)
  const [lecturesError, setLecturesError] = useState('')
  const [error, setError] = useState('')

  const examOptions = useMemo(() => exam.map((s) => ({ value: s, label: subjectLabel(s) })), [exam])
  const allLabels = useMemo(() => [...exam, ...support].map(subjectLabel), [exam, support])

  /* 科目来自配置：首次到达、或当前选中项被移出配置时，落到第一个合法科目 */
  useEffect(() => {
    setSubject((prev) => (
      prev && [...exam, ...support].includes(prev) ? prev : (exam[0] || support[0] || '')
    ))
  }, [exam, support])

  const fetchLectures = useCallback(async () => {
    setLoadLectures(true)
    setLecturesError('')
    try {
      const r = await analysisApi.lectures({ limit: 50 })
      setLectures(Array.isArray(r) ? r : (r.items || r.lectures || []))
    } catch (e) {
      setLecturesError(e.message || '获取讲义列表失败')
    } finally {
      setLoadLectures(false)
    }
  }, [])

  useEffect(() => {
    fetchLectures()
  }, [fetchLectures])

  const doAnalyze = async () => {
    setError('')
    setLecturePath('')
    if (!question.trim() && !imagePath.trim()) {
      toast('请输入题目文本或图片路径')
      return
    }
    setAnalyzing(true)
    try {
      const body = { question: question.trim() || undefined, image_path: imagePath.trim() || undefined, subject, prefer }
      const r = await analysisApi.analyze(body)
      setAnalysis(r)
    } catch (e) {
      setError(e.message || '分析失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const doLecture = async () => {
    setError('')
    if (!analysis && !question.trim() && !imagePath.trim()) {
      toast('请先输入题目')
      return
    }
    setBusy(true)
    try {
      const body = {
        question: question.trim() || undefined,
        image_path: imagePath.trim() || undefined,
        subject,
        prefer,
        analysis: analysis || undefined
      }
      const r = await analysisApi.lecture(body)
      setLecturePath(r.path || '')
      toast('讲义已生成')
      fetchLectures()
    } catch (e) {
      setError(e.message || '讲义生成失败')
    } finally {
      setBusy(false)
    }
  }

  const doOcr = async () => {
    if (!imagePath.trim()) {
      toast('请填写图片路径')
      return
    }
    setBusy(true)
    setError('')
    try {
      const r = await analysisApi.ocr({ image_path: imagePath.trim(), prefer })
      setQuestion(r.text || question)
      toast(`OCR 完成（${r.engine || ''}）`)
    } catch (e) {
      setError(e.message || 'OCR 失败')
    } finally {
      setBusy(false)
    }
  }

  const steps = (analysis && analysis.steps) || []

  return (
    <div className="container stack">
      <div className="page-head spread">
        <div>
          <h1 className="page-title">题目分析引擎</h1>
          <p className="page-sub">题目输入 → 结构化分析（已知条件 / 思路 / 分步推导 / 结论验证）→ HTML 可视化讲义（KaTeX 公式渲染）</p>
        </div>
        <div className="page-actions row">
          <Segmented value={subject} onChange={setSubject} options={examOptions} />
          {support.length > 0 && (
            <select
              className="select"
              style={{ width: 132 }}
              aria-label="支撑科目"
              value={support.includes(subject) ? subject : ''}
              onChange={(e) => e.target.value && setSubject(e.target.value)}
            >
              <option value="">支撑科目…</option>
              {support.map((s) => <option key={s} value={s}>{subjectLabel(s)}</option>)}
            </select>
          )}
          <Segmented value={prefer} onChange={setPrefer} options={PREFERS} />
        </div>
      </div>

      <div className="card">
        <div className="card-title">题目输入</div>
        <div className="stack">
          <textarea
            className="input"
            rows={4}
            placeholder={`粘贴题目文本（支持 ${allLabels.join(' / ')}）`}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <div className="row spread">
            <input
              className="input"
              style={{ flex: 1 }}
              placeholder="或填写本地图片路径，先 OCR 识别题目（如 D:\试卷\题1.png）"
              value={imagePath}
              onChange={(e) => setImagePath(e.target.value)}
            />
            <button className="btn ghost" disabled={busy} onClick={doOcr}>OCR 识别</button>
          </div>
          <div className="row">
            <button className="btn primary" disabled={analyzing || busy} onClick={doAnalyze}>
              {analyzing ? '分析中…' : '开始分析'}
            </button>
            <button className="btn" disabled={busy || analyzing} onClick={doLecture}>
              {busy ? '生成中…' : '生成 HTML 讲义'}
            </button>
            {lecturePath && (
              <a className="btn ghost" href={`file:///${lecturePath.replace(/\\/g, '/')}`} target="_blank" rel="noreferrer">
                打开讲义
              </a>
            )}
          </div>
          {lecturePath && <div className="card-sub">讲义已保存：{lecturePath}</div>}
          {error && <div className="badge danger">{error}</div>}
        </div>
      </div>

      {analysis && (
        <div className="card">
          <div className="card-title spread">
            <span>结构化分析</span>
            <span className="card-sub">
              {analysis.subject || ''} · {analysis.engine || ''} · {analysis.model || ''} · {(analysis.latency_ms || 0).toFixed(0)}ms
            </span>
          </div>
          <div className="stack">
            <div className="card-title">已知条件</div>
            {(analysis.known_conditions || []).length > 0 ? (
              <ul className="list">
                {(analysis.known_conditions || []).map((c, i) => (
                  <li key={i} className="list-row">{renderLatexText(c)}</li>
                ))}
              </ul>
            ) : <div className="card-sub">无</div>}

            {analysis.solution_approach && (
              <>
                <div className="card-title">解题思路</div>
                <div className="badge accent">{renderLatexText(analysis.solution_approach)}</div>
              </>
            )}

            <div className="card-title">分步推导</div>
            {steps.length > 0 ? steps.map((s, i) => (
              <div key={i} className="card-sub">
                <b>{i + 1}. {s.title || '步骤'}</b>
                <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{renderLatexText(s.content)}</div>
                {s.conclusion && <div style={{ marginTop: 4, color: 'var(--ok)' }}>→ {renderLatexText(s.conclusion)}</div>}
              </div>
            )) : <div className="card-sub">无分步推导</div>}

            {analysis.final_answer && (
              <>
                <div className="card-title">最终答案</div>
                <div className="badge success">{renderLatexText(analysis.final_answer)}</div>
              </>
            )}
            {analysis.verification && (
              <>
                <div className="card-title">结论验证</div>
                <div className="badge neutral">{renderLatexText(analysis.verification)}</div>
              </>
            )}
            {(analysis.knowledge_points || []).length > 0 && (
              <>
                <div className="card-title">涉及知识点</div>
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  {(analysis.knowledge_points || []).map((kp, i) => (
                    <SubTag key={i} text={kp} />
                  ))}
                </div>
              </>
            )}
            {(analysis.common_mistakes || []).length > 0 && (
              <>
                <div className="card-title">常见错误</div>
                <ul className="list">
                  {(analysis.common_mistakes || []).map((m, i) => (
                    <li key={i} className="list-row badge danger">{renderLatexText(m)}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-title spread">
          <span>历史讲义</span>
          <button className="btn sm ghost" onClick={fetchLectures} disabled={loadLectures}>刷新</button>
        </div>
        {loadLectures ? (
          <div className="loading-inline">正在加载讲义列表…</div>
        ) : lecturesError ? (
          <div className="empty-state">
            <div className="empty-state-title">讲义列表加载失败</div>
            <div className="empty-state-desc">{lecturesError}</div>
            <div className="empty-state-action">
              <button className="btn ghost" onClick={fetchLectures}>重试</button>
            </div>
          </div>
        ) : lectures.length === 0 ? (
          <Empty title="暂无讲义，先生成一份试试" />
        ) : (
          <div className="list">
            {lectures.map((l) => (
              <div key={l.id || l.path} className="list-row spread">
                <div>
                  <div className="lr-title">{l.title || l.filename || l.path}</div>
                  <div className="lr-main card-sub">{l.subject || ''} · {l.created_at || ''}</div>
                </div>
                <div className="row">
                  <a className="btn sm ghost" href={`file:///${(l.path || '').replace(/\\/g, '/')}`} target="_blank" rel="noreferrer">打开</a>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
