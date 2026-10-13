const API='http://127.0.0.1:8000'
async function get(p){const r=await fetch(API+p,{headers:{accept:'application/json'}});const t=await r.text();let j=null;try{j=JSON.parse(t)}catch{};return{status:r.status,json:j,raw:t}}
// 1) 扫 quiz 题目里的【草稿】
let draft=0,total=0,sample=null
for(let page=1;page<=6;page++){
  const r=await get(`/api/quiz/questions?page=${page}&page_size=100`)
  const qs=r.json?.questions||[]; total+=qs.length
  for(const q of qs){
    const s=JSON.stringify(q)
    if(s.includes('【草稿】')||s.includes('草稿')){draft++; if(!sample)sample={id:q.id,answer:q.answer,content:q.content?.slice(0,80)}}
  }
}
console.log('QUIZ 草稿统计: 扫描',total,'题, 含“草稿”',draft,'题')
if(sample)console.log('  sample:',JSON.stringify(sample).slice(0,400))
// 2) 文档正文
const docs=await get('/api/documents')
const list=docs.json||[]
const parsed=list.find(d=>d.index_status==='parsed'||d.index_status==='indexed'||(d.knowledge_point_count||0)>0)||list[0]
console.log('DOC 选中:',parsed?.id,parsed?.file_name,'status',parsed?.index_status,'kp',parsed?.knowledge_point_count)
const c=await get(`/api/documents/${parsed.id}/content`)
console.log('  /content status',c.status,'len',(c.raw||'').length,'head:',(c.raw||'').slice(0,300).replace(/\n/g,' '))
const cs=await get(`/api/documents/${parsed.id}/chunks`)
const cj=cs.json; console.log('  /chunks status',cs.status, Array.isArray(cj)?`array[${cj.length}]`:typeof cj, JSON.stringify(cj).slice(0,200))
// 3) 知识点详情
const kps=await get('/api/taxonomy/knowledge-points?page=1&page_size=3')
const kp=kps.json?.items?.[0]
console.log('KP 选中:',kp?.id,kp?.name)
const kd=await get(`/api/taxonomy/knowledge-points/${kp.id}`)
console.log('  KP详情 status',kd.status,'keys:',kd.json?Object.keys(kd.json).join(','):'-')
console.log('  raw:',JSON.stringify(kd.json).slice(0,600))
