import { defineConfig } from 'vitest/config'

/**
 * 前端只对**纯函数**做单元测试（格式化、标签映射）。
 *
 * 组件与页面的行为验证走"真后端 + 真浏览器"的端到端路径（见 docs/DECISIONS.md ADR-011），
 * 而不是在 jsdom 里 mock 一套假 API —— 那样测的是 mock，不是系统。
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
