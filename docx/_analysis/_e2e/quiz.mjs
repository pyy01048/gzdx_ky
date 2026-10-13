import { launch, openPage, shot, api, dump } from './harness.mjs'

const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : dump(x)).join(' '))
const browser = await launch()

/* ---------------- A. 题库管理 /quiz-bank ---------------- */
try {
  const p = await openPage(browser, '/quiz-bank', { waitMs: 3500 })
  await shot(p.page, 'quizbank-01-manage.png')
  log('### A. /quiz-bank 题库管理')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, 'failedReq=', p.failedReqs.length)
  log('api 4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))
  const s = await p.page.evaluate(() => ({
    header: document.querySelector('.page-header p')?.innerText?.replace(/\s+/g, ' '),
    stats: [...document.querySelectorAll('.stat-card')].map(c => c.innerText.replace(/\s+/g, ' ')),
    cards: document.querySelectorAll('.question-card').length,
    pager: [...document.querySelectorAll('span')].map(e => e.innerText).find(t => /第 \d+ \/ \d+ 页/.test(t)),
  }))
  log('管理页:', s)
  log('>> 同屏数字一致性: 页头=共3467道? 卡片=5588?', JSON.stringify({ header: s.header, card0: s.stats[0] }))

  // 第一题：点"显示答案/解析"
  const firstCard = p.page.locator('.question-card').first()
  const beforeTxt = await firstCard.innerText()
  await p.page.locator('.question-card button', { hasText: '显示答案/解析' }).first().click()
  await p.page.waitForTimeout(800)
  const afterTxt = await firstCard.innerText()
  log('显示答案后出现"正确答案/解析"?', /正确答案|解析/.test(afterTxt), '| 变化:', afterTxt.length - beforeTxt.length, '字')
  await shot(p.page, 'quizbank-02-reveal-answer.png')

  // 预览弹窗
  await p.page.locator('.question-card button', { hasText: '预览' }).first().click()
  await p.page.waitForTimeout(800)
  const modal = await p.page.evaluate(() => {
    const m = document.querySelector('.modal, [class*=modal]')
    return m ? m.innerText.replace(/\s+/g, ' ').slice(0, 300) : null
  })
  log('预览弹窗:', modal)
  await shot(p.page, 'quizbank-03-preview-modal.png')
  await p.page.keyboard.press('Escape').catch(() => {})

  // 搜索
  await p.page.locator('input.input').first().fill('放大器')
  await p.page.waitForTimeout(1800)
  const afterSearch = await p.page.locator('.page-header p').innerText()
  log('搜索"放大器"后页头:', afterSearch)
  await shot(p.page, 'quizbank-04-search.png')
  await p.ctx.close()
} catch (e) { log('A 段异常:', String(e)) }

