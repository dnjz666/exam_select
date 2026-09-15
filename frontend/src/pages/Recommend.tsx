import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import {
  api,
  ApiError,
  type RecommendItem,
  type RecommendStats,
  type Tier,
} from '../api/client'
import { EvidenceTable } from '../components/EvidenceTable'
import { ProbabilityBar } from '../components/ProbabilityBar'
import { ErrorNote, EmptyState, Loading, SourceLink, WarningList } from '../components/StateBlocks'
import { TierBadge } from '../components/TierBadge'
import { TierLegend } from '../components/Disclaimer'
import { formatNumber, formatPlanCount, formatRank, formatTuition, describeSubjectRequirement } from '../lib/format'
import { useAsync } from '../lib/hooks'
import { PROVINCE_LABEL, TIER_ORDER, TIER_STYLE, UNIT_TYPE_LABEL, missingFieldLabel, provinceLabel } from '../lib/labels'
import { useProfileStore } from '../store/profile'
import { usePlanStore } from '../store/plan'

const LEVEL_OPTIONS = ['985', '211', '双一流']
const DEFAULT_LIMIT = 60

const TIER_HEADLINE: Record<string, string> = {
  CHONG: '冲 —— 有机会但不稳，放在志愿表前段',
  WEN: '稳 —— 大概率能上，志愿表的主体',
  BAO: '保 —— 很稳，且通过了"真保底"余量闸门',
  DIAN: '垫 —— 绝对兜底',
  TOO_RISKY: '基本无望（默认不推荐，仅在你显式开启时显示）',
  NO_DATA: '无可用历史数据（不参与志愿表生成）',
}

/**
 * 推荐列表（AGENTS.md §8.2 `/recommend`）。
 *
 * 硬要求：卡片流 + 冲稳保色带 + **概率区间条** + 「为什么」展开历史证据表。
 * 前端不做任何"看起来更漂亮"的数字加工：概率只显示区间，位次直接引用后端值。
 */
