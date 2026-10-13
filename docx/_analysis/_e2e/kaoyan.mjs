import { launch, openPage, shot, api, dump } from './harness.mjs'

const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : dump(x)).join(' '))
const browser = await launch()
try {
  // 后端基准
  const sc = await api('/api/kaoyan/schools?page=1&page_size=20')
  const scArr = sc.json?.items || sc.json?.schools || (Array.isArray(sc.json) ? sc.json : [])
  log('后端 /api/kaoyan/schools total=', sc.json?.total, 'items=', scArr.length, '| sample:', dump(scArr.slice(0, 2).map(s => ({ id: s.id, name: s.name }))))
  const st = await api('/api/kaoyan/stats'); log('后端 /api/kaoyan/stats:', dump(st.json).slice(0, 400))

  /* ---- 院校库 ---- */
  const p = await openPage(browser, '/kaoyan/schools', { waitMs: 4500 })
  await shot(p.page, 'kaoyan-01-schools.png')
  log('\n### /kaoyan/schools')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, 'failedReq=', p.failedReqs.length, '| api4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))
  const s0 = await p.page.evaluate(() => ({
    cardNames: document.querySelectorAll('.ky-card-name').length,
    detailLinks: document.querySelectorAll('.ky-link').length,
    hotNames: document.querySelectorAll('.ky-hot-name').length,
    countText: document.body.innerText.match(/共[^\n]*院校|共\s*\d+\s*条|共\s*\d+/)?.[0],
    firstNames: [...document.querySelectorAll('.ky-card-name')].slice(0, 8).map(e => e.innerText.trim()),
  }))
  log('院校库:', s0)

  // 搜院校
  const input = p.page.locator('input[type=search]').first()
  log('搜索框存在:', await input.count())
  if (await input.count()) {
    await input.fill('邮电')
    await p.page.locator('button', { hasText: '搜索' }).first().click()
    await p.page.waitForTimeout(2500)
    const after = await p.page.evaluate(() => ({
      names: [...document.querySelectorAll('.ky-card-name')].slice(0, 10).map(e => e.innerText.trim()),
      cnt: document.querySelectorAll('.ky-card-name').length,
    }))
    log('搜索"邮电"后:', after)
    await shot(p.page, 'kaoyan-02-search.png')
  }

  // 点进详情
  const detail = p.page.locator('.ky-link').first()
  log('院校详情链接数:', await detail.count())
  if (await detail.count()) {
    await detail.scrollIntoViewIfNeeded().catch(() => {})
    await p.page.waitForTimeout(500)
    const href = await detail.getAttribute('href')
    await detail.click()
    await p.page.waitForTimeout(3500)
    const d = await p.page.evaluate(() => ({
      url: location.hash,
      textLen: document.body.innerText.length,
      head: document.body.innerText.replace(/\s+/g, ' ').slice(0, 600),
    }))
    log('详情页 href=', href, '-> url=', d.url, 'textLen=', d.textLen)
    log('详情页文本:', d.head)
    await shot(p.page, 'kaoyan-03-detail.png')
  }

  // 分数分析
  await p.page.goto('http://127.0.0.1:5173/#/kaoyan/analysis', { waitUntil: 'domcontentloaded' })
  await p.page.waitForTimeout(4000)
  const an = await p.page.evaluate(() => ({
    canvas: document.querySelectorAll('canvas').length,
    svg: document.querySelectorAll('svg').length,
    textLen: document.body.innerText.length,
    head: document.body.innerText.replace(/\s+/g, ' ').slice(0, 300),
  }))
  log('\n### /kaoyan/analysis:', an)
  await shot(p.page, 'kaoyan-04-analysis.png')

  // 院校对比
  await p.page.goto('http://127.0.0.1:5173/#/kaoyan/compare', { waitUntil: 'domcontentloaded' })
  await p.page.waitForTimeout(3500)
  const cmp = await p.page.evaluate(() => ({ textLen: document.body.innerText.length, head: document.body.innerText.replace(/\s+/g, ' ').slice(0, 250) }))
  log('### /kaoyan/compare:', cmp)
  await shot(p.page, 'kaoyan-05-compare.png')

  // 择校中心
  await p.page.goto('http://127.0.0.1:5173/#/kaoyan/guide', { waitUntil: 'domcontentloaded' })
  await p.page.waitForTimeout(3000)
  const gd = await p.page.evaluate(() => ({ textLen: document.body.innerText.length, head: document.body.innerText.replace(/\s+/g, ' ').slice(0, 250) }))
  log('### /kaoyan/guide:', gd)
  await shot(p.page, 'kaoyan-06-guide.png')
} catch (e) { log('异常:', String(e)) }
await browser.close()
