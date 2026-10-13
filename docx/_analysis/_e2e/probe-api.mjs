// 后端接口探针：确认各模块真实数据量与字段
const API = 'http://127.0.0.1:8000'
async function get(p) {
  try {
    const r = await fetch(API + p, { headers: { accept: 'application/json' } })
    const t = await r.text()
    let j = null; try { j = JSON.parse(t) } catch {}
    return { p, status: r.status, j, len: t.length }
  } catch (e) { return { p, status: 0, err: String(e.message) } }
}
function count(o) {
  if (o == null) return 'null'
  if (Array.isArray(o)) return `array[${o.length}]`
  if (typeof o === 'object') {
    for (const k of ['total', 'count', 'total_count']) if (k in o) return `${k}=${o[k]}`
    const arrKey = Object.keys(o).find((k) => Array.isArray(o[k]))
    if (arrKey) return `${arrKey}[${o[arrKey].length}]`
    return 'obj{' + Object.keys(o).slice(0, 10).join(',') + '}'
  }
  return String(o).slice(0, 60)
}
const probes = [
  ['文库-documents初试', '/api/documents?subject_source=ima&stage=%E5%88%9D%E8%AF%95'],
  ['文库-documents复试', '/api/documents?subject_source=ima&stage=%E5%A4%8D%E8%AF%95'],
  ['文库-subjects', '/api/documents/subjects'],
  ['知识地图-tree', '/api/taxonomy/tree'],
  ['知识地图-subjects', '/api/taxonomy/subjects'],
  ['知识地图-kps', '/api/taxonomy/knowledge-points?page=1&page_size=50'],
  ['知识地图-coverage', '/api/taxonomy/coverage'],
  ['题库-subjects', '/api/quiz/subjects'],
  ['题库-sections', '/api/quiz/sections'],
  ['题库-questions', '/api/quiz/questions?page=1&page_size=20'],
  ['题库-stats', '/api/quiz/stats'],
  ['题库-modes', '/api/quiz/modes'],
  ['题库-papers', '/api/papers?page=1&page_size=20'],
  ['单词-words', '/api/words?page=1&page_size=20'],
  ['单词-due', '/api/words/due?limit=20'],
  ['单词-decks', '/api/words/decks'],
  ['单词-stats', '/api/words/stats'],
  ['错题-errors', '/api/errors?page=1&page_size=50'],
  ['错题-wrongreasons', '/api/quiz/wrong-reasons'],
  ['错题-weakpoints', '/api/analytics/weak-points'],
  ['错题-overview', '/api/analytics/overview'],
  ['院校-schools', '/api/kaoyan/schools?page=1&page_size=20'],
  ['院校-stats', '/api/kaoyan/stats'],
  ['院校-subjects', '/api/kaoyan/subjects'],
  ['首页-dashboard', '/api/dashboard'],
  ['首页-stats', '/api/dashboard/stats'],
]
for (const [name, p] of probes) {
  const r = await get(p)
  const shape = r.err ? 'ERR ' + r.err : (r.status === 200 ? count(r.j) : 'HTTP ' + r.status)
  console.log(`${String(r.status).padEnd(4)} ${name.padEnd(22)} ${p}`)
  console.log(`      -> ${shape}`)
}
