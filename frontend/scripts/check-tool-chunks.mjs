/**
 * P1（F-13）构建门禁：工具箱「页面自身 chunk ≤ 500KB」。
 *
 * 重库（elk / mathjs / mermaid / graph）按 manualChunks 独立成 vendor chunk，
 * 且只在用户点开对应工具时二次 dynamic import；这里守的是 Tools 页入口 chunk
 * 不被重库代码塞回首屏/页面包（页面包变胖即说明按需加载回退失败）。
 */
import fs from 'node:fs'
import path from 'node:path'

const MAX_BYTES = 500 * 1024
const jsDir = path.resolve(process.cwd(), '..', 'backend-main-fastapi', 'static', 'assets', 'js')

if (!fs.existsSync(jsDir)) {
  console.warn('[chunk-gate] 构建产物目录不存在，跳过 Tools chunk 门禁')
  process.exit(0)
}

const files = fs.readdirSync(jsDir).filter((name) => /^Tools-.*\.js$/.test(name))
if (files.length === 0) {
  console.warn('[chunk-gate] 未找到独立的 Tools chunk，跳过门禁')
  process.exit(0)
}

const violations = files
  .map((name) => ({ name, bytes: fs.statSync(path.join(jsDir, name)).size }))
  .filter(({ bytes }) => bytes > MAX_BYTES)

for (const { name, bytes } of violations) {
  console.error(`[chunk-gate] ${name} = ${(bytes / 1024).toFixed(1)}KB，超过 500KB 上限`)
}
if (violations.length) process.exit(1)

console.log(`[chunk-gate] Tools 页面 chunk 检查通过：${files.map((f) => `${f} ${(fs.statSync(path.join(jsDir, f)).size / 1024).toFixed(1)}KB`).join(', ')}`)
