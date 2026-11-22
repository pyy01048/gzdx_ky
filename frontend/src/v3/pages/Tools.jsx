/**
 * 学习工具箱（移动优先）
 *  A. 站内进制计算器：任意进制 2–36 互转（BigInt）、8/16/32 位原/反/补码、位网格双向绑定、
 *     一键复制、URL hash 分享。纯前端本地计算，不联网、无假数据。
 *  B. 外部专业工具目录（4 组，按工科备考动线）：外链一律新标签页 + rel="noopener noreferrer"。
 *  C. 站内工具入口卡：直达既有真实路由（App.jsx 已核对）；未建成的标「即将上线」禁用态。
 *  D. 使用边界诚实声明。
 *  W2 归并：页首新增「复试工具箱」分区 —— CodeBank（代码上机，原「练习」导航入口）
 *  与进制计算器、规划中的函数图像 / 电路简单绘制合成一个复试准备入口；
 *  未实现项保持禁用态「即将上线」。
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Alert, Badge, Button, Card, CardHead, Chip, IconButton, Input, PageHeader, Select,
  toastErr, toastOk,
} from '../ui'
import {
  ArrowRight, BookOpen, Brain, Check, Copy, ExternalLink, Hash, Image, Info,
  LayoutGrid, RotateCcw, Share2, Type,
} from '../icons'
import '../styles/tools-v3.css'

/* ------------------------------------------------------------------ */
/* A · 进制计算纯函数（BigInt，支持超大整数与负数）                       */
/* ------------------------------------------------------------------ */
const DIGITS = '0123456789abcdefghijklmnopqrstuvwxyz'

/** 把「[sign]digits」按 base 解析成 BigInt；非法字符/越界位返回原因 */
function parseRadix(raw, base) {
  const text = String(raw ?? '').trim().toLowerCase().replace(/\s|_/g, '')
  if (!text) return { ok: false, reason: '请输入数值' }
  let sign = 1n
  let body = text
  if (body.startsWith('-')) { sign = -1n; body = body.slice(1) } else if (body.startsWith('+')) { body = body.slice(1) }
  if (!body) return { ok: false, reason: '缺少数字部分' }
  for (const ch of body) {
    const d = DIGITS.indexOf(ch)
    if (d < 0) return { ok: false, reason: `「${ch}」不是有效数字` }
    if (d >= base) return { ok: false, reason: `「${ch}」超出 ${base} 进制可用位（0–${DIGITS[base - 1]}）` }
  }
  let v = 0n
  const b = BigInt(base)
  for (const ch of body) v = v * b + BigInt(DIGITS.indexOf(ch))
  return { ok: true, value: sign * v }
}

/** BigInt → base 进制字符串（保留负号，大写展示超过 9 的位） */
function toRadix(value, base) {
  if (value === 0n) return '0'
  const neg = value < 0n
  let v = neg ? -value : value
  const b = BigInt(base)
  let s = ''
  while (v > 0n) { s = DIGITS[Number(v % b)] + s; v /= b }
  return (neg ? '-' : '') + s.toUpperCase()
}

const padBits = (v, w) => v.toString(2).padStart(w, '0')

/** num 在 w 位下的补码位串（超范围按低 w 位截断） */
function twosBits(num, w) {
  const m = 1n << BigInt(w)
  return padBits(((num % m) + m) % m, w)
}
/** 原码位串：符号位 + 绝对值 w-1 位 */
function signMagBits(num, w) {
  const magLimit = 1n << BigInt(w - 1)
  const mag = num < 0n ? -num : num
  const sign = num < 0n ? '1' : '0'
  return mag >= magLimit ? `${sign}${padBits(mag % magLimit, w - 1)}` : `${sign}${padBits(mag, w - 1)}`
}
/** 反码位串：正数同原码；负数符号位 1 + 数值位按位取反 */
function onesBits(num, w) {
  if (num >= 0n) return signMagBits(num, w)
  const magLimit = 1n << BigInt(w - 1)
  const mag = -num > magLimit - 1n ? (magLimit - 1n) : -num
  return `1${padBits((magLimit - 1n) ^ mag, w - 1)}`
}
/** 位串 → 数值（按所选码制解码） */
function decodeBits(bits, mode) {
  const w = bits.length
  const neg = bits[0] === '1'
  const magLimit = 1n << BigInt(w - 1)
  const rest = BigInt(`0b${bits.slice(1) || '0'}`)
  if (mode === 'twos') return neg ? rest - magLimit : rest
  if (mode === 'sign') return neg && rest !== 0n ? -rest : rest
  return neg ? -((magLimit - 1n) ^ rest) : rest
}

