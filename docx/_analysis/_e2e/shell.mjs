import { launch, openPage, shot, api, dump } from './harness.mjs'

const routes = ['/', '/tasks', '/kbmap', '/library', '/quiz', '/quiz-bank', '/panorama', '/exam-frequency',
  '/subjects', '/analysis', '/profile', '/error-review', '/documents', '/notebook', '/planner',
  '/assistant', '/pan', '/words', '/cards', '/settings', '/kaoyan', '/kaoyan/schools', '/kaoyan/compare',
  '/kaoyan/analysis', '/kaoyan/recommend', '/kaoyan/map', '/kaoyan/import']

const browser = await launch()
const rows = []
try {
  for (const r of routes) {
    const p = await openPage(browser, r, { waitMs: 3000 })
    const errs = p.consoleMsgs.filter(m => m.type === 'error')
    const bad = p.apiCalls.filter(a => a.status >= 400)
    const row = {
      route: r,
      rootLen: p.state?.rootLen,
      pageErrors: p.pageErrors.length,
      consoleErr: errs.length,
      api4xx5xx: bad.map(b => b.status + ' ' + b.url).join(';') || '',
      white: (p.state?.rootLen ?? 0) < 400,
      errSample: errs.slice(0, 2).map(e => e.text.slice(0, 160)).join(' || '),
    }
    rows.push(row)
    if (row.white || row.pageErrors || errs.length || bad.length) await shot(p.page, 'shell-anomaly' + r.replace(/\W+/g, '_') + '.png')
    await p.ctx.close()
  }
  console.log('route'.padEnd(22), 'rootLen', 'pErr', 'cErr', 'api4xx', 'white')
  for (const r of rows) {
    console.log(String(r.route).padEnd(22), String(r.rootLen).padEnd(7), String(r.pageErrors).padEnd(4), String(r.consoleErr).padEnd(4), (r.api4xx5xx || '-').padEnd(30), r.white ? 'YES' : '')
  }
  console.log('\n--- 异常明细 ---')
  for (const r of rows) {
    if (r.pageErrors || r.consoleErr || r.api4xx5xx || r.white) console.log(r.route, dump({ white: r.white, pErr: r.pageErrors, cErr: r.consoleErr, api: r.api4xx5xx, sample: r.errSample }))
  }

  // 首页仪表盘数据核对 + 导航点击
  const p = await openPage(browser, '/', { waitMs: 3500 })
  const dash = await api('/api/dashboard')
  const tiles = await p.page.evaluate(() => [...document.querySelectorAll('.card, .stat-tile, [class*=stat]')].map(e => e.innerText.replace(/\s+/g, ' ')).slice(0, 12))
  console.log('\n### Dashboard 页面文本片段:', dump(tiles.slice(0, 8)))
  console.log('后端 /api/dashboard:', dump({ countdown: dash.json?.countdown, stats: dash.json?.stats, today: dash.json?.today_tasks?.length }))
  // 逐个点击侧边栏主导航
  const navClicks = []
  for (const label of ['学习文库', '知识地图', '题库', '单词记忆', '错题复盘', '院校数据中心']) {
    const el = p.page.locator('button, a', { hasText: new RegExp('^' + label + '$') }).first()
    if (await el.count()) {
      await el.click().catch(() => {})
      await p.page.waitForTimeout(1200)
      navClicks.push(label + ' -> ' + await p.page.evaluate(() => location.hash))
    } else navClicks.push(label + ' -> (未找到入口)')
  }
  console.log('侧边栏点击结果:', dump(navClicks))
  await shot(p.page, 'shell-dashboard.png')
} catch (e) { console.log('异常:', String(e)) }
await browser.close()
