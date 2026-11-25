import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ImmersiveLayout from './ImmersiveLayout'
import Disclosure from './Disclosure'
import { cx, Ic, Chip, Empty, Spinner, Stat } from './lib'
import { taxonomyApi, quizApi } from '../api/client'
import {
  AlertCircle, ArrowRight, BookOpen, Brain, ChevronRight, GraduationCap,
  Layers, RefreshCw, Search, Target, X,
} from '../v3/icons'

const TYPE_TONE = { 选择: 'accent', 填空: 'teal', 计算: 'warn', 分析: '', 论述: '', 证明: '', 画图: '' }

function qtypeChips(types) {
  const arr = String(types || '').split(/[\s,，、;；\n]+/).filter(Boolean)
  return [...new Set(arr)].slice(0, 6)
}

function KpCard({ kp, onPractice }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState(null)
  const [count, setCount] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (detail !== null) return
    setLoading(true)
    try {
      const d = await taxonomyApi.knowledgePoint(kp.id)
      setDetail(d)
    } catch { setDetail({ description: '' }) }
    try {
      const r = await quizApi.questions({ kp_id: kp.id, page: 1, page_size: 1 })
      setCount(r?.total_count ?? r?.total ?? (r?.questions || r?.items || []).length)
    } catch { setCount(null) }
    finally { setLoading(false) }
  }, [kp.id, detail])

  useEffect(() => { if (open) load() }, [open, load])

  const diff = Number(kp.difficulty) || 0
  const chips = qtypeChips(kp.question_types)

  return (
    <Disclosure
      open={open}
      onOpenChange={setOpen}
      label={
        <>
          <span style={{ flex: '0 0 auto' }}>{kp.name}</span>
          {chips.map((t) => <Chip key={t} tone={TYPE_TONE[t]}>{t}</Chip>)}
        </>
      }
      meta={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          {diff > 0 && <span title="难度" style={{ color: 'var(--im-warning)' }}>{'★'.repeat(Math.min(5, diff))}</span>}
          {typeof count === 'number' && <span>{count} 题</span>}
        </span>
      }
    >
      {loading && !detail ? (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}><Spinner size={16} /> 加载知识点详解…</div>
      ) : (
        <>
          {detail?.description ? (
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.85 }}>{detail.description}</div>
          ) : (
            <div style={{ color: 'var(--im-text-subtle)' }}>暂无详解文本。</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            <button className="im-btn im-btn--primary im-btn--sm" onClick={() => onPractice(kp)}>
              <Ic of={Target} size={14} /> 去练这一知识点
            </button>
            <button
              className="im-btn im-btn--sm"
              onClick={() => onPractice(kp, true)}
              title="在题库中定位该知识点"
            >
              <Ic of={ArrowRight} size={14} /> 看全部关联题
            </button>
          </div>
        </>
      )}
    </Disclosure>
  )
}

