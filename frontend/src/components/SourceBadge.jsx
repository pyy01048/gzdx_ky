import React, { useState } from 'react'
import { SOURCE_TYPES, resolveSourceType, UNTRUSTED_FIELDS } from '../utils/kaoyanFields'

/**
 * 数据来源角标（V7.0 P0-2）
 * ---------------------------------------------------------------------------
 * 审计发现择校库中 97.3% 的记录 `source` 为 `unverified`。此前页面直接
 * 把这些数字当官方口径展示，用户无法判断可信度。本组件在分数线 / 人数类
 * 数值旁统一挂角标，做到「数据不可信这件事必须可见」。
 */

/** 各分档对应的 CSS 变量（全部走主题变量，明暗色自适应） */
const TONE_STYLE = {
  [SOURCE_TYPES.OFFICIAL]: { color: 'var(--green)', bg: 'var(--green-soft)' },
  [SOURCE_TYPES.AGGREGATOR]: { color: 'var(--gold)', bg: 'var(--gold-soft)' },
  [SOURCE_TYPES.UNVERIFIED]: { color: 'var(--ink-3)', bg: 'var(--surface-2)' },
}

const TONE_TEXT = {
  [SOURCE_TYPES.OFFICIAL]: '官方来源',
  [SOURCE_TYPES.AGGREGATOR]: '聚合来源',
  [SOURCE_TYPES.UNVERIFIED]: '来源未核验',
}

/**
 * 单个来源角标。
 *
 * @param {object} props
 * @param {string} [props.source] 库内 source / data_source 原始标记
 * @param {string} [props.sourceType] 后端已归一化的分档（有则优先，省一次前端推断）
 * @param {boolean} [props.compact] 只显示圆点不显示文字（表格密集场景）
 * @returns {React.ReactElement} 角标节点
 */
export function SourceBadge({ source, sourceType, compact = false }) {
  const type = sourceType || resolveSourceType(source)
  const tone = TONE_STYLE[type] || TONE_STYLE[SOURCE_TYPES.UNVERIFIED]
  const text = TONE_TEXT[type] || TONE_TEXT[SOURCE_TYPES.UNVERIFIED]
  return (
    <span
      className="src-badge"
      title={`数据来源：${text}${source ? `（${source}）` : ''}`}
      style={{ color: tone.color, background: tone.bg }}
    >
      {compact ? '·' : text}
    </span>
  )
}

/**
 * 表格单元格：数值 + （按需）来源角标。
 * 统一处理空值占位，避免各页面出现 '-' / '—' / 空字符串三种写法。
 *
 * @param {object} props
 * @param {*} props.value 字段值
 * @param {object} [props.record] 整行数据，用于取 source / data_source
 * @param {string} [props.sourceType] 整行的来源分档
 * @param {boolean} [props.badge] 是否挂来源角标（分数线 / 人数类为 true）
 * @param {string} [props.empty] 空值占位符
 * @returns {React.ReactElement} 单元格内容
 */
export function DataCell({ value, record, sourceType, badge = false, empty = '-' }) {
  const hasValue = value !== null && value !== undefined && value !== ''
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      {hasValue ? value : empty}
      {badge && hasValue && (
        <SourceBadge
          source={record?.source ?? record?.data_source}
          sourceType={sourceType ?? record?.source_type ?? record?.data_source_type}
          compact
        />
      )}
    </span>
  )
}

/** 被下线字段的中文名（用于「口径说明」文案） */
const RETIRED_FIELD_LABELS = {
  retest_line: '复试线',
  national_line: '国家线',
  politics_line: '政治线',
  english_line: '英语线',
  math_line: '数学线',
  admit_count: '拟录取人数',
}

/**
 * 数据口径说明（可折叠）。
 * 明确告知用户「哪些字段没展示、为什么」——避免用户以为数据缺失，
 * 也避免把不可信字段悄悄藏起来。
 *
 * @param {object} props
 * @param {string[]} [props.fields] 需要说明的字段名列表，默认全部已下线字段
 * @returns {React.ReactElement} 口径说明节点
 */
export function DataQualityNote({ fields }) {
  const [open, setOpen] = useState(false)
  const keys = fields && fields.length ? fields : Object.keys(UNTRUSTED_FIELDS)
  if (keys.length === 0) return null

  return (
    <div style={{ marginBottom: 12 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'none', border: 'none', padding: 0, cursor: 'pointer',
          color: 'var(--accent)', fontSize: 12.5, textAlign: 'left',
        }}
      >
        {open ? '▾ 收起数据口径说明' : '▸ 为什么少了这几个字段？'}
      </button>
      {open && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 20, fontSize: 12.5, color: 'var(--ink-3)', lineHeight: 1.9 }}>
          {keys.map((k) => (
            <li key={k}>
              <b style={{ color: 'var(--ink-2)' }}>{RETIRED_FIELD_LABELS[k] || k}</b>：{UNTRUSTED_FIELDS[k]}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default SourceBadge