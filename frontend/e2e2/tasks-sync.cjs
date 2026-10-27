// final tasks experiment: when does the UI refetch tasks?
const path = require('path');
const { chromium } = require('playwright');
const C = require('./common.cjs');
const SH = p => path.join(C.SHOTS, p);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const { ctx, page, rec } = await C.makePage(browser);
  let gets = [];
  page.on('response', async r => {
    if (r.request().method() === 'GET' && r.url().includes('/api/tasks')) {
      let b = ''; try { b = (await r.text()).slice(0, 160); } catch (e) {}
      gets.push({ t: Date.now(), u: r.url().replace(C.BASE, ''), status: r.status(), body: b });
    }
  });
  const R = {};
  // load
  await page.goto(C.BASE + '/#/tasks', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);
  const today = new Date().toISOString().slice(0, 10);
  const cr = await page.request.post(C.BASE + '/api/tasks', { data: { title: '【测试】e2e', subject: '其他', due_date: today, priority: 0 }, headers: { 'Content-Type': 'application/json' } });
  let tid = null; try { tid = JSON.parse(await cr.text()).id; } catch (e) {}
  console.log('[create]', cr.status(), tid);

  // 1. wait 12s in place: does periodic sync pick it up?
  gets = [];
  await page.waitForTimeout(12000);
  let vis = /【测试】e2e/.test((await C.snapshotState(page)).bodyText);
  R.inPlaceSync = { waited: '12s', newGets: gets.length, visible: vis };
  console.log('[in-place 12s]', JSON.stringify(R.inPlaceSync), JSON.stringify(gets));

  // 2. navigate away and back (hash nav)
  gets = [];
  await C.gotoPage(page, '/#/', 2500);
  await C.gotoPage(page, '/#/tasks', 3500);
  vis = /【测试】e2e/.test((await C.snapshotState(page)).bodyText);
  R.hashNav = { newGets: gets.length, bodies: gets.map(g => g.body.slice(0, 60)), visible: vis };
  console.log('[hash nav]', JSON.stringify(R.hashNav));
  await page.screenshot({ path: SH('tasks-sync-hashnav.png'), fullPage: true });

  // 3. full reload
  gets = [];
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);
  vis = /【测试】e2e/.test((await C.snapshotState(page)).bodyText);
  R.fullReload = { newGets: gets.length, bodies: gets.map(g => g.body.slice(0, 60)), visible: vis };
  console.log('[full reload]', JSON.stringify(R.fullReload));
  await page.screenshot({ path: SH('tasks-sync-reload.png'), fullPage: true });

  // 4. manual refresh button? there is 刷新 on dashboard; tasks page may not have one. try 刷新 if exists
  const rf = page.getByText('刷新', { exact: true }).first();
  if (await rf.count()) {
    gets = [];
    await rf.click({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(3000);
    vis = /【测试】e2e/.test((await C.snapshotState(page)).bodyText);
    R.refreshBtn = { newGets: gets.length, bodies: gets.map(g => g.body.slice(0, 60)), visible: vis };
    console.log('[refresh btn]', JSON.stringify(R.refreshBtn));
  }

  // cleanup
  if (tid) { const del = await page.request.delete(C.BASE + '/api/tasks/' + tid); console.log('[cleanup]', del.status()); }
  C.saveResult('tasks-sync', R);
  await ctx.close(); await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
