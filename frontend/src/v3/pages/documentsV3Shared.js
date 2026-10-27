/* ==========================================================================
   Aurora v3 · 文档知识库共享层
   · governanceApi：与 legacy docShared.js 完全相同的五个治理端点契约
   · 文档归一化 / 指纹 / 空正文判定 / 知识点响应解析
   仅复用 api/client 的 request / fileUrl，不引入任何 legacy 页面或样式。
   ========================================================================== */
import { fileUrl, request } from '../../api/client'

export const governanceApi = {
  snapshot: (id) => request(`/documents/${id}/snapshot`),
  exportUrl: (id, fmt) => fileUrl(`/documents/${id}/export`, { fmt: fmt || 'md' }),
  archive: (id) => request(`/documents/${id}/archive`, { method: 'POST', body: {} }),
  bulk: (body) => request('/documents/bulk', { method: 'POST', body }),
  scanRoot: (dryRun) => request('/documents/scan-root', { method: 'POST', body: { dry_run: !!dryRun } }),
}

export const ACCEPT = '.pdf,.docx,.doc,.txt,.md'

/* 文件名 + 字节数指纹：同名同大小视为重复 */
export const sigOf = (name, size) => `${String(name || '').trim().toLowerCase()}::${size || 0}`

/* 正文缺失：documents.content 为空。列表与详情都要一眼可见。 */
export const isEmptyBody = (d) => (Number(d?.content_length) || 0) === 0

/* GET /documents/{doc_id}/knowledge-points 返回裸数组（或 {items:[…]}）。
   形状认不出时抛错，由调用方展示失败态 —— 不拿空数组冒充「没有知识点」。 */
export const kpItems = (r) => {
  if (Array.isArray(r)) return r
  if (r == null) return []
  if (Array.isArray(r.items)) return r.items
  throw new Error(`知识点响应形状不认识：${Object.keys(r).join(',') || '空对象'}`)
}

/* /documents 列表响应形态容错 */
export const listItems = (d) => {
  if (Array.isArray(d)) return d
  if (d && Array.isArray(d.documents)) return d.documents
  if (d && Array.isArray(d.items)) return d.items
  return null
}

/* 与 legacy Documents.jsx 的 refresh() 字段映射逐项一致 */
export function normalizeDoc(x = {}) {
  const filename = x.file_name || x.filename || x.name || '未命名文档'
  return {
    id: String(x.id),
    filename,
    file_name: filename,
    doc_type: x.file_type || x.doc_type || 'txt',
    file_type: x.file_type || '',
    size: x.size || 0,
    subject: x.subject || '未分类',
    status: x.index_status === 'indexed' ? 'parsed' : (x.index_status || 'uploaded'),
    // 后端没给日期就是「未知」，不用当前时间冒充上传时间
    uploaded_at: x.created_at || '',
    summary: (x.summary || '').slice(0, 120),
    content_length: x.content_length || 0,
    chunk_count: x.chunk_count || 0,
    has_local_file: !!x.has_local_file,
    local_file_note: x.local_file_note || '',
    chunk_count_raw: x.chunk_count || 0,
    stage: x.stage || '',
    content_type: x.content_type || '',
    subject_source: x.subject_source || '',
    folder_path: x.folder_path || '',
    index_status: x.index_status || '',
  }
}

export const FILE_META = {
  pdf: { label: 'PDF', cls: 'pdf' },
  docx: { label: 'DOC', cls: 'doc' },
  doc: { label: 'DOC', cls: 'doc' },
  md: { label: 'MD', cls: 'md' },
  txt: { label: 'TXT', cls: 'txt' },
}

export function fileMetaOf(d) {
  const key = String(d?.doc_type || d?.file_type || '').toLowerCase()
  const known = FILE_META[key]
  if (known) return { key, ...known }
  return { key: 'other', label: key ? key.slice(0, 3).toUpperCase() : 'FILE', cls: 'other' }
}

export function docStateOf(d) {
  if (isEmptyBody(d)) return { label: '正文缺失', tone: 'danger', empty: true }
  if (d?.status === 'parsed') return { label: '已入库', tone: 'success', empty: false }
  if (d?.status === 'failed') return { label: '入库失败', tone: 'danger', empty: false }
  return { label: '未解析', tone: 'warning', empty: false }
}
