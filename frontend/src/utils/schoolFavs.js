/* ============================================================================
 * 院校收藏 · 统一本机存储（P2 双键分裂修复）
 *
 * 历史：院校列表页（KaoyanSchools）写 `ky_fav_school_ids`（id 数组），
 * 院校详情页（KaoyanSchoolDetail）写 `kaoyan-fav-schools`（{id:{name,level}}）。
 * 同一台机器上两页各存各的 —— 列表页点的星，详情页不认，反之亦然。
 *
 * 统一到 `kaoyan-fav-schools`（map 形态，信息量更大且详情页已在用）：
 *   - readSchoolFavs()：readMigrated 读新键（含旧全局裸键 → uid 键迁移），
 *     再把旧 `ky_fav_school_ids`（裸键或 uid 键）里的 id **一次性并集**进来
 *     （只有 id 没有名称的补空对象，详情页据真值判断收藏态），随后删除旧键；
 *   - writeSchoolFavs(map)：按当前账号（ukey）落盘。
 * 两页同源后，任何一页的收藏动作另一页立即可见（同一 localStorage 键）。
 * ============================================================================ */
import { ukey, readMigrated, migrateKey } from './userKeys'

export const SCHOOL_FAV_KEY = 'kaoyan-fav-schools'
const LEGACY_IDS_KEY = 'ky_fav_school_ids'

/** 读收藏 map：{ [String(id)]: { name?, level? } }。含旧键一次性迁移。 */
export function readSchoolFavs() {
  const raw = readMigrated(SCHOOL_FAV_KEY, {})
  const map = raw && typeof raw === 'object' && !Array.isArray(raw) ? { ...raw } : {}

  /* 旧 id 数组键：先把裸键迁到当前 uid 命名空间，再读出并集进 map */
  migrateKey(LEGACY_IDS_KEY)
  let legacy = null
  try {
    const rawIds = localStorage.getItem(ukey(LEGACY_IDS_KEY))
    legacy = rawIds == null ? null : JSON.parse(rawIds)
  } catch {
    legacy = null
  }
  if (Array.isArray(legacy)) {
    let changed = false
    for (const id of legacy) {
      const k = String(id)
      if (!(k in map)) {
        map[k] = {} /* 旧键只有 id：名称/层次留空，详情页收藏态按真值判断 */
        changed = true
      }
    }
    if (changed) writeSchoolFavs(map)
    try { localStorage.removeItem(ukey(LEGACY_IDS_KEY)) } catch { /* 隐私模式 */ }
  }
  return map
}

/** 写收藏 map（按当前账号隔离）。 */
export function writeSchoolFavs(map) {
  try {
    localStorage.setItem(ukey(SCHOOL_FAV_KEY), JSON.stringify(map))
  } catch { /* 隐私模式 / 配额满：内存态仍可用 */ }
}
