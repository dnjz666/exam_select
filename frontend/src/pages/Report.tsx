import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import { api, type HistoryEvidence } from '../api/client'
import { Disclaimer } from '../components/Disclaimer'
import { RiskPanel } from '../components/RiskPanel'
import { ErrorNote, Loading, SourceLink } from '../components/StateBlocks'
import { TierBadge } from '../components/TierBadge'
import { formatInterval, formatPlanCount, formatRank, formatScore, formatTuition, formatDateTime, describeSubjectRequirement } from '../lib/format'
import { useAsync } from '../lib/hooks'
import { UNIT_TYPE_LABEL, provinceLabel, verifiedStyle } from '../lib/labels'
import { useProfileStore } from '../store/profile'
import { usePlanStore } from '../store/plan'

/**
 * 报告页（AGENTS.md §8.2 `/report`）：可打印的志愿报告。
 *
 * 必须包含：档案 + 志愿表 + 每志愿依据 + 风险提示 + **免责声明 + 数据来源清单**。
 * 报告里的每一个来源链接都打印出来（`@media print` 里把 URL 展开），
 * 这样纸质版也能核对数据出处。
 */
export function ReportPage() {
  const profile = useProfileStore()
  const planId = usePlanStore((state) => state.planId)
  const stored = usePlanStore((state) => state.bundle)

  const loaded = useAsync(async () => {
    if (stored) return stored
    if (!planId) return null
    return await api.plans.get(planId)
  }, [planId, stored])

  // 免责声明文案以后端 `/meta/tiers` 为唯一来源（不在前端另写一份法律文案）
  const tiers = useAsync(() => api.meta.tiers(), [])
  const disclaimerText = tiers.data?.data.disclaimer ?? null

  const bundle = stored ?? loaded.data
  const payload = bundle?.data ?? null
  const envelopeEvidence = bundle?.evidence ?? []

  const evidenceByUnit = useMemo(() => {
    const map = new Map<string, HistoryEvidence[]>()
    for (const entry of envelopeEvidence) {
      // evidence 里 unit_history 条目结构与 HistoryEvidence 一致（额外带 unit_id）
      const record = entry as unknown as HistoryEvidence & { unit_id?: string; what?: string }
      if (record.what !== 'unit_history' || !record.unit_id) continue
      const list = map.get(record.unit_id) ?? []
      list.push(record)
      map.set(record.unit_id, list)
    }
    return map
  }, [envelopeEvidence])

  const sources = useMemo(() => {
    const seen = new Map<string, string>()
    const add = (url: string | null | undefined, what: string) => {
      if (!url || !/^https?:\/\//i.test(url)) return
      if (!seen.has(url)) seen.set(url, what)
    }
    const plan = payload?.plan
    add(plan?.rule.source_url, '批次投档规则')
    for (const entry of envelopeEvidence) {
      const record = entry as { what?: string; source_url?: string; unit_id?: string; year?: number }
      add(record.source_url, record.unit_id ? `招生历史（${record.unit_id}）` : (record.what ?? '数据来源'))
    }
    for (const college of Object.values(payload?.colleges ?? {})) {
      add(college.source_url, `院校信息（${college.name}）`)
    }
    return [...seen.entries()].map(([url, what]) => ({ url, what }))
  }, [payload, envelopeEvidence])

  if (loaded.loading && !payload) return <Loading label="正在装配报告…" rows={3} />
  if (loaded.error && !payload) {
    return (
      <ErrorNote
        title="读取志愿表失败"
        message={loaded.error instanceof Error ? loaded.error.message : String(loaded.error)}
        onRetry={loaded.reload}
      />
    )
  }
  if (!payload) {
    return (
      <div className="card card-pad text-center">
        <p className="font-medium text-slate-700">还没有可打印的志愿表</p>
        <p className="muted mt-1">请先生成志愿表，报告会同时给出每个志愿的依据与数据来源。</p>
        <Link to="/plan" className="btn-primary mt-3 inline-flex">
          去生成志愿表
        </Link>
      </div>
    )
  }

  const plan = payload.plan
  const student = profile.student

  return (
    <div className="space-y-5">
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">志愿报告</h1>
          <p className="muted mt-1">可直接用浏览器打印（Ctrl/⌘ + P）或导出 PDF / Excel。</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-primary" onClick={() => window.print()}>
            打印 / 存为 PDF
          </button>
          <a className="btn-secondary" href={api.plans.exportUrl(plan.id, 'pdf')}>
            下载 PDF
          </a>
          <a className="btn-secondary" href={api.plans.exportUrl(plan.id, 'xlsx')}>
            下载 Excel
          </a>
        </div>
      </div>

      <article className="space-y-5">
        {/* ------------------------------ 表头 ------------------------------ */}
        <header className="card card-pad">
          <h1 className="text-lg font-semibold text-slate-900">
            {provinceLabel(plan.province)}普通高校招生志愿表（模拟数据）
          </h1>
          <p className="muted mt-1">
            生成时间 {formatDateTime(new Date().toISOString())} · 志愿表编号{' '}
            <span className="font-mono">{plan.id}</span> · {plan.rule.batch_name}
          </p>
          <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Field label="考生编号" value={plan.student_id} mono />
            <Field label="省份" value={provinceLabel(plan.province)} />
            <Field label="选考科目" value={profile.subjects.join('、') || '—'} />
            <Field label="高考总分" value={student ? formatScore(student.total_score) : formatScore(profile.totalScore)} />
            <Field label="位次" value={formatRank(profile.rank)} mono />
            <Field label="外语语种" value={student?.foreign_language ?? profile.foreignLanguage} />
            <Field
              label="投档模式"
              value={`${UNIT_TYPE_LABEL[plan.rule.unit_type] ?? plan.rule.unit_type} · ${plan.rule.max_volunteers} 个志愿`}
            />
            <Field label="志愿性质" value={plan.rule.is_parallel ? '平行志愿' : '顺序志愿'} />
          </div>
        </header>

        <Disclaimer text={disclaimerText} />

        {/* ------------------------------ 志愿表 ------------------------------ */}
        <section className="card card-pad">
          <h2 className="card-title">一、志愿表（共 {plan.items.length} 个志愿）</h2>
          <div className="mt-3 overflow-x-auto">
            <table className="data-table">
              <caption className="sr-only">按填报顺序排列的志愿表</caption>
              <thead>
                <tr>
                  <th scope="col">序</th>
                  <th scope="col">分层</th>
                  <th scope="col">院校</th>
                  <th scope="col">专业 / 专业组</th>
                  <th scope="col">选考要求</th>
                  <th scope="col">计划</th>
                  <th scope="col">学费</th>
                  <th scope="col">概率区间</th>
                  {plan.rule.has_major_adjustment ? <th scope="col">服从调剂</th> : null}
                </tr>
              </thead>
              <tbody>
                {plan.items.map((item) => {
                  const college = payload.colleges?.[item.unit.college_id]
                  return (
                    <tr key={item.unit.unit_id} className="print-avoid-break">
                      <td className="num">{item.position}</td>
                      <td>
                        <TierBadge tier={item.tier} />
                      </td>
                      <td>
                        <div className="font-medium">{college?.name ?? item.unit.college_id}</div>
                        <div className="text-xs text-slate-500">
                          {college?.province ? `${provinceLabel(college.province)}${college.city ?? ''}` : ''}
                          {college?.level_tags?.length ? ` · ${college.level_tags.join('/')}` : ''}
                          {college && !college.is_public ? ' · 非公办' : ''}
                        </div>
                      </td>
                      <td>
                        {item.unit.group_name ? <div className="text-xs text-slate-500">{item.unit.group_name}</div> : null}
                        {item.unit.major_name}
                      </td>
                      <td className="text-xs">{describeSubjectRequirement(item.unit.subject_requirement)}</td>
                      <td className="num">{formatPlanCount(item.unit.plan_count)}</td>
                      <td className="num">{formatTuition(item.unit.tuition)}</td>
                      <td className="num">{formatInterval(item.probability_interval ?? null)}</td>
                      {plan.rule.has_major_adjustment ? (
                        <td>{item.obey_adjustment === true ? '服从' : item.obey_adjustment === false ? '不服从' : '未选'}</td>
                      ) : null}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* ------------------------------ 每志愿依据 ------------------------------ */}
        <section className="card card-pad">
          <h2 className="card-title">二、每个志愿的依据</h2>
          <ol className="mt-3 space-y-4">
            {plan.items.map((item) => {
              const college = payload.colleges?.[item.unit.college_id]
              const records = evidenceByUnit.get(item.unit.unit_id) ?? []
              return (
                <li key={item.unit.unit_id} className="print-avoid-break rounded-lg border border-slate-200 p-3">
                  <p className="font-medium">
                    {item.position}. {college?.name ?? item.unit.college_id} · {item.unit.major_name}
                  </p>
                  {(item.notes ?? []).length > 0 && (
                    <ul className="mt-1 list-inside list-disc text-sm text-slate-600">
                      {(item.notes ?? []).map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  )}
                  {records.length > 0 ? (
                    <table className="data-table mt-2">
                      <thead>
                        <tr>
                          <th scope="col">年份</th>
                          <th scope="col">最低位次</th>
                          <th scope="col">数据质量</th>
                          <th scope="col">来源</th>
                        </tr>
                      </thead>
                      <tbody>
                        {records.map((record, index) => (
                          <tr key={`${record.year}-${index}`}>
                            <td className="num">{record.year}</td>
                            <td className="num">{formatRank(record.min_rank)}</td>
                            <td className="text-xs">{record.data_quality}</td>
                            <td>
                              <SourceLink url={record.source_url} label="来源" />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="mt-1 text-xs text-amber-700">
                      无本单位历史（新增专业）：概率来自同类单位类比，置信度低，不得当作保底。
                    </p>
                  )}
                </li>
              )
            })}
          </ol>
        </section>

        {/* ------------------------------ 风险 ------------------------------ */}
        <section className="card card-pad">
          <h2 className="card-title">三、风险提示</h2>
          <div className="mt-3">
            <RiskPanel risks={payload.risks ?? []} violations={payload.stats?.violations ?? []} />
          </div>
        </section>

        {/* ------------------------------ 来源清单 ------------------------------ */}
        <section className="card card-pad">
          <h2 className="card-title">四、数据来源清单</h2>
          <p className="muted mt-1 text-xs">
            以下为本次报告中所有数字的来源。任何没有来源的数字都不应出现在报告里；
            若你发现某个数字无法在此清单中对应，请视为异常并核实。
          </p>
          <table className="data-table mt-3">
            <thead>
              <tr>
                <th scope="col">用途</th>
                <th scope="col">来源地址</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>批次投档规则</td>
                <td>
                  <SourceLink url={plan.rule.source_url} label={plan.rule.source_url} />
                  <span className="ml-2 text-xs text-slate-500">
                    核实等级：{verifiedStyle(plan.rule.verified_status).label}
                    {plan.rule.verified_year ? ` · ${plan.rule.verified_year} 年` : ''}
                  </span>
                </td>
              </tr>
              {sources
                .filter((source) => source.url !== plan.rule.source_url)
                .map((source) => (
                  <tr key={source.url}>
                    <td>{source.what}</td>
                    <td>
                      <SourceLink url={source.url} label={source.url} />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">
            共 {sources.length} 条来源 · 每个志愿最多引用近 3 年历史记录
          </p>
        </section>

        <Disclaimer text={disclaimerText} />
      </article>
    </div>
  )
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={mono ? 'num font-medium' : 'font-medium'}>{value}</p>
    </div>
  )
}
