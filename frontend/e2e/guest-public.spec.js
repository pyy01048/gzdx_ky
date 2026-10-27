// 访客公开面：真题索引与公告中心不依赖个人状态，不应被登录壳拦截。
import { test, expect } from '@playwright/test'

test.describe('访客公开面', () => {
  test('真题索引对访客开放', async ({ page }) => {
    await page.goto('/#/exam')
    await expect(page.getByRole('heading', { name: '真题中心' })).toBeVisible({ timeout: 15_000 })
    await expect(page).toHaveURL(/\/#\/exam$/)
  })

  test('公告中心对访客开放且能加载列表', async ({ page }) => {
    await page.goto('/#/kaoyan/notices')
    await expect(page.getByRole('heading', { name: '通知中心' })).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.v3-notices-item').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.v3-notices-star')).toHaveCount(0)
    await expect(page).not.toHaveURL(/\/login/)
  })
})
