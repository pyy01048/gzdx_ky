import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FE = path.resolve(HERE, '..')
const OUT = path.join(FE, 'acceptance')
const BASE = process.env.SHOUTU_ACCEPTANCE_BASE || 'http://127.0.0.1:5173'
const VIEWPORTS = [
  { name: '1440', width: 1440, height: 900 },
  { name: '390', width: 390, height: 844 },
]
const ME = { id: 7, username: 'acceptance-user', display_name: '验收用户', role: 'user', is_admin: false, must_change_password: false }
const ERROR = {
  id: 42,
  question_id: 901,
  content: '计算极限 lim(x→0) sin(x)/x，并说明所用等价无穷小。',
  my_answer: '直接代入 0/0，极限为 0。',
  correct_answer: 'lim(x→0) sin(x)/x = 1。',
  error_reason: '概念混淆',
  subject: '数学',
  accuracy: 0.25,
  review_count: 2,
  last_review: '2026-11-24T08:00:00Z',
  next_review: '2026-11-26T08:00:00Z',
  status: 'active',
  mastery_state: 'weak',
  mastery_label: '薄弱',
  tags: ['极限', '等价无穷小'],
  analysis: '',
  created_at: '2026-11-20T08:00:00Z',
}
const KP = { id: 9, knowledge_point_id: 9, name: '等价无穷小', subject: '数学', chapter: '极限', mastery: 40, question_count: 2 }
const AI_ANALYSIS = {
  analysis: '错因是把 0/0 型未定式误当成可直接计算的代数式。应先判断极限类型，再使用重要极限或等价无穷小。',
  category: '概念混淆',
  knowledge_point: '等价无穷小',
  suggestion: '先单独练习 sin(x)/x、tan(x)/x 与 1-cos(x) 的极限，再处理乘积中的主项。',
  confidence: 0.86,
  engine: '本地规则',
  model: '不提供',
  practice_questions: [{ question_id: 902, content: '求 lim(x→0) tan(x)/x。', answer: '1' }],
}
const results = []
const browser = await chromium.launch({ headless: true })