export function RecommendPage() {
  const navigate = useNavigate()
  const profile = useProfileStore()
  const planStore = usePlanStore()

  const [regions, setRegions] = useState<string[]>([])
  const [levels, setLevels] = useState<string[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [tuitionMax, setTuitionMax] = useState<number | null>(null)
  const [includeTooRisky, setIncludeTooRisky] = useState(false)
  const [intentAsHard, setIntentAsHard] = useState(false)
  const [limit, setLimit] = useState(DEFAULT_LIMIT)

  const studentId = profile.studentId
  const missing = profile.student?.missing_fields ?? []

  const tiers = useAsync(() => api.meta.tiers(), [])
  const majors = useAsync(() => api.catalog.majorSearch({ limit: 300 }), [])
  const categoryOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const major of majors.data?.data ?? []) if (major.category) seen.add(major.category)
    return [...seen].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
  }, [majors.data])

  const filters = useMemo(
    () => ({
      regions,
      levels,
      majors: categories,
      tuition_max: tuitionMax,
      exclude_unit_ids: [] as string[],
      intent_as_hard: intentAsHard,
    }),
    [regions, levels, categories, tuitionMax, intentAsHard],
  )

  // 档案不完整时**不发请求**：后端会 409，前端也必须在入口就拦住（§8.1）
  const recommendation = useAsync(
    async () => {
      if (!studentId || missing.length > 0) return null
      const envelope = await api.recommend({
        student_id: studentId,
        filters,
        limit,
        include_too_risky: includeTooRisky,
      })
      return envelope
    },
    [studentId, missing.length, JSON.stringify(filters), limit, includeTooRisky],
  )

  const items = recommendation.data?.data.items ?? []
  const stats: RecommendStats | null = recommendation.data?.data.stats ?? null

  const grouped = useMemo(() => {
    const map = new Map<Tier, RecommendItem[]>()
    for (const tier of TIER_ORDER) map.set(tier, [])
    for (const item of items) {
      const bucket = map.get(item.tier)
      if (bucket) bucket.push(item)
      else map.set(item.tier, [item])
    }
    return map
  }, [items])

  const bounds = useMemo(() => {
    const result: Record<string, [number, number]> = {}
    for (const tier of tiers.data?.data.tiers ?? []) result[tier.tier] = [tier.low, tier.high]
    return result
  }, [tiers.data])

  const rule = stats?.rule ?? null
  const studentRank = profile.rank

  if (missing.length > 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">推荐列表</h1>
        <div className="blocking-banner">
          <p className="blocking-banner-title">
            <span aria-hidden="true">⛔</span>档案还没填完，无法进入推荐
          </p>
          <p className="mt-2 text-sm text-rose-900">
            系统不会替你假设缺失信息。请先补齐：
            {missing.map((field) => missingFieldLabel(field)).join('、')}
          </p>
          <Link to="/profile" className="btn-primary mt-3 inline-flex">
            去补齐档案
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">推荐列表</h1>
          <p className="muted mt-1">
            {provinceLabel(profile.province)} · 位次 {formatRank(profile.rank)} · 分数 {profile.totalScore} ·
            选考 {profile.subjects.join('、')}
          </p>
        </div>
        {planStore.preferenceOrder.length > 0 && (
          <div className="card card-pad flex items-center gap-3 py-2">
            <span className="text-sm text-slate-600">
              已加入意愿序 <span className="num font-semibold">{planStore.preferenceOrder.length}</span> 个
            </span>
            <button
              type="button"
              className="btn-primary"
              onClick={() => navigate('/plan?generate=1')}
            >
              去生成志愿表
            </button>
            <button type="button" className="btn-ghost" onClick={() => planStore.setPreferenceOrder([])}>
              清空
            </button>
          </div>
        )}
      </div>

      {rule && (
        <div className="card card-pad">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            <span className="font-medium">{rule.batch_name}</span>
            <span className="chip-slate">{UNIT_TYPE_LABEL[rule.unit_type] ?? rule.unit_type}</span>
            <span className="chip-slate">最多 {rule.max_volunteers} 个志愿</span>
            {rule.requires_banner && (
              <span className="chip bg-rose-100 text-rose-800 ring-1 ring-rose-300">规则待核实</span>
            )}
          </div>
          <div className="mt-2">
            <TierLegend tiers={tiers.data?.data ?? null} />
          </div>
        </div>
      )}

      {/* ------------------------------ 筛选 ------------------------------ */}
      <details className="card card-pad">
        <summary className="cursor-pointer text-sm font-medium text-slate-700">
          筛选与偏好（可选；改动会重新计算推荐）
        </summary>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <section>
            <h3 className="text-sm font-semibold text-slate-800">意向地区（院校所在省）</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.keys(PROVINCE_LABEL).map((region) => {
                const picked = regions.includes(region)
                return (
                  <button
                    key={region}
                    type="button"
                    aria-pressed={picked}
                    className={[
                      'rounded-lg border px-3 py-1 text-sm',
                      picked ? 'border-sky-500 bg-sky-600 text-white' : 'border-slate-200 bg-white text-slate-700',
                    ].join(' ')}
                    onClick={() =>
                      setRegions(picked ? regions.filter((item) => item !== region) : [...regions, region])
                    }
                  >
                    {provinceLabel(region)}
                  </button>
                )
              })}
            </div>
            <label className="mt-2 flex items-center gap-2 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={intentAsHard}
                onChange={(event) => setIntentAsHard(event.target.checked)}
              />
              把意向地区/层次/门类当作**硬约束**（直接过滤掉，而不只是降权）
            </label>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-slate-800">院校层次</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {LEVEL_OPTIONS.map((level) => {
                const picked = levels.includes(level)
                return (
                  <button
                    key={level}
                    type="button"
                    aria-pressed={picked}
                    className={[
                      'rounded-lg border px-3 py-1 text-sm',
                      picked ? 'border-sky-500 bg-sky-600 text-white' : 'border-slate-200 bg-white text-slate-700',
                    ].join(' ')}
                    onClick={() =>
                      setLevels(picked ? levels.filter((item) => item !== level) : [...levels, level])
                    }
                  >
                    {level}
                  </button>
                )
              })}
            </div>
            <h3 className="mt-4 text-sm font-semibold text-slate-800">专业门类</h3>
            <div className="mt-2 flex max-h-32 flex-wrap gap-2 overflow-y-auto">
              {categoryOptions.map((category) => {
                const picked = categories.includes(category)
                return (
                  <button
                    key={category}
                    type="button"
                    aria-pressed={picked}
                    className={[
                      'rounded-lg border px-3 py-1 text-xs',
                      picked ? 'border-sky-500 bg-sky-600 text-white' : 'border-slate-200 bg-white text-slate-700',
                    ].join(' ')}
                    onClick={() =>
                      setCategories(
                        picked ? categories.filter((item) => item !== category) : [...categories, category],
                      )
                    }
                  >
                    {category}
                  </button>
                )
              })}
            </div>
          </section>

          <section className="space-y-3">
            <div>
              <label className="label" htmlFor="tuition-max">
                学费硬上限（元/年）
              </label>
              <input
                id="tuition-max"
                type="number"
                min={0}
                className="input num"
                value={tuitionMax ?? ''}
                onChange={(event) => setTuitionMax(event.target.value === '' ? null : Number(event.target.value))}
                placeholder="留空 = 不限"
              />
            </div>
            <div>
              <label className="label" htmlFor="limit">
                返回条数上限
              </label>
              <input
                id="limit"
                type="number"
                min={1}
                max={500}
                className="input num"
                value={limit}
                onChange={(event) => setLimit(Math.max(1, Math.min(500, Number(event.target.value) || 1)))}
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={includeTooRisky}
                onChange={(event) => setIncludeTooRisky(event.target.checked)}
              />
              也显示「基本无望」（概率 &lt; 10%）的单位
            </label>
          </section>
        </div>
      </details>

      {/* ------------------------------ 统计 ------------------------------ */}
      {stats && (
        <div className="card card-pad">
          <div className="grid gap-3 text-sm sm:grid-cols-4">
            <div>
              <p className="muted">候选单位</p>
              <p className="num text-lg font-semibold">{formatNumber(stats.units_considered)}</p>
            </div>
            <div>
              <p className="muted">硬约束剔除</p>
              <p className="num text-lg font-semibold">{formatNumber(stats.hard_filtered_out)}</p>
            </div>
            <div>
              <p className="muted">数据覆盖率</p>
              <p className="num text-lg font-semibold">{(stats.data_coverage * 100).toFixed(1)}%</p>
              {stats.no_data_count > 0 && (
                <p className="text-xs text-amber-700">{stats.no_data_count} 个无可用历史（不编造概率）</p>
              )}
            </div>
            <div>
              <p className="muted">返回</p>
              <p className="num text-lg font-semibold">{formatNumber(stats.returned)}</p>
            </div>
          </div>
          {Object.keys(stats.filtered_out_reasons ?? {}).length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-slate-600">
                被硬约束剔除的原因分布（"为什么没推荐 XX"）
              </summary>
              <ul className="mt-2 flex flex-wrap gap-3 text-xs text-slate-600">
                {Object.entries(stats.filtered_out_reasons ?? {}).map(([code, count]) => (
                  <li key={code}>
                    <span className="font-mono">{code}</span>：{count}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {recommendation.data?.warnings?.length ? <WarningList warnings={recommendation.data.warnings} /> : null}

      {/* ------------------------------ 列表 ------------------------------ */}
      {recommendation.loading && <Loading label="正在按位次法计算每个单位的录取概率…" rows={4} />}
      {!!recommendation.error && (
        <ErrorNote
          title="推荐计算失败"
          message={
            recommendation.error instanceof ApiError
              ? recommendation.error.message
              : recommendation.error instanceof Error
                ? recommendation.error.message
                : String(recommendation.error)
          }
          onRetry={recommendation.reload}
        />
      )}
      {!recommendation.loading && !recommendation.error && items.length === 0 && (
        <EmptyState
          title="没有符合条件的推荐"
          hint="放宽筛选条件（地区/层次/门类/学费上限），或到建档向导核对选考科目。"
        />
      )}

      <div className="space-y-6">
        {TIER_ORDER.filter((tier) => (grouped.get(tier)?.length ?? 0) > 0).map((tier) => {
          const bucket = grouped.get(tier) ?? []
          const style = TIER_STYLE[tier]
          return (
            <section key={tier} id={`tier-${tier}`}>
              <h2 className="flex items-center gap-3 text-base font-semibold">
                <span className={`chip ${style.badge}`}>{style.name}</span>
                <span className="num text-slate-500">{bucket.length}</span>
                <span className="text-sm font-normal text-slate-500">{TIER_HEADLINE[tier]}</span>
              </h2>
              <div className="mt-3 grid gap-3 xl:grid-cols-2">
                {bucket.map((item) => (
                  <RecommendCard
                    key={item.unit.unit_id}
                    item={item}
                    bounds={bounds}
                    studentRank={studentRank}
                  />
                ))}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}

function RecommendCard({
  item,
  bounds,
  studentRank,
}: {
  item: RecommendItem
  bounds: Record<string, [number, number]>
  studentRank: number | null
}) {
  const planStore = usePlanStore()
  const [open, setOpen] = useState(false)
  const unit = item.unit
  const college = item.college
  const picked = planStore.preferenceOrder.includes(unit.unit_id)
  const planTooSmall = unit.plan_count < 5

  return (
    <article className="card card-pad" id={`unit-${unit.unit_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <TierBadge tier={item.tier} confidence={item.confidence} />
            <h3 className="truncate text-base font-semibold text-slate-900">
              {college?.name ?? unit.college_id}
            </h3>
            {college?.level_tags?.map((tag) => (
              <span key={tag} className="chip-slate">
                {tag}
              </span>
            ))}
            {college && !college.is_public && (
              <span className="chip bg-amber-100 text-amber-800 ring-1 ring-amber-200">非公办</span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-700">
            {unit.group_name ? `${unit.group_name} · ` : ''}
            {unit.major_name}
          </p>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            <span>{college?.province ? `${provinceLabel(college.province)}${college.city ?? ''}` : '—'}</span>
            <span>选考要求：{describeSubjectRequirement(unit.subject_requirement)}</span>
            <span className={planTooSmall ? 'font-medium text-amber-700' : ''}>
              计划 {formatPlanCount(unit.plan_count)}
              {planTooSmall ? '（<5 人，波动大）' : ''}
            </span>
            {/* 名师铁律 10：学费必须明示 */}
            <span>学费 {formatTuition(unit.tuition)}</span>
          </div>
        </div>
        <button
          type="button"
          className={picked ? 'btn-secondary' : 'btn-primary'}
          onClick={() => planStore.togglePreference(unit.unit_id)}
          title="加入「意愿序」：生成志愿表时作为你指定的排序意愿（最终构成仍由分层配额与保底闸门决定）"
        >
          {picked ? '已加入意愿序' : '加入志愿表'}
        </button>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <ProbabilityBar interval={item.probability_interval ?? null} tier={item.tier} bounds={bounds} />
        <div className="text-xs text-slate-600">
          <p>
            预测今年最低位次 <span className="num font-semibold">{formatRank(item.predicted_min_rank)}</span>
            <span className="text-slate-400">（σ≈{formatNumber(item.sigma)}）</span>
          </p>
          <p className="mt-1">
            你的位次 <span className="num font-semibold">{formatRank(studentRank)}</span>
            {studentRank && item.predicted_min_rank ? (
              <span className="ml-1">
                （{studentRank <= item.predicted_min_rank ? '你更靠前，占优' : '你略靠后'}）
              </span>
            ) : null}
          </p>
          <p className="mt-1 text-slate-400">效用分 {item.utility.toFixed(3)}（软偏好加权，不影响概率）</p>
        </div>
      </div>

      {item.warnings && item.warnings.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2 text-xs">
          {item.warnings.map((warning) => (
            <li key={warning} className="chip bg-amber-100 text-amber-800 ring-1 ring-amber-200">
              {warning}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3">
        <button
          type="button"
          className="btn-ghost !px-2 text-sm"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
        >
          {open ? '收起依据' : '为什么？（看证据链）'}
        </button>
      </div>

      {open && (
        <div className="mt-2 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div>
            <h4 className="text-sm font-semibold text-slate-700">算法给的理由</h4>
            <ul className="mt-1 list-inside list-disc space-y-0.5 text-sm text-slate-600">
              {item.reasons?.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          </div>

          {item.adjustments && item.adjustments.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-slate-700">修正项（趋势 / 计划数）</h4>
              <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
                {item.adjustments.map((adjustment) => (
                  <li key={adjustment.name}>
                    <span className="font-mono">{adjustment.name}</span> {adjustment.delta >= 0 ? '+' : ''}
                    {(adjustment.delta * 100).toFixed(1)}% —— {adjustment.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <h4 className="text-sm font-semibold text-slate-700">历史证据（哪年 / 最低分 / 最低位次 / 计划数）</h4>
            <div className="mt-1">
              <EvidenceTable evidence={item.evidence ?? []} studentRank={studentRank} />
            </div>
          </div>

          <p className="text-xs text-slate-500">
            院校来源：<SourceLink url={college?.source_url ?? null} label={college?.source_url ?? '无'} />
          </p>
        </div>
      )}
    </article>
  )
}
