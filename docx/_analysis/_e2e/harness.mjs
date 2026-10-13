// 复用型浏览器走查脚手架（只读诊断，不修改任何项目代码）
// 用法：import { walk } from './harness.mjs'
import pw from 'file:///D:/平台/frontend/node_modules/playwright/index.js'
const { chromium } = pw
import fs from 'node:fs'
import path from 'node:path'

export const BASE = 'http://127.0.0.1:5173'
export const API = 'http://127.0.0.1:8000'
export const SHOT_DIR = 'D:/平台/docx/_analysis/e2e-shots'

export function ensureShotDir() {
  fs.mkdirSync(SHOT_DIR, { recursive: true })
}

/**
 * 打开一个哈希路由页面并采集诊断信息。
 * @param {string} hash 例 '/library'
 * @param {object} opts { shot:'name.png', waitMs, waitFor:'selector', viewport }
 */
export async function openPage(browser, hash, opts = {}) {
  const ctx = await browser.newContext({
    viewport: opts.viewport || { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
    bypassCSP: true,
  })
  const page = await ctx.newPage()
  const consoleMsgs = []
  const pageErrors = []
  const failedReqs = []
  const apiCalls = []
  page.on('console', (m) => {
    const t = m.type()
    if (t === 'error' || t === 'warning') consoleMsgs.push({ type: t, text: m.text() })
  })
  page.on('pageerror', (e) => pageErrors.push(String(e && e.stack || e)))
  page.on('requestfailed', (r) => failedReqs.push({ url: r.url(), err: r.failure()?.errorText }))
  page.on('response', async (r) => {
    const u = r.url()
    if (u.includes('/api/')) {
      apiCalls.push({ url: u.replace(API, '').replace(BASE, ''), status: r.status() })
    }
  })
  const url = BASE + '/#' + hash
  let navErr = null
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 })
  } catch (e) { navErr = String(e.message) }
  if (opts.waitFor) {
    try { await page.waitForSelector(opts.waitFor, { timeout: opts.waitMs || 8000 }) } catch (e) { /* record below */ }
  } else {
    await page.waitForTimeout(opts.waitMs || 2500)
  }
  const state = await page.evaluate(() => {
    const root = document.getElementById('root') || document.body
    const txt = (root.innerText || '').trim()
    return {
      title: document.title,
      rootLen: txt.length,
      htmlLen: document.body.innerHTML.length,
      head: txt.slice(0, 400),
      hasReactError: /Something went wrong|应用出错|ErrorBoundary|发生错误/i.test(txt),
    }
  }).catch((e) => ({ err: String(e.message) }))
  return { page, ctx, consoleMsgs, pageErrors, failedReqs, apiCalls, navErr, state, url }
}

export async function shot(page, name, opts = {}) {
  ensureShotDir()
  const p = path.join(SHOT_DIR, name)
  try { await page.screenshot({ path: p, fullPage: opts.fullPage !== false }) } catch (e) { return { err: String(e.message) } }
  return { path: p }
}

export async function launch(opts = {}) {
  return chromium.launch({
    headless: true,
    args: ['--no-proxy-server', '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage'],
    ...opts,
  })
}

/** 直接调后端接口（绕过浏览器），用于交叉验证数据真伪 */
export async function api(pathname) {
  try {
    const r = await fetch(API + pathname, { headers: { accept: 'application/json' } })
    const txt = await r.text()
    let json = null
    try { json = JSON.parse(txt) } catch {}
    return { status: r.status, json, text: txt.slice(0, 2000) }
  } catch (e) { return { status: 0, err: String(e.message) } }
}

export function dump(obj) {
  return JSON.stringify(obj, null, 2)
}