const CODE_MODES = [
  { value: 'sign', label: '原码' },
  { value: 'ones', label: '反码' },
  { value: 'twos', label: '补码' },
]
const WIDTHS = [8, 16, 32]
const QUICK_BASES = [
  { base: 2, label: '二进制 B' },
  { base: 8, label: '八进制 O' },
  { base: 10, label: '十进制 D' },
  { base: 16, label: '十六进制 H' },
]
const BASE_OPTIONS = Array.from({ length: 35 }, (_, i) => {
  const b = i + 2
  return { value: String(b), label: `${b} 进制` }
})

async function copyText(text) {
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
    } catch { return false }
  }
}

/* ------------------------------------------------------------------ */
/* A · 进制计算器                                                       */
/* ------------------------------------------------------------------ */
function RadixCalculator() {
  const [searchParams] = useSearchParams()
  const bootRef = useRef(() => {
    const v = searchParams.get('v')
    const s = Number(searchParams.get('s')) || 10
    const t = Number(searchParams.get('t')) || 2
    const parsed = v ? parseRadix(v, s) : null
    return parsed?.ok
      ? { num: parsed.value, srcBase: s, dstBase: t, width: WIDTHS.includes(Number(searchParams.get('w'))) ? Number(searchParams.get('w')) : 16 }
      : null
  })
  const boot = bootRef.current()

  const [srcText, setSrcText] = useState(boot ? toRadix(boot.num, boot.srcBase) : '255')
  const [dstText, setDstText] = useState(boot ? toRadix(boot.num, boot.dstBase) : '11111111')
  const [num, setNum] = useState(boot ? boot.num : 255n)
  const [srcBase, setSrcBase] = useState(boot ? boot.srcBase : 10)
  const [dstBase, setDstBase] = useState(boot ? boot.dstBase : 2)
  const [err, setErr] = useState('')
  const [width, setWidth] = useState(boot ? boot.width : 16)
  const [codeMode, setCodeMode] = useState('twos')
  const [lastTouched, setLastTouched] = useState('src')

  const applyNum = useCallback((next, fromSide) => {
    setNum(next)
    const s = toRadix(next, srcBase)
    const d = toRadix(next, dstBase)
    if (fromSide !== 'src') setSrcText(s)
    if (fromSide !== 'dst') setDstText(d)
    setErr('')
  }, [srcBase, dstBase])

  const onSrcInput = (t) => {
    setLastTouched('src')
    setSrcText(t)
    const r = parseRadix(t, srcBase)
    if (r.ok) { setNum(r.value); setDstText(toRadix(r.value, dstBase)); setErr('') } else setErr(r.reason)
  }
  const onDstInput = (t) => {
    setLastTouched('dst')
    setDstText(t)
    const r = parseRadix(t, dstBase)
    if (r.ok) { setNum(r.value); setSrcText(toRadix(r.value, srcBase)); setErr('') } else setErr(r.reason)
  }
  const onSrcBaseChange = (b) => {
    setSrcBase(b)
    const r = parseRadix(srcText, b)
    if (r.ok) { setNum(r.value); setDstText(toRadix(r.value, dstBase)); setSrcText(toRadix(r.value, b)); setErr('') }
    else setErr(`当前输入不是合法的 ${b} 进制数：${r.reason}`)
  }
  const onDstBaseChange = (b) => {
    setDstBase(b)
    setDstText(toRadix(num, b))
    setErr('')
  }
  const swapBases = () => {
    const [a, t] = [srcBase, dstBase]
    setSrcBase(t); setDstBase(a)
    setSrcText(toRadix(num, t)); setDstText(toRadix(num, a))
    setLastTouched('src'); setErr('')
  }
  const reset = () => {
    setSrcBase(10); setDstBase(2); setSrcText('255'); setDstText('11111111')
    setNum(255n); setWidth(16); setCodeMode('twos'); setErr(''); setLastTouched('src')
  }

  /* 位网格：展示所选码制的 w 位机器数，点击翻转第 i 位 → 反解数值 */
  const bits = useMemo(() => {
    if (codeMode === 'twos') return twosBits(num, width)
    if (codeMode === 'ones') return onesBits(num, width)
    return signMagBits(num, width)
  }, [num, width, codeMode])

  const outOfRange = useMemo(() => {
    const lim = 1n << BigInt(width - 1)
    const abs = num < 0n ? -num : num
    if (codeMode === 'twos') return num < -lim || num > lim - 1n
    return abs > lim - 1n || (num === -lim)
  }, [num, width, codeMode])

  const toggleBit = (i) => {
    const arr = bits.split('')
    arr[i] = arr[i] === '1' ? '0' : '1'
    applyNum(decodeBits(arr.join(''), codeMode), 'grid')
    setLastTouched('grid')
  }

  /* URL hash 分享：replaceState 写查询串，不触发路由重渲染 */
  useEffect(() => {
    const id = window.setTimeout(() => {
      const q = `?v=${encodeURIComponent(toRadix(num, srcBase))}&s=${srcBase}&t=${dstBase}&w=${width}`
      const base = window.location.href.split('#')[0]
      window.history.replaceState(null, '', `${base}#/tools${q}`)
    }, 400)
    return () => window.clearTimeout(id)
  }, [num, srcBase, dstBase, width])

  const share = async () => {
    const url = `${window.location.href.split('#')[0]}#/tools?v=${encodeURIComponent(toRadix(num, srcBase))}&s=${srcBase}&t=${dstBase}&w=${width}`
    if (await copyText(url)) toastOk('分享链接已复制（含当前数值与进制）')
    else toastErr('复制失败，请手动复制地址栏链接')
  }

  const copy = async (text, label) => {
    if (await copyText(text)) toastOk(`${label}已复制`)
    else toastErr('复制失败，请手动选择复制')
  }

  const rows = []
  for (let i = 0; i < width / 8; i += 1) {
    rows.push(bits.slice(i * 8, i * 8 + 8).split('').map((b, j) => ({ b, idx: i * 8 + j })))
  }

  return (
    <Card className="v3-tools-calc">
      <CardHead
        icon={<Hash size={16} />}
        title="进制计算器"
        sub="任意 2–36 进制互转 · BigInt 超大整数 · 8/16/32 位机器数 · 全部在浏览器本地计算"
        actions={(
          <>
            <IconButton label="重置" icon={<RotateCcw size={16} />} onClick={reset} />
            <IconButton label="复制分享链接" icon={<Share2 size={16} />} onClick={share} />
          </>
        )}
      />

      <div className="v3-tools-conv">
        <div className={`v3-tools-side${lastTouched === 'src' ? ' is-active' : ''}`}>
          <div className="v3-tools-side__head">
            <span className="v3-label">输入值（源进制）</span>
            <div className="v3-tools-bases">
              {QUICK_BASES.map((q) => (
                <Chip key={q.base} as="button" type="button" active={srcBase === q.base} onClick={() => onSrcBaseChange(q.base)}>
                  {q.base}
                </Chip>
              ))}
              <Select aria-label="源进制" value={String(srcBase)} onChange={(e) => onSrcBaseChange(Number(e.target.value))} options={BASE_OPTIONS} />
            </div>
          </div>
          <Input
            className="v3-tools-mono"
            value={srcText}
            spellCheck={false}
            autoComplete="off"
            aria-label={`源进制数值（${srcBase} 进制）`}
            onChange={(e) => onSrcInput(e.target.value)}
          />
          <span className="v3-tools-side__hint">{srcBase} 进制 · 可用位 0–{DIGITS[srcBase - 1].toUpperCase()}，支持负号与超大整数</span>
        </div>

        <button type="button" className="v3-tools-swap" onClick={swapBases} aria-label="交换两个进制方向">⇄</button>

        <div className={`v3-tools-side${lastTouched === 'dst' ? ' is-active' : ''}`}>
          <div className="v3-tools-side__head">
            <span className="v3-label">转换结果（目标进制）</span>
            <div className="v3-tools-bases">
              {QUICK_BASES.map((q) => (
                <Chip key={q.base} as="button" type="button" active={dstBase === q.base} onClick={() => onDstBaseChange(q.base)}>
                  {q.base}
                </Chip>
              ))}
              <Select aria-label="目标进制" value={String(dstBase)} onChange={(e) => onDstBaseChange(Number(e.target.value))} options={BASE_OPTIONS} />
            </div>
          </div>
          <Input
            className="v3-tools-mono"
            value={dstText}
            spellCheck={false}
            autoComplete="off"
            aria-label={`目标进制数值（${dstBase} 进制）`}
            onChange={(e) => onDstInput(e.target.value)}
          />
          <span className="v3-tools-side__hint">也可直接在此输入，实时反解回源进制</span>
        </div>
      </div>

      {err ? <div className="v3-tools-error">{err}</div> : null}

      <div className="v3-tools-quick">
        {QUICK_BASES.map((q) => (
          <div key={q.base} className="v3-tools-quick__row">
            <span className="v3-tools-quick__label">{q.label}</span>
            <code className="v3-tools-quick__value" title={toRadix(num, q.base)}>{toRadix(num, q.base)}</code>
            <IconButton size="sm" label={`复制 ${q.label}`} icon={<Copy size={14} />} onClick={() => copy(toRadix(num, q.base), q.label)} />
          </div>
        ))}
      </div>

      <div className="v3-tools-word">
        <div className="v3-tools-word__head">
          <span className="v3-label">机器数（按 {width} 位字长）</span>
          <div className="v3-tools-word__ctrl">
            {WIDTHS.map((w) => (
              <Chip key={w} as="button" type="button" active={width === w} onClick={() => setWidth(w)}>{w} 位</Chip>
            ))}
            {CODE_MODES.map((m) => (
              <Chip key={m.value} as="button" type="button" gradient={codeMode === m.value} onClick={() => setCodeMode(m.value)}>{m.label}</Chip>
            ))}
          </div>
        </div>
        {outOfRange ? (
          <div className="v3-tools-warn">数值超出 {width} 位{CODE_MODES.find((m) => m.value === codeMode)?.label}表示范围，位模式按低 {width} 位截断显示。</div>
        ) : null}

        <div className="v3-tools-bits" role="group" aria-label={`${width} 位${CODE_MODES.find((m) => m.value === codeMode)?.label}位网格，点击翻转某一位`}>
          <div className="v3-tools-bits__legend">
            {rows.map((_, r) => (
              <span key={r} className="v3-tools-byte">
                {Array.from({ length: 8 }).map((__, j) => (
                  <i key={j} className="v3-bit-idx">{width - 1 - (r * 8 + j)}</i>
                ))}
              </span>
            ))}
          </div>
          {rows.map((row, r) => (
            <span key={r} className="v3-tools-byte">
              {row.map(({ b, idx }) => (
                <button
                  key={idx}
                  type="button"
                  className={`v3-bit${b === '1' ? ' is-one' : ''}${idx === 0 ? ' is-sign' : ''}`}
                  aria-label={`第 ${width - 1 - idx} 位，当前 ${b}，点击翻转为 ${b === '1' ? '0' : '1'}`}
                  onClick={() => toggleBit(idx)}
                >
                  {b}
                </button>
              ))}
            </span>
          ))}
        </div>
        <div className="v3-tools-word__foot">
          <code className="v3-tools-quick__value">{bits}</code>
          <Button size="sm" variant="tonal" icon={<Copy size={14} />} onClick={() => copy(bits, `${width} 位位串`)}>复制位串</Button>
          <span className="v3-tools-word__tip">点击任意位可翻转，数值与上方输入实时联动；最左为符号位</span>
        </div>
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* B · 外部专业工具目录数据                                              */
/* ------------------------------------------------------------------ */
const STAGE_TONE = { 通用: '', 初试: 'primary', 复试: 'warning' }

const TOOL_GROUPS = [
  {
    key: 'math',
    title: '通用数学 & CAS',
    icon: Brain,
    intro: '符号计算与推导核对：高数/线代/复变/信号与系统的计算验证。',
    items: [
      {
        name: 'GeoGebra',
        stage: '通用', tag: '强推',
        purpose: '2D/3D 绘图 + CAS 符号计算',
        note: '空间几何、相量图、光路、轨迹作图一站解决；国内可用官方中国节点，速度与功能一致。',
        url: 'https://www.geogebra.org', urlLabel: '官网',
        mirror: { url: 'https://www.geogebra.cn', label: '官方中国节点' },
      },
      {
        name: 'Wolfram Alpha',
        stage: '通用', tag: '推导核对',
        purpose: '极限/微分方程/傅里叶·拉普拉斯·z 变换/矩阵特征值/伯德图零极点',
        note: '计算数学「标准答案」级引擎；官网直连较慢，可先用站内搜索「WolframAlpha 中文镜像」。',
        url: 'https://www.wolframalpha.com', urlLabel: '官网',
      },
      {
        name: 'Desmos',
        stage: '初试', tag: '免安装',
        purpose: '轻量 2D 函数绘图，打开即用',
        note: '无官方国内镜像、直连偶尔慢；追求稳定建议改用 GeoGebra 的图形计算器，能力覆盖它。',
        url: 'https://www.desmos.com', urlLabel: '官网',
      },
      {
        name: 'GNU Octave',
        stage: '复试', tag: '仿真',
        purpose: 'MATLAB 免费平替：矩阵/电路/振动/信号仿真',
        note: '语法与 MATLAB 高度兼容，Windows 安装包可从清华 TUNA GNU 镜像下载，速度快。',
        url: 'https://octave.org', urlLabel: '官网',
        mirror: { url: 'https://mirrors.tuna.tsinghua.edu.cn/gnu/octave/', label: '清华 TUNA 镜像' },
      },
      {
        name: 'Python SymPy / SciPy',
        stage: '复试', tag: '加分项',
        purpose: '符号推导 + 数值仿真 + Bode/奈奎斯特/FFT 专业图',
        note: '本地装包用清华 PyPI 镜像：pip install sympy scipy -i https://pypi.tuna.tsinghua.edu.cn/simple ；做出来的仿真代码可以直接当复试作品。',
        url: 'https://docs.scipy.org', urlLabel: '官方文档',
        mirror: { url: 'https://pypi.tuna.tsinghua.edu.cn/simple', label: '清华 PyPI 镜像' },
      },
    ],
  },
  {
    key: 'formula',
    title: '公式识别 & 排版',
    icon: Type,
    intro: '把纸质/课件/手写公式变成可编辑 LaTeX，节省抄题时间。',
    items: [
      {
        name: 'SimpleTex',
        stage: '通用', tag: '国内快',
        purpose: '截图识别手写/印刷公式，快捷键悬浮输出 LaTeX',
        note: '国内首选公式 OCR：全局快捷键截取屏幕、识别结果直接粘贴进 LaTeX/Word。',
        url: 'https://simpletex.cn', urlLabel: '官网',
      },
      {
        name: 'Mathpix Snip',
        stage: '通用', tag: '复杂式',
        purpose: '复杂矩阵/多行方程组/电路公式识别更强',
        note: '识别上限高但免费额度有限，官网直连慢；日常优先 SimpleTex，啃硬骨头再上它。',
        url: 'https://mathpix.com', urlLabel: '官网',
      },
      {
        name: 'Pix2Text',
        stage: '通用', tag: '离线',
        purpose: '本地离线批量识别课件截图，隐私友好',
        note: '开源、完全离线跑在自己电脑上；克隆仓库慢可加 GitHub 加速前缀（如 https://gitclone.com/github.com/...）。',
        url: 'https://github.com/PekingUniversity/pix2text', urlLabel: '源码仓库',
      },
      {
        name: 'Overleaf',
        stage: '复试', tag: '排版',
        purpose: 'LaTeX 在线协作：复试科研小结/课程报告/毕设摘要',
        note: '模板丰富、免环境配置；官方中国节点 cn.overleaf.com 国内直连稳定。',
        url: 'https://www.overleaf.com', urlLabel: '官网',
        mirror: { url: 'https://cn.overleaf.com', label: '官方中国节点' },
      },
    ],
  },
  {
    key: 'diagram',
    title: '绘图 · 框图 · 电路仿真',
    icon: Image,
    intro: '框图/信号流图/电路图从手绘升级到可导出矢量图，直接进报告与 PPT。',
    items: [
      {
        name: 'Draw.io (diagrams.net)',
        stage: '通用', tag: '免费',
        purpose: '电路框图/信号流图/流水线/PFD/网络拓扑，导出 SVG/PDF',
        note: '完全免费、无需注册；GitHub Pages 版界面相同，官方应用打不开时可作直达入口。',
        url: 'https://app.diagrams.net', urlLabel: '官网',
        mirror: { url: 'https://jgraph.github.io/drawio/', label: 'GitHub Pages 版' },
      },
      {
        name: 'Excalidraw',
        stage: '通用', tag: '手绘',
        purpose: '手绘风白板，快速画机构简图/思路草图',
        note: '白板草稿利器，导出 PNG/SVG；后续站内框图编辑器上线后也可在站内完成。',
        url: 'https://excalidraw.com', urlLabel: '官网',
      },
      {
        name: 'LTspice',
        stage: '复试', tag: '电类',
        purpose: '模电/运放/电源/小信号仿真，面试演示波形',
        note: 'ADI 官方免费；官网下载页提供 Windows 安装包直链，无需翻墙。',
        url: 'https://www.analog.com/en/design-center/design-tools-and-calculators/ltspice-simulator.html', urlLabel: '官方下载页',
      },
      {
        name: 'Qucs-S',
        stage: '通用', tag: '平替',
        purpose: '开源电路仿真，Multisim 平替',
        note: '图形化建电路 + ngspice 仿真内核；SourceForge 下载节点国内可达性较好。',
        url: 'https://ra3xdh.github.io', urlLabel: '项目主页',
        mirror: { url: 'https://sourceforge.net/projects/qucs-s/', label: 'SourceForge 下载' },
      },
      {
        name: 'Inkscape',
        stage: '复试', tag: '矢量',
        purpose: '矢量修图：给仿真/GeoGebra 导出图标注美化后进 PPT',
        note: '开源 SVG 编辑器；安装包可从清华 TUNA 镜像下载。',
        url: 'https://inkscape.org', urlLabel: '官网',
        mirror: { url: 'https://mirrors.tuna.tsinghua.edu.cn/inkscape/', label: '清华 TUNA 镜像' },
      },
    ],
  },
  {
    key: 'notes',
    title: '知识库 · 笔记 · 错题',
    icon: BookOpen,
    intro: '把「面试高频问答」「错题归因」沉淀成可检索的个人知识库。',
    items: [
      {
        name: 'Obsidian',
        stage: '通用', tag: '最推荐',
        purpose: '本地 Markdown + LaTeX + Mermaid + 双向链接',
        note: '数据全在自己磁盘上，最适合建「面试高频问答库」；官网为官方中文站，下载慢可到其 GitHub Releases 用 ghproxy 类加速前缀。',
        url: 'https://obsidian.md', urlLabel: '官网',
      },
      {
        name: '思源笔记',
        stage: '通用', tag: '国产',
        purpose: '国内访问稳定的本地双链笔记，免折腾插件',
        note: '块级引用 + 内置公式渲染，中文生态与更新节奏对国内用户友好。',
        url: 'https://b3log.org/siyuan', urlLabel: '官网',
      },
      {
        name: 'MarginNote',
        stage: '初试', tag: 'iPad',
        purpose: 'iPad 上 PDF 教材边读边做导图与摘录卡',
        note: '啃厚专业课书的重度阅读工具：高亮即卡片、卡片自动成导图；仅 Apple 平台。',
        url: 'https://www.marginnote.com', urlLabel: '官网',
      },
      {
        name: 'OneNote',
        stage: '通用', tag: '手写',
        purpose: '随手手写推导/贴截图，多端同步方便',
        note: '手写笔推导公式 + 截图整理试卷的自由画布；微软中国节点可直连。',
        url: 'https://www.onenote.com', urlLabel: '官网',
      },
    ],
  },
]

function ExternalToolCard({ tool }) {
  return (
    <Card className="v3-tools-ext" as="article">
      <header className="v3-tools-ext__head">
        <strong>{tool.name}</strong>
        <Badge tone={STAGE_TONE[tool.stage] || undefined}>{tool.stage}</Badge>
        {tool.tag ? <Badge tone="outline">{tool.tag}</Badge> : null}
      </header>
      <p className="v3-tools-ext__purpose">{tool.purpose}</p>
      <p className="v3-tools-ext__note">{tool.note}</p>
      <footer className="v3-tools-ext__actions">
        <a className="v3-btn v3-btn--tonal v3-btn--sm" href={tool.url} target="_blank" rel="noopener noreferrer">
          <ExternalLink size={14} /> {tool.urlLabel || '打开官网'}
        </a>
        {tool.mirror ? (
          <a className="v3-btn v3-btn--outline v3-btn--sm" href={tool.mirror.url} target="_blank" rel="noopener noreferrer">
            <ArrowRight size={14} /> {tool.mirror.label}
          </a>
        ) : null}
      </footer>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* C · 站内工具入口（路由均已对照 App.jsx 核实）                          */
/* ------------------------------------------------------------------ */
const INTERNAL_TOOLS = [
  { to: '/library', label: '知识库', desc: '学习文库 · 文档知识库统一入口', icon: BookOpen },
  { to: '/knowledge', label: '知识图谱', desc: '科目→章节→知识点地图', icon: LayoutGrid },
  { to: '/notebook', label: '错题本', desc: '错题录入 · 间隔复习', icon: Check },
  { to: '/error-review', label: '错题复盘', desc: '错因分布 · AI 归因', icon: RotateCcw },
  { to: '/quiz', label: '刷题中心', desc: '题库与章节强化', icon: ArrowRight },
]
const PLANNED_TOOLS = [
  { label: '公式验算器', desc: '关键公式在线代入核对结果', icon: Check },
  { label: 'LaTeX 工作台', desc: '公式排版与实时预览', icon: Type },
  { label: '框图编辑器', desc: '控制系统框图/SFV 站内绘制', icon: LayoutGrid },
]

/* W2 归并：复试工具箱 —— CodeBank（代码上机）自「练习」导航移入，
   与站内进制计算器、规划中的函数图像/电路绘制合成一个复试准备入口。
   未实现的项保持「即将上线」禁用态，不做假功能。 */
const FUSHI_TOOLS = [
  { key: 'codebank', label: '代码上机题库', desc: 'LeetCode 式复试 OJ · 提交即判', to: '/codebank', icon: Hash, ready: true },
  { key: 'radix', label: '进制计算器', desc: '任意进制互转 · 原/反/补码 —— 已内置在本页上方', href: '#tools-calc', icon: Type, ready: true },
  { key: 'funcplot', label: '函数图像生成器', desc: '考研高数函数图像速绘与变换', icon: Image, ready: false },
  { key: 'circuit', label: '电路简单绘制', desc: '基础电路图与连线练习', icon: LayoutGrid, ready: false },
]

/* ------------------------------------------------------------------ */
/* 页面                                                                */
/* ------------------------------------------------------------------ */
export default function Tools() {
  return (
    <div className="v3-stack v3-tools">
      <PageHeader
        eyebrow="TOOLS · 工具箱"
        title="学习工具箱 · 复试工具箱"
        sub="复试工具箱（代码上机 / 进制 / 函数图像 / 电路）· 工科备考外部工具目录 · 常用站内功能直达"
        actions={(
          <Link className="v3-btn v3-btn--tonal" to="/library">
            去知识库 <ArrowRight size={15} />
          </Link>
        )}
      />

      <section className="v3-tools-section" aria-labelledby="tools-fushi">
        <div className="v3-tools-section__head" id="tools-fushi">
          <div>
            <h2>复试工具箱</h2>
            <p>
              复试准备一站进入：代码上机题库与进制计算器已可用；函数图像、电路简单绘制还在规划中，
              上线前保持「即将上线」禁用态，不提供假功能。
            </p>
          </div>
        </div>
        <div className="v3-tools-int-grid">
          {FUSHI_TOOLS.map((t) => {
            const Icon = t.icon
            const inner = (
              <>
                <span className="v3-tools-int__icon"><Icon size={18} /></span>
                <span className="v3-tools-int__copy">
                  <strong>{t.label}</strong>
                  <em>{t.desc}</em>
                </span>
              </>
            )
            if (!t.ready) {
              return (
                <div key={t.key} className="v3-tools-int v3-tools-int--soon" aria-disabled="true">
                  {inner}
                  <Badge tone="outline">即将上线</Badge>
                </div>
              )
            }
            if (t.href) {
              return (
                <a key={t.key} className="v3-tools-int" href={t.href}>
                  {inner}
                  <ArrowRight size={16} className="v3-tools-int__go" />
                </a>
              )
            }
            return (
              <Link key={t.to} to={t.to} className="v3-tools-int">
                {inner}
                <ArrowRight size={16} className="v3-tools-int__go" />
              </Link>
            )
          })}
        </div>
      </section>

      <section className="v3-tools-section" aria-labelledby="tools-calc">
        <div className="v3-tools-section__head" id="tools-calc">
          <div>
            <h2>进制计算器</h2>
            <p>考试与复试上机高频：任意进制互转、机器数与原码/反码/补码位视图，位网格点击即可翻转。</p>
          </div>
        </div>
        <RadixCalculator />
      </section>

      {TOOL_GROUPS.map((g) => {
        const Icon = g.icon
        return (
          <section key={g.key} className="v3-tools-section" aria-label={g.title}>
            <div className="v3-tools-section__head">
              <div>
                <h2><Icon size={15} /> {g.title}</h2>
                <p>{g.intro}</p>
              </div>
              <span className="v3-tools-section__count">{g.items.length} 个</span>
            </div>
            <div className="v3-tools-ext-grid">
              {g.items.map((t) => <ExternalToolCard key={t.name} tool={t} />)}
            </div>
          </section>
        )
      })}

      <section className="v3-tools-section" aria-labelledby="tools-internal">
        <div className="v3-tools-section__head" id="tools-internal">
          <div>
            <h2>站内工具直达</h2>
            <p>平台内已有功能一键进入；规划中的工具完成后会出现在这里。</p>
          </div>
        </div>
        <div className="v3-tools-int-grid">
          {INTERNAL_TOOLS.map((t) => {
            const Icon = t.icon
            return (
              <Link key={t.to} to={t.to} className="v3-tools-int">
                <span className="v3-tools-int__icon"><Icon size={18} /></span>
                <span className="v3-tools-int__copy">
                  <strong>{t.label}</strong>
                  <em>{t.desc}</em>
                </span>
                <ArrowRight size={16} className="v3-tools-int__go" />
              </Link>
            )
          })}
          {PLANNED_TOOLS.map((t) => {
            const Icon = t.icon
            return (
              <div key={t.label} className="v3-tools-int v3-tools-int--soon" aria-disabled="true">
                <span className="v3-tools-int__icon"><Icon size={18} /></span>
                <span className="v3-tools-int__copy">
                  <strong>{t.label}</strong>
                  <em>{t.desc}</em>
                </span>
                <Badge tone="outline">即将上线</Badge>
              </div>
            )
          })}
        </div>
      </section>

      <Alert tone="info" icon={<Info size={16} />} className="v3-tools-boundary">
        <div className="v3-tools-boundary__inner">
          <strong>使用边界说明</strong>
          {' '}站内进制计算器为浏览器本地真实计算，不联网、不含任何预置假数据；外部工具为第三方官网入口，功能、额度与可用性以官方为准，本页不构成任何效果承诺。「国内加速」仅为镜像 / 官方中国节点的直达链接，本站不代理、不缓存其内容；所有外链均在新标签页打开。
        </div>
      </Alert>
    </div>
  )
}
