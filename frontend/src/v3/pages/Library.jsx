import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { documentsApi } from '../../api/client'
import { fmtBytes } from '../../utils/format'
import {
  AnimatedNumber, Badge, Button, Card, CardHead, Chip, Empty, IconButton, PageHeader,
  Segmented, Skeleton, Tile, toastErr, toastOk,
} from '../ui'
import {
  AlertCircle, CheckCircle2, ChevronDown, ChevronRight, FileText, Folder, FolderOpen,
  Layers, RefreshCw, Upload,
} from '../icons'
import { useAuth } from '../../auth/AuthContext'
import '../styles/library-v3.css'

/* ==========================================================================
   学习文库（Aurora v3）
   数据源：GET /api/documents（documentsApi.list，参数原样透传）
     - subject_source=ima  只看 IMA 导入的资料
     - stage               初试 / 复试
     - subject             科目
     - content_type        知识 / 试题 / 单词
   两个请求：清单请求（全部筛选条件）+ 计数请求（只带阶段，用于 chip 条数）。
   ========================================================================== */

const STAGE_OPTIONS = [
  { value: '初试', label: '初试' },
  { value: '复试', label: '复试' },
]

const CONTENT_TYPE_OPTIONS = [
  { value: '', label: '全部性质' },
  { value: '知识', label: '知识' },
  { value: '试题', label: '试题' },
  { value: '单词', label: '单词' },
]

/* 内容性质 → Badge 语义色 */
const CT_TONE = {
  知识: 'primary',
  试题: 'warning',
  单词: 'success',
}

/* 资料层级（doc_type）→ 中文 */
const DOC_TYPE_LABEL = {
  raw: '原始',
  note: '加工',
  index: '索引',
}

/** 兼容 /documents 的多种返回形态 */
function normalizeList(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.documents)) return data.documents
  if (data && Array.isArray(data.items)) return data.items
  if (data && Array.isArray(data.docs)) return data.docs
  return []
}

/** 正文长度或分块数任一 > 0 即视为已解析 */
function isParsed(d) {
  return (Number(d?.content_length) || 0) > 0 || (Number(d?.chunk_count) || 0) > 0
}

/** 按字段计数 */
function countBy(list, field) {
  const m = {}
  for (const it of list) {
    const k = it?.[field] || ''
    m[k] = (m[k] || 0) + 1
  }
  return m
}

/** 组装请求参数：空值不下发 */
function buildParams(stage, subject, contentType) {
  const p = { subject_source: 'ima', stage }
  if (subject) p.subject = subject
  if (contentType) p.content_type = contentType
  return p
}

function StatTile({ icon, label, value, unit, hint }) {
  return (
    <Tile span={3} className="lb3-stat">
      <span className="v3-tile__label">{icon}{label}</span>
      <span className="v3-tile__value">
        <AnimatedNumber value={value} />
        <em>{unit}</em>
      </span>
      <span className="v3-tile__hint">{hint}</span>
    </Tile>
  )
}