function record(viewport, flow, check, ok, detail = '') {
  results.push({ viewport, flow, check, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'} ${viewport} ${flow} :: ${check}${detail ? ` :: ${detail}` : ''}`)
}

function json(body, status = 200) {
  return { status, contentType: 'application/json', body: JSON.stringify(body) }
}

function hashParams(value) {
  const hash = new URL(value, BASE).hash
  return new URLSearchParams(hash.split('?')[1] || '')
}

function hashPath(value) {
  return new URL(value, BASE).hash.slice(1)
}

function tree(subject, includePoints) {
  const chapters = subject === '英语'
    ? [{ title: '阅读理解', knowledge_point_count: 1, learned_avg_mastery: 40, unlearned_count: 0 }]
    : [{ title: '极限', knowledge_point_count: 1, learned_avg_mastery: 40, unlearned_count: 0 }]
  if (includePoints) {
    chapters[0].knowledge_points = subject === '英语'
      ? [{ ...KP, id: 10, knowledge_point_id: 10, subject: '英语', chapter: '阅读理解', name: '长难句' }]
      : [KP]
  }
  return { tree: [{ subject: subject || '数学', is_core: true, knowledge_point_count: 1, learned_avg_mastery: 40, mastered_count: 0, weak_count: 1, unlearned_count: 0, chapters }] }
}

async function installPrivateMocks(page, options = {}) {
  const calls = []
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url())
    const p = url.pathname.replace(/^\/api/, '')
    calls.push({ path: p, query: Object.fromEntries(url.searchParams), method: route.request().method() })
    if (p === '/auth/me') return route.fulfill(json(ME))
    if (p === '/auth/refresh') return route.fulfill(json({ ok: true }))
    if (p === '/auth/logout') return route.fulfill(json({ ok: true }))
    if (p === '/errors') return route.fulfill(json({ items: [ERROR], total: 1, page: 1, page_size: 20, total_pages: 1 }))
    if (p === '/errors/stats') return route.fulfill(json({ total: 1, active_errors: 1, due_errors: 1, archived_errors: 0, unlearned: 0, weak: 1, mastered: 0, labels: { weak: '薄弱' } }))
    if (p === '/errors/404') return route.fulfill(json({ code: 'not_found', message: '错题不存在' }, 404))
    if (p === '/errors/42') return route.fulfill(json(ERROR))
    if (p === '/errors/42/knowledge-points') return route.fulfill(json({ error_id: 42, items: [{ ...KP, link_id: 71, verified: true, source: 'manual' }] }))
    if (p === '/errors/42/ai-analyze') return route.fulfill(json(AI_ANALYSIS))
    if (p === '/quiz/wrong-reasons') return route.fulfill(json({ total: 1, items: [{ reason: '概念混淆', count: 1 }] }))
    if (p === '/taxonomy/subjects') return route.fulfill(json({ subjects: [{ subject: '数学', question_count: 2, knowledge_point_count: 1 }, { subject: '英语', question_count: 1, knowledge_point_count: 1 }] }))
    if (p === '/taxonomy/tree') {
      if (options.failTree) return route.fulfill(json({ code: 'upstream_error', message: '知识结构暂不可用' }, 503))
      const includePoints = url.searchParams.get('include_points') !== 'false'
      return route.fulfill(json(tree(url.searchParams.get('subject') || '', includePoints)))
    }
    if (p === '/taxonomy/knowledge-points') return route.fulfill(json({ items: [KP], total: 1, page: 1, page_size: 100, total_pages: 1 }))
    if (p === '/taxonomy/knowledge-points/9') return route.fulfill(json(KP))
    if (p === '/quiz/questions') return route.fulfill(json({ items: [{ id: 902, content: '求 lim(x→0) tan(x)/x。', answer: '1', analysis: '利用 tan(x)/x 的极限为 1。', subject: '数学', chapter: '极限', knowledge_point_id: 9 }], total: 1, page: 1, page_size: 6, total_pages: 1 }))
    if (p === '/taxonomy/coverage') return route.fulfill(json({ totals: { chapters: 2, covered_chapters: 1, documents: 3, chunks: 12 } }))
    if (p === '/review/due') return route.fulfill(json({ items: [], total: 0 }))
    if (p === '/review/weak-points') return route.fulfill(json({ items: [] }))
    if (p === '/review/link-stats' || p === '/review/stats') return route.fulfill(json({}))
    if (p === '/kb/health') return route.fulfill(json({}))
    if (p === '/kaoyan/analysis/recommend/529/set-goal') return route.fulfill(json({ ok: true }))
    return route.fulfill(json({}))
  })
  return calls
}

async function installAnonymousAuthMock(page) {
  await page.route(/^https?:\/\/[^/]+\/api\/auth\/me$/, (route) => route.fulfill(json(null)))
}

async function installAbortableStream(page) {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    window.fetch = (input, init = {}) => {
      const url = typeof input === 'string' ? input : input.url
      if (!url.includes('/api/ai/chat/stream')) return originalFetch(input, init)
      const encoder = new TextEncoder()
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(`data:${JSON.stringify({ type: 'delta', content: '尚未完成的回答' })}\n\n`))
          init.signal?.addEventListener('abort', () => {
            controller.error(new DOMException('Aborted', 'AbortError'))
          }, { once: true })
        },
      })
      return Promise.resolve(new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    }
  })
}

