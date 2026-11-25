import React from 'react'
import { Badge } from '../ui'
import './ai-evidence.css'

/**
 * 共享 AI 证据卡（批次 C6，为批次 D「上岸经验进 RAG 后引用卡显示来源」打基础）。
 *
 * 统一呈现：引用编号 / 标题 / 原文片段 / 命中分 / 置信度 / 引擎标识 / 自定义字段。
 * 所有展示字段都是可选 props，缺字段时给明确占位，不编造来源。
 */

/* 引擎三态 + provider_override 本地 Ollama 的互斥标签 */
export const ENGINE_LABELS = {
  localLora: '本地 Qwen2.5-1.5B (LoRA)',
  online: '在线模型',
  localRules: '本地规则',
  localOllama: '本地模型',
}

export function isLocalProvider(type) {
  return /ollama|local/i.test(String(type || ''))
}

/** 三态引擎标签解析：任一答案只有一个引擎身份，本地规则与 LoRA/本地模型互斥。 */
export function resolveEngineLabel({
  engine = 'api', localAvailable = false, routingMode = 'auto',
  providerType = '', providerModel = '',
} = {}) {
  if (engine === 'local') return ENGINE_LABELS.localRules
  if (isLocalProvider(providerType)) {
    return providerModel ? `${ENGINE_LABELS.localOllama} · ${providerModel}` : ENGINE_LABELS.localOllama
  }
  if (localAvailable && /local/i.test(String(routingMode))) return ENGINE_LABELS.localLora
  return `${ENGINE_LABELS.online}${providerModel ? ` ${providerModel}` : ''}`
}

const CONFIDENCE_TONE = { high: 'success', medium: 'warning', low: 'danger' }
const CONFIDENCE_LABEL = { high: '高置信', medium: '中置信', low: '低置信' }

/** 置信度徽标：high/medium/low 三档，缺失时显式「不提供」。 */
export function ConfidenceBadge({ confidence, className = '' }) {
  const key = String(confidence || '').toLowerCase()
  const known = ['high', 'medium', 'low'].includes(key)
  return (
    <Badge tone={known ? CONFIDENCE_TONE[key] : 'outline'} className={className}>
      {known ? CONFIDENCE_LABEL[key] : '置信度不提供'}
    </Badge>
  )
}

export default function AiEvidenceCard({
  index = null, title = '', snippet = '', score = null, confidence = null,
  engine = '', source = '', subject = '', docId = null, fields = [],
  rag = null, hits = null, elapsedMs = null, model = '', degradeReason = '',
  className = '',
}) {
  return (
    <div className={`v3-ai-evidence ${className}`} data-ai-evidence="1">
      <div className="v3-ai-evidence__head">
        {index != null ? <span className="v3-ai-evidence__index">[{index}]</span> : null}
        <strong>{title || '未命名依据'}</strong>
        {engine ? <Badge tone="primary">{engine}</Badge> : null}
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
            <div key={String(label)}><dt>{label}</dt><dd>{value == null || value === '' ? '暂无记录' : value}</dd></div>
          ))}
        </dl>
      ) : null}
    </div>
  )
}