export default function Library() {
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [searchParams] = useSearchParams()
  const urlSubject = searchParams.get('subject') || ''

  const [stage, setStage] = useState('初试')
  const [subject, setSubject] = useState(urlSubject)
  const [contentType, setContentType] = useState('')

  /* 全局学科选择器联动：URL ?subject= 变化时同步本地筛选 */
  useEffect(() => {
    setSubject(urlSubject)
  }, [urlSubject])

  /* 科目选项唯一来源：GET /api/documents/subjects（不硬编码科目数组） */
  const [subjectOptions, setSubjectOptions] = useState([])

  const [items, setItems] = useState([])
  const [facet, setFacet] = useState([])
  const [status, setStatus] = useState('loading') // loading | ok | error
  const [loading, setLoading] = useState(false)
  const [errMsg, setErrMsg] = useState('')

  useEffect(() => {
    let alive = true
    documentsApi.subjects()
      .then((d) => {
        if (!alive) return
        setSubjectOptions((d?.subjects || []).map((s) => s.name).filter(Boolean))
      })
      .catch(() => { if (alive) setSubjectOptions([]) })
    return () => { alive = false }
  }, [])

  /* 正文预览：一次只展开一条 */
  const [openId, setOpenId] = useState(null)
  const [preview, setPreview] = useState({ id: null, state: 'idle', text: '', note: '' })
  const openIdRef = useRef(null)
  const previewBoxRef = useRef(null)

  const scrollPreviewIntoView = () => {
    requestAnimationFrame(() => {
      const el = previewBoxRef.current
      if (el) {
        try { el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) } catch (e) { /* ignore */ }
      }
    })
  }

  /* 请求序号：快速切换筛选时丢弃过期响应 */
  const listSeq = useRef(0)

  const loadList = useCallback(async () => {
    const seq = ++listSeq.current
    setLoading(true)
    try {
      const data = await documentsApi.list(buildParams(stage, subject, contentType))
      if (seq !== listSeq.current) return false
      setItems(normalizeList(data))
      setStatus('ok')
      setErrMsg('')
      return true
    } catch (e) {
      if (seq !== listSeq.current) return false
      setItems([])
      setErrMsg(e?.message || '未知错误')
      setStatus('error')
      return false
    } finally {
      if (seq === listSeq.current) setLoading(false)
    }
  }, [stage, subject, contentType])

  useEffect(() => { loadList() }, [loadList])

  /* 手动刷新：只有用户点按钮才弹成败提示 */
  const refreshList = async () => {
    const ok = await loadList()
    if (ok) toastOk('资料列表已刷新')
    else toastErr('刷新失败，请检查后端服务后重试')
  }

  /* 计数请求（facet）：只在阶段变化时重拉 */
  useEffect(() => {
    let alive = true
    documentsApi.list({ subject_source: 'ima', stage })
      .then((d) => { if (alive) setFacet(normalizeList(d)) })
      .catch(() => { if (alive) setFacet([]) })
    return () => { alive = false }
  }, [stage])

  /* 交叉计数：选了科目按科目统计性质，反之亦然 */
  const subjectCounts = useMemo(
    () => countBy(facet.filter((d) => !contentType || d.content_type === contentType), 'subject'),
    [facet, contentType],
  )
  const ctCounts = useMemo(
    () => countBy(facet.filter((d) => !subject || d.subject === subject), 'content_type'),
    [facet, subject],
  )

  /* 科目 chip：以科目 API 为骨架，按本阶段实际计数收窄；数据里多出的补在末尾 */
  const subjectChips = useMemo(() => {
    const inData = Object.keys(subjectCounts).filter(Boolean)
    const base = subjectOptions.length
      ? subjectOptions.filter((s) => inData.includes(s))
      : inData
    const extra = inData.filter((s) => !base.includes(s))
    return [...base, ...extra]
  }, [subjectOptions, subjectCounts])

  const parsedCount = useMemo(() => facet.filter(isParsed).length, [facet])

  const closePreview = () => {
    openIdRef.current = null
    setOpenId(null)
    setPreview({ id: null, state: 'idle', text: '', note: '' })
  }
  const pickSubject = (v) => { closePreview(); setSubject(v) }
  const pickContentType = (v) => { closePreview(); setContentType(v) }
  const pickStage = (v) => { closePreview(); setStage(v) }

  /* 点击文件名：就地展开正文预览（GET /documents/{id}/content） */
  const togglePreview = async (doc) => {
    const id = doc?.id
    if (id == null) return
    if (openId === id) {
      closePreview()
      return
    }
    openIdRef.current = id
    setOpenId(id)
    setPreview({ id, state: 'loading', text: '', note: '' })
    try {
      const r = await documentsApi.getContent(id, 3000)
      if (openIdRef.current !== id) return
      const text = (r && typeof r.content === 'string') ? r.content : ''
      setPreview({
        id,
        state: 'ok',
        text,
        note: text
          ? `已解析 ${Number(r?.content_length) || text.length} 字${r?.truncated ? '（预览已截断）' : ''}`
          : (r?.message || '该资料尚未解析正文'),
      })
      scrollPreviewIntoView()
    } catch (e) {
      if (openIdRef.current !== id) return
      setPreview({ id, state: 'error', text: '', note: e?.message || '正文加载失败' })
      toastErr('正文加载失败：' + (e?.message || ''))
      scrollPreviewIntoView()
    }
  }

  const subjectLabel = subject || '全部科目'
  const ctLabel = contentType || '全部性质'

  const header = (
    <PageHeader
      eyebrow="LIBRARY · IMA 知识库"
      title="学习文库"
      sub="初试 / 复试 · 科目 · 知识 / 试题 / 单词 三维检索 IMA 资料"
      actions={(
        <>
          <IconButton
            label="刷新资料列表"
            icon={<RefreshCw size={17} />}
            onClick={refreshList}
            disabled={loading}
          />
          {isAdmin ? (
            <Button variant="tonal" icon={<Upload size={16} />} onClick={() => navigate('/documents')}>
              前往导入
            </Button>
          ) : null}
        </>
      )}
    />
  )

  /* ---------- 首次加载 ---------- */
  if (status === 'loading') {
    return (
      <div className="v3-stack v3-library">
        {header}
        <div className="v3-bento">
          {[0, 1, 2, 3].map((i) => (
            <Tile span={3} key={i} className="lb3-stat lb3-stat--skeleton">
              <Skeleton height={14} width="52%" />
              <Skeleton height={34} width="44%" style={{ marginTop: 18 }} />
              <Skeleton height={11} width="70%" style={{ marginTop: 10 }} />
            </Tile>
          ))}
        </div>
        <Card className="lb3-list-card">
          <CardHead
            icon={<Layers size={17} />}
            title="资料清单"
            sub="正在读取 IMA 知识库…"
          />
          <div className="lb3-skeleton-list">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div className="lb3-skel-row" key={i}>
                <Skeleton height={12} width="5%" />
                <Skeleton height={12} width={`${46 + (i % 3) * 12}%`} />
                <Skeleton height={12} width="14%" />
                <Skeleton height={12} width="18%" />
              </div>
            ))}
          </div>
        </Card>
      </div>
    )
  }

  /* ---------- 失败 ---------- */
  if (status === 'error') {
    return (
      <div className="v3-stack v3-library">
        {header}
        <Card className="lb3-error-card">
          <Empty
            icon={<AlertCircle size={26} />}
            title="资料加载失败"
            text={errMsg || '请确认后端服务已启动后重试。'}
            action={(
              <Button
                variant="tonal"
                icon={<RefreshCw size={16} />}
                loading={loading}
                onClick={() => loadList()}
              >
                重新加载
              </Button>
            )}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="v3-stack v3-library">
      {header}

      {/* 真实统计 */}
      <div className="v3-bento">
        <StatTile
          icon={<Folder size={15} />}
          label="本阶段资料"
          value={facet.length}
          unit="条"
          hint={`${stage} · 含全部科目与性质`}
        />
        <StatTile
          icon={<FileText size={15} />}
          label="当前结果"
          value={items.length}
          unit="条"
          hint={`${subjectLabel} · ${ctLabel}`}
        />
        <StatTile
          icon={<CheckCircle2 size={15} />}
          label="已解析"
          value={parsedCount}
          unit="条"
          hint="正文或分块已入库，可检索"
        />
        <StatTile
          icon={<Layers size={15} />}
          label="覆盖科目"
          value={subjectChips.length}
          unit="个"
          hint="按本阶段 IMA 实际数据收窄"
        />
      </div>

      {/* 筛选 */}
      <Card className="lb3-filter-card">
        <div className="lb3-filter-top">
          <Segmented
            ariaLabel="备考阶段"
            options={STAGE_OPTIONS}
            value={stage}
            onChange={pickStage}
          />
          <div className="lb3-filter-summary">
            <Badge tone={loading ? 'outline' : 'primary'}>{loading ? '同步中' : `共 ${items.length} 条`}</Badge>
            <span>
              {stage} / {subjectLabel} / {ctLabel}
              {loading ? ' · 加载中…' : ''}
            </span>
          </div>
        </div>

        <div className="lb3-filter-row">
          <span className="lb3-filter-label"><Folder size={15} />科目</span>
          <div className="lb3-chips">
            <Chip active={subject === ''} onClick={() => pickSubject('')}>
              全部科目
              {facet.length > 0 ? <span className="lb3-chip-count">{facet.length}</span> : null}
            </Chip>
            {subjectChips.map((name) => {
              const n = subjectCounts[name] || 0
              return (
                <Chip key={name} active={subject === name} onClick={() => pickSubject(name)}>
                  {name}
                  {n > 0 ? <span className="lb3-chip-count">{n}</span> : null}
                </Chip>
              )
            })}
            {subjectChips.length === 0 ? (
              <span className="lb3-filter-note">当前阶段暂无 IMA 资料</span>
            ) : null}
          </div>
        </div>

        <div className="lb3-filter-row">
          <span className="lb3-filter-label"><FileText size={15} />性质</span>
          <div className="lb3-chips">
            {CONTENT_TYPE_OPTIONS.map((o) => {
              const n = ctCounts[o.value] || 0
              return (
                <Chip
                  key={o.value || 'all'}
                  active={contentType === o.value}
                  onClick={() => pickContentType(o.value)}
                >
                  {o.label}
                  {n > 0 ? <span className="lb3-chip-count">{n}</span> : null}
                </Chip>
              )
            })}
          </div>
        </div>
      </Card>

      {/* 资料清单 */}
      <Card className="lb3-list-card">
        <CardHead
          icon={<Layers size={17} />}
          title="资料清单"
          sub={items.length === 0
            ? '当前筛选组合下没有资料'
            : `${items.length} 条资料 · 点击文件名可展开正文预览`}
          actions={<Badge tone="outline">IMA 来源</Badge>}
        />

        {items.length === 0 ? (
          <Empty
            icon={<Folder size={26} />}
            title={`「${stage} · ${subjectLabel} · ${ctLabel}」下暂无资料`}
            text={facet.length === 0
              ? (isAdmin
                ? '当前阶段还没有 IMA 导入记录，可先在「文档知识库」导入资料。'
                : '当前阶段还没有资料，导入由管理员在「文档知识库」统一维护。')
              : '数据里确实没有符合该组合的资料 —— 换个科目或内容性质看看。'}
            action={isAdmin
              ? <Button variant="gradient" icon={<Upload size={16} />} onClick={() => navigate('/documents')}>去导入资料</Button>
              : null}
          />
        ) : (
          <div className="lb3-list">
            {items.map((d) => {
              const open = openId === d.id
              const parsed = isParsed(d)
              const ct = d.content_type || ''
              const chunks = Number(d.chunk_count) || 0
              const stateLabel = parsed
                ? '已解析'
                : ((Number(d.content_length) || 0) === 0 ? '正文缺失' : '未解析')
              const stateTone = parsed ? 'success' : ((Number(d.content_length) || 0) === 0 ? 'warning' : 'outline')
              return (
                <div className={`lb3-row${open ? ' is-open' : ''}`} key={d.id ?? d.file_name}>
                  <button
                    type="button"
                    className="lb3-row__head"
                    onClick={() => togglePreview(d)}
                    title="点击展开正文预览"
                    aria-expanded={open}
                  >
                    <span className="lb3-row__chev">
                      {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    </span>
                    <span className="lb3-row__main">
                      <span className="lb3-row__name">{d.file_name || '未命名资料'}</span>
                      <span className="lb3-row__meta">
                        <Badge tone="outline">{d.subject || '未分类'}</Badge>
                        <span>
                          {DOC_TYPE_LABEL[d.doc_type] || d.file_type || '—'}
                          {' · '}
                          {fmtBytes(d.size)}
                          {chunks > 0 ? ` · ${chunks} 分块` : ''}
                        </span>
                        <span className="lb3-row__src">
                          {d.subject_source === 'ima' ? 'IMA' : (d.subject_source || '本地')}
                        </span>
                      </span>
                    </span>
                    <span className="lb3-row__badges">
                      <Badge tone={CT_TONE[ct]}>{ct || '未分类'}</Badge>
                      <Badge tone={stateTone}>{stateLabel}</Badge>
                    </span>
                  </button>

                  <div className="lb3-row__path" title={d.folder_path || ''}>
                    <FolderOpen size={13} />
                    <span>{d.folder_path || '无 IMA 目录信息'}</span>
                  </div>

                  {open ? (
                    <div className="lb3-preview" ref={previewBoxRef}>
                      <div className="lb3-preview__head">
                        <span className="lb3-preview__label">正文预览</span>
                        {d.file_type ? <Badge tone="outline">{d.file_type}</Badge> : null}
                        {d.summary ? <span className="lb3-preview__summary">{d.summary.slice(0, 60)}</span> : null}
                      </div>
                      {preview.id === d.id && preview.state === 'loading' ? (
                        <div className="lb3-preview__skeleton">
                          <Skeleton height={11} width="94%" />
                          <Skeleton height={11} width="86%" />
                          <Skeleton height={11} width="72%" />
                        </div>
                      ) : null}
                      {preview.id === d.id && preview.state !== 'loading' ? (
                        <>
                          {preview.text ? (
                            <div className="lb3-preview__body">{preview.text}</div>
                          ) : (
                            <div className="lb3-preview__empty">{preview.note || '暂无正文'}</div>
                          )}
                          {preview.text && preview.note ? (
                            <div className="lb3-preview__note">{preview.note}</div>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}
