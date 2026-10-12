import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { quizApi, taxonomyApi } from '../api/client'
import { toast, Empty } from '../components/UI'
import {
  Target, Map as MapIcon, Book, Play, RefreshCw, AlertCircle,
} from '../components/Icon'
import './ExamFrequency.css'

/* =====================================================================
 * 考频分析（对标 codebrick.tech/practice/exam-strategy 的功能类型）
 *   三档维度：知识点 / 章节 / 套卷，均由后端 GET /api/quiz/frequency 提供。
 *   数据来源（诚实口径）：
 *     - dimension=kp     ：按知识点聚合，exam_frequency 降序 + 关联题数（去重、排除碎片题）
 *     - dimension=chapter：按章节聚合，题数 + 涉及知识点数
 *     - dimension=paper  ：按套卷聚合，题数 + 涉及知识点数
 *   ⚠️ 不提供"按年份"维度：quiz_questions.year 覆盖率仅 7.9%，按年聚合会失真
 *      （后端 /frequency 亦刻意不按年份聚合）。
 *   零新依赖：条形/色标全部用现有 DOM + CSS 实现，颜色走全站 CSS 令牌。
 * ===================================================================== */

/* 考频分档（与后端 exam_frequency 0–5 对齐）：
   5 高频 / 4-3 中频 / 2-1 低频 / 0 冷门。色标复用全站语义色（red/gold/ok/ink-3）。 */
function freqTone(f) {
  const v = Number(f) || 0
  if (v >= 5) return { cls: 'high', label: '高频' }
  if (v >= 3) return { cls: 'mid', label: '中频' }
  if (v >= 1) return { cls: 'low', label: '低频' }
  return { cls: 'cold', label: '冷门' }
}

/* 兼容 /taxonomy/subjects 的多种返回（与 Panorama/KbMap 同一容错策略）。 */
function normalizeSubjects(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.subjects)) return data.subjects
  if (data && Array.isArray(data.items)) return data.items
  return []
}

/* 从 /taxonomy/tree 的三级结构里建「(科目,知识点名) → kp_id」索引，
   供知识点档的"去练习"跳 /quiz?kp_id=X。章节名一并入键，避免跨章重名歧义。 */
function buildKpIdIndex(tree) {
  const idx = new Map()
  for (const s of tree || []) {
    for (const ch of s.chapters || []) {
      for (const kp of ch.knowledge_points || []) {
        if (kp?.id == null) continue
        idx.set(`${s.subject}|${ch.title}|${kp.name}`, kp.id)
        // 兜底键：不带章节（同名取首个），保证仍能命中
        const loose = `${s.subject}|${kp.name}`
        if (!idx.has(loose)) idx.set(loose, kp.id)
      }
    }
  }
  return idx
}

const DIM_TABS = [
  { value: 'kp', label: '知识点' },
  { value: 'chapter', label: '章节' },
  { value: 'paper', label: '套卷' },
]

