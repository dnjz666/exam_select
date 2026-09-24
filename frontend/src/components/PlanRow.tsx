import type { CollegeBlock, PlanItem } from '../api/client'
import { formatPlanCount, formatRank, formatTuition, shortUnitId } from '../lib/format'
import { describeSubjectRequirement } from '../lib/format'
import { ProbabilityBar } from './ProbabilityBar'
import { SourceLink } from './StateBlocks'
import { TierBadge } from './TierBadge'

export interface PlanRowProps {
  item: PlanItem
  index: number
  total: number
  college?: CollegeBlock | null
  /** 该批次是否有专业调剂（专业+院校模式必须隐藏调剂选项，AGENTS.md §8.1）。 */
  hasAdjustment: boolean
  studentRank?: number | null
  tierBounds?: Record<string, [number, number]> | null
  dragging: boolean
  dropTarget: boolean
  onDragStart: () => void
  onDragEnter: () => void
  onDragEnd: () => void
  onDrop: () => void
  onMove: (from: number, to: number) => void
  onRemove: () => void
  onToggleObey: (value: boolean) => void
}

/**
 * 志愿表的一行（AGENTS.md §8.2 `/plan`：拖拽排序、分层配色、缺额提示）。
 *
 * 无障碍：HTML5 拖拽之外**必须**同时提供上下移动按钮（键盘与读屏可用），
 * 拖拽只是加速手段，不能是唯一操作路径。
 */
export function PlanRow({
  item,
  index,
  total,
  college,
  hasAdjustment,
  studentRank,
  tierBounds,
  dragging,
  dropTarget,
  onDragStart,
  onDragEnter,
  onDragEnd,
  onDrop,
  onMove,
  onRemove,
  onToggleObey,
}: PlanRowProps) {
  const unit = item.unit
  const planTooSmall = unit.plan_count < 5
  const name = college?.name ?? unit.college_id

  return (
    <li
      id={`unit-row-${unit.unit_id}`}
      draggable
      onDragStart={onDragStart}
      onDragEnter={onDragEnter}
      onDragOver={(event) => event.preventDefault()}
      onDragEnd={onDragEnd}
      onDrop={(event) => {
        event.preventDefault()
        onDrop()
      }}
      className={[
        'card card-pad transition',
        dragging ? 'opacity-40' : '',
        dropTarget ? 'ring-2 ring-sky-400' : '',
      ].join(' ')}
    >
      <div className="flex gap-3">
        <div className="flex w-10 shrink-0 flex-col items-center gap-1">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-sm font-semibold text-white"
            title="填报顺序（平行志愿检索严格按此顺序）"
          >
            {index + 1}
          </span>
          <span
            className="cursor-grab select-none text-slate-400"
            title="拖拽调整顺序"
            aria-hidden="true"
          >
            ⠿
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <TierBadge tier={item.tier} />
            <span className="font-semibold text-slate-900">{name}</span>
            {college?.level_tags?.map((tag) => (
              <span key={tag} className="chip-slate">
                {tag}
              </span>
            ))}
            {college && !college.is_public && (
              <span className="chip bg-amber-100 text-amber-800 ring-1 ring-amber-200" title="民办/独立学院，学费通常明显更高">
                非公办
              </span>
            )}
            <span className={unit.is_synthetic ? 'chip bg-amber-100 text-amber-800 ring-1 ring-amber-200' : 'chip bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200'}>
              {unit.is_synthetic ? '模拟数据' : '真实来源'}
            </span>
          </div>

          <p className="mt-1 text-sm text-slate-700">
            {unit.group_name ? `${unit.group_name} · ` : ''}
            {unit.major_name}
          </p>

          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            <span>
              选考要求：{describeSubjectRequirement(unit.subject_requirement)}
            </span>
            <span className={planTooSmall ? 'font-medium text-amber-700' : ''}>
              计划 {formatPlanCount(unit.plan_count)}
              {planTooSmall ? '（<5 人，波动大）' : ''}
            </span>
            {/* 名师铁律 10：学费必须让家长看见 */}
            <span>学费 {formatTuition(unit.tuition)}</span>
            <span>
              招生计划来源：
              <SourceLink
                url={unit.source_url}
                label={unit.source_url?.startsWith('http') ? '查看来源' : unit.source_url || '无来源链接'}
              />
            </span>
            <span>学制 {unit.duration} 年</span>
            {unit.campus && <span>校区 {unit.campus}</span>}
            {studentRank && <span>你的位次 {formatRank(studentRank)}</span>}
          </div>

          <div className="mt-2">
            <ProbabilityBar
              interval={item.probability_interval ?? null}
              tier={item.tier}
              bounds={tierBounds}
              compact
            />
          </div>

          {(item.notes ?? []).length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-amber-800">
              {(item.notes ?? []).map((note) => (
                <li key={note}>⚠ {note}</li>
              ))}
            </ul>
          )}

          {hasAdjustment && (
            <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-2">
              <p className="text-xs font-medium text-slate-700">
                是否服从专业组内调剂（不服从 = 主动接受退档风险）
              </p>
              <div className="mt-1.5 flex gap-4 text-sm">
                <label className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name={`obey-${unit.unit_id}`}
                    checked={item.obey_adjustment === true}
                    onChange={() => onToggleObey(true)}
                  />
                  <span>服从</span>
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name={`obey-${unit.unit_id}`}
                    checked={item.obey_adjustment === false}
                    onChange={() => onToggleObey(false)}
                  />
                  <span>不服从</span>
                </label>
                {item.obey_adjustment === null || item.obey_adjustment === undefined ? (
                  <span className="text-xs text-rose-700">尚未选择（批次规则要求显式选择）</span>
                ) : null}
              </div>
            </div>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-400">单位 {shortUnitId(unit.unit_id)}</span>
            <SourceLink url={college?.source_url ?? null} label="院校信息来源" />
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1">
          <button
            type="button"
            className="btn-ghost !px-2 !py-1 text-xs"
            disabled={index === 0}
            onClick={() => onMove(index, index - 1)}
            aria-label={`把第 ${index + 1} 个志愿上移`}
          >
            ↑ 上移
          </button>
          <button
            type="button"
            className="btn-ghost !px-2 !py-1 text-xs"
            disabled={index === total - 1}
            onClick={() => onMove(index, index + 1)}
            aria-label={`把第 ${index + 1} 个志愿下移`}
          >
            ↓ 下移
          </button>
          <button
            type="button"
            className="btn-ghost !px-2 !py-1 text-xs text-rose-600 hover:bg-rose-50"
            onClick={onRemove}
            aria-label={`移除第 ${index + 1} 个志愿`}
          >
            移除
          </button>
        </div>
      </div>
    </li>
  )
}
