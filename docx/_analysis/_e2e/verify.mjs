// 针对性验证脚本：知识地图知识点详情 / 刷题答案【草稿】前缀
// 只读诊断，不修改项目代码
import { launch, openPage, shot, api, dump } from './harness.mjs'

const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : dump(x)).join(' '))
const browser = await launch()

/* ============ A. /kbmap 知识点详情 ============ */
try {
  const p = await openPage(browser, '/kbmap', { waitMs: 4500 })
  log('\n========== A. /kbmap 知识地图 ==========')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, 'failedReq=', p.failedReqs.length, '| api4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))
  const cerr = p.consoleMsgs.filter(m => m.type === 'error'); if (cerr.length) log('CONSOLE-ERR:', cerr.slice(0, 5).map(e => e.text.slice(0, 300)))

  // 是否有"关联知识块/原文摘录/知识块"这类字样（全页文本）
  const kw = await p.page.evaluate(() => {
    const t = document.body.innerText
    return {
      hasYuanwen: /原文/.test(t), hasZhaiLu: /摘录/.test(t), hasZhiShiKuai: /知识块/.test(t),
      hasGuanlian: /关联/.test(t),
      sampleGuanlian: (t.match(/[^\n]{0,20}关联[^\n]{0,30}/g) || []).slice(0, 6),
    }
  })
  log('关键词命中:', kw)

  // 展开一个非空章节
  const chBtns = p.page.locator('.kb-chapter:not(.is-empty) .kb-chapter-head')
  const chN = await chBtns.count()
  log('非空章节数:', chN)
  if (chN > 0) {
    await chBtns.first().click(); await p.page.waitForTimeout(1500)
    const kpN = await p.page.locator('.kb-kp').count()
    log('展开后 .kb-kp 行数:', kpN)
    const beforeLen = await p.page.evaluate(() => document.body.innerText.length)
    const beforeHash = await p.page.evaluate(() => location.hash)
    // 点知识点名称（用户说"点开知识点详情"）
    const nameEl = p.page.locator('.kb-kp-name').first()
    const kpName = await nameEl.innerText().catch(() => '?')
    log('点击的知识点:', kpName)
    await nameEl.click({ force: true }).catch(e => log('click name err', String(e).slice(0, 120)))
    await p.page.waitForTimeout(1800)
    const after = await p.page.evaluate(() => ({
      hash: location.hash,
      len: document.body.innerText.length,
      drawers: document.querySelectorAll('.drawer,[class*=drawer],[class*=modal],[class*=detail]').length,
      drawersDetail: [...document.querySelectorAll('[class*=drawer],[class*=detail]')].map(e => (e.className || '').toString()).slice(0, 10),
    }))
    log('点击知识点名称后:', { hash变化: beforeHash !== after.hash, 文本长度变化: after.len - beforeLen, drawer类元素数: after.drawers, classes: after.drawersDetail })
    await shot(p.page, 'verify-kbmap-01-kp-click.png')

    // 再点整行 .kb-kp
    const rowEl = p.page.locator('.kb-kp').first()
    const b2 = await p.page.evaluate(() => document.body.innerText.length)
    await rowEl.click({ force: true }).catch(e => log('click row err', String(e).slice(0, 120)))
    await p.page.waitForTimeout(1500)
    const a2 = await p.page.evaluate(() => ({ len: document.body.innerText.length, drawers: document.querySelectorAll('.drawer,[class*=drawer],[class*=modal],[class*=detail]').length }))
    log('点击知识点整行后文本长度变化:', a2.len - b2, 'drawer数:', a2.drawers)
    await shot(p.page, 'verify-kbmap-02-row-click.png')
  }
  await p.ctx.close()
} catch (e) { log('A 段异常:', String(e), e.stack?.slice(0, 300)) }

/* ============ A2. /panorama 知识点详情（最接近"点开知识点"的现存实现） ============ */
try {
  const p = await openPage(browser, '/panorama', { waitMs: 4500 })
  log('\n========== A2. /panorama 知识点全景 ==========')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, '| api4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))
  const chBtns = p.page.locator('.kb-chapter:not(.is-empty) .kb-chapter-head')
  if (await chBtns.count()) { await chBtns.first().click(); await p.page.waitForTimeout(1500) }
  const kps = p.page.locator('.pn-kp')
  log('.pn-kp 数:', await kps.count())
  // 收集前 5 个 kp 的"关联题量"文本，并点开第一个
  const listInfo = await p.page.evaluate(() => [...document.querySelectorAll('.pn-kp')].slice(0, 6).map(e => ({
    name: e.querySelector('.kb-kp-name')?.innerText?.trim(),
    freq: e.querySelector('.kb-kp-freq')?.innerText?.trim(),
  })))
  log('知识点及其题量(列表):', listInfo)
  if (await kps.count()) {
    await kps.first().click(); await p.page.waitForTimeout(1200)
    const detail = await p.page.evaluate(() => document.querySelector('.pn-detail')?.innerText?.replace(/\s+/g, ' '))
    log('点开知识点详情面板内容:', detail)
    // 面板里是否含 blob/原文摘录
    log('详情面板是否含"原文/摘录/知识块":', /原文|摘录|知识块/.test(detail || ''))
    await shot(p.page, 'verify-panorama-01-kp-detail.png')
  }
  await p.ctx.close()
} catch (e) { log('A2 段异常:', String(e), e.stack?.slice(0, 300)) }

