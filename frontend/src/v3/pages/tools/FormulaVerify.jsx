/**
 * 公式验算器（浏览器本地真实计算，不联网、无假数据）
 * 七个模式：恒等式核验 / 求导(高阶) / 极限(数值逼近) / 定积分(自适应辛普森) /
 *           泰勒展开 / 矩阵(行列式·逆·rref·特征值·解 Ax=b) / 解方程(数值根)
 * - 符号计算走 mathjs（derivative / simplify / toTex），数值算法本文件内实现并如实标注精度与适用范围
 * - 矩阵初等变换用分数域精确运算（mathjs Fraction），行列式/秩/解集为精确值
 * - 特征值：Faddeev–LeVerrier 求特征多项式 + 拉盖尔法复数求根，附迹/行列式一致性校验
 * - 结论诚实：数值方法明说「数值核验，非符号证明」，超出范围（符号积分、区间外根）直接拒答或声明边界
 */
import { useMemo, useState } from 'react'
import * as math from 'mathjs'
import { Button, Chip, Input, Segmented, Textarea, toastOk } from '../../ui'
import { Check, ChevronDown, Copy, PlayCircle, Warning } from '../../icons'
import { ToolShell, Steps, Tex, FieldRow } from './toolsShared'
import '../../styles/tools-suite-v3.css'
import { compileWith, copyText, findSignChangeRoots, fmt, makePRNG, nodeSymbols } from './toolUtils'

/* ============================== 公共小件 ============================== */

function ErrLine({ msg }) {
  return msg ? <div className="v3-tools-error">{msg}</div> : null
}

function OkLine({ children }) {
  return <div className="v3-tv-ok">{children}</div>
}

function TexRow({ label, tex, mono }) {
  return (
    <div className="v3-tv-row">
      <span className="v3-tv-row__label">{label}</span>
      <span className="v3-tv-row__value">{tex ? <Tex tex={tex} /> : <code>{mono}</code>}</span>
    </div>
  )
}

function useCompile(expr) {
  return useMemo(() => compileWith(math, expr), [expr])
}

/** 表达式 → LaTeX（失败回退原文） */
function exprTex(src) {
  try {
    return math.parse(src).toTex()
  } catch {
    return String(src)
  }
}

/** 求 n 阶符号导数，逐步返回 [{order, node, simplifiedTex, simplifiedStr}] */
function derivativeSteps(src, variable, order) {
  const steps = []
  let node = math.parse(src)
  steps.push({ order: 0, tex: node.toTex(), str: node.toString({ parenthesis: 'all' }) })
  for (let k = 1; k <= order; k += 1) {
    node = math.derivative(node, variable)
    let simp = node
    try { simp = math.simplify(node) } catch { /* 保留未化简形式 */ }
    steps.push({ order: k, tex: simp.toTex(), str: simp.toString({ parenthesis: 'all' }) })
  }
  return steps
}

/* ============================== 恒等式核验 ============================== */

function IdentityPanel() {
  const [lhs, setLhs] = useState('sin(x)^2 + cos(x)^2')
  const [rhs, setRhs] = useState('1')
  const cl = useCompile(lhs)
  const cr = useCompile(rhs)

  const verdict = useMemo(() => {
    if (!cl.ok || !cr.ok) return null
    const symbols = Array.from(new Set([...cl.symbols, ...cr.symbols]))
    const rnd = makePRNG()
    let checked = 0
    let maxRel = 0
    let counter = null
    for (let i = 0; i < 400 && checked < 60; i += 1) {
      const scope = {}
      symbols.forEach((s) => { scope[s] = (rnd() - 0.5) * 12 })
      const l = cl.evaluate(scope)
      const r = cr.evaluate(scope)
      if (![l, r].every(Number.isFinite)) continue
      checked += 1
      const rel = Math.abs(l - r) / Math.max(1, Math.abs(l), Math.abs(r))
      if (rel > maxRel) maxRel = rel
      if (rel > 1e-9 && !counter) counter = { scope: { ...scope }, l, r, rel }
    }
    return { symbols, checked, maxRel, counter }
  }, [cl, cr])

  const error = (!lhs.trim() || !rhs.trim()) ? '请输入左右两边表达式' : (!cl.ok ? `左边解析失败：${cl.message}` : (!cr.ok ? `右边解析失败：${cr.message}` : ''))

  return (
    <div className="v3-tv-grid">
      <FieldRow label="左边 L"><Input className="v3-tools-mono" value={lhs} onChange={(e) => setLhs(e.target.value)} aria-label="恒等式左边" spellCheck={false} /></FieldRow>
      <FieldRow label="右边 R"><Input className="v3-tools-mono" value={rhs} onChange={(e) => setRhs(e.target.value)} aria-label="恒等式右边" spellCheck={false} /></FieldRow>
      <ErrLine msg={error} />
      {verdict ? (
        verdict.checked < 12 ? (
          <div className="v3-tools-warn">采样区间内仅 {verdict.checked} 个点双方同时有定义，样本太少，无法给出可靠结论（可尝试换元或缩小表达式）。</div>
        ) : verdict.counter ? (
          <div className="v3-tools-error">
            不成立。反例：{Object.entries(verdict.counter.scope).map(([k, v]) => `${k}=${fmt(v, 4)}`).join('，')} 时
            左={fmt(verdict.counter.l, 8)}、右={fmt(verdict.counter.r, 8)}（相对偏差 {fmt(verdict.counter.rel, 3)}）。
          </div>
        ) : (
          <OkLine>
            在 {verdict.checked} 个随机点上左右两边数值一致（最大相对偏差 {fmt(verdict.maxRel, 3)} ≤ 1e-9）。
            {verdict.symbols.length ? `自由变量：${verdict.symbols.join(', ')}。` : ''}
            {' '}注意：这是数值核验，不是符号证明。
          </OkLine>
        )
      ) : null}
      {cl.ok && cr.ok && lhs.trim() && rhs.trim() ? (
        <TexRow label="L − R" tex={`${exprTex(lhs)}-(${exprTex(rhs)})`} />
      ) : null}
    </div>
  )
}

/* ============================== 求导 ============================== */

