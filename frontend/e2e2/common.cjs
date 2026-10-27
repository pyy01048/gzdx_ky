// shared helpers for e2e round 2
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const BASE = 'http://60.204.223.140';
const OUT = 'D:/平台/dogfood-output/e2e2';
const SHOTS = path.join(OUT, 'screenshots');
const RESULTS = path.join(OUT, 'results');
const STATE = path.join(OUT, 'auth-state.json');
fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(RESULTS, { recursive: true });

// destructive / data-mutating action texts we must NOT auto-click site-wide
const DENY = /删除|退出登录|登出|注销|清空|重置|保存|提交|确认|确定|修改密码|改密|停用|禁用|上传|导入|导出|发送|购买|支付|绑定|解绑|同步|恢复|还原|注销账号|立即|生成|开始|提交答案|退出/;
const NAV_DENY = /退出登录|登出|注销/;

function nowIso() { return new Date().toISOString(); }

async function makePage(browser, opts = {}) {
  const ctx = await browser.newContext({
    storageState: STATE,
    viewport: opts.viewport || { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  const rec = { console: [], pageErrors: [], badResponses: [], requestFailed: [], network: 0 };

  page.on('console', m => {
    if (m.type() === 'error' || m.type() === 'warning') {
      rec.console.push({ type: m.type(), text: (m.text() || '').slice(0, 500), ts: nowIso() });
    }
  });
  page.on('pageerror', e => rec.pageErrors.push({ text: String(e && e.stack || e).slice(0, 800), ts: nowIso() }));
  page.on('response', r => {
    if (r.status() >= 400) {
      rec.badResponses.push({ url: r.url(), status: r.status(), method: r.request().method(), ts: nowIso() });
    }
  });
  page.on('requestfailed', r => {
    rec.requestFailed.push({ url: r.url(), failure: (r.failure() && r.failure().errorText) || '', method: r.request().method(), ts: nowIso() });
  });
  page.on('request', r => { if (r.url().includes('/api/')) rec.network++; });
  page.on('dialog', d => d.dismiss().catch(() => {}));
  return { ctx, page, rec };
}

async function snapshotState(page) {
  return await page.evaluate(() => {
    const dlg = document.querySelector('[role="dialog"], .modal, [class*="modal" i], [class*="dialog" i], [class*="Drawer"], [class*="drawer"]');
    const dlgVisible = dlg ? !!(dlg.offsetWidth || dlg.offsetHeight) : false;
    const toasts = Array.from(document.querySelectorAll('[class*="toast" i], [class*="message" i], [class*="notification" i], [class*="snackbar" i]'))
      .filter(e => e.offsetWidth || e.offsetHeight).map(e => e.textContent.trim().slice(0, 120));
    return {
      url: location.hash || '#/',
      bodyLen: (document.body.innerText || '').length,
      bodyText: (document.body.innerText || '').slice(0, 2500),
      dlgVisible, dlgText: dlgVisible ? dlg.textContent.trim().slice(0, 400) : '',
      toasts,
    };
  }).catch(() => ({ url: 'EVAL_FAIL', bodyLen: -1, bodyText: '', dlgVisible: false, dlgText: '', toasts: [] }));
}

async function clickInventory(page, deny = DENY) {
  // collect visible, enabled clickables
  return await page.evaluate(() => {
    const sel = 'button, [role="button"], a[href^="#/"], [onclick], [class*="cursor-pointer" i], [class*="tab" i][role="tab"], summary';
    const els = Array.from(document.querySelectorAll(sel));
    return els.map((e, i) => {
      const r = e.getBoundingClientRect();
      return {
        i,
        tag: e.tagName.toLowerCase(),
        text: (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || e.value || '').trim().slice(0, 60),
        cls: (e.className && e.className.toString ? e.className.toString() : '').slice(0, 80),
        href: e.getAttribute && e.getAttribute('href'),
        x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
        w: Math.round(r.width), h: Math.round(r.height),
        disabled: e.disabled || e.getAttribute('aria-disabled') === 'true' || e.getAttribute('disabled') !== null,
      };
    }).filter(e => e.w > 0 && e.h > 0 && e.x >= 0 && e.y >= 0 && e.y < innerHeight + 50 && !e.disabled);
  }).then(list => list.filter(e => !(deny.test(e.text))));
}

async function settle(page, ms = 1300) { await page.waitForTimeout(ms); }

async function gotoPage(page, hash, wait = 3200) {
  await page.goto(BASE + hash, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(wait);
}

async function closeOverlays(page) {
  // try Escape then common close buttons, up to 2 rounds
  for (let k = 0; k < 2; k++) {
    const st = await snapshotState(page);
    if (!st.dlgVisible) break;
    await page.keyboard.press('Escape').catch(() => {});
    await settle(page, 500);
    const st2 = await snapshotState(page);
    if (!st2.dlgVisible) continue;
    const btn = page.locator('[role="dialog"] button:has-text("关闭"), [role="dialog"] button:has-text("取消"), [role="dialog"] button:has-text("×"), [class*="modal" i] button:has-text("关闭"), [class*="modal" i] button:has-text("取消"), [class*="modal" i] [class*="close" i]').first();
    if (await btn.count()) { await btn.click({ timeout: 2000 }).catch(() => {}); await settle(page, 500); }
  }
}

function saveResult(name, data) {
  const p = path.join(RESULTS, name + '.json');
  fs.writeFileSync(p, JSON.stringify(data, null, 2));
  console.log('RESULT SAVED', p);
}

module.exports = { BASE, OUT, SHOTS, RESULTS, STATE, DENY, NAV_DENY, makePage, snapshotState, clickInventory, settle, gotoPage, closeOverlays, saveResult, nowIso };
