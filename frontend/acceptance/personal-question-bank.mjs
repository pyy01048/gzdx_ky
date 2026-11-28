import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'

const baseURL = 'http://127.0.0.1:5173'
const report = { date: new Date().toISOString(), checks: [], scenarios: [] }
const browser = await chromium.launch({ headless: true })

const user = {
  id: 99201,
  username: 'pqb-browser-test',
  nickname: '题库验收用户',
  role: 'student',
  must_change_password: false,
  is_active: true,
}

function bank(id = 11, name = '数学专项') {
  return { id, name, description: '错题与自建题', question_count: 0, mastered_count: 0 }
}

function question(id = 21, bankId = 11, mastery = 'unmastered') {
  return {
    id,
    bank_id: bankId,
    bank_ids: bankId ? [bankId] : [],
    content: '2 的平方是多少？',
    question_type: 'single',
    options: [{ key: 'A', text: '甲' }, { key: 'B', text: '乙' }],
    answer: 'A',
    analysis: '2 的平方等于 4，对应选项甲。',
    subject: '数学',
    chapter: '极限',
    difficulty: 3,
    mastery_state: mastery,
    is_personal: true,
    source_kind: 'user_created',
  }
}

function createState(seed = false) {
  const initialBank = bank()
  const initialQuestion = question()
  const state = {
    banks: seed ? [initialBank] : [],
    questions: seed ? [initialQuestion] : [],
    failSubmit: false,
    releaseSubmit: null,
    nextBankId: 12,
    nextQuestionId: 22,
    nextSessionId: 31,
    sessions: new Map(),
  }
  syncBank(state, initialBank)
  return state
}

function summarize(state, bankId) {
  const items = state.questions.filter((item) => (
    !bankId || (item.bank_ids?.length ? item.bank_ids : [item.bank_id]).map(Number).includes(Number(bankId))
  ))
  const mastered = items.filter((item) => item.mastery_state === 'mastered').length
  return { total: items.length, mastered, unmastered: items.length - mastered }
}

function syncBank(state, item) {
  if (!item) return
  const summary = summarize(state, item.id)
  item.question_count = summary.total
  item.mastered_count = summary.mastered
}

function sessionPayload(state, session) {
  return {
    session_id: session.id,
    title: session.bank?.name || '个人题库练习',
    mode: 'practice',
    no_answer: false,
    basis: { kind: 'personal_question_bank', bank_id: session.bank_id },
    filters: session.filters,
    questions: session.questions.map((item) => {
      const answered = session.records[String(item.id)]
      const { answer, analysis, correct_answer, reference_answer, ...safe } = item
      return answered ? { ...safe, answer, analysis } : { ...safe, answer: null, analysis: null }
    }),
    current_index: session.current_index,
    version: session.version,
    drafts: session.drafts,
    text_drafts: session.text_drafts,
    self_scores: session.self_scores,
    marked: session.marked,
    elapsed_seconds: session.duration_seconds,
    duration_seconds: session.duration_seconds,
    total_questions: session.questions.length,
    answered_count: Object.keys(session.records).length,
    correct_count: Object.values(session.records).filter((record) => record.correct === true).length,
    status: session.status,
    updated_at: session.updated_at,
    records: session.records,
  }
}

