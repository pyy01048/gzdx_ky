// P3-7 冒烟：院校主链路（/kaoyan/schools）
import { test, expect } from '@playwright/test'

test.describe('院校库冒烟', () => {
  test('院校库页面渲染不报错', async ({ page }) => {
    await page.goto('/kaoyan/schools')
    await expect(page.getByRole('heading', { name: '院校数据库' })).toBeVisible({ timeout: 15_000 })
  })
})