async function inspect(page, viewport) {
  return page.evaluate((mobile) => {
    const visible = (el) => {
      const r = el.getBoundingClientRect()
      const s = getComputedStyle(el)
      return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0'
        && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight
    }
    const rendered = (el) => {
      const r = el.getBoundingClientRect()
      const s = getComputedStyle(el)
      return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0'
    }
    const h1 = [...document.querySelectorAll('h1')].filter(rendered)
    const root = document.querySelector('.v3-main__inner') || document.body
    const targets = [...root.querySelectorAll('a[href], button, input, select, textarea, summary, [role="button"]')]
      .filter((el) => !el.closest('.v3-skip-link'))
      .filter(visible)
    return {
      title: document.title,
      h1: h1.map((el) => el.textContent.trim()),
      overflow: Math.max(0, document.documentElement.scrollWidth - innerWidth),
      breadcrumbs: document.querySelectorAll('nav[aria-label="面包屑"]').length,
      smallTargets: mobile ? targets.filter((el) => {
        const r = el.getBoundingClientRect()
        return r.width < 44 || r.height < 44
      }).map((el) => {
        const r = el.getBoundingClientRect()
        return { tag: el.tagName.toLowerCase(), className: String(el.className), label: el.getAttribute('aria-label') || el.textContent.trim().slice(0, 30), width: Math.round(r.width), height: Math.round(r.height) }
      }) : [],
      animations: document.getAnimations().filter((animation) => animation.playState === 'running').length,
    }
  }, viewport.width < 768)
}

async function audit(page, viewport, flow, label, { detail = false } = {}) {
  await page.waitForTimeout(100)
  const metrics = await inspect(page, viewport)
  record(viewport.name, flow, `${label}-single-h1`, metrics.h1.length === 1, JSON.stringify(metrics.h1))
  record(viewport.name, flow, `${label}-title`, metrics.title.includes('硕途考研') && metrics.title.length > 6, metrics.title)
  record(viewport.name, flow, `${label}-no-overflow`, metrics.overflow <= 1, `delta=${metrics.overflow}`)
  if (detail) record(viewport.name, flow, `${label}-breadcrumb`, metrics.breadcrumbs === 1, `count=${metrics.breadcrumbs}`)
  if (viewport.width < 768) {
    record(viewport.name, flow, `${label}-touch-44px`, metrics.smallTargets.length === 0, JSON.stringify(metrics.smallTargets))
    record(viewport.name, flow, `${label}-reduced-motion`, metrics.animations === 0, `running=${metrics.animations}`)
  }
  return metrics
}

async function shot(page, viewport, flow, label) {
  await mkdir(OUT, { recursive: true })
  await page.screenshot({ path: path.join(OUT, `detail-${flow}-${label}-${viewport.name}.png`), fullPage: true })
}

async function withPage(browser, viewport, flow, privateMocks, work) {
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, reducedMotion: 'reduce', colorScheme: 'light' })
  const page = await context.newPage()
  const pageErrors = []
  const consoleErrors = []
  const httpErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource:')) {
      consoleErrors.push(message.text().slice(0, 300))
    }
  })
  page.on('response', (response) => {
    if (response.status() >= 400) {
      httpErrors.push({ path: new URL(response.url()).pathname, status: response.status() })
    }
  })
  let calls = []
  if (privateMocks) calls = await installPrivateMocks(page, privateMocks)
  else await installAnonymousAuthMock(page)
  try {
    await work(page, calls)
    const expected = flow === 'error'
      ? (failure) => failure.path === '/api/errors/404' && failure.status === 404
      : flow === 'knowledge-error'
        ? (failure) => failure.path === '/api/taxonomy/tree' && failure.status === 503
        : () => false
    const unexpectedHttpErrors = httpErrors.filter((failure) => !expected(failure))
    const expectedFailures = httpErrors.filter(expected)
    record(viewport.name, flow, 'no-pageerror', pageErrors.length === 0, pageErrors.join(' | '))
    record(viewport.name, flow, 'no-console-error', consoleErrors.length === 0, consoleErrors.join(' | '))
    record(viewport.name, flow, 'no-unexpected-http-error', unexpectedHttpErrors.length === 0, JSON.stringify(unexpectedHttpErrors))
    if (flow === 'error' || flow === 'knowledge-error') {
      record(viewport.name, flow, 'expected-http-failure-observed', expectedFailures.length > 0, JSON.stringify(expectedFailures))
    }
  } catch (error) {
    record(viewport.name, flow, 'flow-completed', false, error.stack || error.message)
    await shot(page, viewport, flow, 'failed').catch(() => {})
  } finally {
    await context.close()
  }
}

