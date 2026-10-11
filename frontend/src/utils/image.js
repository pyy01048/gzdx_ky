/* ============================================================
   图片工具：手机拍照 → 纠偏 → 压缩 → 上传 OCR

   手机场景的三个真实坑（桌面端不会遇到）：
   1. **EXIF 方向**：手机竖拍的照片像素其实是横的，方向信息存在 EXIF 里。
      用 canvas 直接画会得到躺着/倒着的图，OCR 基本认不出。
      解法：用 createImageBitmap(file, {imageOrientation:'from-image'})，
      浏览器会按 EXIF 自动摆正；不支持时回退到 <img> + 新解码路径。
   2. **HEIC/HEIF**：iPhone 默认格式，Chrome/Edge/Firefox 都解不了。
      本模块会明确识别并给出可操作提示，而不是抛一个看不懂的错。
   3. **超大分辨率**：现在手机动辄 4000×3000、单张 5-8MB，
      直接上传又慢又容易超时，必须先压到合理尺寸。
   ============================================================ */

/** 是否 HEIC/HEIF（iPhone 默认格式，浏览器普遍不支持解码） */
export function isHeic(file) {
  const name = (file?.name || '').toLowerCase()
  const type = (file?.type || '').toLowerCase()
  return /\.(heic|heif)$/.test(name) || type.includes('heic') || type.includes('heif')
}

/** 是否图片类文件（含 HEIC，由调用方决定如何处理） */
export function isImageFile(file) {
  if (!file) return false
  const type = (file.type || '').toLowerCase()
  return type.startsWith('image/') || isHeic(file)
}

/**
 * 把 File/Blob 解码成 ImageBitmap 或 HTMLImageElement，并按 EXIF 摆正。
 * @returns {Promise<{source: CanvasImageSource, width: number, height: number}>}
 */
async function decodeOriented(file) {
  // 首选：createImageBitmap 支持 imageOrientation，效率高且能读 EXIF
  if (typeof createImageBitmap === 'function') {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
      return { source: bmp, width: bmp.width, height: bmp.height }
    } catch {
      // 某些浏览器不支持 imageOrientation 选项，退回普通解码
      try {
        const bmp = await createImageBitmap(file)
        return { source: bmp, width: bmp.width, height: bmp.height }
      } catch {
        /* 继续走 <img> 兜底 */
      }
    }
  }
  // 兜底：<img> 解码（现代浏览器对 <img> 默认会应用 EXIF 方向）
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise((resolve, reject) => {
      const el = new Image()
      el.onload = () => resolve(el)
      el.onerror = () => reject(new Error('图片解码失败'))
      el.src = url
    })
    return { source: img, width: img.naturalWidth, height: img.naturalHeight, _revoke: url }
  } catch (e) {
    URL.revokeObjectURL(url)
    throw e
  }
}

/**
 * 手机拍照/相册图片 → 纠正方向 + 压缩 → dataURL
 *
 * @param {File} file
 * @param {object} opts
 *   maxSide  最长边上限（默认 1800，足够 OCR；再大只是浪费带宽）
 *   quality  JPEG 质量（默认 0.85）
 *   grayscale 是否转灰度（OCR 前处理，可提升对比度不高的照片命中率）
 * @returns {Promise<{dataUrl: string, width: number, height: number, bytes: number}>}
 */
export async function fileToCompressedDataUrl(file, { maxSide = 1800, quality = 0.85, grayscale = false } = {}) {
  if (!file) throw new Error('没有选择图片')
  if (isHeic(file)) {
    throw new Error(
      'HEIC/HEIF 格式（iPhone 默认）浏览器无法解码。' +
      '请在手机「设置 → 相机 → 格式」改为「兼容性最佳」，' +
      '或拍照时用微信/QQ 发送一次再保存为 JPG。'
    )
  }

  const { source, width: sw, height: sh, _revoke } = await decodeOriented(file)

  let width = sw
  let height = sh
  if (!width || !height) throw new Error('图片尺寸读取失败')

  // 只在超过上限时缩小；小图不放大（放大不会增加信息量，只会变糊）
  if (width > maxSide || height > maxSide) {
    const ratio = Math.min(maxSide / width, maxSide / height)
    width = Math.max(1, Math.round(width * ratio))
    height = Math.max(1, Math.round(height * ratio))
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  // OCR 用白底，避免透明区域变黑导致识别率下降
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, width, height)
  ctx.drawImage(source, 0, 0, width, height)

  if (grayscale) {
    const img = ctx.getImageData(0, 0, width, height)
    const d = img.data
    for (let i = 0; i < d.length; i += 4) {
      // 亮度加权（人眼对绿最敏感）
      const g = (d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114) | 0
      d[i] = d[i + 1] = d[i + 2] = g
    }
    ctx.putImageData(img, 0, 0)
  }

  const dataUrl = canvas.toDataURL('image/jpeg', quality)
  if (_revoke) URL.revokeObjectURL(_revoke)
  if (source.close) try { source.close() } catch { /* ignore */ }

  return { dataUrl, width, height, bytes: Math.round((dataUrl.length - 23) * 3 / 4) }
}

/** dataURL → File（后端 OCR 接口要 multipart 文件） */
export function dataUrlToFile(dataUrl, filename = 'photo.jpg') {
  const [head, body] = dataUrl.split(',')
  const mime = /:(.*?);/.exec(head)?.[1] || 'image/jpeg'
  const bin = atob(body)
  const arr = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  return new File([arr], filename, { type: mime })
}

/**
 * 处理一批文件（相册多选 / 连拍），逐个压缩并回传进度。
 * 单个失败不影响其余，最后汇总错误。
 */
export async function compressBatch(files, onProgress, opts) {
  const results = []
  const errors = []
  const list = Array.from(files || [])
  for (let i = 0; i < list.length; i++) {
    try {
      const r = await fileToCompressedDataUrl(list[i], opts)
      results.push({ name: list[i].name, ...r })
    } catch (e) {
      errors.push({ name: list[i].name, message: e.message })
    }
    if (onProgress) onProgress(i + 1, list.length)
  }
  return { results, errors }
}

export default {
  fileToCompressedDataUrl,
  dataUrlToFile,
  compressBatch,
  isHeic,
  isImageFile,
}
