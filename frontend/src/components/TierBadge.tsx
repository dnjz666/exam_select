import type { Confidence, Tier } from '../api/client'
import { CONFIDENCE_STYLE, TIER_STYLE } from '../lib/labels'

export interface TierBadgeProps {
  tier: Tier
  confidence?: Confidence | null
  className?: string
}

/**
 * 冲/稳/保/垫 徽标。
 *
 * 只表达**分层**（来自后端 `tier`），概率一律由 `ProbabilityBar` 以区间呈现。
 * 前端不重新计算分层——分层含有"真保底安全闸门"这类算法语义，不能在前端复刻。
 */
export function TierBadge({ tier, confidence, className = '' }: TierBadgeProps) {
  const style = TIER_STYLE[tier] ?? TIER_STYLE.NO_DATA
  const confidenceStyle = confidence ? CONFIDENCE_STYLE[confidence] : null
  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      <span className={`chip ${style.badge}`} title={style.hint}>
        {style.label}
      </span>
      {confidenceStyle && (
        <span className={`chip ${confidenceStyle.badge}`} title={confidenceStyle.hint}>
          {confidenceStyle.label}
        </span>
      )}
    </span>
  )
}
