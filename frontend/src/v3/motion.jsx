/* ==========================================================================
   Aurora v3 · Motion primitives
   参考 16 种微交互动效补齐的可复用原语。已有能力不重复造：
   CountUp=AnimatedNumber(ui)、Shimmer/Stagger/HoverLift/Spring/Easing=motion.css。
   这里新增：Spotlight、ScrollReveal、BorderBeam(CSS)、Magnetic、3DTilt、
   Typewriter、TextScramble、Marquee、Parallax、ScrollProgress(Scrollytelling)。
   铁律：只动 transform/opacity（或纯绘制的 CSS 变量）；
   prefers-reduced-motion / 粗指针 / 无 IO 环境一律静态降级。
   ========================================================================== */
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { cx } from './ui'

const prefersReduced = () => {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

const finePointer = () => {
  try {
    return window.matchMedia('(pointer: fine)').matches
  } catch {
    return false
  }
}

export function useReducedMotion() {
  const [reduced, setReduced] = useState(prefersReduced)
  useEffect(() => {
    let mq
    try {
      mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    } catch {
      return undefined
    }
    const onChange = (e) => setReduced(e.matches)
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])
  return reduced
}

/* ---------- Scroll Reveal（IntersectionObserver，进入视口后一次性显现） ---------- */
export function useReveal(delay = 0) {
  const ref = useRef(null)
  const reduced = useReducedMotion()
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    if (reduced || typeof IntersectionObserver === 'undefined') {
      setShown(true)
      return undefined
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true)
          io.disconnect()
        }
      },
      { rootMargin: '0px 0px -6% 0px', threshold: 0.05 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [reduced])
  return {
    ref,
    className: cx('v3-reveal', shown && 'is-revealed'),
    style: { '--reveal-delay': `${delay}ms` },
  }
}

export function Reveal({ as: As = 'div', delay = 0, className = '', style, children, ...props }) {
  const rv = useReveal(delay)
  return (
    <As ref={rv.ref} {...props} className={cx(rv.className, className)} style={{ ...style, ...rv.style }}>
      {children}
    </As>
  )
}

/* ---------- Spotlight / 3D Tilt / Magnetic（共用一个指针处理器，零额外 DOM） ---------- */
export function usePointerFx({ spotlight = false, tilt = 0, magnetic = 0, disabled = false }) {
  const onPointerMove = useCallback(
    (e) => {
      if (disabled || !finePointer()) return
      const el = e.currentTarget
      const r = el.getBoundingClientRect()
      if (!r.width || !r.height) return
      const x = e.clientX - r.left
      const y = e.clientY - r.top
      if (spotlight) {
        el.style.setProperty('--mx', `${x.toFixed(1)}px`)
        el.style.setProperty('--my', `${y.toFixed(1)}px`)
      }
      if (tilt > 0) {
        el.style.setProperty('--tilt-x', `${(-(y / r.height - 0.5) * 2 * tilt).toFixed(2)}deg`)
        el.style.setProperty('--tilt-y', `${((x / r.width - 0.5) * 2 * tilt).toFixed(2)}deg`)
      }
      if (magnetic > 0) {
        const mx = Math.max(-magnetic, Math.min(magnetic, (x - r.width / 2) * 0.22))
        const my = Math.max(-magnetic, Math.min(magnetic, (y - r.height / 2) * 0.22))
        el.style.setProperty('--mag-x', `${mx.toFixed(1)}px`)
        el.style.setProperty('--mag-y', `${my.toFixed(1)}px`)
      }
    },
    [spotlight, tilt, magnetic, disabled],
  )
  const onPointerLeave = useCallback((e) => {
    const el = e.currentTarget
    for (const v of ['--mx', '--my', '--tilt-x', '--tilt-y', '--mag-x', '--mag-y']) el.style.removeProperty(v)
  }, [])
  return { onPointerMove, onPointerLeave }
}

export function PointerFx({ as: As = 'div', spotlight = true, tilt = 0, magnetic = 0, className = '', children, ...props }) {
  const reduced = useReducedMotion()
  const fx = usePointerFx({ spotlight, tilt, magnetic, disabled: reduced })
  return (
    <As
      {...props}
      {...fx}
      className={cx(spotlight && 'v3-spotlight', tilt > 0 && 'v3-tilt', magnetic > 0 && 'v3-magnetic', className)}
    >
      {children}
    </As>
  )
}

/* 磁吸按钮：把返回值直接展开到 Button/按钮上（className 会被 Button 合并） */
export function useMagnetic(strength = 4) {
  const reduced = useReducedMotion()
  const fx = usePointerFx({ magnetic: strength, disabled: reduced })
  return { className: 'v3-magnetic', ...fx }
}

