// 临时探针：公网 /kaoyan 院校库页面实测（用户视角）。执行后删除。
const { BASE, OUT, makePage, gotoPage, settle } = require('./common.cjs')
const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch()
  const { page, rec } = await makePage(browser)
  for (const [name, hash] of [['schools', '/#/kaoyan'], ['schools-direct', '/kaoyan']]) {
    try {
      await gotoPage(page, hash)
      await settle(page, 6000)
      const state = await page.evaluate(() => {
        const rows = document.querySelectorAll('table tbody tr, [class*="school-row"], [class*="card"]')
        const text = document.body.innerText.slice(0, 400)
        return {
          rowCount: document.querySelectorAll('tbody tr').length,
          cardCount: document.querySelectorAll('[class*="card"]').length,
          hasErrorBanner: /加载失败|出错|Error|失败/.test(document.body.innerText.slice(0, 2000)),
          bodyHead: text,
        }
      })
      await page.screenshot({ path: `${OUT}/probe-kaoyan-${name}.png`, fullPage: false })
      console.log(`[${name}] rows=${state.rowCount} cards=${state.cardCount} errBanner=${state.hasErrorBanner}`)
      console.log('bodyHead:', JSON.stringify(state.bodyHead.slice(0, 200)))
    } catch (e) {
      console.log(`[${name}] EXCEPTION ${e.message.slice(0, 120)}`)
    }
  }
  console.log('consoleErrors:', rec.console.slice(0, 5))
  console.log('pageErrors:', rec.pageErrors.slice(0, 5))
  console.log('badResponses:', rec.badResponses.slice(0, 8))
  await browser.close()
})()
