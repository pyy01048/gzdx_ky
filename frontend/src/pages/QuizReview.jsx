import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Empty, toast } from '../components/UI'
import { LoadingState, ErrorState } from '../components/States'
import ErrorDomainNav from '../components/ErrorDomainNav'
import { errorsApi, quizSectionApi, fetchAllPages } from '../api/client'
import { normalizeOptions } from '../utils/optionText'
import {
  FileText, Target, Clock, CheckCircle, Search, RefreshCw,
  ChevronDown, ChevronRight, Brain, Play,
} from '../components/Icon'

/* =====================================================================
 * 刷题中心 · 错题库与收藏（自 Quiz.jsx 拆出，V12 重做）
 *
 * 之前这里只拉错题列表、而且**闭环面板从未加载**：
 * `loadPanel` 定义了却没有任何地方调用，所以「薄弱点 / 错因 / 待复习队列」
 * 永远是空的 —— 用户看到的就是「我根本看不到错题库」。
 *
 * 现在：
 *   1. 进入 Tab 同时加载错题列表 + 闭环数据，失败分别给错误态与重试；
 *   2. 错题按学科 / 掌握度 / 关键词筛选，展开即可看答案解析，并直达复盘页；
 *   3. 右侧收藏仍是本地快照，但会明确标注「为什么不能判分」；
 *   4. 所有空态都带下一步动作，不留空白区域。
 * ===================================================================== */

const MASTERY_LABEL = { unlearned: '未学', weak: '薄弱', mastered: '已掌握' }
const MASTERY_TONE = { unlearned: 'muted', weak: 'warn', mastered: 'ok' }
const ALL = ''

