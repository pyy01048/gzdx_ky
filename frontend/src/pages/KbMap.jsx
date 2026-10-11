import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { taxonomyApi, reviewApi } from '../api/client'
import { toast, Empty } from '../components/UI'
import {
  RefreshCw, CheckCircle, ChevronRight, ChevronDown,
  Book, Brain, AlertCircle, Map as MapIcon,
} from '../components/Icon'

/* 题型码 → 中文标签（与后端 ALLOWED_QUESTION_TYPES 对齐）。
   后端落库为 single/judge/fill/essay/calc/draw，展示层统一翻成中文。 */
const TYPE_LABEL = {
  single: '单选',
  judge: '判断',
  fill: '填空',
  essay: '简答',
  calc: '计算',
  draw: '作图',
}
function typeLabel(t) {
  return TYPE_LABEL[t] || t || ''
}

/* 掌握度档位：与后端口径一致（<40 薄弱 / 40-69 一般 / ≥70 良好） */
function masteryTone(m) {
  const v = Number(m) || 0
  if (v >= 70) return { cls: 'ok', label: '良好' }
  if (v >= 40) return { cls: 'mid', label: '一般' }
  return { cls: 'low', label: '薄弱' }
}

/* 复习结果三态按钮 */
const REVIEW_ACTIONS = [
  { result: 'mastered', label: '会', cls: 'ok' },
  { result: 'fuzzy', label: '模糊', cls: 'warn' },
  { result: 'forgotten', label: '不会', cls: 'danger' },
]

/* 兼容 /taxonomy/subjects 的两种返回：数组或 {subjects:[...]} */
function normalizeSubjects(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.subjects)) return data.subjects
  if (data && Array.isArray(data.items)) return data.items
  return []
}

