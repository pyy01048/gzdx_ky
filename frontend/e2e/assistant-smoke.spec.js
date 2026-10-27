// AI 助手依赖个人会话与 API Key 配置，位于登录壳内。
// 游客直达应被 RequireAuth 送到登录页，而不是渲染一个只会 401 的空页。
import { test, expect } from '@playwright/test'

test.describe('AI 助手：登录壳守门', () => {
  test('游客直达 /assistant 被引导到登录页', async ({ page }) => {
    await page.goto('/#/assistant')
    await expect(page).toHaveURL(/\/#\/login/)
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  })
})
