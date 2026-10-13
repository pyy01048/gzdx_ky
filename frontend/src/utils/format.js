/* 展示层格式化工具：全站只有这一份字节数口径。
   背景：Documents / Library 原先各写一个 fmtSize，一个用 `>` 一个用 `>=`，
   1 MiB 的文件在两个页面分别显示「1024 KB」和「1.0 MB」；Documents 那版还把
   0 字节写成「1 KB」（库里实测有 148 篇空正文文档）。 */

/** 字节 → 人类可读；0 或缺失返回「—」，绝不返回假的 1 KB */
export function fmtBytes(n) {
  const b = Number(n) || 0
  if (b <= 0) return '—'
  if (b >= 1024 * 1024 * 1024) return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
  if (b >= 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  if (b >= 1024) return `${Math.round(b / 1024)} KB`
  return `${b} B`
}
