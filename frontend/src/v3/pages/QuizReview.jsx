import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Alert, Badge, Button, Card, CardHead, Chip, Empty, Input, LoadingState, toast,
} from '../ui'
import {
  Brain, CheckCircle2, ChevronDown, ChevronRight, Clock, FileText, Play, RefreshCw,
  Search, Target,
} from '../icons'
import { errorsApi, quizSectionApi, fetchAllPages } from '../../api/client'
import { normalizeOptions } from '../../utils/optionText'
import '../styles/quiz-v3.css'

/* =====================================================================
 * 刷题中心 · 错题库与收藏（v3）
 *
 * 1. 进入 Tab 同时加载错题列表 + 闭环数据，失败分别给错误态与重试；
 * 2. 错题按学科 / 掌握度 / 关键词筛选，展开即可看答案解析，并直达复盘页；
 * 3. 右侧收藏仍是本地快照，但会明确标注「为什么不能判分」；
 * 4. 所有空态都带下一步动作，不留空白区域。
 * ===================================================================== */

const MASTERY_LABEL = { unlearned: '未学', weak: '薄弱', mastered: '已掌握' }
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
    const map = new Map()
    for (const e of errorItems) {
      const name = e.subject || '未分类'
      map.set(name, (map.get(name) || 0) + 1)
    }
    return [...map.entries()].map(([name, count]) => ({ name, count }))
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

  const masteryTone = (state) => (
    state === 'mastered' ? 'success' : state === 'weak' ? 'warning' : undefined
  )

  /* ---------- 错题库主视图 ---------- */
  const renderErrorBank = () => (
    <Card className="v3-quiz-review-main">
      <CardHead
        title="错题库"
        sub={errLoading
          ? '正在读取错题…'
          : `活跃错题 ${errorItems.length} 道${filtered.length !== errorItems.length ? ` · 当前筛选 ${filtered.length} 道` : ''} · 展开可看答案解析`}
        actions={(
          <>
            <Button size="sm" variant="ghost" icon={<RefreshCw size={14} />}
              onClick={reloadAll} disabled={errLoading || panelLoading}>
              刷新
            </Button>
            <Link className="v3-btn v3-btn--ghost v3-btn--sm" to="/error-review">
              <Brain size={14} /> 去复盘
            </Link>
            <Button
              size="sm"
              variant="filled"
              icon={<Play size={13} />}
              disabled={!errQuestions.length}
              onClick={() => onBeginSession(`错题重练（${errQuestions.length} 题）`, errQuestions, mode)}
            >
              全部重练
            </Button>
          </>
        )}
      />

      <div className="v3-quiz-toolbar">
        <Input
          className="v3-quiz-search"
          icon={<Search size={15} />}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索题干 / 错因 / 解析"
          aria-label="搜索错题"
        />
        <div className="v3-quiz-chipgroup" role="group" aria-label="按学科筛选">
          <Chip active={subject === ALL} onClick={() => setSubject(ALL)}>全部学科</Chip>
          {subjectOptions.map((s) => (
            <Chip
              key={s.name}
              active={subject === s.name}
              onClick={() => setSubject(subject === s.name ? ALL : s.name)}
            >
              {s.name}<small style={{ marginLeft: 4, opacity: 0.7 }}>{s.count}</small>
            </Chip>
          ))}
        </div>
        <div className="v3-quiz-chipgroup" role="group" aria-label="按掌握度筛选">
          {[['', '全部'], ['unlearned', '未学'], ['weak', '薄弱'], ['mastered', '已掌握']].map(([v, label]) => (
            <Chip key={v || 'all'} active={mastery === v} onClick={() => setMastery(v)}>{label}</Chip>
          ))}
        </div>
      </div>

      {errLoading && <LoadingState text="正在加载错题…" />}
      {!errLoading && errError && (
        <Alert tone="danger">
          <div className="v3-quiz-inline">
            <span><strong>错题库加载失败：</strong>{errError}</span>
            <Button size="sm" variant="text" onClick={loadErrors}>重新加载</Button>
          </div>
        </Alert>
      )}
      {!errLoading && !errError && !filtered.length && (
        <Empty
          icon={<FileText size={26} />}
          title={errorItems.length ? '当前筛选下没有错题' : '错题库还是空的'}
          text={errorItems.length
            ? '清空搜索或切换学科 / 掌握度，就能看到全部错题。'
            : '在刷题中心作答后，答错的题会自动归集到这里；也可以先手动录入。'}
          action={(
            <div className="v3-quiz-inline">
              <Link className="v3-btn v3-btn--filled" to="/quiz">去刷题</Link>
              <Link className="v3-btn v3-btn--ghost" to="/notebook">手动录入</Link>
            </div>
          )}
        />
      )}

      {!errLoading && !errError && filtered.length > 0 && (
        <div className="v3-quiz-list">
          {filtered.slice(0, 100).map((e) => {
            const open = expandedId === e.id
            const state = e.mastery_state || 'unlearned'
            return (
              <div key={e.id} className={`v3-quiz-item ${open ? 'is-open' : ''}`}>
                <button
                  type="button"
                  className="v3-quiz-item__head"
                  aria-expanded={open}
                  onClick={() => setExpandedId(open ? null : e.id)}
                >
                  <Badge tone={masteryTone(state)}>
                    {e.mastery_label || MASTERY_LABEL[state] || state}
                  </Badge>
                  <span className="v3-quiz-item__subj">{e.subject || '未分类'}</span>
                  {e.error_reason && <span className="v3-quiz-item__reason">{e.error_reason}</span>}
                  <span className="v3-quiz-item__meta">复习 {e.review_count || 0} 次</span>
                  <span className="v3-quiz-item__caret">
                    {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                  </span>
                </button>
                <div className="v3-quiz-item__q">{e.content || '（题干为空）'}</div>
                {open && (
                  <div className="v3-quiz-item__detail">
                    <div className="v3-quiz-answers">
                      <div className="v3-quiz-answer is-wrong">
                        <span>我的答案</span><b>{e.my_answer || '—'}</b>
                      </div>
                      <div className="v3-quiz-answer is-right">
                        <span>正确答案</span><b>{e.correct_answer || '—'}</b>
                      </div>
                    </div>
                    {e.analysis && (
                      <div className="v3-quiz-analysis">
                        <div className="v3-quiz-analysis__title">解析</div>
                        <p>{e.analysis}</p>
                      </div>
                    )}
                    <div className="v3-quiz-item__foot">
                      <span>
                        正确率 {Math.round((Number(e.accuracy) || 0) * 100)}% · 下次复习 {fmtDate(e.next_review)}
                      </span>
                      <div className="v3-quiz-inline">
                        <Link className="v3-btn v3-btn--ghost v3-btn--sm" to={`/error-review?error_id=${e.id}`}>
                          在复盘中查看
                        </Link>
                        <Button
                          size="sm"
                          variant="filled"
                          onClick={() => onBeginSession(`错题 · ${e.subject || '未分类'}`, [{
                            id: String(e.question_id || e.id), content: e.content || '',
                            options: normalizeOptions(e.options),
                            answer: e.correct_answer || '', analysis: e.analysis || '',
                            subject: e.subject || '', chapter: '错题', difficulty: 1, question_type: '',
                          }], mode, 0, true)}
                        >
                          重练本题
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
          {filtered.length > 100 && (
            <p className="v3-quiz-note">已展示前 100 道。需要按考点或错因细看，请前往「错题复盘」。</p>
          )}
        </div>
      )}
    </Card>
  )

  /* ---------- 收藏（本地快照） ---------- */
  const renderFavorites = () => (
    <Card className="v3-quiz-review-side">
      <CardHead
        title="我的收藏"
        sub="收藏的是题目快照，不含选项，因此以浏览模式重看"
        actions={(
          <Button
            size="sm"
            variant="ghost"
            icon={<Play size={13} />}
            disabled={!favQuestions.length}
            onClick={() => onBeginSession('收藏题目', favQuestions, mode, 0, true)}
          >
            重看全部
          </Button>
        )}
      />
      {!favQuestions.length ? (
        <Empty
          icon={<CheckCircle2 size={24} />}
          title="还没有收藏"
          text="作答时点击题目右上角的星标，题目就会出现在这里。"
          action={<Link className="v3-btn v3-btn--ghost" to="/quiz">去刷题</Link>}
        />
      ) : (
        <div className="v3-quiz-fav-list">
          {favQuestions.map((f) => (
            <div key={f.id} className="v3-quiz-fav">
              <div className="v3-quiz-fav__meta">{f.subject}{f.chapter ? ` · ${f.chapter}` : ''}</div>
              <div className="v3-quiz-fav__text">{f.content}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )

  /* ---------- 闭环面板 ---------- */
  const renderClosedLoop = () => (
    <Card>
      <CardHead
        title="错题闭环"
        sub={`今日已复习 ${closedStats?.today_reviews ?? '—'} 次 · 累计 ${closedStats?.total_reviews ?? '—'} 次`}
        actions={(
          <Button size="sm" variant="ghost" icon={<RefreshCw size={14} />}
            onClick={loadPanel} disabled={panelLoading}>
            {panelLoading ? '刷新中…' : '刷新'}
          </Button>
        )}
      />

      {panelError ? (
        <Alert tone="danger">
          <div className="v3-quiz-inline">
            <span>{panelError}</span>
            <Button size="sm" variant="text" onClick={loadPanel}>重试</Button>
          </div>
        </Alert>
      ) : (
        <div className="v3-quiz-loop">
          <div className="v3-quiz-loop__stats">
            <div className="v3-quiz-loop__stat">
              <span className="v3-quiz-loop__ico"><Target size={16} /></span>
              <div><b>{closedStats?.active_errors ?? '—'}</b><span>活跃错题</span></div>
            </div>
            <div className="v3-quiz-loop__stat">
              <span className="v3-quiz-loop__ico is-warn"><Clock size={16} /></span>
              <div><b>{closedStats?.due_errors ?? '—'}</b><span>今日待复习</span></div>
            </div>
            <div className="v3-quiz-loop__stat">
              <span className="v3-quiz-loop__ico is-ok"><CheckCircle2 size={16} /></span>
              <div><b>{closedStats?.graduated_errors ?? '—'}</b><span>已掌握</span></div>
            </div>
          </div>

          <div className="v3-quiz-loop__grid">
            <div>
              <div className="v3-quiz-subtitle">薄弱点排行</div>
              {panelLoading && !weak.length ? (
                <LoadingState text="加载中…" />
              ) : weak.length === 0 ? (
                <div className="v3-quiz-muted">暂无薄弱点数据</div>
              ) : (
                <ol className="v3-quiz-rank">
                  {weak.map((w, i) => (
                    <li key={w.key || i}>
                      <span className="v3-quiz-rank__no">{String(i + 1).padStart(2, '0')}</span>
                      <span className="v3-quiz-rank__name">
                        {w.chapter || w.subject}{w.knowledge_point ? ` · ${w.knowledge_point}` : ''}
                      </span>
                      <Badge tone="danger">{w.error_count} 错</Badge>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            <div>
              <div className="v3-quiz-subtitle">错因分布</div>
              {panelLoading && !reasons.length ? (
                <LoadingState text="加载中…" />
              ) : reasons.length === 0 ? (
                <div className="v3-quiz-muted">暂无错因数据</div>
              ) : (
                <div className="v3-quiz-reasons">
                  {reasons.map((r, i) => {
                    const max = Math.max(...reasons.map((x) => Number(x.count) || 0), 1)
                    const pct = Math.round(((Number(r.count) || 0) / max) * 100)
                    return (
                      <div key={`${r.reason}-${i}`} className="v3-quiz-reason">
                        <span>{r.reason}</span>
                        <span className="v3-quiz-reason__bar"><i style={{ width: `${pct}%` }} /></span>
                        <b>{r.count}</b>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="v3-quiz-due">
            <div className="v3-quiz-subtitle">
              待复习队列（艾宾浩斯）
              <small>按遗忘曲线排好序，直接给结果即可</small>
            </div>
            {panelLoading && !due.length ? (
              <LoadingState text="加载中…" />
            ) : due.length === 0 ? (
              <div className="v3-quiz-muted">暂无待复习项。答错或标记薄弱后会自动进入队列。</div>
            ) : (
              <div className="v3-quiz-due__list">
                {due.map((item) => (
                  <div key={item.id || item.item_id} className="v3-quiz-due__item">
                    <div className="v3-quiz-due__main">
                      <div className="v3-quiz-due__title">
                        {item.title || item.content || `${item.item_type}#${item.item_id}`}
                      </div>
                      <div className="v3-quiz-due__meta">
                        {[item.subject, item.chapter].filter(Boolean).join(' · ') || '未分类'}
                        {' · 掌握度 '}{Math.round(Number(item.mastery) || 0)}
                      </div>
                    </div>
                    <div className="v3-quiz-inline">
                      <Button size="sm" variant="ghost" onClick={() => reviewItem(item, 'forgotten')}>忘了</Button>
                      <Button size="sm" variant="ghost" onClick={() => reviewItem(item, 'fuzzy')}>模糊</Button>
                      <Button size="sm" variant="filled" onClick={() => reviewItem(item, 'mastered')}>掌握</Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  )

  return (
    <div className="v3-quiz">
      <nav className="v3-quiz-domain" aria-label="错题域导航">
        <Link to="/error-review">错题分析</Link>
        <Link to="/notebook">错题本</Link>
        <Link to="/quiz?tab=review" className="is-active" aria-current="page">快速重练</Link>
      </nav>
      <div className="v3-quiz-review-grid">
        {renderErrorBank()}
        {renderFavorites()}
      </div>
      {renderClosedLoop()}
    </div>
  )
}

/* 后端返回 ISO 时间；无效值不显示 "Invalid Date" */
function fmtDate(s) {
  if (!s) return '—'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