export default function SubjectReview() {
  const navigate = useNavigate()
  const params = useParams()
  const subject = params.subject || ''

  const [subjects, setSubjects] = useState([])
  const [chapters, setChapters] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [openChapters, setOpenChapters] = useState(() => new Set([0]))
  const [query, setQuery] = useState('')
  const mainRef = useRef(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      setLoading(true); setError('')
      try {
        const [subjRes, treeRes] = await Promise.all([
          taxonomyApi.subjects().catch(() => ({ subjects: [] })),
          taxonomyApi.tree(subject, true, false),
        ])
        if (!alive) return
        setSubjects(subjRes?.subjects || [])
        const nodes = treeRes?.tree || []
        const node = nodes.find((n) => n.subject === subject) || nodes[0]
        setChapters((node?.chapters || []).filter((c) => (c.knowledge_points || []).length > 0))
        setOpenChapters(new Set([0]))
      } catch (e) {
        setError(e?.message || '加载失败')
      } finally {
        setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [subject])

  const stats = useMemo(() => {
    const s = subjects.find((x) => x.subject === subject)
    const kpTotal = chapters.reduce((a, c) => a + (c.knowledge_points?.length || 0), 0)
    return {
      chapters: chapters.length,
      kps: kpTotal,
      questions: s?.question_count ?? 0,
      kpDb: s?.knowledge_point_count ?? kpTotal,
    }
  }, [subjects, chapters, subject])

  // 知识点搜索：按名称过滤，搜索时只展示命中的章节并全部展开
  const q = query.trim().toLowerCase()
  const viewChapters = useMemo(() => {
    const list = chapters.map((ch, origIdx) => {
      const kps = ch.knowledge_points || []
      const kept = q ? kps.filter((kp) => String(kp.name || '').toLowerCase().includes(q)) : kps
      return { ch: { ...ch, knowledge_points: kept }, origIdx }
    })
    return q ? list.filter((x) => x.ch.knowledge_points.length > 0) : list
  }, [chapters, q])
  const matchCount = viewChapters.reduce((a, x) => a + (x.ch.knowledge_points?.length || 0), 0)

  const toggleChapter = (i) => setOpenChapters((prev) => {
    const n = new Set(prev); n.has(i) ? n.delete(i) : n.add(i); return n
  })

  const jumpChapter = (i) => {
    setOpenChapters((prev) => new Set(prev).add(i))
    requestAnimationFrame(() => {
      const el = document.getElementById(`im-ch-${i}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  const onPractice = (kp, all = false) => {
    const qs = new URLSearchParams({ subject })
    if (kp?.id) qs.set('kp_id', kp.id)
    navigate(`${all ? '/quiz' : '/studio/quiz'}?${qs.toString()}`)
  }

  const totalKps = stats.kps
  const leftRail = (
    <div className="im-chapters">
      <div
        className={cx('im-chapter')}
        style={{ cursor: 'default', opacity: .6 }}
      >
        <Ic of={Layers} size={14} /> {q ? `命中 ${viewChapters.length} 章 · ${matchCount} 点` : `共 ${chapters.length} 章 · ${totalKps} 知识点`}
      </div>
      {viewChapters.map(({ ch, origIdx }) => (
        <div
          key={ch.title + origIdx}
          className={cx('im-chapter')}
          onClick={() => jumpChapter(origIdx)}
        >
          <Ic of={ChevronRight} size={13} />
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ch.title}</span>
          <span className="im-chapter__count">{ch.knowledge_points?.length || 0}</span>
        </div>
      ))}
    </div>
  )

  const rightRail = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="im-card im-card__pad" style={{ padding: 14 }}>
        <div style={{ fontSize: 12, color: 'var(--im-text-subtle)', marginBottom: 8 }}>本科目概览</div>
        <div style={{ display: 'grid', gap: 10 }}>
          <MetaRow label="章节" value={`${stats.chapters}`} />
          <MetaRow label="知识点" value={`${stats.kps}`} />
          <MetaRow label="题库总量" value={`${stats.questions}`} />
        </div>
      </div>
      <button
        className="im-btn im-btn--primary im-btn--sm"
        style={{ justifyContent: 'flex-start' }}
        onClick={() => navigate(`/studio/quiz?subject=${encodeURIComponent(subject)}`)}
      >
        <Ic of={GraduationCap} size={14} /> 进入全屏刷题
      </button>
      <button className="im-btn im-btn--sm" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/knowledge')}>
        <Ic of={BookOpen} size={14} /> 返回知识地图
      </button>
      <div style={{ fontSize: 11.5, color: 'var(--im-text-subtle)', lineHeight: 1.6, padding: '0 4px' }}>
        点击左侧章节可快速跳转；展开知识点查看详解与关联题。侧栏可随时收起，把空间让给内容。
      </div>
    </div>
  )

  return (
    <ImmersiveLayout
      title="知识地图 · 全屏复习"
      subtitle={subject}
      subject={subject}
      left={leftRail} leftTitle="章节目录" leftIcon={BookOpen}
      right={rightRail} rightTitle="概览" rightIcon={Brain}
      defaultLeftOpen
      actions={
        <button className="im-btn im-btn--sm" onClick={() => setOpenChapters(new Set(chapters.map((_, i) => i)))}>
          全部展开
        </button>
      }
    >
      <div className="im-hero">
        <div>
          <h1>{subject}</h1>
          <p>按章节串联的知识点复习动线：逐章展开，看完一个知识点直接跳转刷题，形成「学 → 练」闭环。</p>
        </div>
        <div className="im-hero__stats">
          <Stat value={stats.chapters} label="章节" />
          <Stat value={stats.kps} label="知识点" tone="accent" />
          <Stat value={stats.questions} label="题目" tone="success" />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 18 }}>
        <div className="im-search">
          <Ic of={Search} size={16} style={{ color: 'var(--im-text-subtle)', flex: '0 0 auto' }} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`搜索 ${subject} 的知识点…`}
            aria-label="搜索知识点"
          />
          {query && (
            <button className="im-search__clear" onClick={() => setQuery('')} aria-label="清除搜索" title="清除">
              <Ic of={X} size={14} />
            </button>
          )}
        </div>
        {q && (
          <span style={{ fontSize: 12.5, color: 'var(--im-text-muted)' }}>
            命中 <b style={{ color: 'var(--im-accent)' }}>{matchCount}</b> 个知识点 · {viewChapters.length} 章
          </span>
        )}
      </div>

      {loading ? (
        <div style={{ display: 'grid', gap: 12 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} className="im-card im-card__pad">
              <div className="im-skeleton" style={{ height: 18, width: 180, marginBottom: 14 }} />
              <div className="im-skeleton" style={{ height: 12, marginBottom: 8 }} />
              <div className="im-skeleton" style={{ height: 12, width: '70%' }} />
            </div>
          ))}
        </div>
      ) : error ? (
        <Empty icon={AlertCircle} title="加载失败" hint={error} action={<button className="im-btn" onClick={() => window.location.reload()}><Ic of={RefreshCw} size={15} /> 重试</button>} />
      ) : viewChapters.length === 0 ? (
        <Empty
          icon={BookOpen}
          title={q ? `未找到与「${query.trim()}」匹配的知识点` : '该科目暂无知识结构'}
          hint={q ? '换个关键词试试，或清除搜索查看全部章节。' : '可能尚未导入教材知识点，或该科目知识点还在整理中。'}
          action={q
            ? <button className="im-btn im-btn--primary" onClick={() => setQuery('')}><Ic of={X} size={15} /> 清除搜索</button>
            : <button className="im-btn im-btn--primary" onClick={() => navigate('/knowledge')}><Ic of={BookOpen} size={15} /> 返回知识地图</button>}
        />
      ) : (
        <div ref={mainRef} style={{ display: 'grid', gap: 14 }}>
          {viewChapters.map(({ ch, origIdx }) => (
            <section key={ch.title + origIdx} id={`im-ch-${origIdx}`} className="im-card im-card__pad" style={{ padding: 0, overflow: 'hidden' }}>
              <Disclosure
                open={q ? true : openChapters.has(origIdx)}
                onOpenChange={() => { if (!q) toggleChapter(origIdx) }}
                defaultOpen={origIdx === 0}
                className=""
                triggerClassName=""
                label={
                  <>
                    <span style={{ fontSize: 13, color: 'var(--im-text-subtle)', fontWeight: 600 }}>第 {origIdx + 1} 章</span>
                    <span style={{ fontSize: 16, fontWeight: 700 }}>{ch.title}</span>
                  </>
                }
                meta={<Chip tone="accent">{ch.knowledge_points?.length || 0} 个知识点</Chip>}
              >
                <div style={{ display: 'grid', gap: 10, paddingTop: 4 }}>
                  {(ch.knowledge_points || []).map((kp) => (
                    <KpCard key={kp.id} kp={kp} onPractice={onPractice} />
                  ))}
                </div>
              </Disclosure>
            </section>
          ))}
        </div>
      )}
    </ImmersiveLayout>
  )
}

function MetaRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
      <span style={{ color: 'var(--im-text-subtle)' }}>{label}</span>
      <span style={{ color: 'var(--im-text)', fontWeight: 600 }}>{value}</span>
    </div>
  )
}
