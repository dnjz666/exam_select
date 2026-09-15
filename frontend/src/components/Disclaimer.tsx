import type { TiersPayload } from '../api/client'
import { TIER_STYLE } from '../lib/labels'

/**
 * 免责声明（AGENTS.md §12）。
 *
 * 必须出现在：报告页、导出 PDF、Chat 首次回复。
 * 文案以后端 `/meta/tiers` 的 `disclaimer` 为权威来源；后端不可用时回落到本常量，
 * 保证"声明永远在"。
 */
export const FALLBACK_DISCLAIMER = '系统输出仅供参考，最终以各省考试院官方文件与招生章程为准。'

export const SIMULATION_NOTICE =
  '当前数据为**确定性模拟数据**（is_synthetic=1，院校名与专业名为公开信息，分数线/位次/计划数均为模拟值），' +
  '仅用于验证算法与流程，严禁用于真实志愿填报。'

export function Disclaimer({ text, extra }: { text?: string | null; extra?: boolean }) {
  return (
    <div className="callout-muted text-xs leading-relaxed">
      <p className="font-medium text-slate-700">免责声明</p>
      <p className="mt-1">{text || FALLBACK_DISCLAIMER}</p>
      {extra !== false && <p className="mt-1">{SIMULATION_NOTICE}</p>}
      <p className="mt-1">
        任何录取概率都以**区间**呈现，且不构成录取承诺；系统不连接任何省考试院填报接口，不代填、不代提交。
      </p>
    </div>
  )
}

/**
 * 分层图例：区间数字**来自后端** `/meta/tiers`（§6.3 是算法层参数，前端不得写死）。
 */
export function TierLegend({ tiers }: { tiers: TiersPayload | null }) {
  if (!tiers?.tiers?.length) return null
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {tiers.tiers.map((tier) => {
        const style = TIER_STYLE[tier.tier as keyof typeof TIER_STYLE]
        return (
          <li key={tier.tier} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: style?.hex ?? '#94a3b8' }}
              aria-hidden="true"
            />
            <span className="font-medium">{style?.name ?? tier.tier}</span>
            <span className="num text-slate-500">
              {(tier.low * 100).toFixed(0)}%–{(tier.high * 100).toFixed(0)}%
            </span>
            <span className="text-slate-400">{tier.meaning}</span>
          </li>
        )
      })}
    </ul>
  )
}
