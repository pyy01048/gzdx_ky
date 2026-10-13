import { launch, openPage, dump } from './harness.mjs'

const routes = process.argv.slice(2)
const browser = await launch()
try {
  for (const r of routes) {
    const p = await openPage(browser, r, { waitMs: 3500 })
    const info = await p.page.evaluate(() => {
      const vis = (el) => {
        const s = getComputedStyle(el)
        const rect = el.getBoundingClientRect()
        return s.display !== 'none' && s.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
      }
      const txt = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 60)
      const btns = [...document.querySelectorAll('button, [role=button], a')].filter(vis).map((e) => `${e.tagName.toLowerCase()}:${txt(e)}`).filter((t) => t.split(':')[1]).slice(0, 60)
      const inputs = [...document.querySelectorAll('input, textarea, select')].filter(vis).map((e) => `${e.tagName.toLowerCase()}[${e.type || ''}]ph="${e.placeholder || ''}"cls="${(e.className || '').toString().slice(0, 40)}"`).slice(0, 30)
      const tables = [...document.querySelectorAll('table, .card, [class*=list], [class*=item], [class*=row]')].length
      const root = document.getElementById('root') || document.body
      return { rootLen: (root.innerText || '').trim().length, btns, inputs, listishEls: tables, text: (root.innerText || '').trim().replace(/\n{2,}/g, '\n').slice(0, 1200) }
    })
    console.log('\n########## ROUTE', r, '##########')
    console.log('navErr:', p.navErr, '| pageErrors:', p.pageErrors.length, '| consoleErr:', p.consoleMsgs.filter(m => m.type === 'error').length, '| failedReq:', p.failedReqs.length, '| rootLen:', info.rootLen)
    if (p.pageErrors.length) console.log('PAGEERRORS:', dump(p.pageErrors.slice(0, 3)))
    const cerr = p.consoleMsgs.filter((m) => m.type === 'error')
    if (cerr.length) console.log('CONSOLE-ERR:', dump(cerr.slice(0, 5)))
    if (p.failedReqs.length) console.log('FAILED-REQ:', dump(p.failedReqs.slice(0, 6)))
    const bad = p.apiCalls.filter((a) => a.status >= 400)
    if (bad.length) console.log('API-4xx5xx:', dump(bad))
    console.log('BUTTONS/LINKS:', dump(info.btns))
    console.log('INPUTS:', dump(info.inputs))
    console.log('TEXT>>>', info.text)
    await p.ctx.close()
  }
} finally { await browser.close() }
