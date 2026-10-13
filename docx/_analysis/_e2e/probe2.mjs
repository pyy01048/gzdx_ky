// 只读：直接调后端接口，摸清六大模块真实数据形状（不走代理）
const API = 'http://127.0.0.1:8000'
async function get(p) {
  try {
    const r = await fetch(API + p, { headers: { accept: 'application/json' } })
    const t = await r.text()
    let j = null; try { j = JSON.parse(t) } catch {}
    return { p, status: r.status, json: j, raw: t.slice(0, 1200) }
  } catch (e) { return { p, status: 0, err: String(e.message) } }
}
function brief(o) {
  if (Array.isArray(o)) return `array[${o.length}]`
  if (o && typeof o === 'object') return `object{${Object.keys(o).slice(0, 14).join(',')}}`
  return String(o)
}
const paths = [
  '/api/documents',
  '/api/documents/subjects',
  '/api/taxonomy/knowledge-points',
  '/api/quiz/questions?limit=3',
  '/api/quiz/stats',
  '/api/quiz/subjects',
  '/api/words/stats',
  '/api/words/due?limit=3',
  '/api/errors',
  '/api/kaoyan/schools?limit=3',
  '/api/kaoyan/stats',
]
for (const p of paths) {
  const r = await get(p)
  console.log('=====', p, '->', r.status)
  if (r.err) { console.log('  ERR', r.err); continue }
  const j = r.json
  if (j && typeof j === 'object' && Array.isArray(j.items)) {
    console.log('  keys:', Object.keys(j).join(','), '| items:', j.items.length, '| total:', j.total)
    if (j.items[0]) console.log('  item0 keys:', Object.keys(j.items[0]).join(','))
  } else {
    console.log('  ', brief(j))
    console.log('  raw:', r.raw.slice(0, 500))
  }
}
