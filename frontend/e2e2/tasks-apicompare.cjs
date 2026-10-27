// pinpoint: GET /api/tasks with/without params, different auth states
const { chromium } = require('playwright');
const C = require('./common.cjs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const { ctx, page } = await C.makePage(browser);
  await page.goto(C.BASE + '/#/tasks', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000); // refresh auth

  const today = new Date().toISOString().slice(0, 10);
  const cr = await page.request.post(C.BASE + '/api/tasks', { data: { title: '【测试】e2e', subject: '其他', due_date: today, priority: 0 }, headers: { 'Content-Type': 'application/json' } });
  const crBody = await cr.text();
  let tid = null; try { tid = JSON.parse(crBody).id; } catch (e) {}
  console.log('[create]', cr.status(), crBody);

  const variants = [
    '/api/tasks',
    '/api/tasks?page=1&page_size=200',
    '/api/tasks?page=1&page_size=50',
    '/api/tasks?page_size=200',
    '/api/tasks?date=' + today,
    '/api/tasks?due_date=' + today,
    '/api/tasks?status=pending',
    '/api/tasks?all=1',
  ];
  for (const v of variants) {
    const r = await page.request.get(C.BASE + v);
    const t = await r.text();
    console.log('[' + v + ']', r.status(), t.slice(0, 260).replace(/\n/g, ''));
  }
  // auth header check: what does the app send? intercept via route
  await page.route('**/api/tasks**', route => {
    const h = route.request().headers();
    console.log('[app request headers]', JSON.stringify({ authorization: h['authorization'] ? 'present(len ' + h['authorization'].length + ')' : 'absent', cookie: h['cookie'] ? 'present(len ' + h['cookie'].length + ')' : 'absent', others: Object.keys(h).filter(k => !['accept', 'accept-encoding', 'accept-language', 'user-agent', 'referer', 'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site', 'sec-fetch-user', 'connection', 'host', 'content-length', 'content-type', 'origin', 'pragma', 'cache-control'].includes(k)).map(k => k + '=' + h[k].slice(0, 40)) }));
    route.continue();
  });
  await C.gotoPage(page, '/#/tasks', 5000);
  const st = await C.snapshotState(page);
  console.log('[ui visible]', /【测试】e2e/.test(st.bodyText));

  if (tid) {
    const del = await page.request.delete(C.BASE + '/api/tasks/' + tid);
    console.log('[cleanup]', del.status());
  }
  await ctx.close(); await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
