/**
 * API 客户端（AGENTS.md §4.3）。
 *
 * 铁律：
 * - **契约唯一来源是后端 OpenAPI**：本文件的所有业务类型都从 `./schema`（由
 *   `pnpm gen:api` 从 `/openapi.json` 生成）取，禁止手写第二份字段定义；
 * - API 基址来自 `VITE_API_BASE_URL`，**禁止硬编码 localhost**（dev 由 Vite proxy 转发）；
 * - 所有响应都是 `{data, evidence, warnings}` 三段信封，错误统一为 `{error:{code,message,details}}`。
 */
import type { components } from './schema'

export type Schema = components['schemas']

// ---- 业务类型别名（全部来自生成的契约，便于业务代码书写） ----
export type ProvinceMeta = Schema['ProvinceMeta']
export type BatchMeta = Schema['BatchMeta']
export type SubjectPoolMeta = Schema['SubjectPoolMeta']
export type SubjectCoveragePayload = Schema['SubjectCoveragePayload']
export type TiersPayload = Schema['TiersPayload']
export type MajorTaxonomyPayload = Schema['MajorTaxonomyPayload']
export type StudentPayload = Schema['StudentPayload']
export type ResolveRankPayload = Schema['ResolveRankPayload']
export type RecommendItem = Schema['RecommendItem']
export type RecommendStats = Schema['RecommendStats']
export type RecommendPayload = Schema['RecommendPayload']
export type PlanPayload = Schema['PlanPayload']
export type PlanStats = Schema['PlanStats']
export type VolunteerPlan = Schema['VolunteerPlan']
export type PlanItem = Schema['PlanItem']
export type AdmissionUnit = Schema['AdmissionUnit']
export type CollegeBlock = Schema['CollegeBlock']
export type MajorBlock = Schema['MajorBlock']
export type Risk = Schema['Risk']
export type RiskScanPayload = Schema['RiskScanPayload']
export type RuleBlock = Schema['RuleBlock']
export type HistoryEvidence = Schema['HistoryEvidence']
export type Adjustment = Schema['Adjustment']
export type UnitHistoryPayload = Schema['UnitHistoryPayload']
export type UnitHistoryRecord = Schema['UnitHistoryRecord']
export type CollegeSearchItem = Schema['CollegeSearchItem']
export type MajorSearchItem = Schema['MajorSearchItem']
export type ChatHistoryPayload = Schema['ChatHistoryPayload']
export type ChatMessage = Schema['ChatMessage']
export type Tier = Schema['Tier']
export type Confidence = Schema['Confidence']
export type RuleViolation = Schema['RuleViolation']
export type FilterCriteriaInput = Schema['RecommendFilters']
export type StudentCreateRequest = Schema['StudentCreateRequest']
export type StudentPatchRequest = Schema['StudentPatchRequest']

/** 证据链条目（后端各端点的 `evidence` 都是自由结构，但**必须**带 `source_url`）。 */
export type EvidenceEntry = Record<string, unknown>

/**
 * 统一响应信封。
 *
 * 这里用**泛型包装**而不是逐个引用 `Envelope_RecommendPayload_` 之类的生成类型：
 * 信封形状由后端 `schemas.Envelope` 唯一定义，下面从生成的某个实例中 `Omit` 出来，
 * 因此形状依然只有契约这一个来源；而 `data` 换成业务载荷类型后，调用点才可读。
 */
type GeneratedEnvelope = Schema['Envelope_RecommendPayload_']
export type Envelope<T> = Omit<GeneratedEnvelope, 'data'> & { data: T }

/** 后端错误体（`{error:{code,message,details}}`）。 */
export interface ApiErrorBody {
  code: string
  message: string
  details?: Record<string, unknown>
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** 档案缺字段（409 PROFILE_INCOMPLETE）时回传的字段清单，供向导高亮。 */
  get missingFields(): string[] {
    const value = this.details['missing_fields']
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
  }
}

/**
 * 浏览器侧 API 基址。
 * 默认空字符串 = 同源（dev 由 Vite `server.proxy` 转发 `/api`）；生产由环境变量指定。
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')
export const API_PREFIX = `${API_BASE}/api/v1`

type QueryValue = string | number | boolean | undefined | null | Array<string | number>

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = `${API_PREFIX}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item))
    } else {
      params.append(key, String(value))
    }
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

async function parseError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  const error = (body as { error?: ApiErrorBody } | null)?.error
  if (error && typeof error.message === 'string') {
    return new ApiError(response.status, error.code || 'HTTP_ERROR', error.message, error.details ?? {})
  }
  // FastAPI 原生校验错误（422）是 {detail: [...]}，没有统一错误体 —— 也要说人话
  const detail = (body as { detail?: unknown } | null)?.detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        const record = item as { loc?: unknown[]; msg?: string }
        const loc = Array.isArray(record.loc) ? record.loc.join('.') : ''
        return loc ? `${loc}: ${record.msg ?? ''}` : (record.msg ?? '')
      })
      .filter(Boolean)
    return new ApiError(response.status, 'VALIDATION_ERROR', messages.join('；') || '请求参数不合法', {
      detail,
    })
  }
  return new ApiError(response.status, 'HTTP_ERROR', `请求失败（HTTP ${response.status}）`)
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; query?: Record<string, QueryValue>; signal?: AbortSignal } = {},
): Promise<Envelope<T>> {
  const { method = 'GET', body, query, signal } = options
  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(
      0,
      'NETWORK_ERROR',
      '连不上后端服务。请确认后端已启动（uvicorn app.main:app --port 8000）。',
    )
  }
  if (!response.ok) throw await parseError(response)
  return (await response.json()) as Envelope<T>
}

/** 原始（非信封）请求：导出报告等返回二进制/文本的端点使用。 */
async function requestRaw(path: string, query?: Record<string, QueryValue>): Promise<Response> {
  const response = await fetch(buildUrl(path, query))
  if (!response.ok) throw await parseError(response)
  return response
}

