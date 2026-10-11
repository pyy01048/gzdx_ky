import mammoth from 'mammoth'

/* 批次2-7（P2-5）：移除 pdfjs-dist 的静态顶层导入。
   pdfjs 体积大（≈800KB），改为仅在 parsePdf() 内动态 import（见下方），
   使其可单独分包、不被打进首屏主包；mammoth（docx）保留静态导入。 */

/* ============================================================
   文档解析层：PDF / DOCX / MD / TXT → 纯文本
   供「任务文档导入」「AI 辅助阅读」等场景复用
   ============================================================ */

export function fileExt(name = '') {
  const m = /\.([a-zA-Z0-9]+)$/.exec(name || '')
  return m ? m[1].toLowerCase() : ''
}

export function isSupported(name = '') {
  return ['pdf', 'docx', 'md', 'txt', 'markdown'].includes(fileExt(name))
}

export async function parseDocument(file) {
  const ext = fileExt(file.name)
  if (ext === 'pdf') return parsePdf(file)
  if (ext === 'docx') return parseDocx(file)
  // md / txt / markdown：直接读文本
  return (await file.text()) || ''
}

async function parsePdf(file) {
  // 仅在真正解析 PDF 时引入 pdfjs，降低首屏主包体积
  const pdfjsLib = await import('pdfjs-dist')
  const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
  pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl
  const buf = await file.arrayBuffer()
  const pdf = await pdfjsLib.getDocument({ data: buf }).promise
  let text = ''
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i)
    const content = await page.getTextContent()
    const line = content.items.map((it) => ('str' in it ? it.str : '')).join(' ')
    text += line + '\n'
  }
  return text.replace(/\s*\n\s*/g, '\n').trim()
}

async function parseDocx(file) {
  const buf = await file.arrayBuffer()
  const result = await mammoth.extractRawText({ arrayBuffer: buf })
  return (result.value || '').replace(/\s*\n\s*/g, '\n').trim()
}

export default { parseDocument, fileExt, isSupported }
