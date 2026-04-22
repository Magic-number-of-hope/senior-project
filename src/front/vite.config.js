import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendPort = process.env.VITE_BACKEND_PORT || process.env.VUE_APP_BACKEND_PORT || '8010'
const httpTarget = `http://localhost:${backendPort}`

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: 'localhost',
    port: 5173,
    proxy: {
      '/api': {
        target: httpTarget,
        changeOrigin: true
      },
      '/ws': {
        target: httpTarget,
        ws: true,
        changeOrigin: true
      }
    }
  },
  preview: {
    host: 'localhost',
    port: 4173
  }
})
