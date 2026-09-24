/**
 * 端到端冒烟：**按前端真实调用顺序**走一遍"建档 → 推荐 → 志愿表 → 校验 → 手改 → 导出"闭环，
 * 并逐条断言界面依赖的硬性规则（AGENTS.md §8）。
 *
 * 为什么不用浏览器跑：本仓库的验收命令是 `npm run build && npm run typecheck`（§10 M4），
 * 浏览器 E2E 在 M7 引入；但"闭环可走通"不能靠肉眼，所以这里用 Node 直接打后端，
 * 断言口径与页面完全一致（同样的端点、同样的字段、同样的铁律）。
 *
 * 用法：node scripts/smoke.mjs            （后端需在 API_ORIGIN 上运行）
 *      API_ORIGIN=http://127.0.0.1:8000 node scripts/smoke.mjs
 */
const ORIGIN = (process.env.API_ORIGIN || process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(
  /\/+$/,
  '',
)
const API = `${ORIGIN}/api/v1`

let failures = 0
const notes = []

function check(condition, label, detail = '') {
  if (condition) {
    console.log(`  ✓ ${label}`)
  } else {
    failures += 1
    console.error(`  ✗ ${label}${detail ? ` —— ${detail}` : ''}`)
  }
}

async function call(method, path, body) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  if (!response.ok) {
    throw new Error(`${method} ${path} → HTTP ${response.status}: ${text.slice(0, 300)}`)
  }
  return text ? JSON.parse(text) : null
}

async function raw(path) {
  const response = await fetch(`${API}${path}`)
  if (!response.ok) throw new Error(`GET ${path} → HTTP ${response.status}`)
  return response
}