/* ---------- Typewriter（ghost 占位防回流；读屏拿全文） ---------- */
export function Typewriter({ text, speed = 32, startDelay = 0, caret = true, className = '' }) {
  const reduced = useReducedMotion()
  const [n, setN] = useState(() => (prefersReduced() ? text.length : 0))
  useEffect(() => {
    if (reduced) {
      setN(text.length)
      return undefined
    }
    setN(0)
    let i = 0
    let interval
    const timer = setTimeout(() => {
      interval = setInterval(() => {
        i += 1
        setN(i)
        if (i >= text.length) clearInterval(interval)
      }, speed)
    }, startDelay)
    return () => {
      clearTimeout(timer)
      clearInterval(interval)
    }
  }, [text, speed, startDelay, reduced])
  const done = n >= text.length
  return (
    <span className={cx('v3-typewriter', className)}>
      <span className="v3-typewriter__ghost" aria-hidden="true">{text}</span>
      <span className="v3-typewriter__live" aria-hidden="true">
        {text.slice(0, n)}
        {caret && !done ? <i className="v3-caret" /> : null}
      </span>
      <span className="v3-sr-only">{text}</span>
    </span>
  )
}

/* ---------- Text Scramble（挂载时解码；中文用汉字池，标点/空格不参与） ---------- */
const LATIN_POOL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
const CJK_POOL = '考研学府硕博知行思学问道志远登峰砺剑'
const KEEP = /[\s，。、·：；！？「」]/

export function ScrambleText({ text, duration = 700, className = '', as: As = 'span' }) {
  const reduced = useReducedMotion()
  const [out, setOut] = useState(text)
  useLayoutEffect(() => {
    if (reduced || !text) {
      setOut(text)
      return undefined
    }
    const chars = [...text]
    const start = performance.now()
    let raf = 0
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration)
      const settled = Math.floor(t * chars.length)
      setOut(
        chars
          .map((c, i) => {
            if (i < settled || KEEP.test(c)) return c
            const pool = /[一-鿿]/.test(c) ? CJK_POOL : LATIN_POOL
            return pool[Math.floor(Math.random() * pool.length)]
          })
          .join(''),
      )
      if (t < 1) raf = requestAnimationFrame(tick)
      else setOut(text)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [text, duration, reduced])
  return (
    <As className={className}>
      <span aria-hidden="true">{out}</span>
      <span className="v3-sr-only">{text}</span>
    </As>
  )
}

/* ---------- Marquee（无缝横滚；reduced-motion 下退化为可横滑静态条） ---------- */
export function Marquee({ children, duration = 30, className = '' }) {
  return (
    <div className={cx('v3-marquee', className)}>
      <div className="v3-marquee__track" style={{ '--marquee-dur': `${duration}s` }}>
        <div className="v3-marquee__group">{children}</div>
        <div className="v3-marquee__group" aria-hidden="true">{children}</div>
      </div>
    </div>
  )
}

/* ---------- Parallax（装饰层专用；transform-only，rAF 节流） ---------- */
export function useParallax(factor = 0.12, max = 40) {
  const ref = useRef(null)
  const reduced = useReducedMotion()
  useEffect(() => {
    const el = ref.current
    if (!el || reduced) return undefined
    let raf = 0
    const compute = () => {
      raf = 0
      const r = el.getBoundingClientRect()
      const offset = (r.top + r.height / 2 - window.innerHeight / 2) * factor
      el.style.setProperty('--par-y', `${Math.max(-max, Math.min(max, offset)).toFixed(1)}px`)
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(compute)
    }
    compute()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf) cancelAnimationFrame(raf)
      el.style.removeProperty('--par-y')
    }
  }, [factor, max, reduced])
  return ref
}

/* ---------- Scrollytelling 基础：滚动进度（0..1）与阅读进度条 ---------- */
export function useScrollProgress(targetRef) {
  const [p, setP] = useState(0)
  useEffect(() => {
    let raf = 0
    const compute = () => {
      raf = 0
      const el = targetRef?.current
      if (el) {
        const r = el.getBoundingClientRect()
        const total = r.height - window.innerHeight
        setP(total > 0 ? Math.min(1, Math.max(0, -r.top / total)) : 1)
      } else {
        const total = document.documentElement.scrollHeight - window.innerHeight
        setP(total > 0 ? Math.min(1, Math.max(0, window.scrollY / total)) : 1)
      }
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(compute)
    }
    compute()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [targetRef])
  return p
}

export function ReadingProgress({ targetRef, className = '' }) {
  const p = useScrollProgress(targetRef)
  return <div className={cx('v3-read-progress', className)} style={{ transform: `scaleX(${p.toFixed(4)})` }} />
}
