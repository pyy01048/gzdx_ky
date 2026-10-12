import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { taxonomyApi, quizApi } from '../api/client'
import { toast, Empty } from '../components/UI'
import {
  RefreshCw, ChevronRight, ChevronDown, Book, Brain,
  AlertCircle, Map as MapIcon, Play, Target,
} from '../components/Icon'
import './Panorama.css'

/* =====================================================================
 * 知识点全景刷题（对标 codebrick.tech/practice/panorama 的信息架构）
 *   一屏纵览「科目 → 章节 → 知识点」，点知识点直接刷题。
 *   信息架构抄参考件（左侧结构树 + 中部详情 + 右侧操作/概览），
 *   视觉沿用本平台 V8 学术蓝令牌（复用 kbmap.css 的色标与 KbMap 的
 *   masteryTone 口径：<40 薄弱 / 40-69 一般 / ≥70 良好）。
 *   零新依赖：树/热力/色标全部用现有 DOM + CSS 实现。
 * ===================================================================== */

/* 题型码 → 中文标签（与后端 ALLOWED_QUESTION_TYPES 对齐，口径同 KbMap/Quiz） */
const TYPE_LABEL = {
  single: '单选',
  judge: '判断',
  fill: '填空',
  essay: '简答',
  calc: '计算',
  draw: '作图',
  multiple: '多选',
}
function typeLabel(t) {
  return TYPE_LABEL[t] || t || ''
}

/* 掌握度档位：与后端口径一致（<40 薄弱 / 40-69 一般 / ≥70 良好）。
   与 KbMap.jsx 的 masteryTone 保持同一口径，保证全站染色一致。 */
function masteryTone(m) {
  const v = Number(m) || 0
  if (v >= 70) return { cls: 'ok', label: '良好' }
  if (v >= 40) return { cls: 'mid', label: '一般' }
  return { cls: 'low', label: '薄弱' }
}

/* 兼容 /taxonomy/subjects 的多种返回：数组 / {subjects:[...]} / {items:[...]} */
function normalizeSubjects(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.subjects)) return data.subjects
  if (data && Array.isArray(data.items)) return data.items
  return []
}

/* 把知识点名归一为稳定的展示/跳转键（后端 kp_id 未就绪时的降级参数） */
function kpKeyOf(subject, chapter, kp) {
  return `${subject}|${chapter}|${kp?.id ?? kp?.name ?? ''}`
}

