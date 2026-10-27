import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { quizApi } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import {
  Button, Chip, Empty, IconButton, PageHeader, Segmented, Skeleton, Tile, toastErr, toastOk,
} from '../ui'
import {
  ArrowRight, Calendar, ChevronRight, FileText, Info, Layers, RefreshCw, Target,
} from '../icons'
import '../styles/pages.css'

function fmtYear(y) {
  return y ? `${y} 年` : '年份未标注'
}

const paperHref = (p) => (
  p.year
    ? `/exam/${p.year}/${encodeURIComponent(p.paper)}`
    : `/exam/paper/${encodeURIComponent(p.paper)}`
)

export default function ExamCenter() {
  const { isAdmin, user, status } = useAuth()
  const [searchParams] = useSearchParams()
  const urlSubject = searchParams.get('subject') || ''
  const [papers, setPapers] = useState([])
  const [years, setYears] = useState([])
  const [subjects, setSubjects] = useState([])
  const [subject, setSubject] = useState(urlSubject)
  const [tab, setTab] = useState('year')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const subjectsLoaded = useRef(false)

  /* 全局学科选择器联动：URL ?subject= 变化时同步本地筛选 */
  useEffect(() => {
    setSubject(urlSubject)
  }, [urlSubject])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [p, y, s] = await Promise.all([
        quizApi.papersIndex({ source_kind: 'exam', subject: subject || undefined }),
        quizApi.years({ source_kind: 'exam' }),
        // /quiz/subjects 带个人错题数，访客不可读；访客的科目筛选项从索引元数据派生
        (!user || subjectsLoaded.current) ? Promise.resolve(null) : quizApi.subjects(),
      ])
      const paperList = Array.isArray(p?.papers) ? p.papers : []
      const yearList = Array.isArray(y?.years) ? y.years : []
      setPapers(paperList)
      setYears(yearList)
      if (s) {
        const items = Array.isArray(s?.items) ? s.items : Array.isArray(s) ? s : []
        setSubjects(items.map((x) => x.subject).filter(Boolean))
        subjectsLoaded.current = true
      } else if (!user) {
        const names = new Set()
        yearList.forEach((row) => Object.keys(row.subjects || {}).forEach((name) => names.add(name)))
        paperList.forEach((row) => Object.keys(row.subjects || {}).forEach((name) => names.add(name)))
        setSubjects([...names].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN')))
        subjectsLoaded.current = true
      }
      return true
    } catch (e) {
      setError(e?.message || '真题索引加载失败')
      return false
    } finally {
      setLoading(false)
    }
  }, [subject, user])

  useEffect(() => {
    if (status === 'loading') return
    load()
  }, [status, load])

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

  return (
    <div className="v3-stack" style={{ gap: 20 }}>
      <PageHeader
        eyebrow="REAL EXAM · 历年真题"
        title="真题中心"
        sub="按年份或套卷进入整卷练习 · 链接可收藏、可分享、刷新不丢上下文"
        actions={(
          <>
            <IconButton label="刷新真题索引" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading} />
            <Link className="v3-btn v3-btn--tonal" to="/quiz">去刷题中心 <ArrowRight size={15} /></Link>
          </>
        )}
      />

      <section className="v3-exam-hero">
        <div className="v3-exam-hero__glow" aria-hidden="true" />
        <div className="v3-exam-hero__main">
          <span className="v3-eyebrow"><Target size={13} /> 原卷节奏</span>
          <h2>把每一套真题，<br />按原卷节奏做完。</h2>
          <p>年份索引用于按年刷整套；套卷索引保留原卷题序。答错自动进入错题库。</p>
        </div>
        <div className="v3-exam-hero__stats">
          {[
            ['套卷', totals.papers],
            ['年份', totals.years],
            ['题数', totals.questions],
          ].map(([label, value]) => (
            <div key={label} className="v3-exam-hero__stat">
              <b>{value}</b>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </section>

      <div className="v3-exam-toolbar">
        <Segmented
          ariaLabel="真题视图"
          value={tab}
          onChange={setTab}
          options={[
            { value: 'year', label: '按年份', icon: <Calendar size={15} /> },
            { value: 'paper', label: '按套卷', icon: <Layers size={15} /> },
          ]}
        />
        <div className="v3-exam-chips" role="group" aria-label="按科目筛选">
          <Chip active={subject === ''} onClick={() => setSubject('')}>全部科目</Chip>
          {subjects.map((s) => (
            <Chip key={s} active={subject === s} onClick={() => setSubject(subject === s ? '' : s)}>{s}</Chip>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="v3-exam-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="v3-card" style={{ padding: 22 }}><Skeleton height={140} /></div>
          ))}
        </div>
      ) : error ? (
        <div className="v3-card" style={{ padding: 36 }}>
          <Empty
            icon={<Info size={26} />}
            title="真题索引加载失败"
            text={error}
            action={<Button variant="tonal" onClick={load}>重新加载</Button>}
          />
        </div>
      ) : tab === 'year' ? (
        filteredYears.length ? (
          <div className="v3-exam-grid">
            {filteredYears.map((y) => (
              <Link className="v3-exam-card" key={y.year} to={`/exam/year/${y.year}`}>
                <div className="v3-exam-card__top">
                  <span className="v3-exam-card__year">{y.year}</span>
                  <span className="v3-badge">{y.total} 题</span>
                </div>
                <div className="v3-exam-card__title">{fmtYear(y.year)}真题</div>
                <div className="v3-exam-card__chips">
                  {Object.entries(y.subjects || {}).slice(0, 4).map(([s, n]) => (
                    <span key={s} className="v3-exam-tag">{s} {n}</span>
                  ))}
                </div>
                <span className="v3-exam-card__go">{!user ? '登录后练习' : '进入该年份'} <ChevronRight size={14} /></span>
              </Link>
            ))}
          </div>
        ) : (
          <div className="v3-card" style={{ padding: 40 }}>
            <Empty
              icon={<Calendar size={26} />}
              title="还没有可用的真题年份"
              text="题目入库时会从真题文档名解析年份。导入真题后，这里会自动按年份聚合。"
              action={isAdmin
                ? <Link className="v3-btn v3-btn--filled" to="/admin/quiz-bank">去题库管理</Link>
                : <Link className="v3-btn v3-btn--tonal" to="/quiz">去刷题中心</Link>}
            />
          </div>
        )
      ) : (
        papers.length ? (
          <div className="v3-exam-grid">
            {papers.map((p) => (
              <Link className="v3-exam-card" key={p.paper} to={paperHref(p)}>
                <div className="v3-exam-card__top">
                  <span className="v3-exam-card__year">{p.year_label || fmtYear(p.year)}</span>
                  <span className="v3-badge">{p.count} 题</span>
                </div>
                <div className="v3-exam-card__title" title={p.paper}>{p.paper}</div>
                <div className="v3-exam-card__chips">
                  {Object.entries(p.subjects || {}).slice(0, 4).map(([s, n]) => (
                    <span key={s} className="v3-exam-tag">{s} {n}</span>
                  ))}
                </div>
                <span className="v3-exam-card__go">开始这套 <ChevronRight size={14} /></span>
              </Link>
            ))}
          </div>
        ) : (
          <div className="v3-card" style={{ padding: 40 }}>
            <Empty
              icon={<FileText size={26} />}
              title="当前条件下没有真题套卷"
              text="套卷名来自真题文档名回填；如果只导入教材题，请到刷题中心按章节练习。"
              action={<Link className="v3-btn v3-btn--filled" to="/quiz">去刷题中心</Link>}
            />
          </div>
        )
      )}

      <Tile variant="well" className="v3-exam-note">
        <Info size={17} />
        <p>
          <b>口径说明：</b>套卷名与年份由后端从真题文档名回填，「题号」是套卷内录入顺序号，不是原卷题号。
          年份索引只覆盖能可靠解析年份的真题子集，不伪造年份。
        </p>
      </Tile>
    </div>
  )
}
