/* ============================================================
   站内计算工具 · 公共纯函数（无 JSX / 无 React 依赖）
   进制计算器之外的 4 个工具（函数图像 / 公式验算 / LaTeX / 框图）
   共享：剪贴板、下载、数值格式化、表达式编译、数值求根/极值等。
   全部为浏览器本地真实计算，不联网、不造假数据。
   ============================================================ */

/* ---------------- 剪贴板 / 下载 ---------------- */

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      ta.remove()
      return ok
    } catch {
      return false
    }
  }
}

export function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 4000)
}

export function downloadText(filename, text, mime = 'text/plain;charset=utf-8') {
  downloadBlob(filename, new Blob([text], { type: mime }))
}

/* ---------------- 数值格式化 ---------------- */

/** 有效数字裁剪 + 去浮点噪声（1e-16 视为 0）；非有限值返回 em-dash */
export function fmt(v, sig = 6) {
  if (v == null || typeof v === 'string' || Number.isNaN(v)) return '—'
  if (!Number.isFinite(v)) return v > 0 ? '∞' : (v < 0 ? '-∞' : '—')
  if (v === 0 || Math.abs(v) < 1e-15) return '0'
  const abs = Math.abs(v)
  if (abs >= 1e12 || abs < 1e-9) return v.toExponential(Math.max(1, sig - 3))
  let s = v.toPrecision(sig)
  if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '')
  return s
}

export function clamp(v, lo, hi) {
  return v < lo ? lo : (v > hi ? hi : v)
}

/** 坐标轴刻度步长：1/2/5 × 10^k */
export function niceStep(range, targetTicks = 8) {
  if (!(range > 0) || !Number.isFinite(range)) return 1
  const raw = range / targetTicks
  const mag = 10 ** Math.floor(Math.log10(raw))
  const norm = raw / mag
  const step = norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10
  return step * mag
}

/* ---------------- 表达式编译（mathjs 由调用方注入） ---------------- */

const RESERVED = new Set(['pi', 'e', 'i', 'tau', 'phi', 'true', 'false', 'null', 'Infinity'])

/** mathjs AST 节点 → 自由变量名（排除函数名与常量；v15 起 SymbolNode 用 .name） */
export function nodeSymbols(node) {
  const fnNames = new Set(node.filter((n) => n.isFunctionNode).map((n) => n.fn && n.fn.name).filter(Boolean))
  const syms = node.filter((n) => n.isSymbolNode).map((n) => n.name)
    .filter((s) => s && !fnNames.has(s) && !RESERVED.has(s))
  return Array.from(new Set(syms))
}

/** 编译 y=f(自由变量) 表达式；返回 { ok, evaluate(scope)|message, symbols } */
export function compileWith(math, expr) {
  const src = String(expr || '').trim()
  if (!src) return { ok: false, message: '表达式为空' }
  try {
    const node = math.parse(src)
    const code = node.compile()
    return {
      ok: true,
      symbols: nodeSymbols(node),
      evaluate(scope) {
        try {
          const v = code.evaluate(scope || {})
          return typeof v === 'number' ? v : (typeof v === 'bigint' ? Number(v) : NaN)
        } catch {
          return NaN
        }
      },
    }
  } catch (err) {
    return { ok: false, message: err?.message || '表达式无法解析' }
  }
}

/* ---------------- 数值求根 / 极值（供函数图像 & 解方程共用） ---------------- */

/** 二分法：f(a)、f(b) 异号；返回 NaN 表示失败 */
export function bisect(f, a, b, tol = 1e-12, maxIter = 200) {
  let fa = f(a)
  let fb = f(b)
  if (!Number.isFinite(fa) || !Number.isFinite(fb) || fa * fb > 0) return NaN
  if (fa === 0) return a
  if (fb === 0) return b
  for (let i = 0; i < maxIter; i += 1) {
    const m = (a + b) / 2
    const fm = f(m)
    if (!Number.isFinite(fm)) return NaN
    if (fm === 0 || (b - a) / 2 < tol) return m
    if (fa * fm < 0) { b = m; fb = fm } else { a = m; fa = fm }
  }
  return (a + b) / 2
}

