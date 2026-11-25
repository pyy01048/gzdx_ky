import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// PWA 图标（192 / 512 / maskable / apple-touch）位于 frontend/public/pwa/，
// 由 index.html 内联 SVG favicon（同一份品牌路径 + #0A84FF→#0062CC 渐变）
// 用无头 Chrome 按尺寸渲染而来，改 logo 时同步重出这套 PNG。
//
// ── HTTPS 前置条件（务必留意）───────────────────────────────────────────
// Service Worker 只在「安全上下文」下注册：https:// 或 localhost / 127.0.0.1。
// 当前生产是纯 http://60.204.223.140（IP 直连、无证书），手机通过 http + IP
// 访问时：SW 注册被浏览器拒绝 → 离线缓存不生效，Chrome「安装到主屏」入口
// 也不会出现。本文件与 main.jsx 里的 PWA 代码已就绪且与证书解耦，运维侧
// 一旦挂上 HTTPS（域名 + 证书），无需改前端代码即可自动获得：
//   · manifest.webmanifest → 安装到主屏（standalone 全屏 App）
//   · sw.js 预缓存 + 导航回退 index.html → 断网可打开已用过的页面
//   · 公开字典 API（/api/health、taxonomy、教材、院校等）NetworkFirst →
//     弱网/断网回退最近一次缓存；个人域 API 一律不缓存（P0-F02 换账号串号）
// ────────────────────────────────────────────────────────────────────────
/* P0（F-02）：个人 API 绝不进 Service Worker 缓存。
   采用「公开白名单」而非「个人黑名单」：黑名单会漏掉以后新增的按 uid 端点
   （/auth/me、/tasks、/errors、/favorites、/planner…），白名单是 fail-closed ——
   未显式列入的 /api/** 路径一律不缓存。只有不带身份的公开静态字典可离线回退。
   注意：urlPattern 的函数体被 workbox 原样注入 sw.js，不能引用本文件的外部
   变量/函数（不会随 worker 打包），白名单必须内联在函数体内。 */
