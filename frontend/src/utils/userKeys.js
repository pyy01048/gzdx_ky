/* ============================================================================
 * P4/P6-A（用户数据隔离）：localStorage 散键按登录账号隔离
 *
 * 背景：全站散键（quiz_favorites_v9、ky_fav_school_ids、focus_timer_v1 等）
 * 过去是全局共享的 —— 同一台浏览器换账号登录，看到的是上一个人的收藏/布局/
 * 计时状态。本模块给所有散键提供统一的按账号命名与迁移口径：
 *
 *   - setUser(id)：登录成功（含会话恢复）时由 AuthContext 调用，重置全局 uid；
 *   - ukey(base) ：读写的真实键 = `base:{uid}`；uid 未设置（未登录）时原样
 *                  返回 base —— 与改造前行为一致，未登录路径不用到处判空；
 *   - migrateKey(base) / readMigrated(base, fallback)：首读时若新键不存在而
 *                  旧全局键存在，把旧值**一次性**迁移给当前登录用户并删除旧键
 *                  （单机场景旧值的主人大概率就是当前登录者，见
 *                  docs/plan-gap/E-user-data-isolation.md §5）。
 *
 * 注意：setUser 每次都会广播 `userkeys:uid-changed`（包括重设同一个 uid）。
 * useUiLayout 这类「模块加载即建快照」的消费方依赖该信号重建内存态，
 * 否则硬刷新恢复会话 / 同页切换账号时会读到错误账号的布局。
 * ============================================================================ */

let uid = null

export function setUser(id) {
  uid = id
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('userkeys:uid-changed'))
  }
}

export function currentUid() { return uid }

/** base 加当前 uid 后缀；uid 未设置时原样返回（旧行为：未登录走全局键）。 */
export function ukey(base) { return uid ? `${base}:${uid}` : base }

/**
 * 一次性迁移（值原样搬运，不解析 —— 裸字符串键与 JSON 键都适用）：
 * 新键 ukey(base) 不存在且旧全局键 base 存在 → 复制到新键、删除旧键。
 * uid 未设置、新键已存在、旧键缺失、存储异常时都不动作。返回是否发生迁移。
 */
export function migrateKey(base) {
  const next = ukey(base)
  if (next === base) return false
  try {
    if (localStorage.getItem(next) != null) return false
    const raw = localStorage.getItem(base)
    if (raw == null) return false
    localStorage.setItem(next, raw)
    localStorage.removeItem(base)
    return true
  } catch {
    return false /* 隐私模式 / 配额满：放弃迁移，按不存在处理 */
  }
}

/**
 * 迁移读（JSON 语义）：等价于 `JSON.parse(localStorage.getItem(ukey(base)))`，
 * 但首读会先触发 migrateKey 的一次性迁移；不存在或解析失败返回 fallback。
 * fallback 由调用方每次传入字面量，返回后允许调用方持有/修改。
 */
export function readMigrated(base, fallback) {
  migrateKey(base)
  try {
    const raw = localStorage.getItem(ukey(base))
    return raw == null ? fallback : JSON.parse(raw)
  } catch {
    return fallback
  }
}
