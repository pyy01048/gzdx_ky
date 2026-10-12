import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { documentsApi } from '../api/client'
import { toast, Empty, Segmented } from '../components/UI'
import {
  RefreshCw, Folder, FileText, AlertCircle, ChevronDown, ChevronRight,
} from '../components/Icon'
import './Library.css'

/* ==========================================================================
   学习文库（Library）
   --------------------------------------------------------------------------
   把 IMA 知识库导入的资料按「备考阶段 → 科目 → 内容性质」三级展示，
   信息架构对标研码「学习文库」（抄结构、不抄视觉）。

   数据来源：GET /api/documents（documentsApi.list，参数原样透传）
     - subject_source=ima  只看 IMA 导入的资料
     - stage               初试 / 复试
     - subject             数模电 / 408 / 信号与系统 / 公共课-* / 其他
     - content_type        知识 / 试题 / 单词

   两个请求的分工（都是同一个接口，只是参数不同）：
     ① 清单请求：带上全部生效筛选条件 → 服务端过滤，结果直接渲染；
     ② 计数请求（facet）：只带 stage → 拿到该阶段全量，用于算每个 chip 的条数。
   后端 /documents 无分页（routers/documents.py:101 一次性返回全部），
   所以面额统计是精确的，不会因分页而少算。
   ========================================================================== */

/* 备考阶段（顶部 segmented 切换） */
const STAGE_OPTIONS = [
  { value: '初试', label: '初试' },
  { value: '复试', label: '复试' },
]

/* 科目选项：专业课并列；公共课三个子项归入「公共课」分组，避免一行里三个
   「公共课-xx」长标签把 chip 挤爆。value 必须与后端 Document.subject 取值一致。 */
const SUBJECT_OPTIONS = [
  { value: '', label: '全部' },
  { value: '数模电', label: '数模电' },
  { value: '408', label: '408' },
  { value: '信号与系统', label: '信号与系统' },
  { value: '公共课-数学', label: '数学', group: '公共课' },
  { value: '公共课-政治', label: '政治', group: '公共课' },
  { value: '公共课-英语', label: '英语', group: '公共课' },
  { value: '其他', label: '其他' },
]

/* 内容性质（与后端 Document.content_type 取值一致） */
const CONTENT_TYPE_OPTIONS = [
  { value: '', label: '全部' },
  { value: '知识', label: '知识' },
  { value: '试题', label: '试题' },
  { value: '单词', label: '单词' },
]

/* 内容性质 → 徽标配色类（沿用 global.css 的 soft 色令牌） */
const CT_CLASS = {
  知识: 'knowledge',
  试题: 'exercise',
  单词: 'word',
}

/* 资料层级（doc_type）→ 中文：raw 原始层 / note 加工层 / index 索引层 */
const DOC_TYPE_LABEL = {
  raw: '原始',
  note: '加工',
  index: '索引',
}

/** 兼容 /documents 的多种返回形态：数组 / {documents:[]} / {items:[]} / {docs:[]} */
function normalizeList(data) {
  if (Array.isArray(data)) return data
  if (data && Array.isArray(data.documents)) return data.documents
  if (data && Array.isArray(data.items)) return data.items
  if (data && Array.isArray(data.docs)) return data.docs
  return []
}

