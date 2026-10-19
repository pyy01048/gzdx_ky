import { useCallback, useEffect, useMemo, useState } from 'react'
import { favoritesApi } from '../api/client'

/* ---------------------------------------------------------------------------
 * 全站收藏状态 hook（S7）
 *
 * 设计要点：
 * 1. **进程内共享缓存** —— key = `${item_type}:${item_id}`。列表页渲染 50 项时
 *    不必为每行发一次 /check（N+1 请求），命中缓存直接渲染，未命中的批量补齐。
 * 2. **乐观更新** —— toggle 先改本地态再发请求，失败回滚。收藏是高频轻交互，
 *    等后端往返会让星标点上去有肉眼可见的延迟。
 * 3. **并发去重** —— 同一 key 在途请求复用同一 Promise，防止用户连点产生
 *    重复 toggle（后端虽幂等，但两次 toggle 会互相抵消，等于点了没反应）。
 * ------------------------------------------------------------------------- */

/** 模块级共享缓存：跨组件/跨页面复用，避免重复探测。 */
const sharedCache = new Map()
/** 在途请求表：key -> Promise，用于并发去重。 */
const inflight = new Map()
/** 批量探测单片上限：383 篇文档一次打完 URL 会过长，按片切分并发。
 *  （后端 _BATCH_MAX_IDS=1000，这里取更小值换取可控的 URL 长度） */
const PROBE_BATCH_SIZE = 200
/** 订阅者集合：任一处变更时通知所有 useFavorites 实例重渲染。 */
const listeners = new Set()

function keyOf(itemType, itemId) {
  return `${itemType}:${itemId}`
}

function notify() {
  listeners.forEach((fn) => fn())
}

function setCache(key, value) {
  sharedCache.set(key, value)
  notify()
}

/** 预置已知的收藏态（列表接口已带 favorited 字段时用，省掉一轮 check）。 */
export function primeFavorites(entries) {
  let changed = false
  for (const e of entries || []) {
    const k = keyOf(e.item_type, e.item_id)
    if (sharedCache.get(k) !== true) {
      sharedCache.set(k, true)
      changed = true
    }
  }
  if (changed) notify()
}

/** 清空缓存（切换账号 / 数据导入后调用）。 */
export function clearFavoriteCache() {
  sharedCache.clear()
  inflight.clear()
  notify()
}

/**
 * 单个实体的收藏态。
 *
 * @param {string} itemType document/question/error/kp/word/flashcard/link
 * @param {number|string} itemId 实体 ID
 * @returns {{ favorited: boolean, known: boolean, toggle: (meta?: object) => Promise<boolean> }}
 *          known=false 表示尚未探测过（首次渲染未知态），可据此显示空心星。
 */
export function useFavorite(itemType, itemId) {
  const key = useMemo(() => keyOf(itemType, itemId), [itemType, itemId])
  const [, forceRender] = useState(0)
  const rerender = useCallback(() => forceRender((n) => n + 1), [])

  // 订阅全局缓存变更；卸载时注销，否则组件反复挂载会累积 listener
  // （内存泄漏 + 无谓重渲染）。
  useEffect(() => {
    listeners.add(rerender)
    return () => {
      listeners.delete(rerender)
    }
  }, [rerender])

  const favorited = sharedCache.get(key) === true
  const known = sharedCache.has(key)

  const toggle = useCallback(
    async (meta) => {
      const prev = sharedCache.get(key) === true
      const next = !prev
      // 乐观更新
      setCache(key, next)
      try {
        const res = await favoritesApi.toggle({
          item_type: itemType,
          item_id: Number(itemId),
          title: meta?.title || '',
          snippet: meta?.snippet || null,
          meta: meta?.meta || null,
        })
        const server = Boolean(res?.favorited)
        if (server !== next) setCache(key, server)
        return server
      } catch (e) {
        // 回滚
        setCache(key, prev)
        throw e
      }
    },
    [key, itemType, itemId]
  )

  return { favorited, known, toggle }
}

/**
 * 批量探测收藏态（列表页用）。
 *
 * 只在缓存未命中时发请求，已命中的直接跳过 —— 这是本 hook 存在的
 * 主要理由：把 N 次 /check 压成"仅未命中项"的少量请求。
 *
 * P0-3：未命中项不再逐个 check，而是**按 item_type 分组 + 每 200 个一片**
 * 走 /favorites/check?ids= 批量接口。文档知识库 383 篇因此从 383 路并发
 * 降为 2 路（383/200），根除了打满 PG 连接池引发的全站 500。
 *
 * @param {Array<{item_type: string, item_id: number|string}>} items
 */
export function useFavoriteProbe(items) {
  const [, forceRender] = useState(0)
  const rerender = useCallback(() => forceRender((n) => n + 1), [])

  useEffect(() => {
    listeners.add(rerender)
    return () => {
      listeners.delete(rerender)
    }
  }, [rerender])

  const signature = useMemo(
    () => (items || []).map((i) => keyOf(i.item_type, i.item_id)).join('|'),
    [items]
  )

  const probe = useCallback(async () => {
    const miss = (items || []).filter((i) => !sharedCache.has(keyOf(i.item_type, i.item_id)))
    if (miss.length === 0) return

    // 按 item_type 归组：ids 参数是同一类型下的 ID 列表，跨类型必须分开请求
    const byType = new Map()
    for (const i of miss) {
      const bucket = byType.get(i.item_type) || []
      bucket.push(i.item_id)
      byType.set(i.item_type, bucket)
    }

    const jobs = []
    for (const [itemType, rawIds] of byType) {
      const uniq = [...new Set(rawIds.map((v) => Number(v)))]
      for (let s = 0; s < uniq.length; s += PROBE_BATCH_SIZE) {
        const chunk = uniq.slice(s, s + PROBE_BATCH_SIZE)
        const ck = `batch:${itemType}:${chunk.join(',')}`
        if (inflight.has(ck)) {
          jobs.push(inflight.get(ck))
          continue
        }
        const p = favoritesApi
          .checkMany(itemType, chunk)
          .then((r) => {
            const map = r?.map || {}
            for (const id of chunk) {
              sharedCache.set(keyOf(itemType, id), Boolean(map[String(id)]))
            }
            notify()
          })
          .catch(() => {
            // 探测失败不写缓存：下次挂载会重试，避免把"未知"固化成"未收藏"
            // 而让用户以为收藏丢了。这也是一个"静默失败不能污染状态"的实践。
          })
          .finally(() => inflight.delete(ck))
        inflight.set(ck, p)
        jobs.push(p)
      }
    }
    await Promise.all(jobs)
  }, [items, signature])

  return { probe, cache: sharedCache }
}
