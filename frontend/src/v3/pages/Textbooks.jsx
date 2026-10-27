import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { textbooksApi } from '../../api/client'
import {
  Badge, Button, Chip, Dialog, Empty, IconButton, Input, PageHeader, Segmented,
  Skeleton, Tile, toastErr,
} from '../ui'
import {
  AlertCircle, BookOpen, School, ChevronRight, FileText, RefreshCw, Search, Star,
} from '../icons'
import '../styles/pages.css'

const STAGE_ALL = '全部'
const STAGES = [STAGE_ALL, '初试', '复试']

function StageBadge({ stage }) {
  return <span className={`v3-tb-stage is-${stage === '复试' ? 'retest' : 'initial'}`}>{stage}</span>
}

function BookCard({ book, onOpen }) {
  return (
    <button type="button" className="v3-tb-card" onClick={() => onOpen(book)}>
      <div className="v3-tb-card__top">
        <div className="v3-tb-card__title">
          {book.title}
          {book.edition ? <span className="v3-tb-card__edition">{book.edition}</span> : null}
        </div>
        <div className="v3-tb-card__stages">
          {(book.stages || []).map((s) => <StageBadge key={s} stage={s} />)}
        </div>
      </div>
      <div className="v3-tb-card__meta">
        <span>{book.authors || '作者未标注'}</span>
        {book.publisher ? <span>{book.publisher}</span> : null}
      </div>
      {book.note ? <p className="v3-tb-card__note">{book.note}</p> : null}
      <div className="v3-tb-card__foot">
        <span className="v3-tb-card__scope">
          {book.school_count > 0 ? `适用 ${book.school_count} 所院校` : '全国通用'}
        </span>
        <span className={`v3-tb-conf${book.confidence === 'high' ? ' is-high' : ''}`}>
          {book.confidence === 'high' ? '指定教材' : '常见考情'}
        </span>
        <ChevronRight size={14} />
      </div>
    </button>
  )
}

function BookDetail({ book, onClose }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!book) return undefined
    let alive = true
    setLoading(true)
    setError('')
    textbooksApi.detail(book.id)
      .then((d) => { if (alive) setDetail(d) })
      .catch((e) => { if (alive) setError(e?.message || '关联信息加载失败') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [book])

  if (!book) return null

  return (
    <Dialog
      open={!!book}
      onClose={onClose}
      title={book.title}
      sub={`${book.authors || '作者未标注'} · ${book.publisher || '出版社未标注'}`}
      wide
    >
      <div className="v3-tb-detail">
        <div className="v3-tb-detail__meta">
          <div><span>版次</span><b>{book.edition || '—'}</b></div>
          <div><span>ISBN</span><b>{book.isbn || '—'}</b></div>
          <div><span>所属科目</span><b>{book.subject_name || '—'}</b></div>
          <div><span>适用阶段</span><b>{(book.stages || []).join(' / ') || '—'}</b></div>
          <div className="is-wide"><span>数据可信度</span><b>{book.confidence === 'high' ? '官方指定' : '常见考情归纳（人工整理）'}</b></div>
        </div>

        {book.note ? <p className="v3-tb-detail__note">{book.note}</p> : null}

        {loading ? (
          <div className="v3-stack" style={{ gap: 10 }}>
            <Skeleton height={18} /><Skeleton height={18} /><Skeleton height={18} />
          </div>
        ) : error ? (
          <Empty icon={<AlertCircle size={20} />} title="关联信息加载失败" text={error} />
        ) : (
          <>
            <section className="v3-tb-detail__section">
              <h3><School size={16} /> 适用院校 <Badge>{detail?.schools?.length || 0}</Badge></h3>
              {detail?.schools?.length ? (
                <div className="v3-tb-schools">
                  {detail.schools.map((s) => (
                    <div key={`${s.id}-${s.exam_stage || ''}`} className="v3-tb-school">
                      <span className="v3-tb-school__name">{s.name}</span>
                      {s.province ? <span className="v3-tb-school__prov">{s.province}</span> : null}
                      {s.exam_stage ? <StageBadge stage={s.exam_stage} /> : null}
                      {s.is_official ? <Badge tone="success">官方指定</Badge> : null}
                      {s.usage_note ? <span className="v3-tb-school__note">{s.usage_note}</span> : null}
                    </div>
                  ))}
                </div>
              ) : <p className="v3-caption">尚未关联到具体院校（属全国通用教材）</p>}
            </section>

            <section className="v3-tb-detail__section">
              <h3><FileText size={16} /> 关联文档 <Badge>{detail?.documents?.length || 0}</Badge></h3>
              {detail?.documents?.length ? (
                <div className="v3-tb-docs">
                  {detail.documents.map((d) => (
                    <div key={d.id} className="v3-tb-doc">
                      <FileText size={15} />
                      <span>{d.file_name}</span>
                      <Badge>{d.doc_role || '资料'}</Badge>
                    </div>
                  ))}
                </div>
              ) : <p className="v3-caption">该教材尚无实体文档入库</p>}
            </section>
          </>
        )}
      </div>
    </Dialog>
  )
}

