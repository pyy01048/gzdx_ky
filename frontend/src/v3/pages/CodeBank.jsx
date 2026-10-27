import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { request } from '../../api/client'
import {
  AnimatedNumber, Badge, Button, Card, CardHead, Chip, Dialog, Empty, Field, IconButton,
  Input, PageHeader, Skeleton, Tabs, Tile, toastErr, toastOk,
} from '../ui'
import {
  Activity, AlertCircle, ChevronRight, FileText, InfoCircle, Layers, Map, Plus,
  RefreshCw, Search, Star, Tag, Trophy, X,
} from '../icons'
import '../styles/codebank-v3.css'

/* ==========================================================================
   复试代码题库（Aurora v3）
   数据源：
     GET  /codebank/subjects          科目模块（name / direction / question_count）
     GET  /codebank/panorama          知识点全景（tag / subject / total / avg_frequency / hot）
     GET  /codebank/questions         题库列表（q / difficulty / tag / min_frequency）
     GET  /codebank/questions/{id}    题目详情
     GET  /codebank/exam-strategy     考频分析（top_questions / by_subject）
     POST /codebank/subjects          添加科目 { name, direction }
   ========================================================================== */

const DIFF_CN = { easy: '简单', medium: '中等', hard: '困难' }
const DIFF_TONE = { easy: 'success', medium: 'warning', hard: 'danger' }

const TABS = [
  { value: 'panorama', label: '知识点全景', icon: <Map size={15} /> },
  { value: 'list', label: '题库列表', icon: <FileText size={15} /> },
  { value: 'strategy', label: '考频分析', icon: <Activity size={15} /> },
]

/* 后端可能返回 null / 缺键，入口统一归一 */
const toArr = (v) => (Array.isArray(v) ? v : [])
const toObj = (v) => (v && typeof v === 'object' ? v : null)

/** 考频星级：实心 + 空心补足 5 星 */
function Stars({ n, className = '' }) {
  const filled = Math.min(5, Math.max(0, Math.round(Number(n) || 0)))
  return (
    <span className={`cb3-stars ${className}`} aria-label={`考频 ${filled} / 5`}>
      <b>{'★'.repeat(filled)}</b>
      <i>{'☆'.repeat(5 - filled)}</i>
    </span>
  )
}

/** 按语言返回入门模板（与旧版一致：题库不存逐题模板） */
function template(detail, lang) {
  const skeletons = {
    'C++': '#include <bits/stdc++.h>\nusing namespace std;\nint main() {\n    // 在此实现\n    return 0;\n}',
    Python: 'def solve():\n    # 在此实现\n    pass\n\nif __name__ == "__main__":\n    print(solve())',
    C: '#include <stdio.h>\nint main() {\n    /* 在此实现 */\n    return 0;\n}',
    Java: 'public class Main {\n    public static void main(String[] args) {\n        // 在此实现\n    }\n}',
  }
  return skeletons[lang] || '// 选择语言'
}

function StatTile({ icon, label, value, unit, hint }) {
  return (
    <Tile span={4} className="cb3-stat">
      <span className="v3-tile__label">{icon}{label}</span>
      <span className="v3-tile__value">
        {value == null ? '—' : <AnimatedNumber value={value} />}
        {value == null ? null : <em>{unit}</em>}
      </span>
      <span className="v3-tile__hint">{hint}</span>
    </Tile>
  )
}