function continuityOk(f, x, span, cap) {
  const h = Math.max(span * 1e-7, 1e-12)
  const y = f(x)
  const yl = f(x - h)
  const yr = f(x + h)
  if (![y, yl, yr].every(Number.isFinite)) return false
  return Math.abs(yl - y) < cap && Math.abs(yr - y) < cap
}

/**
 * 在 [x0,x1] 上扫描 f 的符号变化并二分细化，得到数值零点。
 * cap：|f| 超过该值的变号视为极点/断点，不作为零点（tan、1/x 等）。
 * 返回 { roots:number[], truncated:boolean }
 */
export function findSignChangeRoots(f, x0, x1, opts = {}) {
  const n = opts.samples || 1200
  const cap = opts.cap ?? Number.MAX_SAFE_INTEGER
  const maxOut = opts.max ?? 40
  const roots = []
  let truncated = false
  let prevX = x0
  let prevY = f(x0)
  for (let i = 1; i <= n; i += 1) {
    const x = x0 + ((x1 - x0) * i) / n
    const y = f(x)
    if (Number.isFinite(prevY) && Number.isFinite(y) && prevY * y <= 0 && Math.abs(prevY) <= cap && Math.abs(y) <= cap) {
      const r = bisect(f, prevX, x)
      if (Number.isFinite(r) && Math.abs(f(r)) <= Math.max(cap, 1) && continuityOk(f, r, x1 - x0, cap)) {
        if (!roots.some((q) => Math.abs(q - r) <= (x1 - x0) * 1e-7)) {
          roots.push(r)
          if (roots.length >= maxOut) { truncated = true; return { roots, truncated } }
        }
      }
    }
    prevX = x
    prevY = y
  }
  return { roots, truncated }
}

/** 数值导数（中心差商） */
export function numDeriv(f, x, h) {
  return (f(x + h) - f(x - h)) / (2 * h)
}

/**
 * 在 [x0,x1] 上求 f 的局部极值：对数值导数做变号扫描 + 二分。
 * 返回 { points:[{x,y,kind:'max'|'min'}], truncated }
 */
export function findLocalExtrema(f, x0, x1, opts = {}) {
  const span = x1 - x0
  const n = opts.samples || 1200
  const cap = opts.cap ?? Number.MAX_SAFE_INTEGER
  const maxOut = opts.max ?? 40
  const h = Math.max(span * 1e-7, 1e-12)
  const d = (x) => numDeriv(f, x, h)
  const points = []
  let truncated = false
  let prevX = x0
  let prevD = d(x0)
  for (let i = 1; i <= n; i += 1) {
    const x = x0 + (span * i) / n
    const dv = d(x)
    if (Number.isFinite(prevD) && Number.isFinite(dv) && prevD * dv < 0) {
      const r = bisect(d, prevX, x, Math.max(span * 1e-12, 1e-13))
      if (Number.isFinite(r)) {
        const y = f(r)
        if (Number.isFinite(y) && Math.abs(y) <= cap && continuityOk(f, r, span, cap)) {
          const dd = (f(r + h) - 2 * y + f(r - h)) / (h * h)
          const kind = dd > 0 ? 'min' : dd < 0 ? 'max' : null
          if (kind && !points.some((p) => Math.abs(p.x - r) <= span * 1e-6)) {
            points.push({ x: r, y, kind })
            if (points.length >= maxOut) { truncated = true; return { points, truncated } }
          }
        }
      }
    }
    prevX = x
    prevD = dv
  }
  return { points, truncated }
}

/** 可复现随机数（mulberry32），供恒等式随机采样核验 */
export function makePRNG(seed = 20261121) {
  let a = seed >>> 0
  return () => {
    a += 0x6d2b79f5
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
