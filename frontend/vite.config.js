import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// V3.0 前端工程配置（性能优化版）
// 使用函数式 config：区分 dev / build，避免 dev 也 drop console 掩盖报错
export default defineConfig(({ command }) => ({
  plugins: [react()],
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
    // 批次2-7（P2-4）：回调默认 500，让真实超大 chunk（EChart / pdfjs）显式告警
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'state-vendor': ['zustand'],
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
