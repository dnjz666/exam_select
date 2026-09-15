import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * AGENTS.md §4.3 硬性规则 5：
 * - 前端 API 基址来自 `VITE_API_BASE_URL`，**禁止硬编码 localhost**；
 * - dev 环境用 Vite `server.proxy` 把 `/api` 转发到后端。
 *
 * 因此浏览器侧默认基址是**空字符串（同源）**，由下面的 proxy 承担转发；
 * 只有非 dev 部署才需要显式设置 `VITE_API_BASE_URL`。
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  // dev 代理目标只是本地开发配置，允许用环境变量覆盖，不写进任何业务代码。
  const devTarget = env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target: devTarget, changeOrigin: true },
        '/health': { target: devTarget, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      // ECharts 体量偏大，单独成 chunk，避免主包告警淹没真实问题
      rollupOptions: {
        output: {
          manualChunks: {
            echarts: ['echarts'],
            react: ['react', 'react-dom', 'react-router-dom'],
          },
        },
      },
    },
  }
})
