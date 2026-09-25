import type { EChartsCoreOption } from 'echarts/core'
import { useMemo } from 'react'

import { TIER_ORDER, TIER_STYLE } from '../lib/labels'
import { Chart } from './Chart'

export interface GradientChartProps {
  distribution: Record<string, number> | null | undefined
  /** 该批次的志愿上限（来自后端规则，禁止前端写死 80/96/24…）。 */
  maxVolunteers?: number | null
  height?: number
  onTierClick?: (tier: string) => void
}

const CHART_TIERS = TIER_ORDER.filter((tier) => tier !== 'NO_DATA')

/**
 * 梯度分布柱状图（AGENTS.md §8.2「梯度分布柱状图」）。
 *
 * 只画**实际分布**，不叠"理想配额"的假想线：M3 实测中 BAO 常被安全闸门降级为 WEN，
 * 配额比例不会精确成立（见 HANDOVER §6），画一条理想线只会误导。
 * 缺口提示由文本与风险面板承担。
 */
export function GradientChart({ distribution, maxVolunteers, height = 200, onTierClick }: GradientChartProps) {
  const counts = useMemo(() => distribution ?? {}, [distribution])
  const option = useMemo<EChartsCoreOption>(() => {
    return {
      grid: { left: 8, right: 16, top: 24, bottom: 4, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: {
        type: 'category',
        data: CHART_TIERS.map((tier) => TIER_STYLE[tier].name),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#cbd5e1' } },
        axisLabel: { color: '#64748b' },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        name: '志愿数',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: { color: '#64748b' },
        splitLine: { lineStyle: { color: '#f1f5f9' } },
      },
      series: [
        {
          type: 'bar',
          barMaxWidth: 44,
          data: CHART_TIERS.map((tier) => ({
            value: counts[tier] ?? 0,
            itemStyle: { color: TIER_STYLE[tier].hex, borderRadius: [4, 4, 0, 0], cursor: 'pointer' },
          })),
          label: { show: true, position: 'top', color: '#475569' },
        },
      ],
    }
  }, [counts])

  const handleDataClick = useMemo(
    () => (dataIndex: number) => {
      const tier = CHART_TIERS[dataIndex]
      if (tier) onTierClick?.(tier)
    },
    [onTierClick],
  )

  return (
    <div>
      <Chart
        option={option}
        height={height}
        ariaLabel="志愿表冲稳保垫分层分布柱状图，点击柱子定位到该档第一个志愿"
        onDataClick={onTierClick ? handleDataClick : undefined}
      />
      {onTierClick && (
        <div className="mt-2 flex flex-wrap gap-2" aria-label="按梯度定位志愿">
          {CHART_TIERS.map((tier) => {
            const count = counts[tier] ?? 0
            return (
              <button
                key={tier}
                type="button"
                className="btn-ghost"
                disabled={count === 0}
                onClick={() => onTierClick(tier)}
                aria-label={`定位到${TIER_STYLE[tier].name}档第一个志愿，共${count}个`}
              >
                {TIER_STYLE[tier].name} {count}
              </button>
            )
          })}
        </div>
      )}
      {typeof maxVolunteers === 'number' && (
        <p className="mt-1 text-xs text-slate-400">
          本批次最多可填 {maxVolunteers} 个志愿；当前共{' '}
          {Object.values(counts).reduce((sum, count) => sum + count, 0)} 个。
        </p>
      )}
    </div>
  )
}
