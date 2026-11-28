import { chromium } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

const baseURL = 'http://127.0.0.1:5173'
const token = process.env.SHOUTU_TEST_ACCESS
if (!token) throw new Error('缺少本地验收会话')

const routes = [
  ['hub', '/#/hub'],
  ['quiz', '/#/quiz'],
  ['words', '/#/words'],
  ['cards', '/#/cards'],
  ['plan', '/#/kaoyan/plan'],
  ['diagram', '/#/tools?tool=diagram'],
]
const viewports = [
  ['1440', { width: 1440, height: 900 }],
  ['390', { width: 390, height: 844 }],
]
const results = []
const browser = await chromium.launch({ headless: true })

async function inspectPage(page) {
  return page.evaluate(() => {
    const visible = (element) => {
      const rect = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      return rect.width > 0 && rect.height > 0
        && style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0'
        && rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight
    }
    const rendered = (element) => {
      const rect = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0'
    }
    const targets = [...document.querySelectorAll('a, button, input, select, textarea, [role="button"]')]
      .filter((node) => !node.closest('.v3-skip-link'))
      .filter(visible)
    return {
      url: location.hash,
      h1: [...document.querySelectorAll('h1')].filter(rendered).map((node) => node.textContent.trim()),
      h1Geometry: [...document.querySelectorAll('h1')].map((node) => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return { text: node.textContent.trim(), top: Math.round(rect.top), height: Math.round(rect.height), display: style.display, visibility: style.visibility, opacity: style.opacity }
      }),
      overflow: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
      smallTargets: targets.filter((node) => {
        const rect = node.getBoundingClientRect()
        return rect.width < 44 || rect.height < 44
      }).map((node) => {
        const rect = node.getBoundingClientRect()
        return {
          tag: node.tagName.toLowerCase(), className: node.className,
          label: node.getAttribute('aria-label') || node.textContent.trim().slice(0, 30),
          width: Math.round(rect.width), height: Math.round(rect.height),
        }
      }),
      runningAnimations: document.getAnimations().filter((animation) => animation.playState === 'running').length,
    }
  })
}

for (const [viewportName, viewport] of viewports) {
  const context = await browser.newContext({ viewport, reducedMotion: 'reduce' })
  await context.addCookies([{
    name: 'kaoyan_access', value: token, domain: '127.0.0.1',
    path: '/', httpOnly: true, sameSite: 'Lax',
  }])
  for (const [name, route] of routes) {
    const page = await context.newPage()
    const pageErrors = []
    const httpErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('response', (response) => {
      if (response.status() >= 400) httpErrors.push({ status: response.status(), path: new URL(response.url()).pathname })
    })
    try {
      await page.goto(`${baseURL}${route}`, { waitUntil: 'domcontentloaded' })
      await page.locator('h1:visible').first().waitFor({ timeout: 30000 })
      await page.waitForTimeout(1200)
      if (name === 'diagram') await page.locator('.v3-td-svg svg').waitFor({ timeout: 30000 })
      const metrics = await inspectPage(page)
      const result = { viewport: viewportName, route: name, ...metrics, pageErrors, httpErrors }
      if (viewportName === '390' && name === 'hub') {
        await page.getByRole('button', { name: '打开导航' }).click()
        await page.locator('.v3-sidebar.is-open').waitFor()
        result.drawer = await inspectPage(page)
        await page.screenshot({ path: 'acceptance/auth-drawer-390.png', fullPage: false })
      }
      results.push(result)
      await page.screenshot({ path: `acceptance/auth-${name}-${viewportName}.png`, fullPage: true })
    } catch (error) {
      results.push({ viewport: viewportName, route: name, error: error.message, pageErrors, httpErrors })
      await page.screenshot({ path: `acceptance/auth-${name}-${viewportName}-failed.png`, fullPage: true }).catch(() => {})
    } finally {
      await page.close()
    }
  }
  await context.close()
}

await browser.close()
await writeFile('acceptance/authenticated-smoke-report.json', JSON.stringify({ date: new Date().toISOString(), results }, null, 2))
for (const result of results) {
  console.log(JSON.stringify({
    viewport: result.viewport, route: result.route, h1: result.h1, overflow: result.overflow,
    smallTargets: result.smallTargets?.length, smallTargetDetails: result.smallTargets,
    drawerSmallTargets: result.drawer?.smallTargets?.length, drawerSmallTargetDetails: result.drawer?.smallTargets,
    animations: result.runningAnimations, pageErrors: result.pageErrors?.length, httpErrors: result.httpErrors, error: result.error,
  }))
}
if (results.some((result) => result.error || result.url?.includes('/login') || result.h1?.length !== 1
  || result.overflow > 0 || result.pageErrors?.length || result.httpErrors?.length
  || (result.viewport === '390' && (result.smallTargets?.length || result.drawer?.smallTargets?.length || result.runningAnimations)))) {
  process.exitCode = 1
}
