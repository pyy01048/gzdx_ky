const API='http://127.0.0.1:8000'
const g=async p=>{const r=await fetch(API+p,{headers:{accept:'application/json'}});const t=await r.text();let j=null;try{j=JSON.parse(t)}catch{};return{status:r.status,j,raw:t}}
// 1) 文库条数
const all=await g('/api/documents'); console.log('documents 全部:', Array.isArray(all.j)?all.j.length:all.j)
for(const q of ['?subject_source=ima&stage=%E5%88%9D%E8%AF%95','?stage=%E5%88%9D%E8%AF%95','?subject_source=ima']){
  const r=await g('/api/documents'+q); console.log('documents'+q+':', Array.isArray(r.j)?r.j.length:r.raw.slice(0,120))
}
// 2) 单词
const ws=await g('/api/words/stats'); console.log('words/stats:', ws.raw.slice(0,200))
const decks=await g('/api/words/decks'); console.log('words/decks:', decks.raw.slice(0,400))
const ws1=await g('/api/words/stats?deck_id=1'); console.log('words/stats?deck_id=1:', ws1.raw.slice(0,200))
const due=await g('/api/words/due?limit=5'); console.log('words/due len:', Array.isArray(due.j)?due.j.length:due.raw.slice(0,120))
// 3) 知识结构树
const tree=await g('/api/taxonomy/tree?include_extension=true')
const t=tree.j?.tree||[]
console.log('taxonomy/tree 科目数:', t.length)
for(const s of t) console.log('  ', s.subject, '| kp=', s.knowledge_point_count, '| 章=', s.outline_chapter_count, '| is_core=', s.is_core, '| 有kp章节=', (s.chapters||[]).filter(c=>c.knowledge_point_count>0).length)
// 4) taxonomy/subjects 字段
const sub=await g('/api/taxonomy/subjects'); console.log('taxonomy/subjects 样本:', JSON.stringify(sub.j).slice(0,400))
// 5) quiz 口径
const qs=await g('/api/quiz/stats'); console.log('quiz/stats total/total_questions:', qs.j?.total)
const q1=await g('/api/quiz/questions?page=1&page_size=1'); console.log('quiz/questions total:', q1.j?.total, 'mode:', q1.j?.mode)
