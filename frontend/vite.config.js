import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// V3.0 前端工程配置（性能优化版）
export default defineConfig({
  plugins: [react()],
  base: './',
  test: {
    // E2: Vitest 前端 smoke 测试配置
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
    include: ['src/test/**/*.test.{js,jsx}'],
  },
  server: {
    host: true,
    port: 5173,
    open: false,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true }
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
  esbuild: {
    drop: ['console', 'debugger'],
  },
})
