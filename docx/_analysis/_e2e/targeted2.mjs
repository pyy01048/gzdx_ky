// 修正版针对性验证：kbmap 知识点是否可点开详情 / panorama 详情 / words 数据来源
import { launch, openPage, shot, api, dump } from './harness.mjs'
const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : dump(x)).join(' '))
const browser = await launch()

/* A. /kbmap：知识点是否可点开详情 */
try {
  const p = await openPage(browser, '/kbmap', { waitMs: 5000 })
  log('\n===== A. /kbmap =====')
  const info = await p.page.evaluate(() => ({
    kpRows: document.querySelectorAll('.kb-kp').length,
    kpNames: [...document.querySelectorAll('.kb-kp-name')].slice(0, 8).map(e => e.innerText.trim()),
    openChapters: document.querySelectorAll('.kb-kp-list').length,
    keyword: {
      yuanwen: /原文/.test(document.body.innerText), zhailu: /摘录/.test(document.body.innerText),
      zhishikuai: /知识块/.test(document.body.innerText), guanlian: /关联/.test(document.body.innerText),
    },
  }))
  log('默认渲染:', info)
  const len0 = await p.page.evaluate(() => document.body.innerText.length)
  // 用 JS 点击知识点名称 + 整行（绕过可点击性检查）
  await p.page.evaluate(() => { document.querySelector('.kb-kp-name')?.click() })
  await p.page.waitForTimeout(1200)
  const after1 = await p.page.evaluate(() => ({
    len: document.body.innerText.length, hash: location.hash,
    panels: document.querySelectorAll('[class*=drawer],[class*=modal],[class*=detail],[class*=popover]').length,
  }))
  await p.page.evaluate(() => { document.querySelector('.kb-kp')?.click() })
  await p.page.waitForTimeout(1200)
  const after2 = await p.page.evaluate(() => ({
    len: document.body.innerText.length, hash: location.hash,
    panels: document.querySelectorAll('[class*=drawer],[class*=modal],[class*=detail],[class*=popover]').length,
  }))
  log('JS点击 .kb-kp-name 后:', { 文本变化: after1.len - len0, hash: after1.hash, 面板数: after1.panels })
  log('JS点击 .kb-kp 整行后:', { 文本变化: after2.len - len0, hash: after2.hash, 面板数: after2.panels })
  await shot(p.page, 'targeted-kbmap-kp.png')
  await p.ctx.close()
} catch (e) { log('A 异常:', String(e)) }

/* A2. /panorama：知识点详情面板 */
try {
  const p = await openPage(browser, '/panorama', { waitMs: 5000 })
  log('\n===== A2. /panorama =====')
  // 展开任一"关闭"的章节
  await p.page.evaluate(() => {
    const heads = [...document.querySelectorAll('.kb-chapter-head')]
    for (const h of heads) { if (!h.parentElement.querySelector('.kb-kp-list')) { h.click(); return } }
  })
  await p.page.waitForTimeout(1500)
  const n = await p.page.evaluate(() => document.querySelectorAll('.pn-kp').length)
  log('.pn-kp 数:', n)
  if (n > 0) {
    const listTxt = await p.page.evaluate(() => [...document.querySelectorAll('.pn-kp')].slice(0, 5).map(e => ({
      name: e.querySelector('.kb-kp-name')?.innerText?.trim(), freq: e.querySelector('.kb-kp-freq')?.innerText?.trim(),
    })))
    log('知识点(名/题量):', listTxt)
    await p.page.evaluate(() => document.querySelector('.pn-kp').click())
    await p.page.waitForTimeout(1000)
    const detail = await p.page.evaluate(() => document.querySelector('.pn-detail')?.innerText?.replace(/\s+/g, ' '))
    log('知识点详情面板:', detail)
    log('面板含原文/摘录/知识块:', /原文|摘录|知识块/.test(detail || ''))
    await shot(p.page, 'targeted-panorama-detail.png')
  }
  await p.ctx.close()
} catch (e) { log('A2 异常:', String(e)) }

/* B. /words：数据来源真伪 */
try {
  const p = await openPage(browser, '/words', { waitMs: 4500 })
  log('\n===== B. /words =====')
  // 重新发一次请求并抓响应体长度
  const resp = await p.page.evaluate(async () => {
    try {
      const r = await fetch('/api/words?page=1&page_size=500')
      const j = await r.json()
      return { status: r.status, items: Array.isArray(j) ? j.length : (j.items ? j.items.length : null), total: j.total, keys: j && !Array.isArray(j) ? Object.keys(j) : '(array)' }
    } catch (e) { return { err: String(e) } }
  })
  log('/api/words?page_size=500 响应:', resp)
  const dom = await p.page.evaluate(() => {
    const tiles = [...document.querySelectorAll('.stat-tile')].map(e => e.innerText.replace(/\s+/g, ' '))
    return { tiles, bodyHasApproach: /approach/.test(document.body.innerText), counter: document.body.innerText.match(/\d+\s*\/\s*\d+/)?.[0] }
  })
  log('页面统计块:', dom)
  log('后端 words/stats:', (await api('/api/words/stats')).json)
  log('>> 结论: 页面总词数 =', dom.tiles[0], ' vs 后端 total = 4569')
  await shot(p.page, 'targeted-words-truth.png')
  await p.ctx.close()
} catch (e) { log('B 异常:', String(e)) }

await browser.close()
console.log('\n=== TARGETED DONE ===')
