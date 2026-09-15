import type { ReactNode } from 'react'

/**
 * 通用状态块：加载 / 错误 / 空。
 *
 * 错误提示必须**说人话 + 给下一步**（后端错误体 `{error:{code,message,details}}` 的
 * message 已经是中文可读文本，直接透出，不吞掉）。
 */

export function Loading({ label = '加载中…', rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      <p className="muted">{label}</p>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="card card-pad">
          <div className="skeleton h-4 w-1/3" />
          <div className="skeleton mt-3 h-3 w-2/3" />
          <div className="skeleton mt-2 h-3 w-1/2" />
        </div>
      ))}
    </div>
  )
}

export function ErrorNote({
  title = '出错了',
  message,
  hint,
  onRetry,
}: {
  title?: string
  message: string
  hint?: ReactNode
  onRetry?: () => void
}) {
  return (
    <div className="callout-danger" role="alert">
      <p className="font-semibold">{title}</p>
      <p className="mt-1">{message}</p>
      {hint && <div className="mt-2 text-xs">{hint}</div>}
      {onRetry && (
        <button type="button" className="btn-secondary mt-3" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="card card-pad text-center">
      <p className="font-medium text-slate-700">{title}</p>
      {hint && <div className="muted mt-2">{hint}</div>}
    </div>
  )
}

/** 数据来源链接。**任何数字旁边都应当能点开来源**（AGENTS.md §8.2）。 */
export function SourceLink({ url, label }: { url?: string | null; label?: string }) {
  if (!url) return <span className="text-xs text-slate-400">无来源链接</span>
  const isHttp = /^https?:\/\//i.test(url)
  if (!isHttp) {
    // 形如 manual://student-provided、draft://student-profile 的内部来源标识
    return <span className="text-xs text-slate-500">{label ?? url}</span>
  }
  return (
    <a className="source-link" href={url} target="_blank" rel="noreferrer noopener">
      {label ?? url}
    </a>
  )
}

/** 提示条（后端 `warnings` 的统一渲染）。 */
export function WarningList({ warnings, tone = 'warn' }: { warnings: readonly string[]; tone?: 'warn' | 'info' }) {
  if (!warnings.length) return null
  const cls = tone === 'warn' ? 'callout-warn' : 'callout-info'
  return (
    <ul className={`${cls} space-y-1`}>
      {warnings.map((warning) => (
        <li key={warning} className="flex gap-2">
          <span aria-hidden="true">{tone === 'warn' ? '⚠' : 'ℹ'}</span>
          <span>{warning}</span>
        </li>
      ))}
    </ul>
  )
}
