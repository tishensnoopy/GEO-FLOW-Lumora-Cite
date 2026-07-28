import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api/v1': {
        target: 'http://localhost:8090',
        changeOrigin: true
      },
      '/sso': {
        target: 'http://localhost:8090',
        changeOrigin: true
      }
    }
  },
  resolve: { alias: { '@': '/src' } }
})
