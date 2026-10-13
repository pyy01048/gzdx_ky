import { launch, openPage, shot, api, dump } from './harness.mjs'

const browser = await launch()
try {
  const r = await openPage(browser, '/library', { shot: 'smoke-library.png', waitMs: 3000 })
  await shot(r.page, 'smoke-library.png')
  console.log('=== NAV ===', r.url, 'navErr=', r.navErr)
  console.log('=== STATE ===', dump(r.state))
  console.log('=== CONSOLE(err/warn) ===', dump(r.consoleMsgs.slice(0, 20)))
  console.log('=== PAGE ERRORS ===', dump(r.pageErrors.slice(0, 10)))
  console.log('=== FAILED REQS ===', dump(r.failedReqs.slice(0, 10)))
  console.log('=== API CALLS ===', dump(r.apiCalls.slice(0, 20)))
  console.log('=== API PROBE /api/library/documents ===', dump(await api('/api/library/documents')))
} finally {
  await browser.close()
}
