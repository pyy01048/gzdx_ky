// decisive: in-page fetch vs context.request at the same moment
const { chromium } = require('playwright');
const C = require('./common.cjs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const { ctx, page } = await C.makePage(browser);
  await page.goto(C.BASE + '/#/tasks', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);

  const today = new Date().toISOString().slice(0, 10);
  const cr = await page.request.post(C.BASE + '/api/tasks', { data: { title: '【测试】e2e', subject: '其他', due_date: today, priority: 0 }, headers: { 'Content-Type': 'application/json' } });
  const crBody = await cr.text();
  let tid = null; try { tid = JSON.parse(crBody).id; } catch (e) {}
  console.log('[create]', cr.status(), crBody);

  const inPage = await page.evaluate(() => fetch('/api/tasks?page=1&page_size=200', { credentials: 'include' }).then(r => r.text()));
  const viaCtx = await (await page.request.get(C.BASE + '/api/tasks?page=1&page_size=200')).text();
  console.log('[in-page fetch] ', inPage.slice(0, 220));
  console.log('[context request]', viaCtx.slice(0, 220));
  const docCookie = await page.evaluate(() => document.cookie);
  const ctxCookies = await ctx.cookies(C.BASE);
  console.log('[doc.cookie]', docCookie);
  console.log('[ctx cookies]', JSON.stringify(ctxCookies.map(c => c.name + '=' + String(c.value).slice(0, 12) + '... exp=' + c.expires)));

  if (tid) { const del = await page.request.delete(C.BASE + '/api/tasks/' + tid); console.log('[cleanup]', del.status()); }
  await ctx.close(); await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