async function publicRecommend(page, viewport) {
  const flow = 'recommend'
  await page.goto(`${BASE}/#/kaoyan/recommend`, { waitUntil: 'domcontentloaded' })
  const score = page.getByLabel('预估总分')
  await score.waitFor({ timeout: 30000 })
  await page.getByRole('combobox', { name: '参考年份' }).waitFor({ timeout: 30000 })
  await score.fill('350')
  await page.getByRole('button', { name: '开始推荐' }).click()
  const detailLink = page.getByRole('link', { name: /查看推荐依据/ }).first()
  await detailLink.waitFor({ timeout: 30000 })
  const href = await detailLink.getAttribute('href')
  record(viewport.name, flow, 'detail-url-score-350', hashParams(href).get('score') === '350', href)
  await score.fill('370')
  record(viewport.name, flow, 'request-params-frozen', (await detailLink.getAttribute('href')) === href, await detailLink.getAttribute('href'))
  await shot(page, viewport, flow, 'list')
  await detailLink.click()
  await page.getByRole('heading', { name: /为什么推荐给你/ }).waitFor({ timeout: 30000 })
  record(viewport.name, flow, 'deep-link-keeps-score', hashParams(page.url()).get('score') === '350', page.url())
  record(viewport.name, flow, 'score-breakdown-visible', await page.getByText('评分拆解', { exact: true }).isVisible())
  record(viewport.name, flow, 'raw-evidence-visible', await page.getByText('分数线记录', { exact: true }).isVisible() && await page.getByText('招生记录', { exact: true }).isVisible())
  await audit(page, viewport, flow, 'recommend-detail', { detail: true })
  await shot(page, viewport, flow, 'detail')
  await page.getByRole('link', { name: /查看完整院校档案/ }).click()
  await page.locator('h1:visible').first().waitFor({ timeout: 30000 })
  record(viewport.name, flow, 'school-profile-deep-link', !page.url().includes('/recommend/'), page.url())
  await audit(page, viewport, flow, 'school-profile')
  await shot(page, viewport, flow, 'school-profile')

  await page.goto(`${BASE}/#/kaoyan/recommend/529`, { waitUntil: 'domcontentloaded' })
  await page.getByText('推荐详情链接不完整', { exact: true }).waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'invalid-link-state', true)
  await audit(page, viewport, flow, 'invalid-link')
  await shot(page, viewport, flow, 'invalid-link')
}

async function errorDetail(page, viewport) {
  const flow = 'error'
  await page.goto(`${BASE}/#/error-review`, { waitUntil: 'domcontentloaded' })
  const row = page.getByRole('button').filter({ hasText: '计算极限' })
  await row.waitFor({ timeout: 30000 })
  await row.click()
  const open = page.getByRole('link', { name: /打开单题工作台/ })
  await open.waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'list-entry', hashPath(await open.getAttribute('href')) === '/error-review/42', await open.getAttribute('href'))
  await open.click()
  await page.getByRole('heading', { name: '错题详情与 AI 加固' }).waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'single-record-loaded', await page.getByText(ERROR.content, { exact: true }).isVisible())
  record(viewport.name, flow, 'knowledge-deep-link', hashPath(await page.getByRole('link', { name: /等价无穷小/ }).getAttribute('href')) === '/knowledge/9', await page.getByRole('link', { name: /等价无穷小/ }).getAttribute('href'))
  await page.getByRole('button', { name: '开始 AI 归因' }).click()
  const follow = page.getByRole('link', { name: /继续追问 AI/ })
  await follow.waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'ai-analysis-loaded', await page.getByText(AI_ANALYSIS.analysis, { exact: true }).isVisible())
  record(viewport.name, flow, 'follow-up-has-question', decodeURIComponent((await follow.getAttribute('href'))).includes(ERROR.content))
  await audit(page, viewport, flow, 'error-detail', { detail: true })
  await shot(page, viewport, flow, 'detail')
  await follow.click()
  await page.getByLabel('向 AI 助手提问').waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'follow-up-prefilled', (await page.getByLabel('向 AI 助手提问').inputValue()).includes(ERROR.content))

  await page.goto(`${BASE}/#/error-review/404`, { waitUntil: 'domcontentloaded' })
  await page.getByText('这条错题不存在或不属于当前账号', { exact: true }).waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'missing-record-state', true)
  await audit(page, viewport, flow, 'missing-record')
  await shot(page, viewport, flow, 'missing-record')
}

