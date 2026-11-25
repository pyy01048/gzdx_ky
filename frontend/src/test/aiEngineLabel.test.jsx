/**
 * C1 / C3：AI 引擎三态标称 + 入口互引的静态契约。
 *
 * QA-06：本地规则 / 本地 LoRA / 本地模型三者互斥，provider_override 指向
 * 本地 Ollama 时绝不显示「自定义 AI API」。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import {
  ENGINE_LABELS, resolveEngineLabel, isLocalProvider, ConfidenceBadge,
} from '../v3/ai/AiEvidenceCard'

const source = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

describe('引擎三态标签映射', () => {
  it('四档标签的文案固定且彼此不同', () => {
    expect(ENGINE_LABELS.localLora).toBe('本地 Qwen2.5-1.5B (LoRA)')
    expect(ENGINE_LABELS.online).toBe('在线模型')
    expect(ENGINE_LABELS.localRules).toBe('本地规则')
    expect(ENGINE_LABELS.localOllama).toBe('本地模型')
    expect(new Set(Object.values(ENGINE_LABELS)).size).toBe(4)
  })

  it('本地规则引擎只标「本地规则」，不带 LoRA / 本地模型字样', () => {
    const label = resolveEngineLabel({ engine: 'local', localAvailable: true, routingMode: 'local' })
    expect(label).toBe(ENGINE_LABELS.localRules)
    expect(label).not.toMatch(/LoRA|本地模型|在线/)
  })

  it('本地 LoRA 三态与路由一致时才标 LoRA', () => {
    const label = resolveEngineLabel({
      engine: 'api', localAvailable: true, routingMode: 'local', providerType: 'openai',
    })
    expect(label).toBe(ENGINE_LABELS.localLora)
    expect(label).toMatch(/LoRA/)
    expect(label).not.toMatch(/本地规则|本地模型/)
  })

  it('provider_override 指向本地 Ollama 时标「本地模型」，不标「自定义 AI API」', () => {
    expect(isLocalProvider('ollama')).toBe(true)
    const label = resolveEngineLabel({
      engine: 'api', localAvailable: false, routingMode: 'auto',
      providerType: 'ollama', providerModel: 'qwen2.5:7b',
    })
    expect(label).toBe('本地模型 · qwen2.5:7b')
    expect(label).not.toMatch(/自定义 AI API|本地规则|LoRA/)
  })

  it('默认在线态带模型名，本地不可用时不得冒充 LoRA', () => {
    expect(resolveEngineLabel({ engine: 'api', providerModel: 'qwen-plus' }))
      .toBe('在线模型 qwen-plus')
    expect(resolveEngineLabel({ engine: 'api', localAvailable: false, routingMode: 'local' }))
      .toBe('在线模型')
  })

  it('任一答案只会命中一个本地身份（互斥正则）', () => {
    const cases = [
      { engine: 'local' },
      { engine: 'api', localAvailable: true, routingMode: 'local' },
      { engine: 'api', providerType: 'ollama', providerModel: 'llama3' },
      { engine: 'api', providerModel: 'gpt-4o' },
    ]
    for (const input of cases) {
      const label = resolveEngineLabel(input)
      const hits = [/本地规则/, /LoRA/, /本地模型/].filter((re) => re.test(label)).length
      expect(hits, `${label} 命中 ${hits} 个本地身份`).toBeLessThanOrEqual(1)
    }
  })
})

describe('置信度徽标', () => {
  it('三档有文案，缺失时显式「不提供」', () => {
    const { rerender } = render(<ConfidenceBadge confidence="high" />)
    expect(screen.getByText('高置信')).toBeTruthy()
    rerender(<ConfidenceBadge confidence="medium" />)
    expect(screen.getByText('中置信')).toBeTruthy()
    rerender(<ConfidenceBadge confidence="low" />)
    expect(screen.getByText('低置信')).toBeTruthy()
    rerender(<ConfidenceBadge confidence={null} />)
    expect(screen.getByText('置信度不提供')).toBeTruthy()
  })
})

describe('C1：回答元信息与断网降级文案', () => {
  it('每条 bot 回答都渲染可见元信息卡', () => {
    const code = source('src/v3/pages/Assistant.jsx')
    expect(code).toMatch(/m\.role === 'bot' && !m\.error && !m\.streaming \? \([\s\S]{0,120}<AiEvidenceCard/)
    expect(code).toMatch(/elapsedMs=\{m\.elapsedMs\}/)
    expect(code).toMatch(/degradeReason=/)
  })

  it('断网文案明确区分本地规则与本地 LoRA 模型', () => {
    const code = source('src/v3/pages/Assistant.jsx')
    expect(code).toMatch(/不是「本地 LoRA 模型」/)
    expect(code).toMatch(/本地规则/)
  })
})

describe('C3：AI 入口互引与登录页低成本方案', () => {
  it('两个助手页各有指向对方的互链（hash 路由 href）', () => {
    expect(source('src/v3/pages/Assistant.jsx')).toMatch(/href="#\/kaoyan\/assistant"/)
    expect(source('src/v3/pages/KaoyanAssistant.jsx')).toMatch(/to="\/assistant"/)
  })

  it('命令面板「AI」可命中通用助手与择校助手两条', () => {
    /* /assistant 来自 NAV_OTHER，/kaoyan/assistant 由 C3 在命令面板 entries 追加 */
    const nav = source('src/nav/navConfig.js')
    const shell = source('src/v3/shell/index.jsx')
    expect(nav).toMatch(/to: '\/assistant'[^\n]*kw: \[[^\]]*'ai'/)
    expect(shell).toMatch(/to: '\/kaoyan\/assistant'[^\n]*kw: \[[^\]]*'ai'/)
    expect(shell).toMatch(/\.\.\.NAV_OTHER\.map/)
  })

  it('登录页方案②：卡片不可点击且注明需登录，主视觉卡不含 AI 字样', () => {
    const login = source('src/v3/pages/Login.jsx')
    expect(login).toMatch(/需登录后使用/)
    expect(login).toMatch(/不可点击/)
  })
})
