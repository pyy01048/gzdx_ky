// 收尾：/settings 422 影响 + 稀疏页面是否真白屏
import { launch, openPage, shot, api } from './harness.mjs'
const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' '))
const browser = await launch()
for (const [name, route] of [['settings', '/settings'], ['tasks', '/tasks'], ['planner', '/planner'], ['kaoyan-compare', '/kaoyan/compare'], ['kaoyan-recommend', '/kaoyan/recommend'], ['cards', '/cards']]) {
  const p = await openPage(browser, route, { waitMs: 4000 })
  const errs = p.consoleMsgs.filter(m => m.type === 'error').map(e => e.text.slice(0, 160))
  const bad = p.apiCalls.filter(c => c.status >= 400)
  const info = await p.page.evaluate(() => {
    const t = (document.getElementById('root')?.innerText || '').trim()
    return {
      rootLen: t.length,
      selects: [...document.querySelectorAll('select')].map(s => ({ opts: s.options.length, first: s.options[0]?.text })),
      inputs: document.querySelectorAll('input,textarea').length,
      tail: t.replace(/\s+/g, ' ').slice(-260),
    }
  })
  log(`\n### ${name} ${route}`)
  log('  rootLen=', info.rootLen, '| consoleErr=', errs.length, '| api>=400=', bad.map(b => b.status + ' ' + b.url).join(';') || '-')
  if (errs.length) log('  ERR原文:', errs)
  log('  selects:', info.selects, '| inputs:', info.inputs)
  log('  文本尾部:', info.tail)
  await shot(p.page, `final-${name}.png`)
  await p.ctx.close()
}
await browser.close()
console.log('\n=== FINAL DONE ===')