async function main() {
  console.log(`[smoke] 目标后端 ${ORIGIN}`)

  // ---------------------------------------------------------------- 元数据
  console.log('\n1) 首屏 Step 1/2：省份规则与选考科目池')
  const provinces = (await call('GET', '/meta/provinces')).data
  check(provinces.length === 6, '六省市规则均可读', `实际 ${provinces.length}`)
  for (const province of provinces) {
    check(Boolean(province.current_year), `${province.province} 带 current_year`)
    const pool = province.subject_pool
    check(Boolean(pool), `${province.province} 有选考科目池`)
    if (!pool) continue
    check(pool.origin === 'RULE', `${province.province} 科目池来自规则（非反推）`, pool.origin)
    check(Boolean(pool.source_url && pool.source_quote), `${province.province} 科目池带来源与原文`)
    check((pool.subjects ?? []).length >= 3, `${province.province} 科目池至少 3 门`)
    check((province.batches ?? []).length > 0, `${province.province} 至少一个批次`)
  }
  const zhejiang = provinces.find((item) => item.province === 'zhejiang')
  check(zhejiang?.subject_pool?.mode === '7选3', '浙江为 7 选 3')
  check((zhejiang?.subject_pool?.subjects ?? []).includes('技术'), '浙江科目池含「技术」')
  const banner = provinces.filter((item) => item.requires_banner).map((item) => item.province)
  check(
    banner.includes('tianjin') && banner.includes('hainan'),
    '天津/海南要求「规则待核实」横幅（红线）',
    banner.join(','),
  )

  // ---------------------------------------------------------------- 建档
  console.log('\n2) 首屏 Step 3：建档 + 分数 → 位次换算')
  const created = await call('POST', '/students', {
    province: 'zhejiang',
    year: zhejiang.current_year,
    subjects: ['物理', '化学', '生物'],
    total_score: 640,
    gender: '男',
    foreign_language: '英语',
    single_subject_scores: { 英语: 125 },
  })
  const student = created.data
  check(student.id.startsWith('stu-'), '创建档案返回 id', student.id)
  check((student.missing_fields ?? []).length === 0, '档案完整（missing_fields 为空）')

  const rank = (await call('POST', `/students/${student.id}/resolve-rank`)).data
  check(Number.isInteger(rank.rank) && rank.rank > 0, '分数换成位次', String(rank.rank))
  check(rank.total_candidates > 0, '给出总考生数（位次归一化分母）')
  check(Boolean(rank.source_url), '位次带来源', rank.source_url)

  const coverage = (
    await call('GET', `/meta/provinces/zhejiang/subject-coverage?subjects=${encodeURIComponent('物理,化学,生物')}`)
  ).data
  check(coverage.total_units > 0, '覆盖率统计有数据')
  check(coverage.coverage > 0 && coverage.coverage <= 1, '覆盖率在 (0,1]', String(coverage.coverage))
  check(Boolean(coverage.source_url), '覆盖率带规则来源')

  // ---------------------------------------------------------------- 推荐
  console.log('\n3) 推荐列表：概率区间 + 证据链（契约铁律）')
  const recommend = await call('POST', '/recommend', {
    student_id: student.id,
    filters: { regions: [], levels: [], majors: [], tuition_max: null, exclude_unit_ids: [], intent_as_hard: false },
    limit: 60,
    include_too_risky: false,
  })
  const items = recommend.data.items ?? []
  check(items.length > 0, '返回推荐项', String(items.length))
  check(Boolean(recommend.data.stats?.rule?.unit_type), 'stats.rule 带 unit_type')
  let missingInterval = 0
  let missingEvidence = 0
  let unsourcedEvidence = 0
  let badConfidence = 0
  for (const item of items) {
    if (!item.probability_interval || item.probability_interval.length < 2) missingInterval += 1
    if (!item.evidence || item.evidence.length === 0) missingEvidence += 1
    for (const entry of item.evidence ?? []) {
      if (!entry.source_url && !entry.note) unsourcedEvidence += 1
    }
    if ((item.probability === null) !== (item.confidence === 'NO_DATA')) badConfidence += 1
    if (item.tier === 'NO_DATA') badConfidence += 1
  }
  check(missingInterval === 0, '每个推荐项都有 ±1σ 概率区间（UI 只显示区间）', `${missingInterval} 项缺失`)
  check(missingEvidence === 0, '每个推荐项 evidence 非空（契约铁律 1）', `${missingEvidence} 项缺失`)
  check(unsourcedEvidence === 0, '每条证据都有 source_url 或明确的类比标注', `${unsourcedEvidence} 条`)
  check(badConfidence === 0, 'probability=null ⇔ confidence=NO_DATA（契约铁律 2）', `${badConfidence} 项`)
  const tiers = [...new Set(items.map((item) => item.tier))]
  check(tiers.every((tier) => tier !== 'TOO_RISKY'), '默认不返回「基本无望」', tiers.join(','))

  // ---------------------------------------------------------------- 志愿表
  console.log('\n4) 志愿表：生成 → 读取 → 校验')
  const generated = await call('POST', '/plans/generate', {
    student_id: student.id,
    filters: { regions: [], levels: [], majors: [], tuition_max: null, exclude_unit_ids: [], intent_as_hard: false },
    preference_order: items.slice(0, 10).map((item) => item.unit.unit_id),
    obey_adjustment: null,
  })
  const planId = generated.data.plan.id
  const plan = generated.data.plan
  check(plan.items.length > 0, '志愿表非空', `${plan.items.length} 个志愿`)
  check(
    plan.items.every((item) => Array.isArray(item.probability_interval) && item.probability_interval.length === 2),
    '每个志愿都带概率区间（志愿表页同样只显示区间）',
  )
  const colleges = generated.data.colleges ?? {}
  check(Object.keys(colleges).length > 0, '志愿表带院校名索引（否则页面无法阅读）')
  check(
    plan.items.every((item) => Boolean(colleges[item.unit.college_id]?.name)),
    '每个志愿的院校都能查到名字',
  )
  check(
    plan.items.every((item) => item.unit.tuition == null || item.unit.tuition > 0),
    '学费为正数或明确缺失（缺失时 UI 必须显示待核验提示，不得显示 0 元）',
  )
  const distribution = plan.tier_distribution ?? {}
  const last = plan.items[plan.items.length - 1]
  check(['BAO', 'DIAN'].includes(last.tier), '最后一档是保/垫（§6.7 步骤 3）', last.tier)
  notes.push(
    `分层分布 ${JSON.stringify(distribution)}；风险 ${(generated.data.risks ?? []).length} 条` +
      `（HIGH ${(generated.data.risks ?? []).filter((risk) => risk.level === 'HIGH').length} 条）`,
  )

  const fetched = await call('GET', `/plans/${planId}`)
  check(fetched.data.plan.id === planId, '志愿表可按 id 读回')
  check((fetched.data.colleges ?? null) !== null, '读回时同样带院校索引')
  check((fetched.evidence ?? []).length > 0, '志愿表带逐项来源证据')
  const validated = await call('POST', `/plans/${planId}/validate`)
  check(Array.isArray(validated.data.risks), '风险可重跑')

  // ---------------------------------------------------------------- 手改
  console.log('\n5) 手改：排序 / 移除 / 加回')
  const order = plan.items.map((item) => item.unit.unit_id)
  const reversed = [...order].reverse()
  const reordered = await call('PATCH', `/plans/${planId}/items`, {
    items: reversed.map((unitId) => ({ unit_id: unitId })),
    filters: { regions: [], levels: [], majors: [], tuition_max: null, exclude_unit_ids: [], intent_as_hard: false },
  })
  check(
    reordered.data.plan.items.map((item) => item.unit.unit_id).join('|') === reversed.join('|'),
    '拖拽排序后顺序与提交一致',
  )
  const withoutFirst = reversed.slice(1)
  const shrunk = await call('PATCH', `/plans/${planId}/items`, {
    items: withoutFirst.map((unitId) => ({ unit_id: unitId })),
    filters: { regions: [], levels: [], majors: [], tuition_max: null, exclude_unit_ids: [], intent_as_hard: false },
  })
  check(shrunk.data.plan.items.length === withoutFirst.length, '移除一个志愿成功')
  const restored = await call('PATCH', `/plans/${planId}/items`, {
    items: reversed.map((unitId) => ({ unit_id: unitId })),
    filters: { regions: [], levels: [], majors: [], tuition_max: null, exclude_unit_ids: [], intent_as_hard: false },
  })
  check(restored.data.plan.items.length === reversed.length, '移除的志愿可以加回来（不可逆操作是危险缺陷）')

  // ---------------------------------------------------------------- 导出
  console.log('\n6) 导出与报告数据源')
  const pdf = await raw(`/plans/${planId}/export?format=pdf`)
  const pdfBytes = new Uint8Array(await pdf.arrayBuffer())
  check(pdfBytes[0] === 0x25 && pdfBytes[1] === 0x50, 'PDF 导出可用（%PDF 头）')
  const xlsx = await raw(`/plans/${planId}/export?format=xlsx`)
  const xlsxBytes = new Uint8Array(await xlsx.arrayBuffer())
  check(xlsxBytes[0] === 0x50 && xlsxBytes[1] === 0x4b, 'Excel 导出可用（zip 头）')

  const tierMeta = (await call('GET', '/meta/tiers')).data
  check(Boolean(tierMeta.disclaimer), '免责声明文案来自后端（报告页直接引用）')
  check((tierMeta.tiers ?? []).length >= 4, '分层区间来自后端（前端不写死 10/40/75/93）')

  console.log('\n[smoke] 备注：')
  for (const note of notes) console.log(`  · ${note}`)
  if (failures > 0) {
    console.error(`\n[smoke] 失败 ${failures} 项`)
    process.exit(1)
  }
  console.log('\n[smoke] 闭环全部通过 ✓')
}

main().catch((error) => {
  console.error('[smoke] 执行中断：', error instanceof Error ? error.message : error)
  process.exit(1)
})