export default function KbMap() {
  const [subjects, setSubjects] = useState([])      // 动态科目列表（taxonomyApi.subjects）
  const [tree, setTree] = useState([])              // 结构树（taxonomyApi.tree）
  const [progress, setProgress] = useState(null)    // 全局掌握度总览
  const [due, setDue] = useState([])                // 今日复习队列
  const [coverage, setCoverage] = useState(null)    // 结构化覆盖体检
  const [status, setStatus] = useState('loading')  // loading | ok | error
  const [treeLoading, setTreeLoading] = useState(false)
  const [activeSubject, setActiveSubject] = useState('')
  const [openChapters, setOpenChapters] = useState({})
  const [reviewing, setReviewing] = useState(null)
  const [errMsg, setErrMsg] = useState('')

  /* 首次加载：科目列表 + 全局总览 + 全量结构树 并行拉取 */
  const loadAll = useCallback(async () => {
    setStatus('loading')
    setErrMsg('')
    try {
      const [sj, t, p, d, c] = await Promise.all([
        taxonomyApi.subjects(),
        taxonomyApi.tree(),
        reviewApi.progress(),
        reviewApi.due({ limit: 30 }),
        taxonomyApi.coverage(),
      ])
      setSubjects(normalizeSubjects(sj))
      const tNodes = t?.tree || []
      setTree(tNodes)
      setProgress(p)
      setDue(d?.items || [])
      setCoverage(c)
      setActiveSubject('')
      // 默认展开第一个有知识点的科目首个有知识点的章节
      const first = tNodes.find((s) => s.knowledge_point_count > 0)
      const firstCh = first?.chapters?.find((ch) => ch.knowledge_point_count > 0)
      setOpenChapters(
        first && firstCh ? { [`${first.subject}|${firstCh.title}`]: true } : {}
      )
      setStatus('ok')
    } catch (e) {
      setErrMsg(e?.message || '未知错误')
      setStatus('error')
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  /* 切换科目：仅重拉该科结构树，保留全局总览与队列 */
  const selectSubject = useCallback(async (name) => {
    if (name === activeSubject) return
    setActiveSubject(name)
    setTreeLoading(true)
    setOpenChapters({})
    try {
      const t = await taxonomyApi.tree(name || undefined)
      const tNodes = t?.tree || []
      setTree(tNodes)
      const first = tNodes.find((s) => s.knowledge_point_count > 0)
      const firstCh = first?.chapters?.find((ch) => ch.knowledge_point_count > 0)
      if (first && firstCh) {
        setOpenChapters({ [`${first.subject}|${firstCh.title}`]: true })
      }
    } catch (e) {
      toast('加载知识结构失败：' + (e?.message || ''))
    } finally {
      setTreeLoading(false)
    }
  }, [activeSubject])

  const toggleChapter = (key) =>
    setOpenChapters((s) => ({ ...s, [key]: !s[key] }))

  /* 提交一次复习结果（艾宾浩斯回写掌握度） */
  const submitReview = async (kpId, result) => {
    setReviewing(kpId)
    try {
      const r = await reviewApi.submit({ item_type: 'knowledge', item_id: kpId, result })
      toast(`已记录：掌握度 ${r.mastery_before} → ${r.mastery_after}，${r.interval} 天后复习`)
      await loadAll()
    } catch (e) {
      toast('记录失败：' + (e?.message || ''))
    } finally {
      setReviewing(null)
    }
  }

  /* 科目维度汇总（用于概览分布条） */
  const dist = useMemo(() => {
    if (!progress) return null
    const total = progress.total_knowledge_points || 0
    const mastered = progress.mastered_count || 0
    const weak = progress.weak_count || 0
    const mid = Math.max(0, total - mastered - weak)
    return { total, mastered, weak, mid }
  }, [progress])

  /* 科目选择 chips：优先用 /taxonomy/subjects（阶段1 契约 {subjects:[...]}）；
     若该表为空（旧库未播种 SubjectConfig），回退用结构树里已存在的科目，
     避免有大量知识点却误报「暂未配置科目」。 */
  const chipSubjects = useMemo(() => {
    if (subjects.length > 0) return subjects
    return tree
      .filter((s) => s.knowledge_point_count > 0)
      .map((s) => ({ subject: s.subject, question_count: s.knowledge_point_count }))
  }, [subjects, tree])

  /* ---------------- 三态：加载中 ---------------- */
  if (status === 'loading') {
    return (
      <div className="page">
        <div className="card">
          <div className="loading-inline">知识结构加载中…</div>
        </div>
      </div>
    )
  }

  /* ---------------- 三态：失败（toast + 就地提示 + 重试） ---------------- */
  if (status === 'error') {
    return (
      <div className="page">
        <div className="card kb-error-card">
          <div className="kb-error-icon"><AlertCircle size={28} /></div>
          <div className="kb-error-body">
            <div className="kb-error-title">知识地图加载失败</div>
            <div className="kb-error-desc">{errMsg || '请确认后端服务已启动后重试。'}</div>
            <button className="btn ghost" onClick={loadAll}>
              <RefreshCw size={14} /> 重新加载
            </button>
          </div>
        </div>
      </div>
    )
  }

  const coreSubjects = tree.filter((s) => s.is_core)
  const extSubjects = tree.filter((s) => !s.is_core)
  const hasAnyKp = tree.some((s) => s.knowledge_point_count > 0)

  return (
    <div className="page">
      {/* 页头 */}
      <div className="page-head">
        <div>
          <h1 className="page-title">知识地图</h1>
          <div className="page-sub">章节 → 知识点 → 题型 三级结构 · 掌握度可视化追踪</div>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={loadAll}>
            <RefreshCw size={15} /> 刷新
          </button>
        </div>
      </div>

      {/* 掌握度总览卡 */}
      {progress && dist && (
        <div className="kb-overview">
          <div className="kb-overview-main">
            <div className="kb-overview-figure">
              <span className={`kb-overview-num tone-${masteryTone(progress.avg_mastery).cls}`}>
                {progress.avg_mastery}
              </span>
              <span className="kb-overview-unit">%</span>
            </div>
            <div className="kb-overview-meta">
              <div className="kb-overview-label">平均掌握度</div>
              <div className="kb-overview-hint">
                共 {dist.total} 个知识点 · 已掌握 {dist.mastered} · 薄弱 {dist.weak}
              </div>
            </div>
          </div>
          <div className="kb-overview-dist">
            <div className="kb-dist-bar" role="img" aria-label="掌握度分布">
              <span className="seg low" style={{ width: dist.total ? `${(dist.weak / dist.total) * 100}%` : '0%' }} />
              <span className="seg mid" style={{ width: dist.total ? `${(dist.mid / dist.total) * 100}%` : '0%' }} />
              <span className="seg ok" style={{ width: dist.total ? `${(dist.mastered / dist.total) * 100}%` : '0%' }} />
            </div>
            <div className="kb-legend">
              <span className="kb-legend-item"><i className="dot low" />薄弱 &lt;40</span>
              <span className="kb-legend-item"><i className="dot mid" />一般 40–69</span>
              <span className="kb-legend-item"><i className="dot ok" />良好 ≥70</span>
            </div>
          </div>
        </div>
      )}

      {/* 全局统计小卡 */}
      {progress && (
        <div className="kb-stats">
          <div className="kb-stat">
            <span className="kb-stat-num">{progress.total_knowledge_points}</span>
            <span className="kb-stat-label">知识点总数</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num">{progress.reviewed_count}</span>
            <span className="kb-stat-label">已复习</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num warn">{progress.new_count}</span>
            <span className="kb-stat-label">待开始</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num ok">{progress.mastered_count}</span>
            <span className="kb-stat-label">已掌握</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num danger">{progress.weak_count}</span>
            <span className="kb-stat-label">薄弱</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num">{progress.due_count ?? 0}</span>
            <span className="kb-stat-label">待复习</span>
          </div>
          <div className="kb-stat">
            <span className="kb-stat-num">{progress.reviews_last_7_days}</span>
            <span className="kb-stat-label">近 7 天复习</span>
          </div>
        </div>
      )}

      {/* 科目选择（动态，来自 taxonomyApi.subjects） */}
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

      {/* 三态：科目为空（接口与结构树都无科目） */}
      {chipSubjects.length === 0 && !treeLoading ? (
        <Empty
          icon={<Book size={44} />}
          title="暂未配置科目"
          desc="请先在「科目管理」中添加考试科目与大纲章节，知识地图会自动生成三级结构。"
        />
      ) : (
        <div className="kb-layout">
          {/* 左：三级结构树 */}
          <div className="kb-tree-col">
            {treeLoading ? (
              <div className="card"><div className="loading-inline">结构加载中…</div></div>
            ) : !hasAnyKp ? (
              <Empty
                icon={<Brain size={44} />}
                title={activeSubject ? `「${activeSubject}」暂无知识点` : '暂无知识结构数据'}
                desc="上传资料并解析后，这里会按章节展开知识点与掌握度。"
              />
            ) : (
              [...coreSubjects, ...extSubjects].map((subject) => (
                <div className="card kb-subject-card" key={subject.subject}>
                  <div className="kb-subject-head">
                    <div className="kb-subject-titles">
                      <div className="kb-subject-name">
                        {subject.subject}
                        {!subject.is_core && <span className="kb-tag-ext">拓展</span>}
                      </div>
                      <div className="kb-subject-meta">
                        知识点 {subject.knowledge_point_count} · {subject.outline_chapter_count} 章节
                      </div>
                    </div>
                    <div className="kb-subject-mastery">
                      <span className={`kb-pill tone-${masteryTone(subject.avg_mastery).cls}`}>
                        平均 {subject.avg_mastery}%
                      </span>
                    </div>
                  </div>
                  {/* 科目维度掌握度条 */}
                  <div className={`kb-bar tone-${masteryTone(subject.avg_mastery).cls}`}>
                    <i style={{ width: `${Math.min(100, subject.avg_mastery)}%` }} />
                  </div>

                  <div className="kb-chapters">
                    {subject.chapters.map((ch) => {
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
                              <div className="kb-qtypes">
                                <span className="kb-qtypes-label">题型</span>
                                {ch.question_types.slice(0, 8).map((t) => (
                                  <span className="kb-qtype" key={t}>{typeLabel(t)}</span>
                                ))}
                              </div>
                              {ch.knowledge_points.map((kp) => {
                                const kt = masteryTone(kp.mastery)
                                return (
                                  <div className="kb-kp" key={kp.id}>
                                    <span className={`kb-dot tone-${kt.cls}`} title={`掌握度 ${kp.mastery}（${kt.label}）`} />
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
                                        <span className="kb-kp-freq">
                                          {kp.review_count ? `已复习 ${kp.review_count} 次` : '未复习'}
                                        </span>
                                      </div>
                                    </div>
                                    <span className="kb-kp-actions">
                                      {REVIEW_ACTIONS.map((r) => (
                                        <button
                                          key={r.result}
                                          className={`kb-mini-btn ${r.cls}`}
                                          disabled={reviewing === kp.id}
                                          onClick={() => submitReview(kp.id, r.result)}
                                          title={`标记为${r.label}`}
                                        >
                                          {r.label}
                                        </button>
                                      ))}
                                    </span>
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

          {/* 右：复习队列 + 薄弱考点 + 覆盖率 */}
          <div className="kb-side-col">
            <div className="card">
              <div className="card-head">
                <div>
                  <div className="card-title">今日复习队列</div>
                  <div className="card-sub">{due.length} 个知识点待复习</div>
                </div>
              </div>
              <div className="card-body">
                {due.length === 0 ? (
                  <div className="kb-due-empty">
                    <CheckCircle size={18} /> 今天没有待复习的知识点
                  </div>
                ) : (
                  <div className="kb-due-list">
                    {due.slice(0, 12).map((it) => (
                      <div className="kb-due-item" key={it.id}>
                        <div className="kb-due-main">
                          <div className="kb-due-name">{it.name}</div>
                          <div className="kb-due-sub">
                            {it.subject} · {it.chapter || '未归章'}
                            {it.is_new && <span className="kb-tag-new">新</span>}
                          </div>
                        </div>
                        <div className="kb-due-actions">
                          <button className="kb-mini-btn ok" disabled={reviewing === it.id}
                            onClick={() => submitReview(it.id, 'mastered')}>会</button>
                          <button className="kb-mini-btn warn" disabled={reviewing === it.id}
                            onClick={() => submitReview(it.id, 'fuzzy')}>模糊</button>
                          <button className="kb-mini-btn danger" disabled={reviewing === it.id}
                            onClick={() => submitReview(it.id, 'forgotten')}>不会</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {progress?.weak_points?.length > 0 && (
              <div className="card">
                <div className="card-head">
                  <div>
                    <div className="card-title">薄弱知识点</div>
                    <div className="card-sub">按掌握度升序，优先攻克</div>
                  </div>
                </div>
                <div className="card-body">
                  <div className="kb-weak-list">
                    {progress.weak_points.slice(0, 10).map((k) => (
                      <div className="kb-weak-item" key={k.id}>
                        <span className="kb-weak-name">{k.name}</span>
                        <span className="kb-weak-ch">{k.chapter || '未归章'}</span>
                        <span className={`kb-pill tone-${masteryTone(k.mastery).cls}`}>{k.mastery}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {coverage && (
              <div className="card">
                <div className="card-head">
                  <div>
                    <div className="card-title">结构化覆盖体检</div>
                    <div className="card-sub">
                      {coverage.totals?.documents ?? 0} 篇资料 · {coverage.totals?.chunks ?? 0} 分块 ·{' '}
                      {coverage.totals?.ocr_documents ?? 0} 篇扫描件
                    </div>
                  </div>
                </div>
                <div className="card-body">
                  <table className="kb-cov-table">
                    <thead>
                      <tr><th>科目</th><th>分块</th><th>知识点</th><th>章节覆盖</th></tr>
                    </thead>
                    <tbody>
                      {coverage.subjects.filter((s) => s.documents > 0).map((s) => (
                        <tr key={s.subject} className={s.is_core ? '' : 'ext'}>
                          <td>
                            {s.subject}
                            {!s.is_core && <span className="kb-tag-ext">拓展</span>}
                          </td>
                          <td>{s.chunks}</td>
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
