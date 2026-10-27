import fs from 'node:fs'
import path from 'node:path'

/* ------------------------------------------------------------------ *
 * api/client.js 导出面的静态清单（供测试装配 mock 用，不是用例）
 *
 * 为什么必须从源码解析，而不是在测试里手写一份清单：
 * 手写清单会随 client.js 演进漏项。漏掉的方法在 mock 分组里是 undefined，
 * 页面一调用就抛 `xxx is not a function` —— 于是「后端全挂」守卫测的并不是
 * 离线，而是一个假 TypeError，页面真崩了也照样绿。
 *
 * 两类方法要分开对待：
 *   network —— 方法体里出现 request( / fetch(，真的会打后端，离线守卫要覆盖
 *   builder —— 只拼 URL（fileUrl 之类），不发请求，必须保留真实实现，
 *              否则被守卫 sweep 成 reject 后，页面把它当字符串用会同步抛错。
 * ------------------------------------------------------------------ */

// jsdom 下 import.meta.url 不是 file: 协议，用进程 cwd（= frontend/）定位源码
const CLIENT = path.resolve(process.cwd(), 'src', 'api', 'client.js')

const GROUP_RE = /^export const (\w+) = \{/
const METHOD_RE = /^\s{2}(?:async\s+)?(\w+):\s*/
const NETWORK_RE = /\b(?:request|fetch)\(/

/** @returns {{ network: Array<[string, string]>, builders: Map<string, Set<string>> }} */
export function apiSurface() {
  const lines = fs.readFileSync(CLIENT, 'utf8').split('\n')
  const network = []
  const builders = new Map()

  let group = null
  for (let i = 0; i < lines.length; i++) {
    const head = lines[i].match(GROUP_RE)
    if (head) { group = head[1]; continue }
    if (!group) continue
    if (/^\}/.test(lines[i])) { group = null; continue }

    const m = lines[i].match(METHOD_RE)
    if (!m) continue
    // 收集该方法声明到下一个方法/分组结束之间的整个方法体
    let body = lines[i].slice(m[0].length)
    for (let j = i + 1; j < lines.length; j++) {
      if (/^\}/.test(lines[j]) || METHOD_RE.test(lines[j])) break
      body += `\n${lines[j]}`
    }
    if (NETWORK_RE.test(body)) network.push([group, m[1]])
    else {
      if (!builders.has(group)) builders.set(group, new Set())
      builders.get(group).add(m[1])
    }
  }
  return { network, builders }
}
