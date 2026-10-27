import React, { useEffect, useMemo, useRef, useState } from 'react'
import { documentsApi } from '../../api/client'
import { fmtBytes } from '../../utils/format'
import {
  Badge, Button, Chip, Dialog, Empty, Skeleton, Tabs, toast, toastErr, toastOk, cx,
} from '../ui'
import {
  AlertCircle, Brain, Download, FileText, FolderOpen, Layers, ListChecks, RefreshCw, Tag,
} from '../icons'
import { docStateOf, governanceApi, isEmptyBody, kpItems } from './documentsV3Shared'
import { useAuth } from '../../auth/AuthContext'

/* ==========================================================================
   文档知识库 · 文档详情抽屉（Aurora v3）
   · 快照：GET  /documents/{id}/snapshot
   · 导出：GET  /documents/{id}/export?fmt=md|txt|pdf（PDF 缺失依赖时后端降级）
   · 知识点：GET /documents/{id}/knowledge-points（裸数组契约）
   · 分块：GET  /documents/{id}/chunks
   · 题目预览：POST /documents/{id}/preview-questions（只读预览，不写题库）
   · 归档：POST /documents/{id}/archive（由页面统一确认）
   所有区块独立三态；任何接口失败都显式报错，不用空数组冒充「没有」。
   ========================================================================== */

const TABS = (points, chunks, questions, canManage) => [
  { value: 'overview', label: '概览' },
  { value: 'points', label: '知识点', count: points },
  { value: 'chunks', label: '分块', count: chunks },
  ...(canManage ? [{ value: 'questions', label: '题目预览', count: questions }] : []),
]

function PanelSkeleton({ rows = 3 }) {
  return (
    <div className="dv3-skel" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} height={12} width={`${92 - i * 13}%`} />
      ))}
    </div>
  )
}

function PanelError({ text, onRetry }) {
  return (
    <Empty
      icon={<AlertCircle size={24} />}
      title="加载失败"
      text={text || '请稍后重试'}
      action={<Button variant="tonal" size="sm" icon={<RefreshCw size={14} />} onClick={onRetry}>重试</Button>}
    />
  )
}

