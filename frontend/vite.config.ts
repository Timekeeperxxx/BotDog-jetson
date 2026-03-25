/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,  // 改变端口号，强制浏览器加载新代码
    strictPort: true,
    hmr: {
      overlay: true
    }
  },
  // 强制清除缓存
  cacheDir: 'node_modules/.vite',
  optimizeDeps: {
    force: true // 强制重新预构建依赖
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
    css: true,
  }
})
