// 中枢页公网真实登录态实测（账号从环境变量读取，凭据不落盘）
// 用法: HUB_USER=pyy HUB_PW=<密码> node scripts/hub_live_audit.mjs
import { chromium } from 'playwright'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SHOTS = path.join(HERE, 'shots')
fs.mkdirSync(SHOTS, { recursive: true })

const BASE = process.env.HUB_BASE || 'http://60.204.223.140'
const USER = process.env.HUB_USER || 'pyy'
const PW = process.env.HUB_PW
if (!PW) { console.error('[中止] 未设置 HUB_PW 环境变量'); process.exit(2) }

const FONT_LADDER = new Set([12, 13, 14, 16, 20, 24, 28, 36])
const findings = {}
const pageErrors = []
const consoleErrors = []

function check(name, ok, detail = '') {
  findings[name] = { ok, detail }
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
}

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })

// ---- 登录 ----
await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('input', { timeout: 20000 })
const inputs = await page.$$('input')
// 用户名/邮箱 + 密码
let userEl = null, passEl = null
for (const el of inputs) {
  const t = (await el.getAttribute('type')) || ''
  if (t === 'password') passEl = el
  else if (!userEl) userEl = el
}
if (!userEl || !passEl) { console.error('[中止] 登录页输入框未找到'); await browser.close(); process.exit(3) }
await userEl.fill(USER)
await passEl.fill(PW)
await Promise.all([
  page.waitForURL(/#\/(hub|login|change-password|dashboard|home)/, { timeout: 20000 }).catch(() => {}),
  page.click('button[type="submit"]').catch(() => page.click('button:has-text("登录")')),
])
await page.waitForTimeout(3500)
const afterLogin = page.url()
check('登录成功离开登录页', !/#\/login/.test(afterLogin), afterLogin)
fs.writeFileSync(path.join(SHOTS, 'live-after-login.png'), await page.screenshot({ fullPage: false }))

// ---- 进中枢 ----
if (!/#\/hub/.test(page.url())) {
  await page.goto(`${BASE}/#/hub`, { waitUntil: 'domcontentloaded' })
}
await page.waitForTimeout(4500) // 等聚合数据加载
check('当前在中枢页', /#\/hub/.test(page.url()), page.url())

// ---- A. 唯一主数字 ----
const mainFigCount = await page.$$eval('[data-main-figure]', (els) => els.length).catch(() => -1)
check('data-main-figure 全页唯一', mainFigCount === 1, `命中 ${mainFigCount}`)

// ---- B. 零调试文本 ----
const bodyText = await page.evaluate(() => document.body.innerText || '')
const apiLeaks = (bodyText.match(/\/api\/[a-zA-Z0-9_/\-]+/g) || []).filter(Boolean)
const costLeaks = (bodyText.match(/\b\d+\s?ms\b/gi) || []).filter(Boolean)
const perfWords = (bodyText.match(/耗时|延迟|端点|请求路径/g) || [])
check('无 /api 路径泄漏', apiLeaks.length === 0, apiLeaks.slice(0, 4).join(', '))
check('无 ms 耗时泄漏', costLeaks.length === 0, costLeaks.slice(0, 4).join(', '))
check('无性能调试词', perfWords.length === 0, perfWords.slice(0, 4).join(', '))

// ---- C. 字号阶梯（中枢容器内可见文本） ----
const offLadder = await page.evaluate((ladder) => {
  const set = new Set(ladder)
  const hub = document.querySelector('[class*="hub"], main') || document.body
  const bad = {}
  const seen = new Set()
  for (const el of hub.querySelectorAll('*')) {
    if (!el.textContent || !el.textContent.trim()) continue
    // 仅取叶子文本节点元素
    if (el.children.length > 0 && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) {
      // 混合容器也算，只要有直接文字
    } else if (el.children.length > 0) {
      continue
    }
    if (el.closest('.v3-sr-only, [hidden], [aria-hidden="true"]')) continue
    const st = getComputedStyle(el)
    if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) continue
    if (st.clip !== 'auto' && st.clip !== 'none') continue // sr-only clip: rect(0,0,0,0)
    if (st.position === 'absolute' && (parseFloat(st.width) <= 2 || parseFloat(st.height) <= 2)) continue
    const r = el.getBoundingClientRect()
    if (r.width <= 2 || r.height <= 2) continue // 微尺寸=视觉隐藏
    const px = Math.round(parseFloat(st.fontSize))
    if (!set.has(px) && !seen.has(px)) { seen.add(px); bad[px] = (el.textContent || '').trim().slice(0, 24) }
  }
  return bad
}, [...FONT_LADDER])
const offList = Object.entries(offLadder)
check('可见字号落在设计阶梯', offList.length === 0, offList.slice(0, 6).map(([px, t]) => `${px}px「${t}」`).join(' | '))

// ---- D. 无横向溢出 1440 ----
const ovf1440 = await page.evaluate(() => {
  const vw = document.documentElement.clientWidth
  const bad = []
  for (const el of document.querySelectorAll('*')) {
    const st = getComputedStyle(el)
    if (st.position === 'fixed') continue
    const r = el.getBoundingClientRect()
    if (r.width === 0) continue
    if (r.right > vw + 2 || r.left < -2) bad.push(`${el.tagName}.${(el.className || '').toString().slice(0, 24)} right=${Math.round(r.right)}`)
  }
  return { vw, docW: document.documentElement.scrollWidth, bad: bad.slice(0, 6) }
})
check('1440 无横向溢出', ovf1440.docW <= ovf1440.vw + 2, `scrollW ${ovf1440.docW} vs vw ${ovf1440.vw}; ${ovf1440.bad.join(' | ')}`)
fs.writeFileSync(path.join(SHOTS, 'live-hub-1440.png'), await page.screenshot({ fullPage: true }))

// ---- E. 主题持久化（刷新后 data-theme 不变） ----
const theme1 = await page.evaluate(() => document.documentElement.getAttribute('data-theme') || document.body.getAttribute('data-theme') || getComputedStyle(document.documentElement).getPropertyValue('color-scheme'))
await page.reload({ waitUntil: 'domcontentloaded' })
await page.waitForTimeout(3500)
const theme2 = await page.evaluate(() => document.documentElement.getAttribute('data-theme') || document.body.getAttribute('data-theme') || getComputedStyle(document.documentElement).getPropertyValue('color-scheme'))
check('主题刷新后保持', String(theme1) === String(theme2), `${theme1} -> ${theme2}`)

// ---- F. live region + skip link ----
const liveCount = await page.evaluate(() => document.querySelectorAll('[role="status"],[role="alert"],[aria-live]').length)
check('存在 live region', liveCount >= 1, `命中 ${liveCount}`)
const skipFirst = await page.evaluate(() => {
  const sel = 'a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])'
  const nodes = [...document.querySelectorAll(sel)].filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 })
  const first = nodes[0]
  return first ? `${first.tagName} ${(first.getAttribute('href') || first.className || '').toString().slice(0, 30)} :: ${(first.textContent || '').trim().slice(0, 20)}` : 'none'
})
check('首个可聚焦为 skip-link（或页内跳转）', /skip|跳转|到主内容|main|content/i.test(skipFirst), skipFirst)

