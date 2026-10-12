import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { errorsApi, reviewApi, quizApi } from '../api/client'
import { toast, Empty, Segmented } from '../components/UI'
import {
  RefreshCw, AlertCircle, ChevronDown, ChevronRight, Brain, Map, FileText, Activity, Target
} from '../components/Icon'
import './ErrorReview.css'

/* ==========================================================================
   错题复盘（ErrorReview）
   --------------------------------------------------------------------------
   与「电子错题本」（/notebook）分工：Notebook 负责"录入 + 日常复习"，
   本页负责"复盘分析"——把错题摊开成数据，看错误原因分布、薄弱知识点，
   对单题做 AI 归因与知识点挂接。

   数据来源（全部为后端真实接口，无 mock）：
     - GET  /api/errors?subject=&error_reason=&status=&page=&page_size=  错题列表（分页）
     - GET  /api/quiz/wrong-reasons                错因分布（错因筛选项 + 计数）
     - GET  /api/review/stats                       复盘总览（在练/到期/已毕业/今日复习）
     - GET  /api/review/weak-points                 薄弱知识点排行（错题数 / 弱度）
     - GET  /api/errors/{id}/knowledge-points      该错题已挂接的知识点
     - POST /api/errors/{id}/ai-analyze             AI 归因分析
     - POST /api/errors/{id}/link-knowledge         挂接知识点 {knowledge_point_id}
     - DELETE /api/errors/links/{link_id}           解除挂接
   任一接口失败都在页面上如实呈现错误态，不用假数据兜底。
   ========================================================================== */

const PAGE_SIZE = 20

/* 掌握度筛选：后端 status 字段取值（active=在练/未毕业，graduated=已毕业） */
const MASTERY_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'active', label: '未掌握' },
  { value: 'graduated', label: '已掌握' },
]

/* 状态徽标配色类（沿用 global.css 的 soft 色令牌） */
const STATUS_CLASS = { active: 'warn', graduated: 'ok', archived: 'muted' }

/** 兼容 /api/errors 的多种返回形态：数组 / {items:[]} / {errors:[]} */
function normalizeList(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.items)) return data.items
  if (data && Array.isArray(data.errors)) return data.errors
  return []
}

/** 标签：后端可能是 JSON 字符串或数组 */
function parseTags(t) {
  if (Array.isArray(t)) return t
  if (typeof t === 'string') {
    try { const p = JSON.parse(t || '[]'); return Array.isArray(p) ? p : [] } catch { return [] }
  }
  return []
}

/** 知识点候选下拉：从薄弱知识点排行取（后端已按弱度倒序） */
function kpOptions(weakItems) {
  return weakItems.map((w) => ({
    id: w.knowledge_point_id,
    label: `${w.name}（${w.subject || '未分类'} · 错 ${w.error_count || 0} 次）`
  }))
}