export default function Panorama() {
  const navigate = useNavigate()

  const [subjects, setSubjects] = useState([])         // 科目列表（taxonomyApi.subjects）
  const [tree, setTree] = useState([])                 // 当前科目三级结构（taxonomyApi.tree）
  const [coverage, setCoverage] = useState(null)       // 覆盖率概览（taxonomyApi.coverage）
  const [status, setStatus] = useState('loading')     // loading | ok | error
  const [treeLoading, setTreeLoading] = useState(false)
  const [errMsg, setErrMsg] = useState('')

  const [activeSubject, setActiveSubject] = useState('')  // 当前选中的科目（'' = 全部）
  const [openChapters, setOpenChapters] = useState({})    // 章节展开态 { 'subject|chapter': true }
  const [selected, setSelected] = useState(null)          // 当前选中知识点 { subject, chapter, kp }
  const [qCount, setQCount] = useState(null)              // 关联题量（真实，来自 /quiz/questions?kp_id=）
  const [qLoading, setQLoading] = useState(false)

  /* 首次加载：科目列表 + 全量结构树 + 覆盖率 并行拉取 */
  const loadAll = useCallback(async () => {
    setStatus('loading')
    setErrMsg('')
    try {
      const [sj, t, c] = await Promise.all([
        taxonomyApi.subjects().catch(() => null),
        taxonomyApi.tree(),
        taxonomyApi.coverage().catch(() => null),
      ])
      const tNodes = t?.tree || []
      setSubjects(normalizeSubjects(sj))
      setTree(tNodes)
      setCoverage(c)
      setActiveSubject('')
      setSelected(null)
      // 默认展开第一个有知识点的科目的首个有知识点的章节，并选中其第一个知识点
      const first = tNodes.find((s) => s.knowledge_point_count > 0)
      const firstCh = first?.chapters?.find((ch) => ch.knowledge_point_count > 0)
      if (first && firstCh) {
        setOpenChapters({ [`${first.subject}|${firstCh.title}`]: true })
        const kp = (firstCh.knowledge_points || [])[0]
        if (kp) setSelected({ subject: first.subject, chapter: firstCh.title, kp })
      }
      setStatus('ok')
    } catch (e) {
      setErrMsg(e?.message || '未知错误')
      setStatus('error')
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  /* 切换科目：仅重拉该科结构树；'' 表示全部（取全量树�� */
  const selectSubject = useCallback(async (name) => {
    if (name === activeSubject) return
    setActiveSubject(name)
    setTreeLoading(true)
    setOpenChapters({})
    setSelected(null)
    try {
      const t = await taxonomyApi.tree(name || undefined)
      const tNodes = t?.tree || []
      setTree(tNodes)
      const first = tNodes.find((s) => s.knowledge_point_count > 0)
      const firstCh = first?.chapters?.find((ch) => ch.knowledge_point_count > 0)
      if (first && firstCh) {
        setOpenChapters({ [`${first.subject}|${firstCh.title}`]: true })
        const kp = (firstCh.knowledge_points || [])[0]
        if (kp) setSelected({ subject: first.subject, chapter: firstCh.title, kp })
      }
    } catch (e) {
      toast('加载科目结构失败：' + (e?.message || ''))
    } finally {
      setTreeLoading(false)
    }
  }, [activeSubject])

  const toggleChapter = (key) =>
    setOpenChapters((s) => ({ ...s, [key]: !s[key] }))

  /* 点击知识点：选中并展开其所属章节（章节已由树渲染保证展开态） */
  const pickKp = (subject, chapter, kp) => {
    setSelected({ subject, chapter, kp })
  }

  /* 科目选择 chips：优先用 /taxonomy/subjects；为空时回退结构树里已有科目的科目，
     避免有知识点却误报「暂未配置科目」（与 KbMap 同一容错策略）。 */
  const chipSubjects = useMemo(() => {
    if (subjects.length > 0) return subjects
    return tree
      .filter((s) => s.knowledge_point_count > 0)
      .map((s) => ({ subject: s.subject, question_count: s.knowledge_point_count }))
  }, [subjects, tree])

  /* 顶部覆盖概览：总知识点数 / 有题的知识点数 / 平均掌握度（按当前科目口径）。
     有题的知识点：优先用 kp.question_count，其次用 question_types 非空推断。 */
  const overview = useMemo(() => {
    let totalKp = 0
    let withQ = 0
    let sumMastery = 0
    tree.forEach((s) => {
      (s.chapters || []).forEach((ch) => {
        (ch.knowledge_points || []).forEach((kp) => {
          totalKp += 1
          const hasQ = Number(kp.question_count) > 0 || (kp.question_types || []).length > 0
          if (hasQ) withQ += 1
          sumMastery += Number(kp.mastery) || 0
        })
      })
    })
    const avg = totalKp ? Math.round(sumMastery / totalKp) : 0
    return { totalKp, withQ, avg }
  }, [tree])

  /* 关联题量：真实来源 /api/quiz/questions?kp_id=（响应体 total）。
     /api/taxonomy/tree 返回的知识点不含 question_count 字段，故不能沿用
     kp.question_count（会恒为 0）；改为按 kp_id 实时查询，与「开始练习」同口径。 */
  useEffect(() => {
    const kpId = selected?.kp?.id
    if (kpId == null) { setQCount(null); setQLoading(false); return }
    let alive = true
    setQLoading(true)
    setQCount(null)
    quizApi.questions({ kp_id: kpId, page_size: 1 })
      .then((d) => { if (alive && d && typeof d.total === 'number') setQCount(d.total) })
      .catch(() => { if (alive) setQCount(null) })   // 失败显示 '—'，不伪造 0
      .finally(() => { if (alive) setQLoading(false) })
    return () => { alive = false }
  }, [selected?.kp?.id])

  /* 开始练习：跳 /quiz。
     优先带 kp_id 精确筛选（后端 /api/quiz/questions 已支持 kp_id）；
     同时带 kp_name 供 Quiz 页展示"当前筛选：知识点 XXX"标识。
     并保留 subject + chapter 作为兜底展示信息（kp_id 命中 0 题时 Quiz 会给出空态提示）。 */
  const startPractice = (subject, chapter, kp) => {
    const params = new URLSearchParams()
    if (subject) params.set('subject', subject)
    if (chapter) params.set('chapter', chapter)
    if (kp?.id != null) params.set('kp_id', kp.id)
    if (kp?.name) params.set('kp_name', kp.name)
    navigate(`/quiz?${params.toString()}`)
  }

  /* ---------------- 三态：加载中 ---------------- */
  if (status === 'loading') {
    return (
      <div className="page">
        <div className="card">
          <div className="loading-inline">知识点全景加载中…</div>
        </div>
      </div>
    )
  }

  /* ---------------- 三态：失败（就地提示 + 重试，不白屏） ---------------- */
  if (status === 'error') {
    return (
      <div className="page">
        <div className="card kb-error-card">
          <div className="kb-error-icon"><AlertCircle size={28} /></div>
          <div className="kb-error-body">
            <div className="kb-error-title">知识点全景加载失败</div>
            <div className="kb-error-desc">{errMsg || '请确认后端服务已启动后重试。'}</div>
            <button className="btn ghost" onClick={loadAll}>
              <RefreshCw size={14} /> 重新加载
            </button>
          </div>
        </div>
      </div>
    )
  }

  const hasAnyKp = tree.some((s) => s.knowledge_point_count > 0)

  return (
    <div className="page">
      {/* 页头 */}
      <div className="page-head">
        <div>
          <h1 className="page-title">知识点全景</h1>
          <div className="page-sub">科目 → 章节 → 知识点 一屏纵览 · 点知识点直接刷题 · 掌握度热力着色</div>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={loadAll}>
            <RefreshCw size={15} /> 刷新
          </button>
        </div>
      </div>

      {/* 覆盖概览（按当前科目口径） */}
      <div className="pn-overview">
        <div className="pn-ov-stat">
          <span className="pn-ov-num">{overview.totalKp}</span>
          <span className="pn-ov-label">知识点总数</span>
        </div>
        <div className="pn-ov-stat">
          <span className="pn-ov-num ok">{overview.withQ}</span>
          <span className="pn-ov-label">有题知识点</span>
        </div>
        <div className="pn-ov-stat">
          <span className={`pn-ov-num tone-${masteryTone(overview.avg).cls}`}>{overview.avg}<small>%</small></span>
          <span className="pn-ov-label">平均掌握度</span>
        </div>
        <div className="pn-legend">
          <span className="kb-legend-item"><i className="dot low" />薄弱 &lt;40</span>
          <span className="kb-legend-item"><i className="dot mid" />一般 40–69</span>
          <span className="kb-legend-item"><i className="dot ok" />良好 ≥70</span>
        </div>
      </div>

      {/* 科目选择 */}
      <div className="kb-subjectbar">
        <MapIcon size={15} className="kb-subjectbar-icon" />
        <div className="kb-chips">
          <button
            className={`kb-chip ${!activeSubject ? 'active' : ''}`}
            onClick={() => selectSubject('')}
          >
            全部
          </button>
          {chipSubjects.map((s) => (
            <button
              key={s.subject}
              className={`kb-chip ${activeSubject === s.subject ? 'active' : ''}`}
              onClick={() => selectSubject(s.subject)}
            >
              {s.subject}
              {typeof s.question_count === 'number' && <small>{s.question_count}</small>}
            </button>
          ))}
        </div>
      </div>

      {/* 三态：无科目 或 无知识点 */}
      {chipSubjects.length === 0 && !treeLoading ? (
        <Empty
          icon={<Book size={44} />}
          title="暂未配置科目"
          desc="请先在「科目管理」中添加考试科目与大纲章节，知识点全景会自动生成三级结构。"
        />
      ) : !hasAnyKp && !treeLoading ? (
        <Empty
          icon={<Brain size={44} />}
          title={activeSubject ? `「${activeSubject}」暂无知识点` : '暂无知识结构数据'}
          desc="上传资料并解析后，这里会按章节展开知识点与掌握度。"
        />
      ) : (
        <div className="pn-layout">
          {/* 左：章节 → 知识点 树 */}
          <div className="pn-tree-col">
            {treeLoading ? (
              <div className="card"><div className="loading-inline">结构加载中…</div></div>
            ) : (
              tree.map((subject) => (
                <div className="card pn-subject-card" key={subject.subject}>
                  <div className="kb-subject-head">
                    <div className="kb-subject-titles">
                      <div className="kb-subject-name">
                        {subject.subject}
                        {!subject.is_core && <span className="kb-tag-ext">拓展</span>}
                      </div>
                      <div className="kb-subject-meta">
                        知识点 {subject.knowledge_point_count} · {subject.outline_chapter_count || 0} 章节
                      </div>
                    </div>
                    <div className="kb-subject-mastery">
                      <span className={`kb-pill tone-${masteryTone(subject.avg_mastery).cls}`}>
                        平均 {subject.avg_mastery}%
                      </span>
                    </div>
                  </div>
                  <div className={`kb-bar tone-${masteryTone(subject.avg_mastery).cls}`}>
                    <i style={{ width: `${Math.min(100, subject.avg_mastery)}%` }} />
                  </div>

                  <div className="kb-chapters">
                    {(subject.chapters || []).map((ch) => {
                      const key = `${subject.subject}|${ch.title}`
                      const open = !!openChapters[key]
                      const hasData = ch.knowledge_point_count > 0
                      const tone = masteryTone(ch.avg_mastery)
                      return (
                        <div className={`kb-chapter ${hasData ? '' : 'is-empty'}`} key={key}>
                          <button className="kb-chapter-head" onClick={() => toggleChapter(key)}>
                            {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                            <span className="kb-chapter-title">{ch.title}</span>
                            <span className="kb-chapter-meta">
                              {hasData ? `${ch.knowledge_point_count} 个知识点` : '暂无资料'}
                              {hasData && (
                                <span className={`kb-bar sm tone-${tone.cls}`}>
                                  <i style={{ width: `${Math.min(100, ch.avg_mastery)}%` }} />
                                </span>
                              )}
                            </span>
                          </button>

                          {open && hasData && (
                            <div className="kb-kp-list">
                              {(ch.knowledge_points || []).map((kp) => {
                                const kt = masteryTone(kp.mastery)
                                const isSel = selected
                                  && selected.subject === subject.subject
                                  && selected.chapter === ch.title
                                  && String(selected.kp?.id) === String(kp.id)
                                return (
                                  <div
                                    className={`pn-kp ${isSel ? 'is-sel' : ''}`}
                                    key={kpKeyOf(subject.subject, ch.title, kp)}
                                    onClick={() => pickKp(subject.subject, ch.title, kp)}
                                    role="button"
                                    tabIndex={0}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault()
                                        pickKp(subject.subject, ch.title, kp)
                                      }
                                    }}
                                    title={`掌握度 ${kp.mastery}（${kt.label}）`}
                                  >
                                    <span className={`kb-dot tone-${kt.cls}`} />
                                    <div className="kb-kp-main">
                                      <div className="kb-kp-row1">
                                        <span className="kb-kp-name">{kp.name}</span>
                                        <span className="kb-kp-tags">
                                          {(kp.question_types || []).slice(0, 3).map((t) => (
                                            <span className="kb-qtype sm" key={t}>{typeLabel(t)}</span>
                                          ))}
                                        </span>
                                      </div>
                                      <div className="kb-kp-row2">
                                        <span className={`kb-bar tone-${kt.cls}`}>
                                          <i style={{ width: `${Math.min(100, kp.mastery)}%` }} />
                                        </span>
                                        <span className={`kb-kp-pct tone-${kt.cls}`}>{kp.mastery}%</span>
                                        {Number(kp.question_count) > 0 && (
                                          <span className="kb-kp-freq">{kp.question_count} 题</span>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 右：知识点详情 + 开始练习 + 覆盖率 */}
          <div className="pn-side-col">
            <div className="card pn-detail-card">
              <div className="card-head">
                <div>
                  <div className="card-title">知识点详情</div>
                  <div className="card-sub">选中左侧知识点后，可一键进入刷题</div>
                </div>
              </div>
              <div className="card-body">
                {!selected ? (
                  <div className="pn-detail-empty">
                    <Target size={18} /> 请从左侧点选一个知识点
                  </div>
                ) : (
                  <div className="pn-detail">
                    <div className="pn-detail-name">{selected.kp?.name || '未命名知识点'}</div>
                    <div className="pn-detail-path">
                      {selected.subject} · {selected.chapter || '未归章'}
                    </div>

                    <div className="pn-detail-grid">
                      <div className="pn-detail-cell">
                        <span className="pn-cell-label">掌握度</span>
                        <span className={`pn-cell-val tone-${masteryTone(selected.kp?.mastery).cls}`}>
                          {Number(selected.kp?.mastery) || 0}%
                        </span>
                      </div>
                      <div className="pn-detail-cell">
                        <span className="pn-cell-label">关联题量</span>
                        <span className="pn-cell-val">
                          {qLoading ? '查询中…' : qCount == null ? '—' : `${qCount} 题`}
                        </span>
                      </div>
                      <div className="pn-detail-cell">
                        <span className="pn-cell-label">掌握档位</span>
                        <span className={`kb-pill tone-${masteryTone(selected.kp?.mastery).cls}`}>
                          {masteryTone(selected.kp?.mastery).label}
                        </span>
                      </div>
                      <div className="pn-detail-cell">
                        <span className="pn-cell-label">考频</span>
                        <span className="pn-cell-val">
                          {selected.kp?.exam_frequency != null
                            ? selected.kp.exam_frequency
                            : (selected.kp?.frequency != null ? selected.kp.frequency : '—')}
                        </span>
                      </div>
                    </div>

                    {(selected.kp?.question_types || []).length > 0 && (
                      <div className="pn-detail-types">
                        <span className="pn-cell-label">涉及题型</span>
                        <span className="pn-types">
                          {selected.kp.question_types.map((t) => (
                            <span className="kb-qtype" key={t}>{typeLabel(t)}</span>
                          ))}
                        </span>
                      </div>
                    )}

                    <div className="pn-detail-actions">
                      <button className="btn primary" onClick={() => startPractice(selected.subject, selected.chapter, selected.kp)}>
                        <Play size={14} /> 开始练习
                      </button>
                    </div>
                    {/* 跳转口径说明：已支持知识点级精确刷题 */}
                    <p className="pn-detail-note">
                      跳转口径：已支持知识点级精确刷题 —— 点击「开始练习」将按该知识点（kp_id）精确出题；
                      若该知识点暂无关联题目，刷题页会给出空态提示并可返回按科目/章节刷题。
                    </p>
                  </div>
                )}
              </div>
            </div>

            {coverage && (
              <div className="card">
                <div className="card-head">
                  <div>
                    <div className="card-title">结构化覆盖概览</div>
                    <div className="card-sub">
                      {coverage.totals?.documents ?? 0} 篇资料 · {coverage.totals?.chunks ?? 0} 分块
                    </div>
                  </div>
                </div>
                <div className="card-body">
                  <table className="kb-cov-table">
                    <thead>
                      <tr><th>科目</th><th>知识点</th><th>章节覆盖</th></tr>
                    </thead>
                    <tbody>
                      {(coverage.subjects || []).filter((s) => s.documents > 0).map((s) => (
                        <tr key={s.subject} className={s.is_core ? '' : 'ext'}>
                          <td>
                            {s.subject}
                            {!s.is_core && <span className="kb-tag-ext">拓展</span>}
                          </td>
                          <td>{s.knowledge_points}</td>
                          <td>
                            {s.outline_chapters ? `${s.covered_chapters}/${s.outline_chapters}` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