// ---------------------------------------------------------------------------
// 端点封装
// ---------------------------------------------------------------------------
export const api = {
  meta: {
    provinces: () => request<ProvinceMeta[]>('/meta/provinces'),
    provinceRule: (province: string) => request<ProvinceMeta>(`/meta/provinces/${province}/rule`),
    subjectCoverage: (province: string, subjects: string[]) =>
      request<SubjectCoveragePayload>(`/meta/provinces/${province}/subject-coverage`, {
        query: { subjects: subjects.join(',') },
      }),
    tiers: () => request<TiersPayload>('/meta/tiers'),
    // ★ ADR-022：专业分类规则库（门类 → 专业类），供意向专业分级选择。
    //   唯一权威来源是后端规则库，前端**不得**自己列一份门类清单（必然漂移）。
    majorTaxonomy: () => request<MajorTaxonomyPayload>('/meta/major-taxonomy'),
  },

  students: {
    create: (payload: Partial<StudentCreateRequest> & { province: string }) =>
      request<StudentPayload>('/students', { method: 'POST', body: payload }),
    get: (studentId: string) => request<StudentPayload>(`/students/${studentId}`),
    patch: (studentId: string, payload: StudentPatchRequest) =>
      request<StudentPayload>(`/students/${studentId}`, { method: 'PATCH', body: payload }),
    resolveRank: (studentId: string) =>
      request<ResolveRankPayload>(`/students/${studentId}/resolve-rank`, { method: 'POST' }),
  },

  recommend: (payload: Schema['RecommendRequest']) =>
    request<RecommendPayload>('/recommend', { method: 'POST', body: payload }),

  plans: {
    generate: (payload: Schema['PlanGenerateRequest']) =>
      request<PlanPayload>('/plans/generate', { method: 'POST', body: payload }),
    get: (planId: string) => request<PlanPayload>(`/plans/${planId}`),
    patchItems: (planId: string, payload: Schema['PlanPatchRequest']) =>
      request<PlanPayload>(`/plans/${planId}/items`, { method: 'PATCH', body: payload }),
    validate: (planId: string) =>
      request<PlanPayload>(`/plans/${planId}/validate`, { method: 'POST' }),
    exportUrl: (planId: string, format: 'pdf' | 'xlsx') =>
      buildUrl(`/plans/${planId}/export`, { format }),
    download: (planId: string, format: 'pdf' | 'xlsx') =>
      requestRaw(`/plans/${planId}/export`, { format }),
  },

  risk: {
    scan: (payload: Schema['RiskScanRequest']) =>
      request<RiskScanPayload>('/risk/scan', { method: 'POST', body: payload }),
  },

  catalog: {
    unitHistory: (unitId: string, years = 3) =>
      request<UnitHistoryPayload>(`/units/${encodeURIComponent(unitId)}/history`, { query: { years } }),
    collegeSearch: (query: { q?: string; province?: string; level?: string; limit?: number }) =>
      request<CollegeSearchItem[]>('/colleges/search', { query }),
    majorSearch: (query: { q?: string; category?: string; discipline?: string; limit?: number }) =>
      request<MajorSearchItem[]>('/majors/search', { query }),
  },

  chat: {
    history: (sessionId: string) => request<ChatHistoryPayload>(`/chat/${sessionId}/history`),
  },

  /** 志愿表导出直链（用于 <a download> / window.open，带 Origin 同源 cookie 语义）。 */
  exportUrl: (planId: string, format: 'pdf' | 'xlsx') => buildUrl(`/plans/${planId}/export`, { format }),
}

// ---------------------------------------------------------------------------
// 对话 SSE（POST /chat 是流式接口，EventSource 只支持 GET，因此用 fetch + ReadableStream）
// ---------------------------------------------------------------------------
export interface ChatStreamEvent {
  event: 'start' | 'delta' | 'done' | 'error'
  data: Record<string, unknown>
}

/**
 * 流式对话。
 *
 * M3 的 `/chat` **不是可用助手**：它只有 SSE 通道与防幻觉底线，回复里不含任何数字，
 * 真正的工具化回答在 M5（AGENTS.md §9）。前端必须如实标注这个能力边界。
 */
export async function streamChat(
  payload: { message: string; session_id?: string; student_id?: string },
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_PREFIX}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    throw new ApiError(0, 'NETWORK_ERROR', '连不上后端服务，无法开始对话。')
  }
  if (!response.ok) throw await parseError(response)
  if (!response.body) throw new ApiError(0, 'STREAM_ERROR', '响应没有可读流。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const flush = (chunk: string) => {
    // SSE 帧以空行分隔；一帧内可能有 event: / data: 多行
    let event = 'message'
    const dataLines: string[] = []
    for (const line of chunk.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) return
    try {
      const parsed = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
      onEvent({ event: event as ChatStreamEvent['event'], data: parsed })
    } catch {
      onEvent({ event: 'delta', data: { text: dataLines.join('\n') } })
    }
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index = buffer.indexOf('\n\n')
    while (index !== -1) {
      const frame = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      if (frame.trim()) flush(frame)
      index = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) flush(buffer)
}