export default function DocumentsDetail({
  open, doc, tab, onTab, onClose, backendOk,
  parsingId, analyzingId, onParse, onAnalyze, onGenerateQuiz, onArchive,
}) {
  const { isAdmin } = useAuth()
  const [snapshot, setSnapshot] = useState({ state: 'idle', md: '', path: '', exists: false, error: '' })
  const [snapRetry, setSnapRetry] = useState(0)
  const [kp, setKp] = useState({ state: 'idle', list: [], error: '' })
  const [chunks, setChunks] = useState({ state: 'idle', list: [], error: '' })
  const [questions, setQuestions] = useState({ state: 'idle', list: [], total: 0, error: '' })
  const [kpSubject, setKpSubject] = useState('all')
  const tokenRef = useRef(0)

  const empty = isEmptyBody(doc)
  const state = docStateOf(doc)
  const activeTab = !isAdmin && tab === 'questions' ? 'overview' : tab

  /* 切换文档：作废旧请求并清空各区块 */
  useEffect(() => {
    tokenRef.current += 1
    setKp({ state: 'idle', list: [], error: '' })
    setChunks({ state: 'idle', list: [], error: '' })
    setQuestions({ state: 'idle', list: [], total: 0, error: '' })
    setKpSubject('all')
  }, [doc?.id, open])

  /* Markdown 快照 */
  useEffect(() => {
    if (!open || !doc) return undefined
    let alive = true
    setSnapshot({ state: 'loading', md: '', path: '', exists: false, error: '' })
    governanceApi.snapshot(Number(doc.id))
      .then((r) => {
        if (!alive) return
        setSnapshot({
          state: 'ok',
          md: r?.markdown || '',
          path: r?.snapshot_path || '',
          exists: !!r?.snapshot_exists,
          error: '',
        })
      })
      .catch((e) => {
        if (!alive) return
        setSnapshot({ state: 'error', md: '', path: '', exists: false, error: e?.message || '' })
        toastErr(`读取快照失败：${e?.message || e}`)
      })
    return () => { alive = false }
  }, [open, doc?.id, snapRetry])

  const loadPoints = async () => {
    if (!doc) return
    const token = tokenRef.current
    setKp({ state: 'loading', list: [], error: '' })
    try {
      const r = await documentsApi.knowledgePoints(Number(doc.id))
      if (token !== tokenRef.current) return
      setKp({ state: 'ok', list: kpItems(r), error: '' })
    } catch (e) {
      if (token !== tokenRef.current) return
      setKp({ state: 'error', list: [], error: e?.message || '获取知识点失败' })
      toastErr(`获取知识点失败：${e?.message || e}`)
    }
  }

  const loadChunks = async () => {
    if (!doc) return
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
      toastErr(`获取分块失败：${e?.message || e}`)
    }
  }

  const loadQuestions = async () => {
    if (!doc) return
    const token = tokenRef.current
    setQuestions({ state: 'loading', list: [], total: 0, error: '' })
    try {
      const r = await documentsApi.previewQuestions(Number(doc.id))
      if (token !== tokenRef.current) return
      if (!r || !Array.isArray(r.questions)) throw new Error('题目预览响应格式无法识别')
      const total = r.total ?? r.questions.length
      setQuestions({ state: 'ok', list: r.questions, total, error: '' })
      toast(`预览到 ${total} 道题目，请人工审核`)
    } catch (e) {
      if (token !== tokenRef.current) return
      setQuestions({ state: 'error', list: [], total: 0, error: e?.message || '预览失败' })
      toastErr(`预览失败：${e?.message || e}`)
    }
  }

  /* 仅当前页签需要的请求才发出；切页/重开不会重复空转 */
  useEffect(() => {
    if (!open || !doc) return
    if (activeTab === 'points' && kp.state === 'idle') loadPoints()
    if (activeTab === 'chunks' && chunks.state === 'idle') loadChunks()
    if (activeTab === 'questions' && questions.state === 'idle') loadQuestions()
  }, [open, doc?.id, activeTab, kp.state, chunks.state, questions.state])

  const kpName = (k) => k?.name || k?.point || k?.title || '未命名知识点'
  const kpDesc = (k) => (k?.description || k?.summary || '').trim()

  const kpFacets = useMemo(() => {
    const map = new Map()
    kp.list.forEach((k) => {
      const s = k?.subject || doc?.subject || '未分类'
      map.set(s, (map.get(s) || 0) + 1)
    })
    return Array.from(map.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
  }, [kp.list, doc?.subject])

  const kpShown = useMemo(
    () => (kpSubject === 'all'
      ? kp.list
      : kp.list.filter((k) => (k?.subject || doc?.subject || '未分类') === kpSubject)),
    [kp.list, kpSubject, doc?.subject],
  )

  const exportDoc = async (fmt) => {
    if (!doc) return
    try {
      const resp = await fetch(governanceApi.exportUrl(doc.id, fmt))
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const degraded = resp.headers.get('X-Export-Degraded') === '1'
      if (degraded) toast('PDF 渲染依赖缺失，已降级导出 Markdown（内容一致）')
      const blob = await resp.blob()
      const cd = resp.headers.get('content-disposition') || ''
      const m = /filename\*=UTF-8''([^;]+)/i.exec(cd)
      const fname = m
        ? decodeURIComponent(m[1])
        : `${(doc.filename || 'document').replace(/\.[^.]+$/, '')}.${fmt}`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = fname
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 4000)
      if (!degraded) toastOk(`已导出 ${fname}`)
    } catch (e) {
      toastErr(`导出失败：${e?.message || e}`)
    }
  }

  const downloadOriginal = () => {
    if (!doc) return
    const a = document.createElement('a')
    a.href = documentsApi.downloadUrl(doc.id)
    a.download = doc.filename || ''
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  if (!doc) return null

  const tabOptions = TABS(
    kp.state === 'ok' ? kp.list.length : null,
    chunks.state === 'ok' ? chunks.list.length : null,
    questions.state === 'ok' ? (questions.total ?? questions.list.length) : null,
    isAdmin,
  )

  return (
    <Dialog
      open={!!open}
      wide
      className="dv3-drawer"
      title="文档详情"
      sub={doc.filename}
      onClose={onClose}
      footer={(
        <>
          <Button variant="text" size="sm" onClick={() => exportDoc('md')}>导出 MD</Button>
          <Button variant="text" size="sm" onClick={() => exportDoc('txt')}>导出 TXT</Button>
          <Button
            variant="text"
            size="sm"
            onClick={() => exportDoc('pdf')}
            title="PDF 依赖不可用时后端会降级为 Markdown 并提示"
          >
            导出 PDF
          </Button>
          <Button variant="filled" size="sm" onClick={onClose}>关闭</Button>
        </>
      )}
    >
      <div className="dv3-drawer__meta">
        <Badge tone="primary">{doc.subject || '未分类'}</Badge>
        <Badge tone="outline">{doc.file_type || doc.doc_type || '未知类型'}</Badge>
        <Badge tone="outline">{fmtBytes(doc.size)}</Badge>
        <Badge tone={empty ? 'danger' : 'outline'}>
          {Number(doc.content_length || 0).toLocaleString('zh-CN')} 字
        </Badge>
        <Badge tone="outline">{Number(doc.chunk_count || 0).toLocaleString('zh-CN')} 分块</Badge>
        <Badge tone={state.tone}>{state.label}</Badge>
        {!doc.has_local_file ? (
          <Badge tone="warning" title={doc.local_file_note || '本地没有原文件'}>
            {doc.local_file_note || '本地无原文'}
          </Badge>
        ) : null}
      </div>

      <div className="dv3-drawer__tabs">
        <Tabs
          ariaLabel="文档详情页签"
          options={tabOptions}
          value={activeTab}
          onChange={(v) => onTab(v)}
        />
      </div>

      <div className="dv3-drawer__panel" aria-busy={activeTab === 'overview' ? snapshot.state === 'loading' : false}>
        {activeTab === 'overview' ? (
          <>
            {empty ? (
              <div className="dv3-drawer__note" role="status">
                <AlertCircle size={15} />
                <span>
                  {isAdmin
                    ? '正文缺失（documents.content 为空），建议重新解析后再导出或出题。'
                    : '正文缺失（documents.content 为空），请联系管理员重新解析后再阅读。'}
                </span>
              </div>
            ) : null}
            <div className="dv3-snap-head">
              <span>Markdown 快照预览</span>
              {snapshot.path ? (
                <span className="dv3-path" title={snapshot.path}>
                  {snapshot.exists ? '已落盘' : '未落盘'}：{snapshot.path.split(/[\\/]/).pop()}
                </span>
              ) : null}
            </div>
            {snapshot.state === 'loading' ? (
              <div className="dv3-pre" aria-busy="true"><PanelSkeleton rows={5} /></div>
            ) : snapshot.state === 'error' ? (
              <div className="dv3-pre is-error">
                <div>快照生成失败，可稍后重试{snapshot.error ? `（${snapshot.error}）` : ''}。</div>
                <Button
                  variant="tonal"
                  size="sm"
                  icon={<RefreshCw size={14} />}
                  onClick={() => setSnapRetry((n) => n + 1)}
                >
                  重新生成
                </Button>
              </div>
            ) : (
              <pre className="dv3-pre">{snapshot.md || '（该文档暂无正文，快照为空）'}</pre>
            )}
          </>
        ) : null}

        {activeTab === 'points' ? (
          kp.state === 'loading' ? <PanelSkeleton rows={4} />
            : kp.state === 'error' ? <PanelError text={kp.error} onRetry={loadPoints} />
              : kp.list.length === 0 ? (
                <Empty
                  icon={<Tag size={24} />}
                  title="该文档暂无知识点"
                  text="可对文档执行「智能分析」重新提取；也可能该文档不含可识别知识点。"
                />
              ) : (
                <>
                  {kpFacets.length > 1 ? (
                    <div className="dv3-kp-chips" role="group" aria-label="按科目筛选知识点">
                      <Chip active={kpSubject === 'all'} onClick={() => setKpSubject('all')}>
                        全部 <span className="dv3-chip-n">{kp.list.length}</span>
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
                      {kpShown.map((k, i) => (
                        <div className="dv3-kp" key={`${kpName(k)}-${i}`}>
                          <div className="dv3-kp__head">
                            <b>{kpName(k)}</b>
                            {k?.exam_frequency != null && k.exam_frequency !== '' ? (
                              <Badge tone="warning">出题频率 {String(k.exam_frequency)}</Badge>
                            ) : null}
                          </div>
                          <p>{kpDesc(k) || '（该知识点暂无描述，可对文档执行「智能分析」补全）'}</p>
                          {k?.subject ? <span className="dv3-kp__subj">{k.subject}</span> : null}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )
        ) : null}

        {activeTab === 'chunks' ? (
          chunks.state === 'loading' ? <PanelSkeleton rows={5} />
            : chunks.state === 'error' ? <PanelError text={chunks.error} onRetry={loadChunks} />
              : chunks.list.length === 0 ? (
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
              )
        ) : null}

        {activeTab === 'questions' ? (
          questions.state === 'loading' ? <PanelSkeleton rows={6} />
            : questions.state === 'error' ? <PanelError text={questions.error} onRetry={loadQuestions} />
              : questions.list.length === 0 ? (
                <Empty
                  icon={<ListChecks size={24} />}
                  title="未提取到题目"
                  text="可先执行「智能分析」，或该文档不含可识别题目。"
                />
              ) : (
                <>
                  <div className="dv3-panel-head">
                    <b>题目预览</b>
                    <span>共 {questions.total ?? questions.list.length} 道 · 仅预览，不会写入题库</span>
                  </div>
                  <div className="dv3-question-list">
                    {questions.list.map((q, i) => {
                      const options = Array.isArray(q?.options) ? q.options : []
                      return (
                        <div className="dv3-question" key={`${q?.id || i}`}>
                          <div className="dv3-question__head">
                            <span className="dv3-q-num">#{i + 1}</span>
                            {q?.question_type ? <Badge tone="outline">{q.question_type}</Badge> : null}
                            {q?.is_real ? <Badge tone="warning">真题</Badge> : null}
                          </div>
                          <div className="dv3-q-stem">{q?.question || q?.content || '（无题干）'}</div>
                          {options.length > 0 ? (
                            <div className="dv3-q-options">
                              {options.map((op, oi) => (
                                <div key={oi}>{String.fromCharCode(65 + oi)}. {op}</div>
                              ))}
                            </div>
                          ) : null}
                          <div className="dv3-q-meta">
                            {q?.answer ? <Badge tone="success">答案 {q.answer}</Badge> : null}
                            {q?.subject ? <Badge tone="outline">{q.subject}</Badge> : null}
                          </div>
                          {q?.analysis ? <div className="dv3-q-analysis">解析：{q.analysis}</div> : null}
                        </div>
                      )
                    })}
                  </div>
                </>
              )
        ) : null}
      </div>

      <div className="dv3-drawer__actions">
        {isAdmin ? (
          <>
            {empty ? (
              <Button
                variant="filled"
                size="sm"
                loading={parsingId === doc.id}
                onClick={() => onParse(doc.id)}
              >
                {parsingId === doc.id ? '解析中…' : '重新解析'}
              </Button>
            ) : null}
            <Button
              variant="tonal"
              size="sm"
              icon={<Brain size={14} />}
              loading={analyzingId === doc.id}
              onClick={() => onAnalyze(doc)}
            >
              {analyzingId === doc.id ? '分析中…' : '智能分析'}
            </Button>
            <Button
              variant="tonal"
              size="sm"
              icon={<ListChecks size={14} />}
              onClick={() => onGenerateQuiz(doc)}
            >
              出题（5 道）
            </Button>
          </>
        ) : (
          <span className="v3-caption dv3-drawer__readonly">
            只读预览：解析、智能分析与出题由管理员执行
          </span>
        )}
        <Button
          variant="text"
          size="sm"
          icon={<Download size={14} />}
          disabled={!doc.has_local_file}
          title={doc.has_local_file ? '下载磁盘上的原文件' : (doc.local_file_note || '本地没有原文件')}
          onClick={downloadOriginal}
        >
          下载原文件
        </Button>
        {isAdmin ? (
          <Button
            variant="text"
            size="sm"
            icon={<FolderOpen size={14} />}
            disabled={!doc.has_local_file || !backendOk}
            title={doc.has_local_file ? '归档源文件到 knowledge_base/_archive/' : '本地无原文，无法归档'}
            onClick={() => onArchive(doc)}
          >
            归档源文件
          </Button>
        ) : null}
      </div>

      <div className={cx('dv3-drawer__foot', 'v3-caption')}>
        <FileText size={13} />
        <span>快照与导出均基于服务端 Markdown；导出 PDF 依赖缺失时自动降级为 Markdown。</span>
      </div>
    </Dialog>
  )
}
