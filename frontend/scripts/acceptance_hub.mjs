/**
 * 今日中枢评审验收（FE_REVIEW / UX_REVIEW 自动化口径）。
 *
 * 跑法：node scripts/acceptance_hub.mjs
 * 依赖：vite preview（4173，serve 构建产物）+ 本地 playwright chromium。
 * 所有 /api 走 page.route mock（不依赖后端进程）；/media/images 从磁盘 fulfil。
 *
 * 断言口径（评审文档）：
 *  - 375 / 768 / 1440 / 1920 × light / dark 无横向溢出（含 .hub-step/.hub-kpi/.hub-heat/.hub/面包屑）
 *  - [data-main-figure] 全页唯一
 *  - .hub 内无调试文本（/api/、端点名、ms、耗时…）
 *  - .hub 可见字号 ⊆ {12,13,14,16,20,24,28,36}
 *  - .hub / 侧栏 / 顶栏 backdrop-filter 全 none；按钮 0 渐变
 *  - 首个 Tab 落在 skip link；移动端触控目标 ≥44px
 *  - 768 档侧栏 = 76px 导轨且分组短标签可见；1440 档 = 248px
 *  - 常驻 live region（role=status + role=alert）存在
 *  - 0 pageerror
 */
import { chromium } from 'playwright'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FE = path.resolve(HERE, '..')
const MEDIA_ROOT = path.resolve(FE, '../backend-main-fastapi/data/storage/images')
const SHOTS = path.join(FE, 'acceptance', 'shots')
fs.mkdirSync(SHOTS, { recursive: true })

const VIEWPORTS = [
  { w: 375, h: 812, name: '375' },
  { w: 768, h: 1024, name: '768' },
  { w: 1440, h: 900, name: '1440' },
  { w: 1920, h: 1080, name: '1920' },
]
const FONT_SET = new Set([12, 13, 14, 16, 20, 24, 28, 36])
const DEBUG_RE = /\/api\/|dashboard\/summary|insight\/today|words\/stats|review\/stats|fetchHubOverview|\bms\b|耗时|latency/i

