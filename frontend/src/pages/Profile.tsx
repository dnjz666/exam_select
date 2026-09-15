import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, ApiError, type ProvinceMeta, type ResolveRankPayload, type SubjectCoveragePayload } from '../api/client'
import { RuleBanner } from '../components/RuleBanner'
import { ErrorNote, Loading, SourceLink, WarningList } from '../components/StateBlocks'
import { StepIndicator } from '../components/StepIndicator'
import { formatCoverage, formatNumber, formatRank, formatScore } from '../lib/format'
import { useAsync, useDebouncedValue } from '../lib/hooks'
import { PROVINCE_LABEL, UNIT_TYPE_LABEL, missingFieldLabel, provinceLabel, verifiedStyle } from '../lib/labels'
import { isProfileComplete, submitDraft, useProfileStore } from '../store/profile'

const STEPS = ['选省份', '选选考科目', '填成绩', '偏好与身体条件'] as const

/** 意向地区候选项：来自后端规则包（禁止前端另立一份省份清单）。 */
const REGION_OPTIONS = Object.keys(PROVINCE_LABEL)

/**
 * 建档向导（AGENTS.md §8.1）。
 *
 * 前 3 步是硬门槛：未完成不得进入推荐（`/recommend` 会再校验一次 `missing_fields`）。
 * 第 4 步可跳过。进度同时写 localStorage（store persist）与后端草稿（`submitDraft`）。
 */
