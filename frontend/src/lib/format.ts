/**
 * 展示格式化：**纯函数，可单测**（`src/lib/format.test.ts`）。
 *
 * 纪律（AGENTS.md §8）：
 * - 概率**永远显示为区间**，禁止把单点概率当结论展示；
 * - 位次/分数一律带千分位，便于逐位核对；
 * - 缺失值显示 `—`（而不是 0），避免"编造一个数"的观感。
 */

const DASH = '—'

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** 千分位整数；非有限数 → `—`。 */
export function formatNumber(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return DASH
  return Math.round(value).toLocaleString('zh-CN')
}

/** 位次（数值越小越靠前）。 */
export function formatRank(rank: number | null | undefined): string {
  return formatNumber(rank)
}

/** 分数（可能是小数，如等效分）。 */
export function formatScore(score: number | null | undefined): string {
  if (!isFiniteNumber(score)) return DASH
  return Number.isInteger(score) ? String(score) : score.toFixed(1)
}

/** 概率区间 `[low, high]`（0–1）→ `62%–78%`。
 *
 * 区间过窄时（四舍五入后相等）自动增加小数位，**不做任何美化放大**：
 * 宁可显示 `94.2%–94.6%`，也不把不确定度伪装成更宽的区间。
 */
export function formatInterval(interval: readonly number[] | null | undefined): string {
  if (!interval || interval.length < 2) return DASH
  const low = interval[0]
  const high = interval[1]
  if (!isFiniteNumber(low) || !isFiniteNumber(high)) return DASH
  const safeLow = Math.min(low, high)
  const safeHigh = Math.max(low, high)
  for (const digits of [0, 1, 2]) {
    const left = (safeLow * 100).toFixed(digits)
    const right = (safeHigh * 100).toFixed(digits)
    if (left !== right) return `${left}%–${right}%`
  }
  return `${(safeLow * 100).toFixed(2)}%–${(safeHigh * 100).toFixed(2)}%`
}

/** 单个百分比（仅在"统计口径"这类非推荐结论的场景使用，如数据覆盖率）。 */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (!isFiniteNumber(value)) return DASH
  return `${(value * 100).toFixed(digits)}%`
}

/** 覆盖率：后端给 0–1。 */
export function formatCoverage(value: number | null | undefined): string {
  return formatPercent(value, 1)
}

/** 学费（元/年）。名师铁律 10：中外合作/民办必须在推荐卡片上明示。 */
export function formatTuition(yuan: number | null | undefined): string {
  if (!isFiniteNumber(yuan)) return DASH
  return `${Math.round(yuan).toLocaleString('zh-CN')} 元/年`
}

/** 计划数（计划数小 = 波动大，名师铁律 6）。 */
export function formatPlanCount(count: number | null | undefined): string {
  if (!isFiniteNumber(count)) return DASH
  return `${Math.round(count).toLocaleString('zh-CN')} 人`
}

/** 位次差：正值 = 考生比该单位切线更靠前（更安全）。 */
export function formatRankMargin(studentRank: number | null | undefined, targetRank: number | null | undefined): string {
  if (!isFiniteNumber(studentRank) || !isFiniteNumber(targetRank)) return DASH
  const margin = targetRank - studentRank
  const sign = margin >= 0 ? '+' : '−'
  return `${sign}${Math.abs(Math.round(margin)).toLocaleString('zh-CN')}`
}

/** ISO 时间 → `2026-02-14 09:30`。 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return DASH
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (value: number) => String(value).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** 选考要求的人话描述（DOMAIN_RULES §2.4 的三种模式）。 */
export function describeSubjectRequirement(
  requirement: { mode?: string | null; subjects?: string[] | null } | null | undefined,
): string {
  if (!requirement) return '不限'
  const subjects = requirement.subjects ?? []
  if (!subjects.length || requirement.mode === 'none') return '不限'
  const joined = subjects.join('、')
  if (requirement.mode === 'all_of') return `均须选考：${joined}`
  if (requirement.mode === 'any_of') return `选考其一：${joined}`
  return joined
}

/** 志愿表/推荐的分层分布 → `冲 7 · 稳 55 · 保 0 · 垫 18`。 */
export function formatTierDistribution(
  distribution: Record<string, number> | null | undefined,
  labels: Record<string, string>,
): string {
  if (!distribution) return DASH
  const parts = Object.entries(distribution)
    .filter(([, count]) => count > 0)
    .map(([tier, count]) => `${labels[tier] ?? tier} ${count}`)
  return parts.length ? parts.join(' · ') : DASH
}

/** 投档单位 id → 便于阅读的短标识（完整 id 太长，卡片上放不下）。 */
export function shortUnitId(unitId: string | null | undefined): string {
  if (!unitId) return DASH
  const parts = unitId.split('-')
  return parts.length >= 5 ? parts.slice(2).join('-') : unitId
}

/** 把 `{code,message,suggestion}` 风险列表按等级分组计数。 */
export function countByLevel<T extends { level: string }>(items: readonly T[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const item of items) counts[item.level] = (counts[item.level] ?? 0) + 1
  return counts
}
