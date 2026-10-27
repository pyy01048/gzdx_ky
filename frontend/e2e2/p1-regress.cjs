// p1: regression of round-2 issues (deployed 2026-10-19)
const { BASE, SHOTS, STATE, makePage, snapshotState, settle, gotoPage, closeOverlays, modalProbe, saveResult, sleep } = require('./common3.cjs');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const out = { auth: {}, t001: {}, t002: {}, t003: {} };

  // ---------- auth sanity ----------
  {
    const { ctx, page, rec } = await makePage(browser);
    await gotoPage(page, '/#/tasks', 4000);
    const me = await page.evaluate(async () => {
      const r = await fetch('/api/auth/me', { credentials: 'include' });
      let j = null; try { j = await r.json(); } catch {}
      return { status: r.status, body: j };
    });
    out.auth = { url: page.url(), me, consoleErrs: rec.console.length, bad: rec.badResponses };
    await page.screenshot({ path: SHOTS + '/regress-tasks-initial.png' });
    await ctx.close();
  }

  const browser2 = await chromium.launch();
  const { ctx, page, rec } = await makePage(browser2);

  // ---------- T1: E2E2-001 新建任务弹窗 + 创建【测试】e2e3 + 删除 ----------
  try {
    await gotoPage(page, '/#/tasks', 4000);
    // click 新建任务
    const btn = page.locator('button:has-text("新建任务")').first();
    const t = {};
    t.btnCount = await btn.count();
    await btn.click({ timeout: 5000 });
    await settle(page, 1200);
    const m1 = await modalProbe(page);
    t.modalAfterClick = m1;
    // fields check
    t.fields = await page.evaluate(() => {
      const dlg = document.querySelector('.modal-mask .modal');
      if (!dlg) return null;
      const labels = Array.from(dlg.querySelectorAll('label')).map(l => (l.textContent || '').trim().slice(0, 12));
      const inputs = Array.from(dlg.querySelectorAll('input, select')).map(i => ({ tag: i.tagName.toLowerCase(), type: i.type || '', aria: i.getAttribute('aria-label') || '' }));
      const btns = Array.from(dlg.querySelectorAll('button')).map(b => (b.textContent || '').trim());
      return { labels, inputs, btns, title: (dlg.querySelector('.modal-head b') || {}).textContent || '' };
    });
    await page.screenshot({ path: SHOTS + '/regress-001-modal-open.png' });
    // fill and save
    if (m1.open && t.fields) {
      const nameInput = page.locator('.modal-mask .modal input.input').first();
      await nameInput.fill('【测试】e2e3');
      // keep default subject/date
      const saveResp = page.waitForResponse(r => r.url().includes('/api/tasks') && r.request().method() === 'POST', { timeout: 15000 }).catch(() => null);
      await page.locator('.modal-mask .modal button:has-text("保存")').first().click();
      const resp = await saveResp;
      await settle(page, 2000);
      t.save = resp ? { status: resp.status(), url: resp.url() } : 'NO_POST_OBSERVED';
      const st = await snapshotState(page);
      t.afterSave = { hash: st.hash, toasts: st.toasts, dlgVisible: st.dlgVisible };
      await page.screenshot({ path: SHOTS + '/regress-001-after-save.png' });
      // verify appears in list
      t.inList = await page.evaluate(() => {
        const txt = document.body.innerText || '';
        return { found: txt.includes('【测试】e2e3'), sample: txt.slice(0, 1200) };
      });
      // delete it via UI if a delete control exists on the task row
      const delBtn = page.locator('button[title*="删除"], button[aria-label*="删除"], button:has-text("删除")').first();
      t.delBtnCount = await delBtn.count();
      if (t.delBtnCount > 0 && t.inList.found) {
        await delBtn.click({ timeout: 4000 });
        await settle(page, 900);
        // confirm dialog if any (confirm text 确定/删除/确认)
        const confirmBtn = page.locator('.modal-mask .modal button:has-text("删除"), .modal-mask .modal button:has-text("确定"), .modal-mask .modal button:has-text("确认")').first();
        if (await confirmBtn.count()) {
          const delResp = page.waitForResponse(r => r.url().includes('/api/tasks/') && r.request().method() === 'DELETE', { timeout: 10000 }).catch(() => null);
          await confirmBtn.click({ timeout: 4000 });
          const dr = await delResp;
          t.delete = dr ? { status: dr.status() } : 'NO_DELETE_REQ';
        } else {
          t.delete = 'NO_CONFIRM_DIALOG';
        }
        await settle(page, 1500);
        t.afterDelete = await page.evaluate(() => ({ stillThere: (document.body.innerText || '').includes('【测试】e2e3') }));
        await page.screenshot({ path: SHOTS + '/regress-001-after-delete.png' });
      }
    }
    out.t001 = t;
  } catch (e) { out.t001 = { fatal: String(e).slice(0, 300) }; }

  // ---------- T2: E2E2-002 AI 生成 (max 2 calls) ----------
  try {
    await gotoPage(page, '/#/tasks', 3500);
    await closeOverlays(page);
    await page.locator('button:has-text("AI 生成")').first().click({ timeout: 5000 });
    await settle(page, 900);
    const m = await modalProbe(page);
    const calls = [];
    for (let i = 0; i < 2; i++) {
      const genBtn = page.locator('.modal-mask .modal button:has-text("生成复习计划")').first();
      if (!(await genBtn.count())) break;
      const respP = page.waitForResponse(r => r.url().includes('ai-generate') || (r.url().includes('/api/tasks') && r.request().method() === 'POST'), { timeout: 90000 }).catch(() => null);
      await genBtn.click({ timeout: 5000 });
      const resp = await respP;
      if (!resp) { calls.push({ try: i + 1, note: 'no response observed in 90s' }); break; }
      const body = await resp.text().catch(() => '');
      calls.push({
        try: i + 1, status: resp.status(), url: resp.url(),
        bodyHead: body.slice(0, 500),
        leakDeepseek: body.includes('api.deepseek.com'),
        leak401: /401/.test(body),
      });
      await settle(page, 1500);
      const uiText = await page.evaluate(() => {
        const dlg = document.querySelector('.modal-mask .modal');
        return dlg ? (dlg.textContent || '').slice(0, 400) : (document.body.innerText || '').slice(0, 200);
      });
      calls[calls.length - 1].uiText = uiText;
      await page.screenshot({ path: SHOTS + `/regress-002-ai-try${i + 1}.png` });
      // if still generating (no response yet), wait a bit more for UI settle then break loop only after 2 tries
      if (i === 0 && resp.status() !== 502) {
        // reset modal state for a clean 2nd try
        await page.keyboard.press('Escape').catch(() => {});
        await settle(page, 600);
        await page.locator('button:has-text("AI 生成")').first().click({ timeout: 5000 }).catch(() => {});
        await settle(page, 900);
      } else break;
    }
    out.t002 = { modalOpen: m.open, modalText: m.text, calls };
  } catch (e) { out.t002 = { fatal: String(e).slice(0, 300) }; }

  // ---------- T3: modal UX on 3 modals (新建任务 / AI 生成 / 新建卡片) ----------
  const modalCases = [
    { name: 'tasks-newtask', route: '/#/tasks', opener: 'button:has-text("新建任务")' },
    { name: 'tasks-ai', route: '/#/tasks', opener: 'button:has-text("AI 生成")' },
    { name: 'cards-newcard', route: '/#/cards', opener: 'button:has-text("新建卡片")' },
  ];
  out.t003 = [];
  for (const mc of modalCases) {
    const r3 = { name: mc.name };
    try {
      await gotoPage(page, mc.route, 3500);
      await closeOverlays(page);
      const openModal = async () => {
        await page.locator(mc.opener).first().click({ timeout: 5000 });
        await settle(page, 900);
      };
      // open + probe (scroll lock)
      await openModal();
      r3.probeOpen = await modalProbe(page);
      await page.screenshot({ path: SHOTS + `/ux-${mc.name}-open.png` });

      // close via ×
      const xBtn = page.locator('.modal-mask .modal .modal-close').first();
      r3.xBtnExists = await xBtn.count();
      if (r3.xBtnExists) { await xBtn.click({ timeout: 3000 }); await settle(page, 700); }
      r3.closedByX = !(await modalProbe(page)).open;

      // reopen, close via ESC
      await openModal();
      await page.keyboard.press('Escape');
      await settle(page, 700);
      r3.closedByEsc = !(await modalProbe(page)).open;

      // reopen, close via overlay click (click mask far corner)
      await openModal();
      const mr = (await modalProbe(page)).maskRect;
      if (mr) {
        await page.mouse.click(8, Math.min(8, mr.h - 8)); // top-left corner = mask area
        await settle(page, 700);
      }
      r3.closedByOverlay = !(await modalProbe(page)).open;
      r3.bodyOverflowRestored = await page.evaluate(() => getComputedStyle(document.body).overflow);

      // narrow screen 375: open and check fit
      await page.setViewportSize({ width: 375, height: 667 });
      await settle(page, 600);
      await openModal();
      const narrow = await modalProbe(page);
      r3.narrow = {
        open: narrow.open, rect: narrow.rect, innerW: narrow.innerW, docScrollW: narrow.docScrollW,
        overW: narrow.rect ? (narrow.rect.x < -1 || narrow.rect.x + narrow.rect.w > narrow.innerW + 1) : null,
        overflowX: narrow.docScrollW > narrow.innerW + 1,
      };
      await page.screenshot({ path: SHOTS + `/ux-${mc.name}-375.png` });
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.keyboard.press('Escape').catch(() => {});
      await settle(page, 400);
    } catch (e) { r3.fatal = String(e).slice(0, 250); }
    out.t003.push(r3);
  }

  saveResult('p1-regress', out);
  await ctx.close();
  await browser2.close();
  await browser.close();
  console.log('P1 DONE');
})().catch(e => { console.error('P1 FATAL', e); process.exit(1); });
