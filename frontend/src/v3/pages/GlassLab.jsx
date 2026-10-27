/* ==========================================================================
   Glass Lab · 毛玻璃交互式页面（/glass）
   「液态玻璃」动效演示场：极光底 + 实时可调的毛玻璃面板 + 指针追光/拖拽/翻转交互。
   全部令牌来自 ../styles/tokens.css；调参变量（--gl-*）见 glasslab-v3.css。
   ========================================================================== */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import useStore from '../../store/useStore'
import { useResolvedTheme } from '../../components/UI'
import { AnimatedNumber, Ring, toast, toastOk } from '../ui'
import {
  BookOpen, Flame, Menu, Moon, RotateCcw, SlidersHorizontal, Sparkles,
  Sun, Trophy, Zap,
} from '../icons'
import '../styles/glasslab-v3.css'

/* ---------------------------------------------------------------- aids ---- */
const PRESETS = [
  { key: 'mist',    label: '清雾', blur: 8,  alpha: 0.40, sat: 1.10, radius: 20 },
  { key: 'classic', label: '标准', blur: 16, alpha: 0.55, sat: 1.25, radius: 24 },
  { key: 'rich',    label: '浓郁', blur: 24, alpha: 0.70, sat: 1.45, radius: 28 },
  { key: 'frost',   label: '磨砂', blur: 36, alpha: 0.82, sat: 1.10, radius: 32 },
]
const SUBJECTS = ['高等数学', '考研英语', '思想政治', '数据结构']

/* 单张追光倾斜卡：指针位置驱动 3D 倾斜与高光 */
function TiltCard({ icon: Icon, label, value, unit, foot, tone = '', extra }) {
  const ref = useRef(null)
  const onMove = useCallback((e) => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    if (r.width <= 0 || r.height <= 0) return
    if (!Number.isFinite(e.clientX) || !Number.isFinite(e.clientY)) return
    const px = (e.clientX - r.left) / r.width
    const py = (e.clientY - r.top) / r.height
    el.style.setProperty('--rx', `${(0.5 - py) * 7}deg`)
    el.style.setProperty('--ry', `${(px - 0.5) * 7}deg`)
    el.style.setProperty('--mx', `${px * 100}%`)
    el.style.setProperty('--my', `${py * 100}%`)
  }, [])
  const onLeave = useCallback(() => {
    const el = ref.current
    if (!el) return
    el.style.setProperty('--rx', '0deg')
    el.style.setProperty('--ry', '0deg')
  }, [])
  return (
    <div className={`glab-glass glab-tilt glab-tilt--${tone}`} ref={ref} onPointerMove={onMove} onPointerLeave={onLeave}>
      <span className="glab-tilt__spot" aria-hidden="true" />
      <span className="glab-tilt__icon"><Icon size={21} /></span>
      <span className="glab-tilt__label">{label}</span>
      <span className="glab-tilt__value">
        <AnimatedNumber value={value} />
        {unit ? <small style={{ fontSize: '0.44em', marginLeft: 4, color: 'var(--v3-text-3)' }}>{unit}</small> : null}
      </span>
      {extra}
      <span className="glab-tilt__foot">{foot}</span>
    </div>
  )
}

/* 迷你柱状趋势：填充同排大卡留下的高度，也让「积累」有形 */
function WeekBars({ days = [32, 45, 28, 51, 39, 62, 48], labels = ['一', '二', '三', '四', '五', '六', '日'] }) {
  const max = Math.max(...days, 1)
  return (
    <div className="glab-weekbars" role="img" aria-label="本周每日积累柱状图">
      {days.map((d, i) => (
        <span key={i} className="glab-weekbars__col" title={`${labels[i]}：${d} 条`}>
          <span className="glab-weekbars__track">
            <span className="glab-weekbars__bar" style={{ height: `${Math.round((d / max) * 100)}%` }} />
          </span>
          <span className="glab-weekbars__lab">{labels[i]}</span>
        </span>
      ))}
    </div>
  )
}