/** 文件大小格式化：B / KB / MB / GB（<1KB 显示字节，0 或缺失显示 —） */
function fmtSize(n) {
  const b = Number(n) || 0
  if (b <= 0) return '—'
  if (b >= 1024 * 1024 * 1024) return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
  if (b >= 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  if (b >= 1024) return `${Math.round(b / 1024)} KB`
  return `${b} B`
}

/** 是否已解析：正文长度或分块数任一 > 0 即视为已入库可检索 */
function isParsed(d) {
  return (Number(d?.content_length) || 0) > 0 || (Number(d?.chunk_count) || 0) > 0
}

/** 按字段计数（用于 chip 上的条数角标） */
function countBy(list, field) {
  const m = {}
  for (const it of list) {
    const k = it?.[field] || ''
    m[k] = (m[k] || 0) + 1
  }
  return m
}

/** 组装请求参数：空值不下发，避免后端把空串当精确匹配条件 */
function buildParams(stage, subject, contentType) {
  const p = { subject_source: 'ima', stage }
  if (subject) p.subject = subject
  if (contentType) p.content_type = contentType
  return p
}

export default function Library() {
  const [stage, setStage] = useState('初试')
  const [subject, setSubject] = useState('')
  const [contentType, setContentType] = useState('')

  const [items, setItems] = useState([])        // 当前筛选组合下的资料（服务端过滤）
  const [facet, setFacet] = useState([])        // 当前阶段全量（用于 chip 计数）
  const [status, setStatus] = useState('loading') // loading | ok | error
  const [loading, setLoading] = useState(false)   // 清单请求进行中（含切筛选时的刷新）
  const [errMsg, setErrMsg] = useState('')

  // 正文预览：就地展开，一次只展开一条
  const [openId, setOpenId] = useState(null)
  const [preview, setPreview] = useState({ id: null, state: 'idle', text: '', note: '' })
  // openId 的镜像 ref：异步回调里读 state 会拿到渲染时的旧值，这里用 ref 取当前值
  const openIdRef = useRef(null)

  /* 请求序号：快速连点筛选时丢弃过期响应，避免旧结果覆盖新结果 */
  const listSeq = useRef(0)

  /* ---------------- 清单请求（随 阶段/科目/内容性质 变化重拉） ---------------- */
  const loadList = useCallback(async () => {
    const seq = ++listSeq.current
    setLoading(true)
    try {
      const data = await documentsApi.list(buildParams(stage, subject, contentType))
      if (seq !== listSeq.current) return // 已过期，丢弃
      setItems(normalizeList(data))
      setStatus('ok')
      setErrMsg('')
    } catch (e) {
      if (seq !== listSeq.current) return
      setItems([])
      setErrMsg(e?.message || '未知错误')
      setStatus('error')
    } finally {
      if (seq === listSeq.current) setLoading(false)
    }
  }, [stage, subject, contentType])

  useEffect(() => { loadList() }, [loadList])

  /* ---------------- 计数请求（facet）（只在阶段变化时重拉，用于 chip 计数） ---------------- */
  useEffect(() => {
    let alive = true
    documentsApi
      .list({ subject_source: 'ima', stage })
      .then((d) => { if (alive) setFacet(normalizeList(d)) })
      .catch(() => { if (alive) setFacet([]) }) // 计数失败不影响清单本身，静默降级为不显示条数
    return () => { alive = false }
  }, [stage])

  /* ---------------- chip 计数：交叉计数（facet）（选了科目就按科目统计内容性质，反之亦然） ---------------- */
  const subjectCounts = useMemo(
    () => countBy(facet.filter((d) => !contentType || d.content_type === contentType), 'subject'),
    [facet, contentType]
  )
  const ctCounts = useMemo(
    () => countBy(facet.filter((d) => !subject || d.subject === subject), 'content_type'),
    [facet, subject]
  )

  /* ---------------- 切换筛选：收起预览，避免残留上一条的正文 ---------------- */
  const closePreview = () => {
    openIdRef.current = null
    setOpenId(null)
    setPreview({ id: null, state: 'idle', text: '', note: '' })
  }
  const pickSubject = (v) => {
    closePreview()
    setSubject(v)
  }
  const pickContentType = (v) => {
    closePreview()
    setContentType(v)
  }
  const pickStage = (v) => {
    closePreview()
    setStage(v)
  }

  /* ---------------- 点击文件名：就地展开正文预览 ----------------
     后端 GET /documents/{id}/content 返回 {content, content_length, truncated, message}；
     未解析的文档返回空 content + message，这里如实展示，不硬造内容。 */
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
      if (openIdRef.current !== id) return // 用户已收起/切换，丢弃这次结果
      const text = (r && typeof r.content === 'string') ? r.content : ''
      setPreview({
        id,
        state: 'ok',
        text,
        note: text
          ? `已解析 ${Number(r?.content_length) || text.length} 字${r?.truncated ? '（预览已截断）' : ''}`
          : (r?.message || '该资料尚未解析正文'),
      })
    } catch (e) {
      if (openIdRef.current !== id) return
      setPreview({ id, state: 'error', text: '', note: e?.message || '正文加载失败' })
      toast('正文加载失败：' + (e?.message || ''))
    }
  }

  /* ---------------- 三态：加载中（首次） ---------------- */
  if (status === 'loading') {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1 className="page-title">学习文库</h1>
            <div className="page-sub">初试 / 复试 · 科目 · 知识 / 试题 / 单词 三维检索 IMA 资料</div>
          </div>
        </div>
        <div className="card lb-card">
          <div className="card-head">
            <div>
              <div className="card-title">资料清单</div>
              <div className="card-sub">正在读取 IMA 知识库…</div>
            </div>
          </div>
          <div className="card-body">
            <div className="lb-skel-list">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div className="lb-skel-row" key={i}>
                  <span className="lb-skel w1" />
                  <span className="lb-skel w60" />
                  <span className="lb-skel w90" />
                  <span className="lb-skel w46" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  /* ---------------- 三态：失败（就地提示 + 重试） ---------------- */
  if (status === 'error') {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1 className="page-title">学习文库</h1>
            <div className="page-sub">初试 / 复试 · 科目 · 知识 / 试题 / 单词 三维检索 IMA 资料</div>
          </div>
        </div>
        <div className="card lb-error-card">
          <div className="lb-error-icon"><AlertCircle size={28} /></div>
          <div>
            <div className="lb-error-title">资料加载失败</div>
            <div className="lb-error-desc">{errMsg || '请确认后端服务已启动后重试。'}</div>
            <button className="btn ghost" onClick={loadList}>
              <RefreshCw size={14} /> 重新加载
            </button>
          </div>
        </div>
      </div>
    )
  }

  const subjectLabel = SUBJECT_OPTIONS.find((o) => o.value === subject)?.label || '全部'
  const ctLabel = contentType || '全部'

  return (
    <div className="page">
      {/* 页头 */}
      <div className="page-head">
        <div>
          <h1 className="page-title">学习文库</h1>
          <div className="page-sub">初试 / 复试 · 科目 · 知识 / 试题 / 单词 三维检索 IMA 资料</div>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={loadList} disabled={loading}>
            <RefreshCw size={15} /> 刷新
          </button>
        </div>
      </div>

      {/* 顶部一行：初试 / 复试 切换 + 当前结果条数 */}
      <div className="lb-topbar">
        <Segmented options={STAGE_OPTIONS} value={stage} onChange={pickStage} />
        <div className="lb-count">
          共 <b>{items.length}</b> 条 · {stage} / {subjectLabel} / {ctLabel}
          {loading && ' · 加载中…'}
        </div>
      </div>

      {/* 科目筛选 */}
      <div className="lb-filterbar">
        <Folder size={15} className="lb-filterbar-icon" />
        <span className="lb-filter-label">科目</span>
        <div className="kb-chips">
          {SUBJECT_OPTIONS.map((o, i) => {
            const prev = SUBJECT_OPTIONS[i - 1]
            const needGroup = o.group && (!prev || prev.group !== o.group)
            const n = subjectCounts[o.value] || 0
            return (
              <React.Fragment key={o.value || 'all'}>
                {needGroup && <span className="lb-chip-group">{o.group}</span>}
                <button
                  className={`kb-chip ${subject === o.value ? 'active' : ''}`}
                  onClick={() => pickSubject(o.value)}
                >
                  {o.label}
                  {n > 0 && <small>{n}</small>}
                </button>
              </React.Fragment>
            )
          })}
        </div>
      </div>

      {/* 内容性质筛选 */}
      <div className="lb-filterbar">
        <FileText size={15} className="lb-filterbar-icon" />
        <span className="lb-filter-label">性质</span>
        <div className="kb-chips">
          {CONTENT_TYPE_OPTIONS.map((o) => {
            const n = ctCounts[o.value] || 0
            return (
              <button
                key={o.value || 'all'}
                className={`kb-chip ${contentType === o.value ? 'active' : ''}`}
                onClick={() => pickContentType(o.value)}
              >
                {o.label}
                {n > 0 && <small>{n}</small>}
              </button>
            )
          })}
        </div>
      </div>

      {/* 资料清单 */}
      <div className="card lb-card">
        <div className="card-head">
          <div>
            <div className="card-title">资料清单</div>
            <div className="card-sub">
              {items.length === 0
                ? '当前筛选组合下没有资料'
                : `${items.length} 条资料 · 点击文件名可展开正文预览`}
            </div>
          </div>
        </div>
        <div className="card-body">
          {items.length === 0 ? (
            <Empty
              icon={<Folder size={44} />}
              title={`「${stage} · ${subjectLabel} · ${ctLabel}」下暂无资料`}
              desc={
                facet.length === 0
                  ? '当前阶段还没有 IMA 导入记录，可先在「网盘联动 / 文档知识库」导入资料。'
                  : '数据里确实没有符合该组合的资料——换个科目或内容性质看看（例如「单词」目前仅有少量资料）。'
              }
            />
          ) : (
            <div className="lb-list">
              {items.map((d) => {
                const open = openId === d.id
                const parsed = isParsed(d)
                const ct = d.content_type || ''
                return (
                  <div className={`lb-row ${open ? 'open' : ''}`} key={d.id ?? d.file_name}>
                    <button
                      className="lb-row-head"
                      onClick={() => togglePreview(d)}
                      title="点击展开正文预览"
                      aria-expanded={open}
                    >
                      {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      <span className="lb-name">{d.file_name || '未命名资料'}</span>
                      <span className={`lb-ct ${CT_CLASS[ct] || 'unknown'}`}>
                        {ct || '未分类'}
                      </span>
                      <span className="lb-subj">{d.subject || '未分类'}</span>
                      <span className="lb-meta">
                        {DOC_TYPE_LABEL[d.doc_type] || d.file_type || '—'} · {fmtSize(d.size)}
                        {(Number(d.chunk_count) || 0) > 0 && ` · ${d.chunk_count} 分块`}
                      </span>
                      <span className={`lb-state ${parsed ? 'ok' : ''}`}>
                        {parsed ? '已解析' : '未解析'}
                      </span>
                      <span className="lb-src">{d.subject_source === 'ima' ? 'IMA' : (d.subject_source || '本地')}</span>
                    </button>

                    {/* IMA 原始目录（次要信息） */}
                    <div className="lb-path" title={d.folder_path || ''}>
                      {d.folder_path || '无 IMA 目录信息'}
                    </div>

                    {open && (
                      <div className="lb-preview">
                        <div className="lb-preview-head">
                          <span>正文预览</span>
                          <span>{d.file_type || ''}</span>
                          {d.summary ? <span>· {d.summary.slice(0, 60)}</span> : null}
                        </div>
                        {preview.id === d.id && preview.state === 'loading' && (
                          <div className="loading-inline">正文加载中…</div>
                        )}
                        {preview.id === d.id && preview.state !== 'loading' && (
                          <>
                            {preview.text
                              ? <div className="lb-preview-body">{preview.text}</div>
                              : <div className="lb-preview-empty">{preview.note || '暂无正文'}</div>}
                            {preview.text && preview.note && (
                              <div className="lb-preview-head" style={{ marginTop: 8, marginBottom: 0 }}>
                                <span>{preview.note}</span>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
