// tasks closed loop: load UI first (refresh auth), create, verify in UI, toggle/edit/delete
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
      let b = ''; try { b = (await r.text()).slice(0, 300); } catch (e) {}
      apiResp.push({ m: r.request().method(), u: r.url().replace(C.BASE, ''), status: r.status(), body: b });
    }
  });
  const R = {};

  // 1. load UI so in-app refresh sets fresh cookies
  await page.goto(C.BASE + '/#/tasks', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);
  R.bootBad = rec.badResponses.slice();

  // 2. create via API (context cookies refreshed by app)
  const today = new Date().toISOString().slice(0, 10);
  const cr = await page.request.post(C.BASE + '/api/tasks', { data: { title: '【测试】e2e', subject: '其他', due_date: today, priority: 0 }, headers: { 'Content-Type': 'application/json' } });
  const crBody = await cr.text();
  R.create = { status: cr.status(), body: crBody };
  console.log('[create]', cr.status(), crBody);
  let tid = null; try { tid = JSON.parse(crBody).id; } catch (e) {}
  if (!tid) { C.saveResult('tasks-special3', R); await ctx.close(); await browser.close(); return; }

  // 3. reload UI, check visibility
  await C.gotoPage(page, '/#/tasks', 5000);
  const st = await C.snapshotState(page);
  R.uiVisible = /【测试】e2e/.test(st.bodyText);
  await page.screenshot({ path: SH('tasks-loop-visible.png'), fullPage: true });
  console.log('[ui visible]', R.uiVisible, '|', st.bodyText.slice(0, 260).replace(/\n/g, '|'));

  if (R.uiVisible) {
    const probe = await page.evaluate(() => {
      const t = Array.from(document.querySelectorAll('*')).find(e => e.children.length === 0 && /【测试】e2e/.test(e.textContent || ''));
      if (!t) return null;
      let row = t; for (let k = 0; k < 8 && row.parentElement; k++) { row = row.parentElement; if (row.querySelectorAll('button, input').length >= 1 && row.textContent.length < 300) break; }
      const items = Array.from(row.querySelectorAll('button, input[type="checkbox"]')).map((b, i) => { const r = b.getBoundingClientRect(); return { i, tag: b.tagName, type: b.type || '', x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), txt: (b.innerText || '').trim().slice(0, 16), aria: b.getAttribute('aria-label') || '', cls: (b.className || '').toString().slice(0, 50) }; });
      return { rowText: row.textContent.trim().slice(0, 200), items };
    });
    R.taskRow = probe;
    console.log('[task row]', JSON.stringify(probe));

    // toggle complete
    if (probe && probe.items.length) {
      const cb = probe.items.find(b => b.tag === 'INPUT' || /check|circle|complete|done|toggle/i.test(b.cls + b.aria)) || probe.items[0];
      const mark = apiResp.length;
      await page.mouse.click(cb.x, cb.y);
      await page.waitForTimeout(2500);
      const s3 = await C.snapshotState(page);
      R.uiCompleteToggle = { clicked: { i: cb.i, tag: cb.tag, cls: cb.cls, aria: cb.aria }, newApi: apiResp.slice(mark).map(a => a.m + ' ' + a.u + ' ' + a.status + ' ' + a.body.slice(0, 120)), toasts: s3.toasts };
      await page.screenshot({ path: SH('tasks-loop-toggle.png'), fullPage: true });
      console.log('[toggle]', JSON.stringify(R.uiCompleteToggle).slice(0, 500));

      // edit modal
      const eBtn = probe.items.find(b => /edit|pen|编辑|square|pencil/i.test(b.cls + b.aria + b.txt));
      if (eBtn) {
        await page.mouse.click(eBtn.x, eBtn.y);
        await page.waitForTimeout(1800);
        const s4 = await C.snapshotState(page);
        R.uiEditModal = { open: s4.dlgVisible, text: s4.dlgText.slice(0, 400) };
        await page.screenshot({ path: SH('tasks-loop-edit.png'), fullPage: true });
        console.log('[edit modal]', JSON.stringify(R.uiEditModal).slice(0, 400));
        await page.keyboard.press('Escape'); await page.waitForTimeout(500); await C.closeOverlays(page);
      } else { R.uiEditModal = { note: 'no edit-looking button', items: probe.items }; }

      // delete
      const dBtn = probe.items.find(b => /del|trash|删除|remove|x\b/i.test(b.cls + b.aria + b.txt));
      if (dBtn) {
        const mark3 = apiResp.length;
        await page.mouse.click(dBtn.x, dBtn.y);
        await page.waitForTimeout(1500);
        const s5 = await C.snapshotState(page);
        R.uiDeleteConfirm = { dlg: s5.dlgVisible, text: s5.dlgText.slice(0, 250) };
        await page.screenshot({ path: SH('tasks-loop-delconfirm.png'), fullPage: true });
        if (s5.dlgVisible) {
          const ok = page.locator('[role="dialog"] button:has-text("删除"), [role="dialog"] button:has-text("确定"), [class*="modal" i] button:has-text("删除"), [class*="modal" i] button:has-text("确定")').first();
          if (await ok.count()) { await ok.click({ timeout: 2000 }).catch(() => {}); await page.waitForTimeout(2200); }
        }
        const s6 = await C.snapshotState(page);
        R.uiDelete = { gone: !/【测试】e2e/.test(s6.bodyText), newApi: apiResp.slice(mark3).map(a => a.m + ' ' + a.u + ' ' + a.status) };
        await page.screenshot({ path: SH('tasks-loop-afterdel.png'), fullPage: true });
        console.log('[delete ui]', JSON.stringify(R.uiDelete));
      } else { R.uiDelete = { note: 'no delete-looking button', items: probe.items }; }
    }
  }
  // cleanup
  const chk = await page.request.get(C.BASE + '/api/tasks');
  const chkBody = await chk.text();
  if (chkBody.includes('【测试】e2e')) {
    const del = await page.request.delete(C.BASE + '/api/tasks/' + tid);
    R.cleanup = { status: del.status() };
    console.log('[cleanup]', del.status());
  } else { R.cleanup = { note: 'already gone' }; }

  R.consoleErrors = rec.console.filter(c => c.type === 'error');
  C.saveResult('tasks-special3', R);
  await ctx.close(); await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
