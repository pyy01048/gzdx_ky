import { useMemo } from 'react'
import { passwordCategories } from '../../utils/password'

const LABELS = ['', '弱', '一般', '较强', '强']
const TONES = ['', 'danger', 'warning', 'primary', 'success']
const HINT = '需 8 位以上，含大小写/数字/特殊字符中至少 3 类'

/** 密码强度指示器：根据字符类别数与长度评级，给出条形强度与文字提示 */
export function PasswordStrength({ value }) {
  const { cats, okLen, level } = useMemo(() => {
    const v = value || ''
    const c = passwordCategories(v)
    const ok = v.length >= 8
    return { cats: c, okLen: ok, level: !value ? 0 : Math.min(c + (ok ? 1 : 0), 4) }
  }, [value])
  if (!value) return null
  const tone = TONES[level] || 'muted'
  return (
    <div className="v3-pwd-meter" aria-live="polite">
      <div className="v3-pwd-meter__bars">
        {[1, 2, 3, 4].map((i) => (
          <i key={i} className={i <= level ? `is-on is-${TONES[level]}` : ''} />
        ))}
      </div>
      <span className={`v3-pwd-meter__label is-${tone}`}>
        {okLen && cats >= 3 ? `强度：${LABELS[level]}` : HINT}
      </span>
    </div>
  )
}