async function assistantDetail(page, viewport) {
  const flow = 'assistant'
  await page.goto(`${BASE}/#/assistant`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: 'AI 助手', exact: true }).waitFor({ timeout: 30000 })
  await page.getByRole('tab', { name: '本地', exact: true }).click()
  const question = '请解释等价无穷小，并给出一个易错例子。'
  await page.getByLabel('向 AI 助手提问').fill(question)
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const open = page.getByRole('link', { name: '查看回答与引用详情' })
  await open.waitFor({ timeout: 15000 })
  const archive = await page.evaluate(() => JSON.parse(localStorage.getItem('kaoyan-ai-answer-archive-v1:7') || '[]'))
  record(viewport.name, flow, 'account-scoped-archive', archive.length === 1 && archive[0].question === question, `count=${archive.length}`)
  const href = await open.getAttribute('href')
  record(viewport.name, flow, 'archive-entry', /^#?\/assistant\/answers\/.+/.test(href), href)
  await audit(page, viewport, flow, 'assistant-list')
  await shot(page, viewport, flow, 'list')
  await open.click()
  await page.getByRole('heading', { name: '回答与引用详情' }).waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'question-preserved', await page.getByText(question, { exact: true }).isVisible())
  record(viewport.name, flow, 'engine-preserved', await page.getByText('本地规则', { exact: true }).first().isVisible())
  record(viewport.name, flow, 'empty-citations-honest', await page.getByText('权威引用（0）', { exact: true }).isVisible())
  await audit(page, viewport, flow, 'answer-detail', { detail: true })
  await shot(page, viewport, flow, 'detail')
  await page.getByRole('link', { name: /基于这条回答追问/ }).click()
  await page.getByLabel('向 AI 助手提问').waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'answer-follow-up-prefilled', (await page.getByLabel('向 AI 助手提问').inputValue()).includes('等价无穷小'))

  await page.goto(`${BASE}/#/assistant/answers/not-found`, { waitUntil: 'domcontentloaded' })
  await page.getByText('当前账号没有这条回答记录', { exact: true }).waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'missing-archive-state', true)
  await audit(page, viewport, flow, 'missing-answer')
  await shot(page, viewport, flow, 'missing-answer')
}

async function assistantAbort(page, viewport) {
  const flow = 'assistant-abort'
  await page.goto(`${BASE}/#/assistant`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: 'AI 助手', exact: true }).waitFor({ timeout: 30000 })
  await page.getByLabel('向 AI 助手提问').fill('请开始一段会被中止的回答。')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const stop = page.getByRole('button', { name: '停止', exact: true })
  await stop.waitFor({ timeout: 15000 })
  await page.getByText('尚未完成的回答', { exact: true }).waitFor({ timeout: 15000 })
  await stop.click()
  await page.getByRole('button', { name: '停止', exact: true }).waitFor({ state: 'detached', timeout: 15000 })
  record(viewport.name, flow, 'partial-answer-kept', await page.getByText('尚未完成的回答', { exact: true }).isVisible())
  record(viewport.name, flow, 'no-archive-dead-link', await page.getByRole('link', { name: '查看回答与引用详情' }).count() === 0)
  await shot(page, viewport, flow, 'aborted')
}

