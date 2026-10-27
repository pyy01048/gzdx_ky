// shared helpers for e2e round 3 (built on round-2 common.cjs conventions)
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const BASE = 'http://60.204.223.140';
const OUT = 'D:/平台/dogfood-output/e2e3';
const SHOTS = path.join(OUT, 'screenshots');
const RESULTS = path.join(OUT, 'results');
const STATE = 'D:/平台/dogfood-output/auth-state.json';
fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(RESULTS, { recursive: true });

// destructive/data-mutating action texts we must NOT auto-click during site walk
const DENY = /删除|退出登录|登出|注销|清空|重置|保存|提交|确认|确定|修改密码|改密|停用|禁用|上传|导入|导出|发送|购买|支付|绑定|解绑|同步|恢复|还原|立即|生成|开始|提交答案|退出|移除|置顶|标为|标记|评分|认识|不认识|简单|困难|模糊|忘记|收藏|取消收藏|关闭提醒|新增|新建|创建|添加|粘贴|下载|续费|邀请/;
const ADMIN_DENY = /.*/; // admin: inventory only, click nothing

function nowIso() { return new Date().toISOString(); }

async function makePage(browser, opts = {}) {
  const ctx = await browser.newContext({
    storageState: STATE,
    viewport: opts.viewport || { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  const rec = { console: [], pageErrors: [], badResponses: [], requestFailed: [], apiCount: 0 };

  page.on('console', m => {
    if (m.type() === 'error') {
      rec.console.push({ type: m.type(), text: (m.text() || '').slice(0, 400), ts: nowIso() });
    }
  });
  page.on('pageerror', e => rec.pageErrors.push({ text: String(e && e.stack || e).slice(0, 600), ts: nowIso() }));
  page.on('response', r => {
    if (r.status() >= 400) {
      rec.badResponses.push({ url: r.url(), status: r.status(), method: r.request().method(), ts: nowIso() });
    }
  });
  page.on('requestfailed', r => {
    let method = 'GET'; try { if (typeof r.request === 'function') method = r.request().method(); } catch {}
    rec.requestFailed.push({ url: r.url(), failure: (r.failure() && r.failure().errorText) || '', method, ts: nowIso() });
  });
  page.on('request', r => { if (r.url().includes('/api/')) rec.apiCount++; });
  page.on('dialog', d => d.dismiss().catch(() => {}));
  return { ctx, page, rec };
}

async function snapshotState(page) {
  return await page.evaluate(() => {
    const dlg = document.querySelector('.modal-mask, [role="dialog"][aria-modal="true"]');
    const dlgVisible = dlg ? !!(dlg.offsetWidth || dlg.offsetHeight) : false;
    const toasts = Array.from(document.querySelectorAll('[class*="toast" i], [class*="message" i], [class*="notification" i]'))
      .filter(e => e.offsetWidth || e.offsetHeight).map(e => e.textContent.trim().slice(0, 100));
    const selTabs = Array.from(document.querySelectorAll('[aria-selected="true"]')).map(e => (e.textContent || '').trim().slice(0, 20)).filter(Boolean).slice(0, 8);
    return {
      hash: location.hash || '#/',
      bodyLen: (document.body.innerText || '').length,
      dlgVisible,
      dlgText: dlgVisible ? (dlg.textContent || '').trim().slice(0, 200) : '',
      toasts,
      selTabs,
    };
  }).catch(() => ({ hash: 'EVAL_FAIL', bodyLen: -1, dlgVisible: false, dlgText: '', toasts: [], selTabs: [] }));
}

// click inventory: visible, enabled clickables (buttons/tabs incl.), custom deny
async function clickInventory(page, deny = DENY) {
  return await page.evaluate(() => {
    const sel = 'button, [role="button"], [role="tab"], [role="option"], summary, .seg button';
    const els = Array.from(document.querySelectorAll(sel));
    return els.map((e, i) => {
      const r = e.getBoundingClientRect();
      return {
        i,
        tag: e.tagName.toLowerCase(),
        text: (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim().replace(/\s+/g, ' ').slice(0, 50),
        role: e.getAttribute('role') || '',
        cls: (typeof e.className === 'string' ? e.className : '').slice(0, 60),
        href: e.getAttribute && e.getAttribute('href'),
        x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
        w: Math.round(r.width), h: Math.round(r.height),
        disabled: e.disabled || e.getAttribute('aria-disabled') === 'true',
      };
    }).filter(e => e.w > 0 && e.h > 0 && e.x >= 0 && e.y >= 0 && e.y < innerHeight + 60 && !e.disabled);
  }).then(list => list.filter(e => !(deny.test(e.text))));
}

async function settle(a, b) { const ms = (typeof a === 'number') ? a : b; await new Promise(r => setTimeout(r, ms || 1200)); }

async function gotoPage(page, hash, wait = 3000) {
  await page.goto(BASE + hash, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(wait);
}

async function closeOverlays(page) {
  for (let k = 0; k < 2; k++) {
    const st = await snapshotState(page);
    if (!st.dlgVisible) break;
    await page.keyboard.press('Escape').catch(() => {});
    await settle(page, 450);
    const st2 = await snapshotState(page);
    if (!st2.dlgVisible) continue;
    const btn = page.locator('.modal-mask .modal-close, [role="dialog"] button:has-text("取消"), [role="dialog"] button:has-text("关闭")').first();
    if (await btn.count()) { await btn.click({ timeout: 1500 }).catch(() => {}); await settle(page, 450); }
  }
}

// responsive audit: horizontal overflow + key element bounds
async function overflowAudit(page) {
  return await page.evaluate(() => {
    const vw = window.innerWidth;
    const se = document.scrollingElement;
    const sw = se ? se.scrollWidth : -1;
    const offenders = [];
    const all = document.querySelectorAll('body *');
    for (const el of all) {
      const r = el.getBoundingClientRect();
      if (r.width > 4 && r.height > 4 && r.right > vw + 1 && r.left < vw) {
        const cs = getComputedStyle(el);
        if (cs.position === 'fixed') continue;
        const tag = el.tagName.toLowerCase();
        const cls = (typeof el.className === 'string' && el.className) ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
        const txt = (el.innerText || '').trim().slice(0, 24).replace(/\s+/g, ' ');
        offenders.push({ sel: tag + cls, txt, right: Math.round(r.right), w: Math.round(r.width) });
        if (offenders.length >= 8) break;
      }
    }
    // key containers
    const keys = [];
    const keySel = ['.page-actions', '.page-head', 'table', '[class*="chart"]', '.echarts', 'canvas', '[class*="grid"]'];
    const seen = new Set();
    for (const s of keySel) {
      for (const el of document.querySelectorAll(s)) {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const k = s;
        if (seen.has(k + Math.round(r.top))) continue;
        seen.add(k + Math.round(r.top));
        keys.push({ sel: s, top: Math.round(r.top), right: Math.round(r.right), over: r.right > vw + 1 });
        if (keys.length >= 14) break;
      }
      if (keys.length >= 14) break;
    }
    const bodyOv = getComputedStyle(document.body).overflowX;
    const htmlOv = getComputedStyle(document.documentElement).overflowX;
    return { vw, vh: window.innerHeight, sw, overflow: sw > vw + 1, offenders, keys, bodyOv, htmlOv };
  }).catch(e => ({ error: String(e).slice(0, 120) }));
}

// modal probe: rect, body scroll lock, viewport fit
async function modalProbe(page) {
  return await page.evaluate(() => {
    const mask = document.querySelector('.modal-mask');
    const dlg = document.querySelector('.modal-mask .modal, [role="dialog"][aria-modal="true"]');
    const r = dlg ? dlg.getBoundingClientRect() : null;
    const mr = mask ? mask.getBoundingClientRect() : null;
    return {
      open: !!(mask && (mask.offsetWidth || mask.offsetHeight)),
      rect: r ? { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } : null,
      maskRect: mr ? { w: Math.round(mr.width), h: Math.round(mr.height) } : null,
      bodyOverflow: getComputedStyle(document.body).overflow,
      docScrollW: document.scrollingElement ? document.scrollingElement.scrollWidth : -1,
      innerW: window.innerWidth,
      text: dlg ? (dlg.textContent || '').trim().slice(0, 160) : '',
    };
  }).catch(() => ({ open: false, error: 'probe_fail' }));
}

function saveResult(name, data) {
  const p = path.join(RESULTS, name + '.json');
  fs.writeFileSync(p, JSON.stringify(data, null, 2));
  console.log('RESULT SAVED', p);
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

module.exports = { BASE, OUT, SHOTS, RESULTS, STATE, DENY, ADMIN_DENY, makePage, snapshotState, clickInventory, settle, gotoPage, closeOverlays, overflowAudit, modalProbe, saveResult, nowIso, sleep };
