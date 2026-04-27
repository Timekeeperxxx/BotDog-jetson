/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiBaseUrl = env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      port: 5174,  // 改变端口号，强制浏览器加载新代码
      strictPort: true,
      hmr: {
        overlay: true
      },
      proxy: {
        '/api': {
          target: apiBaseUrl,
          changeOrigin: true,
        },
        '/ws': {
          target: apiBaseUrl.replace(/^http/, 'ws'),
          changeOrigin: true,
          ws: true,
        },
      },
    },
    // 强制清除缓存
    cacheDir: 'node_modules/.vite',
    optimizeDeps: {
      force: true // 强制重新预构建依赖
    },
    build: {
      rollupOptions: {
        input: {
          main: resolve(__dirname, 'index.html'),
          navPatrol: resolve(__dirname, 'nav-patrol.html'),
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      globals: true,
      css: true,
    },
  }
})
