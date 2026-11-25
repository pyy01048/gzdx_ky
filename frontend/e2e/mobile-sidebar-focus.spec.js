import { test, expect } from '@playwright/test'

const openButton = (page) => page.getByRole('button', { name: '打开导航', exact: true })
const drawer = (page) => page.locator('.v3-sidebar')

test.beforeEach(async ({ page }) => {
  // 焦点回归不依赖后端或登录态；公开路由由本地 shell 独立渲染。
  await page.route('http://localhost:5173/api/**', async (route) => {
    if (new URL(route.request().url()).pathname.endsWith('/api/auth/me')) {
      await route.fulfill({ status: 401, contentType: 'application/json', body: '{}' })
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
  })
  await page.setViewportSize({ width: 390, height: 844 })
})

test('移动侧栏关闭态不渲染，连续 24 次 Tab 不会聚焦屏幕外链接', async ({ page }) => {
  await page.goto('/#/kaoyan/schools')
  await expect(openButton(page)).toBeVisible()
  await expect(drawer(page)).toHaveCount(0)

  for (let i = 0; i < 24; i += 1) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('.v3-sidebar')))).toBe(false)
  }
})

test('打开移入焦点、Tab 陷阱、Escape 关闭并恢复触发按钮', async ({ page }) => {
  await page.goto('/#/kaoyan/schools')
  const trigger = openButton(page)
  await trigger.click()

  const panel = page.getByRole('dialog', { name: '主导航' })
  const brand = panel.locator('.v3-brand')
  const last = panel.locator('.v3-sidebar__collapse').last()
  await expect(panel).toBeVisible()
  await expect(brand).toBeFocused()

  await last.focus()
  await page.keyboard.press('Tab')
  await expect(brand).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(last).toBeFocused()

  await page.keyboard.press('Escape')
  await expect(panel).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('遮罩关闭恢复焦点，命令面板 Escape 不关闭或抢占侧栏', async ({ page }) => {
  await page.goto('/#/kaoyan/schools')
  const trigger = openButton(page)
  await trigger.click()
  await page.locator('.v3-mobile-mask').click({ position: { x: 350, y: 400 } })
  await expect(drawer(page)).toHaveCount(0)
  await expect(trigger).toBeFocused()

  await trigger.click()
  await page.keyboard.press('Control+k')
  const command = page.getByRole('dialog', { name: '命令面板' })
  await expect(command).toBeVisible()
  await expect(command.getByRole('textbox')).toBeFocused()
  await expect(drawer(page)).toHaveCount(0)

  await page.keyboard.press('Escape')
  await expect(command).toHaveCount(0)
  await expect(drawer(page)).toHaveCount(0)

  // 侧栏打开时，Escape 只关闭侧栏，不产生命令面板。
  await trigger.click()
  await expect(page.getByRole('dialog', { name: '主导航' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(drawer(page)).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: '命令面板' })).toHaveCount(0)
})

test('桌面侧栏保持常驻且不接管焦点', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/#/kaoyan/schools')
  await expect(openButton(page)).toBeHidden()
  await expect(drawer(page)).toBeVisible()
  await expect(drawer(page).locator('.v3-brand')).toBeVisible()
  await expect(page.locator('.v3-mobile-mask')).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: '主导航' })).toHaveCount(0)

  await drawer(page).locator('.v3-brand').focus()
  await page.keyboard.press('Escape')
  await expect(drawer(page).locator('.v3-brand')).toBeFocused()
})