export function ProfilePage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const meta = useAsync(() => api.meta.provinces(), [])

  const profile = useProfileStore()
  const complete = isProfileComplete(profile.student)

  // 当前可到达的最大步骤：第 1 步永远可达；后续需要满足各自前置条件
  const provinces = meta.data?.data ?? []
  const selected: ProvinceMeta | null = useMemo(
    () => provinces.find((item) => item.province === profile.province) ?? null,
    [provinces, profile.province],
  )
  const subjectPool = selected?.subject_pool ?? null
  const choose = subjectPool?.choose ?? 3

  const maxReachable = useMemo(() => {
    if (!profile.province) return 1
    if (profile.subjects.length !== choose) return 2
    if (!profile.totalScore || profile.totalScore <= 0) return 3
    return 4
  }, [profile.province, profile.subjects.length, profile.totalScore, choose])

  if (meta.loading) return <Loading label="正在读取六省市规则（含来源与核实状态）…" rows={2} />
  if (meta.error) {
    return (
      <ErrorNote
        title="读取省份规则失败"
        message={meta.error instanceof Error ? meta.error.message : String(meta.error)}
        hint="请确认后端已启动：uvicorn app.main:app --port 8000"
        onRetry={meta.reload}
      />
    )
  }

  return (
    <div className="space-y-5">
      <div className="card card-pad">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">建档向导</h1>
            <p className="muted mt-1">
              前 3 步是硬门槛：省份决定投档模式与志愿容量，选考科目决定能报哪些专业，成绩决定位次。
              系统不会替你假设任何缺失信息。
            </p>
          </div>
          <StepIndicator steps={STEPS} current={step} maxReachable={maxReachable} onJump={setStep} />
        </div>
        {meta.data?.warnings?.length ? (
          <div className="mt-3">
            <WarningList warnings={meta.data.warnings} />
          </div>
        ) : null}
      </div>

      {step === 1 && (
        <Step1Province
          provinces={provinces}
          selected={selected}
          onSelect={async (province) => {
            profile.setProvince(province.province, province.current_year)
            // 立即落后端草稿：后面每一步都 PATCH 同一份档案（§8.1「同时存 localStorage 与后端草稿」）
            try {
              await submitDraft()
            } catch {
              /* 草稿创建失败不阻断向导：下一步会重试，错误在提交处统一提示 */
            }
            setStep(2)
          }}
          onNext={() => setStep(2)}
        />
      )}

      {step === 2 && selected && (
        <Step2Subjects
          province={selected}
          pool={subjectPool}
          choose={choose}
          onDone={async () => {
            try {
              await submitDraft()
            } catch {
              /* 同上：错误在进入推荐/成绩换算时统一呈现 */
            }
            setStep(3)
          }}
        />
      )}

      {step === 3 && (
        <Step3Score
          provinceMeta={selected}
          onDone={() => setStep(4)}
        />
      )}

      {step === 4 && (
        <Step4Preferences
          provinceMeta={selected}
          onFinish={async () => {
            const student = await submitDraft()
            if ((student.missing_fields ?? []).length === 0) navigate('/recommend')
          }}
          complete={complete}
        />
      )}

      <div className="flex items-center justify-between">
        <button
          type="button"
          className="btn-secondary"
          disabled={step === 1}
          onClick={() => setStep((value) => Math.max(1, value - 1))}
        >
          上一步
        </button>
        {step < 4 ? (
          <button
            type="button"
            className="btn-primary"
            disabled={step >= maxReachable}
            title={step >= maxReachable ? '请先完成当前步骤' : undefined}
            onClick={() => setStep((value) => Math.min(4, value + 1))}
          >
            下一步
          </button>
        ) : (
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              void submitDraft()
                .then((student) => {
                  if ((student.missing_fields ?? []).length === 0) navigate('/recommend')
                })
                .catch(() => undefined)
            }}
          >
            完成，进入推荐
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 第 1 步：选省份
// ---------------------------------------------------------------------------
function Step1Province({
  provinces,
  selected,
  onSelect,
  onNext,
}: {
  provinces: ProvinceMeta[]
  selected: ProvinceMeta | null
  onSelect: (province: ProvinceMeta) => void | Promise<void>
  onNext: () => void
}) {
  const [busy, setBusy] = useState(false)
  // 契约里这些字段是可选的（Pydantic 有默认值 → OpenAPI 非 required）：显式兜底，
  // 缺字段时一律按「没有这一项」渲染，而不是崩在 `.length` 上。
  const batches = selected?.batches ?? []
  const mainBatch = batches.find((batch) => batch.batch_code === selected?.main_batch_code)
  const pool = selected?.subject_pool ?? null
  const poolSubjects = pool?.subjects ?? []
  const poolCaveats = pool?.caveats ?? []

  return (
    <div className="space-y-4">
      <div className="card card-pad">
        <h2 className="card-title">第 1 步 · 你在哪个省参加高考？</h2>
        <p className="muted mt-1">
          省份一旦选定，投档模式（专业+院校 / 院校专业组）、志愿容量、可选科目范围全部随之确定。
        </p>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {provinces.map((province) => {
            const batch = (province.batches ?? []).find(
              (item) => item.batch_code === province.main_batch_code,
            )
            const active = selected?.province === province.province
            return (
              <button
                key={province.province}
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true)
                  void Promise.resolve(onSelect(province)).finally(() => setBusy(false))
                }}
                className={[
                  'rounded-xl border p-3 text-left transition',
                  active
                    ? 'border-sky-500 bg-sky-50 ring-2 ring-sky-200'
                    : 'border-slate-200 bg-white hover:border-sky-300 hover:bg-slate-50',
                ].join(' ')}
              >
                <p className="text-base font-semibold text-slate-900">{provinceLabel(province.province)}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {batch ? (UNIT_TYPE_LABEL[batch.unit_type] ?? batch.unit_type) : '规则待补'}
                </p>
                <p className="num mt-0.5 text-xs text-slate-500">
                  {batch ? `${batch.max_volunteers} 个志愿` : '—'}
                </p>
                {province.requires_banner && (
                  <span className="chip mt-2 bg-rose-100 text-rose-800 ring-1 ring-rose-300">规则待核实</span>
                )}
                {!province.requires_banner && province.has_caution && (
                  <span className="chip mt-2 bg-amber-100 text-amber-800 ring-1 ring-amber-200">部分批次待核实</span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {selected && (
        <div className="card card-pad space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="card-title">{provinceLabel(selected.province)} · 投档规则</h2>
            <button type="button" className="btn-primary" onClick={onNext}>
              就用这个省，下一步
            </button>
          </div>

          <RuleBanner rule={mainBatch ? ruleToBlock(selected, mainBatch) : null} />

          {pool && (
            <div className="callout-info">
              <p className="font-medium">
                选考科目池：{pool.mode ?? '未核实'}（从 {poolSubjects.length} 门中选 {pool.choose} 门）
              </p>
              <p className="mt-1 text-xs">科目：{poolSubjects.join('、')}</p>
              <p className="mt-1 text-xs">
                来源：<SourceLink url={pool.source_url} label="查看官方原文" />
                {pool.source_quote ? ` · 原文：「${pool.source_quote}」` : ''}
              </p>
              {poolCaveats.map((caveat) => (
                <p key={caveat} className="mt-1 text-xs text-amber-800">
                  ⚠ {caveat}
                </p>
              ))}
            </div>
          )}

          <details className="rounded-lg border border-slate-200 p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-700">
              该省全部批次（{batches.length} 个）与来源原文
            </summary>
            <ul className="mt-3 space-y-3">
              {batches.map((batch) => {
                const verified = verifiedStyle(batch.verified_status)
                return (
                  <li key={batch.batch_code} className="rounded-lg bg-slate-50 p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{batch.batch_name}</span>
                      <span className="chip-slate">{batch.max_volunteers} 个志愿</span>
                      <span className={`chip ${verified.badge}`}>{verified.label}</span>
                      {!batch.is_parallel && (
                        <span className="chip bg-rose-100 text-rose-800 ring-1 ring-rose-200">顺序志愿</span>
                      )}
                      {batch.requires_banner && (
                        <span className="chip bg-rose-100 text-rose-800 ring-1 ring-rose-300">待核实</span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-slate-600">官方原文：{batch.source_quote}</p>
                    <p className="mt-1 text-xs">
                      <SourceLink url={batch.source_url} label={batch.source_url} />
                    </p>
                    {(batch.assumptions ?? []).map((assumption) => (
                      <p key={assumption} className="mt-1 text-xs text-amber-800">
                        未核实维度：{assumption}
                      </p>
                    ))}
                    {(batch.caveats ?? []).map((caveat) => (
                      <p key={caveat} className="mt-1 text-xs text-slate-500">
                        说明：{caveat}
                      </p>
                    ))}
                  </li>
                )
              })}
            </ul>
          </details>
        </div>
      )}
    </div>
  )
}

/** `BatchMeta` → `RuleBlock`（两者字段同源；RuleBanner 只依赖后者）。 */
function ruleToBlock(province: ProvinceMeta, batch: NonNullable<ProvinceMeta['batches']>[number]) {
  return {
    province: province.province,
    batch_code: batch.batch_code,
    batch_name: batch.batch_name,
    unit_type: batch.unit_type,
    max_volunteers: batch.max_volunteers,
    has_major_adjustment: batch.has_major_adjustment,
    is_parallel: batch.is_parallel,
    majors_per_group: batch.majors_per_group ?? null,
    verified_status: batch.verified_status,
    verified_year: batch.verified_year ?? null,
    source_url: batch.source_url,
    requires_banner: batch.requires_banner,
  }
}

// ---------------------------------------------------------------------------
// 第 2 步：选选考科目
// ---------------------------------------------------------------------------
function Step2Subjects({
  province,
  pool,
  choose,
  onDone,
}: {
  province: ProvinceMeta
  pool: ProvinceMeta['subject_pool']
  choose: number
  onDone: () => void | Promise<void>
}) {
  const profile = useProfileStore()
  const subjects = profile.subjects
  const full = subjects.length === choose
  const coverageKey = subjects.join(',')

  const coverage = useAsync<SubjectCoveragePayload | null>(
    async () => {
      if (subjects.length === 0) return null
      const envelope = await api.meta.subjectCoverage(province.province, subjects)
      return envelope.data
    },
    [province.province, coverageKey],
  )

  if (!pool) {
    return <ErrorNote title="缺少选考科目池" message="该省未提供选考科目池（规则与数据均不可用），无法继续。" />
  }
  const poolSubjects = pool.subjects ?? []

  return (
    <div className="space-y-4">
      <div className="card card-pad">
        <h2 className="card-title">
          第 2 步 · 从 {poolSubjects.length} 门中选 {choose} 门选考科目
        </h2>
        <p className="muted mt-1">
          必须**恰好 {choose} 门**。选满后其余选项自动禁用——新高考的选考科目是硬约束，
          少一门或多一门都会导致推荐结果不合法。
        </p>

        {(pool.origin === 'DATA_DERIVED' || pool.requires_caution) && (
          <div className="callout-warn mt-3">
            <p className="font-medium">科目池来源需注意</p>
            <p className="mt-1 text-xs">
              {pool.origin === 'DATA_DERIVED'
                ? '该省科目池未核实到官方原文，当前列表由现有招生计划的选考要求反推，只包含有招生计划的科目。'
                : `该省科目池来源等级为 ${pool.verified_status}（未达官方原文），请以考试院文件为准。`}
            </p>
            {pool.source_url ? (
              <p className="mt-1 text-xs">
                来源：<SourceLink url={pool.source_url} label={pool.source_url} />
              </p>
            ) : null}
          </div>
        )}

        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {poolSubjects.map((subject) => {
            const picked = subjects.includes(subject)
            const disabled = !picked && full
            return (
              <button
                key={subject}
                type="button"
                disabled={disabled}
                onClick={() => profile.toggleSubject(subject, choose)}
                aria-pressed={picked}
                className={[
                  'rounded-xl border px-3 py-3 text-sm font-medium transition',
                  picked
                    ? 'border-sky-500 bg-sky-600 text-white'
                    : disabled
                      ? 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'
                      : 'border-slate-200 bg-white text-slate-700 hover:border-sky-300',
                ].join(' ')}
              >
                {subject}
              </button>
            )
          })}
        </div>

        <p className="mt-3 text-sm">
          已选 <span className="num font-semibold">{subjects.length}</span> / {choose} 门
          {full ? '（已选满，其余已禁用）' : `（还需选 ${choose - subjects.length} 门）`}
        </p>

        <div className="mt-3">
          <span className="text-xs text-slate-500">
            科目池来源：<SourceLink url={pool.source_url} label="官方原文" />
            {pool.source_quote ? ` · 「${pool.source_quote}」` : ''}
          </span>
        </div>
      </div>

      <div className="card card-pad">
        <h3 className="card-title">可报专业覆盖率（实时）</h3>
        {subjects.length === 0 && <p className="muted mt-1">选择科目后立即统计。</p>}
        {subjects.length > 0 && coverage.loading && <p className="muted mt-1">统计中…</p>}
        {!!coverage.error && (
          <ErrorNote
            title="覆盖率统计失败"
            message={coverage.error instanceof Error ? coverage.error.message : String(coverage.error)}
            onRetry={coverage.reload}
          />
        )}
        {coverage.data && (
          <div className="mt-2 space-y-2">
            <p className="text-2xl font-semibold text-slate-900">
              {formatCoverage(coverage.data.coverage)}
            </p>
            <p className="muted">
              你的组合（{(coverage.data.subjects ?? []).join('、')}）可报{' '}
              <span className="num">{formatNumber(coverage.data.matched_units)}</span> /{' '}
              <span className="num">{formatNumber(coverage.data.total_units)}</span> 个投档单位
              （{coverage.data.year} 年 {coverage.data.batch_code}）
            </p>
            <p className="text-xs text-slate-500">
              统计口径：主批次当年全部投档单位中，选考要求被你的组合满足的比例（真实统计，非估算）。
              来源：<SourceLink url={coverage.data.source_url} label="批次规则来源" />
            </p>
            {(coverage.data.unmatched_examples ?? []).length > 0 && (
              <details className="rounded-lg border border-slate-200 p-2 text-xs">
                <summary className="cursor-pointer text-slate-600">
                  看几个被排除的例子（为什么有些专业报不了）
                </summary>
                <ul className="mt-2 space-y-1">
                  {(coverage.data.unmatched_examples ?? []).map((unit) => (
                    <li key={unit.unit_id} className="text-slate-600">
                      {unit.major_name}：要求
                      {unit.requirement_mode === 'all_of' ? '均须选考' : '选考其一'}
                      {(unit.requirement_subjects ?? []).join('、')}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {(coverage.data.warnings ?? []).length > 0 && (
              <WarningList warnings={coverage.data.warnings ?? []} />
            )}
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          className="btn-primary"
          disabled={!full}
          onClick={() => void Promise.resolve(onDone())}
        >
          选好了，下一步
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 第 3 步：填成绩
// ---------------------------------------------------------------------------
function Step3Score({ provinceMeta, onDone }: { provinceMeta: ProvinceMeta | null; onDone: () => void }) {
  const profile = useProfileStore()
  const debouncedScore = useDebouncedValue(profile.totalScore, 500)
  const [converting, setConverting] = useState(false)
  const [computed, setComputed] = useState<ResolveRankPayload | null>(null)
  const [convertError, setConvertError] = useState<unknown>(null)
  /** 考生手填的位次（用于与换算结果做一致性校验，§8.1「不得擅自覆盖」） */
  const [manualRank, setManualRank] = useState<string>(profile.rankSourceUrl === 'manual://student-provided' ? String(profile.rank ?? '') : '')

  useEffect(() => {
    if (!profile.studentId || !debouncedScore || debouncedScore <= 0) return undefined
    let alive = true
    setConverting(true)
    setConvertError(null)
    submitDraft()
      .then(() => api.students.resolveRank(profile.studentId as string))
      .then((envelope) => {
        if (!alive) return
        setComputed(envelope.data)
        // 换算成功即以系统换算为准，并把来源写进档案（可追溯）
        profile.setRank(envelope.data.rank, envelope.data.source_url)
      })
      .catch((error: unknown) => {
        if (!alive) return
        setConvertError(error)
      })
      .finally(() => {
        if (alive) setConverting(false)
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedScore, profile.studentId])

  const manualValue = manualRank.trim() === '' ? null : Number(manualRank)
  const conflict =
    computed !== null && manualValue !== null && Number.isFinite(manualValue) && manualValue !== computed.rank

  const rankUnavailable = convertError instanceof ApiError && convertError.code === 'RANK_UNAVAILABLE'
  const scoreRange = computed?.score_range ?? {}
  const equivalents = computed?.equivalent_scores ?? []

  return (
    <div className="space-y-4">
      <div className="card card-pad">
        <h2 className="card-title">第 3 步 · 高考总分（位次可选）</h2>
        <p className="muted mt-1">
          位次比分数可靠：跨年比较一律用位次。系统会用当年一分一段表把你的分数换成位次；
          <strong>换算不可用时只会提示"不可用"，绝不会用估算值糊弄</strong>。
        </p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="total-score">
              高考总分（必填）
            </label>
            <input
              id="total-score"
              className="input num"
              type="number"
              inputMode="numeric"
              min={0}
              max={750}
              value={profile.totalScore ?? ''}
              onChange={(event) => {
                const raw = event.target.value
                profile.setScore(raw === '' ? null : Number(raw))
              }}
              placeholder={provinceMeta ? `${provinceLabel(provinceMeta.province)} 3+3 总分` : '例如 640'}
            />
          </div>
          <div>
            <label className="label" htmlFor="manual-rank">
              位次（选填，已知可直接填）
            </label>
            <input
              id="manual-rank"
              className="input num"
              type="number"
              inputMode="numeric"
              min={1}
              value={manualRank}
              onChange={(event) => setManualRank(event.target.value)}
              placeholder="例如 12340"
            />
            <p className="mt-1 text-xs text-slate-500">
              填了位次会与系统换算结果做一致性校验；两者不一致时**由你决定以哪个为准**。
            </p>
          </div>
        </div>

        {converting && <p className="muted mt-3">正在用当年一分一段表换算位次…</p>}

        {rankUnavailable && (
          <div className="callout-danger mt-3">
            <p className="font-medium">位次换算不可用</p>
            <p className="mt-1 text-sm">
              {convertError instanceof Error ? convertError.message : '一分一段表缺失。'}
            </p>
            <p className="mt-1 text-xs">
              请在上方「位次」一栏直接填写你已知的位次；系统不会用估算值代替。
            </p>
          </div>
        )}

        {!!convertError && !rankUnavailable && (
          <div className="mt-3">
            <ErrorNote
              title="位次换算失败"
              message={convertError instanceof Error ? convertError.message : String(convertError)}
            />
          </div>
        )}

        {computed && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm text-slate-600">系统换算结果（完整溯源）</p>
            <p className="num mt-1 text-2xl font-semibold text-slate-900">
              {formatRank(computed.rank)}
              <span className="text-base font-normal text-slate-500"> / {formatNumber(computed.total_candidates)}</span>
            </p>
            <p className="mt-1 text-xs text-slate-500">
              来源：<SourceLink url={computed.source_url} label={computed.source_url} />
            </p>
            <p className="mt-1 text-xs text-slate-500">
              百分位 {(computed.percentile * 100).toFixed(2)}% · 该年一分一段分数区间{' '}
              {formatScore(scoreRange['min'])}–{formatScore(scoreRange['max'])}
            </p>
            {equivalents.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-medium text-slate-600">等效分（同样位次在往年是多少分）</p>
                <ul className="mt-1 flex flex-wrap gap-3 text-xs text-slate-600">
                  {equivalents.map((item) => (
                    <li key={String(item['year'])} className="num">
                      {String(item['year'])} 年 ≈ {formatScore(item['score'] as number)} 分
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {conflict && computed && (
          <div className="callout-warn mt-4">
            <p className="font-medium">分数换算的位次与你填的位次不一致</p>
            <p className="mt-1 text-sm">
              系统按 {profile.totalScore} 分换算出 <span className="num font-semibold">{formatRank(computed.rank)}</span>，
              你填写的是 <span className="num font-semibold">{formatRank(manualValue)}</span>。
              请确认以哪个为准（系统不会擅自覆盖你的输入）。
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  profile.setRank(computed.rank, computed.source_url)
                  setManualRank('')
                }}
              >
                以系统换算为准（{formatRank(computed.rank)}）
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  profile.setRank(manualValue, 'manual://student-provided')
                  setManualRank('')
                }}
              >
                以我填写的为准（{formatRank(manualValue)}）
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          className="btn-primary"
          disabled={!profile.totalScore || profile.totalScore <= 0}
          onClick={onDone}
        >
          下一步
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 第 4 步：偏好与身体条件（可跳过）
// ---------------------------------------------------------------------------
function Step4Preferences({
  provinceMeta,
  onFinish,
  complete,
}: {
  provinceMeta: ProvinceMeta | null
  onFinish: () => Promise<void>
  complete: boolean
}) {
  const profile = useProfileStore()
  const preferences = profile.preferences
  const exam = profile.physicalExam
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const majors = useAsync(() => api.catalog.majorSearch({ limit: 300 }), [])
  const categories = useMemo(() => {
    const seen = new Set<string>()
    for (const major of majors.data?.data ?? []) {
      if (major.category) seen.add(major.category)
    }
    return [...seen].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
  }, [majors.data])

  const weights: Array<{ key: keyof typeof preferences; label: string }> = [
    { key: 'weight_region', label: '地区' },
    { key: 'weight_college_level', label: '院校层次' },
    { key: 'weight_major', label: '专业匹配' },
    { key: 'weight_tuition', label: '学费' },
    { key: 'weight_city', label: '城市' },
    { key: 'weight_misc', label: '其他' },
  ]

  const missing = profile.student?.missing_fields ?? []
  const intendedRegions = preferences.intended_regions ?? []
  const intendedCategories = preferences.intended_major_categories ?? []
  const excludedMajors = preferences.excluded_majors ?? []

  return (
    <div className="space-y-4">
      <div className="card card-pad">
        <h2 className="card-title">第 4 步 · 偏好与身体条件（可跳过）</h2>
        <p className="muted mt-1">
          这些是**软偏好**（影响排序）与**硬约束**（体检、语种；影响能否报）。跳过即采用默认值。
        </p>

        {missing.length > 0 && (
          <div className="callout-warn mt-3">
            <p className="font-medium">档案还缺以下必填项，补齐后才能进入推荐：</p>
            <ul className="mt-1 list-inside list-disc text-sm">
              {missing.map((field) => (
                <li key={field}>{missingFieldLabel(field)}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-4 grid gap-5 lg:grid-cols-2">
          <section>
            <h3 className="text-sm font-semibold text-slate-800">意向地区（可多选，空 = 不限）</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {REGION_OPTIONS.map((region) => {
                const picked = intendedRegions.includes(region)
                return (
                  <button
                    key={region}
                    type="button"
                    aria-pressed={picked}
                    className={[
                      'rounded-lg border px-3 py-1.5 text-sm transition',
                      picked
                        ? 'border-sky-500 bg-sky-600 text-white'
                        : 'border-slate-200 bg-white text-slate-700 hover:border-sky-300',
                    ].join(' ')}
                    onClick={() =>
                      profile.patchPreferences({
                        intended_regions: picked
                          ? intendedRegions.filter((item) => item !== region)
                          : [...intendedRegions, region],
                      })
                    }
                  >
                    {provinceLabel(region)}
                  </button>
                )
              })}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              意向地区默认按**软偏好**打分；勾选下方"当作硬约束"后才会直接过滤掉外省院校。
            </p>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-slate-800">意向专业门类</h3>
            {majors.loading && <p className="muted mt-2">读取专业库…</p>}
            {categories.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {categories.map((category) => {
                  const picked = intendedCategories.includes(category)
                  return (
                    <button
                      key={category}
                      type="button"
                      aria-pressed={picked}
                      className={[
                        'rounded-lg border px-3 py-1.5 text-sm transition',
                        picked
                          ? 'border-sky-500 bg-sky-600 text-white'
                          : 'border-slate-200 bg-white text-slate-700 hover:border-sky-300',
                      ].join(' ')}
                      onClick={() =>
                        profile.patchPreferences({
                          intended_major_categories: picked
                            ? intendedCategories.filter((item) => item !== category)
                            : [...intendedCategories, category],
                        })
                      }
                    >
                      {category}
                    </button>
                  )
                })}
              </div>
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-slate-800">预算与排斥专业</h3>
            <div>
              <label className="label" htmlFor="budget-max">
                学费硬上限（元/年，超过直接剔除）
              </label>
              <input
                id="budget-max"
                className="input num"
                type="number"
                min={0}
                value={preferences.budget_max ?? ''}
                onChange={(event) =>
                  profile.patchPreferences({
                    budget_max: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
                placeholder="留空 = 不限"
              />
              <p className="mt-1 text-xs text-slate-500">
                中外合作办学、民办院校学费常在 2–8 万/年，这个上限是**硬约束**。
              </p>
            </div>
            <div>
              <label className="label" htmlFor="excluded">
                明确排斥的专业（顿号或逗号分隔）
              </label>
              <input
                id="excluded"
                className="input"
                value={excludedMajors.join('、')}
                onChange={(event) =>
                  profile.patchPreferences({
                    excluded_majors: event.target.value
                      .split(/[、,，\s]+/)
                      .map((item) => item.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="例如 护理学、农学"
              />
              <p className="mt-1 text-xs text-slate-500">
                院校专业组模式下，组内含你排斥的专业会触发「组内不可接受」风险——冲进去也可能被调剂过去。
              </p>
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-slate-800">体检与语种（硬约束）</h3>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={exam.color_blindness ?? false}
                  onChange={(event) => profile.patchExam({ color_blindness: event.target.checked })}
                />
                色盲
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={exam.color_weakness ?? false}
                  onChange={(event) => profile.patchExam({ color_weakness: event.target.checked })}
                />
                色弱
              </label>
            </div>
            <div>
              <label className="label" htmlFor="height">
                身高（cm，部分专业有限制）
              </label>
              <input
                id="height"
                className="input num"
                type="number"
                min={0}
                value={exam.height_cm ?? ''}
                onChange={(event) =>
                  profile.patchExam({ height_cm: event.target.value === '' ? null : Number(event.target.value) })
                }
              />
            </div>
            <div>
              <label className="label" htmlFor="other-restrictions">
                其他受限结论原文
              </label>
              <input
                id="other-restrictions"
                className="input"
                value={(exam.other_restrictions ?? []).join('；')}
                onChange={(event) =>
                  profile.patchExam({
                    other_restrictions: event.target.value
                      .split(/[；;]+/)
                      .map((item) => item.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="例如 不宜就读医学类"
              />
            </div>
            <div>
              <label className="label" htmlFor="language">
                外语语种
              </label>
              <select
                id="language"
                className="input"
                value={profile.foreignLanguage}
                onChange={(event) => profile.setForeignLanguage(event.target.value)}
              >
                {['英语', '日语', '俄语', '德语', '法语', '西班牙语'].map((language) => (
                  <option key={language} value={language}>
                    {language}
                  </option>
                ))}
              </select>
            </div>
          </section>
        </div>

        <section className="mt-5">
          <h3 className="text-sm font-semibold text-slate-800">偏好权重（影响志愿排序，不影响概率）</h3>
          <p className="mt-1 text-xs text-slate-500">
            所有权重归一化后参与效用打分；默认等权。概率只由算法决定，权重不会让"没戏"的志愿变得有戏。
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {weights.map(({ key, label }) => {
              const value = Number(preferences[key] ?? 0)
              return (
                <div key={String(key)}>
                  <div className="flex items-center justify-between text-xs text-slate-600">
                    <span>{label}</span>
                    <span className="num">{(value * 100).toFixed(0)}%</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={value}
                    aria-label={`${label}权重`}
                    className="mt-1 w-full"
                    onChange={(event) =>
                      profile.patchPreferences({ [key]: Number(event.target.value) } as never)
                    }
                  />
                </div>
              )
            })}
          </div>
        </section>
      </div>

      {!!error && (
        <ErrorNote
          title="提交失败"
          message={error instanceof Error ? error.message : String(error)}
          hint={
            error instanceof ApiError && error.code === 'PROFILE_INCOMPLETE'
              ? `缺少：${error.missingFields.map(missingFieldLabel).join('、')}`
              : undefined
          }
        />
      )}

      <div className="flex flex-wrap items-center justify-end gap-3">
        {provinceMeta ? null : <span className="text-xs text-rose-700">尚未选择省份</span>}
        <button
          type="button"
          className="btn-primary"
          disabled={submitting}
          onClick={() => {
            setSubmitting(true)
            setError(null)
            onFinish()
              .catch((caught: unknown) => setError(caught))
              .finally(() => setSubmitting(false))
          }}
        >
          {submitting ? '提交中…' : complete ? '完成，进入推荐' : '保存并进入推荐'}
        </button>
      </div>
    </div>
  )
}
