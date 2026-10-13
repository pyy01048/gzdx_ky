import { launch, openPage, shot, api, dump } from './harness.mjs'

const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : dump(x)).join(' '))
const browser = await launch()
try {
  const before = await api('/api/words/stats')
  const p = await openPage(browser, '/words', { waitMs: 4000 })
  await shot(p.page, 'words-01-learn.png')
  log('### /words 单词记忆')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, 'failedReq=', p.failedReqs.length, '| api4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))
  const cerr = p.consoleMsgs.filter(m => m.type === 'error'); if (cerr.length) log('CONSOLE-ERR:', cerr.slice(0, 4))

  const s0 = await p.page.evaluate(() => ({
    stats: [...document.querySelectorAll('.stat-tile')].map(e => e.innerText.replace(/\s+/g, ' ')),
    tabs: [...document.querySelectorAll('.seg button, .segmented button, [class*=seg] button')].map(b => b.innerText.trim()),
    emptyState: document.body.innerText.includes('今日单词已全部复习完成'),
    currentWord: document.querySelector('.card .page-title')?.innerText?.trim(),
    hasReveal: !!document.querySelector('button.block'),
    bodyLen: document.body.innerText.length,
  }))
  log('首屏:', s0)
  log('后端 words/stats:', before.json)

  // 若空队列，点重新开始
  if (s0.emptyState) {
    const b = p.page.locator('button', { hasText: '重新开始今日复习' })
    if (await b.count()) { await b.first().click(); await p.page.waitForTimeout(1500); log('已点"重新开始今日复习"') }
  }

  const curWord = () => p.page.evaluate(() => document.querySelector('.card .page-title')?.innerText?.trim() || null)
  let w1 = await curWord()
  log('当前单词:', w1)
  await shot(p.page, 'words-02-word.png')

  // 点显示释义
  const revealBtn = p.page.locator('button', { hasText: '显示释义' })
  log('显示释义按钮:', await revealBtn.count())
  if (await revealBtn.count()) {
    await revealBtn.first().click(); await p.page.waitForTimeout(1000)
    const detail = await p.page.evaluate(() => {
      const card = document.querySelector('.card')
      return { text: card?.innerText?.replace(/\s+/g, ' ').slice(0, 400) }
    })
    log('显示释义后卡片:', detail.text)
    await shot(p.page, 'words-03-reveal.png')

    // 四档评分按钮
    const grades = await p.page.evaluate(() => ['忘记', '模糊', '记得', '简单'].filter(t => [...document.querySelectorAll('button')].some(b => b.innerText.replace(/\s+/g, '').startsWith(t))))
    log('四档按钮存在:', grades)
    // 点"记得"
    const good = p.page.locator('button', { hasText: '记得' }).first()
    if (await good.count()) {
      await good.click(); await p.page.waitForTimeout(2000)
      const w2 = await curWord()
      log('点"记得"后单词变化:', w1, '->', w2, '| 已切换:', w1 !== w2)
      await shot(p.page, 'words-04-after-grade.png')
    }
  }

  const after = await api('/api/words/stats')
  log('后端 words/stats 前/后:', dump(before.json), '->', dump(after.json))

  // 词库列表视图
  const listTab = p.page.locator('button, [role=tab]', { hasText: '词库列表' }).first()
  if (await listTab.count()) {
    await listTab.click(); await p.page.waitForTimeout(1800)
    const listInfo = await p.page.evaluate(() => ({
      rows: document.querySelectorAll('table tbody tr, .list-row, [class*=word] .card').length,
      bodyLen: document.body.innerText.length,
      sample: document.body.innerText.replace(/\s+/g, ' ').slice(400, 900),
    }))
    log('词库列表视图:', listInfo)
    await shot(p.page, 'words-05-wordlist.png')
  }

  // 试卷模式（翻卡）
  const fcBtn = p.page.locator('button', { hasText: '试卷模式' })
  if (await fcBtn.count()) {
    await fcBtn.first().click(); await p.page.waitForTimeout(800)
    log('切换试卷模式后当前卡片文本:', await p.page.evaluate(() => document.querySelector('.card')?.innerText?.replace(/\s+/g, ' ').slice(0, 200)))
    await shot(p.page, 'words-06-flashcard.png')
  }
} catch (e) { log('异常:', String(e)) }
await browser.close()