/* ---------------------------------------------------------------- page ---- */
export default function GlassLab() {
  /* —— 翻转卡状态 —— */
  const [flipped, setFlipped] = useState(false)
  /* —— 调参台状态 —— */
  const [blur, setBlur] = useState(PRESETS[1].blur)
  const [alpha, setAlpha] = useState(PRESETS[1].alpha)
  const [sat, setSat] = useState(PRESETS[1].sat)
  const [radius, setRadius] = useState(PRESETS[1].radius)
  const [borderOn, setBorderOn] = useState(true)
  const [noiseOn, setNoiseOn] = useState(true)
  const [presetKey, setPresetKey] = useState('classic')
  const [subjects, setSubjects] = useState(() => new Set(['高等数学']))

  const glVars = useMemo(() => ({
    '--gl-blur': `${blur}px`,
    '--gl-alpha': alpha,
    '--gl-sat': sat,
    '--gl-radius': `${radius}px`,
    '--gl-border': borderOn ? 1 : 0,
    '--gl-noise': noiseOn ? 0.35 : 0,
  }), [blur, alpha, sat, radius, borderOn, noiseOn])

  const applyPreset = useCallback((p) => {
    setPresetKey(p.key)
    setBlur(p.blur); setAlpha(p.alpha); setSat(p.sat); setRadius(p.radius)
  }, [])

  /* —— 极光底指针视差 —— */
  const [px, setPx] = useState(0)
  useEffect(() => {
    const onMove = (e) => setPx(e.clientX / window.innerWidth - 0.5)
    window.addEventListener('pointermove', onMove, { passive: true })
    return () => window.removeEventListener('pointermove', onMove)
  }, [])

  /* —— 控制台拖拽（抓手在面板头部；滑杆区域不受影响） —— */
  const panelRef = useRef(null)
  const dragRef = useRef(null)
  const [drag, setDrag] = useState({ x: 0, y: 0, on: false })
  const onDragStart = useCallback((e) => {
    if (e.button != null && e.button !== 0) return
    const el = panelRef.current
    if (!el) return
    dragRef.current = { sx: e.clientX, sy: e.clientY, ox: drag.x, oy: drag.y }
    setDrag((d) => ({ ...d, on: true }))
    /* 指针捕获：拖出面板仍能继续收 move；合成事件/不支持时静默降级 */
    try { e.currentTarget.setPointerCapture?.(e.pointerId) } catch { /* noop */ }
  }, [drag.x, drag.y])
  const onDragMove = useCallback((e) => {
    const d = dragRef.current
    if (!d) return
    /* 合成事件（测试/jsdom 播放）可能没有 clientX/Y，数值无效时保持原位 */
    if (!Number.isFinite(e.clientX) || !Number.isFinite(e.clientY)) return
    const el = panelRef.current
    const maxX = el ? el.offsetWidth / 2 + 160 : 320
    const maxY = el ? el.offsetHeight / 2 + 120 : 260
    const x = Math.max(-maxX, Math.min(maxX, d.ox + (e.clientX - d.sx)))
    const y = Math.max(-maxY, Math.min(maxY, d.oy + (e.clientY - d.sy)))
    setDrag({ x, y, on: true })
  }, [])
  const onDragEnd = useCallback(() => {
    dragRef.current = null
    setDrag((d) => ({ ...d, on: false }))
  }, [])

  /* —— 主题切换：复用全局 store，让玻璃同时在明/暗两界受检 —— */
  const themePref = useStore((s) => s.settings?.theme || 'light')
  const updateSettings = useStore((s) => s.updateSettings)
  const resolved = useResolvedTheme(themePref)
  const isDark = resolved === 'dark'

  const toggleSubject = useCallback((s) => {
    setSubjects((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s); else next.add(s)
      return next
    })
  }, [])

  const resetAll = useCallback(() => {
    applyPreset(PRESETS[1])
    setBorderOn(true); setNoiseOn(true)
    toastOk('已恢复标准玻璃')
  }, [applyPreset])

  return (
    <section
      className="glab"
      style={glVars}
      aria-label="毛玻璃交互实验室"
    >
      <div className="glab__aurora" style={{ '--px': `${px * 14}px` }} aria-hidden="true">
        <span className="glab__blob glab__blob--1" />
        <span className="glab__blob glab__blob--2" />
        <span className="glab__blob glab__blob--3" />
        <span className="glab__blob glab__blob--4" />
      </div>
      <div className="glab__grid" aria-hidden="true" />

      {/* 顶栏 hero：一块大玻璃 */}
      <header className="glab-glass glab-hero">
        <div>
          <span className="glab-hero__eyebrow"><Sparkles size={14} /> AURORA · GLASS LAB</span>
          <h1 className="glab-hero__title">毛玻璃交互实验室</h1>
          <p className="glab-hero__sub">
            把「液态玻璃」放在手上调：拖拽控制台、推移滑杆，看背景光斑穿过玻璃时
            模糊、折射与饱和度的实时变化。所有卡片都会追随你的指针，明暗两套主题即时切换。
          </p>
        </div>
        <div className="glab-hero__badge-row">
          <div className="glab-chipstat glab-glass">
            <span className="glab-chipstat__label">模糊半径</span>
            <span className="glab-chipstat__value">{blur}px</span>
          </div>
          <div className="glab-chipstat glab-glass">
            <span className="glab-chipstat__label">玻璃浓度</span>
            <span className="glab-chipstat__value">{Math.round(alpha * 100)}%</span>
          </div>
          <button
            type="button"
            className="glab-pill"
            onClick={() => { updateSettings({ theme: isDark ? 'light' : 'dark' }); toast(isDark ? '已切回浅色，玻璃更透亮' : '已进入暗色，玻璃更深邃') }}
          >
            {isDark ? <Sun size={15} /> : <Moon size={15} />}
            {isDark ? '浅色玻璃' : '暗色玻璃'}
          </button>
        </div>
      </header>

      <div className="glab-body">
        {/* —— 左：可拖拽调参台 —— */}
        <aside
          ref={panelRef}
          className={`glab-glass glab-panel${drag.on ? ' is-dragging' : ''}`}
          style={{ translate: `${drag.x}px ${drag.y}px`, transition: drag.on ? 'none' : 'translate 0.3s var(--v3-ease-spring)' }}
          aria-label="玻璃调参台"
        >
          <div
            className="glab-panel__head"
            onPointerDown={onDragStart}
            onPointerMove={onDragMove}
            onPointerUp={onDragEnd}
            onPointerCancel={onDragEnd}
            role="button"
            tabIndex={0}
            aria-label="拖拽移动调参台"
            onKeyDown={(e) => {
              const step = e.shiftKey ? 24 : 8
              const map = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }
              const mv = map[e.key]
              if (mv) { e.preventDefault(); setDrag((d) => ({ ...d, x: d.x + mv[0], y: d.y + mv[1] })) }
            }}
          >
            <span className="glab-panel__grip"><Menu size={15} /></span>
            <span className="glab-panel__title">玻璃调参台</span>
            <span className="glab-dragtip"><SlidersHorizontal size={13} /> 拖我</span>
          </div>

          <div className="glab-ctrl">
            <div className="glab-ctrl__row">
              <span className="glab-ctrl__label">backdrop 模糊</span>
              <span className="glab-ctrl__value">{blur}px</span>
            </div>
            <input aria-label="背景模糊半径" className="glab-slider" type="range"
              min={0} max={40} step={1} value={blur}
              style={{ '--fill': `${(blur / 40) * 100}%` }}
              onChange={(e) => { setBlur(Number(e.target.value)); setPresetKey('') }} />
          </div>

          <div className="glab-ctrl">
            <div className="glab-ctrl__row">
              <span className="glab-ctrl__label">玻璃透明度</span>
              <span className="glab-ctrl__value">{Math.round(alpha * 100)}%</span>
            </div>
            <input aria-label="玻璃不透明度" className="glab-slider" type="range"
              min={0.15} max={0.95} step={0.01} value={alpha}
              style={{ '--fill': `${((alpha - 0.15) / 0.8) * 100}%` }}
              onChange={(e) => { setAlpha(Number(e.target.value)); setPresetKey('') }} />
          </div>

          <div className="glab-ctrl">
            <div className="glab-ctrl__row">
              <span className="glab-ctrl__label">色彩饱和度</span>
              <span className="glab-ctrl__value">{sat.toFixed(2)}×</span>
            </div>
            <input aria-label="饱和度倍率" className="glab-slider" type="range"
              min={1} max={2} step={0.01} value={sat}
              style={{ '--fill': `${((sat - 1) / 1) * 100}%` }}
              onChange={(e) => { setSat(Number(e.target.value)); setPresetKey('') }} />
          </div>

          <div className="glab-ctrl">
            <div className="glab-ctrl__row">
              <span className="glab-ctrl__label">圆角半径</span>
              <span className="glab-ctrl__value">{radius}px</span>
            </div>
            <input aria-label="玻璃圆角" className="glab-slider" type="range"
              min={8} max={36} step={1} value={radius}
              style={{ '--fill': `${((radius - 8) / 28) * 100}%` }}
              onChange={(e) => { setRadius(Number(e.target.value)); setPresetKey('') }} />
          </div>

          <div className="glab-presets">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                type="button"
                className={`glab-preset${presetKey === p.key ? ' is-active' : ''}`}
                onClick={() => applyPreset(p)}
              >
                {p.label}
              </button>
            ))}
            <button type="button" className="glab-preset" onClick={resetAll}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><RotateCcw size={12} /> 复原</span>
            </button>
          </div>

          <div className="glab-toggles">
            <button
              type="button"
              className={`glab-preset${borderOn ? ' is-active' : ''}`}
              aria-pressed={borderOn}
              onClick={() => setBorderOn((v) => !v)}
            >
              高光描边
            </button>
            <button
              type="button"
              className={`glab-preset${noiseOn ? ' is-active' : ''}`}
              aria-pressed={noiseOn}
              onClick={() => setNoiseOn((v) => !v)}
            >
              噪点纹理
            </button>
          </div>
        </aside>

        {/* —— 右：玻璃展台 —— */}
        <div className="glab-stage">
          <TiltCard icon={Zap} tone="amber" label="今日专注" value={48} unit="分钟" foot="连续第 12 天 · 追光卡：指针掠过会倾斜" />
          <TiltCard icon={Trophy} tone="purple" label="掌握度" value={87} unit="%" foot="薄弱点较上周 −5%" />
          <TiltCard icon={Flame} tone="coral" label="连续打卡" value={12} unit="天" foot="历史最长 31 天" />
          <TiltCard icon={BookOpen} tone="green" label="词句积累" value={356} unit="条"
            extra={<WeekBars />} foot="本周 +48 · 每天都在涨" />

          {/* 大看板：进度环 + 课程胶囊 + 分层玻璃 */}
          <div className="glab-glass glab-showcase">
            <div className="glab-showcase__head">
              <span className="glab-showcase__title">学习进度 · 玻璃展台</span>
              <span className="glab-dragtip"><Sparkles size={13} /> 这些控件都是毛玻璃</span>
            </div>

            <div className="glab-rings">
              <div className="glab-rings__item">
                <Ring value={78} size={82} gradient><strong>78%</strong></Ring>
                <span className="glab-rings__label">章节掌握</span>
              </div>
              <div className="glab-rings__item">
                <Ring value={86} size={82}><strong>86%</strong></Ring>
                <span className="glab-rings__label">题目正确率</span>
              </div>
              <div className="glab-rings__item">
                <Ring value={64} size={82} gradient><strong>64%</strong></Ring>
                <span className="glab-rings__label">背诵进度</span>
              </div>
            </div>

            <div>
              <div className="glab-ctrl__row" style={{ marginBottom: 10 }}>
                <span className="glab-ctrl__label">在学课程（可多选）</span>
              </div>
              <div className="glab-pills" role="group" aria-label="在学课程">
                {SUBJECTS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={`glab-pill${subjects.has(s) ? ' is-active' : ''}`}
                    aria-pressed={subjects.has(s)}
                    onClick={() => toggleSubject(s)}
                  >
                    <Sparkles size={13} /> {s}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="glab-ctrl__row" style={{ marginBottom: 10 }}>
                <span className="glab-ctrl__label">同参数 · 三档浓度的玻璃分层</span>
              </div>
              <div className="glab-layers">
                <div className="glab-layer glab-layer--a">
                  <span className="glab-layer__name">α × 0.55</span>
                  <span className="glab-layer__hint">最薄的一层：透出更多极光，适合次级信息</span>
                </div>
                <div className="glab-layer glab-layer--b">
                  <span className="glab-layer__name">α × 0.80</span>
                  <span className="glab-layer__hint">中间层：主体卡片常用浓度，可读与氛围平衡</span>
                </div>
                <div className="glab-layer glab-layer--c">
                  <span className="glab-layer__name">α × 1.00</span>
                  <span className="glab-layer__hint">最厚的一层：弹窗/浮层用，内容最稳</span>
                </div>
              </div>
            </div>
          </div>

          {/* 翻转卡：点击换面 */}
          <button
            type="button"
            className={`glab-glass glab-flip${flipped ? ' is-flipped' : ''}`}
            aria-pressed={flipped}
            onClick={() => { setFlipped((v) => !v); if (!flipped) toast('玻璃背面：参数配方藏在这里') }}
          >
            <span className="glab-flip__face">
              <span className="glab-tilt__icon"><Sparkles size={20} /></span>
              <span className="glab-tilt__label">液态玻璃 · 正面</span>
              <span className="glab-tilt__foot">点击翻面查看参数配方 &gt;&gt;</span>
            </span>
            <span className="glab-flip__face glab-flip__face--back">
              <span className="glab-tilt__label">配方速记</span>
              <span className="glab-layer__hint">
                背景 rgba(玻璃色, α) + backdrop-filter: blur + saturate，
                顶部 1px 高光渐变描边，再铺一层 feTurbulence 噪点去塑料感。
              </span>
              <span className="glab-flip__hint"><RotateCcw size={13} /> 再点一次翻回正面</span>
            </span>
          </button>
          {/* 占位格：补齐翻转卡所在行的栅格（窄屏隐藏） */}
          <div className="glab-pad" aria-hidden="true" />
        </div>
      </div>
    </section>
  )
}
