import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { aiApi, documentsApi, kbApi, kbImportApi, taxonomyApi } from '../../api/client'
import { fmtBytes } from '../../utils/format'
import useStore from '../../store/useStore'
import {
  Alert, Badge, Button, Card, Chip, Dialog, Empty, Field, Input, Progress, Select, Skeleton,
  Tabs, Textarea, toast, toastErr, toastOk, useClickOutside, useConfirm, cx,
} from '../ui'
import {
  AlertCircle, AlertTriangle, ChevronDown, ChevronUp, Database, Edit, FileText, FolderOpen,
  Layers, ListChecks, Plus, RefreshCw, Search, Sparkles, Tag, Trash, X,
} from '../icons'
import { kpItems } from './documentsV3Shared'
import { useAuth } from '../../auth/AuthContext'

/* ==========================================================================
   文档知识库 · Aurora v3 扩展面板
   · RagSearchPanel      POST /ai/rag-search
   · KnowledgeView       GET  /documents/{id}/knowledge-points + /chunks
   · KbHealthPanelV3     GET  /kb/health
   · KbImportDialog      POST /kb-import/scan + /kb-import/confirm
   · QuestionReviewDialog POST /documents/{id}/preview-questions + /confirm-questions
   · SubjectMgrDialog    taxonomyApi 科目 CRUD
   · RawFilePreviewDialog GET /documents/{id}/raw（iframe，后端支持 Range）
   所有数据均来自接口，加载 / 失败 / 空都有显式状态。
   ========================================================================== */

