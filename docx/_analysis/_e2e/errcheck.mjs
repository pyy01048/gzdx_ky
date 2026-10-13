// 证据：错题复盘详情里"正确答案"是否仍显示【草稿】前缀
import { launch, openPage, shot } from './harness.mjs'
const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' '))
const browser = await launch()
try {
  const p = await openPage(browser, '/error-review', { waitMs: 4500 })
  log('consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length)
  const n = await p.page.evaluate(() => [...document.querySelectorAll('button')].filter(b => /未掌握|已掌握/.test(b.innerText) && b.innerText.length > 20).length)
  log('错题条目数:', n)
  let found = false
  for (let i = 0; i < n && i < 25; i++) {
    const item = p.page.locator('button').filter({ hasText: /未掌握|已掌握/ }).filter({ hasText: /复习 \d+ 次/ }).nth(i)
    if (!(await item.count())) continue
    await item.scrollIntoViewIfNeeded().catch(() => {})
    await item.click().catch(() => {})
    await p.page.waitForTimeout(700)
    const d = await p.page.evaluate(() => {
      const t = document.body.innerText
      const i = t.lastIndexOf('正确答案')
      return i >= 0 ? t.slice(i, i + 120).replace(/\n+/g, ' | ') : null
    })
    if (d && d.includes('【草稿')) {
      log(`>>> 命中第 ${i + 1} 条错题，正确答显示:`, d)
      await shot(p.page, 'evidence-errorreview-caogao.png')
      found = true
      break
    }
    if (i < 2) log(`  第${i + 1}条 正确答案片段:`, d)
  }
  if (!found) log('前 25 条错题详情未发现【草稿】')
  await p.ctx.close()
} catch (e) { log('异常:', String(e)) }
await browser.close()
console.log('=== DONE ===')