export default function Textbooks() {
  const [searchParams] = useSearchParams()
  const [groups, setGroups] = useState([])
  const [stats, setStats] = useState(null)
  const [stage, setStage] = useState(STAGE_ALL)
  const [subject, setSubject] = useState(searchParams.get('subject') || '')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [active, setActive] = useState(null)

  useEffect(() => {
    const s = searchParams.get('subject')
    if (s !== null) setSubject(s)
  }, [searchParams])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [g, s] = await Promise.all([
        textbooksApi.bySubject(stage === STAGE_ALL ? undefined : stage),
        textbooksApi.stats(),
      ])
      setGroups(Array.isArray(g?.groups) ? g.groups : [])
      setStats(s || null)
      return true
    } catch (e) {
      setError(e?.message || '教材数据加载失败')
      toastErr('教材数据加载失败')
      return false
    } finally {
      setLoading(false)
    }
  }, [stage])

  useEffect(() => { load() }, [load])

  const subjectOptions = useMemo(
    () => groups.map((g) => ({ name: g.subject_name, count: g.textbooks?.length || 0 })),
    [groups],
  )

  const visibleGroups = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return groups
      .filter((g) => !subject || g.subject_name === subject)
      .map((g) => ({
        ...g,
        textbooks: (g.textbooks || []).filter((b) => {
          if (!kw) return true
          return [b.title, b.authors, b.publisher, b.note]
            .filter(Boolean).some((v) => String(v).toLowerCase().includes(kw))
        }),
      }))
      .filter((g) => g.textbooks.length > 0)
  }, [groups, subject, keyword])


  const stageCount = (name) => (stats?.by_stage || []).find((s) => s.stage === name)?.n || 0

  return (
    <div className="v3-stack" style={{ gap: 20 }}>
      <PageHeader
        eyebrow="TEXTBOOKS · 人工整理目录"
        title="核心专业课教材总目录"
        sub={subjectOptions.length
          ? `${subjectOptions.length} 个科目：${subjectOptions.slice(0, 6).map((o) => o.name).join(' / ')}${subjectOptions.length > 6 ? ' 等' : ''}`
          : '暂无教材数据：目录内容全部来自后端，导入资料后自动按科目归组'}
        actions={<IconButton label="刷新教材目录" icon={<RefreshCw size={17} />} onClick={load} disabled={loading} />}
      />

      {stats ? (
        <div className="v3-bento">
          {[
            ['教材总数', stats.total ?? 0, '本', BookOpen],
            ['初试适用', stageCount('初试'), '本', Star],
            ['复试适用', stageCount('复试'), '本', Star],
            ['覆盖科目', (stats.by_subject || []).length, '个', BookOpen],
            ['覆盖出版社', (stats.by_publisher || []).length, '家', School],
          ].map(([label, value, unit, Icon]) => (
            <Tile key={label} span={label === '教材总数' ? 4 : 2} className="v3-tb-stat">
              <span className="v3-tile__label"><Icon size={15} /> {label}</span>
              <span className="v3-tile__value">{value}<em>{unit}</em></span>
            </Tile>
          ))}
        </div>
      ) : null}

      <div className="v3-tb-toolbar">
        <Segmented ariaLabel="教材阶段" value={stage} onChange={(v) => { setStage(v); setSubject('') }} options={STAGES} />
        <Input
          icon={<Search size={16} />}
          placeholder="搜索书名 / 作者 / 出版社…"
          aria-label="搜索书名 / 作者 / 出版社"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      {subjectOptions.length > 0 ? (
        <div className="v3-tb-chips">
          <Chip active={subject === ''} onClick={() => setSubject('')}>全部科目 <span className="v3-tb-chip-n">{groups.reduce((n, g) => n + (g.textbooks?.length || 0), 0)}</span></Chip>
          {subjectOptions.map((o) => (
            <Chip key={o.name} active={subject === o.name} onClick={() => setSubject(o.name)}>
              {o.name} <span className="v3-tb-chip-n">{o.count}</span>
            </Chip>
          ))}
        </div>
      ) : null}

      {loading ? (
        <div className="v3-tb-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="v3-card" style={{ padding: 22 }}><Skeleton height={120} /></div>
          ))}
        </div>
      ) : error ? (
        <div className="v3-card" style={{ padding: 36 }}>
          <Empty icon={<AlertCircle size={24} />} title="教材目录加载失败" text={error}
            action={<Button variant="tonal" onClick={load}>重新加载</Button>} />
        </div>
      ) : visibleGroups.length === 0 ? (
        <div className="v3-card" style={{ padding: 40 }}>
          <Empty
            icon={<BookOpen size={26} />}
            title={groups.length ? '没有匹配的教材' : '教材目录还没有数据'}
            text={groups.length ? '换个阶段、科目或关键词试试。' : '目录全部来自后端人工整理数据；导入教材资料后会自动按科目归组。'}
            action={keyword ? <Button variant="tonal" onClick={() => { setKeyword(''); setSubject('') }}>清空筛选</Button> : null}
          />
        </div>
      ) : (
        visibleGroups.map((g) => (
          <section key={g.subject_id} className="v3-tb-group">
            <header className="v3-tb-group__head">
              <h2>{g.subject_name}</h2>
              <span>{g.textbooks.length} 本</span>
            </header>
            <div className="v3-tb-grid">
              {g.textbooks.map((b) => (
                <BookCard key={b.id} book={{ ...b, subject_name: g.subject_name }} onOpen={setActive} />
              ))}
            </div>
          </section>
        ))
      )}

      <Tile variant="well" className="v3-tb-note">
        <AlertCircle size={17} />
        <p><b>口径说明：</b>教材书目来自人工整理目录，<b>指定教材</b>需院校官方文件佐证，「常见考情」为归纳参考，非官方唯一标准；适用院校数量来自已关联院校，不等同于全国范围。</p>
      </Tile>

      {active ? <BookDetail book={active} onClose={() => setActive(null)} /> : null}
    </div>
  )
}
