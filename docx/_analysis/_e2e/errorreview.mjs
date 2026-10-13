import { launch, openPage, shot, api, dump } from './harness.mjs'

const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : dump(x)).join(' '))
const browser = await launch()
try {
  const errApi = await api('/api/errors?page=1&page_size=50')
  const arr = errApi.json?.items || errApi.json?.errors || (Array.isArray(errApi.json) ? errApi.json : [])
  log('后端 /api/errors total=', errApi.json?.total, 'items=', arr.length)
  const wr = await api('/api/quiz/wrong-reasons')
  const wp = await api('/api/analytics/weak-points')
  log('后端 wrong-reasons:', dump(wr.json), '| weak-points 数:', (wp.json?.weak_points || []).length)

  const p = await openPage(browser, '/error-review', { waitMs: 4000 })
  await shot(p.page, 'errorreview-01-list.png')
  log('\n### /error-review')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, 'failedReq=', p.failedReqs.length, '| api4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))
  const cerr = p.consoleMsgs.filter(m => m.type === 'error'); if (cerr.length) log('CONSOLE-ERR:', cerr.slice(0, 5))

  const s0 = await p.page.evaluate(() => ({
    itemButtons: [...document.querySelectorAll('button')].filter(b => /未掌握|已掌握/.test(b.innerText) && b.innerText.length > 20).length,
    filterChips: [...document.querySelectorAll('.kb-chip, .chip, button')].map(b => b.innerText.replace(/\s+/g, ' ')).filter(t => /^(全部|未掌握|已掌握|模考判错|答题错误)/.test(t)).slice(0, 12),
    bodyHead: document.body.innerText.replace(/\s+/g, ' ').slice(0, 200),
  }))
  log('列表统计:', s0)

  // 点第一条错题
  const first = p.page.locator('button').filter({ hasText: /未掌握|已掌握/ }).filter({ hasText: /复习 \d+ 次|正确率/ }).first()
  log('错题条目数（可点）:', await first.count())
  await first.click()
  await p.page.waitForTimeout(2000)
  const detail = await p.page.evaluate(() => {
    const t = document.body.innerText.replace(/\s+/g, ' ')
    return { len: t.length, detailTail: t.slice(-1200) }
  })
  log('点开后页面尾部文本:', detail.detailTail.slice(0, 1000))
  await shot(p.page, 'errorreview-02-detail.png')

  // AI 归因分析
  const ai = p.page.locator('button', { hasText: 'AI 归因分析' })
  log('AI 归因按钮:', await ai.count())
  if (await ai.count()) {
    await ai.first().click()
    await p.page.waitForTimeout(6000)
    const aiText = await p.page.evaluate(() => {
      const t = document.body.innerText.replace(/\s+/g, ' ')
      const i = t.indexOf('归因')
      return i >= 0 ? t.slice(i, i + 600) : t.slice(-600)
    })
    log('AI 归因结果:', aiText)
    await shot(p.page, 'errorreview-03-ai.png')
  }

  // 切筛选 已掌握
  const done = p.page.locator('button', { hasText: '已掌握' }).first()
  if (await done.count()) {
    await done.click(); await p.page.waitForTimeout(1500)
    log('切"已掌握"后按钮数:', await p.page.evaluate(() => [...document.querySelectorAll('button')].filter(b => /未掌握|已掌握/.test(b.innerText) && b.innerText.length > 20).length))
    await shot(p.page, 'errorreview-04-filter.png')
  }
} catch (e) { log('异常:', String(e)) }
await browser.close()