/* ---- mock 载荷：真实形状（snake_case），非演示数据进应用，仅测试夹具 ---- */
const days = Array.from({ length: 14 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 10, 8 + i))
  const date = d.toISOString().slice(0, 10)
  const focus = [0, 30, 45, 0, 60, 25, 0, 40, 55, 30, 0, 45, 20, 0][i]
  const q = [0, 10, 15, 0, 20, 8, 0, 12, 18, 10, 0, 14, 6, 0][i]
  return {
    date, focus_minutes: focus, questions_done: q, questions_correct: Math.round(q * 0.8),
    correct_rate: q ? 80 : null, words_done: focus ? 20 : 0, cards_done: 0,
    tasks_done: i % 3 === 0 ? 1 : 0, is_effective: focus > 0,
  }
})
const SUMMARY = {
  generated_at: '2026-11-21T01:00:00Z',
  countdown: { days: 392, exam_date: '2027-12-18', exam_year: 2028, phase: 'base', university: '清华大学', major: '电子信息（0854）', is_default: false },
  goal: { configured: true, university: '清华大学', major: '电子信息（0854）', subjects: ['数学', '英语（一）'], support_subjects: ['政治'], daily_targets: { focus_minutes: 120, questions: 30, review_words: 50, new_words: 20 }, score_targets: { total: 350 }, targets_set: true },
  kpi: {
    today: { focus_minutes: 0, questions_done: 0, questions_correct: 0, correct_rate: null, words_done: 0, tasks_done: 0 },
    yesterday: { focus_minutes: 45, questions_done: 14, questions_correct: 11, correct_rate: 79 },
    delta: { focus_minutes: -45, questions_done: -14, correct_rate_pp: null },
    streak: { current: 4, longest: 11, total_days: 30, checked_today: false },
  },
  today_tasks: {
    total: 2, pending: 1, done: 1, doing: 0,
    tasks: [
      { id: 7, title: '高数第一章习题', subject: '数学', status: 'pending' },
      { id: 8, title: '英语阅读两篇', subject: '英语（一）', status: 'done' },
    ],
    modules: [{ module: 'word', label: '单词复习', due: 20, done: 0, unit: '个', status: 'pending', note: null }],
  },
  review_queue: { total: 0, cards: [], errors: [], tasks: [] },
  heatmap: { days: days.map((d) => ({ date: d.date, focus_minutes: d.focus_minutes, questions_done: d.questions_done, words_done: d.words_done, is_effective: d.is_effective })), levels: [0, 10, 30, 60], value_field: 'focus_minutes' },
  trend: { days: 14, series: days, week_focus_minutes: 160, weekly_completed_tasks: 4, subject_durations: { 数学: 120, '英语（一）': 80 } },
  weakness: { has_weakness: true, total_errors: 6, suggestion: '', weak_points: [{ knowledge_point_id: 3, name: '极限', chapter: '第一章', subject: '数学', error_count: 4, mastery: 35 }, { knowledge_point_id: 9, name: '中值定理', chapter: '第三章', subject: '数学', error_count: 2, mastery: 48 }], weak_subjects: [{ subject: '数学', count: 6, level: 'high' }], common_reasons: [{ reason: '概念不清', count: 3 }] },
  module_progress: [{ module: 'word', label: '单词', done: 0, target: 20, unit: '个', percent: 0, status: 'pending', note: '' }],
  future_load: { due_today: { errors: 3, flashcards: 0, tasks: 1, words: 20, total: 24 }, due_tomorrow: { errors: 3, flashcards: 0, tasks: 1, words: 20, total: 24 }, due_this_week: { errors: 9, flashcards: 0, tasks: 4, words: 60, total: 73 }, rule: '累计到期量（含此前未清的复习债）' },
  data_coverage: { is_empty: false },
  errors: { active: 3 },
}
const INSIGHT = {
  countdown: { days: 392 }, due_review_count: 12, today_answered: 0, today_correct: 0,
  weak_top: [{ knowledge_point_id: 3, kp: '极限', subject: '数学', error_count: 4 }],
  suggestions: [
    { icon: 'review', label: '到期复习', count: 12, to: '/quiz?tab=review', hint: '艾宾浩斯队列有 12 条到期' },
    { icon: 'target', label: '薄弱点练习', count: 2, to: '/quiz?mode=weak', hint: '极限' },
  ],
}
const WORDS = { due_today: 0, learning: 40, mastered: 120, new: 20, reviewing: 40, total: 160 }
const REVIEW = { active_errors: 3, due_errors: 0, graduated_errors: 8, today_reviews: 0, total_reviews: 40 }
const ME = { id: 1, username: 'ming', display_name: '小明', role: 'user', is_admin: false, must_change_password: false }

const results = []
function record(vp, theme, check, ok, detail = '') {
  results.push({ vp, theme, check, ok, detail })
  if (!ok) console.log(`  [FAIL] ${vp}/${theme} ${check} ${detail}`)
}

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const p = url.pathname.replace(/^\/api/, '')
    const json = (body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (p === '/dashboard/summary') return json(SUMMARY)
    if (p === '/insight/today') return json(INSIGHT)
    if (p === '/words/stats') return json(WORDS)
    if (p === '/review/stats') return json(REVIEW)
    if (p === '/auth/me') return json(ME)
    if (p.startsWith('/auth/')) return json({ ok: true })
    if (p === '/tasks' || p === '/tasks/today') return json({ items: SUMMARY.today_tasks.tasks, total: 2 })
    return json({})
  })
  await page.route('**/media/images/**', async (route) => {
    const rel = new URL(route.request().url()).pathname.replace('/media/images/', '')
    const file = path.join(MEDIA_ROOT, rel)
    if (fs.existsSync(file)) {
      const ext = path.extname(file).slice(1)
      return route.fulfill({ status: 200, contentType: `image/${ext === 'jpg' ? 'jpeg' : ext}`, body: fs.readFileSync(file) })
    }
    return route.fulfill({ status: 404, body: 'not found' })
  })
}

