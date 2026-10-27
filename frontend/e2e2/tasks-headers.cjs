// capture app's real request headers for /api/tasks + service worker check
const { chromium } = require('playwright');
const C = require('./common.cjs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const { ctx, page } = await C.makePage(browser);

  await page.route('**/api/tasks*', route => {
    const h = route.request().headers();
    console.log('[REQ]', route.request().method(), route.request().url().replace(C.BASE, ''), '| auth:', h['authorization'] || 'NONE', '| x-headers:', JSON.stringify(Object.fromEntries(Object.entries(h).filter(([k]) => k.startsWith('x-') || k.includes('subject') || k.includes('user')))));
    route.continue();
  });

  await page.goto(C.BASE + '/#/tasks', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(7000);
  const sw = await page.evaluate(async () => {
    if (!navigator.serviceWorker) return 'unsupported';
    const regs = await navigator.serviceWorker.getRegistrations();
    return regs.map(r => r.scope + ' active=' + !!r.active);
  });
  console.log('[service workers]', JSON.stringify(sw));
  const ls = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage).map(([k, v]) => [k, v.slice(0, 120)])));
  console.log('[localStorage]', JSON.stringify(ls));
  const ss = await page.evaluate(() => Object.keys(sessionStorage));
  console.log('[sessionStorage keys]', JSON.stringify(ss));
  await ctx.close(); await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
