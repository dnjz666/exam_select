import { useEffect, useRef, useState } from 'react'

import { api, streamChat, ApiError, type ChatMessage } from '../api/client'
import { ErrorNote } from '../components/StateBlocks'
import { formatDateTime } from '../lib/format'
import { missingFieldLabel } from '../lib/labels'
import { useProfileStore } from '../store/profile'

const SUGGESTIONS = [
  '帮我看看档案还缺什么？',
  '我是浙江考生，选了物理化学生物，考了 640 分',
  '浙江最多能填几个志愿？有没有专业调剂？',
  '查一下合肥工业大学的投档历史',
]

/** 本轮调用的工具（后端 ``tool_calls`` 的形状）。 */
interface ToolCallRecord {
  name: string
  arguments?: Record<string, unknown>
  result?: Record<string, unknown>
}

const TOOL_LABELS: Record<string, string> = {
  get_rank_by_score: '按分数查位次（一分一段表）',
  get_score_by_rank: '按位次反查分数',
  search_units: '检索投档单位',
  get_unit_history: '查该单位历年投档',
  estimate_probability: '估算录取概率',
  recommend_units: '生成推荐列表',
  generate_plan: '生成志愿表预览（不保存）',
  scan_risks: '扫描志愿风险',
  get_college_profile: '查院校档案',
  get_major_profile: '查专业档案',
  list_missing_fields: '检查档案完整度',
  get_province_rule: '查省份投档规则',
}

