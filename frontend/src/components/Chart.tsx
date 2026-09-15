import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { useEffect, useRef } from 'react'

// 按需注册（而不是 `import * as echarts from 'echarts'`）：只打包用到的图表与组件。
echarts.use([
  BarChart,
  LineChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

export interface ChartProps {
  option: EChartsCoreOption
  height?: number | string
  className?: string
  /** 无障碍标签：图表必须有无障碍替代说明（数字以表格形式同时可读）。 */
  ariaLabel: string
}

/**
 * ECharts 容器（AGENTS.md §4.1 指定 ECharts 画图）。
 *
 * 图表只承担"形状"（趋势 / 梯度分布）；**权威数字一律以表格或文本同时给出**，
 * 不让任何结论只存在于像素里。
 */
export function Chart({ option, height = 240, className, ariaLabel }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    const element = containerRef.current
    if (!element) return undefined
    const instance = echarts.init(element, undefined, { renderer: 'canvas' })
    chartRef.current = instance
    const observer = new ResizeObserver(() => instance.resize())
    observer.observe(element)
    return () => {
      observer.disconnect()
      instance.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(option, true)
  }, [option])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: '100%', height }}
      role="img"
      aria-label={ariaLabel}
    />
  )
}

export { echarts }