/* -------------------------------------------------------------------------- */
/* 可搜索文档选择器（知识点图谱 / 单篇题目识别共用）                          */
/* -------------------------------------------------------------------------- */
function DocPicker({
  docs = [], value, onSelect, placeholder = '搜索并选择文档', ariaLabel = '选择文档',
}) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const boxRef = useRef(null)
  useClickOutside(boxRef, () => setOpen(false), open)

  const selected = useMemo(
    () => docs.find((d) => String(d.id) === String(value)) || null,
    [docs, value],
  )

  const matches = useMemo(() => {
    const kw = q.trim().toLowerCase()
    const arr = kw
      ? docs.filter((d) => `${d.filename} ${d.subject || ''}`.toLowerCase().includes(kw))
      : docs
    return { list: arr.slice(0, 8), more: Math.max(0, arr.length - 8), total: arr.length }
  }, [docs, q])

  return (
    <div className="dv3-docpick" ref={boxRef}>
      <div className="dv3-docpick__box">
        <Input
          icon={<Search size={15} />}
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          placeholder={selected ? selected.filename : placeholder}
          aria-label={ariaLabel}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
        />
        {selected ? (
          <div className="dv3-docpick__selected">
            <span className="dv3-docpick__name" title={selected.filename}>{selected.filename}</span>
            <Badge tone="outline">{selected.subject || '未分类'}</Badge>
            <Button
              variant="text"
              size="sm"
              icon={<X size={13} />}
              onClick={() => { onSelect?.(null); setQ('') }}
            >
              清除
            </Button>
          </div>
        ) : null}

        {open ? (
          <div className="dv3-docpick__list" role="listbox" aria-label="文档候选">
            {matches.list.length === 0 ? (
              <div className="dv3-docpick__hint">没有匹配的文档，换个关键词试试。</div>
            ) : matches.list.map((d) => {
              const active = String(d.id) === String(value)
              return (
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  key={d.id}
                  className={cx('dv3-docpick__item', active && 'is-active')}
                  onClick={() => { onSelect?.(d); setQ(''); setOpen(false) }}
                >
                  <span className="dv3-docpick__item-main">
                    <span className="dv3-docpick__name" title={d.filename}>{d.filename}</span>
                    <span className="dv3-docpick__meta">
                      {d.subject || '未分类'} · {Number(d.chunk_count || 0)} 分块 · {Number(d.content_length || 0).toLocaleString('zh-CN')} 字
                    </span>
                  </span>
                  <Badge tone={d.status === 'parsed' ? 'success' : 'outline'}>
                    {d.status === 'parsed' ? '已入库' : '未解析'}
                  </Badge>
                </button>
              )
            })}
            {matches.more > 0 ? (
              <div className="dv3-docpick__hint">还有 {matches.more} 篇未显示，继续输入可缩小范围。</div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* RAG 检索（移植 legacy DocumentsSearch.jsx）                                */
/* -------------------------------------------------------------------------- */
export function RagSearchPanel({ backendOk, subjectOptions = [], onOpenDoc }) {
  const [query, setQuery] = useState('')
  const [subject, setSubject] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [hits, setHits] = useState([])
  const [searched, setSearched] = useState(false)
  const [expanded, setExpanded] = useState(() => new Set())

  const runSearch = async (e) => {
    e?.preventDefault?.()
    const text = query.trim()
    if (!text) { toast('请输入检索内容'); return }
    if (!backendOk) {
      setError('需连接后端才能进行知识库检索')
      toast('需连接后端进行知识库检索')
      return
    }
    setLoading(true)
    setError('')
    setSearched(true)
    setExpanded(new Set())
    try {
      const r = await aiApi.ragSearch({ query: text, subject: subject || undefined, limit: 10 })
      if (!r || !Array.isArray(r.hits)) throw new Error('检索响应格式无法识别')
      setHits(r.hits)
    } catch (err) {
      setHits([])
      setError(err?.message || '检索失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  const toggleHit = (i) => setExpanded((prev) => {
    const next = new Set(prev)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    return next
  })

  return (
    <Card className="dv3-rag">
      <div className="dv3-panel-head dv3-rag__head">
        <div>
          <b><Search size={16} /> 知识库检索（RAG）</b>
          <span>全文 + 向量混合检索 · 命中分块可作为 AI 回答依据</span>
        </div>
        <Badge tone="primary">最多 10 条</Badge>
      </div>

      <form className="dv3-rag__form" onSubmit={runSearch}>
        <Input
          icon={<Search size={15} />}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入问题，如：什么是香农公式 / MOSFET 工作原理"
          aria-label="知识库检索问题"
        />
        <Select
          aria-label="检索学科范围"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
        >
          <option value="">全部学科</option>
          {subjectOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <Button variant="filled" type="submit" loading={loading} icon={<Search size={15} />}>
          {loading ? '检索中…' : '检索知识库'}
        </Button>
      </form>
      <p className="dv3-rag__note">
        检索结果来自已入库的知识分块，不会生成虚构内容；相关度由后端检索器返回。
      </p>

      {loading ? (
        <div className="dv3-rag__hits" aria-busy="true" aria-label="正在检索">
          {Array.from({ length: 3 }).map((_, i) => (
            <div className="dv3-hit" key={i}>
              <Skeleton height={14} width="42%" />
              <Skeleton height={12} width="88%" />
              <Skeleton height={12} width="76%" />
            </div>
          ))}
        </div>
      ) : error ? (
        <Empty
          icon={<AlertCircle size={24} />}
          title="检索失败"
          text={error}
          action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={runSearch}>重试</Button>}
        />
      ) : !searched ? (
        <Empty
          icon={<Search size={24} />}
          title="知识库检索"
          text="输入问题后回车，从已入库的分块中检索相关知识。"
        />
      ) : hits.length === 0 ? (
        <Empty
          icon={<FolderOpen size={24} />}
          title="未检索到相关知识"
          text="可换个关键词或清除学科筛选后再试。"
        />
      ) : (
        <div className="dv3-rag__hits">
          {hits.map((h, i) => {
            const text = h?.content || h?.text || ''
            const long = text.length > 260
            const isOpen = expanded.has(i)
            const score = h?.score != null && Number.isFinite(Number(h.score))
              ? Number(h.score).toFixed(2)
              : null
            return (
              <article className="dv3-hit" key={`${h?.doc_id || 'hit'}-${h?.chunk_id || i}`}>
                <div className="dv3-hit__head">
                  <div className="dv3-hit__title">
                    <span className="dv3-hit__n">#{i + 1}</span>
                    <b>{h?.title || h?.doc_name || '未命名片段'}</b>
                  </div>
                  <div className="dv3-hit__meta">
                    {score != null ? <Badge tone="success">相关度 {score}</Badge> : null}
                    <Badge tone="outline">{h?.source || h?.source_type || '知识分块'}</Badge>
                    <Badge tone="outline">{h?.subject || '未分类'}</Badge>
                    {h?.doc_name && h.doc_name !== h?.title ? (
                      <Badge tone="outline" className="dv3-hit__doc" title={h.doc_name}>{h.doc_name}</Badge>
                    ) : null}
                  </div>
                </div>
                <div className={cx('dv3-hit__body', long && !isOpen && 'is-clamped')}>
                  {text || '（该命中片段没有正文）'}
                </div>
                <div className="dv3-hit__foot">
                  {long ? (
                    <Button
                      variant="text"
                      size="sm"
                      icon={isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      onClick={() => toggleHit(i)}
                    >
                      {isOpen ? '收起' : '展开全文'}
                    </Button>
                  ) : <span />}
                  {h?.doc_id != null && onOpenDoc ? (
                    <Button
                      variant="text"
                      size="sm"
                      icon={<FileText size={14} />}
                      onClick={() => onOpenDoc(h.doc_id, h)}
                    >
                      查看文档
                    </Button>
                  ) : null}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* 知识库体检（GET /kb/health）                                               */
/* -------------------------------------------------------------------------- */
function KbHealthPanelV3({ backendOk }) {
  const [state, setState] = useState('loading')
  const [rep, setRep] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!backendOk) { setState('offline'); return }
    setState('loading')
    setError('')
    try {
      const r = await kbApi.health()
      if (!r || (!r.documents && !r.chunks)) throw new Error('体检响应缺少统计字段')
      setRep(r)
      setState('ok')
    } catch (e) {
      setRep(null)
      setError(e?.message || '知识库体检失败')
      setState('error')
    }
  }, [backendOk])

  useEffect(() => { load() }, [load])

  const docs = rep?.documents || {}
  const chunks = rep?.chunks || {}
  const issues = Array.isArray(rep?.issues) ? rep.issues : []
  const problemCount = issues.filter((i) => i.level === 'error' || i.level === 'warn').length
  const healthy = rep?.healthy === true

  return (
    <Card className="dv3-health">
      <div className="dv3-panel-head">
        <div className="dv3-health__title">
          <b><Database size={15} /> 知识库体检</b>
          <span>如实统计缺口，不做估算</span>
        </div>
        <div className="dv3-health__actions">
          {state === 'ok' ? (
            <Badge tone={healthy ? 'success' : 'warning'}>
              {healthy ? '状态良好' : `${problemCount} 项待处理`}
            </Badge>
          ) : null}
          <Button
            variant="text"
            size="sm"
            icon={<RefreshCw size={14} />}
            disabled={state === 'loading'}
            onClick={load}
          >
            重新体检
          </Button>
        </div>
      </div>

      {state === 'offline' ? (
        <Empty
          icon={<AlertCircle size={22} />}
          title="后端离线"
          text="连接后端后可查看知识库体检结果。"
        />
      ) : state === 'loading' ? (
        <div className="dv3-health__metrics" aria-busy="true">
          {Array.from({ length: 5 }).map((_, i) => (
            <div className="dv3-health__metric" key={i}><Skeleton height={22} width="48%" /><Skeleton height={11} width="70%" /></div>
          ))}
        </div>
      ) : state === 'error' ? (
        <Empty
          icon={<AlertCircle size={22} />}
          title="体检失败"
          text={error}
          action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={load}>重试</Button>}
        />
      ) : (
        <>
          <div className="dv3-health__metrics">
            <div className="dv3-health__metric">
              <b>{Number(docs.total ?? 0).toLocaleString('zh-CN')}</b>
              <span>文档总数</span>
            </div>
            <div className="dv3-health__metric">
              <b>{Number(chunks.total ?? 0).toLocaleString('zh-CN')}</b>
              <span>分块总数</span>
            </div>
            <div className={cx('dv3-health__metric', chunks.missing_embedding > 0 && 'is-bad')}>
              <b>{chunks.missing_embedding == null ? '未知' : Number(chunks.missing_embedding).toLocaleString('zh-CN')}</b>
              <span>缺向量分块</span>
            </div>
            <div className={cx('dv3-health__metric', docs.empty_content > 0 && 'is-bad')}>
              <b>{docs.empty_content == null ? '未知' : Number(docs.empty_content).toLocaleString('zh-CN')}</b>
              <span>正文为空</span>
            </div>
            <div className={cx('dv3-health__metric', !healthy && 'is-bad')}>
              <b>{healthy ? '健康' : problemCount}</b>
              <span>{healthy ? '无缺口' : '告警 / 错误项'}</span>
            </div>
          </div>
          {issues.length > 0 ? (
            <div className="dv3-health__issues">
              {issues.slice(0, 3).map((it) => (
                <span key={it.key} className={cx('dv3-health__issue', it.level)} title={it.impact || ''}>
                  <AlertTriangle size={12} />
                  {it.title}
                </span>
              ))}
              {issues.length > 3 ? <span className="dv3-health__issue">还有 {issues.length - 3} 项</span> : null}
            </div>
          ) : null}
        </>
      )}
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* 知识图谱 / 分块（移植 legacy DocumentsKnowledge.jsx 语义）                  */
/* -------------------------------------------------------------------------- */
const kpNameOf = (k) => k?.name || k?.point || k?.title || '未命名知识点'
const kpDescOf = (k) => (k?.description || k?.summary || '').trim()
const kpTypeOf = (k) => k?.type || k?.kp_type || k?.category || ''
const kpImportanceOf = (k) => k?.importance ?? k?.importance_level ?? k?.weight ?? null
const kpRelationsOf = (k) => {
  const raw = k?.relations || k?.related || k?.related_points
  if (!Array.isArray(raw)) return []
  return raw
    .map((r) => (typeof r === 'string' ? r : (r?.name || r?.title || r?.target || '')))
    .filter(Boolean)
}

export function KnowledgeView({ backendOk, docs = [], onOpenDoc }) {
  const { isAdmin } = useAuth()
  const addCard = useStore((s) => s.addCard)
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [tab, setTab] = useState('points')
  const [points, setPoints] = useState({ state: 'idle', list: [], error: '' })
  const [chunks, setChunks] = useState({ state: 'idle', list: [], error: '' })
  const [kpSubject, setKpSubject] = useState('all')
  const tokenRef = useRef(0)

  const loadPoints = useCallback(async (doc) => {
    const token = tokenRef.current
    setPoints({ state: 'loading', list: [], error: '' })
    try {
      const r = await documentsApi.knowledgePoints(Number(doc.id))
      if (token !== tokenRef.current) return
      setPoints({ state: 'ok', list: kpItems(r), error: '' })
    } catch (e) {
      if (token !== tokenRef.current) return
      setPoints({ state: 'error', list: [], error: e?.message || '获取知识点失败' })
    }
  }, [])

  const loadChunks = useCallback(async (doc) => {
    const token = tokenRef.current
    setChunks({ state: 'loading', list: [], error: '' })
    try {
      const r = await documentsApi.chunks(Number(doc.id))
      if (token !== tokenRef.current) return
      if (!r || !Array.isArray(r.chunks)) throw new Error('分块响应格式无法识别')
      setChunks({ state: 'ok', list: r.chunks, error: '' })
    } catch (e) {
      if (token !== tokenRef.current) return
      setChunks({ state: 'error', list: [], error: e?.message || '获取分块失败' })
    }
  }, [])

  const pickDoc = (d) => {
    tokenRef.current += 1
    setSelectedDoc(d || null)
    setPoints({ state: 'idle', list: [], error: '' })
    setChunks({ state: 'idle', list: [], error: '' })
    setKpSubject('all')
    setTab('points')
  }

  useEffect(() => {
    if (!selectedDoc) return
    if (tab === 'points' && points.state === 'idle') loadPoints(selectedDoc)
    if (tab === 'chunks' && chunks.state === 'idle') loadChunks(selectedDoc)
  }, [selectedDoc, tab, points.state, chunks.state, loadPoints, loadChunks])

  const kpFacets = useMemo(() => {
    const map = new Map()
    points.list.forEach((k) => {
      const s = k?.subject || selectedDoc?.subject || '未分类'
      map.set(s, (map.get(s) || 0) + 1)
    })
    return Array.from(map.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
  }, [points.list, selectedDoc])

  const kpShown = useMemo(
    () => (kpSubject === 'all'
      ? points.list
      : points.list.filter((k) => (k?.subject || selectedDoc?.subject || '未分类') === kpSubject)),
    [points.list, kpSubject, selectedDoc],
  )

  const tabOptions = [
    { value: 'points', label: '知识点', count: points.state === 'ok' ? points.list.length : null },
    { value: 'chunks', label: '分块', count: chunks.state === 'ok' ? chunks.list.length : null },
  ]

  const kpToCard = (k) => {
    const front = kpNameOf(k)
    const back = kpDescOf(k) || '（该知识点暂无描述，请补充）'
    addCard({ front, back })
    toastOk(`已加入记忆卡片：${front.slice(0, 14)}`)
  }

  return (
    <div className="v3-stack dv3-know">
      {isAdmin ? <KbHealthPanelV3 backendOk={backendOk} /> : null}

      <Card className="dv3-know__pick">
        <div className="dv3-panel-head">
          <div>
            <b><Tag size={16} /> 选择文档</b>
            <span>知识点与分块按文档按需加载，不会预取全库</span>
          </div>
          <Badge tone="outline">{docs.length} 篇可选</Badge>
        </div>
        <DocPicker
          docs={docs}
          value={selectedDoc?.id}
          onSelect={pickDoc}
          placeholder="搜索文档名 / 科目，选择后加载知识点"
          ariaLabel="选择要查看知识点的文档"
        />
      </Card>

      {!selectedDoc ? (
        <Card>
          <Empty
            icon={<Sparkles size={26} />}
            title="选择一篇文档开始"
            text="从上方搜索框选择文档后，可按需加载知识点与知识分块；也可以回到列表点某篇文档的「知识点」。"
          />
        </Card>
      ) : (
        <Card className="dv3-know__panel">
          <div className="dv3-panel-head dv3-know__head">
            <div className="dv3-know__title">
              <b title={selectedDoc.filename}>{selectedDoc.filename}</b>
              <div className="dv3-know__meta">
                <Badge tone="outline">{selectedDoc.subject || '未分类'}</Badge>
                <Badge tone={selectedDoc.status === 'parsed' ? 'success' : 'warning'}>
                  {selectedDoc.status === 'parsed' ? '已入库' : '未解析'}
                </Badge>
                <span>{Number(selectedDoc.content_length || 0).toLocaleString('zh-CN')} 字</span>
              </div>
            </div>
            {onOpenDoc ? (
              <Button variant="text" size="sm" icon={<FileText size={14} />} onClick={() => onOpenDoc(selectedDoc)}>
                查看详情
              </Button>
            ) : null}
          </div>

          <Tabs ariaLabel="知识点与分块" options={tabOptions} value={tab} onChange={setTab} />

          {tab === 'points' ? (
            points.state === 'loading' ? (
              <div className="dv3-skel" aria-busy="true">
                {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={42} width="100%" />)}
              </div>
            ) : points.state === 'error' ? (
              <Empty
                icon={<AlertCircle size={24} />}
                title="获取知识点失败"
                text={points.error}
                action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={() => loadPoints(selectedDoc)}>重试</Button>}
              />
            ) : points.list.length === 0 ? (
              <Empty
                icon={<Tag size={24} />}
                title="该文档暂无知识点"
                text="可能尚未执行「智能分析」，或该文档不含可识别知识点。"
              />
            ) : (
              <>
                {kpFacets.length > 1 ? (
                  <div className="dv3-kp-chips" role="group" aria-label="按科目筛选知识点">
                    <Chip active={kpSubject === 'all'} onClick={() => setKpSubject('all')}>
                      全部 <span className="dv3-chip-n">{points.list.length}</span>
                    </Chip>
                    {kpFacets.map((s) => (
                      <Chip key={s.name} active={kpSubject === s.name} onClick={() => setKpSubject(s.name)}>
                        {s.name} <span className="dv3-chip-n">{s.count}</span>
                      </Chip>
                    ))}
                  </div>
                ) : null}

                {kpShown.length === 0 ? (
                  <Empty
                    icon={<Tag size={24} />}
                    title="该科目下暂无知识点"
                    text="换个科目标签，或对文档执行「智能分析」重新提取。"
                  />
                ) : (
                  <div className="dv3-kp-list">
                    {kpShown.map((k, i) => {
                      const type = kpTypeOf(k)
                      const importance = kpImportanceOf(k)
                      const relations = kpRelationsOf(k)
                      return (
                        <div className="dv3-kp" key={`${kpNameOf(k)}-${i}`}>
                          <div className="dv3-kp__head">
                            <b>{kpNameOf(k)}</b>
                            <div className="dv3-kp__meta">
                              {type ? <Badge tone="primary">类型 {String(type)}</Badge> : null}
                              {importance != null && importance !== '' ? (
                                <Badge tone="warning">重要度 {String(importance)}</Badge>
                              ) : null}
                              {k?.exam_frequency != null && k.exam_frequency !== '' ? (
                                <Badge tone="warning">出题频率 {String(k.exam_frequency)}</Badge>
                              ) : null}
                              {k?.chapter ? <Badge tone="outline">{k.chapter}</Badge> : null}
                            </div>
                          </div>
                          <p>{kpDescOf(k) || '（该知识点暂无描述，可对文档执行「智能分析」补全）'}</p>
                          {k?.subject ? <span className="dv3-kp__subj">{k.subject}</span> : null}
                          {relations.length > 0 ? (
                            <div className="dv3-kp__rel">
                              <span>关联</span>
                              {relations.map((r, ri) => <span className="dv3-kp__rel-item" key={`${r}-${ri}`}>{r}</span>)}
                            </div>
                          ) : null}
                          <div className="dv3-kp__foot">
                            <Button
                              variant="text"
                              size="sm"
                              icon={<Plus size={13} />}
                              onClick={() => kpToCard(k)}
                            >
                              加入记忆卡片
                            </Button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </>
            )
          ) : chunks.state === 'loading' ? (
            <div className="dv3-skel" aria-busy="true">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={64} width="100%" />)}
            </div>
          ) : chunks.state === 'error' ? (
            <Empty
              icon={<AlertCircle size={24} />}
              title="获取分块失败"
              text={chunks.error}
              action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={() => loadChunks(selectedDoc)}>重试</Button>}
            />
          ) : chunks.list.length === 0 ? (
            <Empty
              icon={<Layers size={24} />}
              title="该文档暂无分块"
              text="可能为扫描件或正文过短，可尝试重新解析。"
            />
          ) : (
            <>
              <div className="dv3-panel-head">
                <b>分块内容</b>
                <span>共 {chunks.list.length} 块</span>
              </div>
              <div className="dv3-chunk-list">
                {chunks.list.map((c, i) => {
                  const text = c?.text || c?.content || ''
                  return (
                    <div className="dv3-chunk" key={`${c?.chunk_id || c?.id || i}`}>
                      <div className="dv3-chunk__head">
                        <span className="dv3-chunk__n">#{c?.chunk_id || c?.id || i + 1}</span>
                        <span>{text.length} 字</span>
                      </div>
                      <p>{text}</p>
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* 知识库题目识别 / 确认入库（移植 legacy DocKbImportModal.jsx）               */
/* -------------------------------------------------------------------------- */
const kbCandStem = (c) => c.content || c.question || c.text || c.stem || c.title || c.题干 || '（无题干）'
const kbCandType = (c) => c.question_type || c.type || c.qtype || c.题型 || ''
const kbCandExisting = (c) => !!(c.already_exists || c.is_existing || c.exists || c.dup || c.is_dup || c.in_quiz)

function kbNormalize(resp) {
  const rawItems = resp?.items || resp?.candidates || resp?.docs || []
  const items = (Array.isArray(rawItems) ? rawItems : []).map((it, di) => {
    const docId = it.doc_id ?? it.id ?? ''
    const cands = Array.isArray(it.candidates) ? it.candidates : (Array.isArray(it.items) ? it.items : [])
    return {
      key: `${docId}::${di}`,
      doc_id: docId,
      doc_title: it.doc_title ?? it.title ?? it.file_name ?? it.filename ?? '未命名文档',
      subject: it.subject || '未分类',
      truncated: !!it.truncated,
      candidates: (Array.isArray(cands) ? cands : []).map((c, i) => {
        const candIndex = typeof c.index === 'number' ? c.index : i
        return {
          _key: `${docId}::${candIndex}`,
          docId,
          candIndex,
          stem: kbCandStem(c),
          type: kbCandType(c),
          existing: kbCandExisting(c),
          raw: c,
        }
      }),
    }
  }).filter((d) => d.candidates.length > 0)
  const scannedDocs = resp?.scanned_docs ?? resp?.scannedDocs ?? items.length
  return {
    totalDocs: resp?.total_docs ?? resp?.totalDocs ?? items.length,
    scannedDocs,
    scopeDocs: resp?.file_type ? scannedDocs : null,
    totalCandidates: resp?.total_candidates ?? resp?.totalCandidates ?? items.reduce((s, d) => s + d.candidates.length, 0),
    dupSkipped: resp?.dup_skipped ?? resp?.dupSkipped ?? resp?.duplicates_skipped ?? 0,
    elapsed: resp?.elapsed_seconds ?? resp?.elapsed_ms ?? 0,
    items,
  }
}

export function KbImportDialog({
  open, docs = [], listIds = [], defaultScope = 'list', initialDocId = '', onClose, onImported,
}) {
  const [confirm, confirmDialog] = useConfirm()
  const [scope, setScope] = useState(defaultScope)
  const [singleId, setSingleId] = useState('')
  const [status, setStatus] = useState('setup')
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [checked, setChecked] = useState(() => new Set())
  const [expandedDocs, setExpandedDocs] = useState(() => new Set())
  const [confirming, setConfirming] = useState(false)
  const [done, setDone] = useState(null)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!open) return
    setScope(defaultScope || 'list')
    setSingleId(initialDocId ? String(initialDocId) : '')
    setStatus('setup')
    setError('')
    setResult(null)
    setChecked(new Set())
    setExpandedDocs(new Set())
    setDone(null)
    setElapsed(0)
  }, [open, defaultScope, initialDocId])

  useEffect(() => {
    if (status !== 'scanning') return undefined
    const t0 = Date.now()
    setElapsed(0)
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [status])

  const scopeLabel = scope === 'all'
    ? '全库'
    : scope === 'list'
      ? `当前列表（${listIds.length} 篇）`
      : '单篇'

  const subjDist = useMemo(() => {
    if (!result) return []
    const map = new Map()
    result.items.forEach((d) => d.candidates.forEach((c) => map.set(d.subject, (map.get(d.subject) || 0) + 1)))
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count)
  }, [result])

  const selectable = useMemo(() => {
    if (!result) return { total: 0, checked: 0 }
    let total = 0
    result.items.forEach((d) => d.candidates.forEach((c) => { if (!c.existing) total += 1 }))
    return { total, checked: checked.size }
  }, [result, checked])

  const runScan = async () => {
    let ids = null
    if (scope === 'list') ids = listIds
    if (scope === 'single') ids = singleId ? [Number(singleId)] : null
    if (scope !== 'all' && (!ids || ids.length === 0)) {
      toastErr(scope === 'single' ? '请先选择一篇文档' : '当前列表没有可识别的文档')
      return
    }
    if (scope === 'all') {
      const ok = await confirm({
        title: '全库识别题目',
        message: '全库识别会逐篇扫描并打分，实测约 5 分钟。建议先用「当前列表」或「单篇」分批处理。是否继续全库扫描？',
        confirmText: '开始全库识别',
      })
      if (!ok) return
    }

    setStatus('scanning')
    setError('')
    setResult(null)
    setChecked(new Set())
    setExpandedDocs(new Set())
    setDone(null)
    try {
      const body = ids && ids.length ? { doc_ids: ids } : {}
      const resp = await kbImportApi.scan(body)
      const norm = kbNormalize(resp)
      setResult(norm)
      const next = new Set()
      norm.items.forEach((d) => d.candidates.forEach((c) => { if (!c.existing) next.add(c._key) }))
      setChecked(next)
      setStatus('result')
    } catch (e) {
      setError(e?.message || '扫描失败，请稍后重试')
      setStatus('error')
    }
  }

  const toggleOne = (key) => setChecked((prev) => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })

  const toggleAll = (check) => {
    if (!result) return
    if (!check) { setChecked(new Set()); return }
    const next = new Set()
    result.items.forEach((d) => d.candidates.forEach((c) => { if (!c.existing) next.add(c._key) }))
    setChecked(next)
  }

  const toggleDoc = (key) => setExpandedDocs((prev) => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })

  const confirmImport = async () => {
    if (!result || checked.size === 0) { toast('请先勾选要入库的题目'); return }
    const ok = await confirm({
      title: '确认入库',
      message: `将选中的 ${checked.size} 道题目写入题库，来源标记为「知识库:文档名」。`,
      confirmText: '确认入库',
    })
    if (!ok) return
    setConfirming(true)
    try {
      const selected = []
      result.items.forEach((d) => d.candidates.forEach((c) => {
        if (checked.has(c._key)) selected.push({ doc_id: c.docId, index: c.candIndex })
      }))
      const r = await kbImportApi.confirm({ selected })
      const imported = r?.inserted ?? 0
      const skipped = r?.skipped_existing ?? r?.skipped ?? 0
      setDone({
        inserted: imported,
        skipped,
        outOfRange: r?.out_of_range ?? 0,
        bySubject: r?.by_subject || {},
      })
      setStatus('done')
      toastOk(`已入库 ${imported} 题 / 跳过已存在 ${skipped} 题`)
      onImported?.()
    } catch (e) {
      toastErr(`入库失败：${e?.message || e}`)
    } finally {
      setConfirming(false)
    }
  }

  const close = () => {
    if (status === 'scanning' || confirming) {
      toast('识别 / 入库进行中，请等待完成')
      return
    }
    onClose?.()
  }

  const title = status === 'setup'
    ? '题目识别与确认入库 · 选择范围'
    : status === 'done'
      ? '题目入库完成'
      : `知识库题目识别 · ${scopeLabel}`

  const footer = status === 'done' ? (
    <Button variant="filled" size="sm" onClick={close}>完成</Button>
  ) : (
    <>
      <Button variant="text" size="sm" onClick={close} disabled={status === 'scanning' || confirming}>
        取消
      </Button>
      {status === 'setup' ? (
        <Button
          variant="filled"
          size="sm"
          icon={<Sparkles size={14} />}
          disabled={scope === 'single' ? !singleId : scope === 'list' ? listIds.length === 0 : false}
          onClick={runScan}
        >
          开始识别
        </Button>
      ) : status === 'scanning' ? (
        <Button variant="filled" size="sm" loading>识别中…</Button>
      ) : status === 'error' ? (
        <Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={runScan}>重新识别</Button>
      ) : (
        <Button
          variant="filled"
          size="sm"
          loading={confirming}
          disabled={checked.size === 0 || status !== 'result'}
          onClick={confirmImport}
        >
          {confirming ? '入库中…' : `确认入库（${checked.size}）`}
        </Button>
      )}
    </>
  )

  return (
    <>
      <Dialog open={open} wide title={title} onClose={close} footer={footer} className="dv3-kbimp-dialog">
        <div className="dv3-kbimp">
          {status === 'setup' ? (
            <>
              <p className="dv3-kbimp__hint">
                识别只读扫描候选题目，不会写库；确认后才把勾选的题目写入题库。
              </p>
              <div className="dv3-kbimp__scopes" role="group" aria-label="识别范围">
                <Chip active={scope === 'all'} onClick={() => setScope('all')}>全库</Chip>
                <Chip active={scope === 'list'} onClick={() => setScope('list')}>
                  当前列表 <span className="dv3-chip-n">{listIds.length}</span>
                </Chip>
                <Chip active={scope === 'single'} onClick={() => setScope('single')}>单篇</Chip>
              </div>
              {scope === 'all' ? (
                <Alert tone="warning" icon={<AlertTriangle size={17} />}>
                  全库识别逐篇扫描，实测约 5 分钟；开始前会再次确认。建议优先使用当前列表或单篇。
                </Alert>
              ) : null}
              {scope === 'list' ? (
                <p className="dv3-kbimp__hint">将识别当前筛选出的 {listIds.length} 篇文档（含未解析文档会由后端跳过）。</p>
              ) : null}
              {scope === 'single' ? (
                <Field label="选择文档" hint="按文件名或科目搜索">
                  <DocPicker
                    docs={docs}
                    value={singleId}
                    onSelect={(d) => setSingleId(d ? d.id : '')}
                    placeholder="搜索并选择一篇文档"
                    ariaLabel="选择要识别题目的文档"
                  />
                </Field>
              ) : null}
            </>
          ) : null}

          {status === 'scanning' ? (
            <div className="dv3-kbimp__progress" role="status">
              <Progress indeterminate gradient />
              <b>正在扫描知识库文档并识别候选题目…</b>
              <span>
                范围：{scopeLabel} · 已等待 {elapsed}s
                {scope === 'all' ? '（全库实测约 5 分钟）' : '（按范围通常数秒到数分钟）'}
              </span>
            </div>
          ) : null}

          {status === 'error' ? (
            <Empty
              icon={<AlertCircle size={24} />}
              title="扫描失败"
              text={error}
              action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={runScan}>重试</Button>}
            />
          ) : null}

          {status === 'done' && done ? (
            <div className="dv3-kbimp__result">
              <div className="dv3-kbimp__metrics">
                <div className="dv3-kbimp__metric"><b>{done.inserted}</b><span>实际入库</span></div>
                <div className="dv3-kbimp__metric"><b>{done.skipped}</b><span>跳过已存在</span></div>
                <div className="dv3-kbimp__metric"><b>{done.outOfRange}</b><span>下标越界</span></div>
              </div>
              {Object.keys(done.bySubject || {}).length > 0 ? (
                <div className="dv3-kbimp__subj">
                  {Object.entries(done.bySubject).map(([s, n]) => <Badge key={s} tone="primary">{s} · {n}</Badge>)}
                </div>
              ) : null}
              <p className="dv3-kbimp__hint">可在「刷题中心」查看新入库的题目，来源标记为「知识库:文档名」。</p>
            </div>
          ) : null}

          {status === 'result' ? (
            !result || result.items.length === 0 ? (
              <Empty
                icon={<FolderOpen size={24} />}
                title={result && result.totalDocs === 0 ? '知识库还没有文档' : '未识别到候选题'}
                text={result && result.totalDocs === 0
                  ? '请先上传并解析文档，再回来识别题目。'
                  : `已扫描 ${result?.scannedDocs ?? 0} 篇文档，未发现可入库的候选题目（可能文档没有题号 / 选项结构，或题目都已入库）。`}
                action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={runScan}>重新扫描</Button>}
              />
            ) : (
              <>
                <div className="dv3-kbimp__metrics">
                  <div className="dv3-kbimp__metric"><b>{result.totalCandidates}</b><span>候选题目总数</span></div>
                  <div className="dv3-kbimp__metric"><b>{result.dupSkipped}</b><span>已去重跳过</span></div>
                  <div className="dv3-kbimp__metric">
                    <b>{result.scannedDocs}<em> / {result.scopeDocs ?? result.totalDocs}</em></b>
                    <span>扫描文档{result.elapsed ? ` · 耗时 ${Number(result.elapsed).toFixed(1)}s` : ''}</span>
                  </div>
                </div>

                {subjDist.length > 0 ? (
                  <div className="dv3-kbimp__subj">
                    {subjDist.map((s) => <Badge key={s.name} tone="outline">{s.name} · {s.count}</Badge>)}
                  </div>
                ) : null}

                <div className="dv3-kbimp__toolbar">
                  <Badge tone="success">已勾选 {selectable.checked} / {selectable.total} 新题</Badge>
                  <div className="dv3-kbimp__toolbar-actions">
                    <Button variant="text" size="sm" onClick={() => toggleAll(true)}>全选新题</Button>
                    <Button variant="text" size="sm" onClick={() => toggleAll(false)}>清空</Button>
                  </div>
                </div>

                <div className="dv3-kbimp__list">
                  {result.items.map((doc) => {
                    const expanded = expandedDocs.has(doc.key)
                    const shown = expanded ? doc.candidates : doc.candidates.slice(0, 5)
                    const newCount = doc.candidates.filter((c) => !c.existing).length
                    return (
                      <div className="dv3-kbimp__doc" key={doc.key}>
                        <div className="dv3-kbimp__dochead">
                          <span className="dv3-kbimp__docname" title={doc.doc_title}>{doc.doc_title}</span>
                          <Badge tone="outline">{doc.subject}</Badge>
                          <Badge tone="primary">{newCount} 新 / {doc.candidates.length} 总</Badge>
                          {doc.truncated ? <Badge tone="warning">候选过多已截断</Badge> : null}
                        </div>
                        {shown.map((c) => (
                          <div className={cx('dv3-kbimp__q', c.existing && 'is-existing')} key={c._key}>
                            <label className="dv3-check">
                              <input
                                type="checkbox"
                                aria-label={`选择题目：${c.stem.slice(0, 24)}`}
                                checked={checked.has(c._key)}
                                disabled={c.existing}
                                onChange={() => toggleOne(c._key)}
                              />
                              <span className="dv3-check__box" aria-hidden="true" />
                            </label>
                            <div className="dv3-kbimp__qmain">
                              <div className="dv3-kbimp__stem" title={c.stem}>{c.stem}</div>
                              <div className="dv3-kbimp__qmeta">
                                {c.type ? <Badge tone="outline">{c.type}</Badge> : null}
                                {c.existing ? <Badge tone="warning">已存在</Badge> : <Badge tone="success">新题</Badge>}
                              </div>
                            </div>
                          </div>
                        ))}
                        {doc.candidates.length > 5 ? (
                          <Button
                            variant="text"
                            size="sm"
                            icon={expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            onClick={() => toggleDoc(doc.key)}
                          >
                            {expanded ? '收起' : `展开全部 ${doc.candidates.length} 题`}
                          </Button>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              </>
            )
          ) : null}
        </div>
      </Dialog>
      {confirmDialog}
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* 题目预览与人工审核（移植 legacy DocQuestionPreviewModal.jsx）               */
/* -------------------------------------------------------------------------- */
export function QuestionReviewDialog({ open, doc, onClose, onImported }) {
  const [confirm, confirmDialog] = useConfirm()
  const [status, setStatus] = useState('idle')
  const [questions, setQuestions] = useState([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(-1)
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    if (!open || !doc) return undefined
    let alive = true
    setStatus('loading')
    setQuestions([])
    setTotal(0)
    setError('')
    setEditing(-1)
    documentsApi.previewQuestions(Number(doc.id))
      .then((r) => {
        if (!alive) return
        if (!r || !Array.isArray(r.questions)) throw new Error('题目预览响应格式无法识别')
        setQuestions(r.questions)
        setTotal(r.total ?? r.questions.length)
        setStatus('ok')
        toast(`预览到 ${r.total ?? r.questions.length} 道题目，请人工审核`)
      })
      .catch((e) => {
        if (!alive) return
        setError(e?.message || '预览失败')
        setStatus('error')
      })
    return () => { alive = false }
  }, [open, doc?.id, retry])

  const patch = (idx, field, value) => setQuestions((prev) => prev.map((q, i) => (
    i === idx ? { ...q, [field]: value } : q
  )))

  const patchOption = (qIdx, optIdx, value) => setQuestions((prev) => prev.map((q, i) => {
    if (i !== qIdx) return q
    const options = [...(q.options || [])]
    options[optIdx] = value
    return { ...q, options }
  }))

  const removeOne = (idx) => {
    setQuestions((prev) => prev.filter((_, i) => i !== idx))
    setEditing((cur) => (cur === idx ? -1 : cur))
    toast('已移除该题目')
  }

  const selectedCount = questions.filter((q) => q.selected !== false).length

  const submit = async () => {
    if (!doc) return
    if (selectedCount === 0) { toast('没有选中的题目'); return }
    const ok = await confirm({
      title: '确认入库题目',
      message: `确认入库 ${selectedCount} 道题目？未勾选的题目会被跳过。`,
      confirmText: '确认入库',
    })
    if (!ok) return
    setBusy(true)
    try {
      const r = await documentsApi.confirmQuestions(Number(doc.id), { questions })
      toastOk(`入库完成：成功 ${r?.imported ?? 0} 道，跳过 ${r?.skipped ?? 0} 道`)
      onClose?.()
      onImported?.()
    } catch (e) {
      toastErr(`入库失败：${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  const close = () => {
    if (busy) { toast('入库中，请等待完成'); return }
    onClose?.()
  }

  return (
    <>
      <Dialog
        open={open}
        wide
        title={`题目预览与人工审核${doc ? ` · ${doc.filename}` : ''}`}
        sub="AI 预抽题目 → 勾选 / 编辑 → 确认入库"
        onClose={close}
        footer={(
          <>
            <Button variant="text" size="sm" onClick={close} disabled={busy}>取消</Button>
            <Button
              variant="filled"
              size="sm"
              loading={busy}
              disabled={status !== 'ok' || selectedCount === 0}
              onClick={submit}
            >
              {busy ? '入库中…' : `确认入库（${selectedCount}）`}
            </Button>
          </>
        )}
      >
        <div className="dv3-review">
          {status === 'loading' ? (
            <div className="dv3-review__list" aria-busy="true">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={88} width="100%" />)}
            </div>
          ) : status === 'error' ? (
            <Empty
              icon={<AlertCircle size={24} />}
              title="题目预览失败"
              text={error}
              action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={() => setRetry((n) => n + 1)}>重试</Button>}
            />
          ) : questions.length === 0 ? (
            <Empty
              icon={<ListChecks size={24} />}
              title="未提取到题目"
              text="可先执行「智能分析」，或该文档不含可识别题目。"
              action={<Button variant="tonal" size="sm" onClick={() => setRetry((n) => n + 1)}>重新预览</Button>}
            />
          ) : (
            <>
              <div className="dv3-panel-head">
                <b>预览到 {total} 道题目</b>
                <span>已选 {selectedCount} 道 · 编辑只影响本次入库</span>
              </div>
              <div className="dv3-review__list">
                {questions.map((q, idx) => {
                  const opts = Array.isArray(q.options) ? q.options : []
                  const on = q.selected !== false
                  return (
                    <div className={cx('dv3-review__q', !on && 'is-off')} key={`${q.id || q.content || idx}-${idx}`}>
                      <div className="dv3-review__head">
                        <label className="dv3-check" title="选中该题目入库">
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => patch(idx, 'selected', !on)}
                            aria-label={`选择题目 #${idx + 1}`}
                          />
                          <span className="dv3-check__box" aria-hidden="true" />
                          <span className="dv3-review__n">#{idx + 1}</span>
                        </label>
                        <div className="dv3-review__badges">
                          {q.question_type ? <Badge tone="outline">{q.question_type}</Badge> : null}
                          {q.is_real ? <Badge tone="warning">真题</Badge> : null}
                          {q.difficulty ? <Badge tone="outline">难度 {q.difficulty}</Badge> : null}
                          {!on ? <Badge tone="danger">不入库</Badge> : null}
                        </div>
                        <div className="dv3-review__tools">
                          <Button
                            variant="text"
                            size="sm"
                            icon={<Edit size={13} />}
                            onClick={() => setEditing(editing === idx ? -1 : idx)}
                          >
                            {editing === idx ? '完成' : '编辑'}
                          </Button>
                          <Button variant="text" size="sm" icon={<Trash size={13} />} onClick={() => removeOne(idx)}>
                            移除
                          </Button>
                        </div>
                      </div>

                      {editing === idx ? (
                        <div className="dv3-review__edit">
                          <Field label="题干">
                            <Textarea
                              rows={3}
                              aria-label="题干"
                              value={q.content || q.question || ''}
                              onChange={(e) => patch(idx, 'content', e.target.value)}
                            />
                          </Field>
                          {opts.map((op, oi) => (
                            <Field key={oi} label={`选项 ${String.fromCharCode(65 + oi)}`}>
                              <Input
                                aria-label={`选项 ${String.fromCharCode(65 + oi)}`}
                                value={op}
                                onChange={(e) => patchOption(idx, oi, e.target.value)}
                              />
                            </Field>
                          ))}
                          <div className="dv3-review__grid">
                            <Field label="答案">
                              <Input aria-label="答案" value={q.answer || ''} onChange={(e) => patch(idx, 'answer', e.target.value)} />
                            </Field>
                            <Field label="科目">
                              <Input aria-label="科目" value={q.subject || ''} onChange={(e) => patch(idx, 'subject', e.target.value)} />
                            </Field>
                          </div>
                          <Field label="解析">
                            <Textarea
                              rows={2}
                              aria-label="解析"
                              value={q.analysis || ''}
                              onChange={(e) => patch(idx, 'analysis', e.target.value)}
                            />
                          </Field>
                        </div>
                      ) : (
                        <>
                          <div className="dv3-review__stem">{q.content || q.question || '（无题干）'}</div>
                          {opts.length > 0 ? (
                            <div className="dv3-review__opts">
                              {opts.map((op, oi) => <div key={oi}>{String.fromCharCode(65 + oi)}. {op}</div>)}
                            </div>
                          ) : null}
                          <div className="dv3-review__meta">
                            {q.answer ? <Badge tone="success">答案 {q.answer}</Badge> : null}
                            {q.subject ? <Badge tone="outline">{q.subject}</Badge> : null}
                            {q.chapter ? <span>{q.chapter}</span> : null}
                          </div>
                          {q.analysis ? <p className="dv3-review__analysis">解析：{q.analysis}</p> : null}
                        </>
                      )}
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </div>
      </Dialog>
      {confirmDialog}
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* 科目维护（taxonomyApi 科目 CRUD）                                          */
/* -------------------------------------------------------------------------- */
export function SubjectMgrDialog({ open, onClose, onSubjectsChanged }) {
  const [confirm, confirmDialog] = useConfirm()
  const [state, setState] = useState('idle')
  const [items, setItems] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState(null) // { mode, original, name }
  const loadedRef = useRef(false)
  const nameRef = useRef(null)

  const load = useCallback(async () => {
    setState('loading')
    setError('')
    try {
      const d = await taxonomyApi.subjects()
      const list = Array.isArray(d) ? d : (d?.subjects || d?.items || [])
      setItems(Array.isArray(list) ? list : [])
      setState('ok')
      return true
    } catch (e) {
      setItems([])
      setError(e?.message || '科目列表加载失败')
      setState('error')
      return false
    }
  }, [])

  useEffect(() => {
    if (open && !loadedRef.current) {
      setEditor(null)
      load()
    }
    loadedRef.current = open
  }, [open, load])

  useEffect(() => {
    if (editor) nameRef.current?.focus?.()
  }, [editor])

  const nameOf = (s) => s?.subject || s?.name || ''
  const metaOf = (s) => {
    const parts = []
    if (s?.unregistered) parts.push('未登记')
    else if (s?.is_custom) parts.push('自定义')
    else parts.push('内置')
    if (s?.question_count != null) parts.push(`${s.question_count} 题`)
    if (s?.document_count != null) parts.push(`${s.document_count} 篇资料`)
    return parts.join(' · ')
  }

  const submit = async () => {
    if (!editor) return
    const name = editor.name.trim()
    if (!name) { toastErr('请填写科目名称'); nameRef.current?.focus?.(); return }
    setBusy(true)
    try {
      if (editor.mode === 'create') {
        await taxonomyApi.createSubject({ subject: name })
        toastOk('科目已添加')
      } else {
        await taxonomyApi.updateSubject(editor.original, { subject: name })
        toastOk('科目已更新')
      }
      setEditor(null)
      await load()
      onSubjectsChanged?.()
    } catch (e) {
      toastErr(`保存失败：${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (item) => {
    const n = Number(item?.question_count) || 0
    const ok = await confirm({
      title: '删除科目',
      message: n > 0
        ? `科目「${nameOf(item)}」下已有 ${n} 道题目，删除后这些题目将失去科目归属，确定删除吗？`
        : `确定删除科目「${nameOf(item)}」吗？`,
      danger: true,
      confirmText: '删除',
    })
    if (!ok) return
    setBusy(true)
    try {
      await taxonomyApi.removeSubject(nameOf(item))
      toastOk('科目已删除')
      await load()
      onSubjectsChanged?.()
    } catch (e) {
      toastErr(`删除失败：${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  const refresh = async () => {
    const ok = await load()
    if (ok) toastOk('科目列表已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  return (
    <>
      <Dialog
        open={open}
        wide
        title="科目维护"
        sub="增删改科目走 /taxonomy/subjects，不硬编码科目清单"
        onClose={onClose}
        footer={<Button variant="filled" size="sm" onClick={onClose}>关闭</Button>}
      >
        <div className="dv3-subjmgr">
          <div className="dv3-subjmgr__bar">
            <Badge tone="outline">共 {items.length} 个科目</Badge>
            <div className="dv3-subjmgr__bar-actions">
              <Button variant="text" size="sm" icon={<RefreshCw size={14} />} disabled={busy || state === 'loading'} onClick={refresh}>
                刷新
              </Button>
              <Button
                variant="filled"
                size="sm"
                icon={<Plus size={14} />}
                disabled={busy}
                onClick={() => setEditor({ mode: 'create', original: '', name: '' })}
              >
                添加科目
              </Button>
            </div>
          </div>

          {editor ? (
            <div className="dv3-subjmgr__form">
              <Field label={editor.mode === 'create' ? '新科目名称' : `编辑「${editor.original}」`}>
                <Input
                  ref={nameRef}
                  value={editor.name}
                  onChange={(e) => setEditor((s) => ({ ...s, name: e.target.value }))}
                  placeholder="如：数字电子技术"
                  aria-label="科目名称"
                  onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
                />
              </Field>
              <div className="dv3-subjmgr__form-actions">
                <Button variant="text" size="sm" disabled={busy} onClick={() => setEditor(null)}>取消</Button>
                <Button variant="filled" size="sm" loading={busy} onClick={submit}>保存</Button>
              </div>
            </div>
          ) : null}

          {state === 'loading' && items.length === 0 ? (
            <div className="dv3-skel" aria-busy="true">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={48} width="100%" />)}
            </div>
          ) : state === 'error' ? (
            <Empty
              icon={<AlertCircle size={24} />}
              title="科目列表加载失败"
              text={error}
              action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={refresh}>重试</Button>}
            />
          ) : items.length === 0 ? (
            <Empty
              icon={<FolderOpen size={24} />}
              title="暂无科目"
              text="点击「添加科目」创建第一个科目。"
              action={<Button variant="tonal" size="sm" icon={<Plus size={14} />} onClick={() => setEditor({ mode: 'create', original: '', name: '' })}>添加科目</Button>}
            />
          ) : (
            <div className="dv3-subjmgr__list">
              {items.map((s) => (
                <div className="dv3-subjmgr__row" key={nameOf(s)}>
                  <div className="dv3-subjmgr__main">
                    <div className="dv3-subjmgr__name">{nameOf(s)}</div>
                    <div className="dv3-subjmgr__meta">{metaOf(s)}</div>
                  </div>
                  <div className="dv3-subjmgr__actions">
                    <Button
                      variant="text"
                      size="sm"
                      icon={<Edit size={13} />}
                      disabled={busy}
                      onClick={() => setEditor({ mode: 'edit', original: nameOf(s), name: nameOf(s) })}
                    >
                      编辑
                    </Button>
                    <Button
                      variant="text"
                      size="sm"
                      icon={<Trash size={13} />}
                      disabled={busy}
                      onClick={() => remove(s)}
                    >
                      删除
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Dialog>
      {confirmDialog}
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* 原文件预览（GET /documents/{id}/raw，后端支持 Range）                      */
/* -------------------------------------------------------------------------- */
const INLINE_EXT = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'txt', 'md', 'markdown', 'csv', 'html']
const canInlinePreview = (doc) => {
  const ext = String(doc?.filename || doc?.file_name || '').toLowerCase().split('.').pop()
  return INLINE_EXT.includes(ext) || INLINE_EXT.includes(String(doc?.file_type || '').toLowerCase())
}

export function RawFilePreviewDialog({ doc, onClose }) {
  const download = () => {
    if (!doc) return
    const a = document.createElement('a')
    a.href = documentsApi.downloadUrl(doc.id)
    a.download = doc.filename || ''
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  const openWindow = () => {
    if (!doc) return
    window.open(documentsApi.rawUrl(doc.id), '_blank', 'noopener,noreferrer')
  }

  return (
    <Dialog
      open={!!doc}
      wide
      title={doc ? `原文件预览 · ${doc.filename}` : '原文件预览'}
      sub="浏览器直接渲染磁盘上的原文件，后端支持 Range 分片"
      onClose={onClose}
      footer={(
        <>
          {doc && canInlinePreview(doc) ? (
            <Button variant="text" size="sm" icon={<FileText size={14} />} onClick={openWindow}>新窗口打开</Button>
          ) : null}
          {doc ? <Button variant="tonal" size="sm" icon={<FolderOpen size={14} />} onClick={download}>下载原文件</Button> : null}
          <Button variant="filled" size="sm" onClick={onClose}>关闭</Button>
        </>
      )}
    >
      {doc && canInlinePreview(doc) ? (
        <div className="dv3-raw">
          <iframe className="dv3-raw__frame" title="原文件预览" src={documentsApi.rawUrl(doc.id)} />
        </div>
      ) : doc ? (
        <div className="dv3-raw__note">
          <FileText size={28} />
          <b>该文件类型（{doc.file_type || doc.doc_type || '未知'}）浏览器不能直接渲染</b>
          <p>请下载原文件后用本地应用打开。{doc.size ? ` · 大小 ${fmtBytes(doc.size)}` : ''}</p>
          <Button variant="tonal" size="sm" icon={<FolderOpen size={14} />} onClick={download}>下载原文件</Button>
        </div>
      ) : null}
    </Dialog>
  )
}
