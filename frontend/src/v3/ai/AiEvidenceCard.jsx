import React, { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '../ui'
import './ai-evidence.css'

/**
 * 共享 AI 证据卡（批次 C6，为批次 D「上岸经验进 RAG 后引用卡显示来源」打基础）。
 *
 * 统一呈现：引用编号 / 标题 / 原文片段 / 命中分 / 置信度 / 引擎标识 / 自定义字段。
 * 所有展示字段都是可选 props，缺字段时给明确占位，不编造来源。
 */

/** 引擎三态 + provider_override 本地 Ollama 的互斥标签 */
export const ENGINE_LABELS = {
  localLora: '本地 Qwen2.5-1.5B (LoRA)',
  online: '在线模型',
  localRules: '本地规则',
  localOllama: '本地模型',
}

/**
 * C-ENGINE-ENUM@1：后端统一引擎枚举到前端展示标签的映射。
 * engine_enum 取值：local-ollama / lora / cloud-api / local-rules
 */
export const ENGINE_ENUM_LABELS = {
  'local-ollama': ENGINE_LABELS.localOllama,
  lora: ENGINE_LABELS.localLora,
  'cloud-api': ENGINE_LABELS.online,
  'local-rules': ENGINE_LABELS.localRules,
}

/** 置信度档位与展示色调映射 */
const CONFIDENCE_TONE = { high: 'success', medium: 'warning', low: 'danger' }
const CONFIDENCE_LABEL = { high: '高置信', medium: '中置信', low: '低置信' }
const VALID_CONFIDENCES = ['high', 'medium', 'low']

/**
 * 判断 provider 类型是否为本地模型（Ollama 或含 local 字样）。
 * @param {string} type - provider 类型字符串
 * @returns {boolean} 是否本地
 */
export function isLocalProvider(type) {
  return /ollama|local/i.test(String(type || ''))
}

/**
 * 三态引擎标签解析：任一答案只有一个引擎身份，本地规则与 LoRA/本地模型互斥。
 * @param {Object} opts - 引擎选项
 * @param {string} [opts.engine='api'] - 引擎类型
 * @param {boolean} [opts.localAvailable=false] - 本地模型是否可用
 * @param {string} [opts.routingMode='auto'] - 路由模式
 * @param {string} [opts.providerType=''] - provider 类型
 * @param {string} [opts.providerModel=''] - provider 模型名
 * @returns {string} 引擎展示标签
 */
export function resolveEngineLabel({
  engine = 'api',
  localAvailable = false,
  routingMode = 'auto',
  providerType = '',
  providerModel = '',
} = {}) {
  if (engine === 'local') return ENGINE_LABELS.localRules
  if (isLocalProvider(providerType)) {
    return providerModel ? `${ENGINE_LABELS.localOllama} · ${providerModel}` : ENGINE_LABELS.localOllama
  }
  if (localAvailable && /local/i.test(String(routingMode))) return ENGINE_LABELS.localLora
  return `${ENGINE_LABELS.online}${providerModel ? ` ${providerModel}` : ''}`
}

/**
 * C-ENGINE-ENUM@1：优先使用后端返回的统一引擎枚举，缺失时回退到 resolveEngineLabel。
 * 失败语义：engine_enum 缺失或未知值时回退到既有 resolveEngineLabel 逻辑，不编造身份。
 * @param {Object} opts - 含 engineEnum 与 legacy 字段的对象
 * @returns {string} 引擎展示标签
 */
export function resolveEngineDisplay({ engineEnum = '', ...legacy } = {}) {
  const key = String(engineEnum || '').toLowerCase()
  if (ENGINE_ENUM_LABELS[key]) return ENGINE_ENUM_LABELS[key]
  return resolveEngineLabel(legacy)
}

/**
 * 置信度徽标：high/medium/low 三档，缺失时显式「不提供」。
 * @param {Object} props - 组件 props
 * @param {string} [props.confidence] - 置信度级别
 * @param {string} [props.className=''] - 自定义类名
 * @returns {JSX.Element} 置信度徽标
 */
export function ConfidenceBadge({ confidence, className = '' }) {
  const key = String(confidence || '').toLowerCase()
  const known = useMemo(() => VALID_CONFIDENCES.includes(key), [key])
  return (
    <Badge tone={known ? CONFIDENCE_TONE[key] : 'outline'} className={className}>
      {known ? CONFIDENCE_LABEL[key] : '置信度不提供'}
    </Badge>
  )
}

/**
 * C-CITATIONS@1：构建引用跳转 URL。
 * document_id 为 null/空时返回 null（调用方不渲染跳转）。
 * 格式：/knowledge/{document_id}?chunk={chunk_id}&page={page_start}
 * @param {Object} [c={}] - 引用项
 * @returns {string|null} 跳转 URL 或 null
 */
export function buildCitationUrl(c = {}) {
  const docId = c.document_id ?? c.doc_id ?? null
  if (docId == null || docId === '') return null
  const params = new URLSearchParams()
  if (c.chunk_id != null && c.chunk_id !== '') params.set('chunk', String(c.chunk_id))
  if (c.page_start != null && c.page_start !== '') params.set('page', String(c.page_start))
  const qs = params.toString()
  return `/knowledge/${docId}${qs ? `?${qs}` : ''}`
}

/**
 * C-CITATIONS@1：可跳转的引用列表。
 * document_id 非空的引用项渲染为 Link（跳转文档详情页块/页位置），
 * document_id 为空的引用项渲染为纯文本 span（不渲染跳转）。
 * @param {Object} props - 组件 props
 * @param {Array} [props.citations=[]] - 引用列表
 * @param {string} [props.className=''] - 自定义类名
 * @returns {JSX.Element|null} 引用列表组件
 */
export function AiCitations({ citations = [], className = '' }) {
  const items = useMemo(() => {
    if (!Array.isArray(citations) || !citations.length) return null
    return citations.map((h, index) => ({
      label: (h.title || h.doc_name || h.source || '知识片段').slice(0, 24),
      url: buildCitationUrl(h),
      title: (h.snippet || h.content || '').slice(0, 100),
      key: `${h.chunk_id || h.doc_id || 'h'}-${index}`,
      index,
    }))
  }, [citations])

  if (!items) return null

  return (
    <details className={['v3-asst-msg-citations', className].filter(Boolean).join(' ')}>
      <summary>本轮权威引用（{items.length}）</summary>
      <div className="v3-asst-refs__list">
        {items.map(({ label, url, title, key, index }) =>
          url ? (
            <Link key={key} to={url} title={title}>
              [{index + 1}] {label}
            </Link>
          ) : (
            <span key={key} title={title}>
              [{index + 1}] {label}
            </span>
          ),
        )}
      </div>
      <p className="v3-asst-refs__hint">点击引用可跳转到文档详情页对应块/页位置；无 document_id 的引用不提供跳转。</p>
    </details>
  )
}

/**
 * AI 证据卡：统一呈现单条 AI 引用证据的来源与元信息。
 * @param {Object} props - 组件 props
 * @param {number|null} [props.index=null] - 引用编号
 * @param {string} [props.title=''] - 标题
 * @param {string} [props.snippet=''] - 原文片段
 * @param {number|null} [props.score=null] - 命中分
 * @param {string|null} [props.confidence=null] - 置信度
 * @param {string} [props.engine=''] - 引擎标识（legacy）
 * @param {string} [props.engineEnum=''] - 引擎枚举（优先）
 * @param {string} [props.source=''] - 来源
 * @param {string} [props.subject=''] - 科目
 * @param {number|null} [props.docId=null] - 文档 ID
 * @param {Array} [props.fields=[]] - 自定义字段
 * @param {boolean|null} [props.rag=null] - 是否启用 RAG
 * @param {number|null} [props.hits=null] - 命中片段数
 * @param {number|null} [props.elapsedMs=null] - 耗时（毫秒）
 * @param {string} [props.model=''] - 模型名
 * @param {string} [props.degradeReason=''] - 降级原因
 * @param {string} [props.className=''] - 自定义类名
 * @returns {JSX.Element} 证据卡
 */
export default function AiEvidenceCard({
  index = null,
  title = '',
  snippet = '',
  score = null,
  confidence = null,
  engine = '',
  engineEnum = '',
  source = '',
  subject = '',
  docId = null,
  fields = [],
  rag = null,
  hits = null,
  elapsedMs = null,
  model = '',
  degradeReason = '',
  className = '',
}) {
  // C-ENGINE-ENUM@1：engineEnum 优先，缺失时回退到 engine 字符串
  const engineDisplay = useMemo(
    () => (engineEnum ? resolveEngineDisplay({ engineEnum }) : engine || ''),
    [engineEnum, engine],
  )

  return (
    <div className={`v3-ai-evidence ${className}`} data-ai-evidence="1">
      <div className="v3-ai-evidence__head">
        {index != null ? <span className="v3-ai-evidence__index">[{index}]</span> : null}
        <strong>{title || '未命名依据'}</strong>
        {engineDisplay ? <Badge tone="primary">{engineDisplay}</Badge> : null}
        {source ? <Badge tone="outline">{source}</Badge> : null}
        {subject ? <Badge tone="outline">{subject}</Badge> : null}
        {docId != null ? <Badge tone="outline">文档 #{docId}</Badge> : null}
        <ConfidenceBadge confidence={confidence} />
      </div>
      {snippet ? <p className="v3-ai-evidence__snippet">{snippet}</p> : null}
      <div className="v3-ai-evidence__meta">
        {score != null ? <span>命中分 {Number(score).toFixed(2)}</span> : null}
        {rag != null ? <span>RAG：{rag ? '启用' : '未启用'}</span> : null}
        {hits != null ? <span>命中片段 {hits}</span> : null}
        {elapsedMs != null ? <span>耗时 {elapsedMs} ms</span> : null}
        {model ? <span>模型 {model}</span> : null}
        {degradeReason ? <span>降级原因：{degradeReason}</span> : null}
      </div>
      {fields.length ? (
        <dl className="v3-ai-evidence__fields">
          {fields.map(([label, value]) => (
            <div key={String(label)}>
              <dt>{label}</dt>
              <dd>{value == null || value === '' ? '暂无记录' : value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  )
}
