/* ============================================================================
 * 收藏统一桥（题库侧 → 后端 favorites 表）
 *
 * 背景：全站曾有三套互不相通的收藏
 *   1. 题库侧  localStorage `quiz_favorites_v9`（{ qid: {content,subject,chapter,type} }）
 *   2. 院校侧  localStorage `kaoyan-fav-schools`
 *   3. 后端     S7 新增的 favorites 表（/api/favorites）
 * 后果：用户在刷题页收藏的题，在「我的收藏」页看不到 —— 数据分裂。
 *
 * 策略（为什么不做成纯异步）：
 *   题库侧现有 4 个组件消费的都是**同步** `loadFavs()`（渲染期直接读 map），
 *   改成异步要牵动 QuizPractice / QuizHome / Quiz 多处渲染逻辑，回归风险大。
 *   因此这里保留 localStorage 作为**同步读缓存**，但把**真相源换成后端**：
 *
 *   - `hydrate()`：挂载时拉后端全量 → 与本地取**并集**合并。
 *     只增不删：本地有而后端无的，恰恰是"历史未同步"的收藏，
 *     覆盖式写入会把它们抹掉（等于用户收藏凭空消失）。
 *   - `migrateLocal()`：把「本地有、后端无」的一次性推上去，完成历史迁移。
 *   - `push()`：toggle 后异步推后端；失败只记待重试，不动本地态
 *     （本地是 UI 的即时反馈源，不能因为网络抖动就回滚用户操作）。
 * ========================================================================== */

import { favoritesApi } from './client'
import { ukey, currentUid, readMigrated } from '../utils/userKeys'

/* P4：两键均按登录账号隔离（实际读写 `quiz_favorites_v9:{uid}`），
   首读时 readMigrated 把旧全局键一次性迁给当前用户并删旧键。 */
const FAV_KEY = 'quiz_favorites_v9'
const ITEM_TYPE = 'question'

/** 内存镜像：避免每次渲染都 JSON.parse localStorage。 */
let cache = null
/** cache/synced 建立时的 uid（P4）：账号切换后内存镜像必须作废重建，
 *  否则上一个账号的收藏会串号显示给当前用户。 */
let cacheUid = null
/** 已成功同步到后端的 qid 集合，用于判断"本地有但后端无"（迁移用）。 */
let synced = null
/** synced 建立时的 uid，语义同 cacheUid。 */
let syncedUid = null
const SYNCED_KEY = 'quiz_favorites_v9_synced'
/** 推送失败、待重试的 qid。 */
const pending = new Set()

function writeLS(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 隐私模式 / 配额满：静默降级为纯内存态 */
  }
}

/** 同步读（签名与旧 loadFavs 完全一致，调用方零改动）。
 *  P4：uid 变化（登录/登出/切号）即作废重建镜像，防止串号。 */
export function loadFavs() {
  if (cache === null || cacheUid !== currentUid()) {
    cache = readMigrated(FAV_KEY, {})
    cacheUid = currentUid()
  }
  return cache
}

/** 同步写（签名与旧 saveFavs 一致）+ 顺带把变更推后端。 */
export function saveFavs(next) {
  const prev = loadFavs()
  cache = next
  cacheUid = currentUid()
  writeLS(ukey(FAV_KEY), next)

  // 差集推送：只处理本次真正变化的 id，避免每次全量推
  const ids = new Set([...Object.keys(prev), ...Object.keys(next)])
  for (const id of ids) {
    const was = !!prev[id]
    const now = !!next[id]
    if (was === now) continue
    if (now) pushFav(id, next[id])
    else removeFav(id)
  }
}

/** 收藏态同步给后端（后台，不阻塞 UI）。 */
export function pushFav(qid, snapshot) {
  if (!qid) return
  const body = {
    item_type: ITEM_TYPE,
    item_id: Number(qid),
    title: (snapshot?.content || '').slice(0, 200),
    snippet: (snapshot?.content || '').slice(0, 500),
    meta: {
      subject: snapshot?.subject || '',
      chapter: snapshot?.chapter || '',
      type: snapshot?.type || '',
      source: 'quiz',
    },
  }
  if (!Number.isFinite(body.item_id)) return
  favoritesApi
    .add(body)
    .then(() => {
      pending.delete(String(qid))
      markSynced(qid)
    })
    .catch(() => {
      // 不弹 toast：收藏的即时反馈由本地态负责，网络失败不该打断刷题节奏。
      // 记进 pending，下次 hydrate / 迁移时补推。
      pending.add(String(qid))
    })
}

