/**
 * V3.0 前端性能优化工具
 * - 防抖/节流
 * - 请求缓存
 * - 预加载
 * - 懒加载
 * - 批量请求合并
 */

// ---------------------------------------------------------------------------
// 防抖
// ---------------------------------------------------------------------------
export function debounce(fn, delay = 300) {
  let timer = null
  return function (...args) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      fn.apply(this, args)
    }, delay)
  }
}

// ---------------------------------------------------------------------------
// 节流
// ---------------------------------------------------------------------------
export function throttle(fn, interval = 300) {
  let lastTime = 0
  return function (...args) {
    const now = Date.now()
    if (now - lastTime >= interval) {
      lastTime = now
      fn.apply(this, args)
    }
  }
}

// ---------------------------------------------------------------------------
// 请求缓存
// ---------------------------------------------------------------------------
class RequestCache {
  constructor(ttl = 60000) {
    this.cache = new Map()
    this.ttl = ttl
  }

  _makeKey(url, params) {
    return `${url}?${JSON.stringify(params || {})}`
  }

  get(url, params) {
    const key = this._makeKey(url, params)
    const entry = this.cache.get(key)
    if (!entry) return null
    if (Date.now() - entry.time > this.ttl) {
      this.cache.delete(key)
      return null
    }
    return entry.data
  }

  set(url, params, data) {
    const key = this._makeKey(url, params)
    this.cache.set(key, { data, time: Date.now() })
    // 限制缓存大小
    if (this.cache.size > 100) {
      const firstKey = this.cache.keys().next().value
      this.cache.delete(firstKey)
    }
  }

  clear() {
    this.cache.clear()
  }
}

export const requestCache = new RequestCache(60000) // 1分钟缓存

// ---------------------------------------------------------------------------
// 带缓存的请求
// ---------------------------------------------------------------------------
export async function cachedRequest(fetchFn, url, params, useCache = true) {
  if (useCache) {
    const cached = requestCache.get(url, params)
    if (cached) return cached
  }

  const data = await fetchFn(url, params)
  if (useCache && data) {
    requestCache.set(url, params, data)
  }
  return data
}

// ---------------------------------------------------------------------------
// 预加载
// ---------------------------------------------------------------------------
export function preloadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

export function preloadRoute(importFn) {
  // 预加载路由组件
  return importFn()
}

// ---------------------------------------------------------------------------
// 懒加载（Intersection Observer）
// ---------------------------------------------------------------------------
export function useLazyLoad(options = {}) {
  const {
    root = null,
    rootMargin = '100px',
    threshold = 0.1,
  } = options

  if (typeof IntersectionObserver === 'undefined') {
    return { observe: () => {}, unobserve: () => {} }
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const callback = entry.target._lazyCallback
          if (callback) {
            callback(entry.target)
            observer.unobserve(entry.target)
          }
        }
      })
    },
    { root, rootMargin, threshold }
  )

  return {
    observe: (el, callback) => {
      if (el) {
        el._lazyCallback = callback
        observer.observe(el)
      }
    },
    unobserve: (el) => {
      if (el) observer.unobserve(el)
    },
  }
}

// ---------------------------------------------------------------------------
// 批量请求合并
// ---------------------------------------------------------------------------
class BatchRequest {
  constructor(batchSize = 5, maxWait = 100) {
    this.batchSize = batchSize
    this.maxWait = maxWait
    this.queue = []
    this.timer = null
  }

  add(request) {
    return new Promise((resolve, reject) => {
      this.queue.push({ request, resolve, reject })
      if (this.queue.length >= this.batchSize) {
        this.flush()
      } else if (!this.timer) {
        this.timer = setTimeout(() => this.flush(), this.maxWait)
      }
    })
  }

  async flush() {
    if (this.queue.length === 0) return
    const batch = this.queue.splice(0, this.batchSize)
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }

    try {
      // 这里需要传入实际的批量处理函数
      // 由调用方实现
    } catch (error) {
      batch.forEach(({ reject }) => reject(error))
    }
  }
}

// ---------------------------------------------------------------------------
// 性能监控
// ---------------------------------------------------------------------------
export class PerformanceMonitor {
  constructor() {
    this.metrics = {
      pageLoad: 0,
      apiCalls: 0,
      apiTotalTime: 0,
      slowApis: [],
    }
  }

  recordPageLoad(time) {
    this.metrics.pageLoad = time
  }

  recordApiCall(url, time, success = true) {
    this.metrics.apiCalls++
    this.metrics.apiTotalTime += time
    if (time > 1000) {
      this.metrics.slowApis.push({ url, time, success })
      if (this.metrics.slowApis.length > 50) {
        this.metrics.slowApis = this.metrics.slowApis.slice(-50)
      }
    }
  }

  getStats() {
    return {
      ...this.metrics,
      avgApiTime: this.metrics.apiCalls > 0
        ? this.metrics.apiTotalTime / this.metrics.apiCalls
        : 0,
    }
  }
}

export const perfMonitor = new PerformanceMonitor()

// ---------------------------------------------------------------------------
// 记忆化（Memoize）
// ---------------------------------------------------------------------------
export function memoize(fn, keyFn) {
  const cache = new Map()
  return function (...args) {
    const key = keyFn ? keyFn(...args) : JSON.stringify(args)
    if (cache.has(key)) return cache.get(key)
    const result = fn.apply(this, args)
    cache.set(key, result)
    return result
  }
}

// ---------------------------------------------------------------------------
// 并行请求限制
// ---------------------------------------------------------------------------
export async function parallelLimit(tasks, limit = 3) {
  const results = []
  let index = 0

  async function worker() {
    while (index < tasks.length) {
      const currentIndex = index++
      try {
        results[currentIndex] = await tasks[currentIndex]()
      } catch (error) {
        results[currentIndex] = { error }
      }
    }
  }

  const workers = Array(Math.min(limit, tasks.length)).fill().map(worker)
  await Promise.all(workers)
  return results
}
