/**
 * 领域文案与配色（UI 的唯一来源）。
 *
 * 分层区间、配额、安全闸门的**数值**来自后端 `/meta/tiers`（禁止前端写死）；
 * 本文件只放"怎么显示"：中文名、颜色、一句话解释。
 * 风险码与选考要求的**权威描述**一律用后端返回的 `message` / `suggestion`，
 * 本文件只提供短标签，避免前端成为第二份规则文档。
 */
import type { Confidence, Tier } from '../api/client'

export interface TierStyle {
  /** 中文单字：冲 / 稳 / 保 / 垫 */
  label: string
  /** 完整名称，用于图例与报告 */
  name: string
  /** 一句话人话解释（与后端 §6.3 表一致） */
  hint: string
  /** Tailwind 类：徽标 */
  badge: string
  /** Tailwind 类：进度条填充 */
  fill: string
  /** 十六进制色值（ECharts 用） */
  hex: string
}

export const TIER_ORDER: Tier[] = ['CHONG', 'WEN', 'BAO', 'DIAN', 'TOO_RISKY', 'NO_DATA']

export const TIER_STYLE: Record<Tier, TierStyle> = {
  CHONG: {
    label: '冲',
    name: '冲',
    hint: '有机会但不稳',
    badge: 'bg-amber-100 text-amber-800 ring-1 ring-amber-200',
    fill: 'bg-tier-chong',
    hex: '#f59e0b',
  },
  WEN: {
    label: '稳',
    name: '稳',
    hint: '大概率能上',
    badge: 'bg-sky-100 text-sky-800 ring-1 ring-sky-200',
    fill: 'bg-tier-wen',
    hex: '#0284c7',
  },
  BAO: {
    label: '保',
    name: '保',
    hint: '很稳（且通过真保底余量闸门）',
    badge: 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200',
    fill: 'bg-tier-bao',
    hex: '#059669',
  },
  DIAN: {
    label: '垫',
    name: '垫',
    hint: '绝对兜底（且通过真保底余量闸门）',
    badge: 'bg-indigo-100 text-indigo-800 ring-1 ring-indigo-200',
    fill: 'bg-tier-dian',
    hex: '#4f46e5',
  },
  TOO_RISKY: {
    label: '险',
    name: '基本无望',
    hint: '基本无望，默认不推荐',
    badge: 'bg-rose-100 text-rose-800 ring-1 ring-rose-200',
    fill: 'bg-tier-risky',
    hex: '#e11d48',
  },
  NO_DATA: {
    label: '无据',
    name: '无可用数据',
    hint: '没有可用历史，概率不计算（宁可不答，不可编造）',
    badge: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',
    fill: 'bg-tier-nodata',
    hex: '#64748b',
  },
}

/** 分层中文名（图表/摘要用）。 */
export const TIER_LABEL: Record<string, string> = Object.fromEntries(
  Object.entries(TIER_STYLE).map(([tier, style]) => [tier, style.label]),
)

export interface ConfidenceStyle {
  label: string
  badge: string
  hint: string
}

export const CONFIDENCE_STYLE: Record<Confidence, ConfidenceStyle> = {
  HIGH: {
    label: '高置信',
    badge: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
    hint: '3 年完整数据、计划数充足、波动小',
  },
  MEDIUM: {
    label: '中置信',
    badge: 'bg-sky-50 text-sky-700 ring-1 ring-sky-200',
    hint: '数据年份或计划数略不足',
  },
  LOW: {
    label: '低置信',
    badge: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
    hint: '仅 1 年数据 / 计划数 <5 / 存在缺失位次',
  },
  NO_DATA: {
    label: '无数据',
    badge: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',
    hint: '无可用历史，概率不计算',
  },
}

export interface RiskLevelStyle {
  label: string
  badge: string
  /** HIGH 级必须阻断式提示（AGENTS.md §8.2） */
  blocking: boolean
}

