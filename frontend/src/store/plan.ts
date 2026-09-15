/**
 * 志愿表状态：当前 plan_id + 最近一次后端返回的完整载荷 + 生成时的筛选条件。
 *
 * 纪律：**所有**改动的合法性由后端判定。`PATCH /plans/{id}/items` 会在
 * 「生成时的候选池」（同一套 `evaluate_candidates` 现场重算）内校验 `unit_id`，
 * 池外直接 422。前端因此必须记住生成时用的 `filters` 并在手改时一并回传，
 * 否则候选池口径会与推荐列表不一致。
 */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import type { Envelope, FilterCriteriaInput, PlanPayload } from '../api/client'

export interface PlanState {
  planId: string | null
  /**
   * 后端返回的**完整信封**（`data` + `evidence` + `warnings`）。
   * 报告页需要 `evidence`（逐项来源）与 `warnings`，只存 `data` 会丢掉证据链。
   */
  bundle: Envelope<PlanPayload> | null
  /** 拖拽过程中的本地顺序（乐观展示），提交后由服务端载荷覆盖 */
  draftOrder: string[] | null
  /** 生成该志愿表时使用的筛选条件 */
  filters: FilterCriteriaInput | null
  /** 意愿序：推荐页「加入志愿表」累积的 unit_id 顺序（生成时作为 preference_order） */
  preferenceOrder: string[]
  /** 服从调剂的统一选择（院校专业组批次用） */
  obeyAdjustment: boolean | null

  setPlanId: (planId: string | null) => void
  setBundle: (bundle: Envelope<PlanPayload> | null) => void
  setDraftOrder: (order: string[] | null) => void
  setFilters: (filters: FilterCriteriaInput | null) => void
  togglePreference: (unitId: string) => void
  setPreferenceOrder: (order: string[]) => void
  setObeyAdjustment: (value: boolean | null) => void
  clear: () => void
}

export const usePlanStore = create<PlanState>()(
  persist(
    (set) => ({
      planId: null,
      bundle: null,
      draftOrder: null,
      filters: null,
      preferenceOrder: [],
      obeyAdjustment: null,

      setPlanId: (planId) => set({ planId }),
      setBundle: (bundle) => set({ bundle, draftOrder: null }),
      setDraftOrder: (draftOrder) => set({ draftOrder }),
      setFilters: (filters) => set({ filters }),
      togglePreference: (unitId) =>
        set((state) => ({
          preferenceOrder: state.preferenceOrder.includes(unitId)
            ? state.preferenceOrder.filter((item) => item !== unitId)
            : [...state.preferenceOrder, unitId],
        })),
      setPreferenceOrder: (preferenceOrder) => set({ preferenceOrder }),
      setObeyAdjustment: (obeyAdjustment) => set({ obeyAdjustment }),
      clear: () =>
        set({
          planId: null,
          bundle: null,
          draftOrder: null,
          filters: null,
          preferenceOrder: [],
          obeyAdjustment: null,
        }),
    }),
    {
      name: 'exam-select.plan',
      storage: createJSONStorage(() => localStorage),
      // bundle 体积大且随时可能过期，只持久化 id / 筛选条件 / 意愿序，页面加载时重新 GET
      partialize: (state) => ({
        planId: state.planId,
        filters: state.filters,
        preferenceOrder: state.preferenceOrder,
        obeyAdjustment: state.obeyAdjustment,
      }),
    },
  ),
)
