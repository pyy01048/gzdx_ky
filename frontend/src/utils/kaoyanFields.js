/**
 * 择校数据字段展示规范（V7.0 P0-2）
 * ---------------------------------------------------------------------------
 * 背景：V6.0 三方审计用 825 行全量回归证实，数据库中多数择校字段
 * **值是对的、名字是错的**（历史导入脚本把不同口径的数据写进了同一批列）。
 * 例如 `total_line` 实际是「进面最低分」而非「总分线」，`retest_count`
 * 实际是「录取人数」而非「进复试人数」。
 *
 * 本模块是**唯一**的字段语义来源（single source of truth）：
 *   - 页面按 `label` 展示，不再自己写文案；
 *   - 审计判定为不可信的字段放入 `UNTRUSTED_FIELDS`，页面一律不展示；
 *   - 所有分数线 / 人数类数值旁统一挂 `SourceBadge` 角标。
 *
 * 本模块只管**前端展示**，不修改数据库、不修改后端接口契约。
 */

/** 数据可信度分档（与后端 resolve_source_type 的三档保持一致） */
export const SOURCE_TYPES = {
  OFFICIAL: '官方',
  AGGREGATOR: '聚合',
  UNVERIFIED: '未验证',
}

/** 后端 source 标记 → 展示分档（前端兜底，逻辑对齐后端 datasource_registry） */
const SOURCE_TYPE_MAP = {
  'yz.chsi.com.cn': SOURCE_TYPES.OFFICIAL,
  school_official: SOURCE_TYPES.OFFICIAL,
  yz_chsi: SOURCE_TYPES.OFFICIAL,
  exam_authority: SOURCE_TYPES.OFFICIAL,
  'txkyer.cn': SOURCE_TYPES.AGGREGATOR,
  seed_txkyer: SOURCE_TYPES.AGGREGATOR,
  csv_sample: SOURCE_TYPES.AGGREGATOR,
  unverified: SOURCE_TYPES.UNVERIFIED,
}

/**
 * 归一化数据来源分档。
 * @param {string} [source] 库内 source / data_source 原始标记
 * @returns {'官方'|'聚合'|'未验证'} 三档分档；无法识别时按「未验证」处理
 */
export function resolveSourceType(source) {
  if (!source) return SOURCE_TYPES.UNVERIFIED
  if (SOURCE_TYPE_MAP[source]) return SOURCE_TYPE_MAP[source]
  if (source.includes('yz.chsi.com.cn') || source.includes('.edu.cn') || source.toLowerCase().includes('exam')) {
    return SOURCE_TYPES.OFFICIAL
  }
  if (source.includes('txkyer') || source.toLowerCase().includes('csv')) return SOURCE_TYPES.AGGREGATOR
  return SOURCE_TYPES.UNVERIFIED
}

/**
 * 分数线表字段（KaoyanScoreLine）
 * `key` 为后端字段名，`label` 为审计确认的真实口径。
 */
export const SCORE_FIELDS = [
  { key: 'total_line', label: '进面最低分', kind: 'line' },
  { key: 'major_line', label: '专业课均分', kind: 'line' },
]

/**
 * 招生数据表字段（KaoyanAdmission）
 * `kind` 用于决定是否挂「来源未核验」角标：
 *   - 'line' 分数线类 → 必挂
 *   - 'count' 人数类 → 必挂
 *   - 'ratio' 复录比 → 审计命中率 93.8%，可信度较高，不挂角标
 */
export const ADMISSION_FIELDS = [
  { key: 'enroll_count', label: '进线人数', kind: 'count' },
  { key: 'retest_count', label: '录取人数', kind: 'count' },
  { key: 'admit_avg_score', label: '进面均分', kind: 'line' },
  { key: 'major_avg_score', label: '数学均分', kind: 'line' },
  { key: 'retest_ratio', label: '复录比', kind: 'ratio' },
]

/**
 * 审计判定为不可信、**前端一律不展示**的字段。
 * 说明见各条 comment——这些不是「暂时没数据」，而是「值本身没有意义」。
 */
export const UNTRUSTED_FIELDS = {
  retest_line: '与 total_line 同值（97.2% 命中），重复展示会误导为两所线',
  national_line: '全库为空（0/811 有值）',
  politics_line: '与政治真实分数线无匹配（0% 命中）',
  english_line: '与英语真实分数线无匹配',
  math_line: '仅 3.3% 命中，疑似专业课数据串列',
  admit_count: '伪造列，仅 33.2% 命中（与 retest_count 大量冲突）',
}

/** 是否为需要标注「来源未核验」的字段类型 */
export function needsSourceBadge(kind) {
  return kind === 'line' || kind === 'count'
}

/** 趋势分析可选指标（仅暴露可信字段） */
export const TRUSTED_TREND_METRICS = [
  { value: 'total_line', label: '进面最低分', kind: 'line' },
  { value: 'major_avg_score', label: '数学均分', kind: 'line' },
  { value: 'admit_avg_score', label: '进面均分', kind: 'line' },
  { value: 'enroll_count', label: '进线人数', kind: 'count' },
  { value: 'retest_count', label: '录取人数', kind: 'count' },
  { value: 'retest_ratio', label: '复录比', kind: 'ratio' },
]
