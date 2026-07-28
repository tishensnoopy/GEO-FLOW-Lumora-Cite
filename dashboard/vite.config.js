import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// P0 性能优化：构建配置
// - manualChunks: 拆分 vendor，利用浏览器缓存
// - chunkSizeWarningLimit: 提高阈值，避免大 chunk 警告
// - rollupOptions.output.manualChunks: 显式拆分 vue/element-plus/echarts
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
  resolve: { alias: { '@': '/src' } },
  build: {
    // 提高 chunk 大小警告阈值（默认 500KB，拆分后单个 chunk 仍可能较大）
    chunkSizeWarningLimit: 800,
    // 启用 CSS 代码分割
    cssCodeSplit: true,
    // 使用 esbuild 压缩（比 terser 快，且默认启用）
    minify: 'esbuild',
    // 目标浏览器：现代浏览器，启用更激进的优化
    target: 'es2020',
    rollupOptions: {
      output: {
        // 显式拆分 vendor，利用浏览器长期缓存
        manualChunks: {
          // Vue 核心（vue + vue-router + vuex）
          'vue-vendor': ['vue', 'vue-router', 'vuex'],
          // Element Plus UI 库（体积大，单独拆分）
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
          // ECharts 图表库（体积大，单独拆分）
          'echarts': ['echarts', 'vue-echarts'],
          // 工具库
          'utils': ['axios', 'dayjs'],
        },
        // chunk 文件名带 hash，便于长期缓存
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
      },
    },
  },
})
