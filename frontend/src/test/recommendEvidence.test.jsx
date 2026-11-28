/**
 * C4 / QA-07 + C6：推荐卡逐卡依据。
 *
 * 每卡 ≥5 项字段、缺失字段明确占位、口径与院校库一致，且复用共享证据卡。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import AiEvidenceCard from '../v3/ai/AiEvidenceCard'
import { buildEvidenceFields, buildRecommendDetailUrl, buildSchoolDetailUrl, RECOMMEND_DISCLAIMER } from '../v3/pages/KaoyanRecommend'

const code = readFileSync(resolve(process.cwd(), 'src/v3/pages/KaoyanRecommend.jsx'), 'utf8')

describe('推荐结果专业范围链接', () => {
  it('院校详情链接保留专业代码，空代码不添加参数', () => {
    expect(buildSchoolDetailUrl(9201, ' 0854 ')).toBe('/kaoyan/schools/9201?subject_code=0854')
    expect(buildSchoolDetailUrl(9201, '')).toBe('/kaoyan/schools/9201')
  })
})

describe('逐卡依据字段', () => {
  it('恒为 5 项且分开展示分数线来源、招生来源、年份、采集时间与分差', () => {
    const fields = buildEvidenceFields({
      name: '示例大学', gap: -12, year: 2025,
      scoreline_evidence: { sources: [{ data_source: 'yz.chsi.com.cn', source_type: 'school_official' }] },
      admission_evidence: { sources: [{ data_source: 'notice:school:2025', source_type: 'school_official' }] },
      collected_at: '2026-01-04',
    }, 2024)
    expect(fields).toHaveLength(5)
    expect(fields.map(([label]) => label)).toEqual([
      '分数线来源', '招生来源', '年份', '采集时间', '与本人分数差值',
    ])
    expect(fields[0][1]).toBe('官方')
    expect(fields[1][1]).toBe('官方')
    expect(fields[2][1]).toBe(2025)
    expect(fields[3][1]).toBe('2026-01-04')
    expect(fields[4][1]).toBe('-12')
  })

  it('证据缺失时分别占位，不把学校资料源冒充招生来源', () => {
    const fields = buildEvidenceFields({ name: '缺口大学', data_source: 'school_official' }, 2024)
    expect(fields[0][1]).toBe('未验证')
    expect(fields[1][1]).toBe('暂无官方招生记录')
    expect(fields[2][1]).toBe(2024)
    expect(fields[3][1]).toBe('暂无记录')
    expect(fields[4][1]).toBe('—')
  })

  it('口径说明与官方招生风险计算一致', () => {
    expect(RECOMMEND_DISCLAIMER).toMatch(/仅使用明确官方招生记录/)
    expect(RECOMMEND_DISCLAIMER).not.toMatch(/数据来自第三方聚合/)
  })
})

describe('共享证据卡渲染依据', () => {
  it('编号 / 标题 / 片段 / 命中分 / 置信度 / 引擎全部可复用渲染', () => {
    render(
      <AiEvidenceCard
        index={1}
        title="示例大学 · 推荐依据"
        snippet="近三年录取均分 372"
        score={0.87}
        confidence="high"
        engine="库内聚合"
        source="研招网聚合"
        subject="0808"
        docId={42}
        elapsedMs={320}
        fields={buildEvidenceFields({ name: '示例大学', gap: -12 }, 2025)}
      />
    )
    expect(screen.getByText('[1]')).toBeTruthy()
    expect(screen.getByText('示例大学 · 推荐依据')).toBeTruthy()
    expect(screen.getByText(/近三年录取均分/)).toBeTruthy()
    expect(screen.getByText('命中分 0.87')).toBeTruthy()
    expect(screen.getByText('高置信')).toBeTruthy()
    expect(screen.getByText('库内聚合')).toBeTruthy()
    expect(screen.getByText('耗时 320 ms')).toBeTruthy()
    expect(screen.getByText('分数线来源')).toBeTruthy()
    expect(screen.getByText('招生来源')).toBeTruthy()
    expect(screen.getByText('与本人分数差值')).toBeTruthy()
  })
})

describe('逐卡覆盖率 100%', () => {
  it('每张推荐卡都渲染依据抽屉，不存在无依据卡片', () => {
    expect(code).toMatch(/<details className="v3-ky-rec__evidence">/)
    expect(code).toMatch(/buildEvidenceFields\(item, refYear\)/)
    expect(code).toMatch(/<AiEvidenceCard/)
    /* 抽屉写在 RecommendCard 内，shown.map 的每张卡都经过它 */
    const cardBody = code.slice(code.indexOf('function RecommendCard'), code.indexOf('function AutoAdjustPanel'))
    expect(cardBody).toMatch(/<details className="v3-ky-rec__evidence">/)
    expect(code).toMatch(/shown\.map\(\(item\) =>/)
  })
})