/* ---------------- B. 刷题中心 /quiz ---------------- */
try {
  const p = await openPage(browser, '/quiz', { waitMs: 4000 })
  await shot(p.page, 'quiz-01-home.png')
  log('\n### B. /quiz 刷题中心')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, 'failedReq=', p.failedReqs.length)
  log('api 4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))
  const home = await p.page.evaluate(() => ({
    heroStats: [...document.querySelectorAll('.qh-hstat')].map(e => e.innerText.replace(/\s+/g, ' ')),
    firstSubj: document.querySelector('.qknow-subj')?.innerText?.replace(/\s+/g, ' '),
    subjCount: document.querySelectorAll('.qknow-subj').length,
    rowCount: document.querySelectorAll('.qknow-row').length,
  }))
  log('首页:', home)

  // 选一个"有题"的科目：数字电子技术(2335) / 模拟电子技术(2894)
  let pickedSubj = null, pickedChapter = null
  for (const name of ['数字电子技术', '模拟电子技术', '英语', '政治']) {
    const el = p.page.locator('.qknow-subj', { hasText: name }).first()
    if (await el.count()) { await el.click(); pickedSubj = name; break }
  }
  log('选中科目:', pickedSubj)
  await p.page.waitForTimeout(2000)
  await shot(p.page, 'quiz-02-subject.png')

  // 点第一个章节"开始练习"，或整科练习
  let started = false
  const rows = p.page.locator('.qknow-row')
  if (await rows.count()) {
    pickedChapter = (await rows.first().innerText()).replace(/\s+/g, ' ').slice(0, 40)
    await rows.first().click()
    started = true
  } else {
    const whole = p.page.locator('.qknow-head button', { hasText: '整科练习' })
    if (await whole.count()) { await whole.click(); started = true }
  }
  log('开始练习:', started, '| 章节:', pickedChapter)
  await p.page.waitForTimeout(3000)

  const inPractice = await p.page.evaluate(() => !!document.querySelector('.qprac-stem'))
  log('已进入答题视图:', inPractice)
  if (inPractice) {
    const stem = await p.page.locator('.qprac-stem').innerText()
    const opts = await p.page.locator('.qopt').allInnerTexts()
    log('题干:', stem.replace(/\s+/g, ' ').slice(0, 160))
    log('选项数:', opts.length, dump(opts.map(o => o.replace(/\s+/g, ' ').slice(0, 60))))
    await shot(p.page, 'quiz-03-question.png')

    // 与后端核对这道题
    const qApi = await api(`/api/quiz/questions?subject=${encodeURIComponent(pickedSubj)}&page=1&page_size=100`)
    const list = qApi.json?.questions || qApi.json?.items || []
    const stemCore = stem.replace(/\s+/g, '').replace(/^\d+\./, '')
    const match = list.find(x => x.content && stemCore.includes(x.content.replace(/\s+/g, '').slice(0, 20)))
    log('后端同科目题数:', list.length, '| 匹配到该题:', match ? { id: match.id, ans: match.answer, type: match.question_type } : '未匹配到')

    if (opts.length) {
      // 点第一个选项再点第二个，看选中态切换
      await p.page.locator('.qopt').nth(0).click(); await p.page.waitForTimeout(300)
      const sel0 = await p.page.evaluate(() => document.querySelectorAll('.qopt.sel').length)
      if (opts.length > 1) { await p.page.locator('.qopt').nth(1).click(); await p.page.waitForTimeout(300) }
      const sel1 = await p.page.evaluate(() => [...document.querySelectorAll('.qopt')].map(b => b.className).join(' | '))
      log('单选选中态: 点1后 sel数=', sel0, '点2后 class=', sel1)
      await shot(p.page, 'quiz-04-selected.png')

      // 提交
      const subBtn = p.page.locator('button', { hasText: '提交答案' })
      log('提交按钮存在:', await subBtn.count())
      await subBtn.first().click()
      await p.page.waitForTimeout(2500)
      const reveal = await p.page.evaluate(() => {
        const r = document.querySelector('.qreveal')
        return r ? r.innerText.replace(/\s+/g, ' ') : null
      })
      log('提交后揭示区:', reveal)
      const okOpts = await p.page.evaluate(() => [...document.querySelectorAll('.qopt')].map(b => b.className))
      log('选项判分态:', JSON.stringify(okOpts))
      // 与后端答案核对
      const shownAns = (reveal || '').match(/正确答案：\s*([A-F]+)/)?.[1]
      log('>> 页面显示正确答案:', shownAns, '| 后端该题答案:', match?.answer, '| 一致:', shownAns === match?.answer)
      await shot(p.page, 'quiz-05-submitted.png')

      // 下一题
      const nextBtn = p.page.locator('button', { hasText: '下一题' })
      if (await nextBtn.count()) {
        const stemBefore = stem
        await nextBtn.first().click(); await p.page.waitForTimeout(1500)
        const stem2 = await p.page.locator('.qprac-stem').innerText()
        log('下一题后题干变化:', stem2.replace(/\s+/g, ' ').slice(0, 80), '| 与上一题不同:', stem2 !== stemBefore)
        await shot(p.page, 'quiz-06-next.png')
      }
    }
  } else {
    log('未进入答题视图，可能该章节无题。空态文本:', await p.page.evaluate(() => document.body.innerText.match(/暂无[^\n]*|无题[^\n]*|空[^\n]*/)?.[0] || null))
  }
  await p.ctx.close()
} catch (e) { log('B 段异常:', String(e)) }

await browser.close()
