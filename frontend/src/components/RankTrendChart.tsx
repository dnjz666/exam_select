import type { EChartsCoreOption } from 'echarts/core'
import { useMemo } from 'react'

import type { HistoryEvidence } from '../api/client'
import { formatRank } from '../lib/format'
import { TIER_STYLE } from '../lib/labels'
import { Chart } from './Chart'

export interface RankTrendChartProps {
  evidence: readonly HistoryEvidence[]
  /** 考生位次：作为参考线画出（位次数值越小越靠前，纵轴已反转）。 */
  studentRank?: number | null
  height?: number
}

/**
 * 位次趋势微图（AGENTS.md §8.2「位次趋势微图」）。
 *
 * 两个刻意的设计：
 * 1. **纵轴反转**：`yAxis.inverse = true`。位次数值越小越靠前 = 越难考，
 *    反转后"曲线越高 = 门槛越高"，符合直觉，避免把方向看反（DOMAIN_RULES §2.1 的方向陷阱）。
 * 2. 只画**本单位历史**；类比证据不进趋势图（那是别的单位的数据，画在一起就是误导）。
 */
export function RankTrendChart({ evidence, studentRank, height = 200 }: RankTrendChartProps) {
  const own = useMemo(() => evidence.filter((entry) => !entry.note), [evidence])

  const option = useMemo<EChartsCoreOption>(() => {
    const points = own
      .filter((entry) => typeof entry.min_rank === 'number')
      .slice()
      .sort((a, b) => a.year - b.year)

    const years = points.map((entry) => String(entry.year))
    const ranks = points.map((entry) => entry.min_rank as number)
    const collected = points.map((entry) => entry.is_collected ?? false)

    return {
      grid: { left: 8, right: 16, top: 24, bottom: 4, containLabel: true },
      tooltip: {
        trigger: 'axis',
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params]
          const first = list[0] as { axisValue?: string; data?: number } | undefined
          if (!first) return ''
          const rank = first.data
          return `${first.axisValue} 年<br/>最低位次 <b>${formatRank(rank ?? null)}</b>`
        },
      },
      xAxis: {
        type: 'category',
        data: years,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#cbd5e1' } },
        axisLabel: { color: '#64748b' },
      },
      yAxis: {
        type: 'value',
        inverse: true, // 位次数值越小越靠前 → 反转后"越高越难考"
        scale: true,
        name: '最低位次',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: {
          color: '#64748b',
          formatter: (value: number) => formatRank(value),
        },
        splitLine: { lineStyle: { color: '#f1f5f9' } },
      },
      series: [
        {
          type: 'line',
          smooth: false,
          symbolSize: 8,
          data: ranks.map((rank, index) => ({
            value: rank,
            itemStyle: { color: collected[index] ? TIER_STYLE.CHONG.hex : TIER_STYLE.WEN.hex },
          })),
          lineStyle: { color: TIER_STYLE.WEN.hex, width: 2 },
          markLine:
            typeof studentRank === 'number'
              ? {
                  silent: true,
                  symbol: 'none',
                  label: {
                    formatter: `你的位次 ${formatRank(studentRank)}`,
                    position: 'insideEndTop',
                    color: '#0f766e',
                    fontSize: 11,
                  },
                  lineStyle: { color: TIER_STYLE.BAO.hex, type: 'dashed', width: 1.5 },
                  data: [{ yAxis: studentRank }],
                }
              : undefined,
        },
      ],
    }
  }, [own, studentRank])

  if (!own.some((entry) => typeof entry.min_rank === 'number')) {
    return (
      <p className="callout-muted">
        没有本单位历史位次可画趋势。新增专业请参考下方「类比证据」，并按低置信度看待。
      </p>
    )
  }

  return (
    <div>
      <Chart
        option={option}
        height={height}
        ariaLabel="本单位历年最低位次趋势折线图；具体数值见下方历史证据表"
      />
      <p className="mt-1 text-xs text-slate-400">
        纵轴已反转：曲线越高代表门槛越高（位次数值越小越靠前）。橙色点为征集志愿年份，线偏低不可当常态。
      </p>
    </div>
  )
}
