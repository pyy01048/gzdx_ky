import { passwordCategories } from '../../utils/password'

export function PasswordStrength({ value }) {
  const cats = passwordCategories(value || '')
  const okLen = (value || '').length >= 8
  const level = !value ? 0 : Math.min(cats + (okLen ? 1 : 0), 4)
  const labels = ['', '弱', '一般', '较强', '强']
  const tones = ['', 'danger', 'warning', 'primary', 'success']
  if (!value) return null
  return (
    <div className="v3-pwd-meter" aria-live="polite">
      <div className="v3-pwd-meter__bars">
        {[1, 2, 3, 4].map((i) => (
          <i key={i} className={i <= level ? `is-on is-${tones[level]}` : ''} />
        ))}
      </div>
      <span className={`v3-pwd-meter__label is-${tones[level] || 'muted'}`}>
        {okLen && cats >= 3 ? `强度：${labels[level]}` : '需 8 位以上，含大小写/数字/特殊字符中至少 3 类'}
      </span>
    </div>
  )
}
