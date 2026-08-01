import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Self-Agent Web 前端配置
// 开发时通过代理转发到后端，避免 CORS 问题
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 代理 /api 到后端 FastAPI（默认 8000）
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
