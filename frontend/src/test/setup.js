import '@testing-library/jest-dom/vitest'

/* Node 的 fetch 不接受相对 URL，而 EChart 每次挂载都会 fetch('/china.json')。
   测试不校验地图内容，给一个空 FeatureCollection 即可，避免每个图表用例都
   打一条 "Invalid URL" 错误日志、把真正的问题淹掉。 */
const realFetch = globalThis.fetch
if (typeof realFetch === 'function') {
  globalThis.fetch = (input, init) =>
    input === '/china.json'
      ? Promise.resolve(new Response(
        JSON.stringify({ type: 'FeatureCollection', features: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ))
      : realFetch(input, init)
}

// jsdom 缺少的浏览器 API 补齐
if (typeof window !== 'undefined') {
  // ResizeObserver（部分图表/布局组件会用到）
  if (!window.ResizeObserver) {
    window.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
  // matchMedia（响应式组件用到）
  if (!window.matchMedia) {
    window.matchMedia = (query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })
  }
  // scrollIntoView
  if (!window.HTMLElement.prototype.scrollIntoView) {
    window.HTMLElement.prototype.scrollIntoView = () => {}
  }
}
