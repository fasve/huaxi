import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// dev：默认代理本机 8000；联调临时实例时可用 API_TARGET=http://127.0.0.1:8010 npm run dev
const target = process.env.API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/api': { target, changeOrigin: true },
      // 静态图片资源（/static/poi/xxx.jpg）由后端提供
      '/static': { target, changeOrigin: true },
    },
  },
})