/* ============ B. /quiz-bank 显示答案（【草稿】检查） ============ */
try {
  const p = await openPage(browser, '/quiz-bank', { waitMs: 4000 })
  log('\n========== B. /quiz-bank 显示答案 ==========')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length)
  const btn = p.page.locator('.question-card button', { hasText: '显示答案' }).first()
  if (await btn.count()) {
    await btn.click(); await p.page.waitForTimeout(900)
    const txt = await p.page.evaluate(() => document.querySelector('.question-card')?.innerText?.replace(/\s+/g, ' '))
    log('显示答案后第一题文本:', txt?.slice(0, 400))
    log('>> 含【草稿】:', /【草稿/.test(txt || ''))
    await shot(p.page, 'verify-quizbank-answer.png')
  } else log('未找到"显示答案"按钮')
  await p.ctx.close()
} catch (e) { log('B 段异常:', String(e), e.stack?.slice(0, 300)) }

/* ============ C. /quiz 刷题全链路（答案+解析原文） ============ */
try {
  const p = await openPage(browser, '/quiz', { waitMs: 4500 })
  log('\n========== C. /quiz 刷题 ==========')
  log('pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length)
  let picked = null
  for (const name of ['数字电子技术', '模拟电子技术', '英语', '政治']) {
    const el = p.page.locator('.qknow-subj', { hasText: name }).first()
    if (await el.count()) { await el.click(); picked = name; break }
  }
  log('选中科目:', picked)
  await p.page.waitForTimeout(1800)
  const whole = p.page.locator('.qknow-head button')
  if (await whole.count()) { await whole.first().click() }
  await p.page.waitForTimeout(3000)
  log('进入答题视图:', await p.page.evaluate(() => !!document.querySelector('.qprac-stem')))
  // 走 3 题，收集所有 reveal 文本
  for (let i = 0; i < 3; i++) {
    const has = await p.page.evaluate(() => !!document.querySelector('.qprac-stem'))
    if (!has) break
    const opts = await p.page.locator('.qopt').count()
    const hasTextInput = await p.page.locator('.qtext-input').count()
    if (opts > 0) {
      await p.page.locator('.qopt').nth(0).click(); await p.page.waitForTimeout(300)
      await p.page.locator('button', { hasText: '提交答案' }).first().click()
    } else if (hasTextInput > 0) {
      await p.page.locator('.qtext-input').fill('测试作答')
      await p.page.locator('button', { hasText: '对照答案' }).first().click()
    }
    await p.page.waitForTimeout(2200)
    const rev = await p.page.evaluate(() => document.querySelector('.qreveal')?.innerText?.replace(/\s+/g, ' '))
    log(`-- 第${i + 1}题 reveal 原文:`, rev?.slice(0, 500))
    log(`   含【草稿】:`, /【草稿/.test(rev || ''))
    await shot(p.page, `verify-quiz-reveal-${i + 1}.png`)
    const next = p.page.locator('button', { hasText: '下一题' })
    if (!(await next.count())) break
    await next.first().click(); await p.page.waitForTimeout(1200)
  }
  await p.ctx.close()
} catch (e) { log('C 段异常:', String(e), e.stack?.slice(0, 300)) }

/* ============ D. 后端接口交叉验证：answer/analysis 含【草稿】条数 ============ */
try {
  log('\n========== D. 后端交叉验证 ==========')
  let count = 0, samples = []
  for (const subj of ['数字电子技术', '模拟电子技术']) {
    const r = await api(`/api/quiz/questions?subject=${encodeURIComponent(subj)}&page=1&page_size=200`)
    const list = r.json?.questions || r.json?.items || []
    for (const q of list) {
      const blob = `${q.answer || ''} || ${q.analysis || ''} || ${q.explanation || ''}`
      if (/【草稿/.test(blob)) { count++; if (samples.length < 5) samples.push({ id: q.id, answer: (q.answer || '').slice(0, 40), analysis: (q.analysis || '').slice(0, 80) }) }
    }
    log(`科目 ${subj}: 返回 ${list.length} 题`)
  }
  log(`含【草稿】的题: ${count} 条 | 样本:`, samples)
  // 字段是否下发
  const r1 = await api('/api/quiz/questions?page=1&page_size=3')
  const first = (r1.json?.questions || r1.json?.items || [])[0]
  log('单题字段(keys):', first ? Object.keys(first) : null)
} catch (e) { log('D 段异常:', String(e)) }

await browser.close()
console.log('\n=== VERIFY DONE ===')