/** 构造本地消息：契约里这些字段是必填的（Pydantic 有默认值 → OpenAPI 标记 required）。 */
function localMessage(
  role: 'user' | 'assistant',
  content: string,
  extra: Partial<ChatMessage> = {},
): ChatMessage {
  return {
    id: `local-${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    session_id: '',
    role,
    content,
    created_at: new Date().toISOString(),
    missing_fields: [],
    tool_calls: [],
    mode: null,
    blocked: false,
    ...extra,
  }
}

/**
 * 对话页（AGENTS.md §8.2 `/chat`）。
 *
 * M5 起这是**真能查数据的助手**：每条回复都带 ``tool_calls``，
 * 考生能看到"这句话里的数字是查了哪个工具得来的"。
 *
 * 界面仍然如实标注边界：助手只能转述工具返回的数字；自己算、自己编的部分会被护栏拦掉
 * （被拦时本条消息会标出 ``blocked``，这不是故障，而是防护生效的痕迹）。
 */
export function ChatPage() {
  const profile = useProfileStore()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [missingFields, setMissingFields] = useState<string[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const sessionRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, draft])

  const send = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || streaming) return
    setError(null)
    setMissingFields([])
    setInput('')
    setDraft('')
    setMessages((current) => [...current, localMessage('user', trimmed)])
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let assembled = ''
    let toolCalls: ToolCallRecord[] = []
    let mode: string | null = null
    let blocked = false

    try {
      await streamChat(
        {
          message: trimmed,
          ...(sessionRef.current ? { session_id: sessionRef.current } : {}),
          ...(profile.studentId ? { student_id: profile.studentId } : {}),
        },
        (event) => {
          if (event.event === 'start') {
            const sessionId = event.data['session_id']
            if (typeof sessionId === 'string') sessionRef.current = sessionId
            return
          }
          if (event.event === 'delta') {
            const chunk = event.data['text']
            if (typeof chunk === 'string') {
              assembled += chunk
              setDraft(assembled)
            }
            return
          }
          if (event.event === 'done') {
            const content = event.data['content']
            const fields = event.data['missing_fields']
            const calls = event.data['tool_calls']
            if (typeof content === 'string') assembled = content
            if (Array.isArray(fields)) {
              setMissingFields(fields.filter((item): item is string => typeof item === 'string'))
            }
            if (Array.isArray(calls)) toolCalls = calls as ToolCallRecord[]
            if (typeof event.data['mode'] === 'string') mode = event.data['mode']
            blocked = event.data['blocked'] === true

            // 对话式建档：后端可能在这一轮新建了档案，前端必须接住这个 id，
            // 否则下一条消息会被当成"还没有档案"而重复建档。
            const returned = event.data['student_id']
            if (typeof returned === 'string' && returned !== profile.studentId) {
              void api.students
                .get(returned)
                .then((envelope) => {
                  profile.setStudent(envelope.data)
                  setNotice('已根据你的描述建立档案草稿，可在「建档向导」里核对或补充。')
                })
                .catch(() => undefined)
            }
          }
        },
        controller.signal,
      )
      setMessages((current) => [
        ...current,
        localMessage('assistant', assembled, {
          session_id: sessionRef.current ?? '',
          tool_calls: toolCalls as unknown as ChatMessage['tool_calls'],
          mode,
          blocked,
        }),
      ])
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) setError(caught)
    } finally {
      setDraft('')
      setStreaming(false)
      abortRef.current = null
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">与名师助手对话</h1>
        <p className="muted mt-1">建档、追问、解释——但数字只由算法给出，助手不会凭印象报数字。</p>
      </div>

      <div className="callout-info">
        <p className="font-medium">这个助手能做什么（如实说明）</p>
        <ul className="mt-1 list-inside list-disc text-sm">
          <li>
            <strong>能查数据</strong>：把分数换算成位次、查各省投档规则、查某所院校的历年投档、按你的档案推荐，
            扫志愿表风险；每条回复下方都能展开看它查了哪个工具。
          </li>
          <li>
            <strong>数字只来自工具</strong>：助手自己算或自己编的部分会被幻觉护栏拦掉。
            如果某条回复标了「已被护栏拦截」，那不是故障，而是防护生效——它想说一个没有出处的数字，
            被换成了"我需要先查数据"。
          </li>
          <li>
            <strong>可以对话建档</strong>：直接说你所在省份 + 3 门选考 + 总分（知道位次就一并说），
            我会写进档案草稿；缺什么我就问什么，不会替你假设。
          </li>
          <li>会话历史已落库，重启后端不会丢。</li>
        </ul>
      </div>

      {notice && (
        <p className="callout-muted text-sm" role="status">
          {notice}
        </p>
      )}

      <div className="card">
        <div className="max-h-[28rem] space-y-3 overflow-y-auto p-4">
          {messages.length === 0 && !draft && (
            <div className="space-y-2">
              <p className="muted">可以先从这些问题开始：</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="btn-secondary"
                    onClick={() => void send(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((message) => (
            <div
              key={message.id}
              className={[
                'max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap',
                message.role === 'user'
                  ? 'ml-auto bg-sky-600 text-white'
                  : 'mr-auto border border-slate-200 bg-slate-50 text-slate-800',
              ].join(' ')}
            >
              <p className="mb-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wide opacity-70">
                <span>{message.role === 'user' ? '你' : '名师助手'}</span>
                {message.created_at ? <span>{formatDateTime(message.created_at)}</span> : null}
                {message.role === 'assistant' && message.mode ? <span>{message.mode}</span> : null}
                {message.blocked ? (
                  <span className="chip bg-rose-100 text-rose-800 ring-1 ring-rose-300">
                    已被护栏拦截
                  </span>
                ) : null}
              </p>
              {message.content}
              {message.role === 'assistant' && (message.tool_calls?.length ?? 0) > 0 && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-slate-500">
                    查了什么（{message.tool_calls?.length ?? 0} 次工具调用）
                  </summary>
                  <ol className="mt-1 space-y-0.5 text-xs text-slate-500">
                    {(message.tool_calls as unknown as ToolCallRecord[]).map((call, index) => (
                      <li key={`${call.name}-${index}`}>
                        {TOOL_LABELS[call.name] ?? call.name}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </div>
          ))}

          {draft && (
            <div className="mr-auto max-w-[85%] rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm whitespace-pre-wrap text-slate-800">
              <p className="mb-1 text-[10px] uppercase tracking-wide opacity-70">名师助手 · 正在输入…</p>
              {draft}
            </div>
          )}

          {missingFields.length > 0 && (
            <div className="callout-warn">
              <p className="text-sm font-medium">还缺这些信息，补齐后我才能基于数据回答：</p>
              <ul className="mt-1 list-inside list-disc text-sm">
                {missingFields.map((field) => (
                  <li key={field}>{missingFieldLabel(field)}</li>
                ))}
              </ul>
            </div>
          )}

          {!!error && (
            <ErrorNote
              title="对话失败"
              message={
                error instanceof ApiError
                  ? error.message
                  : error instanceof Error
                    ? error.message
                    : String(error)
              }
            />
          )}
          <div ref={bottomRef} />
        </div>

        <form
          className="flex gap-2 border-t border-slate-200 p-3"
          onSubmit={(event) => {
            event.preventDefault()
            void send(input)
          }}
        >
          <label className="sr-only" htmlFor="chat-input">
            输入消息
          </label>
          <input
            id="chat-input"
            className="input"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="例如：我的档案还缺什么？"
            disabled={streaming}
          />
          {streaming ? (
            <button
              type="button"
              className="btn-secondary shrink-0"
              onClick={() => abortRef.current?.abort()}
            >
              停止
            </button>
          ) : (
            <button type="submit" className="btn-primary shrink-0" disabled={!input.trim()}>
              发送
            </button>
          )}
        </form>
      </div>

    </div>
  )
}