export default function ErrorReview() {
  const [searchParams] = useSearchParams()
  const urlErrorId = searchParams.get('error_id')   // 深链：知识地图「去复盘」跳转目标
  const [subject, setSubject] = useState(() => searchParams.get('subject') || '')
  const [errorReason, setErrorReason] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [listState, setListState] = useState('loading') // loading | ok | error
  const [listErr, setListErr] = useState('')
  const [loading, setLoading] = useState(false)

  /* 统计 / 错因 / 薄弱知识点（三个独立接口，失败各自降级，不影响主列表） */
  const [stats, setStats] = useState(null)
  const [statsErr, setStatsErr] = useState('')
  const [reasons, setReasons] = useState([])
  const [weak, setWeak] = useState([])
  const [weakErr, setWeakErr] = useState('')

  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState({ state: 'idle', kps: [], kpErr: '' })
  const [ai, setAi] = useState({ state: 'idle', text: '', err: '' })
  const [linkKp, setLinkKp] = useState('')
  const [linking, setLinking] = useState(false)

  const listSeq = useRef(0)
  const detailSeq = useRef(0)

  /* ---------------- 错题列表 ---------------- */
  const loadList = useCallback(async () => {
    const seq = ++listSeq.current
    setLoading(true)
    try {
      const data = await errorsApi.list({
        subject: subject || undefined,
        error_reason: errorReason || undefined,
        status: status || undefined,
        page,
        page_size: PAGE_SIZE
      })
      if (seq !== listSeq.current) return
      const list = normalizeList(data)
      setItems(list)
      setTotal(Number(data?.total) || list.length)
      setTotalPages(Number(data?.total_pages) || 1)
      setListState('ok')
      setListErr('')
    } catch (e) {
      if (seq !== listSeq.current) return
      setItems([])
      setTotal(0)
      setListErr(e?.message || '未知错误')
      setListState('error')
    } finally {
      if (seq === listSeq.current) setLoading(false)
    }
  }, [subject, errorReason, status, page])

  useEffect(() => { loadList() }, [loadList])

  /* ---------------- 复盘总览 ---------------- */
  useEffect(() => {
    let alive = true
    reviewApi
      .stats()
      .then((d) => { if (alive) { setStats(d); setStatsErr('') } })
      .catch((e) => { if (alive) { setStats(null); setStatsErr(e?.message || '统计接口不可用') } })
    return () => { alive = false }
  }, [])

  /* ---------------- 错因分布（供筛选 chip 显示计数） ---------------- */
  useEffect(() => {
    let alive = true
    quizApi
      .wrongReasons()
      .then((d) => { if (alive) setReasons(Array.isArray(d?.items) ? d.items : []) })
      .catch(() => { if (alive) setReasons([]) }) // 筛选项拉不到就不显示计数，不阻断主列表
    return () => { alive = false }
  }, [])

  /* ---------------- 薄弱知识点（同时作为挂接知识点候选） ---------------- */
  useEffect(() => {
    let alive = true
    reviewApi
      .weakPoints({ limit: 30 })
      .then((d) => { if (alive) { setWeak(Array.isArray(d?.items) ? d.items : []); setWeakErr('') } })
      .catch((e) => { if (alive) { setWeak([]); setWeakErr(e?.message || '薄弱知识点接口不可用') } })
    return () => { alive = false }
  }, [])

  /* 切换筛选回到第一页 */
  const pickSubject = (v) => { setSubject(v); setPage(1) }
  const pickReason = (v) => { setErrorReason(v); setPage(1) }
  const pickStatus = (v) => { setStatus(v); setPage(1) }

  /* ---------------- 选中一条错题：拉已挂接知识点 ---------------- */
  const selectError = async (err) => {
    setSelectedId(err.id)
    setAi({ state: 'idle', text: '', err: '' })
    setLinkKp('')
    const seq = ++detailSeq.current
    setDetail({ state: 'loading', kps: [], kpErr: '' })
    try {
      const d = await errorsApi.knowledgePoints(err.id)
      if (seq !== detailSeq.current) return
      const list = Array.isArray(d?.items) ? d.items : Array.isArray(d) ? d : []
      setDetail({ state: 'ok', kps: list, kpErr: '' })
    } catch (e) {
      if (seq !== detailSeq.current) return
      setDetail({ state: 'error', kps: [], kpErr: e?.message || '知识点关联接口不可用' })
    }
  }

  /* 列表刷新后，若当前选中项已不在本页，自动选第一条，保证详情区不悬空 */
  useEffect(() => {
    if (listState !== 'ok' || items.length === 0) { if (selectedId != null && items.length === 0) setSelectedId(null); return }
    if (selectedId == null || !items.some((e) => e.id === selectedId)) selectError(items[0])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, listState])

  /* 深链：/error-review?error_id=X&subject=Y —— 列表就绪后自动选中该错题 */
  useEffect(() => {
    if (!urlErrorId || listState !== 'ok') return
    const target = items.find((e) => String(e.id) === String(urlErrorId))
    if (target) selectError(target)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, listState, urlErrorId])

  const selected = useMemo(
    () => items.find((e) => e.id === selectedId) || null,
    [items, selectedId]
  )

  /* ---------------- AI 归因分析 ---------------- */
  const runAiAnalyze = async () => {
    if (selectedId == null) return
    setAi({ state: 'loading', text: '', err: '' })
    try {
      const d = await errorsApi.aiAnalyze(selectedId)
      const text =
        typeof d === 'string' ? d
          : d?.analysis || d?.result || d?.message || ''
      setAi({ state: 'ok', text: text || '接口已返回，但没有可展示的分析文本。', err: '' })
      loadList() // 分析结果会写回 analysis 字段，顺手刷新列表
    } catch (e) {
      setAi({ state: 'error', text: '', err: e?.message || 'AI 分析接口调用失败' })
    }
  }

  /* ---------------- 挂接 / 解除知识点 ---------------- */
  const doLink = async () => {
    if (selectedId == null || !linkKp) return
    setLinking(true)
    try {
      await errorsApi.linkKnowledge(selectedId, { knowledge_point_id: Number(linkKp) })
      const d = await errorsApi.knowledgePoints(selectedId)
      const list = Array.isArray(d?.items) ? d.items : Array.isArray(d) ? d : []
      setDetail({ state: 'ok', kps: list, kpErr: '' })
      setLinkKp('')
      toast('知识点已关联')
    } catch (e) {
      toast(`关联失败：${e?.message || '未知错误'}`)
    } finally {
      setLinking(false)
    }
  }

  const doUnlink = async (linkId) => {
    if (linkId == null) return
    try {
      await errorsApi.unlinkKnowledge(linkId)
      const d = await errorsApi.knowledgePoints(selectedId)
      const list = Array.isArray(d?.items) ? d.items : Array.isArray(d) ? d : []
      setDetail({ state: 'ok', kps: list, kpErr: '' })
      toast('已解除关联')
    } catch (e) {
      toast(`解除失败：${e?.message || '未知错误'}`)
    }
  }

  const kpChoices = kpOptions(weak)

  /* ---------------- 首屏加载骨架 ---------------- */
  if (listState === 'loading') {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1 className="page-title">错题复盘</h1>
            <div className="page-sub">错因分布 · 薄弱知识点 · 单题 AI 归因</div>
          </div>
        </div>
        <div className="card er-card">
          <div className="card-head">
            <div>
              <div className="card-title">错题清单</div>
              <div className="card-sub">正在读取 /api/errors…</div>
            </div>
          </div>
          <div className="card-body">
            <div className="er-skel-list">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div className="er-skel-row" key={i}>
                  <span className="er-skel w1" />
                  <span className="er-skel w90" />
                  <span className="er-skel w46" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  /* ---------------- 列表接口失败：三态错误页 ---------------- */
  if (listState === 'error') {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1 className="page-title">错题复盘</h1>
            <div className="page-sub">错因分布 · 薄弱知识点 · 单题 AI 归因</div>
          </div>
        </div>
        <div className="card er-error-card">
          <div className="er-error-icon"><AlertCircle size={28} /></div>
          <div>
            <div className="er-error-title">错题列表加载失败</div>
            <div className="er-error-desc">{listErr || '请确认后端服务已启动后重试。'}</div>
            <button className="btn ghost" onClick={loadList}>
              <RefreshCw size={14} /> 重新加载
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      {/* 页头 */}
      <div className="page-head">
        <div>
          <h1 className="page-title">错题复盘</h1>
          <div className="page-sub">错因分布 · 薄弱知识点 · 单题 AI 归因与知识点挂接</div>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={loadList} disabled={loading}>
            <RefreshCw size={15} /> 刷新
          </button>
        </div>
      </div>

      {/* 复盘总览：GET /api/review/stats */}
      <div className="er-stat-row">
        {statsErr ? (
          <div className="card er-card er-inline-error">
            <AlertCircle size={14} />
            <span>复盘总览不可用：{statsErr}</span>
          </div>
        ) : (
          <>
            <StatTile label="错题总数" value={stats?.active_errors} />
            <StatTile label="今日待复盘" value={stats?.due_errors} tone="warn" />
            <StatTile label="已掌握" value={stats?.graduated_errors} tone="ok" />
            <StatTile label="累计复习次数" value={stats?.total_reviews} />
          </>
        )}
      </div>

      {/* 筛选：掌握度 / 学科 / 错因 */}
      <div className="er-filterbar">
        <Target size={15} className="er-filterbar-icon" />
        <span className="er-filter-label">掌握度</span>
        <div className="kb-chips">
          {MASTERY_OPTIONS.map((o) => (
            <button
              key={o.value || 'all'}
              className={`kb-chip ${status === o.value ? 'active' : ''}`}
              onClick={() => pickStatus(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="er-filterbar">
        <FileText size={15} className="er-filterbar-icon" />
        <span className="er-filter-label">错因</span>
        <div className="kb-chips">
          <button
            className={`kb-chip ${errorReason === '' ? 'active' : ''}`}
            onClick={() => pickReason('')}
          >
            全部
          </button>
          {reasons.map((r) => (
            <button
              key={r.reason}
              className={`kb-chip ${errorReason === r.reason ? 'active' : ''}`}
              onClick={() => pickReason(r.reason)}
            >
              {r.reason}
              {r.count > 0 && <small>{r.count}</small>}
            </button>
          ))}
        </div>
      </div>

      <div className="er-filterbar">
        <Activity size={15} className="er-filterbar-icon" />
        <span className="er-filter-label">学科</span>
        <div className="kb-chips">
          <button
            className={`kb-chip ${subject === '' ? 'active' : ''}`}
            onClick={() => pickSubject('')}
          >
            全部
          </button>
          {Array.from(new Set(items.map((e) => e.subject).filter(Boolean))).map((s) => (
            <button
              key={s}
              className={`kb-chip ${subject === s ? 'active' : ''}`}
              onClick={() => pickSubject(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="er-layout">
        {/* 左：错题列表 */}
        <div className="card er-card">
          <div className="card-head">
            <div>
              <div className="card-title">错题清单</div>
              <div className="card-sub">
                共 <b>{total}</b> 条 · 第 {page} / {Math.max(totalPages, 1)} 页
                {loading && ' · 加载中…'}
              </div>
            </div>
          </div>
          <div className="card-body">
            {items.length === 0 ? (
              <Empty
                icon={<FileText size={44} />}
                title="当前筛选条件下没有错题"
                desc="换个掌握度 / 错因 / 学科，或先去「电子错题本」录入错题。"
              />
            ) : (
              <div className="er-list">
                {items.map((e) => {
                  const open = selectedId === e.id
                  return (
                    <button
                      key={e.id}
                      className={`er-row ${open ? 'active' : ''}`}
                      onClick={() => selectError(e)}
                    >
                      <div className="er-row-top">
                        <span className={`er-status ${STATUS_CLASS[e.status] || 'muted'}`}>
                          {e.status === 'graduated' ? '已掌握' : e.status === 'archived' ? '已归档' : '未掌握'}
                        </span>
                        <span className="er-subj">{e.subject || '未分类'}</span>
                        <span className="er-reason">{e.error_reason || '未标注错因'}</span>
                        <span className="er-meta">
                          复习 {e.review_count || 0} 次 · 正确率 {Math.round((Number(e.accuracy) || 0) * 100)}%
                        </span>
                      </div>
                      <div className="er-row-q">
                        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        <span>{e.content || '（题干为空）'}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}

            {totalPages > 1 && (
              <div className="er-pager">
                <button className="btn ghost" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
                  上一页
                </button>
                <span className="er-pager-txt">{page} / {totalPages}</span>
                <button className="btn ghost" disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)}>
                  下一页
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 右：详情 + 知识点关联 + AI 分析 */}
        <div className="er-side">
          <div className="card er-card">
            <div className="card-head">
              <div>
                <div className="card-title">错题详情</div>
                <div className="card-sub">
                  {selected ? `#${selected.id} · ${selected.subject || '未分类'}` : '请从左侧选择一条错题'}
                </div>
              </div>
              {selected && (
                <button className="btn primary er-ai-btn" onClick={runAiAnalyze} disabled={ai.state === 'loading'}>
                  <Brain size={14} />
                  {ai.state === 'loading' ? '分析中…' : 'AI 归因分析'}
                </button>
              )}
            </div>
            <div className="card-body">
              {!selected ? (
                <Empty icon={<Brain size={40} />} title="尚未选择错题" desc="点击左侧任意一条错题查看详情、知识点与 AI 分析。" />
              ) : (
                <>
                  <div className="er-q">{selected.content || '（题干为空）'}</div>
                  <div className="er-answers">
                    <div className="er-ans wrong">
                      <span className="er-ans-label">我的答案</span>
                      <span>{selected.my_answer || '—'}</span>
                    </div>
                    <div className="er-ans right">
                      <span className="er-ans-label">正确答案</span>
                      <span>{selected.correct_answer || '—'}</span>
                    </div>
                  </div>
                  <div className="er-kv">
                    <span>错因</span><b>{selected.error_reason || '未标注'}</b>
                    <span>下次复习</span><b>{selected.next_review ? new Date(selected.next_review).toLocaleString('zh-CN') : '—'}</b>
                  </div>
                  {parseTags(selected.tags).length > 0 && (
                    <div className="er-tags">
                      {parseTags(selected.tags).map((t) => (
                        <span className="er-tag" key={t}>{t}</span>
                      ))}
                    </div>
                  )}

                  {/* AI 分析结果 */}
                  {ai.state === 'error' && (
                    <div className="er-ai er-ai-error">
                      <AlertCircle size={15} />
                      <div>
                        <div className="er-ai-title">AI 分析失败</div>
                        <div className="er-ai-err">{ai.err}</div>
                      </div>
                    </div>
                  )}
                  {ai.state === 'ok' && (
                    <div className="er-ai er-ai-ok">
                      <Brain size={15} />
                      <div>
                        <div className="er-ai-title">AI 归因分析</div>
                        <div className="er-ai-body">{ai.text}</div>
                      </div>
                    </div>
                  )}
                  {ai.state === 'idle' && selected.analysis && (
                    <div className="er-ai er-ai-ok">
                      <Brain size={15} />
                      <div>
                        <div className="er-ai-title">已有分析</div>
                        <div className="er-ai-body">{selected.analysis}</div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* 知识点关联 */}
          <div className="card er-card">
            <div className="card-head">
              <div>
                <div className="card-title">知识点关联</div>
                <div className="card-sub">挂接后薄弱知识点统计与间隔复习才会收敛到该考点</div>
              </div>
            </div>
            <div className="card-body">
              {!selected ? (
                <div className="er-muted">选择一条错题后可查看 / 挂接知识点。</div>
              ) : (
                <>
                  {detail.state === 'loading' && <div className="loading-inline">知识点加载中…</div>}
                  {detail.state === 'error' && (
                    <div className="er-inline-error">
                      <AlertCircle size={14} />
                      <span>知识点关联读取失败：{detail.kpErr}</span>
                    </div>
                  )}
                  {detail.state === 'ok' && detail.kps.length === 0 && (
                    <div className="er-muted">该错题尚未关联任何知识点。</div>
                  )}
                  {detail.state === 'ok' && detail.kps.length > 0 && (
                    <div className="er-kp-list">
                      {detail.kps.map((k) => (
                        <div className="er-kp" key={k.link_id ?? k.id ?? k.knowledge_point_id}>
                          <Map size={14} />
                          <div className="er-kp-main">
                            <div className="er-kp-name">{k.name || k.kp_name || `知识点 #${k.knowledge_point_id}`}</div>
                            <div className="er-kp-sub">
                              {[k.subject, k.chapter].filter(Boolean).join(' · ') || '—'}
                              {k.mastery != null && ` · 掌握度 ${k.mastery}`}
                            </div>
                          </div>
                          <button
                            className="btn mini ghost"
                            onClick={() => doUnlink(k.link_id ?? k.linkId)}
                            title="解除关联"
                          >
                            解除
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 挂接：候选来自 /api/review/weak-points */}
                  <div className="er-link-row">
                    <select
                      className="form-input er-select"
                      value={linkKp}
                      onChange={(e) => setLinkKp(e.target.value)}
                    >
                      <option value="">
                        {kpChoices.length ? '选择薄弱知识点…' : '薄弱知识点接口不可用，暂无候选'}
                      </option>
                      {kpChoices.map((c) => (
                        <option key={c.id} value={c.id}>{c.label}</option>
                      ))}
                    </select>
                    <button className="btn primary" onClick={doLink} disabled={!linkKp || linking}>
                      {linking ? '关联中…' : '关联'}
                    </button>
                  </div>
                  {weakErr && <div className="er-inline-error"><AlertCircle size={14} /><span>薄弱知识点接口失败：{weakErr}</span></div>}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* 总览小卡（数值来自 /api/review/stats） */
function StatTile({ label, value, tone }) {
  return (
    <div className={`card er-stat ${tone ? `er-stat-${tone}` : ''}`}>
      <div className="er-stat-num">{value == null ? '—' : value}</div>
      <div className="er-stat-label">{label}</div>
    </div>
  )
}