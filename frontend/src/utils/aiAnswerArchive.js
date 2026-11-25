import { ukey } from './userKeys'

const ARCHIVE_KEY = 'kaoyan-ai-answer-archive-v1'
const MAX_RECORDS = 80

export function saveAiAnswer(record) {
  if (!record?.id) return null
  try {
    const raw = localStorage.getItem(ukey(ARCHIVE_KEY))
    const parsed = raw ? JSON.parse(raw) : []
    const list = Array.isArray(parsed) ? parsed : []
    const next = [{
      id: record.id,
      question: String(record.question || '').slice(0, 4000),
      answer: String(record.answer || '').slice(0, 30000),
      engine: String(record.engine || ''),
      model: String(record.model || ''),
      elapsedMs: record.elapsedMs ?? null,
      rag: record.rag ?? null,
      degraded: !!record.degraded,
      citations: Array.isArray(record.citations)
        ? record.citations.slice(0, 20).map((c) => ({
          title: String(c.title || c.source || '知识片段'),
          source: String(c.source || ''),
          subject: String(c.subject || ''),
          docId: c.doc_id ?? c.document_id ?? null,
          chunkId: c.chunk_id ?? null,
          score: c.score ?? null,
          content: String(c.content || '').slice(0, 4000),
        }))
        : [],
      createdAt: Date.now(),
    }, ...list.filter((item) => item?.id !== record.id)].slice(0, MAX_RECORDS)
    localStorage.setItem(ukey(ARCHIVE_KEY), JSON.stringify(next))
    return record.id
  } catch {
    return null
  }
}

export function readAiAnswer(id) {
  if (!id) return null
  try {
    const raw = localStorage.getItem(ukey(ARCHIVE_KEY))
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list.find((item) => item?.id === id) || null : null
  } catch {
    return null
  }
}
