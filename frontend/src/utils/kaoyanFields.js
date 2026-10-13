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

/**
 * 归一化「初试/复试考试科目」为结构化数组（V8.0 P0-2）。
 * ---------------------------------------------------------------------------
 * 背景：`kaoyan_majors.exam_subjects` 在库内的真实存储形态是**竖线分隔文本**
 *   `"(302)数学（二） | (204)英语（二） | (857)电子技术基础"`
 * 而 `/schools/{id}/enrollment-plan` 端点返回的是结构化数组 `[{code, name}]`。
 *
 * 历史事故：前端直接 `{m.exam_subjects}` 渲染——遇到对象元素就输出
 * `[object Object]`；遇到文本形态则整串挤成一个巨大徽标。两种都不对。
 *
 * 本函数是前端**唯一**的考试科目归一入口，统一吃下：
 *   - 竖线/中文分号/换行分隔的字符串
 *   - `[{code, name}]` 结构化数组
 *   - 纯字符串数组
 * 输出统一为 `[{code, name}]`（`code` 为 3 位科目代码，缺失为 null）。
 *
 * @param {string|Array} [raw]
 * @returns {Array<{code: string|null, name: string}>}
 */
export function examSubjects(raw) {
  if (raw == null) return []
  const CODE_RE = /^[（(]?\s*(\d{3})\s*[)）]?\s*(.*)$/
  // 占位值不算科目（后端在数据缺失时会给出 "-"）
  const PLACEHOLDER = new Set(['-', '—', '－', '/', '无', '暂无', '未标注', '暂无数据'])

  const flatten = (value) => {
    if (value == null) return []
    if (Array.isArray(value)) return value.flatMap(flatten)
    if (typeof value === 'object') {
      const name = String(value.name ?? value.label ?? '').trim()
      return name ? [name] : []
    }
    return String(value).split(/\s*\|\s*/)
  }

  const seen = new Set()
  const out = []
  for (const seg of flatten(raw)) {
    const text = String(seg).replace(/[；\n]/g, '|')
    for (const piece of text.split('|')) {
      const s = piece.trim()
      if (!s) continue
      const m = s.match(CODE_RE)
      const code = m ? m[1] : null
      const name = (m ? m[2] : s).replace(/^[、·\s]+/, '').trim()
      if (!name || PLACEHOLDER.has(name)) continue
      const key = `${code ?? ''}|${name}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ code, name })
    }
  }
  return out
}

/**
 * 考试科目 → 纯科目名数组（展示用，已剥掉 3 位科目代码）。
 * @param {string|Array} [raw]
 * @returns {string[]}
 */
export function examSubjectNames(raw) {
  return examSubjects(raw).map((s) => s.name)
}

/**
 * 考试科目 → 单个展示串（用于列表页紧凑展示）。
 * @param {string|Array} [raw]
 * @param {string} [sep=' · ']
 * @returns {string}
 */
export function examSubjectText(raw, sep = ' · ') {
  return examSubjectNames(raw).join(sep)
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