const PWA_MANIFEST = {
  name: '硕途 · 考研学习平台',
  short_name: '硕途',
  description: '考研备考学习平台：倒计时与每日计划、单词间隔重复、章节刷题与真题、错题艾宾浩斯复习、院校库与资料，知识地图串联全流程，支持电脑 / 平板 / 手机三端，安装到主屏后离线可用。',
  lang: 'zh-CN',
  dir: 'ltr',
  // 相对口径：应用挂在域名根，但用 './' 便于以后迁到子目录不用改 manifest
  start_url: './',
  scope: './',
  id: './',
  display: 'standalone',
  display_override: ['standalone', 'minimal-ui', 'browser'],
  orientation: 'any',
  // 与 index.html 的 theme-color / tokens.css 首屏底色一致（深色由运行时改写）
  theme_color: '#F5F5F7',
  background_color: '#F5F5F7',
  icons: [
    { src: 'pwa/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
    { src: 'pwa/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
    { src: 'pwa/icon-maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
    { src: 'pwa/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
  ],
  shortcuts: [
    // start_url 走 hash 深链（HashRouter），路径均为 src/App.jsx 已注册的真实路由
    { name: '今日中枢', short_name: '今日', url: './#/hub' },
    { name: '章节刷题', short_name: '刷题', url: './#/quiz' },
    { name: '错题复盘', short_name: '错题', url: './#/error-review' },
    { name: '每日计划', short_name: '计划', url: './#/kaoyan/plan' },
  ],
}

// V3.0 前端工程配置（性能优化版）
// 使用函数式 config：区分 dev / build，避免 dev 也 drop console 掩盖报错
export default defineConfig(({ command }) => ({
  plugins: [
    react(),
    VitePWA({
      // 只在生产构建产出 SW：dev（vite serve）不注册，避免热更新被缓存干扰
      registerType: 'autoUpdate',
      injectRegister: false, // 注册入口在 src/main.jsx（virtual:pwa-register），关掉自动注入
      includeAssets: ['pwa/*.png', 'favicon.ico', 'fonts/*.woff2'],
      manifest: PWA_MANIFEST,
      workbox: {
        // 预缓存清单：构建产物（js/css/字体/图标/china.json）全部进 SW 缓存
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2,webmanifest,json}'],
        // EChart / pdfjs 懒加载 chunk 体积较大，放开 workbox 默认 2MiB 上限，
        // 否则这些 chunk 会被静默剔除出预缓存清单，离线时反而打不开。
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        // 离线打开 SPA：任何导航请求（含裸路径 /quiz → HashRouter 兼容跳转）
        // 回退到已缓存的 index.html；/api、/media 不参与导航回退。
        navigateFallback: 'index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/media\//],
        cleanupOutdatedCaches: true,
        // 与 registerType: 'autoUpdate' 配套：新版 SW 装好后立即接管当前页面，
        // 用户无需二次刷新（injectRegister:false 时插件不会自动补这两个开关）
        skipWaiting: true,
        clientsClaim: true,
        runtimeCaching: [
          {
            // 同源【公开字典】GET /api/**：优先走网络，超时或断网回退最近一次缓存。
            // 个人域（auth/tasks/errors/flashcards/notes/favorites/notebook/cards/
            // words/growth/user/profile/sync/hub/planner/goals…）不在白名单内，
            // 一个字节都不进 CacheStorage —— 换账号断网不可能看到上一个人的数据。
            urlPattern: ({ url, sameOrigin }) => {
              if (!sameOrigin) return false
              const p = url.pathname
              if (!p.startsWith('/api/')) return false
              return p === '/api/health'
                || p.startsWith('/api/taxonomy/')
                || p === '/api/textbooks'
                || p.startsWith('/api/textbooks/')
                || p === '/api/kaoyan/schools'
                || p.startsWith('/api/kaoyan/schools/')
                || p === '/api/documents/subjects'
            },
            method: 'GET',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              networkTimeoutSeconds: 10,
              expiration: { maxEntries: 200, maxAgeSeconds: 7 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // 题目配图 /media/**：图片不随版本变，CacheFirst + 容量上限
            urlPattern: ({ url, sameOrigin }) => sameOrigin && url.pathname.startsWith('/media/'),
            method: 'GET',
            handler: 'CacheFirst',
            options: {
              cacheName: 'media-cache',
              expiration: { maxEntries: 500, maxAgeSeconds: 30 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  // 绝对 base：应用始终挂在域名根（公网 IP / Tailscale），且存在 /admin/*
  // 多级路由。此前 base:'./' 让 index.html 以相对路径引用 bundle，
  // 在 /admin/users 等子路由下解析成 /admin/assets/...，被 SPA 回退成
  // HTML——模块脚本 MIME 报错、懒加载 chunk 竞态失败（采集页表格空）。
  // 运行时资源（china.json）本就是 '/china.json' 绝对口径，与此一致。
  base: '/',
  test: {
    // E2: Vitest 前端 smoke 测试配置
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
    include: ['src/test/**/*.test.{js,jsx}'],
    // 交互型用例（Quiz 统计口径 / 分页隔离开关等）单跑 1–6s，50 用例并行时
    // jsdom setup 高峰 3.5s+，默认 5s 超时在全量并发下假失败（audit P1-3 复现）。
    // 放宽到 20s：真回归断在该断言上，而不是资源抖动的 timer 上。
    testTimeout: 20000,
    // jsdom 默认 origin 是 about:blank，Web Storage 的 localStorage 在部分
    // Node/jsdom 组合下会直接抛 SecurityError。固定成 localhost 让持久化
    // 相关用例（收藏缓存、设置项）有真实的 storage 语义。
    environmentOptions: { jsdom: { url: 'http://localhost/' } },
  },
  server: {
    host: true,
    port: 5173,
    open: false,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      // 题目配图：后端把 images[].path 挂在 /media/images 下；开发态不代理就是裂图
      '/media': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    }
  },
  build: {
    // 双产物目录统一：构建直出后端挂载目录，废弃 frontend/dist（消除版本漂移）
    outDir: '../backend-main-fastapi/static',
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: false,
    minify: 'esbuild',
    cssMinify: true,
    // 首屏壳层与按需工具库分开；Mermaid 保留包内图形解析器的动态分块。
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replace(/\\/g, '/')
          if (normalized.includes('/src/v3/shell/') || normalized.includes('/src/v3/ui/') || normalized.includes('/src/components/UI')) {
            return 'app-shell'
          }
          if (!normalized.includes('/node_modules/')) return undefined
          if (/\/node_modules\/(react|react-dom|react-router-dom|scheduler)\//.test(normalized)) {
            return 'react-vendor'
          }
          if (/\/node_modules\/zustand\//.test(normalized)) return 'state-vendor'
          if (/\/node_modules\/(echarts|zrender)\//.test(normalized)) return 'charts-vendor'
          if (/\/node_modules\/pdfjs-dist\//.test(normalized)) return 'pdf-vendor'
          if (/\/node_modules\/mammoth\//.test(normalized)) return 'doc-vendor'
          if (/\/node_modules\/katex\//.test(normalized)) return 'math-vendor'
          if (/\/node_modules\/mathjs\//.test(normalized)) return 'mathjs-vendor'
          if (/\/node_modules\/elkjs\//.test(normalized)) return 'elk-vendor'
          if (/\/node_modules\/cytoscape/.test(normalized)) return 'graph-vendor'
          return undefined
        },
        chunkFileNames: 'assets/js/[name]-[hash].js',
        entryFileNames: 'assets/js/[name]-[hash].js',
        assetFileNames: 'assets/[ext]/[name]-[hash].[ext]',
      },
    },
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom', 'zustand'],
  },
  // 仅在「生产构建」时 drop console/debugger；dev 保留控制台输出，
  // 否则静默降级（catch 里的 console.warn/error）在开发期完全不可见。
  esbuild: {
    drop: command === 'build' ? ['console', 'debugger'] : [],
  },
}))
