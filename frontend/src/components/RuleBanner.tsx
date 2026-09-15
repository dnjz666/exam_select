import type { RuleBlock } from '../api/client'
import { UNIT_TYPE_LABEL, verifiedStyle } from '../lib/labels'
import { SourceLink } from './StateBlocks'

export interface RuleBannerProps {
  rule: RuleBlock | null | undefined
  /** 后端 `warnings` 里与规则来源有关的条目（本组件只展示，不自行判断红线）。 */
  warnings?: readonly string[]
  compact?: boolean
}

/**
 * 批次规则横幅（AGENTS.md §8.1 Step 1：选中省份后**立即**显示投档模式与核实徽标）。
 *
 * 红线：`requires_banner` 为真时必须醒目提示"规则待核实，不得用于真实填报"。
 * 该布尔量由**后端**计算（`meta_service`），前端绝不用 `verified_status` 自行推断——
 * 口径必须只有一处。
 */
export function RuleBanner({ rule, warnings = [], compact = false }: RuleBannerProps) {
  if (!rule) {
    return <p className="callout-muted">暂无批次规则信息。</p>
  }
  const verified = verifiedStyle(rule.verified_status)

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      {rule.requires_banner && (
        <div className="blocking-banner" role="alert">
          <p className="blocking-banner-title">
            <span aria-hidden="true">⛔</span>
            该省规则待核实 —— 不得用于真实填报
          </p>
          <p className="mt-2 text-sm text-rose-900">
            本省全部批次的规则来源未达官方原文等级（当前为「{verified.label}」）。
            系统仍可用于了解投档模式与算法逻辑，但**请勿据此填报真实志愿**；
            最终以省考试院官方文件与招生章程为准。
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <span className="font-medium text-slate-800">{rule.batch_name}</span>
        <span className="chip-slate">{UNIT_TYPE_LABEL[rule.unit_type] ?? rule.unit_type}</span>
        <span className="chip-slate">最多 {rule.max_volunteers} 个志愿</span>
        {typeof rule.majors_per_group === 'number' && (
          <span className="chip-slate">每组 {rule.majors_per_group} 个专业</span>
        )}
        <span className={`chip ${verified.badge}`}>{verified.label}</span>
        {rule.verified_year && <span className="text-xs text-slate-500">核实年份 {rule.verified_year}</span>}
        <span className="text-xs text-slate-500">
          {rule.is_parallel ? '平行志愿（检索按填报顺序）' : '顺序志愿（第一志愿权重极高）'}
        </span>
      </div>

      {/*
        调剂选项的显隐由 unit_type 决定：专业+院校模式**不存在**调剂概念（AGENTS.md §8.1）。
        这里用 has_major_adjustment（后端规则字段），而不是前端按省份名判断。
      */}
      <p className="text-xs text-slate-500">
        {rule.has_major_adjustment
          ? '该批次有「服从专业调剂」选项：不服从调剂 = 主动接受退档风险，务必逐条确认。'
          : '该批次为「专业(类)+院校」模式，不存在专业调剂概念，因此界面不显示调剂选项。'}
      </p>

      {warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-800">
          {warnings.map((warning) => (
            <li key={warning}>⚠ {warning}</li>
          ))}
        </ul>
      )}

      <p className="text-xs text-slate-500">
        规则来源：<SourceLink url={rule.source_url} label="查看官方原文" />
      </p>
    </div>
  )
}
