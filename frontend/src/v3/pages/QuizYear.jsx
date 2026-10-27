import React, { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Empty, LoadingState, Progress, Segmented,
} from '../ui'
import {
  BookOpen, Calendar, FileText, LayoutGrid, List, RefreshCw,
} from '../icons'
import { quizApi, fetchAllPages } from '../../api/client'
import { normQ, loadRecs, SOURCE_KIND_LABEL } from './quizShared'
import '../styles/quiz-v3.css'

/* =====================================================================
 * 刷题中心 · 按年份（v3）
 * 真题套卷索引 / 年份×科目聚合（后端聚合端点，不前端猜分组）+
 * 题号网格·列表双视图 + 分组题目懒加载缓存。
 * 仅「按年份」Tab 激活时渲染（visible=false 时渲染 null），
 * 分组缓存因此在同首页会话内保留——与拆分前行为一致。
 * ===================================================================== */

export default function QuizYear({ visible, tab, groupResetKey, sourceKind, mode, onBeginSession }) {
  const [yearSub, setYearSub] = useState('paper')     // paper 套卷索引 | year 按年份
  const [papers, setPapers] = useState([])            // 真题套卷列表
  const [yearsData, setYearsData] = useState([])      // 年份×科目聚合
  const [yearLoading, setYearLoading] = useState(false)
  const [yearErr, setYearErr] = useState(false)
  const [groupQs, setGroupQs] = useState({})          // {key: questions[]} 懒加载缓存
  const [groupLoading, setGroupLoading] = useState({})// {key: bool}
  const [openKey, setOpenKey] = useState(null)        // 当前展开的分组 key

  /* V10：套卷总览的双视图模式（grid 网格 / list 列表） */
  const [localRecs, setLocalRecs] = useState(loadRecs)
  const [paperView, setPaperView] = useState('grid')  // grid | list

  /* 拉取真题套卷索引 + 年份×科目聚合（后端已回填 paper/year/question_no）。
     带上 source_kind：与列表口径一致，避免「教材题」Tab 下仍显示真题套卷。 */
  const loadYears = useCallback(async () => {
    setYearLoading(true); setYearErr(false)
    try {
      const sk = sourceKind !== 'all' ? sourceKind : undefined
      const [pi, yr] = await Promise.all([
        quizApi.papersIndex({ source_kind: sk }).catch(() => ({ papers: [] })),
        quizApi.years({ source_kind: sk }).catch(() => ({ years: [] })),
      ])
      setPapers(pi?.papers || [])
      setYearsData(yr?.years || [])
    } catch { setYearErr(true) }
    finally { setYearLoading(false) }
  }, [sourceKind])

  /* 懒加载某个分组的题目：套卷按 question_no 顺序，年份按科目筛选。
     统一带上 source_kind，保证「真题 / 教材题」分组视图与列表口径一致。 */
  const loadGroup = useCallback(async (key, params) => {
    if (groupQs[key]) { setOpenKey(key); return }
    setGroupLoading((s) => ({ ...s, [key]: true }))
    setOpenKey(key)
    try {
      // 套卷按题号顺序取全量。原先写死 page_size: 1000，而后端上限是 200——
      // 超限是 422 而不是截断，于是一整套题都取不回来（catch 成空数组）。
      const rows = await fetchAllPages(
        (p) => quizApi.questions({
          ...params,
          ...p,
          source_kind: sourceKind !== 'all' ? sourceKind : undefined,
          mode: 'sequential',
        }),
        { keys: ['questions'] },
      )
      setGroupQs((s) => ({ ...s, [key]: rows.map(normQ) }))
    } catch {
      setGroupQs((s) => ({ ...s, [key]: [] }))
    } finally {
      setGroupLoading((s) => ({ ...s, [key]: false }))
    }
  }, [groupQs, sourceKind])

  /* 进入「按年份」或切换来源大类时（重新）拉取套卷/年份索引，保证与来源 Tab 同口径。
     依赖与拆分前一致（tab / sourceKind）：从练习返回年份 Tab 不重复拉取。 */
  useEffect(() => { if (tab === 'year') loadYears() }, [tab, sourceKind, loadYears])
  /* 来源大类被点击（含重复点击当前项）时清空分组懒加载缓存，与原实现同点清零等价 */
  useEffect(() => { setGroupQs({}); setOpenKey(null) }, [groupResetKey])
  /* 回到首页时刷新本地作答记录（套卷网格颜色/做过次数随之更新） */
  useEffect(() => { if (visible) setLocalRecs(loadRecs()) }, [visible])

  if (!visible) return null

  /* ---------- 真题套卷 / 按年份（数据来自后端聚合，不前端猜） ---------- */
  const renderGroup = (key, title, subtitle, chips, params, count, numbered) => {
    const list = groupQs[key]
    const loading = groupLoading[key]
    const open = openKey === key
    const done = list ? list.filter((q) => localRecs[q.id]).length : 0
    const pct = list && list.length ? Math.round((done / list.length) * 100) : 0
    const noOf = (q, i) => (numbered ? (q.question_no || i + 1) : (i + 1))
    /* 依据明示：套卷/年份分组的来源口径（真题/教材题）随会话带入练习页 */
    const groupBasis = {
      title, subject: null, chapter: null, kpName: null,
      sourceKind, sourceKindLabel: SOURCE_KIND_LABEL[sourceKind] || '全部来源',
      noAnswer: false, loaded: list ? list.length : 0,
      answerableCount: null, totalCount: count, dropped: 0,
    }
    return (
      <Card key={key} className={`v3-quiz-paper ${open ? 'is-open' : ''}`}>
        <div className="v3-quiz-paper__head">
          <span className="v3-quiz-paper__year">{subtitle}</span>
          <span className="v3-quiz-paper__title" title={title}>{title}</span>
          {chips}
          <span className="v3-quiz-paper__meta">
            <strong>{count}</strong> 题
            {list ? ` · 已做 ${done}/${list.length} · ${pct}%` : ''}
          </span>
          <Button
            size="sm"
            variant={list ? 'tonal' : 'filled'}
            icon={list ? <BookOpen size={14} /> : <FileText size={14} />}
            onClick={() => loadGroup(key, params)}
          >
            {list ? '开始练习' : '载入题号'}
          </Button>
          {list && list.length > 0 && (
            <Progress className="v3-quiz-paper__bar" value={pct} />
          )}
        </div>

        {loading && (
          <div className="v3-quiz-paper__body">
            <LoadingState text="正在载入题目…" />
          </div>
        )}

        {open && list && list.length > 0 && (
          <div className="v3-quiz-paper__body">
            {paperView === 'grid' ? (
              <div className="v3-quiz-grid">
                {list.map((q, i) => {
                  const r = localRecs[q.id]
                  let cls = 'v3-quiz-cell'
                  if (r) cls += r.correct ? ' is-ok' : ' is-bad'
                  return (
                    <button key={q.id} type="button" className={cls}
                      title={`第 ${noOf(q, i)} 题${r ? ` · 做过 ${r.times} 次` : ' · 未做'}`}
                      onClick={() => onBeginSession(title, list, mode, i, false, groupBasis)}>
                      {noOf(q, i)}
                      {r?.times > 0 && <span className="v3-quiz-cell__times">{r.times}</span>}
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="v3-quiz-rows">
                {list.map((q, i) => {
                  const r = localRecs[q.id]
                  return (
                    <button key={q.id} type="button" className="v3-quiz-row"
                      onClick={() => onBeginSession(title, list, mode, i, false, groupBasis)}>
                      <span className="v3-quiz-row__no">{noOf(q, i)}</span>
                      <span className={`v3-quiz-row__dot ${r ? (r.correct ? 'is-ok' : 'is-bad') : ''}`} />
                      <span className="v3-quiz-row__text">{q.content}</span>
                      <span className="v3-quiz-row__meta">{r ? `做过 ${r.times} 次` : '未做'}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {open && list && list.length === 0 && !loading && (
          <div className="v3-quiz-paper__body">
            <Empty
              icon={<BookOpen size={24} />}
              title="当前筛选条件下暂无题目"
              text="换个套卷或年份试试"
            />
          </div>
        )}
      </Card>
    )
  }

  const renderYear = () => {
    if (yearLoading) {
      return <Card><LoadingState text="正在载入真题套卷与年份索引…" /></Card>
    }
    if (yearErr) {
      return (
        <Card>
          <Empty
            icon={<RefreshCw size={24} />}
            title="套卷/年份索引加载失败"
            text="无法读取 /api/quiz/papers-index 或 /api/quiz/years。"
            action={<Button variant="tonal" icon={<RefreshCw size={15} />} onClick={loadYears}>重新加载</Button>}
          />
        </Card>
      )
    }
    const yearTotal = yearsData.reduce((a, y) => a + (y.total || 0), 0)
    return (
      <div className="v3-quiz-year">
        <div className="v3-quiz-bar">
          <Segmented
            ariaLabel="真题索引视图"
            value={yearSub}
            onChange={setYearSub}
            options={[
              { value: 'paper', label: `真题套卷 (${papers.length})`, icon: <FileText size={15} /> },
              { value: 'year', label: `按年份 (${yearsData.length})`, icon: <Calendar size={15} /> },
            ]}
          />
          <Segmented
            ariaLabel="套卷展示方式"
            value={paperView}
            onChange={setPaperView}
            options={[
              { value: 'grid', label: '题号网格', icon: <LayoutGrid size={14} /> },
              { value: 'list', label: '列表', icon: <List size={14} /> },
            ]}
          />
        </div>

        {yearSub === 'paper' && (
          papers.length
            ? papers.map((p) => renderGroup(
                `paper::${p.paper}`, p.paper, p.year_label || '套卷',
                Object.entries(p.subjects || {}).slice(0, 3).map(([s, c]) => (
                  <span key={s} className="v3-quiz-tag">{s} <strong>{c}</strong></span>
                )),
                { paper: p.paper }, p.count, true))
            : (
              <Card>
                <Empty
                  icon={<FileText size={24} />}
                  title="暂无套卷"
                  text={sourceKind === 'textbook'
                    ? '「教材题」按章节组织、通常无套卷归属；请切到「按知识点」按章节刷，或切「历年真题」查看套卷。'
                    : '当前来源下还没有可归卷的套卷。'}
                />
              </Card>
            )
        )}

        {yearSub === 'year' && (
          yearsData.length
            ? yearsData.map((y) => renderGroup(
                `year::${y.year}`, `${y.year} 年真题`, String(y.year),
                Object.entries(y.subjects || {}).slice(0, 4).map(([s, c]) => (
                  <span key={s} className="v3-quiz-tag">{s} <strong>{c}</strong></span>
                )),
                { year: y.year }, y.total, false))
            : (
              <Card>
                <Empty
                  icon={<Calendar size={24} />}
                  title="暂无按年份数据"
                  text={sourceKind === 'textbook'
                    ? '「教材题」一般无真题年份；请切到「历年真题」按年份浏览。'
                    : '只有能可靠解析年份的真题才会出现在这里。'}
                />
              </Card>
            )
        )}

        <p className="v3-quiz-note">
          口径说明（诚实）：套卷名与年份由后端从真题文档名回填（paper / year 列），题号 question_no 为套卷内录入顺序号（非原卷题号）；
          「按年份」仅覆盖能无歧义解析年份的真题子集（共 {yearTotal} 题），不伪造年份。
          题格对错与「做过次数」为本地单机记录（localStorage）。点击「载入题号」按需拉取该组全部题目。
        </p>
      </div>
    )
  }

  return renderYear()
}