/** 取消收藏同步给后端。 */
export function removeFav(qid) {
  const id = Number(qid)
  if (!Number.isFinite(id)) return
  favoritesApi
    .remove(ITEM_TYPE, id)
    .then(() => unmarkSynced(qid))
    .catch(() => {
      /* 后端本来就没有这条也要视为成功语义 —— DELETE 404 无副作用 */
      unmarkSynced(qid)
    })
}

function readSynced() {
  if (synced === null || syncedUid !== currentUid()) {
    synced = readMigrated(SYNCED_KEY, {})
    syncedUid = currentUid()
  }
  return synced
}

function markSynced(qid) {
  const m = readSynced()
  m[String(qid)] = 1
  synced = m
  syncedUid = currentUid()
  writeLS(ukey(SYNCED_KEY), m)
}

function unmarkSynced(qid) {
  const m = readSynced()
  delete m[String(qid)]
  synced = m
  syncedUid = currentUid()
  writeLS(ukey(SYNCED_KEY), m)
}

/**
 * 从后端拉全量并**并集**合并回本地缓存。
 *
 * @returns {Promise<{serverCount:number, localOnly:number}>}
 *          localOnly>0 表示存在历史未同步的收藏，可继续调 migrateLocal()。
 */
export async function hydrateFavs() {
  const local = loadFavs()
  let items = []
  try {
    // 后端上限 200/页；收藏量级是个人级，一页足够。若真超了，
    // 分页拉取也不会丢 —— 这里保守只拉第一页但**不做删除**，
    // 超出的本地项仍保留在缓存里。
    const res = await favoritesApi.list({ item_type: ITEM_TYPE, limit: 200 })
    items = res?.items || []
  } catch {
    return { serverCount: 0, localOnly: 0 } // 后端不可用：保留本地态，纯离线可用
  }

  const merged = { ...local }
  let added = 0
  for (const it of items) {
    const key = String(it.item_id)
    markSynced(key)
    if (!merged[key]) {
      // 后端有、本地无 → 补进本地（另一台设备 / 后端页加的收藏）
      merged[key] = {
        content: it.title || '',
        subject: it.meta?.subject || '',
        chapter: it.meta?.chapter || '',
        type: it.meta?.type || '',
      }
      added += 1
    }
  }
  if (added) {
    cache = merged
    cacheUid = currentUid()
    writeLS(ukey(FAV_KEY), merged)
  }

  const syncedMap = readSynced()
  const localOnly = Object.keys(merged).filter(
    (k) => !syncedMap[k] || pending.has(k)
  ).length
  return { serverCount: items.length, localOnly }
}

/** 把「本地有、后端无」的历史收藏一次性推上去。 */
export async function migrateLocalFavs() {
  const local = loadFavs()
  const syncedMap = readSynced()
  const todo = Object.keys(local).filter((k) => !syncedMap[k] || pending.has(k))
  let ok = 0
  for (const k of todo) {
    try {
      // 串行推送：收藏量级不大，且避免瞬时并发打爆后端
      // eslint-disable-next-line no-await-in-loop
      await favoritesApi.add({
        item_type: ITEM_TYPE,
        item_id: Number(k),
        title: (local[k]?.content || '').slice(0, 200),
        snippet: (local[k]?.content || '').slice(0, 500),
        meta: {
          subject: local[k]?.subject || '',
          chapter: local[k]?.chapter || '',
          type: local[k]?.type || '',
          source: 'quiz-migrated',
        },
      })
      markSynced(k)
      pending.delete(String(k))
      ok += 1
    } catch {
      pending.add(String(k))
    }
  }
  return { total: todo.length, migrated: ok }
}

/** 仅供测试：重置内存态。 */
export function __resetFavCache() {
  cache = null
  cacheUid = null
  synced = null
  syncedUid = null
  pending.clear()
}