async function installApiMock(context, state) {
  await context.route(/^http:\/\/127\.0\.0\.1:5173\/api\//, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')
    const method = request.method()
    const json = (body, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (path === '/auth/me' && method === 'GET') return json(user)
    if (path === '/quiz/personal/sets' && method === 'GET') {
      return json({ items: state.banks, total: state.banks.length })
    }
    if (path === '/quiz/personal/sets' && method === 'POST') {
      const body = request.postDataJSON()
      const item = { ...bank(state.nextBankId++, body.name), description: body.description || '' }
      state.banks.push(item)
      return json(item, 201)
    }
    if (path === '/quiz/personal/questions' && method === 'GET') {
      const bankId = url.searchParams.get('bank_id')
      const mastery = url.searchParams.get('mastery') || url.searchParams.get('mastery_state')
      const subject = url.searchParams.get('subject')
      const chapter = url.searchParams.get('chapter')
      const questionType = url.searchParams.get('question_type')
      let items = state.questions.filter((item) => (
        !bankId || (item.bank_ids?.length ? item.bank_ids : [item.bank_id]).map(Number).includes(Number(bankId))
      ))
      if (mastery && mastery !== 'all') items = items.filter((item) => item.mastery_state === mastery)
      if (subject) items = items.filter((item) => item.subject === subject)
      if (chapter) items = items.filter((item) => item.chapter === chapter)
      if (questionType) items = items.filter((item) => item.question_type === questionType)
      return json({
        items,
        total: items.length,
        page: Number(url.searchParams.get('page') || 1),
        page_size: Number(url.searchParams.get('page_size') || 20),
        summary: summarize(state, bankId),
      })
    }
    if (path === '/quiz/personal/questions' && method === 'POST') {
      const body = request.postDataJSON()
      const item = question(state.nextQuestionId++, Number(body.bank_id))
      Object.assign(item, body)
      item.bank_ids = body.bank_id ? [Number(body.bank_id)] : []
      item.is_personal = true
      item.source_kind = 'user_created'
      state.questions.push(item)
      syncBank(state, state.banks.find((entry) => entry.id === item.bank_id))
      return json(item, 201)
    }
    const masteryMatch = path.match(/^\/quiz\/personal\/questions\/(\d+)\/mastery$/)
    if (masteryMatch && method === 'PUT') {
      const item = state.questions.find((entry) => entry.id === Number(masteryMatch[1]))
      if (!item) return json({ detail: '题目不存在' }, 404)
      item.mastery_state = request.postDataJSON().mastery_state
      syncBank(state, state.banks.find((entry) => entry.id === item.bank_id))
      return json({ ok: true })
    }
    if (path === '/quiz/personal/practice/sessions' && method === 'POST') {
      const body = request.postDataJSON()
      const bankId = body.bank_id == null ? null : Number(body.bank_id)
      const bank = state.banks.find((entry) => entry.id === bankId) || null
      let items = state.questions.filter((item) => (
        !bankId || (item.bank_ids?.length ? item.bank_ids : [item.bank_id]).map(Number).includes(bankId)
      ))
      if (body.mastery_state && body.mastery_state !== 'all') {
        items = items.filter((item) => item.mastery_state === body.mastery_state)
      }
      if (body.subject) items = items.filter((item) => item.subject === body.subject)
      if (body.chapter) items = items.filter((item) => item.chapter === body.chapter)
      if (body.question_type) items = items.filter((item) => item.question_type === body.question_type)
      const session = {
        id: state.nextSessionId++,
        bank_id: bankId,
        bank,
        questions: items,
        records: {},
        current_index: Number(body.start_index) || 0,
        version: 1,
        drafts: {},
        text_drafts: {},
        self_scores: {},
        marked: {},
        duration_seconds: 0,
        status: 'in_progress',
        filters: body,
        updated_at: new Date().toISOString(),
      }
      state.sessions.set(session.id, session)
      return json(sessionPayload(state, session), 201)
    }
    const sessionMatch = path.match(/^\/quiz\/sessions\/(\d+)(\/complete)?$/)
    if (sessionMatch) {
      const session = state.sessions.get(Number(sessionMatch[1]))
      if (!session) return json({ detail: '练习会话不存在' }, 404)
      if (sessionMatch[2] && method === 'POST') {
        session.status = 'completed'
        session.updated_at = new Date().toISOString()
        return json(sessionPayload(state, session))
      }
      if (!sessionMatch[2] && method === 'GET') return json(sessionPayload(state, session))
      if (!sessionMatch[2] && method === 'PATCH') {
        const body = request.postDataJSON()
        if (body.version !== session.version) return json({ detail: '进度版本已变化，请刷新后重试' }, 409)
        Object.assign(session, body, { version: session.version + 1, updated_at: new Date().toISOString() })
        return json(sessionPayload(state, session))
      }
    }
    if (path === '/quiz/submit' && method === 'POST') {
      if (state.failSubmit) return json({ detail: '提交失败：网络开小差了，请重试' }, 500)
      if (state.releaseSubmit) await new Promise((resolve) => { state.releaseSubmit = resolve })
      const body = request.postDataJSON()
      const session = state.sessions.get(Number(body.session_id))
      const item = state.questions.find((entry) => entry.id === Number(body.question_id))
      if (!session || !item || !session.questions.some((entry) => entry.id === item.id)) {
        return json({ detail: '题目不存在或不在当前练习会话' }, 404)
      }
      const correct = body.my_answer === item.answer
      item.mastery_state = correct ? 'mastered' : 'unmastered'
      syncBank(state, state.banks.find((entry) => entry.id === item.bank_id))
      const record = {
        question_id: item.id,
        my_answer: body.my_answer,
        correct,
        correct_answer: item.answer,
        analysis: item.analysis,
        needs_review: false,
        client_attempt_id: body.client_attempt_id,
      }
      session.records[String(item.id)] = record
      return json(record)
    }
    if (path === '/quiz/questions' && method === 'GET') return json({ items: [], total: 0, page: 1, page_size: 20 })
    return json({ items: [], total: 0 })
  })
}

