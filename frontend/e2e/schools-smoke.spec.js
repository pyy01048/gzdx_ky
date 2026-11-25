// 院校库是公开页（访客只读），HashRouter 下必须带 #。
import { test, expect } from '@playwright/test'

async function mockSchoolDetailApi(page) {
  const school = { id: 1, name: '测试院校', province: '贵州', city: '贵阳' }
  const scores = [{
    source_id: 1, year: 2025, degree_type: '专业型', major_code: '085404', major_name: '计算机技术',
    depart_name: '计算机学院', total_line: 300, politics_line: 0, english_line: 45,
    math_line: 70, major_line: 80, national_line: 273, diff_total: 27, note: '',
  }]
  const admissions = [{
    year: 2025, major_code: '085404', major_name: '计算机技术', enroll_count: 12,
    retest_count: 24, admit_count: 18, admit_avg_score: 350, major_avg_score: 118,
    retest_ratio: 1.33, data_source: 'txkyer.cn', extra: null,
  }, {
    year: 2025, major_code: '085404', major_name: '计算机技术', enroll_count: 12,
    retest_count: 24, admit_count: 18, admit_avg_score: 350, major_avg_score: 118,
    retest_ratio: 1.33, data_source: 'txkyer.cn', extra: null,
  }]

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname === '/api/auth/me') return json(null)
    if (url.pathname === '/api/kaoyan/schools/1') return json(school)
    if (url.pathname === '/api/kaoyan/schools/1/majors') return json([])
    if (url.pathname === '/api/kaoyan/schools/1/scores') return json(scores)
    if (url.pathname === '/api/kaoyan/schools/1/admissions') return json(admissions)
    if (url.pathname === '/api/kaoyan/schools/1/admissions/details') return json([])
    if (url.pathname === '/api/kaoyan/analysis/score-detail/1') return json({
      trends: { admit_avg_trend: '数据不足' },
      line_vs_national: { year: 2025, total_line: 300, national_line: 300, diff: 0 },
    })
    if (url.pathname === '/api/kaoyan/schools/1/enrollment-plan') return json(null)
    if (url.pathname === '/api/kaoyan/schools/1/notices') return json([])
    if (url.pathname === '/api/kaoyan/reforms') return json([])
    return route.continue()
  })
}

test.describe('院校库冒烟', () => {
  test('访客可打开院校库并看到页头', async ({ page }) => {
    await page.goto('/#/kaoyan/schools')
    await expect(page.getByRole('heading', { name: '院校库', exact: true })).toBeVisible({ timeout: 15_000 })
    await expect(page).toHaveURL(/\/#\/kaoyan\/schools/)
    const firstSchool = page.locator('.kyv3-school').first()
    await expect(firstSchool).toBeVisible()
    await firstSchool.getByRole('button', { name: /^收藏 / }).click()
    await expect(page.getByText('已关注院校', { exact: true })).toBeVisible()
    await firstSchool.getByRole('button', { name: /^取消收藏 / }).click()
    await expect(page.getByText('已取消关注', { exact: true })).toBeVisible()
  })

  test('地图省份深链自动筛选，手机筛选触控热区不小于 44px', async ({ page }) => {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport)
      await page.goto('/#/kaoyan/schools?province=贵州')
      await expect(page.getByRole('heading', { name: '院校库', exact: true })).toBeVisible()
      await expect(page.getByRole('combobox', { name: '按省份筛选' })).toContainText('贵州')
      await expect(page.locator('.kyv3-active-count')).toContainText('1')
      await expect(page.locator('.kyv3-school').first()).toBeVisible()
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)

      const chip = page.locator('button.v3-chip').first()
      const minimumTouchHeight = viewport.width < 768 ? 44 : 28
      expect((await chip.boundingBox()).height).toBeGreaterThanOrEqual(minimumTouchHeight)
      await page.getByRole('combobox', { name: '按省份筛选' }).click()
      const option = page.getByRole('option', { name: '贵州', exact: true })
      await expect(option).toBeVisible()
      expect((await option.boundingBox()).height).toBeGreaterThanOrEqual(minimumTouchHeight)
      await page.keyboard.press('Escape')
    }
  })

  test('地图固定省份后可进入自动筛选的院校库', async ({ page }) => {
    const pageErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/#/kaoyan/map')
    await expect(page.getByRole('heading', { name: '区域择校热力图', exact: true })).toBeVisible()
    const guizhouCard = page.locator('.v3-ky-province-card').filter({ hasText: '贵州' }).first()
    await expect(guizhouCard).toBeVisible()
    await guizhouCard.click()
    await page.getByRole('link', { name: /查看该省院校/ }).click()
    await expect(page).toHaveURL(/\/#\/kaoyan\/schools\?province=/)
    await expect(page.getByRole('combobox', { name: '按省份筛选' })).toContainText('贵州')
    await expect(page.locator('.kyv3-active-count')).toContainText('1')
    expect(pageErrors).toEqual([])
  })

  test('择校决策工具在桌面和手机宽度下均可访问且不横向溢出', async ({ page }) => {
    const pageErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const pages = [
      ['/kaoyan/compare', '院校同年对比'],
      ['/kaoyan/analysis', '分数分析'],
      ['/kaoyan/recommend', '智能择校推荐'],
      ['/kaoyan/scatter', '专业均值招生分布'],
      ['/kaoyan/map', '区域择校热力图'],
    ]
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport)
      for (const [route, heading] of pages) {
        await page.goto(`/#${route}`)
        await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
        await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
      }
    }
    expect(pageErrors).toEqual([])
  })

  test('详情数据页签在桌面和手机宽度下不重复指标且不撑破页面', async ({ page }) => {
    const pageErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await mockSchoolDetailApi(page)

    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport)
      await page.goto('/#/kaoyan/schools/1')
      await expect(page.getByRole('heading', { name: '测试院校', exact: true })).toBeVisible()
      await expect(page.getByText('与国家线持平')).toBeVisible()

      await page.getByRole('tab', { name: /^历年分数/ }).click()
      const scoreTable = page.getByRole('table')
      await expect(scoreTable.getByText('300', { exact: true })).toHaveCount(1)
      await expect(scoreTable.getByText('↗27', { exact: true })).toBeVisible()
      await expect(scoreTable.getByText('0', { exact: true })).toHaveCount(0)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)

      await page.getByRole('tab', { name: /^招生数据/ }).click()
      const admissionTable = page.getByRole('table')
      await expect(admissionTable.getByText('350', { exact: true })).toHaveCount(1)
      await expect(admissionTable.getByText('118', { exact: true })).toHaveCount(1)
      await expect(page.getByText(/各专业均分对比/)).toHaveCount(0)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    }

    expect(pageErrors).toEqual([])
  })
})