async function audit(page, vp, theme) {
  const r = await page.evaluate(({ fontSet, debugSrc }) => {
    const debugRe = new RegExp(debugSrc, 'i')
    const out = { overflow: [], fonts: [], blur: [], gradBtn: 0, mainFig: 0, live: {}, touch: [], rail: null, sidebarW: null, debug: [] }
    out.mainFig = document.querySelectorAll('[data-main-figure]').length
    const hub = document.querySelector('.hub')
    out.docOverflow = document.documentElement.scrollWidth - window.innerWidth
    for (const sel of ['.hub-step', '.hub-kpi', '.hub-heat', '.hub', '.v3-topbar__crumbs']) {
      for (const el of document.querySelectorAll(sel)) {
        const cs = getComputedStyle(el)
        if (cs.overflowX === 'visible') {
          /* 未裁切容器：scrollWidth 直接反映真实溢出 */
          if (el.scrollWidth > el.clientWidth + 1) out.overflow.push(`${sel}+${el.scrollWidth - el.clientWidth}`)
        } else {
          /* overflow:hidden 容器（如 KPI 卡的装饰光晕 ::before）：
             scrollWidth 会把被有意裁切的伪元素算进去，改测真实子元素包围盒 */
          const rect = el.getBoundingClientRect()
          for (const child of el.children) {
            const ccs = getComputedStyle(child)
            if (ccs.display === 'none' || ccs.position === 'absolute' || ccs.position === 'fixed') continue
            const cr = child.getBoundingClientRect()
            if (cr.width > 0 && (cr.right > rect.right + 1 || cr.left < rect.left - 1)) {
              out.overflow.push(`${sel}>${child.className.toString().slice(0, 20)}+${Math.round(cr.right - rect.right)}`)
            }
          }
        }
      }
    }
    if (hub) {
      const walk = document.createTreeWalker(hub, NodeFilter.SHOW_ELEMENT)
      while (walk.nextNode()) {
        const el = walk.currentNode
        const cs = getComputedStyle(el)
        if (cs.display === 'none' || cs.visibility === 'hidden') continue
        /* 屏幕阅读器专用文本（1px 裁切）不参与可视字号阶梯 */
        if (el.closest('.v3-sr-only')) continue
        const direct = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())
        if (direct) {
          const fs = parseFloat(cs.fontSize)
          if (!fontSet.includes(fs)) out.fonts.push(`${fs}:${el.textContent.trim().slice(0, 12)}`)
        }
        if (cs.backdropFilter && cs.backdropFilter !== 'none') out.blur.push(el.className.toString().slice(0, 30))
        if (el.classList.contains('v3-btn') && /gradient/.test(cs.backgroundImage)) out.gradBtn += 1
      }
      if (debugRe.test(hub.innerText)) out.debug.push(hub.innerText.match(debugRe)[0])
    }
    for (const sel of ['.v3-sidebar', '.v3-topbar']) {
      const el = document.querySelector(sel)
      if (el && getComputedStyle(el).backdropFilter !== 'none') out.blur.push(sel)
    }
    out.live.status = !!document.querySelector('.v3-toast-host [role="status"]')
    out.live.alert = !!document.querySelector('.v3-toast-host [role="alert"]')
    const sb = document.querySelector('.v3-sidebar')
    if (sb) out.sidebarW = Math.round(sb.getBoundingClientRect().width)
    const railLabels = [...document.querySelectorAll('.v3-nav-group__label span')]
      .filter((el) => getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().height > 0)
    out.rail = { labels: railLabels.length, sample: railLabels[0] ? getComputedStyle(railLabels[0]).fontSize : null }
    if (window.innerWidth < 768) {
      for (const el of document.querySelectorAll('.v3-mobile-nav a, .v3-mobile-nav button, .hub-task__check, .v3-topbar__mobile-only')) {
        const b = el.getBoundingClientRect()
        if (b.width > 0 && (b.width < 44 || b.height < 44)) out.touch.push(`${el.className.toString().slice(0, 24)}:${Math.round(b.width)}x${Math.round(b.height)}`)
      }
    }
    return out
  }, { fontSet: [...FONT_SET], debugSrc: DEBUG_RE.source })

  record(vp, theme, 'doc-no-h-overflow', r.docOverflow <= 1, `delta=${r.docOverflow}`)
  record(vp, theme, 'panel-no-clip', r.overflow.length === 0, r.overflow.join(','))
  record(vp, theme, 'unique-main-figure', r.mainFig === 1, `count=${r.mainFig}`)
  record(vp, theme, 'no-debug-text', r.debug.length === 0, r.debug.join(','))
  record(vp, theme, 'font-scale', r.fonts.length === 0, r.fonts.join(','))
  record(vp, theme, 'no-backdrop-blur', r.blur.length === 0, r.blur.join(','))
  record(vp, theme, 'no-gradient-buttons', r.gradBtn === 0, `n=${r.gradBtn}`)
  record(vp, theme, 'live-regions', r.live.status && r.live.alert, JSON.stringify(r.live))
  if (vp === '768') {
    record(vp, theme, 'rail-76px', r.sidebarW === 76, `w=${r.sidebarW}`)
    record(vp, theme, 'rail-labels-visible', r.rail.labels >= 3 && r.rail.sample === '12px', JSON.stringify(r.rail))
  }
  if (vp === '1440' || vp === '1920') record(vp, theme, 'sidebar-248px', r.sidebarW === 248, `w=${r.sidebarW}`)
  if (vp === '375') {
    record(vp, theme, 'touch-44px', r.touch.length === 0, r.touch.join(','))
    /* 暗色轮：点击主题按钮会把顺序焦点起点留在顶栏（浏览器行为，非缺陷）。
       重载后主题由持久化设置恢复，Tab 起点回到文档开头，再验证跳转链接。 */
    if (theme === 'dark') {
      await page.reload({ waitUntil: 'networkidle' })
      await page.waitForSelector('.hub-step', { timeout: 15000 })
      const stillDark = await page.evaluate(() => document.documentElement.getAttribute('data-theme'))
      record(vp, theme, 'theme-persists-reload', stillDark === 'dark', `data-theme=${stillDark}`)
    }
    const skip = await page.evaluate(() => {
      document.activeElement?.blur()
      return true
    })
    await page.keyboard.press('Tab')
    const first = await page.evaluate(() => document.activeElement?.className?.toString() || '')
    record(vp, theme, 'skip-link-first-tab', first.includes('v3-skip-link'), first.slice(0, 40))
  }
  return r
}