function monitor(page, allowedConsoleErrors = []) {
  const errors = []
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error' && !allowedConsoleErrors.includes(message.text())) {
      errors.push(`console: ${message.text()}`)
    }
  })
  return errors
}

async function layoutMetrics(page) {
  return page.evaluate(() => {
    const root = document.documentElement
    const body = document.body
    const shell = document.querySelector('.v3-app-shell')
    return {
      overflow: Math.max(0, root.scrollWidth - window.innerWidth),
      viewport: window.innerWidth,
      root_client_width: root.clientWidth,
      root_scroll_width: root.scrollWidth,
      body_client_width: body.clientWidth,
      body_scroll_width: body.scrollWidth,
      body_background: getComputedStyle(body).backgroundColor,
      root_background: getComputedStyle(root).backgroundColor,
      shell_width: shell?.getBoundingClientRect().width ?? null,
      h1: [...document.querySelectorAll('h1')].filter((node) => {
        const rect = node.getBoundingClientRect()
        return rect.width > 0 && rect.height > 0
      }).map((node) => node.textContent.trim()),
    }
  })
}

function assertInsideViewport(box, viewport, label) {
  assert.ok(box && box.x >= 0 && box.x + box.width <= viewport.width
    && box.y >= 0 && box.y + box.height <= viewport.height,
  `${label}被裁切：${JSON.stringify(box)}`)
}

async function runDesktopEmptyToPractice() {
  const state = createState(false)
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
  await installApiMock(context, state)
  const page = await context.newPage()
  const errors = monitor(page)
  const scenario = { name: 'desktop-empty-to-practice', viewport: '1440x900', checks: [] }
  try {
    await page.goto(`${baseURL}/personal-question-bank`, { waitUntil: 'domcontentloaded' })
    await page.getByText('还没有个人题目').waitFor()
    assert.equal(await page.getByRole('button', { name: '新建题库' }).isEnabled(), true)
    assert.equal(await page.getByRole('button', { name: '自建题目' }).isEnabled(), true)
    assert.equal(await page.getByRole('button', { name: '去题库选题' }).isEnabled(), true)
    assert.equal(await page.getByText(/示例题库|演示题目/).count(), 0)
    scenario.checks.push('新号诚实空态与三个真实入口')
    await page.screenshot({ path: 'acceptance/personal-bank-empty-1440.png', fullPage: true })

    await page.getByRole('button', { name: '新建题库' }).click()
    const bankDialog = page.getByRole('dialog', { name: /新建题库/ })
    await bankDialog.getByLabel(/题库名称/).fill('  数学专项  ')
    await bankDialog.getByLabel(/题库描述/).fill('  错题与自建题  ')
    await bankDialog.getByRole('button', { name: /保存|创建/ }).click()
    await page.getByText('数学专项', { exact: true }).waitFor()
    assert.equal(state.banks[0].name, '数学专项')
    assert.equal(state.banks[0].description, '错题与自建题')
    scenario.checks.push('建库表单清理首尾空格并立即展示')

    await page.getByRole('button', { name: /数学专项/ }).click()
    await page.getByRole('button', { name: '自建题目' }).click()
    const questionDialog = page.getByRole('dialog', { name: /自建题目/ })
    await questionDialog.getByLabel('题目内容').fill('  2 的平方是多少？  ')
    await questionDialog.getByLabel(/选项/).fill('A. 甲\nB. 乙')
    await questionDialog.getByLabel('标准答案').fill('A')
    await questionDialog.getByLabel('答案解析').fill('  2 的平方等于 4，对应选项甲。  ')
    await questionDialog.getByLabel('科目').fill('数学')
    await questionDialog.getByLabel('章节').fill('极限')
    await questionDialog.getByLabel('难度').fill('3')
    await questionDialog.getByRole('button', { name: /保存|创建/ }).click()
    await page.getByText('2 的平方是多少？', { exact: true }).waitFor()
    assert.equal(state.questions.length, 1)
    assert.deepEqual(state.questions[0].options, ['甲', '乙'])
    scenario.checks.push('自建题写入个人资产并规范化选项')

    await page.getByRole('button', { name: '未掌握', exact: true }).click()
    await page.getByText('2 的平方是多少？', { exact: true }).waitFor()
    await page.getByRole('button', { name: '标记已掌握' }).click()
    await page.getByRole('button', { name: '已掌握', exact: true }).click()
    await page.getByRole('button', { name: '取消掌握' }).waitFor()
    assert.equal(state.questions[0].mastery_state, 'mastered')
    await page.getByRole('button', { name: '取消掌握' }).click()
    await page.getByRole('button', { name: '未掌握', exact: true }).click()
    await page.getByRole('button', { name: '标记已掌握' }).waitFor()
    scenario.checks.push('未掌握/已掌握筛选与手动状态切换')
    await page.screenshot({ path: 'acceptance/personal-bank-list-1440.png', fullPage: true })

    await page.getByRole('button', { name: '开始刷题' }).click()
    await page.getByText('2 的平方是多少？', { exact: true }).waitFor()
    const before = await page.locator('body').innerText()
    assert.equal(before.includes('答案解析'), false)
    assert.equal(before.includes('答案：A'), false)
    assert.equal(before.includes('2 的平方等于 4，对应选项甲。'), false)
    scenario.checks.push('练习响应与页面提交前均不泄露答案和解析')
    await page.screenshot({ path: 'acceptance/personal-bank-practice-before-1440.png', fullPage: true })

    state.releaseSubmit = () => {}
    await page.getByRole('radio', { name: /A.*甲/ }).click()
    await page.getByRole('button', { name: '提交答案', exact: true }).click()
    const pendingText = await page.locator('body').innerText()
    assert.equal(pendingText.includes('答案：A'), false)
    assert.equal(pendingText.includes('2 的平方等于 4，对应选项甲。'), false)
    state.releaseSubmit()
    await page.getByText(/回答正确|答对了/).first().waitFor()
    await page.getByText(/答案[：:]\s*A/).waitFor()
    await page.getByText('2 的平方等于 4，对应选项甲。', { exact: true }).waitFor()
    assert.equal(state.questions[0].mastery_state, 'mastered')
    scenario.checks.push('提交等待期间不揭示，服务端返回后揭示并更新掌握状态')
    await page.screenshot({ path: 'acceptance/personal-bank-practice-after-1440.png', fullPage: true })

    await page.getByRole('button', { name: '交卷并查看报告' }).first().click()
    await page.getByText('本次练习报告', { exact: true }).waitFor()
    scenario.checks.push('完成练习后进入结果页')
    const metrics = await layoutMetrics(page)
    assert.equal(metrics.overflow, 0)
    assert.deepEqual(errors, [])
    scenario.metrics = metrics
  } catch (error) {
    scenario.error = error.stack
    await page.screenshot({ path: 'acceptance/personal-bank-desktop-failed.png', fullPage: true }).catch(() => {})
  } finally {
    scenario.errors = errors
    report.scenarios.push(scenario)
    await context.close()
  }
}