export default function CodeBank() {
  const [tab, setTab] = useState('panorama') // panorama | list | strategy
  const [subjects, setSubjects] = useState([])
  const [subject, setSubject] = useState('')
  const [pano, setPano] = useState(null)
  const [list, setList] = useState(null)
  const [strategy, setStrategy] = useState(null)
  const [filters, setFilters] = useState({ q: '', difficulty: '', tag: '', min_frequency: 0 })
  const [showAdd, setShowAdd] = useState(false)
  const [newSub, setNewSub] = useState({ name: '', direction: '' })
  const [adding, setAdding] = useState(false)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [lang, setLang] = useState('')

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  /* 手动刷新状态机：null → queued → running → 结算 */
  const pendingRefresh = useRef(null)
  const addNameRef = useRef(null)
  /* 详情请求序号：关闭/切换题目后丢弃过期响应，避免弹层被迟到响应重新打开 */
  const detailSeq = useRef(0)

  const loadSubjects = useCallback(() => {
    request('/codebank/subjects')
      .then((d) => setSubjects(toArr(d)))
      .catch(() => {})
  }, [])

  useEffect(() => { loadSubjects() }, [loadSubjects])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    const fail = (e) => { if (alive) setError(e?.message || '请求失败') }
    const done = () => { if (alive) setLoading(false) }

    if (tab === 'panorama') {
      setPano(null)
      request('/codebank/panorama', { params: subject ? { subject } : {} })
        .then((d) => {
          if (alive) setPano(toObj(d) ? { ...d, items: toArr(d.items) } : { items: [] })
        })
        .catch(fail)
        .finally(done)
    } else if (tab === 'strategy') {
      setStrategy(null)
      request('/codebank/exam-strategy')
        .then((d) => {
          if (!alive) return
          setStrategy(toObj(d)
            ? { ...d, top_questions: toArr(d.top_questions), by_subject: toArr(d.by_subject) }
            : { top_questions: [], by_subject: [] })
        })
        .catch(fail)
        .finally(done)
    } else {
      setList(null)
      const params = {}
      if (subject) params.subject = subject
      if (filters.q) params.q = filters.q
      if (filters.difficulty) params.difficulty = filters.difficulty
      if (filters.tag) params.tag = filters.tag
      if (filters.min_frequency) params.min_frequency = filters.min_frequency
      request('/codebank/questions', { params })
        .then((d) => {
          if (alive) setList(toObj(d) ? { ...d, items: toArr(d.items) } : { items: [] })
        })
        .catch(fail)
        .finally(done)
    }
    return () => { alive = false }
  }, [tab, subject, filters, reloadKey])

  useEffect(() => {
    if (!pendingRefresh.current) return
    if (loading) {
      pendingRefresh.current = 'running'
      return
    }
    if (pendingRefresh.current !== 'running') return
    pendingRefresh.current = null
    if (error) toastErr(`刷新失败：${error}`)
    else toastOk('题库数据已刷新')
  }, [loading, error])

  const hasFilters = Boolean(filters.q || filters.difficulty || filters.tag || filters.min_frequency)

  const totalQuestions = useMemo(
    () => subjects.reduce((n, s) => n + (Number(s.question_count) || 0), 0),
    [subjects],
  )

  const viewCount = tab === 'panorama'
    ? (pano ? pano.items.length : null)
    : tab === 'strategy'
      ? (strategy ? strategy.top_questions.length : null)
      : (list ? list.items.length : null)

  const viewMeta = {
    panorama: { label: '考点标签', unit: '个', hint: '按题目标签汇总的全景' },
    list: { label: '当前题目', unit: '道', hint: hasFilters ? '当前筛选结果' : '全部已录入题目' },
    strategy: { label: '高频题 TOP', unit: '道', hint: '按考频排序的前十题' },
  }[tab]

  const openDetail = (id) => {
    const seq = ++detailSeq.current
    setDetail(null)
    setDetailLoading(true)
    setLang('')
    request('/codebank/questions/' + id)
      .then((d) => {
        if (seq !== detailSeq.current) return
        setDetail(toObj(d) ? {
          ...d,
          tags: toArr(d.tags),
          examples: toArr(d.examples),
          languages: toArr(d.languages),
          appear_years: toArr(d.appear_years),
        } : null)
        setLang(toArr(d?.languages)[0] || '')
      })
      .catch((e) => {
        if (seq !== detailSeq.current) return
        setDetail(null)
        toastErr(`题目详情加载失败：${e?.message || '请求失败'}`)
      })
      .finally(() => {
        if (seq === detailSeq.current) setDetailLoading(false)
      })
  }

  const closeDetail = () => {
    detailSeq.current += 1
    setDetail(null)
    setDetailLoading(false)
    setLang('')
  }

  const addSubject = () => {
    if (!newSub.name.trim()) {
      toastErr('请填写科目名称后再添加')
      addNameRef.current?.focus()
      return
    }
    setAdding(true)
    request('/codebank/subjects', { method: 'POST', body: newSub })
      .then((r) => {
        if (r?.added) {
          loadSubjects()
          setNewSub({ name: '', direction: '' })
          setShowAdd(false)
          toastOk('科目已添加')
          setReloadKey((k) => k + 1)
        } else {
          toastErr(r?.message || r?.reason || '科目已存在')
        }
      })
      .catch((e) => toastErr(`添加失败：${e?.message || '请求失败'}`))
      .finally(() => setAdding(false))
  }

  const refresh = () => {
    pendingRefresh.current = 'queued'
    setReloadKey((k) => k + 1)
  }

  const clearFilters = () => setFilters({ q: '', difficulty: '', tag: '', min_frequency: 0 })

  const maxSubjectCount = useMemo(() => {
    const counts = (strategy?.by_subject || []).map((s) => Number(s.count) || 0)
    return Math.max(1, ...counts)
  }, [strategy])

  const header = (
    <PageHeader
      eyebrow="CODE BANK · 复试题库"
      title="复试代码题库"
      sub={subjects.length
        ? `${subjects.length} 个科目：${subjects.slice(0, 6).map((s) => s.name).join('、')}${subjects.length > 6 ? ' 等' : ''} · LeetCode 式刷题 · 知识点全景 · 考频分析`
        : '当前还没有科目，添加后即可按科目整理复试题'}
      actions={(
        <>
          <IconButton
            label="刷新题库数据"
            icon={<RefreshCw size={17} />}
            onClick={refresh}
            disabled={loading}
          />
          <Button variant="gradient" icon={<Plus size={16} />} onClick={() => setShowAdd(true)}>
            添加科目
          </Button>
        </>
      )}
    />
  )

  return (
    <div className="v3-stack v3-codebank">
      {header}

      <div className="v3-bento">
        <StatTile
          icon={<Layers size={15} />}
          label="科目模块"
          value={subjects.length}
          unit="个"
          hint="来自题库科目接口"
        />
        <StatTile
          icon={<FileText size={15} />}
          label="收录题目"
          value={totalQuestions}
          unit="道"
          hint="各科目题数之和"
        />
        <StatTile
          icon={<Trophy size={15} />}
          label={viewMeta.label}
          value={viewCount}
          unit={viewMeta.unit}
          hint={loading ? '正在读取…' : viewMeta.hint}
        />
      </div>

      {/* 科目 */}
      <Card className="cb3-subject-card">
        <CardHead
          icon={<Layers size={17} />}
          title="科目模块"
          sub="点击切换科目；列表、全景与考频分析共用该筛选"
          actions={<Badge tone="outline">{subjects.length} 个科目</Badge>}
        />
        <div className="cb3-subjects">
          <Chip active={subject === ''} onClick={() => setSubject('')}>
            全部科目
            {subjects.length ? <span className="cb3-chip-n">{totalQuestions}</span> : null}
          </Chip>
          {subjects.map((s) => (
            <Chip
              key={s.id ?? s.name}
              active={subject === s.name}
              onClick={() => setSubject(s.name)}
              title={`${s.direction || '未标注方向'} · ${s.question_count ?? 0} 题`}
            >
              {s.name}
              <span className="cb3-chip-n">{s.question_count ?? 0}</span>
            </Chip>
          ))}
          <Chip className="cb3-chip-add" onClick={() => setShowAdd(true)} title="添加科目模块">
            <Plus size={13} />
            添加科目
          </Chip>
        </div>
      </Card>

      <Tabs
        ariaLabel="题库视图"
        options={TABS}
        value={tab}
        onChange={setTab}
      />

      {/* 加载 / 失败 */}
      {loading ? (
        <Card className="cb3-state-card">
          <CardHead
            icon={<Activity size={17} />}
            title={TABS.find((t) => t.value === tab)?.label}
            sub="正在读取代码题库…"
          />
          {tab === 'panorama' ? (
            <div className="cb3-pano-grid">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div className="cb3-pano-card is-skeleton" key={i}>
                  <Skeleton height={16} width="48%" />
                  <Skeleton height={11} width="68%" style={{ marginTop: 12 }} />
                  <Skeleton height={12} width="42%" style={{ marginTop: 14 }} />
                  <Skeleton height={11} width="80%" style={{ marginTop: 14 }} />
                </div>
              ))}
            </div>
          ) : (
            <div className="cb3-skeleton-list">
              {[0, 1, 2, 3, 4].map((i) => (
                <div className="cb3-skel-row" key={i}>
                  <Skeleton height={12} width={30} />
                  <Skeleton height={13} width={`${42 + (i % 3) * 14}%`} />
                  <Skeleton height={12} width={70} />
                  <Skeleton height={12} width={80} />
                </div>
              ))}
            </div>
          )}
        </Card>
      ) : error ? (
        <Card className="cb3-state-card">
          <Empty
            icon={<AlertCircle size={26} />}
            title="代码题库加载失败"
            text={error}
            action={(
              <Button variant="tonal" icon={<RefreshCw size={16} />} onClick={refresh}>
                重新加载
              </Button>
            )}
          />
        </Card>
      ) : null}

      {/* 知识点全景 */}
      {!loading && !error && tab === 'panorama' && pano ? (
        <Card className="cb3-pano-card-wrap">
          <CardHead
            icon={<Map size={17} />}
            title="知识点全景"
            sub={pano.items.length
              ? `${subject || '全部科目'} · ${pano.items.length} 个考点，点击进入对应题目`
              : '按题目标签自动汇总的考点视图'}
            actions={<Badge tone={subject ? 'primary' : 'outline'}>{subject || '全部科目'}</Badge>}
          />
          {pano.items.length === 0 ? (
            <Empty
              icon={<Map size={26} />}
              title="还没有知识点数据"
              text="先添加科目并录入题目，系统会按标签自动汇总成知识点全景。"
              action={<Button variant="gradient" icon={<Plus size={16} />} onClick={() => setShowAdd(true)}>添加科目</Button>}
            />
          ) : (
            <div className="cb3-pano-grid">
              {pano.items.map((it) => (
                <button
                  type="button"
                  key={it.tag}
                  className="cb3-pano-card"
                  onClick={() => {
                    setFilters((f) => ({ ...f, tag: it.tag }))
                    setTab('list')
                  }}
                >
                  <span className="cb3-pano-top">
                    <span className="cb3-pano-tag">{it.tag}</span>
                    <Badge tone="outline">{it.total ?? 0} 题</Badge>
                  </span>
                  <span className="cb3-pano-subject">{it.subject || '未分类'}</span>
                  <span className="cb3-pano-stars">
                    <Stars n={it.avg_frequency} />
                    <span>均考频 {Math.round((Number(it.avg_frequency) || 0) * 10) / 10}</span>
                  </span>
                  {it.hot ? (
                    <span className="cb3-pano-hot" title={it.hot.title}>
                      <Star size={13} />
                      最热：{it.hot.title}
                    </span>
                  ) : null}
                  <span className="cb3-pano-go">
                    查看题目
                    <ChevronRight size={14} />
                  </span>
                </button>
              ))}
            </div>
          )}
        </Card>
      ) : null}

      {/* 题库列表 */}
      {!loading && !error && tab === 'list' && list ? (
        <Card className="cb3-list-card">
          <CardHead
            icon={<FileText size={17} />}
            title="题库列表"
            sub={`${list.items.length} 道题${subject ? ` · ${subject}` : ''}${hasFilters ? ' · 已应用筛选' : ''}`}
            actions={<Badge tone={hasFilters ? 'primary' : 'outline'}>{hasFilters ? '筛选中' : '全部题目'}</Badge>}
          />

          <div className="cb3-filters">
            <div className="cb3-search">
              <Input
                icon={<Search size={16} />}
                placeholder="搜索题目标题 / 题面…"
                aria-label="搜索题目标题或题面"
                value={filters.q}
                onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
              />
            </div>
            <div className="cb3-filter-group">
              <span className="cb3-filter-label">难度</span>
              {[['', '全部'], ['easy', '简单'], ['medium', '中等'], ['hard', '困难']].map(([v, l]) => (
                <Chip
                  key={v || 'all'}
                  active={filters.difficulty === v}
                  onClick={() => setFilters((f) => ({ ...f, difficulty: v }))}
                >
                  {l}
                </Chip>
              ))}
            </div>
            <div className="cb3-filter-group">
              <span className="cb3-filter-label">考频</span>
              {[0, 4, 5].map((n) => (
                <Chip
                  key={n}
                  active={filters.min_frequency === n}
                  onClick={() => setFilters((f) => ({ ...f, min_frequency: n }))}
                >
                  {n === 0 ? '不限' : `≥ ${'★'.repeat(n)}`}
                </Chip>
              ))}
            </div>
            {filters.tag ? (
              <Chip
                active
                gradient
                icon={<Tag size={13} />}
                onClick={() => setFilters((f) => ({ ...f, tag: '' }))}
                title="清除标签筛选"
              >
                {filters.tag}
                <X size={13} />
              </Chip>
            ) : null}
            {hasFilters ? (
              <Button variant="text" size="sm" onClick={clearFilters}>清空筛选</Button>
            ) : null}
          </div>

          {list.items.length === 0 ? (
            <Empty
              icon={<FileText size={26} />}
              title={hasFilters ? '当前筛选下没有题目' : '题库还是空的'}
              text={hasFilters
                ? '清空关键词 / 难度 / 考频后即可看到全部题目。'
                : '添加科目后即可开始整理复试题；题目录入后这里会自动按考点与考频汇总。'}
              action={hasFilters
                ? <Button variant="tonal" onClick={clearFilters}>清空筛选</Button>
                : <Button variant="gradient" icon={<Plus size={16} />} onClick={() => setShowAdd(true)}>添加科目</Button>}
            />
          ) : (
            <div className="cb3-table-wrap">
              <table className="cb3-table">
                <thead>
                  <tr>
                    <th className="cb3-col-id">#</th>
                    <th>题目</th>
                    <th className="cb3-col-subject">科目</th>
                    <th className="cb3-col-diff">难度</th>
                    <th className="cb3-col-freq">考频</th>
                    <th className="cb3-col-years">年份</th>
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((q) => (
                    <tr
                      key={q.id}
                      onClick={() => openDetail(q.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          openDetail(q.id)
                        }
                      }}
                      tabIndex={0}
                      role="button"
                      aria-label={`查看题目详情：${q.title}`}
                    >
                      <td className="cb3-col-id cb3-id">{q.id}</td>
                      <td>
                        <span className="cb3-q-title">{q.title}</span>
                        <span className="cb3-q-meta">
                          <span>{q.subject || '未分类'}</span>
                          <Badge tone={DIFF_TONE[q.difficulty]}>{DIFF_CN[q.difficulty] || q.difficulty || '—'}</Badge>
                          <span className="cb3-q-years">{(q.appear_years || []).join('/') || '年份未标注'}</span>
                        </span>
                      </td>
                      <td className="cb3-col-subject cb3-muted">{q.subject || '—'}</td>
                      <td className="cb3-col-diff">
                        <Badge tone={DIFF_TONE[q.difficulty]}>{DIFF_CN[q.difficulty] || q.difficulty || '—'}</Badge>
                      </td>
                      <td className="cb3-col-freq"><Stars n={q.frequency} /></td>
                      <td className="cb3-col-years cb3-muted">{(q.appear_years || []).join('/') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : null}

      {/* 考频分析 */}
      {!loading && !error && tab === 'strategy' && strategy
        && strategy.top_questions.length === 0 && strategy.by_subject.length === 0 ? (
          <Card className="cb3-state-card">
            <Empty
              icon={<Activity size={26} />}
              title="还没有考频数据"
              text="题目积累后，系统会按出现年份与标签统计高频题和科目分布。"
              action={<Button variant="tonal" icon={<FileText size={16} />} onClick={() => setTab('list')}>去题库列表</Button>}
            />
          </Card>
        ) : null}

      {!loading && !error && tab === 'strategy' && strategy
        && (strategy.top_questions.length > 0 || strategy.by_subject.length > 0) ? (
          <div className="v3-bento">
            <Card className="cb3-top-card v3-span-7">
              <CardHead
                icon={<Trophy size={17} />}
                title="高频题 TOP 10"
                sub="按考频标注排序，点击查看题面与语言模板"
                actions={<Badge tone="primary">{strategy.top_questions.length} 道</Badge>}
              />
              {strategy.top_questions.length === 0 ? (
                <p className="cb3-caption">暂无可排序的题目。</p>
              ) : (
                <div className="cb3-top-list">
                  {strategy.top_questions.map((q, i) => (
                    <button key={q.id} type="button" className="cb3-top-row" onClick={() => openDetail(q.id)}>
                      <span className={`cb3-rank${i < 3 ? ' is-hot' : ''}`}>{i + 1}</span>
                      <span className="cb3-top-main">
                        <span className="cb3-top-title">{q.title}</span>
                        <span className="cb3-top-meta">
                          {q.subject || '未分类'}
                          {' · '}
                          <em className={`cb3-diff-text is-${q.difficulty || 'unknown'}`}>
                            {DIFF_CN[q.difficulty] || q.difficulty || '—'}
                          </em>
                          {' · '}
                          {(q.appear_years || []).join('/') || '年份未标注'}
                        </span>
                      </span>
                      <Stars n={q.frequency} className="cb3-top-stars" />
                    </button>
                  ))}
                </div>
              )}
            </Card>

            <Card className="cb3-dist-card v3-span-5">
              <CardHead
                icon={<Activity size={17} />}
                title="科目分布"
                sub="题数 × 平均考频"
                actions={<Badge tone="outline">{strategy.by_subject.length} 个科目</Badge>}
              />
              {strategy.by_subject.length === 0 ? (
                <p className="cb3-caption">暂无科目分布数据。</p>
              ) : (
                <div className="cb3-dist">
                  {strategy.by_subject.map((s) => {
                    const count = Number(s.count) || 0
                    return (
                      <div className="cb3-dist-row" key={s.subject}>
                        <div className="cb3-dist-head">
                          <span className="cb3-dist-name">{s.subject || '未分类'}</span>
                          <span className="cb3-dist-num">{count} 题</span>
                        </div>
                        <div className="cb3-dist-bar" aria-hidden="true">
                          <i style={{ width: `${Math.max(4, Math.round((count / maxSubjectCount) * 100))}%` }} />
                        </div>
                        <div className="cb3-dist-foot">
                          <span>均考频 {s.avg_frequency ?? '—'}</span>
                          {subject === s.subject ? <Badge tone="primary">已筛选</Badge> : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </Card>
          </div>
        ) : null}

      {/* 题目详情 */}
      <Dialog
        open={showAdd ? false : (detailLoading || !!detail)}
        title={detail?.title || '题目详情'}
        sub={detail
          ? `${detail.subject || '未分类'} · ${DIFF_CN[detail.difficulty] || detail.difficulty || '难度未标注'}${detail.appear_years?.length ? ` · 出现年份 ${detail.appear_years.join('/')}` : ''}`
          : '正在读取题面与示例…'}
        onClose={closeDetail}
        wide
        footer={<Button variant="tonal" onClick={closeDetail}>关闭</Button>}
      >
        {detailLoading ? (
          <div className="cb3-detail-skeleton">
            <Skeleton height={14} width="40%" />
            <Skeleton height={90} style={{ marginTop: 14 }} />
            <Skeleton height={44} style={{ marginTop: 14 }} />
            <Skeleton height={44} />
          </div>
        ) : detail ? (
          <div className="cb3-detail">
            <div className="cb3-detail-badges">
              <Badge tone={DIFF_TONE[detail.difficulty]}>{DIFF_CN[detail.difficulty] || detail.difficulty || '难度未标注'}</Badge>
              <Stars n={detail.frequency} />
              <span className="cb3-detail-subject">{detail.subject || '未分类'}</span>
              {detail.tags.map((t) => (
                <span className="cb3-tag" key={t}><Tag size={12} />{t}</span>
              ))}
            </div>

            <pre className="cb3-statement">{detail.statement || '题面未填写。'}</pre>

            {(detail.input_desc || detail.output_desc) ? (
              <div className="cb3-io">
                {detail.input_desc ? (
                  <div className="cb3-io__item">
                    <span>输入</span>
                    <p>{detail.input_desc}</p>
                  </div>
                ) : null}
                {detail.output_desc ? (
                  <div className="cb3-io__item">
                    <span>输出</span>
                    <p>{detail.output_desc}</p>
                  </div>
                ) : null}
              </div>
            ) : null}

            {detail.examples.length > 0 ? (
              <section className="cb3-examples">
                {detail.examples.map((ex, i) => (
                  <div className="cb3-example" key={i}>
                    <div className="cb3-example__head">示例 {i + 1}</div>
                    <div className="cb3-example__grid">
                      <div>
                        <span>输入</span>
                        <pre>{ex.input || '—'}</pre>
                      </div>
                      <div>
                        <span>输出</span>
                        <pre>{ex.output || '—'}</pre>
                      </div>
                    </div>
                  </div>
                ))}
              </section>
            ) : null}

            {detail.hint ? (
              <div className="cb3-hint">
                <InfoCircle size={16} />
                <span>提示：{detail.hint}</span>
              </div>
            ) : null}

            {detail.languages.length > 0 ? (
              <section className="cb3-code-section">
                <div className="cb3-code-head">
                  <span className="cb3-section-label">语言模板</span>
                  <div className="cb3-langs">
                    {detail.languages.map((l) => (
                      <Chip key={l} active={lang === l} onClick={() => setLang(l)}>{l}</Chip>
                    ))}
                  </div>
                </div>
                <pre className="cb3-code">{template(detail, lang)}</pre>
              </section>
            ) : null}

            <div className="cb3-note">
              <InfoCircle size={15} />
              <span>本地自测：复制模板到本地 IDE 运行；上机判题与提交记录将在后续版本接入。</span>
            </div>
          </div>
        ) : null}
      </Dialog>

      {/* 添加科目 */}
      <Dialog
        open={showAdd}
        title="添加科目模块"
        sub="科目会立即写入题库，可在题库列表、知识点全景与考频分析中使用"
        onClose={() => setShowAdd(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowAdd(false)}>取消</Button>
            <Button variant="gradient" icon={<Plus size={16} />} loading={adding} onClick={addSubject}>
              确认添加
            </Button>
          </>
        )}
      >
        <div className="cb3-add-form">
          <Field label="科目名称" hint="例如：光纤通信 / 嵌入式 / 复试英语口语">
            <Input
              ref={addNameRef}
              autoFocus
              placeholder="填写科目名称"
              aria-label="科目名称"
              value={newSub.name}
              onChange={(e) => setNewSub((s) => ({ ...s, name: e.target.value }))}
              onKeyDown={(e) => { if (e.key === 'Enter') addSubject() }}
            />
          </Field>
          <Field label="方向（可选）" hint="用于区分初试 / 复试或院校方向">
            <Input
              placeholder="例如：复试·通信"
              aria-label="方向（可选）"
              value={newSub.direction}
              onChange={(e) => setNewSub((s) => ({ ...s, direction: e.target.value }))}
              onKeyDown={(e) => { if (e.key === 'Enter') addSubject() }}
            />
          </Field>
        </div>
      </Dialog>
    </div>
  )
}
