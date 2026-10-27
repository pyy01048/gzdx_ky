// 院校库是公开页（访客只读），HashRouter 下必须带 #。
import { test, expect } from '@playwright/test'

test.describe('院校库冒烟', () => {
  test('访客可打开院校库并看到页头', async ({ page }) => {
    await page.goto('/#/kaoyan/schools')
    await expect(page.getByRole('heading', { name: '院校库', exact: true })).toBeVisible({ timeout: 15_000 })
    await expect(page).toHaveURL(/\/#\/kaoyan\/schools/)
  })
})
