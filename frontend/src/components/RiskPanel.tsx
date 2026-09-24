import type { Risk, RuleViolation } from '../api/client'
import { RISK_LEVEL_STYLE, riskCodeLabel } from '../lib/labels'

export interface RiskPanelProps {
  risks: readonly Risk[]
  /** 批次规则违规（后端 `rule.validate_plan` 输出）。 */
  violations?: readonly RuleViolation[]
  /** 点击风险时定位到对应志愿（可选）。 */
  onLocate?: (unitId: string) => void
  emptyHint?: string
}

/**
 * 风险面板（AGENTS.md §6.8 / §8.2）。
 *
 * 硬要求：**HIGH 级必须阻断式提示**——单独置顶、红色边框、不可折叠，
 * 并要求考生明确"我知道这个风险"才继续（由页面决定是否阻断导出）。
 *
 * 风险文案（`message` / `suggestion`）一律用**后端原文**：
 * 前端只负责分级展示，不复刻规则判断，避免出现两套口径。
 */
export function RiskPanel({ risks, violations = [], onLocate, emptyHint }: RiskPanelProps) {
  const high = risks.filter((risk) => risk.level === 'HIGH')
  const others = risks.filter((risk) => risk.level !== 'HIGH')

  if (!risks.length && !violations.length) {
    return (
      <p className="callout-info">
        {emptyHint ?? '当前没有扫描到风险项。这不代表"稳了"，只是算法未命中已知风险规则。'}
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {high.length > 0 && (
        <div className="blocking-banner" role="alert" aria-live="assertive">
          <p className="blocking-banner-title">
            <span aria-hidden="true">⛔</span>
            必须先处理这 {high.length} 个高风险项
          </p>
          <ul className="mt-3 space-y-3">
            {high.map((risk, index) => (
              <li key={`${risk.code}-${risk.unit_id ?? index}`} className="rounded-lg bg-white/70 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`chip ${RISK_LEVEL_STYLE['HIGH']?.badge ?? ''}`}>
                    {riskCodeLabel(risk.code)}
                  </span>
                  {risk.unit_id && onLocate && (
                    <button
                      type="button"
                      className="btn-ghost !px-2 !py-0.5 text-xs"
                      onClick={() => onLocate(risk.unit_id as string)}
                    >
                      定位到该志愿
                    </button>
                  )}
                </div>
                <p className="mt-2 text-sm text-rose-900">{risk.message}</p>
                <p className="mt-1 text-sm font-medium text-rose-800">建议：{risk.suggestion}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {others.length > 0 && (
        <ul className="space-y-2">
          {others.map((risk, index) => {
            const style = RISK_LEVEL_STYLE[risk.level] ?? RISK_LEVEL_STYLE['LOW']!
            return (
              <li
                key={`${risk.code}-${risk.unit_id ?? index}`}
                className="rounded-lg border border-slate-200 p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`chip ${style.badge}`}>{style.label}</span>
                  <span className="text-sm font-medium text-slate-700">{riskCodeLabel(risk.code)}</span>
                </div>
                <p className="mt-1.5 text-sm text-slate-600">{risk.message}</p>
                <p className="mt-0.5 text-sm text-slate-500">建议：{risk.suggestion}</p>
              </li>
            )
          })}
        </ul>
      )}

      {violations.length > 0 && (
        <div className="callout-danger">
          <p className="font-medium">规则校验未通过（{violations.length} 项）</p>
          <ul className="mt-1 space-y-1 text-xs">
            {violations.map((violation, index) => (
              <li key={`${violation.code}-${index}`}>
                {violation.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
