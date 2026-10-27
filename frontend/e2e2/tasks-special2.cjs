// tasks page deep test round 2: data consistency, date switch, view tabs
const path = require('path');
const { chromium } = require('playwright');
const C = require('./common.cjs');
const SH = p => path.join(C.SHOTS, p);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const { ctx, page, rec } = await C.makePage(browser);
  const apiResp = [];
  page.on('response', async r => {
    if (r.url().includes('/api/')) {
      let b = ''; try { b = (await r.text()).slice(0, 400); } catch (e) {}
      apiResp.push({ m: r.request().method(), u: r.url().replace(C.BASE, ''), status: r.status(), body: b });
    }
  });
  const R = {};

  // 0. direct API probe: does backend list tasks?
  const list1 = await page.request.get(C.BASE + '/api/tasks');
  const list1Body = await list1.text();
  R.apiTasksNoParams = { status: list1.status(), body: list1Body.slice(0, 600) };
  console.log('[GET /api/tasks]', list1.status(), list1Body.slice(0, 400));

  // 1. create test task via API again
  const today = new Date().toISOString().slice(0, 10);
  const cr = await page.request.post(C.BASE + '/api/tasks', { data: { title: '【测试】e2e', subject: '其他', due_date: today, priority: 0 }, headers: { 'Content-Type': 'application/json' } });
  const crBody = await cr.text();
  R.create = { status: cr.status(), body: crBody };
  console.log('[create]', cr.status(), crBody);
  let tid = null; try { tid = JSON.parse(crBody).id; } catch (e) {}

  // 2. load UI, capture what tasks API returns to the app
  await page.goto(C.BASE + '/#/tasks', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);
  const st = await C.snapshotState(page);
  R.uiAfterCreate = { visible: /【测试】e2e/.test(st.bodyText), body: st.bodyText.slice(0, 500) };
  const taskApiCalls = apiResp.filter(a => a.u.includes('/api/tasks') && a.m === 'GET');
  R.uiTaskFetches = taskApiCalls;
  await page.screenshot({ path: SH('tasks-testtask2.png'), fullPage: true });
  console.log('[ui visible]', R.uiAfterCreate.visible, '| GET calls:', JSON.stringify(taskApiCalls.map(a => a.u + '->' + a.status)));

  // 3. enumerate all buttons (incl. icon-only) to find date chevrons
  const btns = await page.evaluate(() => Array.from(document.querySelectorAll('button')).map((e, i) => {
    const r = e.getBoundingClientRect();
    return { i, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), w: Math.round(r.width), h: Math.round(r.height), txt: (e.innerText || '').trim().slice(0, 24), aria: e.getAttribute('aria-label') || '', title: e.title || '', cls: (e.className || '').toString().slice(0, 70) };
  }).filter(e => e.w > 0));
  R.allButtons = btns;
  console.log('[buttons]', JSON.stringify(btns));

  // date text probe
  const dateText = async () => (await C.snapshotState(page)).bodyText.match(/(\d{1,2}月\d{1,2}日[^·]*)|(\d{4}-\d{2}-\d{2})/);
  const d0 = await dateText();
  // click icon-only buttons in header area (y between 120 and 260, small)
  const iconBtns = btns.filter(b => !b.txt && b.y > 100 && b.y < 300);
  const dateSeq = [];
  for (const b of iconBtns.slice(0, 4)) {
    await page.mouse.click(b.x, b.y);
    await page.waitForTimeout(1400);
    const d1 = await dateText();
    dateSeq.push({ cls: b.cls.slice(0, 40), aria: b.aria, dateAfter: d1 && d1[1], toasts: (await C.snapshotState(page)).toasts });
  }
  R.dateSwitch = { before: d0 && d0[1], seq: dateSeq };
  console.log('[date switch]', JSON.stringify(R.dateSwitch));
  await page.screenshot({ path: SH('tasks-date2.png'), fullPage: true });

  // 4. view tabs 日视图/周视图/月视图
  const viewSeq = [];
  for (const t of ['周视图', '月视图', '日视图']) {
    const b = page.getByText(t, { exact: true }).first();
    if (await b.count()) {
      const netMark = apiResp.length;
      await b.click({ timeout: 2000 }).catch(e => {});
      await page.waitForTimeout(1800);
      const s2 = await C.snapshotState(page);
      viewSeq.push({ tab: t, dlg: s2.dlgVisible, len: s2.bodyLen, sample: s2.bodyText.slice(0, 160).replace(/\n/g, '|'), newApi: apiResp.slice(netMark).map(a => a.m + ' ' + a.u + ' ' + a.status) });
      await page.screenshot({ path: SH('tasks-view-' + t + '.png'), fullPage: true });
    }
  }
  R.viewTabs = viewSeq;
  console.log('[view tabs]', JSON.stringify(viewSeq).slice(0, 900));

  // 5. if test task visible -> toggle done via UI
  if (R.uiAfterCreate.visible && tid) {
    const probe = await page.evaluate(() => {
      const t = Array.from(document.querySelectorAll('*')).find(e => e.children.length === 0 && /【测试】e2e/.test(e.textContent || ''));
      if (!t) return null;
      let row = t; for (let k = 0; k < 8 && row.parentElement; k++) { row = row.parentElement; if (row.querySelectorAll('button, input').length >= 1 && row.textContent.length < 300) break; }
      const items = Array.from(row.querySelectorAll('button, input[type="checkbox"]')).map((b, i) => { const r = b.getBoundingClientRect(); return { i, tag: b.tagName, type: b.type || '', x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), txt: (b.innerText || '').trim().slice(0, 16), aria: b.getAttribute('aria-label') || '', cls: (b.className || '').toString().slice(0, 50) }; });
      return { rowText: row.textContent.trim().slice(0, 160), items };
    });
    R.taskRow = probe;
    console.log('[task row]', JSON.stringify(probe));
    if (probe && probe.items.length) {
      const cb = probe.items.find(b => b.tag === 'INPUT' || /check|circle|complete|done/i.test(b.cls + b.aria)) || probe.items[0];
      const mark = apiResp.length;
      await page.mouse.click(cb.x, cb.y);
      await page.waitForTimeout(2500);
      const s3 = await C.snapshotState(page);
      R.uiCompleteToggle = { clicked: cb, stillVisible: /【测试】e2e/.test(s3.bodyText), newApi: apiResp.slice(mark).map(a => a.m + ' ' + a.u + ' ' + a.status + ' ' + a.body.slice(0, 80)), toasts: s3.toasts };
      await page.screenshot({ path: SH('tasks-testtask-toggle.png'), fullPage: true });
      console.log('[toggle]', JSON.stringify(R.uiCompleteToggle).slice(0, 500));

      // edit modal: click edit-looking button
      const eBtn = (probe.items || []).find(b => /edit|pen|编辑|square/i.test(b.cls + b.aria + b.txt));
      if (eBtn) {
        const mark2 = apiResp.length;
        await page.mouse.click(eBtn.x, eBtn.y);
        await page.waitForTimeout(1800);
        const s4 = await C.snapshotState(page);
        R.uiEditModal = { open: s4.dlgVisible, text: s4.dlgText.slice(0, 300) };
        await page.screenshot({ path: SH('tasks-testtask-edit2.png'), fullPage: true });
        console.log('[edit modal]', JSON.stringify(R.uiEditModal));
        await page.keyboard.press('Escape'); await page.waitForTimeout(500); await C.closeOverlays(page);
      }
      // delete via UI
      const dBtn = (probe.items || []).find(b => /del|trash|删除|remove/i.test(b.cls + b.aria + b.txt));
      if (dBtn) {
        const mark3 = apiResp.length;
        await page.mouse.click(dBtn.x, dBtn.y);
        await page.waitForTimeout(1500);
        const s5 = await C.snapshotState(page);
        R.uiDeleteConfirm = { dlg: s5.dlgVisible, text: s5.dlgText.slice(0, 200) };
        await page.screenshot({ path: SH('tasks-testtask-delconfirm.png'), fullPage: true });
        if (s5.dlgVisible) {
          const ok = page.locator('[role="dialog"] button:has-text("删除"), [role="dialog"] button:has-text("确定"), [class*="modal" i] button:has-text("删除"), [class*="modal" i] button:has-text("确定")').first();
          if (await ok.count()) { await ok.click({ timeout: 2000 }).catch(() => {}); await page.waitForTimeout(2200); }
        }
        const s6 = await C.snapshotState(page);
        R.uiDelete = { gone: !/【测试】e2e/.test(s6.bodyText), newApi: apiResp.slice(mark3).map(a => a.m + ' ' + a.u + ' ' + a.status) };
        await page.screenshot({ path: SH('tasks-testtask-afterdel.png'), fullPage: true });
        console.log('[delete ui]', JSON.stringify(R.uiDelete));
      }
    }
  }
  // cleanup by API if still there
  if (tid) {
    const chk = await page.request.get(C.BASE + '/api/tasks');
    const chkBody = await chk.text();
    if (chkBody.includes('【测试】e2e')) {
      const del = await page.request.delete(C.BASE + '/api/tasks/' + tid);
      R.cleanup = { status: del.status() };
      console.log('[cleanup api delete]', del.status());
    }
  }
  R.consoleErrors = rec.console.filter(c => c.type === 'error');
  R.badResponses = rec.badResponses;
  C.saveResult('tasks-special2', R);
  await ctx.close(); await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