export default function QuizReview({ visible, tab, favs, mode, onBeginSession }) {
  /* ---------- 错题库 ---------- */
  const [errorItems, setErrorItems] = useState([])
  const [errLoading, setErrLoading] = useState(false)
  const [errError, setErrError] = useState('')
  const [q, setQ] = useState('')
  const [subject, setSubject] = useState(ALL)
  const [mastery, setMastery] = useState(ALL)
  const [expandedId, setExpandedId] = useState(null)

  /* ---------- 错题闭环面板（薄弱点 / 错因 / 待复习队列） ---------- */
  const [weak, setWeak] = useState([])
  const [reasons, setReasons] = useState([])
  const [closedStats, setClosedStats] = useState(null)
  const [due, setDue] = useState([])
  const [panelLoading, setPanelLoading] = useState(false)
  const [panelError, setPanelError] = useState('')

  const loadErrors = useCallback(async () => {
    setErrLoading(true)
    setErrError('')
    try {
      // 活跃错题全集：面板上写的是"活跃错题 N 道"，只翻第一页的话 N 会被截到 200。
      const rows = await fetchAllPages((p) => errorsApi.list({ ...p, status: 'active' }), { keys: ['errors'] })
      setErrorItems(rows)
    } catch (e) {
      setErrError(e?.message || '无法读取 /api/errors')
      setErrorItems([])
    } finally {
      setErrLoading(false)
    }
  }, [])

  const loadPanel = useCallback(async () => {
    setPanelLoading(true)
    setPanelError('')
    try {
      const [w, rs, st, d] = await Promise.all([
        quizSectionApi.weakPoints({ limit: 15 }),
        quizSectionApi.wrongReasons({ limit: 15 }),
        quizSectionApi.reviewStats(),
        quizSectionApi.reviews({ limit: 30 }),
      ])
      setWeak(Array.isArray(w?.items) ? w.items : [])
      setReasons(Array.isArray(rs?.items) ? rs.items : [])
      setClosedStats(st || null)
      setDue(Array.isArray(d?.items) ? d.items : [])
    } catch (e) {
      setPanelError(e?.message || '加载错题闭环数据失败')
    } finally {
      setPanelLoading(false)
    }
  }, [])

  const reloadAll = useCallback(() => { loadErrors(); loadPanel() }, [loadErrors, loadPanel])

  /* 待复习队列：提交复习结果（忘了 / 模糊 / 掌握） */
  const reviewItem = async (item, result) => {
    try {
      await quizSectionApi.submitReview({
        item_type: item.item_type || 'error',
        item_id: item.item_id,
        result,
      })
      toast('复习已记录')
      loadPanel()
    } catch (e) { toast(e.message || '复习提交失败') }
  }

  /* 进入 Tab 时同时加载两块数据；之前的实现漏了 loadPanel，整块面板恒为空。 */
  useEffect(() => {
    if (tab !== 'review') return
    loadErrors()
    loadPanel()
  }, [tab, loadErrors, loadPanel])

  const subjectOptions = useMemo(() => {
    const set = new Map()
    for (const e of errorItems) {
      const name = e.subject || '未分类'
      set.set(name, (set.get(name) || 0) + 1)
    }
    return [...set.entries()].map(([name, count]) => ({ name, count }))
  }, [errorItems])

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return errorItems.filter((e) => {
      if (subject !== ALL && (e.subject || '未分类') !== subject) return false
      if (mastery !== ALL && (e.mastery_state || 'unlearned') !== mastery) return false
      if (kw) {
        const hay = `${e.content || ''} ${e.error_reason || ''} ${e.analysis || ''}`.toLowerCase()
        if (!hay.includes(kw)) return false
      }
      return true
    })
  }, [errorItems, subject, mastery, q])

  if (!visible) return null

  /* options 走同一条归一化（对象数组 [{key,text}] 与字符串数组都吃），
     且 /api/errors 当前不返回选项 —— 归一化后为空是预期结果，
     此时做题页会落到「本题无选项」只读态，而不是把对象渲染成 [object Object]。 */
  const errQuestions = filtered.map((e) => ({
    id: String(e.question_id || e.id),
    content: e.content || '',
    options: normalizeOptions(e.options),
    answer: e.correct_answer || '', analysis: e.analysis || '',
    subject: e.subject || '', chapter: '错题', difficulty: 1, question_type: '',
  }))
  const favEntries = Object.entries(favs)
  /* 收藏快照本地只存题干/科目/章节，**没有 options**（历史设计）。
     这里同样过一遍归一化：空就空，但绝不让原始对象流到渲染层。 */
  const favQuestions = favEntries.map(([id, f]) => ({
    id, content: f.content || '', options: normalizeOptions(f.options),
    answer: '', analysis: '',
    subject: f.subject || '', chapter: f.chapter || '', difficulty: 1, question_type: f.type || '',
  }))

  /* ---------- 错题库主视图 ---------- */
  const renderErrorBank = () => (
    <section className="card qb-card">
      <div className="card-head">
        <div>
          <div className="card-title">错题库</div>
          <div className="card-sub">
            {errLoading
              ? '正在读取错题…'
              : `活跃错题 ${errorItems.length} 道${filtered.length !== errorItems.length ? ` · 当前筛选 ${filtered.length} 道` : ''} · 展开可看答案解析`}
          </div>
        </div>
        <div className="page-actions row">
          <button className="btn ghost sm" onClick={reloadAll} disabled={errLoading || panelLoading}>
            <RefreshCw size={14} /> 刷新
          </button>
          <Link className="btn ghost sm" to="/error-review">
            <Brain size={14} /> 去复盘
          </Link>
          <button
            className="btn primary sm"
            disabled={!errQuestions.length}
            onClick={() => onBeginSession(`错题重练（${errQuestions.length} 题）`, errQuestions, mode)}
          >
            <Play size={13} /> 全部重练
          </button>
        </div>
      </div>

      <div className="qb-toolbar">
        <label className="qb-search">
          <Search size={15} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索题干 / 错因 / 解析"
            aria-label="搜索错题"
          />
        </label>
        <div className="qb-chipgroup" role="group" aria-label="按学科筛选">
          <button className={`chip ${subject === ALL ? 'active' : ''}`} onClick={() => setSubject(ALL)}>
            全部学科
          </button>
          {subjectOptions.map((s) => (
            <button
              key={s.name}
              className={`chip ${subject === s.name ? 'active' : ''}`}
              onClick={() => setSubject(subject === s.name ? ALL : s.name)}
            >
              {s.name}<small>{s.count}</small>
            </button>
          ))}
        </div>
        <div className="qb-chipgroup" role="group" aria-label="按掌握度筛选">
          {[['', '全部'], ['unlearned', '未学'], ['weak', '薄弱'], ['mastered', '已掌握']].map(([v, label]) => (
            <button key={v || 'all'} className={`chip ${mastery === v ? 'active' : ''}`} onClick={() => setMastery(v)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {errLoading && <LoadingState text="正在加载错题…" rows={4} />}
      {!errLoading && errError && (
        <ErrorState title="错题库加载失败" message={errError} onRetry={loadErrors} retryText="重新加载" />
      )}
      {!errLoading && !errError && !filtered.length && (
        <Empty
          icon={<FileText size={40} />}
          title={errorItems.length ? '当前筛选下没有错题' : '错题库还是空的'}
          desc={errorItems.length
            ? '清空搜索或切换学科 / 掌握度，就能看到全部错题。'
            : '在刷题中心作答后，答错的题会自动归集到这里；也可以先手动录入。'}
          action={(
            <div className="row">
              <Link className="btn primary" to="/quiz">去刷题</Link>
              <Link className="btn ghost" to="/notebook">手动录入</Link>
            </div>
          )}
        />
      )}

      {!errLoading && !errError && filtered.length > 0 && (
        <div className="qb-list">
          {filtered.slice(0, 100).map((e) => {
            const open = expandedId === e.id
            const state = e.mastery_state || 'unlearned'
            return (
              <div key={e.id} className={`qb-item ${open ? 'is-open' : ''}`}>
                <button
                  className="qb-item-head"
                  aria-expanded={open}
                  onClick={() => setExpandedId(open ? null : e.id)}
                >
                  <span className={`qb-state ${MASTERY_TONE[state] || 'muted'}`}>
                    {e.mastery_label || MASTERY_LABEL[state] || state}
                  </span>
                  <span className="qb-subj">{e.subject || '未分类'}</span>
                  {e.error_reason && <span className="qb-reason">{e.error_reason}</span>}
                  <span className="qb-meta">复习 {e.review_count || 0} 次</span>
                  <span className="qb-caret">{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
                </button>
                <div className="qb-item-q">{e.content || '（题干为空）'}</div>
                {open && (
                  <div className="qb-detail">
                    <div className="qb-answers">
                      <div className="qb-ans wrong">
                        <span>我的答案</span><b>{e.my_answer || '—'}</b>
                      </div>
                      <div className="qb-ans right">
                        <span>正确答案</span><b>{e.correct_answer || '—'}</b>
                      </div>
                    </div>
                    {e.analysis && (
                      <div className="qb-analysis">
                        <div className="qb-analysis-title">解析</div>
                        <p>{e.analysis}</p>
                      </div>
                    )}
                    <div className="qb-detail-foot">
                      <span>正确率 {Math.round((Number(e.accuracy) || 0) * 100)}% · 下次复习 {fmtDate(e.next_review)}</span>
                      <div className="row">
                        <Link className="btn sm ghost" to={`/error-review?error_id=${e.id}`}>在复盘中查看</Link>
                        <button
                          className="btn sm primary"
                          onClick={() => onBeginSession(`错题 · ${e.subject || '未分类'}`, [{
                            id: String(e.question_id || e.id), content: e.content || '',
                            options: normalizeOptions(e.options),
                            answer: e.correct_answer || '', analysis: e.analysis || '',
                            subject: e.subject || '', chapter: '错题', difficulty: 1, question_type: '',
                          }], mode, 0, true)}
                        >
                          重练本题
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
          {filtered.length > 100 && (
            <p className="qnote">已展示前 100 道。需要按考点或错因细看，请前往「错题复盘」。</p>
          )}
        </div>
      )}
    </section>
  )

  /* ---------- 收藏（本地快照） ---------- */
  const renderFavorites = () => (
    <section className="card qb-card">
      <div className="card-head">
        <div>
          <div className="card-title">我的收藏</div>
          <div className="card-sub">收藏的是题目快照，不含选项，因此以浏览模式重看</div>
        </div>
        <button
          className="btn ghost sm"
          disabled={!favQuestions.length}
          onClick={() => onBeginSession('收藏题目', favQuestions, mode, 0, true)}
        >
          <Play size={13} /> 重看全部
        </button>
      </div>
      {!favQuestions.length ? (
        <Empty
          icon={<CheckCircle size={36} />}
          title="还没有收藏"
          desc="作答时点击题目右上角的星标，题目就会出现在这里。"
          action={<Link className="btn ghost" to="/quiz">去刷题</Link>}
        />
      ) : (
        <div className="qb-fav-list">
          {favQuestions.map((f) => (
            <div key={f.id} className="qb-fav-item">
              <div className="qb-fav-meta">{f.subject}{f.chapter ? ` · ${f.chapter}` : ''}</div>
              <div className="qb-fav-txt">{f.content}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  )

  /* ---------- 闭环面板 ---------- */
  const renderClosedLoop = () => (
    <section className="card qb-card">
      <div className="card-head">
        <div>
          <div className="card-title">错题闭环</div>
          <div className="card-sub">
            今日已复习 {closedStats?.today_reviews ?? '—'} 次 · 累计 {closedStats?.total_reviews ?? '—'} 次
          </div>
        </div>
        <button className="btn ghost sm" onClick={loadPanel} disabled={panelLoading}>
          <RefreshCw size={14} /> {panelLoading ? '刷新中…' : '刷新'}
        </button>
      </div>

      {panelError ? (
        <div className="qb-panel-error">
          <span>{panelError}</span>
          <button className="btn ghost sm" onClick={loadPanel}>重试</button>
        </div>
      ) : (
        <>
          <div className="qb-stat-grid">
            <div className="qb-stat">
              <span className="qb-stat-ico accent"><Target size={16} /></span>
              <div><b>{closedStats?.active_errors ?? '—'}</b><span>活跃错题</span></div>
            </div>
            <div className="qb-stat">
              <span className="qb-stat-ico warn"><Clock size={16} /></span>
              <div><b>{closedStats?.due_errors ?? '—'}</b><span>今日待复习</span></div>
            </div>
            <div className="qb-stat">
              <span className="qb-stat-ico ok"><CheckCircle size={16} /></span>
              <div><b>{closedStats?.graduated_errors ?? '—'}</b><span>已掌握</span></div>
            </div>
          </div>

          <div className="qb-loop-grid">
            <div>
              <div className="qb-subtitle">薄弱点排行</div>
              {panelLoading && !weak.length ? (
                <LoadingState text="加载中…" rows={2} />
              ) : weak.length === 0 ? (
                <div className="qb-muted">暂无薄弱点数据</div>
              ) : (
                <ol className="qb-rank">
                  {weak.map((w, i) => (
                    <li key={w.key || i}>
                      <span className="qb-rank-no">{String(i + 1).padStart(2, '0')}</span>
                      <span className="qb-rank-name">
                        {w.chapter || w.subject}{w.knowledge_point ? ` · ${w.knowledge_point}` : ''}
                      </span>
                      <span className="badge danger">{w.error_count} 错</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            <div>
              <div className="qb-subtitle">错因分布</div>
              {panelLoading && !reasons.length ? (
                <LoadingState text="加载中…" rows={2} />
              ) : reasons.length === 0 ? (
                <div className="qb-muted">暂无错因数据</div>
              ) : (
                <div className="qb-reasons">
                  {reasons.map((r, i) => {
                    const max = Math.max(...reasons.map((x) => Number(x.count) || 0), 1)
                    const pct = Math.round(((Number(r.count) || 0) / max) * 100)
                    return (
                      <div key={`${r.reason}-${i}`} className="qb-reason-row">
                        <span>{r.reason}</span>
                        <span className="qb-reason-bar"><i style={{ width: `${pct}%` }} /></span>
                        <b>{r.count}</b>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="qb-due">
            <div className="qb-subtitle">
              待复习队列（艾宾浩斯）
              <span className="qb-subtitle-note">按遗忘曲线排好序，直接给结果即可</span>
            </div>
            {panelLoading && !due.length ? (
              <LoadingState text="加载中…" rows={2} />
            ) : due.length === 0 ? (
              <div className="qb-muted">暂无待复习项。答错或标记薄弱后会自动进入队列。</div>
            ) : (
              <div className="qb-due-list">
                {due.map((item) => (
                  <div key={item.id || item.item_id} className="qb-due-item">
                    <div className="qb-due-main">
                      <div className="qb-due-title">{item.title || item.content || `${item.item_type}#${item.item_id}`}</div>
                      <div className="qb-due-meta">
                        {[item.subject, item.chapter].filter(Boolean).join(' · ') || '未分类'}
                        {' · 掌握度 '}{Math.round(Number(item.mastery) || 0)}
                      </div>
                    </div>
                    <div className="row">
                      <button className="btn sm ghost" onClick={() => reviewItem(item, 'forgotten')}>忘了</button>
                      <button className="btn sm ghost" onClick={() => reviewItem(item, 'fuzzy')}>模糊</button>
                      <button className="btn sm primary" onClick={() => reviewItem(item, 'mastered')}>掌握</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  )

  return (
    <>
      <ErrorDomainNav active="review" />
      <div className="qb-layout">
        <div className="qb-main">{renderErrorBank()}</div>
        <aside className="qb-side">
          {renderFavorites()}
        </aside>
        {renderClosedLoop()}
      </div>
    </>
  )
}

/* 后端返回 ISO 时间；无效值不显示 "Invalid Date" */
function fmtDate(s) {
  if (!s) return '—'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
