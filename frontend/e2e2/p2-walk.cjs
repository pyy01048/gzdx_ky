// p2: full-site walk. usage: node p2-walk.cjs a|b|c|d|e|f|g|back
const { BASE, SHOTS, makePage, snapshotState, clickInventory, settle, gotoPage, closeOverlays, saveResult, DENY } = require('./common3.cjs');
const { chromium } = require('playwright');

const GROUPS = {
  a: [['/', '仪表盘'], ['/tasks', '任务打卡'], ['/planner', '学习计划'], ['/profile', '学习画像']],
  b: [['/library', '学习文库'], ['/documents', '文档知识库'], ['/textbooks', '教材目录'], ['/pan', '网盘联动'], ['/knowledge', '知识图谱']],
  c: [['/quiz', '刷题中心'], ['/exam', '真题中心'], ['/cards', '记忆卡片'], ['/words', '单词记忆'], ['/codebank', '复试代码题库']],
  d: [['/error-review', '错题复盘'], ['/notebook', '错题本'], ['/insights', '学习统计'], ['/favorites', '我的收藏'], ['/timeline', '学习轨迹']],
  e: [['/assistant', 'AI助手'], ['/settings', '设置']],
  f: [['/kaoyan', '择校中心'], ['/kaoyan/notices', '通知中心'], ['/kaoyan/schools', '院校库'], ['/kaoyan/compare', '院校对比'], ['/kaoyan/recommend', '智能择校'], ['/kaoyan/map', '区域热力图'], ['/kaoyan/scatter', '招生散点图'], ['/kaoyan/growth', '成长体系'], ['/kaoyan/analysis', '分数线数据'], ['/kaoyan/plan', '考研规划'], ['/kaoyan/assistant', '择校AI问答']],
  g: [['/admin/overview', '数据中心'], ['/admin/users', '用户管理'], ['/admin/subjects', '科目管理'], ['/admin/quiz-bank', '题库管理'], ['/admin/quality', '数据质量'], ['/admin/schools', '院校数据管理'], ['/admin/crawl-sources', '院校采集源'], ['/admin/kb-import', '知识库导入'], ['/admin/model', '模型训练']],
};

const KNOWN = [
  /^#\/$/, /^#\/(tasks|planner|profile|library|documents|textbooks|pan|knowledge|insights|quiz|exam|cards|words|codebank|error-review|notebook|favorites|timeline|assistant|settings|login|403|force-change-password)$/,
  /^#\/knowledge\/.+/, /^#\/exam\/.+/, /^#\/kaoyan(\/(notices|schools|compare|recommend|map|scatter|growth|analysis|plan|assistant))?$/,
  /^#\/kaoyan\/schools\/.+/, /^#\/admin(\/(overview|users|subjects|quiz-bank|quality|schools|crawl-sources|kb-import|model))?$/, /^#\/\?/,
];

function knownHash(h) {
  if (!h || h === '#') return null;
  const path = h.split('?')[0];
  return KNOWN.some(re => re.test(path));
}

