import { useEffect, useRef, useState } from 'react'

import { streamChat, ApiError, type ChatMessage } from '../api/client'
import { Disclaimer } from '../components/Disclaimer'
import { ErrorNote } from '../components/StateBlocks'
import { formatDateTime } from '../lib/format'
import { missingFieldLabel } from '../lib/labels'
import { useProfileStore } from '../store/profile'

const SUGGESTIONS = [
  '我的档案还缺什么？',
  '我这个位次大概能报什么层次的学校？',
  '什么是"专业(类)+院校"和"院校专业组"的区别？',
  '为什么不服从调剂会退档？',
]

/**
 * 对话页（AGENTS.md §8.2 `/chat`）。
 *
 * ⚠️ **能力边界必须如实标注**：M3 的 `/chat` 只有 SSE 通道 + 会话历史 + 防幻觉底线，
 * 回复里**不含任何数字**（§0 最高原则）；真正的工具化回答（查位次、查历史、跑概率）在 M5。
 * 前端不能把"还不会查数据"包装成"已经能给你建议"。
 */
export function ChatPage() {
  const profile = useProfileStore()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [missingFields, setMissingFields] = useState<string[]>([])
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
    setMessages((current) => [
      ...current,
      { id: `local-${Date.now()}`, session_id: sessionRef.current ?? '', role: 'user', content: trimmed },
    ])
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let assembled = ''

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
            if (typeof content === 'string') assembled = content
            if (Array.isArray(fields)) {
              setMissingFields(fields.filter((item): item is string => typeof item === 'string'))
            }
          }
        },
        controller.signal,
      )
      setMessages((current) => [
        ...current,
        {
          id: `local-a-${Date.now()}`,
          session_id: sessionRef.current ?? '',
          role: 'assistant',
          content: assembled,
          created_at: new Date().toISOString(),
        },
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

      <div className="callout-warn">
        <p className="font-medium">能力边界（如实说明）</p>
        <ul className="mt-1 list-inside list-disc text-sm">
          <li>
            当前阶段（M3）的对话**还不能查数据**：它不会、也不允许说出任何分数线、位次、录取率或计划数。
          </li>
          <li>完整的工具化回答（查位次、查历史、跑概率、解释结果）在 M5 交付。</li>
          <li>
            需要真实数字时，请用「推荐列表」与「志愿表」页——那里的每个数字都有来源与证据链。
          </li>
          <li>会话历史存在服务端内存中，重启后端即清空。</li>
        </ul>
      </div>

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
              <p className="mb-1 text-[10px] uppercase tracking-wide opacity-70">
                {message.role === 'user' ? '你' : '名师助手'}
                {message.created_at ? ` · ${formatDateTime(message.created_at)}` : ''}
              </p>
              {message.content}
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

      <Disclaimer />
    </div>
  )
}
