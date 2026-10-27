// p3: responsive audit. usage: node p3-responsive.cjs mobile|tablet|laptop|desktop
const { SHOTS, makePage, settle, gotoPage, saveResult, overflowAudit } = require('./common3.cjs');
const { chromium } = require('playwright');

const VPS = {
  mobile: { width: 375, height: 667 },
  tablet: { width: 768, height: 1024 },
  laptop: { width: 1280, height: 800 },
  desktop: { width: 1920, height: 1080 },
};

const PAGES = [
  { key: 'dashboard', route: '#/' },
  { key: 'tasks', route: '#/tasks' },
  { key: 'quiz', route: '#/quiz' },
  { key: 'quiz-practice', route: '#/quiz', practice: true },
  { key: 'exam', route: '#/exam' },
  { key: 'words', route: '#/words' },
  { key: 'cards', route: '#/cards' },
  { key: 'error-review', route: '#/error-review' },
  { key: 'kaoyan', route: '#/kaoyan' },
  { key: 'kaoyan-schools', route: '#/kaoyan/schools' },
  { key: 'school-detail', route: 'DISCOVER' },
  { key: 'settings', route: '#/settings' },
];

(async () => {
  const vpName = process.argv[2] || 'mobile';
  const vp = VPS[vpName];
  const browser = await chromium.launch();
  const { ctx, page, rec } = await makePage(browser, { viewport: vp });

  // discover school detail hash once (any viewport works)
  let schoolHash = null;
  await gotoPage(page, '#/kaoyan/schools', 3400);
  schoolHash = await page.evaluate(() => {
    const a = document.querySelector('a[href*="/kaoyan/schools/"]');
    return a ? a.getAttribute('href') : null;
  }).catch(() => null);

  const out = { vp: vpName, viewport: vp, pages: {} };
  for (const p of PAGES) {
    const route = p.route === 'DISCOVER' ? (schoolHash || '#/kaoyan/schools') : p.route;
    const entry = { route, practiceEntered: false };
    await gotoPage(page, route, 3400);
    if (p.practice) {
      const start = page.locator('button:has-text("开始练习"), .qknow-action').first();
      if (await start.count()) {
        await start.click({ timeout: 3500 }).catch(() => {});
        await settle(2400);
        entry.practiceEntered = true;
        entry.hash = await page.evaluate(() => location.hash).catch(() => '');
      } else entry.note = 'NO_START_BUTTON';
    }
    entry.audit = await overflowAudit(page);
    await page.screenshot({ path: `${SHOTS}/resp-${p.key}_${vpName}.png`, fullPage: false }).catch(() => {});
    out.pages[p.key] = entry;
    console.log('AUDIT', p.key, vpName, 'overflow:', entry.audit && entry.audit.overflow, 'sw:', entry.audit && entry.audit.sw);
  }
  saveResult('p3-' + vpName, out);
  await ctx.close(); await browser.close();
  console.log('P3', vpName, 'DONE');
})().catch(e => { console.error('P3 FATAL', e); process.exit(1); });
