import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 统一数据请求三态 hook：loading / error / empty。
 *
 * 存在的理由：走查发现多个页面在接口异常/空数据时直接白屏，而各页面
 * 自己拼的 useState + try/catch 模板口径不一（有的吞错、有的不重置
 * loading、有的卸载后 setState）。这里收敛成一处实现，主要数据页共用。
 *
 * 用法：
 *   const { data, loading, error, isEmpty, reload } = useApiData(
 *     () => documentsApi.list({ stage }),
 *     { deps: [stage] },
 *   )
 *
 * 约定：
 *   - data：成功值为响应体；后端 2xx 无 JSON 体（client.js resolve(null)）
 *     或 undefined 一律归一为 null，调用方可用 isEmpty 判空；
 *   - error：失败时为 ApiError.message（已由 client.js 透传 FastAPI detail）；
 *   - reload：手动重试（切筛选/刷新按钮复用），不会重复触发首次加载逻辑；
 *   - 卸载后不再 setState（aliveRef），避免 React 警告与竞态。
 *
 * @param {() => Promise<any>} fetcher 请求函数（变化时不会自动重跑，请传稳定引用）
 * @param {object} [options]
 * @param {any[]} [options.deps=[]] 依赖变化时自动重新请求（语义同 useEffect）
 * @param {boolean} [options.immediate=true] 是否挂载即请求
 * @param {(err: Error) => void} [options.onError] 失败回调（toast 等副作用）
 */
export default function useApiData(fetcher, options = {}) {
  const { deps = [], immediate = true, onError } = options

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(immediate)
  const [error, setError] = useState('')

  const aliveRef = useRef(true)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError

  const run = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const d = await fetcherRef.current()
      if (!aliveRef.current) return false
      // undefined / null 归一为 null：client.js 对无 JSON 体的 2xx 返回 null，
      // 下游判空只须认 null 一种形态，不必同时防 undefined。
      setData(d === undefined ? null : d)
      return true
    } catch (e) {
      if (!aliveRef.current) return false
      setError(e?.message || '加载失败，请稍后重试')
      onErrorRef.current?.(e)
      return false
    } finally {
      if (aliveRef.current) setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    aliveRef.current = true
    if (immediate) run()
    return () => { aliveRef.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  const isEmpty = !loading && !error && data == null

  return { data, loading, error, isEmpty, reload: run, setData }
}
