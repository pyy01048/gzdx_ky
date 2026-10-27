// tasks page deep test (priority 1)
const path = require('path');
const { chromium } = require('playwright');
const C = require('./common.cjs');

const SH = p => path.join(C.SHOTS, p);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const { ctx, page, rec } = await C.makePage(browser);
  const apiCalls = [];
  page.on('request', r => { if (r.url().includes('/api/')) apiCalls.push({ m: r.method(), u: r.url().replace(C.BASE, '') }); });
  const respBodies = [];
  page.on('response', async r => {
    if (r.url().includes('/api/') && r.request().method() !== 'GET') {
      let b = ''; try { b = (await r.text()).slice(0, 300); } catch (e) {}
      respBodies.push({ m: r.request().method(), u: r.url().replace(C.BASE, ''), status: r.status(), body: b });
    }
  });
  const R = { steps: [], issue: {} };

  // ---------- 1. load ----------
  await page.goto(C.BASE + '/#/tasks', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(4500);
  await page.screenshot({ path: SH('tasks-load.png'), fullPage: true });
  const st0 = await C.snapshotState(page);
  R.steps.push({ step: 'load', url: page.url(), body: st0.bodyText.slice(0, 600), consoleErrors: rec.console.filter(c => c.type === 'error'), pageErrors: rec.pageErrors, badResponses: rec.badResponses });
  console.log('[load] dlg=', st0.dlgVisible, 'len=', st0.bodyLen, 'consoleErr=', rec.console.filter(c => c.type === 'error').length, 'pageErr=', rec.pageErrors.length, 'bad4xx=', rec.badResponses.length);

  // ---------- 2. 新建任务 button forensics ----------
  const btnInfo = await page.evaluate(() => {
    const cands = Array.from(document.querySelectorAll('button, [role="button"], a')).filter(e => /新建任务/.test(e.innerText || ''));
    return cands.map(e => {
      const r = e.getBoundingClientRect();
      const cs = getComputedStyle(e);
      const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return {
        text: e.innerText.trim().slice(0, 40), tag: e.tagName,
        rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
        pointerEvents: cs.pointerEvents, disabled: e.disabled || false,
        hitIsSelf: hit === e || e.contains(hit),
        hitDesc: hit ? (hit.tagName + '.' + (hit.className || '').toString().slice(0, 60)) : 'null',
        outer: e.outerHTML.slice(0, 220),
      };
    });
  });
  R.issue.newTaskButton = btnInfo;
  console.log('[newtask-btn]', JSON.stringify(btnInfo));

  const netBefore = rec.network;
  for (let attempt = 1; attempt <= 2; attempt++) {
    const before = await C.snapshotState(page);
    const errBefore = rec.console.filter(c => c.type === 'error').length + rec.pageErrors.length;
    const btn = page.getByText('新建任务', { exact: false }).first();
    let clicked = 'not-found';
    if (await btn.count()) {
      try { await btn.click({ timeout: 3000 }); clicked = 'locator-click-ok'; }
      catch (e) {
        try {
          const bi = btnInfo[0];
          await page.mouse.click(bi.rect.x + bi.rect.w / 2, bi.rect.y + bi.rect.h / 2);
          clicked = 'mouse-click-ok';
        } catch (e2) { clicked = 'click-failed: ' + e2.message.slice(0, 80); }
      }
    }
    await page.waitForTimeout(2500);
    const after = await C.snapshotState(page);
    const errAfter = rec.console.filter(c => c.type === 'error').length + rec.pageErrors.length;
    const res = {
      attempt, clicked,
      dlgOpened: after.dlgVisible && !before.dlgVisible, dlgText: after.dlgText.slice(0, 200),
      navigated: after.url !== before.url,
      bodyLenBefore: before.bodyLen, bodyLenAfter: after.bodyLen,
      newConsoleErrs: errAfter - errBefore,
      netDelta: rec.network - netBefore,
      toasts: after.toasts,
    };
    R.issue['newTaskClick' + attempt] = res;
    await page.screenshot({ path: SH('tasks-newtask-click' + attempt + '.png'), fullPage: true });
    console.log('[newtask click ' + attempt + ']', JSON.stringify(res));
  }

  // ---------- 3. AI 生成 ----------
  const aiBtn = page.getByText('AI 生成', { exact: false }).first();
  R.issue.aiButtonFound = await aiBtn.count();
  if (await aiBtn.count()) {
    await aiBtn.click({ timeout: 3000 }).catch(e => R.issue.aiClickErr = e.message.slice(0, 100));
    await page.waitForTimeout(2000);
    await page.screenshot({ path: SH('tasks-ai-dialog.png'), fullPage: true });
    const dlg1 = await C.snapshotState(page);
    R.issue.aiDialog = { open: dlg1.dlgVisible, text: dlg1.dlgText.slice(0, 400) };
    console.log('[ai dialog]', JSON.stringify(R.issue.aiDialog));
    // try generate up to 2 times
    for (let i = 1; i <= 2; i++) {
      const gen = page.locator('[role="dialog"] button:has-text("生成"), [class*="modal" i] button:has-text("生成")').first();
      if (!(await gen.count())) { R.issue['aiGen' + i] = { note: 'no generate button' }; break; }
      const netMark = respBodies.length;
      await gen.click({ timeout: 3000 }).catch(() => {});
      await page.waitForTimeout(35000);
      const dlg = await C.snapshotState(page);
      R.issue['aiGen' + i] = {
        newApiResponses: respBodies.slice(netMark),
        dlgText: dlg.dlgText.slice(0, 500), toasts: dlg.toasts,
        pageErrorsDelta: rec.pageErrors.length,
      };
      await page.screenshot({ path: SH('tasks-ai-error' + i + '.png'), fullPage: true });
      console.log('[ai gen ' + i + ']', JSON.stringify(R.issue['aiGen' + i]).slice(0, 800));
      if (i === 1 && dlg.dlgText && /失败|错误|重试/.test(dlg.dlgText)) { /* still try 2nd per instructions */ }
    }
    await page.keyboard.press('Escape'); await page.waitForTimeout(600);
    await C.closeOverlays(page);
  }

  // ---------- 4. date switching ----------
  const dateBefore = (await C.snapshotState(page)).bodyText.match(/(\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2})/);
  const chev = page.locator('button:has(svg)').filter({ hasNot: page.locator('[aria-label]') });
  // find chevron by class names containing chevron via evaluate
  const chevPos = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('button')).map((e, i) => {
      const r = e.getBoundingClientRect();
      return { i, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), w: Math.round(r.width), h: Math.round(r.height), cls: (e.className || '').toString().slice(0, 60), label: e.getAttribute('aria-label') || e.title || '' };
    }).filter(e => e.w > 0 && e.h > 0 && /chevron|left|right|prev|next/i.test(e.cls + ' ' + e.label) && !/chevron-up|down/i.test(e.cls));
  });
  R.issue.chevronButtons = chevPos;
  const dateSeq = [];
  for (const p of chevPos.slice(0, 2)) {
    await page.mouse.click(p.x, p.y); await page.waitForTimeout(1500);
    const t = await C.snapshotState(page);
    dateSeq.push({ clicked: p.cls || p.label, date: (t.bodyText.match(/(\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2})/) || [])[1], toasts: t.toasts });
    await page.screenshot({ path: SH('tasks-date-' + (p.cls || p.label).replace(/\W+/g, '') + '.png'), fullPage: true });
  }
  R.issue.dateSwitching = { before: dateBefore && dateBefore[1], seq: dateSeq };
  console.log('[date]', JSON.stringify(R.issue.dateSwitching));

  // ---------- 5. create test task via API ----------
  const today = new Date().toISOString().slice(0, 10);
  let created = null;
  for (const subj of ['其他', '数学', '']) {
    const payload = { title: '【测试】e2e', subject: subj, due_date: today, priority: 0 };
    const resp = await page.request.post(C.BASE + '/api/tasks', { data: payload, headers: { 'Content-Type': 'application/json' } });
    const txt = await resp.text().catch(() => '');
    R.steps.push({ step: 'api-create', payload, status: resp.status(), body: txt.slice(0, 300) });
    console.log('[api-create]', resp.status(), txt.slice(0, 200));
    if (resp.status() < 300) { try { created = JSON.parse(txt); } catch (e) { created = { raw: txt.slice(0, 100) }; } break; }
  }
  R.issue.createdTask = created;
  if (created && created.id) {
    await C.gotoPage(page, '/#/tasks', 3500);
    const st = await C.snapshotState(page);
    R.issue.testTaskVisible = /【测试】e2e/.test(st.bodyText);
    await page.screenshot({ path: SH('tasks-testtask.png'), fullPage: true });
    console.log('[testtask visible]', R.issue.testTaskVisible);

    // checkbox toggle (complete)
    const box = page.locator('text=【测试】e2e').first();
    const row = page.locator('div,li').filter({ hasText: '【测试】e2e' }).last();
    // click the checkbox: find TaskItem checkbox near the title
    const cbClicked = await page.evaluate(() => {
      const t = Array.from(document.querySelectorAll('*')).find(e => e.children.length === 0 && /【测试】e2e/.test(e.textContent || ''));
      if (!t) return 'title-not-found';
      let row = t; for (let k = 0; k < 6 && row.parentElement; k++) { row = row.parentElement; if (row.querySelector('input[type="checkbox"],button')) break; }
      const cb = row.querySelector('input[type="checkbox"]') || row.querySelector('button');
      if (!cb) return 'no-checkbox-in-row';
      const r = cb.getBoundingClientRect();
      return { tag: cb.tagName, cls: (cb.className || '').toString().slice(0, 60), x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    });
    R.issue.checkboxProbe = cbClicked;
    if (cbClicked && cbClicked.x) {
      const netMark = respBodies.length;
      await page.mouse.click(cbClicked.x, cbClicked.y);
      await page.waitForTimeout(2000);
      const stt = await C.snapshotState(page);
      R.issue.completeToggle = { api: respBodies.slice(netMark), bodyHasDone: /已完成|done/i.test(stt.bodyText), toasts: stt.toasts };
      await page.screenshot({ path: SH('tasks-testtask-done.png'), fullPage: true });
      console.log('[toggle done]', JSON.stringify(R.issue.completeToggle).slice(0, 400));
    }

    // edit modal (open, screenshot, cancel)
    const rowText = page.locator('li,div[class*="task" i]').filter({ hasText: '【测试】e2e' }).first();
    const editProbe = await page.evaluate(() => {
      const t = Array.from(document.querySelectorAll('*')).find(e => e.children.length === 0 && /【测试】e2e/.test(e.textContent || ''));
      if (!t) return null;
      let row = t; for (let k = 0; k < 8 && row.parentElement; k++) { row = row.parentElement; if (row.querySelectorAll('button').length >= 2) break; }
      return Array.from(row.querySelectorAll('button')).map((b, i) => { const r = b.getBoundingClientRect(); return { i, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), txt: (b.innerText || '').trim().slice(0, 20), aria: b.getAttribute('aria-label') || '', cls: (b.className || '').toString().slice(0, 50) }; });
    });
    R.issue.rowButtons = editProbe;
    if (editProbe && editProbe.length) {
      const eBtn = editProbe.find(b => /编辑|edit|pencil|pen/i.test(b.txt + b.aria + b.cls)) || editProbe[editProbe.length - 1];
      await page.mouse.click(eBtn.x, eBtn.y); await page.waitForTimeout(1500);
      const d = await C.snapshotState(page);
      R.issue.editModal = { open: d.dlgVisible, text: d.dlgText.slice(0, 300) };
      await page.screenshot({ path: SH('tasks-testtask-edit.png'), fullPage: true });
      await page.keyboard.press('Escape'); await page.waitForTimeout(500); await C.closeOverlays(page);
    }

    // delete test task (UI first; fallback API)
    let deletedVia = null;
    if (editProbe && editProbe.length) {
      const dBtn = editProbe.find(b => /删除|delete|trash|remove/i.test(b.txt + b.aria + b.cls));
      if (dBtn) {
        const netMark = respBodies.length;
        await page.mouse.click(dBtn.x, dBtn.y); await page.waitForTimeout(1200);
        // confirm dialog?
        const conf = await C.snapshotState(page);
        R.issue.deleteConfirm = { dlg: conf.dlgVisible, text: conf.dlgText.slice(0, 200) };
        await page.screenshot({ path: SH('tasks-testtask-delete-confirm.png'), fullPage: true });
        if (conf.dlgVisible) {
          const ok = page.locator('[role="dialog"] button:has-text("删除"), [role="dialog"] button:has-text("确定"), [role="dialog"] button:has-text("确认"), [class*="modal" i] button:has-text("删除"), [class*="modal" i] button:has-text("确定")').first();
          if (await ok.count()) { await ok.click({ timeout: 2000 }).catch(() => {}); await page.waitForTimeout(2000); }
        }
        const after = await C.snapshotState(page);
        const gone = !/【测试】e2e/.test(after.bodyText);
        R.issue.deleteUi = { gone, api: respBodies.slice(netMark) };
        if (gone) deletedVia = 'ui';
        console.log('[delete ui]', JSON.stringify(R.issue.deleteUi).slice(0, 300));
      }
    }
    if (!deletedVia && created.id) {
      const dr = await page.request.delete(C.BASE + '/api/tasks/' + created.id);
      R.issue.deleteApiFallback = { status: dr.status() };
      deletedVia = 'api';
      console.log('[delete api]', dr.status());
      await C.gotoPage(page, '/#/tasks', 2500);
      const st2 = await C.snapshotState(page);
      R.issue.testTaskGoneAfterApiDelete = !/【测试】e2e/.test(st2.bodyText);
    }
  }

  // ---------- 6. segmented tabs (day/week views) ----------
  const segs = await page.evaluate(() => Array.from(document.querySelectorAll('[class*="segment" i] button, [class*="Segmented" i] button, [role="tablist"] [role="tab"]')).map((e, i) => { const r = e.getBoundingClientRect(); return { i, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), txt: (e.innerText || '').trim().slice(0, 10) }; }).filter(e => e.w !== 0 || true));
  R.issue.segmented = segs;
  const segResults = [];
  for (const s of segs.slice(0, 6)) {
    const before = await C.snapshotState(page);
    await page.mouse.click(s.x, s.y); await page.waitForTimeout(1500);
    const after = await C.snapshotState(page);
    segResults.push({ tab: s.txt, changed: after.bodyLen !== before.bodyLen || after.url !== before.url, toasts: after.toasts });
    await page.screenshot({ path: SH('tasks-tab-' + (s.txt || s.i) + '.png'), fullPage: true });
  }
  R.issue.segmentResults = segResults;
  console.log('[segments]', JSON.stringify(segResults));

  R.finalConsoleErrors = rec.console.filter(c => c.type === 'error');
  R.finalPageErrors = rec.pageErrors;
  R.finalBadResponses = rec.badResponses;
  R.finalRequestFailed = rec.requestFailed;
  R.apiCallsSample = apiCalls.slice(0, 40);
  R.respBodies = respBodies;
  C.saveResult('tasks-special', R);
  await ctx.close(); await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
