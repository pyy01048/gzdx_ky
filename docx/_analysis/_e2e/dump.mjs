// 六大模块首轮真实浏览器采集：渲染/控制台/白屏/接口/可见交互元素
import { launch, openPage, shot, api } from './harness.mjs'

const ROUTES = [
  ['library', '/library'],
  ['kbmap', '/kbmap'],
  ['quiz-bank', '/quiz-bank'],
  ['quiz', '/quiz'],
  ['words', '/words'],
  ['error-review', '/error-review'],
  ['kaoyan', '/kaoyan'],
]

const browser = await launch()
for (const [name, route] of ROUTES) {
  let r
  try {
    r = await openPage(browser, route, { waitMs: 4000 })
  } catch (e) { console.log(`\n### ${name} ${route}\n  LAUNCH-ERR`, e.message); continue }
  const { page, consoleMsgs, pageErrors, failedReqs, apiCalls, navErr, state, url } = r
  console.log(`\n================ ${name}  ${route} ================`)
  console.log('url:', url, '| navErr:', navErr)
  console.log('state:', JSON.stringify(state))
  const errs = consoleMsgs.filter(m => m.type === 'error')
  console.log(`console errors(${errs.length}):`)
  errs.slice(0, 8).forEach(m => console.log('  ⛔', m.text.slice(0, 400)))
  const warns = consoleMsgs.filter(m => m.type === 'warning')
  console.log(`console warnings(${warns.length}):`)
  warns.slice(0, 5).forEach(m => console.log('  ⚠', m.text.slice(0, 200)))
  console.log(`pageErrors(${pageErrors.length}):`)
  pageErrors.slice(0, 5).forEach(e => console.log('  💥', e.slice(0, 400)))
  console.log(`failedReqs(${failedReqs.length}):`)
  failedReqs.slice(0, 8).forEach(f => console.log('  ✖', f.url.slice(0, 120), f.err))
  const bad = apiCalls.filter(c => c.status >= 400)
  console.log(`apiCalls(${apiCalls.length}) 非2xx(${bad.length}):`)
  bad.slice(0, 10).forEach(c => console.log('  ❌', c.status, c.url))
  apiCalls.slice(0, 12).forEach(c => console.log('   ·', c.status, c.url))

  // 可见交互元素
  const interactives = await page.evaluate(() => {
    const out = []
    document.querySelectorAll('button, a, [role="button"], [role="tab"], input, select').forEach(el => {
      const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ')
      const rect = el.getBoundingClientRect()
      if (rect.width > 0 && rect.height > 0 && t) out.push(`${el.tagName.toLowerCase()}${el.getAttribute('role') ? '[' + el.getAttribute('role') + ']' : ''}: ${t.slice(0, 40)}`)
    })
    return out.slice(0, 45)
  }).catch(() => [])
  console.log('可见交互元素(前45):')
  interactives.forEach(x => console.log('  ▸', x))

  const visText = await page.evaluate(() => (document.getElementById('root')?.innerText || '').slice(0, 900)).catch(() => '')
  console.log('--- 可见文本前900 ---')
  console.log(visText)

  await shot(page, `${name}-01-landing.png`, { fullPage: true })
  await r.ctx.close().catch(() => {})
}
await browser.close()
console.log('\n=== DONE ===')