export default function ExamFrequency() {
  const navigate = useNavigate()

  const [subjects, setSubjects] = useState([])         // 科目列表
  const [activeSubject, setActiveSubject] = useState('')   // '' = 全部
  const [dim, setDim] = useState('kp')                 // kp | chapter | paper
  const [items, setItems] = useState([])               // 当前维度数据
  const [status, setStatus] = useState('loading')      // loading | ok | error
  const [errMsg, setErrMsg] = useState('')
  const [kpIdx, setKpIdx] = useState(() => new Map())  // (subject|chapter|name)→kp_id

  /* 首次加载：科目列表 + 全量结构树（用于知识点→id 反查）并行拉取。 */
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [sj, t] = await Promise.all([
          taxonomyApi.subjects().catch(() => null),
          taxonomyApi.tree().catch(() => null),
        ])
        if (!alive) return
        setSubjects(normalizeSubjects(sj))
        setKpIdx(buildKpIdIndex(t?.tree || []))
      } catch {
        /* 科目/树加载失败不致命：仍能展示默认（全部）考频 */
      }
    })()
    return () => { alive = false }
  }, [])

  /* 拉取当前 科目×维度 的考频数据。 */
  const loadFreq = useCallback(async (subject, dimension) => {
    setStatus('loading')
    setErrMsg('')
    try {
      const d = await quizApi.frequency({
        dimension,
        subject: subject || undefined,
        limit: 100,
      })
      setItems(Array.isArray(d?.items) ? d.items : [])
      setStatus('ok')
    } catch (e) {
      setErrMsg(e?.message || '加载失败')
      setItems([])
      setStatus('error')
      toast('考频加载失败：' + (e?.message || ''))
    }
  }, [])

  useEffect(() => { loadFreq(activeSubject, dim) }, [activeSubject, dim, loadFreq])

  /* 章节/套卷档的条形宽度：以当前列表最大值归一（最大值占满条）。 */
  const maxCount = useMemo(
    () => items.reduce((m, it) => Math.max(m, Number(it.question_count) || 0), 0),
    [items],
  )

  /* 知识点档：把条目附上 kp_id（用于"去练习"），解析不到 id 时禁用按钮并提示。 */
  const kpRows = useMemo(() => {
    if (dim !== 'kp') return []
    return items.map((it) => {
      const key1 = `${it.subject}|${it.chapter}|${it.name}`
      const key2 = `${it.subject}|${it.name}`
      const id = kpIdx.get(key1) ?? kpIdx.get(key2) ?? null
      return { ...it, kp_id: id, tone: freqTone(it.exam_frequency) }
    })
  }, [dim, items, kpIdx])

  const goPractice = (row) => {
    if (row.kp_id == null) {
      toast('该知识点暂无可跳转的 ID（可能尚未入库），请到「知识点全景」刷题')
      return
    }
    const params = new URLSearchParams()
    if (row.subject) params.set('subject', row.subject)
    if (row.chapter) params.set('chapter', row.chapter)
    params.set('kp_id', row.kp_id)
    params.set('kp_name', row.name)
    navigate(`/quiz?${params.toString()}`)
  }

  /* 科目 chips：优先 /taxonomy/subjects，为空时用跨维数据里出现过的科目兜底。 */
  const chipSubjects = useMemo(() => {
    if (subjects.length) return subjects
    const seen = new Map()
    items.forEach((it) => { if (it.subject && !seen.has(it.subject)) seen.set(it.subject, { subject: it.subject }) })
    return [...seen.values()]
  }, [subjects, items])

  return (
    <div className="page">
      {/* ---------- 顶部：标题 + 口径说明 ---------- */}
      <div className="ef-head">
        <div className="ef-head-main">
          <h1 className="ef-title"><Target size={20} /> 考频分析</h1>
          <p className="ef-sub">
            按 <b>知识点 / 章节 / 套卷</b> 三个维度统计真题出现频次，定位高频考点，优先攻克。
          </p>
        </div>
        <button className="btn mini ghost" onClick={() => loadFreq(activeSubject, dim)} title="重新拉取">
          <RefreshCw size={14} /> 刷新
        </button>
      </div>

      {/* ---------- 科目选择 chips（复用 kbmap.css 的 kb-* 类） ---------- */}
      <div className="kb-subjectbar">
        <MapIcon size={15} className="kb-subjectbar-icon" />
        <div className="kb-chips">
          <button className={`kb-chip ${!activeSubject ? 'active' : ''}`} onClick={() => setActiveSubject('')}>
            全部
          </button>
          {chipSubjects.map((s) => (
            <button
              key={s.subject}
              className={`kb-chip ${activeSubject === s.subject ? 'active' : ''}`}
              onClick={() => setActiveSubject(s.subject)}
            >
              {s.subject}
            </button>
          ))}
        </div>
      </div>

      {/* ---------- 维度切换（复用全站 segmented 组件） ---------- */}
      <div className="ef-toolbar">
        <div className="seg" role="tablist" aria-label="考频维度">
          {DIM_TABS.map((t) => (
            <button
              key={t.value}
              className={`seg-btn ${dim === t.value ? 'active' : ''}`}
              onClick={() => setDim(t.value)}
              role="tab"
              aria-selected={dim === t.value}
            >
              {t.label}
            </button>
          ))}
        </div>
        <span className="ef-count">
          {status === 'ok' ? `共 ${items.length} 项` : ''}
        </span>
      </div>

      {/* ---------- 主体：三态 ---------- */}
      {status === 'loading' ? (
        <div className="ef-skeleton card">
          {Array.from({ length: 6 }).map((_, i) => <span key={i} className="ef-sk-row" />)}
        </div>
      ) : status === 'error' ? (
        <Empty
          icon={<AlertCircle size={44} />}
          title="考频数据加载失败"
          desc={errMsg || '请检查后端 /api/quiz/frequency 是否可用。'}
          action={<button className="btn primary" onClick={() => loadFreq(activeSubject, dim)}>
            <RefreshCw size={14} /> 重试
          </button>}
        />
      ) : items.length === 0 ? (
        <Empty
          icon={<Book size={44} />}
          title={activeSubject ? `「${activeSubject}」暂无考频数据` : '暂无考频数据'}
          desc="该筛选下尚无带知识点/章节/套卷标注的题目，可切换科目或维度查看。"
        />
      ) : dim === 'kp' ? (
        /* ---------- 知识点档：考频排行 ---------- */
        <div className="ef-kp-list card">
          <div className="ef-kp-head">
            <span className="ef-col-rank">#</span>
            <span className="ef-col-name">知识点</span>
            <span className="ef-col-tone">考频</span>
            <span className="ef-col-q">关联题数</span>
            <span className="ef-col-act" />
          </div>
          {kpRows.map((row, i) => (
            <div className="ef-kp-row" key={`${row.name}-${row.chapter}-${i}`}>
              <span className="ef-col-rank">{i + 1}</span>
              <span className="ef-col-name">
                <b className="ef-kp-name">{row.name}</b>
                <small className="ef-kp-chap">{row.chapter || row.subject || ''}</small>
              </span>
              <span className="ef-col-tone">
                <i className={`ef-dot ${row.tone.cls}`} />
                <span className={`ef-tone-text ${row.tone.cls}`}>{row.tone.label}</span>
                <small className="ef-freq-num">· 考频 {row.exam_frequency ?? 0}</small>
              </span>
              <span className="ef-col-q">
                {row.question_count > 0
                  ? <>{row.question_count}<small> 题</small></>
                  : <span className="ef-q-none">—</span>}
              </span>
              <span className="ef-col-act">
                <button
                  className="btn mini primary"
                  onClick={() => goPractice(row)}
                  disabled={row.kp_id == null}
                  title={row.kp_id == null ? '未解析到知识点 ID' : `去练习（kp_id=${row.kp_id}）`}
                >
                  <Play size={12} /> 去练习
                </button>
              </span>
            </div>
          ))}
        </div>
      ) : (
        /* ---------- 章节 / 套卷档：横向条形 ---------- */
        <div className="ef-bar-list card">
          {items.map((it, i) => {
            const cnt = Number(it.question_count) || 0
            const pct = maxCount ? Math.round((cnt / maxCount) * 100) : 0
            return (
              <div className="ef-bar-row" key={`${it.name}-${i}`}>
                <span className="ef-bar-rank">{i + 1}</span>
                <span className="ef-bar-label" title={it.name}>{it.name}</span>
                <span className="ef-bar-track">
                  <i className="ef-bar-fill" style={{ width: `${pct}%` }} />
                </span>
                <span className="ef-bar-val">
                  {cnt}<small> 题</small>
                  <span className="ef-bar-kp">· {it.kp_count ?? 0} 知识点</span>
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* ---------- 页脚：诚实口径标注 ---------- */}
      <p className="ef-foot">
        考频为真题出现频次分档（维度：知识点 / 章节 / 套卷）；题数已排除 OCR 碎片题。
        分档口径：考频 5 高频 / 4–3 中频 / 2–1 低频 / 0 冷门。
        ⚠️ 因真题年份覆盖率仅约 8%，本页<b>不提供"按年份"维度</b>（按年聚合会失真）。
      </p>
    </div>
  )
}
