import { launch, openPage, shot, api, dump } from './harness.mjs'

const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : dump(x)).join(' '))
const browser = await launch()
const SUBJ = '数字电子技术'
try {
  const p = await openPage(browser, '/quiz', { waitMs: 4000 })
  // 选科目
  await p.page.locator('.qknow-subj', { hasText: SUBJ }).first().click()
  await p.page.waitForTimeout(1500)
  // 整科练习
  const whole = p.page.locator('.qknow-head button')
  log('整科练习按钮:', await whole.count())
  await whole.first().click()
  await p.page.waitForTimeout(3000)
  log('进入答题视图:', await p.page.evaluate(() => !!document.querySelector('.qprac-stem')))

  // 后端同批题（与前端 startWithFilter 同参数）
  const qApi = await api(`/api/quiz/questions?subject=${encodeURIComponent(SUBJ)}&page=1&page_size=100`)
  const list = qApi.json?.questions || qApi.json?.items || []
  log('后端同批题数:', list.length)

  let choiceDone = false, textDone = false
  for (let step = 0; step < 14; step++) {
    const st = await p.page.evaluate(() => ({
      stem: document.querySelector('.qprac-stem')?.innerText?.replace(/\s+/g, ' ') || '',
      type: [...document.querySelectorAll('.qprac-meta .chip')].map(c => c.innerText)[0],
      options: [...document.querySelectorAll('.qopt')].map(b => b.innerText.replace(/\s+/g, ' ')),
      hasText: !!document.querySelector('.qtext-input'),
      answered: !!document.querySelector('.qreveal'),
    }))
    if (!st.stem) break
    const core = st.stem.replace(/\s+/g, '').replace(/^\d+\./, '')
    const match = list.find(x => x.content && core.includes(x.content.replace(/\s+/g, '').slice(0, 18)))
    log(`\n-- 第${step + 1}题 type=${st.type} options=${st.options.length} 后端答案=${match?.answer}`)
    log('   stem:', st.stem.slice(0, 90))

    if (st.options.length > 0 && !choiceDone) {
      // 选择题流程
      await p.page.locator('.qopt').nth(0).click(); await p.page.waitForTimeout(300)
      const cls0 = await p.page.evaluate(() => [...document.querySelectorAll('.qopt')].map(b => b.className))
      log('  点第1项后 class:', JSON.stringify(cls0))
      await shot(p.page, 'quiz-10-choice-selected.png')
      await p.page.locator('button', { hasText: '提交答案' }).first().click()
      await p.page.waitForTimeout(2500)
      const rev = await p.page.evaluate(() => ({
        reveal: document.querySelector('.qreveal')?.innerText?.replace(/\s+/g, ' '),
        cls: [...document.querySelectorAll('.qopt')].map(b => b.className),
      }))
      const shown = (rev.reveal || '').match(/正确答案：\s*([A-F]+)/)?.[1]
      log('  提交后揭示:', rev.reveal)
      log('  选项判分 class:', JSON.stringify(rev.cls))
      log('  >> 页面正确答案=', shown, '| 后端=', match?.answer, '| 一致:', shown === match?.answer)
      await shot(p.page, 'quiz-11-choice-submitted.png')
      choiceDone = true
    } else if (st.hasText && !textDone) {
      // 文本题流程
      await p.page.locator('.qtext-input').fill('我的作答测试')
      await p.page.locator('button', { hasText: '对照答案' }).first().click()
      await p.page.waitForTimeout(2500)
      const rev = await p.page.evaluate(() => document.querySelector('.qreveal')?.innerText?.replace(/\s+/g, ' '))
      log('  文本题对照答案揭示:', rev?.slice(0, 200))
      await shot(p.page, 'quiz-12-text-compare.png')
      const selfBtn = p.page.locator('button', { hasText: '我答错了' })
      if (await selfBtn.count()) { await selfBtn.first().click(); await p.page.waitForTimeout(1000) }
      log('  自评后出现下一题:', await p.page.locator('button', { hasText: '下一题' }).count())
      textDone = true
    } else if (st.answered) {
      log('  (已作答，跳过)')
    } else {
      log('  (无选项且非文本题，跳过)')
      if (st.hasText) { await p.page.locator('.qtext-input').fill('x'); await p.page.locator('button', { hasText: '对照答案' }).first().click(); await p.page.waitForTimeout(1500) }
    }

    if (choiceDone && textDone) break
    const next = p.page.locator('button', { hasText: '下一题' })
    if (!(await next.count())) { log('  没有下一题按钮（最后一题）'); break }
    await next.first().click(); await p.page.waitForTimeout(1200)
  }

  // 交卷并查看报告
  const finish = p.page.locator('button', { hasText: '交卷并查看报告' })
  if (await finish.count()) {
    await finish.first().click(); await p.page.waitForTimeout(1500)
    const res = await p.page.evaluate(() => ({
      acc: document.querySelector('.qresult-acc')?.innerText,
      stats: [...document.querySelectorAll('.qresult-stat')].map(e => e.innerText.replace(/\s+/g, ' ')),
      panels: [...document.querySelectorAll('.qresult-row')].slice(0, 5).map(e => e.innerText.replace(/\s+/g, ' ')),
    }))
    log('\n### 交卷报告:', res)
    await shot(p.page, 'quiz-13-result.png')
  } else {
    log('\n未到最后题，无交卷按钮。当前答题卡状态:', await p.page.evaluate(() => [...document.querySelectorAll('.qsheet-cell')].slice(0, 10).map(c => c.className)))
  }
} catch (e) { log('异常:', String(e), e.stack?.slice(0, 400)) }
await browser.close()