function DerivativePanel() {
  const [expr, setExpr] = useState('x^3*sin(a*x)')
  const [variable, setVariable] = useState('x')
  const [order, setOrder] = useState(2)
  const [atX, setAtX] = useState('')
  const [paramVals, setParamVals] = useState({})

  const parsed = useMemo(() => {
    if (!expr.trim()) return null
    try {
      const node = math.parse(expr)
      return { symbols: nodeSymbols(node).filter((s) => s !== variable) }
    } catch (err) {
      return { error: err?.message || '解析失败' }
    }
  }, [expr, variable])

  const result = useMemo(() => {
    if (!expr.trim() || parsed?.error) return null
    try {
      return { steps: derivativeSteps(expr, variable, order) }
    } catch (err) {
      return { error: err?.message || '求导失败（该表达式可能不可符号求导）' }
    }
  }, [expr, variable, order, parsed])

  const numericValues = useMemo(() => {
    if (!result?.steps || parsed?.error || !parsed || atX === '') return null
    const x0 = Number(atX)
    if (!Number.isFinite(x0)) return { error: 'x₀ 不是有限数值' }
    const missing = parsed.symbols.filter((s) => !Number.isFinite(Number(paramVals[s])))
    if (missing.length) return { error: `请先给参数 ${missing.join('、')} 赋数值` }
    const scope = { [variable]: x0, ...Object.fromEntries(parsed.symbols.map((s) => [s, Number(paramVals[s])])) }
    const vals = []
    for (const st of result.steps) {
      try {
        const v = math.parse(st.str).evaluate(scope)
        vals.push({ order: st.order, value: Number.isFinite(v) ? v : NaN })
      } catch {
        vals.push({ order: st.order, value: NaN })
      }
    }
    return { values: vals }
  }, [result, parsed, atX, paramVals, variable])

  return (
    <div className="v3-tv-grid">
      <FieldRow label="f(x)">
        <Input className="v3-tools-mono" value={expr} onChange={(e) => setExpr(e.target.value)} aria-label="求导表达式" spellCheck={false} />
      </FieldRow>
      <div className="v3-tv-inline">
        <FieldRow label="对变量"><Input className="v3-tools-mono" style={{ width: 72 }} value={variable} onChange={(e) => setVariable(e.target.value.replace(/[^a-zA-Z]/g, '') || 'x')} aria-label="求导变量" /></FieldRow>
        <FieldRow label="阶数">
          <span className="v3-tv-orders">
            {[1, 2, 3, 4, 5].map((n) => (
              <Chip key={n} as="button" type="button" active={order === n} onClick={() => setOrder(n)}>{n} 阶</Chip>
            ))}
          </span>
        </FieldRow>
      </div>
      <ErrLine msg={parsed?.error ? `解析失败：${parsed.error}` : (result?.error || '')} />
      {result?.steps ? (
        <>
          {result.steps.map((st) => (
            <TexRow key={st.order} label={st.order === 0 ? 'f' : `f⁽${'ⅰⅱⅲⅳⅴ'[st.order - 1]}⁾ =`} tex={st.tex} />
          ))}
          <Steps title="未化简 / 逐步形式" count={result.steps.length}>
            {result.steps.map((st) => (
              <div key={st.order} className="v3-tv-step">
                <strong>{st.order} 阶</strong>
                <code>{st.str}</code>
              </div>
            ))}
          </Steps>
          <div className="v3-tv-inline">
            <FieldRow label="求值点 x₀"><Input className="v3-tools-mono" style={{ width: 96 }} value={atX} onChange={(e) => setAtX(e.target.value)} placeholder="留空不求值" aria-label="导数求值点" /></FieldRow>
            {(parsed?.symbols || []).map((s) => (
              <FieldRow key={s} label={`参数 ${s}`}><Input className="v3-tools-mono" style={{ width: 88 }} value={paramVals[s] ?? ''} onChange={(e) => setParamVals((p) => ({ ...p, [s]: e.target.value }))} aria-label={`参数 ${s} 取值`} /></FieldRow>
            ))}
          </div>
          {numericValues?.error ? <ErrLine msg={numericValues.error} /> : null}
          {numericValues?.values ? (
            <div className="v3-tv-table-wrap">
              <table className="v3-tv-table">
                <thead><tr><th>k</th><th>f⁽ᵏ⁾(x₀)</th></tr></thead>
                <tbody>
                  {numericValues.values.map((v) => <tr key={v.order}><td>{v.order}</td><td>{fmt(v.value, 8)}</td></tr>)}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

/* ============================== 极限（数值） ============================== */

function LimitPanel() {
  const [expr, setExpr] = useState('sin(x)/x')
  const [variable, setVariable] = useState('x')
  const [at, setAt] = useState('0')
  const compiled = useCompile(expr)

  const result = useMemo(() => {
    if (!compiled.ok) return null
    const target = at.trim().toLowerCase().replace('无穷', 'oo').replace('∞', 'oo')
    const isInfinite = ['oo', '+oo', 'inf', '+inf', 'infinity'].includes(target)
    const isNegInf = ['-oo', '-inf', '-infinity'].includes(target)
    const a = Number(target)
    if (!isInfinite && !isNegInf && !Number.isFinite(a)) return { error: '趋近点请填写数值、oo（+∞）或 -oo' }
    const rows = []
    const side = { plus: [], minus: [] }
    if (isInfinite || isNegInf) {
      const sign = isNegInf ? -1 : 1
      for (let k = 2; k <= 12; k += 1) {
        const x = sign * 10 ** k
        const v = compiled.evaluate({ [variable]: x })
        side.plus.push({ x, v })
      }
      rows.push(...side.plus)
    } else {
      for (let k = 1; k <= 8; k += 1) {
        const h = 10 ** -k
        side.plus.push({ d: h, v: compiled.evaluate({ [variable]: a + h }) })
        side.minus.push({ d: h, v: compiled.evaluate({ [variable]: a - h }) })
      }
    }
    const relClose = (u, w) => Number.isFinite(u) && Number.isFinite(w)
      && Math.abs(u - w) <= 1e-6 * Math.max(1, Math.abs(u), Math.abs(w))
    let verdict
    if (isInfinite || isNegInf) {
      const vs = side.plus.map((r) => r.v)
      if (!vs.slice(-3).every(Number.isFinite)) verdict = { kind: 'warn', text: '末端采样点已无定义或溢出，无法判断。' }
      else if (Math.abs(vs[vs.length - 1]) > 1e12 && Math.abs(vs[vs.length - 1]) > Math.abs(vs[vs.length - 3]) * 10) verdict = { kind: 'inf', text: '函数值随 |x|→∞ 持续增大，判断为发散（∞）。' }
      else if (relClose(vs[vs.length - 1], vs[vs.length - 2]) && relClose(vs[vs.length - 2], vs[vs.length - 3])) verdict = { kind: 'ok', text: `数值趋势收敛于 ≈ ${fmt(vs[vs.length - 1], 8)}（注意：sin x / x 之外的振荡型慢收敛请以表格为准）。` }
      else verdict = { kind: 'warn', text: '末端两档采样仍不明显稳定（可能振荡或对数慢收敛），请查看表格自行判断。' }
    } else {
      const p = side.plus.map((r) => r.v)
      const m = side.minus.map((r) => r.v)
      const pOk = p.slice(-2).every(Number.isFinite) && relClose(p[p.length - 1], p[p.length - 2])
      const mOk = m.slice(-2).every(Number.isFinite) && relClose(m[m.length - 1], m[m.length - 2])
      const Lp = p[p.length - 1]
      const Lm = m[m.length - 1]
      if (!p.some(Number.isFinite) && !m.some(Number.isFinite)) verdict = { kind: 'warn', text: '趋近点两侧都无定义（如 ln(x) 在 0⁻），请确认定义域。' }
      else if (!pOk && !mOk) verdict = { kind: 'warn', text: '两侧数值均不稳定（发散或剧烈振荡），无法给出极限值，见表格。' }
      else if (pOk && mOk && relClose(Lp, Lm)) verdict = { kind: 'ok', text: `左右极限一致：lim ≈ ${fmt((Lp + Lm) / 2, 8)}。` }
      else verdict = { kind: 'jump', text: `右极限趋势 ${pOk ? fmt(Lp, 6) : '不稳定'}，左极限趋势 ${mOk ? fmt(Lm, 6) : '不稳定'}，两侧不一致 → 极限不存在（跳跃/发散）。` }
    }
    return { rows, side, verdict, isInfinite: isInfinite || isNegInf, a }
  }, [compiled, at, variable])

  return (
    <div className="v3-tv-grid">
      <FieldRow label="f(x)">
        <Input className="v3-tools-mono" value={expr} onChange={(e) => setExpr(e.target.value)} aria-label="极限表达式" spellCheck={false} />
      </FieldRow>
      <div className="v3-tv-inline">
        <FieldRow label="变量"><Input className="v3-tools-mono" style={{ width: 64 }} value={variable} onChange={(e) => setVariable(e.target.value.replace(/[^a-zA-Z]/g, '') || 'x')} aria-label="极限变量" /></FieldRow>
        <FieldRow label="趋近点（数值 / oo / -oo）">
          <span className="v3-tv-orders">
            <Input className="v3-tools-mono" style={{ width: 96 }} value={at} onChange={(e) => setAt(e.target.value)} aria-label="趋近点" />
            {[['0', '0'], ['1', '1'], ['oo', '+∞'], ['-oo', '-∞']].map(([v, l]) => (
              <Chip key={v} as="button" type="button" active={at === v} onClick={() => setAt(v)}>{l}</Chip>
            ))}
          </span>
        </FieldRow>
      </div>
      <ErrLine msg={!expr.trim() ? '请输入表达式' : (!compiled.ok ? `解析失败：${compiled.message}` : (result?.error || ''))} />
      {result?.verdict ? (
        <>
          {result.verdict.kind === 'ok'
            ? <OkLine>{result.verdict.text}（数值逼近判定，非严格证明）</OkLine>
            : result.verdict.kind === 'inf'
              ? <div className="v3-tools-warn">{result.verdict.text}</div>
              : <div className="v3-tools-warn">{result.verdict.text}</div>}
          <Steps title="双侧逼近数值表" count={result.rows.length || result.side.plus.length + result.side.minus.length} defaultOpen>
            <div className="v3-tv-table-wrap">
              <table className="v3-tv-table">
                <thead><tr><th>{result.isInfinite ? variable : 'h'}</th><th>f（+侧）</th>{result.isInfinite ? null : <th>f（−侧）</th>}</tr></thead>
                <tbody>
                  {(result.isInfinite
                    ? result.side.plus.map((r, i) => <tr key={i}><td>{fmt(r.x, 6)}</td><td>{fmt(r.v, 10)}</td></tr>)
                    : result.side.plus.map((r, i) => (
                      <tr key={i}><td>{fmt(r.d, 4)}</td><td>{fmt(r.v, 10)}</td><td>{fmt(result.side.minus[i]?.v, 10)}</td></tr>
                    )))}
                </tbody>
              </table>
            </div>
          </Steps>
        </>
      ) : null}
    </div>
  )
}

/* ============================== 定积分（自适应辛普森） ============================== */

function adaptiveSimpson(f, a, b, tol, maxDepth = 32) {
  const whole = (f(a) + 4 * f((a + b) / 2) + f(b)) * ((b - a) / 6)
  let nodes = 1
  function rec(l, m, r, fl, fm, fr, wholeV, depth) {
    const lm = (l + m) / 2
    const mr = (m + r) / 2
    const flm = f(lm)
    const fmr = f(mr)
    const left = (fl + 4 * flm + fm) * ((m - l) / 6)
    const right = (fm + 4 * fmr + fr) * ((r - m) / 6)
    const delta = left + right - wholeV
    nodes += 2
    if (depth >= maxDepth || Math.abs(delta) <= 15 * tol) {
      return { val: left + right + delta / 15, err: Math.abs(delta) / 15, ok: depth < maxDepth }
    }
    const L = rec(l, lm, m, fl, flm, fm, left, depth + 1)
    const R = rec(m, mr, r, fm, fmr, fr, right, depth + 1)
    return { val: L.val + R.val, err: L.err + R.err, ok: L.ok && R.ok }
  }
  const res = rec(a, (a + b) / 2, b, f(a), f((a + b) / 2), f(b), whole, 0)
  return { ...res, nodes }
}

function IntegralPanel() {
  const [expr, setExpr] = useState('x^2*exp(-a*x)')
  const [variable, setVariable] = useState('x')
  const [aText, setAText] = useState('0')
  const [bText, setBText] = useState('1')
  const [params, setParams] = useState({ a: '1' })
  const compiled = useCompile(expr)

  const extraSymbols = useMemo(() => {
    if (!compiled.ok) return []
    return compiled.symbols.filter((s) => s !== variable && !['pi', 'e', 'i', 'tau', 'phi'].includes(s))
  }, [compiled, variable])

  const result = useMemo(() => {
    if (!compiled.ok) return null
    const lo = Number(aText)
    const hi = Number(bText)
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { error: '上下限必须是有限数值（无穷限积分暂不支持）' }
    if (lo === hi) return { value: 0, err: 0, nodes: 0, swapped: false }
    const scope = {}
    for (const s of extraSymbols) {
      const v = Number(params[s])
      if (!Number.isFinite(v)) return { error: `请先给参数 ${s} 赋数值` }
      scope[s] = v
    }
    const f = (x) => compiled.evaluate({ [variable]: x, ...scope })
    const N = 201
    for (let i = 0; i <= N; i += 1) {
      const x = lo + ((hi - lo) * i) / N
      if (!Number.isFinite(f(x))) return { error: `被积函数在 x=${fmt(x, 5)} 处无定义/非实数，数值定积分不可靠（暂不支持瑕积分）` }
    }
    const [A, B] = lo < hi ? [lo, hi] : [hi, lo]
    const r1 = adaptiveSimpson(f, A, B, 1e-10)
    const r2 = adaptiveSimpson(f, A, B, 1e-13)
    const diff = Math.abs(r1.val - r2.val)
    return {
      value: (lo < hi ? 1 : -1) * r2.val,
      err: Math.max(r1.err, r2.err, diff),
      nodes: r2.nodes,
      swapped: lo > hi,
      deepOk: r2.ok,
    }
  }, [compiled, aText, bText, params, extraSymbols, variable])

  return (
    <div className="v3-tv-grid">
      <FieldRow label="f(x)">
        <Input className="v3-tools-mono" value={expr} onChange={(e) => setExpr(e.target.value)} aria-label="被积表达式" spellCheck={false} />
      </FieldRow>
      <div className="v3-tv-inline">
        <FieldRow label="变量"><Input className="v3-tools-mono" style={{ width: 64 }} value={variable} onChange={(e) => setVariable(e.target.value.replace(/[^a-zA-Z]/g, '') || 'x')} aria-label="积分变量" /></FieldRow>
        <FieldRow label="下限 a"><Input className="v3-tools-mono" style={{ width: 96 }} value={aText} onChange={(e) => setAText(e.target.value)} aria-label="积分下限" /></FieldRow>
        <FieldRow label="上限 b"><Input className="v3-tools-mono" style={{ width: 96 }} value={bText} onChange={(e) => setBText(e.target.value)} aria-label="积分上限" /></FieldRow>
      </div>
      {extraSymbols.map((s) => (
        <FieldRow key={s} label={`参数 ${s}`}><Input className="v3-tools-mono" style={{ width: 110 }} value={params[s] ?? ''} onChange={(e) => setParams((p) => ({ ...p, [s]: e.target.value }))} aria-label={`参数 ${s}`} /></FieldRow>
      ))}
      <ErrLine msg={!expr.trim() ? '请输入表达式' : (!compiled.ok ? `解析失败：${compiled.message}` : (result?.error || ''))} />
      {result && result.value !== undefined ? (
        <>
          <OkLine>
            ∫ ≈ {fmt(result.value, 10)}
            {result.swapped ? '（已按上下限交换自动变号）' : ''}
            <Tex tex={`\\int_{${aText}}^{${bText}} ${exprTex(expr)}\\, d${variable}`} className="v3-tv-tex-inline" />
          </OkLine>
          <Steps title="精度与过程">
            <TexRow label="误差估计" mono={`≤ ${fmt(result.err, 3)}`} />
            <TexRow label="自适应剖分数" mono={`≈ ${result.nodes} 段（辛普森 1e-13 容差）`} />
            {result.deepOk === false ? <div className="v3-tools-warn">已达最大递归深度仍未满足容差，结果精度可能不足（奇异性/剧烈振荡？）。</div> : null}
            <div className="v3-tools-warn" style={{ background: 'var(--v3-info-container)', color: 'var(--v3-on-primary-container)' }}>
              数值积分（自适应辛普森），仅支持有限区间且区间内需处处有定义；不定积分（符号原函数）不在本工具范围。
            </div>
          </Steps>
        </>
      ) : null}
    </div>
  )
}

/* ============================== 泰勒展开 ============================== */

function TaylorPanel() {
  const [expr, setExpr] = useState('exp(a*x)*cos(x)')
  const [variable, setVariable] = useState('x')
  const [x0, setX0] = useState('0')
  const [order, setOrder] = useState(5)
  const [params, setParams] = useState({ a: '1' })

  const result = useMemo(() => {
    if (!expr.trim()) return null
    const p = Number(x0)
    if (!Number.isFinite(p)) return { error: '展开点 x₀ 需为有限数值' }
    try {
      const node = math.parse(expr)
      const symbols = nodeSymbols(node).filter((s) => s !== variable)
      const missing = Array.from(new Set(symbols)).filter((s) => !Number.isFinite(Number(params[s])))
      if (missing.length) return { needParams: Array.from(new Set(symbols)), error: `请先给参数 ${missing.join('、')} 赋数值` }
      const scope = { [variable]: p, ...Object.fromEntries(Array.from(new Set(symbols)).map((s) => [s, Number(params[s])])) }
      const steps = derivativeSteps(expr, variable, order)
      const coeffs = steps.map((st) => {
        const v = math.parse(st.str).evaluate(scope)
        return { order: st.order, deriv: Number.isFinite(v) ? v : NaN, coeff: Number.isFinite(v) ? v / math.factorial(st.order) : NaN, tex: st.tex }
      })
      const terms = coeffs.filter((c) => Number.isFinite(c.coeff) && Math.abs(c.coeff) > 1e-14)
      const shift = p === 0 ? '' : p > 0 ? `- ${fmt(p, 6)}` : `+ ${fmt(-p, 6)}`
      const baseTex = (k) => (k === 0 ? '' : k === 1 ? `(${variable}${shift})` : `(${variable}${shift})^{${k}}`)
      let polyTex = ''
      terms.forEach((c) => {
        const abs = fmt(Math.abs(c.coeff), 8)
        const body = `${abs}${baseTex(c.order) ? ` ${baseTex(c.order)}` : ''}`
        if (!polyTex) polyTex = (c.coeff < 0 ? '-' : '') + body
        else polyTex += c.coeff < 0 ? ` - ${body}` : ` + ${body}`
      })
      polyTex = `${polyTex || '0'} + \\mathcal{O}(${baseTex(order + 1) ? `(${variable}${shift})^{${order + 1}}` : `(${variable}${shift})`})`
      return { steps, coeffs, polyTex, needParams: Array.from(new Set(symbols)) }
    } catch (err) {
      return { error: err?.message || '展开失败' }
    }
  }, [expr, variable, x0, order, params])

  const copyTex = result?.polyTex || ''

  return (
    <div className="v3-tv-grid">
      <FieldRow label="f(x)">
        <Input className="v3-tools-mono" value={expr} onChange={(e) => setExpr(e.target.value)} aria-label="展开表达式" spellCheck={false} />
      </FieldRow>
      <div className="v3-tv-inline">
        <FieldRow label="变量"><Input className="v3-tools-mono" style={{ width: 64 }} value={variable} onChange={(e) => setVariable(e.target.value.replace(/[^a-zA-Z]/g, '') || 'x')} aria-label="展开变量" /></FieldRow>
        <FieldRow label="展开点 x₀"><Input className="v3-tools-mono" style={{ width: 88 }} value={x0} onChange={(e) => setX0(e.target.value)} aria-label="展开点" /></FieldRow>
        <FieldRow label="阶数">
          <span className="v3-tv-orders">
            {[2, 3, 4, 5, 6, 8, 10].map((n) => <Chip key={n} as="button" type="button" active={order === n} onClick={() => setOrder(n)}>{n}</Chip>)}
          </span>
        </FieldRow>
      </div>
      {(result?.needParams || []).map((s) => (
        <FieldRow key={s} label={`参数 ${s}`}><Input className="v3-tools-mono" style={{ width: 110 }} value={params[s] ?? ''} onChange={(e) => setParams((p) => ({ ...p, [s]: e.target.value }))} aria-label={`参数 ${s}`} /></FieldRow>
      ))}
      <ErrLine msg={result?.error || ''} />
      {result?.coeffs ? (
        <>
          <TexRow label={`T${order}(x)`} tex={result.polyTex} />
          <div className="v3-tv-table-wrap">
            <table className="v3-tv-table">
              <thead><tr><th>k</th><th>f⁽ᵏ⁾(x₀)</th><th>aₖ = f⁽ᵏ⁾(x₀)/k!</th></tr></thead>
              <tbody>
                {result.coeffs.map((c) => (
                  <tr key={c.order}><td>{c.order}</td><td>{fmt(c.deriv, 8)}</td><td>{fmt(c.coeff, 8)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <Steps title="各阶符号导数（化简后）" count={result.steps.length}>
            {result.steps.map((st) => (
              <div key={st.order} className="v3-tv-step"><strong>{st.order} 阶</strong><Tex tex={st.tex} /></div>
            ))}
          </Steps>
          {copyTex ? (
            <Button size="sm" variant="tonal" icon={<Copy size={14} />} onClick={async () => { if (await copyText(copyTex)) toastOk('泰勒多项式 LaTeX 已复制') }}>复制 LaTeX</Button>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

/* ============================== 矩阵 ============================== */

/** 文本 → Fraction 二维数组；支持 "[[1,2],[3,4]]"、"1,2;3,4"、逐行输入 */
function parseFractionMatrix(text) {
  const t = String(text || '').trim()
  if (!t) return { error: '矩阵内容为空' }
  const body = t.replace(/\[/g, '').replace(/\]/g, '')
  const rows = body.split(/[;\n]+/).map((r) => r.trim()).filter(Boolean)
  let frs
  try {
    frs = rows.map((r) => r.split(/[,\s]+/).filter(Boolean).map((cell) => {
      const f = math.fraction(cell)
      if (!f || !Number.isFinite(f.valueOf())) throw new Error(`「${cell}」不是有理数`)
      return f
    }))
  } catch (err) {
    return { error: err?.message || '矩阵元素解析失败（支持整数/小数/分数 1/3）' }
  }
  if (!frs.length || !frs[0].length) return { error: '矩阵为空' }
  const cols = frs[0].length
  if (frs.some((r) => r.length !== cols)) return { error: '各行列数不一致' }
  return { rows: frs, m: frs.length, n: cols }
}

const fIsZero = (f) => f.valueOf() === 0
const fStr = (f) => (typeof f.toFraction === 'function' ? f.toFraction() : String(f))

/** 分数域行最简形（Gauss–Jordan 精确变换） */
function rrefFraction(rows) {
  const A = rows.map((r) => r.slice())
  const m = A.length
  const n = A[0].length
  const pivots = []
  const steps = []
  let r = 0
  for (let c = 0; c < n && r < m; c += 1) {
    let p = -1
    for (let i = r; i < m; i += 1) if (!fIsZero(A[i][c])) { p = i; break }
    if (p < 0) continue
    if (p !== r) { const tmp = A[p]; A[p] = A[r]; A[r] = tmp; steps.push(`交换第 ${p + 1} 行与第 ${r + 1} 行`) }
    const pv = A[r][c]
    if (!pv.equals(math.fraction(1))) {
      A[r] = A[r].map((v) => v.div(pv))
      steps.push(`第 ${r + 1} 行 ÷ ${fStr(pv)}`)
    }
    for (let i = 0; i < m; i += 1) {
      if (i === r || fIsZero(A[i][c])) continue
      const k = A[i][c]
      A[i] = A[i].map((v, j) => v.sub(k.mul(A[r][j])))
      steps.push(`第 ${i + 1} 行 − (${fStr(k)})×第 ${r + 1} 行`)
    }
    pivots.push(c)
    r += 1
  }
  return { matrix: A, pivots, steps, rank: pivots.length }
}

function detFraction(rows) {
  const A = rows.map((r) => r.slice())
  const n = A.length
  let sign = 1
  let acc = math.fraction(1)
  for (let c = 0; c < n; c += 1) {
    let p = -1
    for (let i = c; i < n; i += 1) if (!fIsZero(A[i][c])) { p = i; break }
    if (p < 0) return { value: math.fraction(0), exact: true }
    if (p !== c) { const t = A[p]; A[p] = A[c]; A[c] = t; sign = -sign }
    acc = acc.mul(A[c][c])
    for (let i = c + 1; i < n; i += 1) {
      const k = A[i][c].div(A[c][c])
      A[i] = A[i].map((v, j) => v.sub(k.mul(A[c][j])))
    }
  }
  return { value: sign === 1 ? acc : acc.neg(), exact: true }
}

function matMulNum(A, B) {
  const n = A.length
  const C = Array.from({ length: n }, () => new Array(n).fill(0))
  for (let i = 0; i < n; i += 1) for (let j = 0; j < n; j += 1) {
    let s = 0
    for (let k = 0; k < n; k += 1) s += A[i][k] * B[k][j]
    C[i][j] = s
  }
  return C
}

/** Faddeev–LeVerrier：p(λ)=λⁿ+c₁λⁿ⁻¹+…+cₙ */
function charPoly(A) {
  const n = A.length
  const I = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)))
  const cs = [1]
  let M = I
  for (let k = 1; k <= n; k += 1) {
    if (k > 1) {
      M = matMulNum(A, M)
      for (let i = 0; i < n; i += 1) M[i][i] = M[i][i] + cs[k - 1]
    }
    const AM = matMulNum(A, M)
    let tr = 0
    for (let i = 0; i < n; i += 1) tr += AM[i][i]
    cs.push(-tr / k)
  }
  return cs
}

/* 复数四则（{re,im}）+ 拉盖尔迭代求特征多项式全部根（实系数，复根共轭成对降阶） */
function cAdd(a, b) { return { re: a.re + b.re, im: a.im + b.im } }
function cSub(a, b) { return { re: a.re - b.re, im: a.im - b.im } }
function cMul(a, b) { return { re: a.re * b.re - a.im * b.im, im: a.re * b.im + a.im * b.re } }
function cDiv(a, b) { const d = b.re * b.re + b.im * b.im || 1e-300; return { re: (a.re * b.re + a.im * b.im) / d, im: (a.im * b.re - a.re * b.im) / d } }
function cAbs(a) { return Math.hypot(a.re, a.im) }
function cSqrt(z) {
  const r = Math.hypot(z.re, z.im)
  const re = Math.sqrt(Math.max(0, (r + z.re) / 2))
  const im = Math.sqrt(Math.max(0, (r - z.re) / 2)) * (z.im < 0 ? -1 : 1)
  return { re, im }
}

/** cs：降幂实系数（cs[0]=1）；z：复数 */
function polyEvalC(cs, z) {
  let acc = { re: 0, im: 0 }
  for (const c of cs) acc = cAdd(cMul(acc, z), { re: c, im: 0 })
  return acc
}
function polyDeriv(cs) {
  const n = cs.length - 1
  return cs.slice(0, -1).map((c, i) => c * (n - i))
}

/** 单根拉盖尔迭代（Numerical Recipes 风格），返回 {re,im} */
function laguerreRoot(cs, z0) {
  const n = cs.length - 1
  const d1 = polyDeriv(cs)
  const d2 = polyDeriv(d1)
  let z = { ...z0 }
  for (let iter = 0; iter < 160; iter += 1) {
    const p = polyEvalC(cs, z)
    if (cAbs(p) < 1e-14) return z
    const g = cDiv(polyEvalC(d1, z), p)
    const h = cSub(cMul(g, g), cDiv(polyEvalC(d2, z), p))
    const inner = cMul({ re: n - 1, im: 0 }, cSub(cMul({ re: n, im: 0 }, h), cMul(g, g)))
    const sq = cSqrt(inner)
    const f1 = cAdd(g, sq)
    const f2 = cSub(g, sq)
    const den = cAbs(f1) >= cAbs(f2) ? f1 : f2
    if (cAbs(den) < 1e-300) { z = { re: z.re + 0.35, im: z.im - 0.28 }; continue }
    const dz = cDiv({ re: n, im: 0 }, den)
    z = cSub(z, dz)
    if (cAbs(dz) < 1e-12 * Math.max(1, cAbs(z)) && iter > 4) {
      if (Math.abs(z.im) < 1e-10 * Math.max(1, Math.abs(z.re))) z.im = 0
      return z
    }
  }
  return z
}

/** 实系数多项式除以 (x−z)，z 为实根：一次降阶 */
function deflateLinear(cs, z) {
  const out = [cs[0]]
  for (let k = 1; k < cs.length - 1; k += 1) out.push(cs[k] + z * out[k - 1])
  return out
}
/** 实系数多项式除以 (x−z)(x−z̄) = x² + Px + Q，保持实系数 */
function deflateQuadratic(cs, z) {
  const P = -2 * z.re
  const Q = z.re * z.re + z.im * z.im
  const m = cs.length
  const out = new Array(m - 2).fill(0)
  out[0] = cs[0]
  if (m > 3) out[1] = cs[1] - P * out[0]
  for (let k = 2; k < m - 2; k += 1) out[k] = cs[k] - P * out[k - 1] - Q * out[k - 2]
  return out
}

function eigenvalues(A) {
  const n = A.length
  const cs = charPoly(A)
  const roots = []
  let cur = cs.slice()
  const maxIter = 4 * n + 30
  for (let guard = 0; guard < maxIter && cur.length >= 2; guard += 1) {
    if (cur.length === 2) {
      roots.push({ re: -cur[1] / cur[0], im: 0 })
      break
    }
    const seed = guard % 3 === 0 ? { re: 1.4, im: -0.9 } : guard % 3 === 1 ? { re: -1.1, im: 1.3 } : { re: 0.2, im: -2.1 }
    const z = laguerreRoot(cur, seed)
    if (!Number.isFinite(z.re) || !Number.isFinite(z.im)) return { error: '特征多项式求根未收敛（矩阵病态或过大）' }
    if (Math.abs(z.im) < 1e-9) {
      roots.push({ re: z.re, im: 0 })
      cur = deflateLinear(cur, z.re)
    } else {
      roots.push(z, { re: z.re, im: -z.im })
      cur = deflateQuadratic(cur, z)
    }
    if (cur.length >= 2 && Math.abs(cur[0]) > 1e-14) cur = cur.map((v) => v / cur[0])
  }
  if (roots.length !== n) return { error: `只求到 ${roots.length}/${n} 个特征值（数值病态），建议改用 Octave/SymPy` }
  const tr = A.reduce((s, row, i) => s + row[i], 0)
  const detNum = math.det(A)
  const sumRe = roots.reduce((s, z) => s + z.re, 0)
  let prod = { re: 1, im: 0 }
  roots.forEach((z) => { prod = cMul(prod, z) })
  const checks = [
    `Σλ = ${fmt(sumRe, 8)} vs tr(A) = ${fmt(tr, 8)}`,
    `Πλ = ${fmt(cAbs(prod), 8)} vs |det(A)| = ${fmt(Math.abs(detNum), 8)}`,
  ]
  return { roots, cs, checks }
}

function MatrixPanel() {
  const [aText, setAText] = useState('[1, 2, 3;\n4, 5, 6;\n7, 8, 10]')
  const [bText, setBText] = useState('[6;\n15;\n27]')
  const [out, setOut] = useState(null)

  const run = (op) => {
    const P = parseFractionMatrix(aText)
    if (P.error) { setOut({ error: P.error }); return }
    if (op === 'det') {
      if (P.m !== P.n) { setOut({ error: '行列式要求方阵' }); return }
      if (P.m > 8) { setOut({ error: '精确行列式仅支持 ≤8 阶（更大请用外部 CAS）' }); return }
      const d = detFraction(P.rows)
      setOut({ title: '行列式（分数域精确值）', lines: [`det(A) = ${fStr(d.value)}`, `小数 ≈ ${fmt(d.value.valueOf(), 10)}`] })
      return
    }
    const rr = rrefFraction(P.rows)
    if (op === 'rank') {
      setOut({
        title: `秩 rank(A) = ${rr.rank} · 行最简形（精确）`,
        lines: [matrixToString(rr.matrix)],
        steps: rr.steps,
      })
      return
    }
    if (op === 'inv') {
      if (P.m !== P.n) { setOut({ error: '求逆要求方阵' }); return }
      const aug = P.rows.map((r, i) => [...r, ...P.rows[0].map((_, j) => math.fraction(i === j ? 1 : 0))])
      const ra = rrefFraction(aug)
      if (ra.rank !== P.m) { setOut({ error: `A 奇异（rank=${ra.rank}<${P.m}），不可逆。` }); return }
      const inv = ra.matrix.map((r) => r.slice(P.n))
      setOut({ title: '逆矩阵 A⁻¹（分数精确 · 高斯-约当）', lines: [matrixToString(inv)], steps: ra.steps.slice(0, 40) })
      return
    }
    if (op === 'solve') {
      const B = parseFractionMatrix(bText)
      if (B.error) { setOut({ error: `b ${B.error}` }); return }
      if (B.m !== P.m || B.n !== 1) { setOut({ error: `b 需为 ${P.m}×1 列向量` }); return }
      const aug = P.rows.map((r, i) => [...r, B.rows[i][0]])
      const ra = rrefFraction(aug)
      const incoherent = ra.pivots.includes(P.n)
      if (incoherent) { setOut({ error: '方程组无解（增广矩阵主元落在常数列，rank(A) < rank(A|b)）', steps: ra.steps.slice(0, 30) }); return }
      const freeCols = Array.from({ length: P.n }, (_, c) => c).filter((c) => !ra.pivots.includes(c))
      const lines = [`rank(A) = ${ra.rank}，未知数 ${P.n} 个`, `增广矩阵行最简形：\n${matrixToString(ra.matrix)}`]
      if (freeCols.length === 0) {
        lines.push(`唯一解：${ra.matrix.map((r, i) => `x${i + 1} = ${fStr(r[P.n])}`).join('，')}`)
      } else {
        lines.push(`无穷多解，自由变量：${freeCols.map((c) => `x${c + 1}`).join('、')}`)
        lines.push('特解 + 自由变量系数见行最简形各行。')
      }
      setOut({ title: 'Ax = b（分数域精确）', lines, steps: ra.steps.slice(0, 40) })
      return
    }
    if (op === 'eig') {
      if (P.m !== P.n) { setOut({ error: '特征值要求方阵' }); return }
      if (P.m > 6) { setOut({ error: '特征值求解仅支持 ≤6 阶方阵（数值法，更大请用 Octave/SymPy）' }); return }
      const A = P.rows.map((r) => r.map((f) => f.valueOf()))
      const E = eigenvalues(A)
      if (E.error) { setOut({ error: E.error }); return }
      const list = E.roots.map((z, i) => {
        const res = cAbs(polyEvalC(E.cs, z))
        return `λ${i + 1} = ${fmt(z.re, 6)}${Math.abs(z.im) > 1e-9 ? ` ${z.im > 0 ? '+' : '−'} ${fmt(Math.abs(z.im), 6)}i` : ''}（特征多项式残差 ${fmt(res, 2)}）`
      })
      setOut({
        title: '特征值（Faddeev–LeVerrier 特征多项式 + 拉盖尔数值求根）',
        lines: [...list, `特征多项式系数（降幂）[${E.cs.map((c) => fmt(c, 6)).join(', ')}]`],
        steps: E.checks,
        warn: '数值方法结果，重根/病态矩阵精度下降；上方两行是 迹/行列式 一致性校验，偏差在 1e-6 量级才可信。',
      })
    }
  }

  return (
    <div className="v3-tv-grid">
      <FieldRow label="矩阵 A（行用 ; 或换行分隔，元素支持分数如 1/3、小数）">
        <Textarea className="v3-tools-mono v3-tv-matrix" rows={4} value={aText} onChange={(e) => setAText(e.target.value)} spellCheck={false} aria-label="矩阵 A" />
      </FieldRow>
      <FieldRow label="列向量 b（解方程用）">
        <Textarea className="v3-tools-mono v3-tv-matrix" rows={2} value={bText} onChange={(e) => setBText(e.target.value)} spellCheck={false} aria-label="列向量 b" />
      </FieldRow>
      <div className="v3-tv-inline">
        <Button size="sm" variant="tonal" icon={<PlayCircle size={14} />} onClick={() => run('det')}>行列式</Button>
        <Button size="sm" variant="tonal" icon={<PlayCircle size={14} />} onClick={() => run('rank')}>秩 · rref</Button>
        <Button size="sm" variant="tonal" icon={<PlayCircle size={14} />} onClick={() => run('inv')}>逆矩阵</Button>
        <Button size="sm" variant="tonal" icon={<PlayCircle size={14} />} onClick={() => run('eig')}>特征值</Button>
        <Button size="sm" variant="tonal" icon={<PlayCircle size={14} />} onClick={() => run('solve')}>解 Ax=b</Button>
      </div>
      {out?.error ? <ErrLine msg={out.error} /> : null}
      {out?.title ? (
        <>
          <OkLine>{out.title}</OkLine>
          {out.lines?.map((l, i) => (l.includes('\n') || /^\s*$/.test(l)
            ? <pre key={i} className="v3-tv-matrix-out">{l}</pre>
            : <div key={i} className="v3-tv-row"><code>{l}</code></div>))}
          {out.warn ? <div className="v3-tools-warn"><Warning size={13} /> {out.warn}</div> : null}
          {out.steps?.length ? <Steps title="初等变换步骤" count={out.steps.length}>{out.steps.map((s, i) => <div key={i} className="v3-tv-step"><code>{i + 1}. {s}</code></div>)}</Steps> : null}
        </>
      ) : null}
    </div>
  )
}

function matrixToString(rows) {
  const strs = rows.map((r) => r.map((v) => fStr(v)))
  const widths = strs[0].map((_, j) => Math.max(...strs.map((r) => r[j].length)))
  return strs.map((r) => r.map((c, j) => c.padStart(widths[j])).join('  ')).join('\n')
}

/* ============================== 解方程 ============================== */

function SolvePanel() {
  const [lhs, setLhs] = useState('x^3 - 3*x')
  const [rhs, setRhs] = useState('1')
  const [range, setRange] = useState('-5, 5')
  const compiled = useCompile(lhs)
  const compiledR = useCompile(rhs)

  const result = useMemo(() => {
    if (!compiled.ok || !compiledR.ok) return null
    const parts = range.split(',').map((s) => Number(s.trim()))
    if (parts.length !== 2 || !parts.every(Number.isFinite) || parts[0] >= parts[1]) return { error: '区间格式：min, max（且 min<max）' }
    const f = (x) => compiled.evaluate({ x }) - compiledR.evaluate({ x })
    const r = findSignChangeRoots(f, parts[0], parts[1], { cap: 1e8, max: 40, samples: 2400 })
    return { roots: r.roots, truncated: r.truncated, range: parts }
  }, [compiled, compiledR, range])

  return (
    <div className="v3-tv-grid">
      <FieldRow label="f(x)"><Input className="v3-tools-mono" value={lhs} onChange={(e) => setLhs(e.target.value)} aria-label="方程左边" spellCheck={false} /></FieldRow>
      <FieldRow label="g(x)（留空即 0）"><Input className="v3-tools-mono" value={rhs} onChange={(e) => setRhs(e.target.value)} aria-label="方程右边" spellCheck={false} /></FieldRow>
      <FieldRow label="搜索区间 [min, max]"><Input className="v3-tools-mono" style={{ width: 150 }} value={range} onChange={(e) => setRange(e.target.value)} aria-label="搜索区间" /></FieldRow>
      <ErrLine msg={!compiled.ok ? `f 解析失败：${compiled.message}` : (!compiledR.ok ? `g 解析失败：${compiledR.message}` : (result?.error || ''))} />
      {result?.roots ? (
        result.roots.length ? (
          <>
            <OkLine>
              <Tex tex={`${exprTex(lhs)} = ${exprTex(rhs) || '0'}`} /> 在 x∈[{result.range[0]}, {result.range[1]}] 内找到 {result.roots.length} 个数值根：
            </OkLine>
            <div className="v3-tv-roots">
              {result.roots.map((r, i) => <code key={i} className="v3-tools-quick__value">x{i + 1} ≈ {fmt(r, 10)}</code>)}
            </div>
            <p className="v3-tv-note">
              变号扫描 + 二分（精度约 1e-12）。注意：重根（如 (x−1)²=0）不变号、区间外的根均会漏检{result.truncated ? '；根数量已达上限并截断' : ''}。
            </p>
          </>
        ) : (
          <div className="v3-tools-warn">在 x∈[{result.range.join(', ')}] 内未发现变号根。可能存在重根、相切解或根在区间外。</div>
        )
      ) : null}
    </div>
  )
}

/* ============================== 主面板 ============================== */

const MODES = [
  { value: 'identity', label: '恒等核验' },
  { value: 'deriv', label: '求导' },
  { value: 'limit', label: '极限' },
  { value: 'integral', label: '定积分' },
  { value: 'taylor', label: '泰勒' },
  { value: 'matrix', label: '矩阵' },
  { value: 'solve', label: '解方程' },
]

export default function FormulaVerify({ onClose }) {
  const [mode, setMode] = useState('identity')
  return (
    <ToolShell
      icon={<ChevronDown size={16} />}
      title="公式验算器"
      sub="符号求导/泰勒走 mathjs；积分/极限/求根为数值法并给出误差；矩阵为分数域精确变换 · 全部本地计算"
      onClose={onClose}
      className="v3-tool-verify"
    >
      <Segmented options={MODES} value={mode} onChange={setMode} ariaLabel="验算模式" className="v3-tv-seg" />
      {mode === 'identity' ? <IdentityPanel /> : null}
      {mode === 'deriv' ? <DerivativePanel /> : null}
      {mode === 'limit' ? <LimitPanel /> : null}
      {mode === 'integral' ? <IntegralPanel /> : null}
      {mode === 'taylor' ? <TaylorPanel /> : null}
      {mode === 'matrix' ? <MatrixPanel /> : null}
      {mode === 'solve' ? <SolvePanel /> : null}
      <div className="v3-tv-boundary">
        <Check size={13} /> 所有结论均标注了方法（符号 / 数值）与适用边界；数值结论建议用外部 CAS（WolframAlpha / SymPy）交叉复核后再写进答卷。
      </div>
    </ToolShell>
  )
}
