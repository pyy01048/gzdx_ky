// P3-7 冒烟：刷题主链路（/quiz）
// 覆盖：Hero 标题 / 三入口 Tab / 按知识点区域 / 错题与收藏 + 错题闭环面板（P3-9 合并保留）
import { test, expect } from '@playwright/test'

test.describe('刷题中心冒烟', () => {
  test('首页 Hero 与三入口 Tab 渲染', async ({ page }) => {
    await page.goto('/quiz')
    await expect(page.getByText('QUIZ CENTER · 刷题中心')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('tab', { name: '按知识点' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '按年份' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '错题与收藏' })).toBeVisible()
  })

  test('按知识点页签可切换并展示科目导航', async ({ page }) => {
    await page.goto('/quiz')
    await page.getByRole('tab', { name: '按知识点' }).click()
    // 科目导航出现（后端在线时显示科目列表；为空时显示空态提示）
    await expect(page.locator('.qknow-nav, .empty-state').first()).toBeVisible({ timeout: 15_000 })
  })

  test('错题与收藏页签渲染错题闭环面板（P3-9 合并保留）', async ({ page }) => {
    await page.goto('/quiz')
    await page.getByRole('tab', { name: '错题与收藏' }).click()
    await expect(page.locator('.qreview-head-t').first()).toBeVisible({ timeout: 15_000 })
    // 闭环面板标题（薄弱点排行 / 错因分布 / 待复习队列）
    await expect(page.getByText('薄弱点排行')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('错因分布')).toBeVisible()
    await expect(page.getByText(/待复习队列（艾宾浩斯）/)).toBeVisible()
  })
})
