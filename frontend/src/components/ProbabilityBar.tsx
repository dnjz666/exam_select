import type { Tier } from '../api/client'
import { formatInterval } from '../lib/format'
import { TIER_STYLE } from '../lib/labels'

export interface ProbabilityBarProps {
  /** ±1σ 概率区间（0–1）。来自后端 `probability_interval`。 */
  interval: readonly number[] | null | undefined
  tier: Tier
  /**
   * 分层边界（来自 `GET /meta/tiers`，禁止前端硬编码 10/40/75/93）。
   * 传入后会在轨道上画出分层刻度，帮助考生理解"这条区间落在哪一档"。
   */
  bounds?: Record<string, [number, number]> | null
  /** 紧凑模式（列表行使用） */
  compact?: boolean
}

/**
 * 概率区间条（AGENTS.md §8「概率永远显示为区间，不显示单一精确数字」）。
 *
 * 刻意**不画单点标记**：单点概率会诱导"精确"的错觉。
 * 轨道上只呈现区间带 + 分层刻度，文字也只输出区间。
 */
export function ProbabilityBar({ interval, tier, bounds, compact = false }: ProbabilityBarProps) {
  const style = TIER_STYLE[tier] ?? TIER_STYLE.NO_DATA
  const low = interval && interval.length >= 2 ? Math.min(interval[0] ?? 0, interval[1] ?? 0) : null
  const high = interval && interval.length >= 2 ? Math.max(interval[0] ?? 0, interval[1] ?? 0) : null

  const ticks: number[] = []
  if (bounds) {
    for (const range of Object.values(bounds)) {
      for (const value of range) {
        if (value > 0 && value < 1 && !ticks.includes(value)) ticks.push(value)
      }
    }
    ticks.sort((a, b) => a - b)
  }

  if (low === null || high === null) {
    return (
      <div className={compact ? 'text-xs text-slate-500' : 'text-sm text-slate-500'}>
        概率不可用（无可用历史数据，不做估算）
      </div>
    )
  }

  const left = `${(Math.max(0, low) * 100).toFixed(2)}%`
  const width = `${(Math.max(0, Math.min(1, high) - Math.max(0, low)) * 100).toFixed(2)}%`

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className={compact ? 'num text-sm font-semibold' : 'num text-base font-semibold'}>
          {formatInterval([low, high])}
        </span>
        <span className="text-xs text-slate-400">录取概率区间（±1σ）</span>
      </div>
      <div
        className={`relative mt-1.5 w-full overflow-hidden rounded-full bg-slate-100 ${compact ? 'h-2' : 'h-3'}`}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(((low + high) / 2) * 100)}
        aria-valuetext={`${formatInterval([low, high])}（${style.name}）`}
        aria-label="录取概率区间"
      >
        {ticks.map((tick) => (
          <span
            key={tick}
            className="absolute top-0 h-full w-px bg-slate-300"
            style={{ left: `${(tick * 100).toFixed(2)}%` }}
          />
        ))}
        <span
          className={`absolute top-0 h-full rounded-full ${style.fill}`}
          style={{ left, width }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-400">
        <span>0%</span>
        <span>50%</span>
        <span>100%</span>
      </div>
    </div>
  )
}