export const RISK_LEVEL_STYLE: Record<string, RiskLevelStyle> = {
  HIGH: { label: '高风险', badge: 'bg-rose-100 text-rose-800 ring-1 ring-rose-300', blocking: true },
  MEDIUM: { label: '中风险', badge: 'bg-amber-100 text-amber-800 ring-1 ring-amber-200', blocking: false },
  LOW: { label: '提示', badge: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200', blocking: false },
}

/** 风险码短标签（AGENTS.md §6.8 的 14 个码 + 概率层警告码）。权威说明用后端 message。 */
export const RISK_CODE_LABEL: Record<string, string> = {
  NO_SAFETY_NET: '保底不足',
  SAFETY_NOT_SAFE: '垫底不真保底',
  GRADIENT_INVERSION: '梯度倒挂',
  INSUFFICIENT_COUNT: '志愿数不足',
  PLAN_TOO_SMALL: '计划数过小',
  VOLATILE_HISTORY: '大小年明显',
  NO_HISTORY: '无本单位历史',
  SINGLE_YEAR_DATA: '仅 1 年数据',
  NO_OBEDIENCE: '未服从调剂',
  GROUP_UNACCEPTABLE: '组内含排斥专业',
  PHYSICAL_LIMIT: '体检受限',
  // ★ ADR-022：TUITION_HIGH 已移除（它依赖"预算舒适线"，而学费预算随学费维度一并删除）。
  //   铁律 10（学费必须让家长看见）由展示层保证：卡片/志愿表/报告都显示学费 + 非公办标记。
  SUSPECT_DATA: '数据存疑',
  COLLECTED_ONLY: '仅征集志愿数据',
  SAFETY_MARGIN_NOT_MET: '未通过真保底闸门',
  DERIVED_DATA_DOWNWEIGHTED: '位次为反查推算',
  SUSPECT_DATA_IGNORED: '存疑数据已剔除',
  MISSING_RANK_IGNORED: '缺位次记录已剔除',
  NO_NORMALIZATION_BASIS: '缺考生人数分母',
  ANALOG_POOL_FALLBACK: '采用同类单位类比',
  UNKNOWN_BATCH: '批次未知',
}

export function riskCodeLabel(code: string): string {
  return RISK_CODE_LABEL[code] ?? code
}

/** 六省市中文名（省代码来自后端规则包 keys）。 */
export const PROVINCE_LABEL: Record<string, string> = {
  zhejiang: '浙江',
  shanghai: '上海',
  beijing: '北京',
  shandong: '山东',
  tianjin: '天津',
  hainan: '海南',
}

/**
 * 院校所在地中文名（ADR-017）。
 *
 * 为什么需要它：**规则包只有六省市，但考生的候选池覆盖全国**——
 * 浙江考生能报的院校分布在 31 个省级行政区（江苏 1,549 个单位、湖北 943 个…）。
 * 推荐页的"意向地区"如果只列六省市，考生想选"江苏"就选不到；
 * 后端因此在 `/recommend` 的 `stats.region_options` 里回传候选池的实际分布，
 * 这里只负责把省代码显示成中文。
 */
export const REGION_LABEL: Record<string, string> = {
  ...PROVINCE_LABEL,
  hebei: '河北',
  shanxi: '山西',
  neimenggu: '内蒙古',
  liaoning: '辽宁',
  jilin: '吉林',
  heilongjiang: '黑龙江',
  jiangsu: '江苏',
  anhui: '安徽',
  fujian: '福建',
  jiangxi: '江西',
  henan: '河南',
  hubei: '湖北',
  hunan: '湖南',
  guangdong: '广东',
  guangxi: '广西',
  chongqing: '重庆',
  sichuan: '四川',
  guizhou: '贵州',
  yunnan: '云南',
  xizang: '西藏',
  shaanxi: '陕西',
  gansu: '甘肃',
  qinghai: '青海',
  ningxia: '宁夏',
  xinjiang: '新疆',
}

/** 地区名（找不到时原样回显代码，不编造）。 */
export function regionLabel(code: string | null | undefined): string {
  if (!code) return '—'
  return REGION_LABEL[code] ?? code
}

export function provinceLabel(code: string | null | undefined): string {
  if (!code) return '—'
  return PROVINCE_LABEL[code] ?? code
}

/** 核实状态徽标（DOMAIN_RULES §1.2）。 */
export const VERIFIED_STYLE: Record<string, { label: string; badge: string }> = {
  PRIMARY: { label: '已核实（官方原文）', badge: 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200' },
  PRIMARY_GOV: {
    label: '已核实（政府门户转述）',
    badge: 'bg-lime-100 text-lime-800 ring-1 ring-lime-200',
  },
  SECONDARY: { label: '待核实（转载源）', badge: 'bg-amber-100 text-amber-900 ring-1 ring-amber-300' },
  UNVERIFIED: { label: '未核实', badge: 'bg-rose-100 text-rose-800 ring-1 ring-rose-300' },
}

export function verifiedStyle(status: string | null | undefined) {
  return VERIFIED_STYLE[status ?? ''] ?? VERIFIED_STYLE['UNVERIFIED']!
}

/** 投档单位类型 → 人话。 */
export const UNIT_TYPE_LABEL: Record<string, string> = {
  MAJOR_COLLEGE: '专业(类)+院校',
  MAJOR_GROUP: '院校专业组',
}

/** 档案缺字段 → 向导中文名（与后端 `missing_fields` 取值对齐）。 */
export const MISSING_FIELD_LABEL: Record<string, string> = {
  province: '省份',
  subjects: '选考科目（恰好 3 门）',
  total_score: '高考总分',
  rank: '位次（填了总分可自动换算）',
}

export function missingFieldLabel(field: string): string {
  return MISSING_FIELD_LABEL[field] ?? field
}
