import type { HistoryEvidence } from '../api/client'
import { formatNumber, formatPlanCount, formatRank, formatScore } from '../lib/format'
import { SourceLink } from './StateBlocks'

/** 数据质量标注（DOMAIN_RULES §2.2）。 */
const QUALITY_LABEL: Record<string, { text: string; className: string }> = {
  OK: { text: '记录完整', className: 'text-slate-500' },
  DERIVED: { text: '由分数反查（降权 0.9）', className: 'text-amber-700' },
  COLLECTED: { text: '征集志愿（线偏低）', className: 'text-amber-700' },
  MISSING_RANK: { text: '缺位次', className: 'text-rose-700' },
  SUSPECT: { text: '数据存疑', className: 'text-rose-700' },
}

export interface EvidenceTableProps {
  evidence: readonly HistoryEvidence[]
  /** 考生位次（用于直观对照"比切线靠前/靠后多少"）。 */
  studentRank?: number | null
}

/**
 * 历史证据表（AGENTS.md §8.2：每个推荐卡片必须能展开看历史证据表）。
 *
 * 关键设计：**区分"本单位历史"与"类比证据"**。
 * 新增专业没有本单位历史，概率来自 Step 0 的同类单位类比（`note` 字段标注），
 * 两者不能混在一张表里让人误以为是本校往年数据。
 */
export function EvidenceTable({ evidence, studentRank }: EvidenceTableProps) {
  if (!evidence.length) {
    return (
      <p className="callout-muted">
        没有可展示的历史证据。按契约要求，无证据链的结果不会进入推荐列表。
      </p>
    )
  }

  const own = evidence.filter((entry) => !entry.note)
  const analog = evidence.filter((entry) => Boolean(entry.note))

  return (
    <div className="space-y-3">
      {own.length > 0 && (
        <div className="overflow-x-auto">
          <table className="data-table">
            <caption className="sr-only">本单位历年投档历史</caption>
            <thead>
              <tr>
                <th scope="col">年份</th>
                <th scope="col">最低分</th>
                <th scope="col">最低位次</th>
                {studentRank ? <th scope="col">与你的位次</th> : null}
                <th scope="col">计划数</th>
                <th scope="col">数据质量</th>
                <th scope="col">数据性质</th>
                <th scope="col">来源</th>
              </tr>
            </thead>
            <tbody>
              {own.map((entry, index) => {
                const quality = QUALITY_LABEL[entry.data_quality ?? 'OK'] ?? QUALITY_LABEL['OK']!
                const margin =
                  studentRank && entry.min_rank ? entry.min_rank - studentRank : null
                return (
                  <tr key={`${entry.year}-${index}`}>
                    <td className="num">{entry.year}</td>
                    <td className="num">{formatScore(entry.min_score)}</td>
                    <td className="num font-medium">{formatRank(entry.min_rank)}</td>
                    {studentRank ? (
                      <td className={`num ${margin !== null && margin >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>
                        {margin === null ? '—' : `${margin >= 0 ? '你靠前' : '你靠后'} ${formatNumber(Math.abs(margin))}`}
                      </td>
                    ) : null}
                    <td className="num">{formatPlanCount(entry.plan_count)}</td>
                    <td className={`text-xs ${quality.className}`}>
                      {quality.text}
                      {entry.is_collected ? '（征集）' : ''}
                    </td>
                    <td className={entry.is_synthetic !== false ? 'text-xs text-amber-700' : 'text-xs text-emerald-700'}>
                      {entry.is_synthetic !== false ? '模拟数据' : '真实来源'}
                    </td>
                    <td>
                      <SourceLink url={entry.source_url} label="查看来源" />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {analog.length > 0 && (
        <div className="callout-info">
          <p className="font-medium">类比证据（本单位无可比历史）</p>
          <ul className="mt-1 space-y-1 text-xs">
            {analog.map((entry, index) => (
              <li key={`analog-${index}`}>
                {entry.note}：{entry.year} 年最低位次 {formatRank(entry.min_rank)}
                {entry.plan_count ? `，计划 ${formatPlanCount(entry.plan_count)}` : ''} ·{' '}
                <span className={entry.is_synthetic !== false ? 'text-amber-700' : 'text-emerald-700'}>
                  {entry.is_synthetic !== false ? '模拟数据' : '真实来源'} ·{' '}
                </span>
                <SourceLink url={entry.source_url} label="来源" />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