async function main() {
  const server = spawn('npx', ['vite', 'preview', '--port', '4173', '--strictPort'], { cwd: FE, shell: true, stdio: 'ignore' })
  await new Promise((r) => setTimeout(r, 2500))
  const browser = await chromium.launch()
  const pageErrors = []
  try {
    for (const vp of VIEWPORTS) {
      const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h }, colorScheme: 'light', deviceScaleFactor: 1 })
      const page = await ctx.newPage()
      page.on('pageerror', (e) => pageErrors.push(`${vp.name}: ${e.message}`))
      await mockApi(page)
      await page.goto('http://127.0.0.1:4173/#/hub', { waitUntil: 'networkidle' })
      await page.waitForSelector('.hub-step', { timeout: 15000 })
      await page.waitForTimeout(700)
      await audit(page, vp.name, 'light')
      await page.screenshot({ path: path.join(SHOTS, `hub-${vp.name}-light.png`), fullPage: vp.w < 800 })
      /* 真实点击顶栏主题按钮切暗色（顺带验证控件可用） */
      const themeBtn = page.locator('.v3-topbar button[aria-label*="主题"], .v3-topbar button[aria-label*="深色"], .v3-topbar button[aria-label*="浅色"]').first()
      await themeBtn.click()
      await page.waitForTimeout(500)
      const isDark = await page.evaluate(() => document.documentElement.dataset.theme === 'dark')
      record(vp.name, 'dark', 'theme-toggle-works', isDark)
      await audit(page, vp.name, 'dark')
      await page.screenshot({ path: path.join(SHOTS, `hub-${vp.name}-dark.png`), fullPage: vp.w < 800 })
      await ctx.close()
    }
    /* 院校页：封面 + 校徽真实渲染（清华 id=5 已回填） */
    /* 扩展名按磁盘实况解析：品牌化重跑可能 jpg↔png 换扩展，夹具不能写死 */
    const pickMedia = (dir, id) => {
      for (const e of ['jpg', 'png', 'webp']) {
        if (fs.existsSync(path.join(MEDIA_ROOT, dir, `${id}.${e}`))) return `/media/images/${dir}/${id}.${e}`
      }
      return null
    }
    const tsinghuaLogo = pickMedia('school_logos', 5)
    const tsinghuaCover = pickMedia('school_covers', 5)
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await ctx.newPage()
    page.on('pageerror', (e) => pageErrors.push(`schools: ${e.message}`))
    await mockApi(page)
    await page.route('**/api/kaoyan/schools**', async (route) => {
      const u = new URL(route.request().url())
      if (u.pathname.endsWith('/schools/5')) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 5, name: '清华大学', level: '985', province: '北京', city: '北京', logo_url: tsinghuaLogo, cover_url: tsinghuaCover, intro: '清华大学始建于1911年。', tags: ['985', '211'], official_url: 'https://www.tsinghua.edu.cn', coverage_score: 80, coverage_items: [], college_count: 21, major_count: 70, heat: 100, star: 5 }) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 2, page: 1, page_size: 20, items: [
        { id: 5, name: '清华大学', level: '985', province: '北京', city: '北京', logo_url: tsinghuaLogo, cover_url: tsinghuaCover, intro: '清华大学始建于1911年。', tags: ['985'], official_url: 'https://www.tsinghua.edu.cn', coverage_score: 80, heat: 100, star: 5, college_count: 21, major_count: 70 },
        { id: 24, name: '中国科学技术信息研究所', level: null, province: '北京', city: '北京', logo_url: null, cover_url: null, intro: '', tags: [], official_url: null, coverage_score: 20, heat: 1, star: 1, college_count: 0, major_count: 0 },
      ] }) })
    })
    await page.goto('http://127.0.0.1:4173/#/kaoyan/schools', { waitUntil: 'networkidle' })
    await page.waitForSelector('.kyv3-school', { timeout: 15000 })
    await page.waitForTimeout(900)
    const schoolAudit = await page.evaluate(() => {
      const covers = [...document.querySelectorAll('.kyv3-school-cover img')]
      const logos = [...document.querySelectorAll('.kyv3-logo img')]
      const loaded = (img) => img.complete && img.naturalWidth > 0
      return {
        covers: covers.length, coversLoaded: covers.filter(loaded).length,
        logos: logos.length, logosLoaded: logos.filter(loaded).length,
        fallbackChar: [...document.querySelectorAll('.kyv3-logo')].some((el) => !el.querySelector('img') && el.textContent.trim().length === 1),
        docOverflow: document.documentElement.scrollWidth - window.innerWidth,
      }
    })
    record('schools', 'light', 'cover-renders', schoolAudit.covers === 1 && schoolAudit.coversLoaded === 1, JSON.stringify(schoolAudit))
    record('schools', 'light', 'logo-renders', schoolAudit.logos === 1 && schoolAudit.logosLoaded === 1, JSON.stringify(schoolAudit))
    record('schools', 'light', 'no-branding-fallback', schoolAudit.fallbackChar, JSON.stringify(schoolAudit))
    record('schools', 'light', 'schools-no-overflow', schoolAudit.docOverflow <= 1, `delta=${schoolAudit.docOverflow}`)
    /* 截图取卡片区域而非页首：封面/校徽才是本次验收对象 */
    await page.locator('.kyv3-school-grid').scrollIntoViewIfNeeded()
    await page.waitForTimeout(600)
    await page.screenshot({ path: path.join(SHOTS, 'schools-1440-light.png'), fullPage: false })
    await page.goto('http://127.0.0.1:4173/#/kaoyan/schools/5', { waitUntil: 'networkidle' })
    await page.waitForSelector('.kyv3-hero-card', { timeout: 15000 })
    await page.waitForTimeout(900)
    const heroAudit = await page.evaluate(() => {
      const img = document.querySelector('.kyv3-hero-cover img')
      const logo = document.querySelector('.kyv3-hero-logo img')
      return {
        cover: !!img && img.complete && img.naturalWidth > 0,
        logo: !!logo && logo.complete && logo.naturalWidth > 0,
        hasCoverClass: document.querySelector('.kyv3-hero-card')?.classList.contains('has-cover'),
      }
    })
    record('detail', 'light', 'hero-cover-bg', heroAudit.cover && heroAudit.hasCoverClass, JSON.stringify(heroAudit))
    record('detail', 'light', 'hero-logo', heroAudit.logo, JSON.stringify(heroAudit))
    await page.screenshot({ path: path.join(SHOTS, 'school-detail-1440-light.png') })
    await ctx.close()
  } finally {
    await browser.close()
    server.kill()
  }
  record('all', '-', 'zero-pageerror', pageErrors.length === 0, pageErrors.join(' | ').slice(0, 300))
  const fails = results.filter((r) => !r.ok)
  fs.writeFileSync(path.join(FE, 'acceptance', 'report.json'), JSON.stringify({ total: results.length, failed: fails.length, results }, null, 1))
  console.log(`\n验收：${results.length - fails.length}/${results.length} 通过`)
  if (fails.length) { console.log('失败项：'); fails.forEach((f) => console.log(` - ${f.vp}/${f.theme} ${f.check} ${f.detail}`)) }
  console.log(`截图目录：${SHOTS}`)
  process.exit(fails.length ? 1 : 0)
}

main().catch((e) => { console.error(e); process.exit(1) })
