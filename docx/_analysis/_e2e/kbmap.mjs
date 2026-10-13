import { launch, openPage, shot, api, dump } from './harness.mjs'

const OUT = []
const log = (...a) => { const s = a.map(x => typeof x === 'string' ? x : dump(x)).join(' '); OUT.push(s); console.log(s) }

const browser = await launch()
try {
  const p = await openPage(browser, '/kbmap', { waitMs: 4000 })
  await shot(p.page, 'kbmap-01-overview.png')
  log('### KbMap 首屏')
  log('navErr=', p.navErr, 'pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, 'failedReq=', p.failedReqs.length)
  log('api 4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))

  const counts0 = await p.page.evaluate(() => ({
    subjectCards: document.querySelectorAll('.kb-subject-card').length,
    chapters: document.querySelectorAll('.kb-chapter').length,
    emptyChapters: document.querySelectorAll('.kb-chapter.is-empty').length,
    kpRows: document.querySelectorAll('.kb-kp').length,
    chipCount: document.querySelectorAll('.kb-chip').length,
    firstCardName: document.querySelector('.kb-subject-name')?.innerText?.trim(),
    firstCardMeta: document.querySelector('.kb-subject-meta')?.innerText?.trim(),
    dueItems: document.querySelectorAll('.kb-due-item').length,
    weakItems: document.querySelectorAll('.kb-weak-item').length,
    covRows: document.querySelectorAll('.kb-cov-table tbody tr').length,
    stats: [...document.querySelectorAll('.kb-stat')].map(e => e.innerText.replace(/\s+/g, ' ')),
  }))
  log('首屏 DOM 统计:', counts0)

  // 逐科目卡片的 kp 数
  const cardInfo = await p.page.evaluate(() => [...document.querySelectorAll('.kb-subject-card')].map(c => ({
    name: c.querySelector('.kb-subject-name')?.innerText?.trim(),
    meta: c.querySelector('.kb-subject-meta')?.innerText?.trim(),
    chapters: c.querySelectorAll('.kb-chapter').length,
    emptyCh: c.querySelectorAll('.kb-chapter.is-empty').length,
    visibleKp: c.querySelectorAll('.kb-kp').length,
  })))
  log('各科目卡片:', cardInfo)

  // 交互1：点击"模拟电子技术" chip
  let clicked = null
  for (const label of ['模拟电子技术', '数字电子技术', '其他']) {
    const el = p.page.locator('.kb-chip', { hasText: label }).first()
    if (await el.count()) { await el.click(); clicked = label; break }
  }
  log('点击 chip =>', clicked)
  await p.page.waitForTimeout(2500)
  await shot(p.page, 'kbmap-02-after-chip.png')
  const afterChip = await p.page.evaluate(() => ({
    cards: document.querySelectorAll('.kb-subject-card').length,
    chapters: document.querySelectorAll('.kb-chapter').length,
    kpRows: document.querySelectorAll('.kb-kp').length,
    names: [...document.querySelectorAll('.kb-subject-name')].map(e => e.innerText.trim()),
    firstMeta: document.querySelector('.kb-subject-meta')?.innerText?.trim(),
  }))
  log('点 chip 后:', afterChip)

  // 交互2：展开第一个有数据的章节
  const chBtns = p.page.locator('.kb-chapter:not(.is-empty) .kb-chapter-head')
  const chN = await chBtns.count()
  log('可选非空章节数:', chN)
  let kpAfterExpand = null
  if (chN > 0) {
    await chBtns.first().click()
    await p.page.waitForTimeout(1200)
    kpAfterExpand = await p.page.evaluate(() => ({
      openedKpLists: document.querySelectorAll('.kb-kp-list').length,
      kpRows: document.querySelectorAll('.kb-kp').length,
      sampleKp: [...document.querySelectorAll('.kb-kp')].slice(0, 5).map(k => ({
        name: k.querySelector('.kb-kp-name')?.innerText?.trim(),
        pct: k.querySelector('.kb-kp-pct')?.innerText?.trim(),
      })),
    }))
    log('展开章节后:', kpAfterExpand)
    await shot(p.page, 'kbmap-03-expanded-kp.png')
  }

  // 交互3：点知识点的"会"按钮 / 或复习队列按钮，看是否有反馈与写回
  const beforeProg = await api('/api/review/progress')
  let reviewBtnUsed = null
  const kbMini = p.page.locator('.kb-kp .kb-mini-btn, .kb-due-item .kb-mini-btn')
  if (await kbMini.count()) {
    reviewBtnUsed = await kbMini.first().innerText().catch(() => '?')
    await kbMini.first().click()
    await p.page.waitForTimeout(2500)
  }
  const afterProg = await api('/api/review/progress')
  log('点复习按钮:', reviewBtnUsed, '| reviewed_count 前:', beforeProg.json?.reviewed_count, '后:', afterProg.json?.reviewed_count)
  const toastText = await p.page.evaluate(() => document.body.innerText.match(/已记录[^\n]*|掌握度[^\n]*|记录失败[^\n]*/)?.[0] || null)
  log('toast/反馈文本:', toastText)
  await shot(p.page, 'kbmap-04-review-action.png')

  log('### 结论要点')
  log('- 首屏是否能看到知识点列表:', counts0.kpRows > 0 ? '是' : '否（首屏 kp=0，默认展开的是空章节）')
  log('- 需要先点科目 chip 才能看到 kp:', afterChip.kpRows > 0 || (kpAfterExpand && kpAfterExpand.kpRows > 0))
} finally { await browser.close() }