async function knowledgeMap(page, viewport, calls, options = {}) {
  const flow = options.failTree ? 'knowledge-error' : 'knowledge'
  await page.goto(`${BASE}/#/knowledge`, { waitUntil: 'domcontentloaded' })
  if (options.failTree) {
    await page.getByText('知识地图加载失败', { exact: true }).waitFor({ timeout: 15000 })
    record(viewport.name, flow, 'failure-state', await page.getByRole('button', { name: '重新加载', exact: true }).isVisible())
    await audit(page, viewport, flow, 'failure')
    await shot(page, viewport, flow, 'failure')
    return
  }
  const chapter = page.locator('button.v3-kb-chapter').filter({ hasText: '极限' })
  await chapter.waitFor({ timeout: 30000 })
  record(viewport.name, flow, 'light-tree-first', calls.some((call) => call.path === '/taxonomy/tree' && call.query.include_points === 'false'))
  await chapter.click()
  await page.getByText('等价无穷小', { exact: true }).first().waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'chapter-lazy-load', calls.some((call) => call.path === '/taxonomy/knowledge-points' && call.query.subject === '数学' && call.query.chapter === '极限'))
  record(viewport.name, flow, 'practice-entry-visible', await page.getByRole('button', { name: /去练习|练习/ }).first().isVisible())
  await audit(page, viewport, flow, 'knowledge-map')
  await shot(page, viewport, flow, 'map')
  await page.locator('button.v3-kb-point__main').filter({ hasText: '等价无穷小' }).click()
  await page.getByRole('heading', { name: '等价无穷小', exact: true }).waitFor({ timeout: 30000 })
  record(viewport.name, flow, 'article-deep-link', hashPath(page.url()) === '/knowledge/9', page.url())
  await page.getByText('关联真题', { exact: false }).first().waitFor({ timeout: 15000 })
  record(viewport.name, flow, 'single-point-loaded', await page.getByText('求 lim(x→0) tan(x)/x。', { exact: true }).isVisible())
  record(viewport.name, flow, 'related-questions-requested', calls.some((call) => call.path === '/quiz/questions' && call.query.kp_id === '9'))
  await audit(page, viewport, flow, 'knowledge-article', { detail: true })
  await shot(page, viewport, flow, 'article')
}

try {
  for (const viewport of VIEWPORTS) {
    await withPage(browser, viewport, 'recommend', null, (page) => publicRecommend(page, viewport))
    await withPage(browser, viewport, 'error', {}, (page) => errorDetail(page, viewport))
    await withPage(browser, viewport, 'assistant', {}, (page) => assistantDetail(page, viewport))
    await withPage(browser, viewport, 'assistant-abort', {}, async (page) => {
      await installAbortableStream(page)
      await assistantAbort(page, viewport)
    })
    await withPage(browser, viewport, 'knowledge', {}, (page, calls) => knowledgeMap(page, viewport, calls))
    await withPage(browser, viewport, 'knowledge-error', { failTree: true }, (page, calls) => knowledgeMap(page, viewport, calls, { failTree: true }))
  }
} finally {
  await browser.close()
}

const report = {
  date: new Date().toISOString(),
  baseURL: BASE,
  browser: 'Chromium / Playwright',
  viewports: VIEWPORTS,
  authentication: '登录态使用 /api/auth/me 与个人域接口测试夹具；公开推荐链使用真实本地后端',
  passed: results.filter((item) => item.ok).length,
  failed: results.filter((item) => !item.ok).length,
  results,
}
await writeFile(path.join(OUT, 'detail-pages-report.json'), JSON.stringify(report, null, 2))
console.log(`RESULT passed=${report.passed} failed=${report.failed}`)
if (report.failed) process.exitCode = 1
