// e2e2 auth check: reuse old storageState; if invalid, API login; save fresh state.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'http://60.204.223.140';
const OLD_STATE = 'D:/平台/dogfood-output/auth-state.json';
const NEW_DIR = 'D:/平台/dogfood-output/e2e2';
const NEW_STATE = path.join(NEW_DIR, 'auth-state.json');
const USER = 'pyy';
const PASS = 'KymO085gl3IvD0Ze9aX7';

fs.mkdirSync(NEW_DIR, { recursive: true });

async function looksLoggedIn(page) {
  // SPA: go to dashboard; logged-in app shows nav / not redirected to login route
  await page.goto(BASE + '/#/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3500);
  const url = page.url();
  const body = await page.evaluate(() => document.body ? document.body.innerText.slice(0, 4000) : '');
  const hasLoginUI = /登录|登 录|请登录|用户名|密码/.test(body) && !/退出|仪表盘|任务打卡/.test(body);
  const navOk = /仪表盘|任务打卡|学习|练习|复盘|择校/.test(body);
  return { url, hasLoginUI, navOk, bodySnippet: body.slice(0, 300) };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const report = { steps: [] };

  // Step 1: try old state
  let ctx;
  if (fs.existsSync(OLD_STATE)) {
    ctx = await browser.newContext({ storageState: OLD_STATE, viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const r = await looksLoggedIn(page);
    report.steps.push({ step: 'old-state-check', ...r });
    console.log('[old-state]', JSON.stringify(r).slice(0, 500));
    if (r.navOk && !r.hasLoginUI) {
      // verify an authed API call too
      const resp = await page.request.get(BASE + '/api/tasks/');
      report.steps.push({ step: 'old-state-api-tasks', status: resp.status() });
      console.log('[old-state api /api/tasks/]', resp.status());
      if (resp.status() < 400) {
        await ctx.storageState({ path: NEW_STATE });
        console.log('OLD STATE VALID — saved to', NEW_STATE);
        report.conclusion = 'old-state-valid';
        fs.writeFileSync(path.join(NEW_DIR, 'auth-check.json'), JSON.stringify(report, null, 2));
        await browser.close();
        return;
      }
    }
    await ctx.close();
  }

  // Step 2: API login
  ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const loginResp = await page.request.post(BASE + '/api/auth/login', {
    data: { username: USER, password: PASS },
    headers: { 'Content-Type': 'application/json' },
  });
  const loginText = await loginResp.text().catch(() => '');
  report.steps.push({ step: 'api-login', status: loginResp.status(), body: loginText.slice(0, 400) });
  console.log('[api-login]', loginResp.status(), loginText.slice(0, 300));
  if (loginResp.status() >= 400) {
    report.conclusion = 'api-login-failed';
    fs.writeFileSync(path.join(NEW_DIR, 'auth-check.json'), JSON.stringify(report, null, 2));
    await browser.close();
    console.log('LOGIN FAILED');
    process.exit(2);
  }
  // reload app with cookies
  const r2 = await looksLoggedIn(page);
  report.steps.push({ step: 'after-login-check', ...r2 });
  console.log('[after-login]', JSON.stringify(r2).slice(0, 500));
  await ctx.storageState({ path: NEW_STATE });
  console.log('NEW STATE SAVED to', NEW_STATE);
  report.conclusion = 'api-login-ok';
  fs.writeFileSync(path.join(NEW_DIR, 'auth-check.json'), JSON.stringify(report, null, 2));
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
