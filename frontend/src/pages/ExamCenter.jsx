import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Empty, toastOk, toastErr } from '../components/UI'
import { LoadingState, ErrorState } from '../components/States'
import { quizApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Calendar, FileText, RefreshCw, Target, ChevronRight, Layers } from '../components/Icon'
import './ExamCenter.css'

/* ============================================================
   真题中心（/exam）
   - 独立一级入口：套卷 / 年份两种索引，全部可深链分享
   - 点年份 → /exam/year/:year；点套卷 → /exam/:year/:paper
   - 所有统计来自 /api/quiz/papers-index 与 /api/quiz/years，不前端猜
   ============================================================ */

function fmtYear(y) {
  return y ? `${y} 年` : '年份未标注'
}

export default function ExamCenter() {
  const { isAdmin } = useAuth()
  const [papers, setPapers] = useState([])
  const [years, setYears] = useState([])
  const [subjects, setSubjects] = useState([])
  const [subject, setSubject] = useState('')
  const [tab, setTab] = useState('year') // year | paper
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [p, y, s] = await Promise.all([
        quizApi.papersIndex({ source_kind: 'exam', subject: subject || undefined }),
        quizApi.years({ source_kind: 'exam' }),
        subjects.length ? Promise.resolve(null) : quizApi.subjects(),
      ])
      setPapers(Array.isArray(p?.papers) ? p.papers : [])
      setYears(Array.isArray(y?.years) ? y.years : [])
      if (s) {
        const items = Array.isArray(s?.items) ? s.items : Array.isArray(s) ? s : []
        setSubjects(items.map((x) => x.subject).filter(Boolean))
      }
      return true
    } catch (e) {
      setError(e?.message || '真题索引加载失败')
      return false
    } finally {
      setLoading(false)
    }
  }, [subject, subjects.length])

  useEffect(() => { load() }, [load])

  /* 手动刷新：给出成功/失败提示，避免用户点完不知道有没有生效 */
  const refresh = async () => {
    const ok = await load()
    if (ok) toastOk('真题索引已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  const totals = useMemo(() => ({
    papers: papers.length,
    years: years.length,
    questions: years.reduce((n, y) => n + (Number(y.total) || 0), 0),
  }), [papers, years])

  const filteredYears = useMemo(
    () => (subject ? years.filter((y) => (y.subjects || {})[subject]) : years),
    [years, subject]
  )

  const paperHref = (p) => (
    p.year
      ? `/exam/${p.year}/${encodeURIComponent(p.paper)}`
      : `/exam/paper/${encodeURIComponent(p.paper)}`
  )

  return (
    <div className="page ec-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">真题中心</h1>
          <p className="page-sub">按年份或套卷进入整卷练习 · 链接可收藏、可分享、刷新不丢上下文</p>
        </div>
        <div className="page-actions row">
          <button className="btn ghost" onClick={refresh} disabled={loading}>
            <RefreshCw size={14} /> {loading ? '加载中…' : '刷新'}
          </button>
          <Link className="btn ghost" to="/quiz">去刷题中心</Link>
        </div>
      </div>

      <div className="ec-hero">
        <div className="ec-hero-main">
          <div className="ec-eyebrow">REAL EXAM · 历年真题</div>
          <div className="ec-hero-title">把每一套真题，按原卷节奏做完</div>
          <div className="ec-hero-desc">
            年份索引用于按年刷整套；套卷索引保留原卷题序。点进任意一套后可直接作答，答错自动进入错题库。
          </div>
        </div>
        <div className="ec-stats">
          <div><b>{totals.papers}</b><span>套卷</span></div>
          <div><b>{totals.years}</b><span>年份</span></div>
          <div><b>{totals.questions}</b><span>题数</span></div>
        </div>
      </div>

      <div className="ec-toolbar">
        <div className="ec-tabs" role="tablist" aria-label="真题视图">
          <button role="tab" aria-selected={tab === 'year'} className={`ec-tab ${tab === 'year' ? 'on' : ''}`} onClick={() => setTab('year')}>
            <Calendar size={14} /> 按年份
          </button>
          <button role="tab" aria-selected={tab === 'paper'} className={`ec-tab ${tab === 'paper' ? 'on' : ''}`} onClick={() => setTab('paper')}>
            <Layers size={14} /> 按套卷
          </button>
        </div>
        <div className="ec-chips" role="group" aria-label="按科目筛选">
          <button className={`chip ${subject === '' ? 'active' : ''}`} onClick={() => setSubject('')}>全部科目</button>
          {subjects.map((s) => (
            <button key={s} className={`chip ${subject === s ? 'active' : ''}`} onClick={() => setSubject(subject === s ? '' : s)}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {loading && <LoadingState text="正在读取真题索引…" rows={4} />}
      {!loading && error && (
        <ErrorState title="真题索引加载失败" message={error} onRetry={load} retryText="重新加载" />
      )}
      {!loading && !error && tab === 'year' && (
        filteredYears.length ? (
          <div className="ec-grid">
            {filteredYears.map((y) => (
              <Link className="ec-card" key={y.year} to={`/exam/year/${y.year}`}>
                <div className="ec-card-top">
                  <span className="ec-year">{y.year}</span>
                  <span className="ec-count">{y.total} 题</span>
                </div>
                <div className="ec-card-title">{fmtYear(y.year)}真题</div>
                <div className="ec-chiprow">
                  {Object.entries(y.subjects || {}).slice(0, 4).map(([s, n]) => (
                    <span key={s} className="chip small">{s} {n}</span>
                  ))}
                </div>
                <span className="ec-go">进入该年份 <ChevronRight size={13} /></span>
              </Link>
            ))}
          </div>
        ) : (
          <Empty
            icon={<Calendar size={40} />}
            title="还没有可用的真题年份"
            desc="题目入库时会从真题文档名解析年份。导入真题后，这里会自动按年份聚合。"
            action={isAdmin ? <Link className="btn primary" to="/admin/quiz-bank">去题库管理</Link> : null}
          />
        )
      )}

      {!loading && !error && tab === 'paper' && (
        papers.length ? (
          <div className="ec-grid">
            {papers.map((p) => (
              <Link className="ec-card" key={p.paper} to={paperHref(p)}>
                <div className="ec-card-top">
                  <span className="ec-year">{p.year_label || fmtYear(p.year)}</span>
                  <span className="ec-count">{p.count} 题</span>
                </div>
                <div className="ec-card-title" title={p.paper}>{p.paper}</div>
                <div className="ec-chiprow">
                  {Object.entries(p.subjects || {}).slice(0, 4).map(([s, n]) => (
                    <span key={s} className="chip small">{s} {n}</span>
                  ))}
                </div>
                <span className="ec-go">开始这套 <ChevronRight size={13} /></span>
              </Link>
            ))}
          </div>
        ) : (
          <Empty
            icon={<FileText size={40} />}
            title="当前条件下没有真题套卷"
            desc="套卷名来自真题文档名回填；如果只导入教材题，请到刷题中心按章节练习。"
            action={<Link className="btn primary" to="/quiz">去刷题中心</Link>}
          />
        )
      )}

      <div className="ec-note">
        <Target size={15} />
        <div>
          <b>口径说明：</b>套卷名与年份由后端从真题文档名回填，「题号」是套卷内录入顺序号，不是原卷题号。
          年份索引只覆盖能可靠解析年份的真题子集，不伪造年份。
        </div>
      </div>
    </div>
  )
}
