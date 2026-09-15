/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // 冲稳保垫色带（AGENTS.md §8.2「冲稳保色带」）。
        // 只在这里定义一次，组件通过 TIER_STYLE 引用，禁止各处硬编码色值。
        tier: {
          chong: '#f59e0b', // 冲 —— 琥珀
          wen: '#0284c7', // 稳 —— 天蓝
          bao: '#059669', // 保 —— 翠绿
          dian: '#4f46e5', // 垫 —— 靛蓝
          risky: '#e11d48', // 基本无望 —— 玫红
          nodata: '#64748b', // 无数据 —— 石板灰
        },
      },
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          '"Segoe UI"',
          '"Microsoft YaHei"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 23, 42, 0.06), 0 4px 12px rgba(15, 23, 42, 0.05)',
      },
    },
  },
  plugins: [],
}
