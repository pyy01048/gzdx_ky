// P3-7 冒烟：AI 主链路（/assistant）
import { test, expect } from '@playwright/test'

test.describe('AI 助手冒烟', () => {
  test('AI 助手页面渲染不报错', async ({ page }) => {
    await page.goto('/assistant')
    await expect(page.getByRole('heading', { name: 'AI 助手' })).toBeVisible({ timeout: 15_000 })
  })
})
