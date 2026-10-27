import { describe, it, expect, vi } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/* ------------------------------------------------------------------ *
 * api/client.js 形参 arity 守卫
 *
 * 实测踩过的坑（2026-10-17）：QuizYear.jsx 传
 *   quizApi.years({ source_kind: sk })
 * 而 client 里写的是 `years: () => request('/quiz/years')` —— 零形参，
 * 实参被静默丢掉。后端明明支持 source_kind，页面注释还专门解释「带上
 * source_kind 避免教材题 Tab 里显示真题套卷」，实际那个筛选从未生效。
 * 这类 bug 页面测试发现不了：mock 掉 client 之后，页面确实"传了参数"。
 *
 * 本测试用源码静态比对封住这一类：调用点传 N 个实参、client 只声明 M<N 个
 * 形参 ⇒ 一定有人被丢掉。只扫单行调用（跨行调用留给具体契约用例）。
 * ------------------------------------------------------------------ */

// vitest 的 import.meta.url 在 jsdom 下不是 file: 协议，用进程 cwd（= frontend/）定位源码
const SRC = path.resolve(process.cwd(), 'src')
const CLIENT = path.join(SRC, 'api', 'client.js')

function listFiles(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) listFiles(p, out)
    else if (/\.(jsx|js)$/.test(e.name)) out.push(p)
  }
  return out
}

/** client.js 里每个 `xxxApi.method` 声明了几个形参 */
function declaredParams() {
  const table = new Map()
  let cur = null
  fs.readFileSync(CLIENT, 'utf8').split('\n').forEach((line, i) => {
    const head = line.match(/^export const (\w+) = \{/)
    if (head) { cur = head[1]; return }
    if (/^\}/.test(line)) { cur = null; return }
    if (!cur) return
    const m = line.match(/^\s*(\w+):\s*\(([^)]*)\)\s*=>\s*request\(/)
    if (!m) return
    const args = m[2].split(',').map((s) => s.trim()).filter(Boolean)
    table.set(`${cur}.${m[1]}`, { count: args.length, line: i + 1 })
  })
  return table
}

/** 数顶层逗号（字符串/嵌套括号里的不算） */
function argCount(inner) {
  if (!inner.trim()) return 0
  let depth = 0, n = 1, str = null
  for (let k = 0; k < inner.length; k++) {
    const c = inner[k]
    if (str) {
      if (c === str && inner[k - 1] !== '\\') str = null
      continue
    }
    if (c === '"' || c === "'" || c === '`') { str = c; continue }
    if (c === '(' || c === '[' || c === '{') depth += 1
    else if (c === ')' || c === ']' || c === '}') depth -= 1
    else if (c === ',' && depth === 0) n += 1
  }
  return n
}

describe('client.js 不静默丢弃调用方参数', () => {
  const table = declaredParams()
  const violations = []

  for (const file of listFiles(SRC)) {
    if (path.resolve(file) === path.resolve(CLIENT)) continue
    fs.readFileSync(file, 'utf8').split('\n').forEach((line, idx) => {
      for (const [key, info] of table) {
        const at = line.indexOf(`${key}(`)
        if (at < 0) continue
        // 从声明的左括号之后开始，depth=1 表示正在实参列表里
        let j = at + key.length + 1
        let depth = 1
        let inner = ''
        for (; j < line.length; j++) {
          const c = line[j]
          if (c === '(') depth += 1
          else if (c === ')') { depth -= 1; if (depth === 0) break }
          if (depth >= 1) inner += c
        }
        const n = argCount(inner)
        if (n > info.count) {
          violations.push(
            `${path.relative(SRC, file)}:${idx + 1} 传 ${n} 个实参，` +
            `但 client.js:${info.line} ${key} 只声明 ${info.count} 个形参 —— 参数会被丢掉`,
          )
        }
      }
    })
  }

  it('所有调用点传的实参数量都不超过 client 声明的形参数量', () => {
    // 先确认扫描器真的抓到了东西：client.js 结构一改（比如换成多行写法）
    // 这张表就会变空，那条断言会退化成永真。
    expect(table.size, '没从 client.js 解析出任何方法，扫描器已失效').toBeGreaterThan(100)
    expect(violations, `client 静默丢参数：\n${violations.join('\n')}`).toEqual([])
  })

  it('被页面带参调用的三个 quiz 端点确实收下了 params', () => {
    for (const key of ['quizApi.years', 'quizSectionApi.weakPoints', 'quizSectionApi.wrongReasons']) {
      expect(table.get(key), `${key} 没在 client.js 里登记`).toBeTruthy()
      expect(table.get(key).count, `${key} 还是零形参，调用方的 params 会被丢掉`).toBe(1)
    }
  })

  it('quizApi.years 的 source_kind 真的落到 query string 上', async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: vi.fn().mockResolvedValue({ years: [] }),
    })
    vi.stubGlobal('fetch', spy)
    try {
      const { quizApi } = await import('../api/client')
      await quizApi.years({ source_kind: 'textbook' })
      expect(spy.mock.calls[0][0]).toBe('/api/quiz/years?source_kind=textbook')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
