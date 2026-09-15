export interface StepIndicatorProps {
  steps: readonly string[]
  current: number
  /** 已完成的步骤（可点击回退；前 3 步是硬门槛，见 AGENTS.md §8.1）。 */
  onJump?: (step: number) => void
  maxReachable: number
}

/** 向导步骤条（4 步：省份 → 选考科目 → 成绩 → 偏好）。 */
export function StepIndicator({ steps, current, onJump, maxReachable }: StepIndicatorProps) {
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="建档向导步骤">
      {steps.map((label, index) => {
        const step = index + 1
        const isCurrent = step === current
        const isDone = step < current
        const reachable = step <= maxReachable
        return (
          <li key={label} className="flex items-center gap-2">
            <button
              type="button"
              disabled={!reachable || !onJump}
              onClick={() => onJump?.(step)}
              aria-current={isCurrent ? 'step' : undefined}
              className={[
                'flex items-center gap-2 rounded-full px-3 py-1.5 text-sm transition',
                isCurrent
                  ? 'bg-sky-600 text-white'
                  : isDone
                    ? 'bg-sky-50 text-sky-700 ring-1 ring-sky-200'
                    : 'bg-slate-100 text-slate-500',
                reachable && onJump ? 'hover:brightness-95' : 'cursor-not-allowed',
              ].join(' ')}
            >
              <span
                className={[
                  'flex h-5 w-5 items-center justify-center rounded-full text-xs font-semibold',
                  isCurrent ? 'bg-white/20 text-white' : 'bg-white text-slate-600',
                ].join(' ')}
              >
                {isDone ? '✓' : step}
              </span>
              {label}
            </button>
            {step < steps.length && <span className="text-slate-300" aria-hidden="true">›</span>}
          </li>
        )
      })}
    </ol>
  )
}