async function walkPage(page, rec, route, label, opts = {}) {
  const R = { route, label, h1: '', bodyLen: 0, consoleErrs: [], pageErrors: [], bad: [], failed: [], deadLinks: [], linkCount: 0, clicked: [], unresponsive: [], navOut: [], notes: [] };
  await gotoPage(page, '#' + route, opts.wait || 3200);
  await closeOverlays(page);
  const st = await snapshotState(page);
  R.bodyLen = st.bodyLen;
  R.h1 = await page.evaluate(() => {
    const h = document.querySelector('h1, .page-head h2, [class*="page-title"]');
    return h ? (h.textContent || '').trim().slice(0, 40) : '';
  }).catch(() => '');
  // links
  const links = await page.evaluate(() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href')).filter(h => h && h.startsWith('#')));
  R.linkCount = links.length;
  for (const h of new Set(links)) if (!knownHash(h)) R.deadLinks.push(h);
  // buttons
  const btns = await clickInventory(page, opts.deny || DENY);
  R.btnTotal = btns.length;
  const cap = opts.cap || 22;
  const baseNet = rec.apiCount;
  let netNow = baseNet;
  for (const b of btns.slice(0, cap)) {
    const before = await snapshotState(page);
    netNow = rec.apiCount;
    const errsBefore = rec.console.length + rec.pageErrors.length;
    let clicked = false;
    try {
      const loc = page.locator('button, [role="tab"], [role="button"], summary').filter({ hasText: b.text || '‡never‡' });
      // fallback: click by coordinates to avoid text ambiguity
      if (await loc.count() > 0) {
        const el = loc.first();
        const box = await el.boundingBox().catch(() => null);
        if (box && Math.abs(box.x + box.width / 2 - b.x) < 30 && Math.abs(box.y + box.height / 2 - b.y) < 30) {
          await el.click({ timeout: 3000 }); clicked = true;
        }
      }
      if (!clicked) { await page.mouse.click(b.x, b.y); clicked = true; }
    } catch (e) { R.clicked.push({ ...b, error: String(e).slice(0, 80) }); continue; }
    await settle(1100);
    const after = await snapshotState(page);
    const netDelta = rec.apiCount - netNow;
    const errsDelta = rec.console.length + rec.pageErrors.length - errsBefore;
    const ariaChanged = JSON.stringify(before.selTabs) !== JSON.stringify(after.selTabs);
    const responsive = after.hash !== before.hash || after.dlgVisible || after.toasts.length > 0 || Math.abs(after.bodyLen - before.bodyLen) >= 10 || ariaChanged || netDelta > 0 || errsDelta > 0;
    const entry = { text: b.text, cls: b.cls.slice(0, 40), hashChanged: after.hash !== before.hash, dlg: after.dlgVisible, toasts: after.toasts, bodyLenDelta: after.bodyLen - before.bodyLen, ariaChanged, netDelta, errsDelta };
    R.clicked.push(entry);
    if (after.hash !== before.hash && after.hash !== before.hash.replace(/$/, '')) {
      const target = after.hash;
      const sameRoute = target === '#' + route || target.startsWith('#' + route + '?') || target.startsWith('#' + route + '/');
      if (!sameRoute) {
        R.navOut.push({ via: b.text, to: target });
        await gotoPage(page, '#' + route, 2600);
        continue;
      }
    }
    if (after.dlgVisible) { await closeOverlays(page); await settle(400); }
    if (!responsive) R.unresponsive.push(entry);
  }
  R.consoleErrs = rec.console.slice(0, 12).map(c => c.text.slice(0, 160));
  R.pageErrors = rec.pageErrors.slice(0, 6).map(c => c.text.slice(0, 200));
  R.bad = rec.badResponses.slice(0, 15).map(b => `${b.method} ${b.url.replace(BASE, '')} → ${b.status}`);
  R.failed = rec.requestFailed.slice(0, 8).map(b => `${b.method} ${b.url.replace(BASE, '')} (${b.failure})`);
  await page.screenshot({ path: `${SHOTS}/walk-${route.replace(/[^a-z0-9]+/gi, '_')}.png`, fullPage: false }).catch(() => {});
  return R;
}

(async () => {
  const group = process.argv[2] || 'a';
  const browser = await chromium.launch();
  const { ctx, page, rec } = await makePage(browser);
  const results = {};

  if (group === 'a') {
    // dashboard special: enumerate cards
    await gotoPage(page, '#/', 4000);
    const dash = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll('[class*="card" i]')).filter(e => e.offsetWidth > 80 && e.offsetHeight > 40);
      const seen = new Set(); const list = [];
      for (const c of cards) {
        const key = Math.round(c.getBoundingClientRect().top) + ':' + Math.round(c.getBoundingClientRect().left);
        if (seen.has(key)) continue; seen.add(key);
        const link = c.querySelector('a[href]');
        const head = c.querySelector('h1,h2,h3,h4,b,strong,[class*="title"]');
        list.push({ cls: (typeof c.className === 'string' ? c.className : '').slice(0, 40), title: head ? head.textContent.trim().slice(0, 24) : (c.textContent || '').trim().slice(0, 24), link: link ? link.getAttribute('href') : null });
        if (list.length >= 40) break;
      }
      return { cardCount: cards.length, list: list.slice(0, 30), text: (document.body.innerText || '').slice(0, 900) };
    });
    results.dashboardCards = dash;
    await page.screenshot({ path: SHOTS + '/walk-dashboard-cards.png', fullPage: true });
  }

  if (group === 'c') {
    // quiz special: tabs + start practice
    await gotoPage(page, '#/quiz', 3800);
    const q = { tabs: [], flow: [] };
    // click entry tabs by role
    const tabs = await page.evaluate(() => Array.from(document.querySelectorAll('[role="tab"]')).map(t => ({ text: (t.textContent || '').trim(), aria: t.getAttribute('aria-selected') })));
    q.tabs = tabs;
    for (const t of tabs) {
      const loc = page.locator(`[role="tab"]:has-text("${t.text}")`).first();
      if (await loc.count()) { await loc.click({ timeout: 3000 }).catch(() => {}); await settle(1000); }
    }
    q.afterTabsBad = rec.badResponses.length;
    await page.screenshot({ path: SHOTS + '/walk-quiz-tabs.png' });
    // start practice
    const start = page.locator('button:has-text("开始练习"), .qknow-action').first();
    if (await start.count()) {
      await start.click({ timeout: 4000 }).catch(() => {});
      await settle(2500);
      q.practice = await page.evaluate(() => ({
        hash: location.hash, bodyLen: (document.body.innerText || '').length,
        hasQuestion: !!document.querySelector('[class*="question" i], [class*="stem" i]'),
        options: Array.from(document.querySelectorAll('button, [class*="option" i]')).map(b => (b.textContent || '').trim().slice(0, 18)).filter(t => /^[ABCD]/.test(t)).slice(0, 6),
        text: (document.body.innerText || '').slice(0, 500),
      }));
      await page.screenshot({ path: SHOTS + '/walk-quiz-practice.png' });
      // answer: click first option then 提交/下一题 if present
      const opt = page.locator('button:has-text("A"), [class*="option" i]').first();
      if (await opt.count()) { await opt.click({ timeout: 3000 }).catch(() => {}); await settle(800); }
      const next = page.locator('button:has-text("提交"), button:has-text("下一题")').first();
      if (await next.count()) {
        await next.click({ timeout: 3000 }).catch(() => {});
        await settle(1500);
        q.afterSubmit = (await page.evaluate(() => (document.body.innerText || '').slice(0, 300)));
        await page.screenshot({ path: SHOTS + '/walk-quiz-after-submit.png' });
      }
      results.quiz = q;
      // continue standard walk of /quiz after leaving practice
      await gotoPage(page, '#/quiz', 3000);
    } else { q.flow.push('NO_START_BUTTON'); results.quiz = q; }
  }

  if (group === 'c') {
    // words import modal probe (explicit, no actual import)
    await gotoPage(page, '#/words', 3200);
    const imp = page.locator('button:has-text("导入")').first();
    if (await imp.count()) {
      await imp.click({ timeout: 3000 }).catch(() => {});
      await settle(900);
      results.wordsImportModal = await page.evaluate(() => {
        const dlg = document.querySelector('.modal-mask .modal');
        return { open: !!dlg, text: dlg ? (dlg.textContent || '').slice(0, 200) : '', buttons: dlg ? Array.from(dlg.querySelectorAll('button')).map(b => (b.textContent || '').trim().slice(0, 20)) : [] };
      });
      await page.screenshot({ path: SHOTS + '/walk-words-import-modal.png' });
      await page.keyboard.press('Escape'); await settle(500);
    }
  }

  if (group === 'e') {
    // settings: enumerate and click all sub tabs
    await gotoPage(page, '#/settings', 3600);
    const tabTexts = await page.evaluate(() => Array.from(document.querySelectorAll('[role="tab"], .seg button, [class*="tab-btn" i], [class*="set-nav"] button, [class*="nav-item"]')).map(b => (b.textContent || '').trim().replace(/\s+/g, ' ')).filter(t => t && t.length <= 14));
    results.settingsTabs = [...new Set(tabTexts)];
    results.settingsTabClicks = [];
    for (const t of results.settingsTabs.slice(0, 18)) {
      const loc = page.locator(`button:has-text("${t}"), [role="tab"]:has-text("${t}")`).first();
      if (!(await loc.count())) continue;
      const errs = rec.badResponses.length;
      await loc.click({ timeout: 2500 }).catch(() => {});
      await settle(1100);
      const st = await snapshotState(page);
      results.settingsTabClicks.push({ tab: t, bodyLen: st.bodyLen, newBad: rec.badResponses.length - errs, toasts: st.toasts });
      await page.screenshot({ path: SHOTS + `/walk-settings-${t.replace(/[^a-z0-9]+/gi, '').slice(0, 12)}.png` }).catch(() => {});
    }
    // assistant: enumerate entries only (no AI send)
    await gotoPage(page, '#/assistant', 3400);
    results.assistant = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button, [role="tab"]')).map(b => (b.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 24)).filter(Boolean);
      return { buttons: [...new Set(btns)].slice(0, 30), text: (document.body.innerText || '').slice(0, 500) };
    });
  }

  if (group === 'back') {
    // back-state tests
    const B = {};
    // 1) quiz tab state
    await gotoPage(page, '#/quiz', 3400);
    await page.locator('[role="tab"]:has-text("年份")').first().click({ timeout: 3000 }).catch(() => {});
    await settle(900);
    B.quizTabBefore = await page.evaluate(() => Array.from(document.querySelectorAll('[role="tab"][aria-selected="true"]')).map(e => e.textContent.trim()));
    await gotoPage(page, '#/words', 2500);
    await page.goBack(); await settle(1800);
    B.quizTabAfterBack = await page.evaluate(() => Array.from(document.querySelectorAll('[role="tab"][aria-selected="true"]')).map(e => e.textContent.trim()));
    // 2) kaoyan schools -> detail -> back
    await gotoPage(page, '#/kaoyan/schools', 3400);
    B.schoolsBodyBefore = await page.evaluate(() => (document.body.innerText || '').length);
    const schoolLink = page.locator('a[href*="/kaoyan/schools/"]').first();
    if (await schoolLink.count()) {
      const href = await schoolLink.getAttribute('href');
      await schoolLink.click({ timeout: 3000 }).catch(() => {});
      await settle(2600);
      B.detailHash = location.hash; B.detailBody = await page.evaluate(() => (document.body.innerText || '').slice(0, 200));
      await page.screenshot({ path: SHOTS + '/walk-school-detail.png' });
      await page.goBack(); await settle(2000);
      B.schoolsBodyAfterBack = await page.evaluate(() => (document.body.innerText || '').length);
      B.schoolsHashAfterBack = location.hash;
    } else B.noSchoolLink = true;
    // 3) knowledge -> article -> back
    await gotoPage(page, '#/knowledge', 3400);
    const kbLink = page.locator('a[href*="/knowledge/"]').first();
    if (await kbLink.count()) {
      await kbLink.click({ timeout: 3000 }).catch(() => {});
      await settle(2600);
      B.kbDetailHash = location.hash;
      B.kbDetailBody = await page.evaluate(() => (document.body.innerText || '').slice(0, 200));
      await page.screenshot({ path: SHOTS + '/walk-knowledge-detail.png' });
      await page.goBack(); await settle(2000);
      B.kbBodyAfterBack = await page.evaluate(() => (document.body.innerText || '').length);
    } else B.noKbLink = true;
    results.backTests = B;
  }

  // standard walk for the group's page list
  const list = GROUPS[group] || [];
  for (const [route, label] of list) {
    const deny = group === 'g' ? /.*/ : DENY;
    results[route] = await walkPage(page, rec, route, label, { deny, cap: group === 'g' ? 0 : 22 });
    console.log('WALKED', route, 'unresp:', results[route].unresponsive.length, 'bad:', results[route].bad.length);
  }

  // group f: discover a school detail id and walk it
  if (group === 'f') {
    await gotoPage(page, '#/kaoyan/schools', 3400);
    const href = await page.evaluate(() => {
      const a = document.querySelector('a[href*="/kaoyan/schools/"]');
      return a ? a.getAttribute('href') : null;
    });
    if (href) {
      results[href] = await walkPage(page, rec, href.replace(/^#/, ''), '院校详情', { deny: DENY, cap: 14 });
    } else results.schoolDetail = 'NO_LINK_FOUND';
  }

  saveResult('p2-' + group, results);
  await ctx.close(); await browser.close();
  console.log('P2 GROUP', group, 'DONE');
})().catch(e => { console.error('P2 FATAL', e); process.exit(1); });
