/**
 * C5 / QA-23：后端健康状态单一口径。
 *
 * 三态（online / degraded / offline）是唯一事实源，backendOnline 只是它的布尔投影：
 * offline → false，online / degraded → true，unknown → null（由 hydrate 临时兜底）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  isBackendOnline, getBackendState, probeBackend, FAILURE_WINDOW_MS,
} from '../api/client'

const source = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('三态 → backendOnline 投影', () => {
  it('offline 为 false，online / degraded 均为 true', () => {
    expect(isBackendOnline({ state: 'offline' })).toBe(false)
    expect(isBackendOnline({ state: 'online' })).toBe(true)
    expect(isBackendOnline({ state: 'degraded' })).toBe(true)
  })

  it('unknown 返回 null，交给 hydrate 兜底而不是各页自行猜测', () => {
    expect(isBackendOnline({ state: 'unknown' })).toBeNull()
    expect(isBackendOnline(null)).toBeNull()
    expect(isBackendOnline({})).toBeNull()
  })

  it('5 分钟失败窗口常量保持不变，不破坏既有降级去重', () => {
    expect(FAILURE_WINDOW_MS).toBe(5 * 60 * 1000)
  })
})

describe('probeBackend 实时三态', () => {
  it('health 可达 → online 且 online 投影为 true', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
    const s = await probeBackend()
    expect(s.state).toBe('online')
    expect(isBackendOnline(s)).toBe(true)
    expect(getBackendState().state).toBe('online')
  })

  it('health 不可达 → offline 且 online 投影为 false', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const s = await probeBackend()
    expect(s.state).toBe('offline')
    expect(isBackendOnline(s)).toBe(false)
  })

  it('health 返回非 2xx → offline（只有 health 本身不可用才叫离线）', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))
    const offline = await probeBackend()
    expect(offline.state).toBe('offline')
    expect(isBackendOnline(offline)).toBe(false)
  })
})

describe('消费方唯一化', () => {
  it('页面不再直接订阅 client 三态，统一走 useBackendHealth', () => {
    const hook = source('src/hooks/useBackendHealth.js')
    expect(hook).toMatch(/subscribeBackendState\(onStatus\)/)
    expect(hook).toMatch(/isBackendOnline\(backend\)/)

    const documents = source('src/v3/pages/Documents.jsx')
    expect(documents).toMatch(/useBackendHealth\(\)/)
    expect(documents).not.toMatch(/subscribeBackendState/)
    expect(documents).not.toMatch(/getBackendState/)
  })

  it('sync.js 的 backendOnline 由三态派生而非「任一数据域成功」', () => {
    const sync = source('src/api/sync.js')
    expect(sync).toMatch(/isBackendOnline\(health\)/)
    expect(sync).not.toMatch(/backendOnline: ok > 0/)
  })
})
