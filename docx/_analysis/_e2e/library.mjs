import { launch, openPage, shot, api, dump } from './harness.mjs'

const log = (...a) => console.log(a.map(x => typeof x === 'string' ? x : dump(x)).join(' '))
const browser = await launch()
try {
  const p = await openPage(browser, '/library', { waitMs: 4000 })
  await shot(p.page, 'library-01-list.png')
  log('### Library 首屏')
  log('navErr=', p.navErr, 'pageErrors=', p.pageErrors.length, 'consoleErr=', p.consoleMsgs.filter(m => m.type === 'error').length, 'failedReq=', p.failedReqs.length)
  log('api 4xx/5xx:', p.apiCalls.filter(a => a.status >= 400))
  const cerr = p.consoleMsgs.filter(m => m.type === 'error'); if (cerr.length) log('CONSOLE-ERR:', cerr.slice(0, 5))

  const s0 = await p.page.evaluate(() => ({
    rows: document.querySelectorAll('.lb-row').length,
    countText: document.querySelector('.lb-count')?.innerText?.replace(/\s+/g, ' '),
    subjChips: [...document.querySelectorAll('.lb-filterbar .kb-chip')].map(b => b.innerText.replace(/\s+/g, ' ')),
    firstRows: [...document.querySelectorAll('.lb-row')].slice(0, 5).map(r => ({
      name: r.querySelector('.lb-name')?.innerText?.trim(),
      ct: r.querySelector('.lb-ct')?.innerText?.trim(),
      subj: r.querySelector('.lb-subj')?.innerText?.trim(),
      state: r.querySelector('.lb-state')?.innerText?.trim(),
      meta: r.querySelector('.lb-meta')?.innerText?.trim(),
    })),
  }))
  log('首屏:', s0)

  // 与后端比对条数 & 已解析比例
  const docs = await api('/api/documents?subject_source=ima&stage=%E5%88%9D%E8%AF%95')
  const arr = Array.isArray(docs.json) ? docs.json : (docs.json?.documents || docs.json?.items || [])
  const parsed = arr.filter(d => (d.content_length || 0) > 0 || (d.chunk_count || 0) > 0)
  const ctCount = {}; const subjCount = {}
  for (const d of arr) { ctCount[d.content_type || '空'] = (ctCount[d.content_type || '空'] || 0) + 1; subjCount[d.subject || '空'] = (subjCount[d.subject || '空'] || 0) + 1 }
  log(`后端初试 IMA: 总数=${arr.length} 已解析=${parsed.length} 未解析=${arr.length - parsed.length}`)
  log('后端 content_type 分布:', ctCount)
  log('后端 subject 分布:', subjCount)

  // 找一个已解析的文档，按文件名定位并点击
  const target = parsed[0]
  log('目标已解析文档:', target ? { id: target.id, name: target.file_name, len: target.content_length, chunks: target.chunk_count } : null)
  let previewBody = null
  if (target) {
    const row = p.page.locator('.lb-row-head', { hasText: (target.file_name || '').slice(0, 12) }).first()
    const n = await row.count()
    log('定位到目标行:', n)
    if (n) {
      await row.scrollIntoViewIfNeeded().catch(() => {})
      await row.click()
      await p.page.waitForTimeout(2500)
      previewBody = await p.page.evaluate(() => {
        const body = document.querySelector('.lb-preview-body')
        const empty = document.querySelector('.lb-preview-empty')
        const head = document.querySelector('.lb-preview-head')?.innerText?.replace(/\s+/g, ' ')
        return { hasBody: !!body, bodyLen: body ? body.innerText.length : 0, bodyText: body ? body.innerText.slice(0, 300) : null, emptyText: empty?.innerText || null, head }
      })
      log('点击已解析文档后预览:', previewBody)
      await shot(p.page, 'library-02-preview-parsed.png')
    }
  }
  // 再点一个未解析的文档，看是否如实提示
  const unparsed = arr.find(d => !((d.content_length || 0) > 0 || (d.chunk_count || 0) > 0))
  let previewUnparsed = null
  if (unparsed) {
    const row = p.page.locator('.lb-row-head', { hasText: (unparsed.file_name || '').slice(0, 12) }).first()
    if (await row.count()) {
      await row.scrollIntoViewIfNeeded().catch(() => {})
      await row.click()
      await p.page.waitForTimeout(2000)
      previewUnparsed = await p.page.evaluate(() => ({
        hasBody: !!document.querySelector('.lb-preview-body'),
        emptyText: document.querySelector('.lb-preview-empty')?.innerText || null,
      }))
      log('点击未解析文档:', { name: unparsed.file_name, ...previewUnparsed })
      await shot(p.page, 'library-03-preview-unparsed.png')
    }
  }

  // 切到"试题"内容性质，看筛选
  const ctChip = p.page.locator('.lb-filterbar .kb-chip', { hasText: '试题' }).first()
  if (await ctChip.count()) {
    await ctChip.click(); await p.page.waitForTimeout(1500)
    log('点"试题"后条数:', await p.page.locator('.lb-count').innerText())
    await shot(p.page, 'library-04-filter-exercise.png')
  }

  log('### 结论')
  log('- 页面条数 =', s0.rows, '| 后端 =', arr.length, '| 一致:', String(s0.rows) === String(arr.length))
  log('- 已解析文档能否看到 IMA 正文:', previewBody?.bodyLen > 20 ? `能（${previewBody.bodyLen} 字）` : '否/为空')
} finally { await browser.close() }
