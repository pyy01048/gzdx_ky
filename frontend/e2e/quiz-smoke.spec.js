// 刷题主链路：做题会写个人答题记录，/quiz 在登录壳内。
// 游客直达应被 RequireAuth 送到登录页（登录后回原页）。
import { test, expect } from '@playwright/test'

test.describe('刷题中心：登录壳守门', () => {
  test('游客直达 /quiz 被引导到登录页', async ({ page }) => {
    await page.goto('/#/quiz')
    await expect(page).toHaveURL(/\/#\/login/)
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  })
})