async function runMobileFailure() {
  const state = createState(true)
  state.failSubmit = true
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' })
  await installApiMock(context, state)
  const page = await context.newPage()
  const errors = monitor(page, ['Failed to load resource: the server responded with a status of 500 (Internal Server Error)'])
  const scenario = { name: 'mobile-submit-failure', viewport: '390x844', checks: [] }
  try {
    await page.goto(`${baseURL}/personal-question-bank?bankId=11&view=bank`, { waitUntil: 'domcontentloaded' })
    await page.getByText('2 的平方是多少？', { exact: true }).waitFor()
    const listMetrics = await layoutMetrics(page)
    assert.equal(listMetrics.overflow, 0)
    await page.screenshot({ path: 'acceptance/personal-bank-list-390.png', fullPage: true })
    scenario.checks.push('移动端题库列表无横向溢出')

    await page.getByRole('button', { name: '开始刷题' }).click()
    await page.getByText('2 的平方是多少？', { exact: true }).waitFor()
    const practiceMetrics = await layoutMetrics(page)
    assert.equal(practiceMetrics.overflow, 0)
    const sheetFab = page.locator('.v3-quiz-sheet-fab')
    await sheetFab.waitFor()
    assert.equal(await sheetFab.evaluate((node) => node.parentElement === document.body), true,
      '移动端答题卡必须通过 Portal 直属 document.body，避免 backdrop-filter 改变固定定位')
    const sheetFabBox = await sheetFab.boundingBox()
    assertInsideViewport(sheetFabBox, { width: 390, height: 844 }, '移动端答题卡入口')
    const aiOrbBox = await page.locator('.v3-orb').boundingBox()
    const overlapsAiOrb = sheetFabBox.x < aiOrbBox.x + aiOrbBox.width
      && sheetFabBox.x + sheetFabBox.width > aiOrbBox.x
      && sheetFabBox.y < aiOrbBox.y + aiOrbBox.height
      && sheetFabBox.y + sheetFabBox.height > aiOrbBox.y
    assert.equal(overlapsAiOrb, false,
      `移动端答题卡与 AI 入口重叠：${JSON.stringify({ sheetFabBox, aiOrbBox })}`)

    const scrollState = await page.evaluate(() => {
      window.scrollTo(0, document.documentElement.scrollHeight)
      const scrollers = [...document.querySelectorAll('.v3-app-shell, .v3-main, .pqb-content, .v3-quiz-page')]
        .filter((node) => node.scrollHeight > node.clientHeight + 1)
      scrollers.forEach((node) => { node.scrollTop = node.scrollHeight })
      return {
        windowY: window.scrollY,
        internalScrollTops: scrollers.map((node) => node.scrollTop),
      }
    })
    assert.ok(scrollState.windowY > 0 || scrollState.internalScrollTops.some((top) => top > 0),
      `移动端练习页无法滚动，未覆盖固定定位随滚动偏移：${JSON.stringify(scrollState)}`)
    const scrolledSheetFabBox = await sheetFab.boundingBox()
    assertInsideViewport(scrolledSheetFabBox, { width: 390, height: 844 }, '滚动后的移动端答题卡入口')
    const scrolledAiOrbBox = await page.locator('.v3-orb').boundingBox()
    const overlapsAiOrbAfterScroll = scrolledSheetFabBox.x < scrolledAiOrbBox.x + scrolledAiOrbBox.width
      && scrolledSheetFabBox.x + scrolledSheetFabBox.width > scrolledAiOrbBox.x
      && scrolledSheetFabBox.y < scrolledAiOrbBox.y + scrolledAiOrbBox.height
      && scrolledSheetFabBox.y + scrolledSheetFabBox.height > scrolledAiOrbBox.y
    assert.equal(overlapsAiOrbAfterScroll, false,
      `滚动后移动端答题卡与 AI 入口重叠：${JSON.stringify({ scrolledSheetFabBox, scrolledAiOrbBox })}`)

    await sheetFab.click()
    await page.getByRole('dialog', { name: '答题卡' }).waitFor()
    await page.keyboard.press('Escape')
    scenario.checks.push('移动端答题卡入口完整可见且可打开')
    await page.getByRole('radio', { name: /B.*乙/ }).click()
    await page.getByRole('button', { name: '提交答案', exact: true }).click()
    const alert = page.locator('.v3-quiz-submit-error[role="alert"]')
    await alert.waitFor()
    await page.waitForFunction(() => {
      const node = document.querySelector('.v3-quiz-submit-error[role="alert"]')
      return node && node.textContent.includes('提交失败：网络开小差了，请重试')
    })
    assert.match(await alert.textContent(), /提交失败：网络开小差了，请重试/)
    const body = await page.locator('body').innerText()
    assert.equal(/回答正确|回答错误|提交成功/.test(body), false)
    assert.equal(/答案[：:]\s*[AB]/.test(body), false)
    assert.equal(body.includes('2 的平方等于 4，对应选项甲。'), false)
    assert.equal(state.questions[0].mastery_state, 'unmastered')
    scenario.checks.push('移动端提交失败仅显示错误，不猜答案、不更新掌握状态')
    await page.screenshot({ path: 'acceptance/personal-bank-failure-390.png', fullPage: true })
    assert.deepEqual(errors, [])
    scenario.metrics = {
      list: listMetrics,
      practice: practiceMetrics,
      floating: { sheetFabBox, aiOrbBox, scrolledSheetFabBox, scrolledAiOrbBox, scrollState },
    }
  } catch (error) {
    scenario.error = error.stack
    await page.screenshot({ path: 'acceptance/personal-bank-mobile-failed.png', fullPage: true }).catch(() => {})
  } finally {
    scenario.errors = errors
    report.scenarios.push(scenario)
    await context.close()
  }
}

await runDesktopEmptyToPractice()
await runMobileFailure()
await browser.close()
await writeFile('acceptance/personal-question-bank-report.json', JSON.stringify(report, null, 2))
for (const scenario of report.scenarios) {
  console.log(JSON.stringify({
    name: scenario.name,
    checks: scenario.checks,
    metrics: scenario.metrics,
    errors: scenario.errors,
    error: scenario.error,
  }))
}
if (report.scenarios.some((scenario) => scenario.error || scenario.errors.length)) process.exitCode = 1