// ---- G. 移动端 375 无溢出 ----
await page.setViewportSize({ width: 375, height: 812 })
await page.waitForTimeout(2000)
const ovf375 = await page.evaluate(() => ({ vw: document.documentElement.clientWidth, docW: document.documentElement.scrollWidth }))
check('375 无横向溢出', ovf375.docW <= ovf375.vw + 2, `scrollW ${ovf375.docW} vs vw ${ovf375.vw}`)
fs.writeFileSync(path.join(SHOTS, 'live-hub-375.png'), await page.screenshot({ fullPage: true }))

// ---- H. pageerror / console ----
check('0 pageerror', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
const realConsoleErr = consoleErrors.filter((t) => !/favicon|401|netdisk|Failed to load resource/i.test(t))
check('0 真实 console error', realConsoleErr.length === 0, realConsoleErr.slice(0, 3).join(' | ') || `(${consoleErrors.length} 条含预期 401/资源)`)

// ---- 汇总 ----
const pass = Object.values(findings).filter((f) => f.ok).length
const total = Object.keys(findings).length
console.log(`\n==== 中枢公网登录实测 ${pass}/${total} ====`)
for (const [k, v] of Object.entries(findings)) if (!v.ok) console.log(`  ✗ ${k}: ${v.detail}`)
console.log(`截图目录: ${SHOTS}`)
await browser.close()
process.exit(pass === total ? 0 : 1)
