/**
 * 建档向导状态（AGENTS.md §8.1）。
 *
 * 两条持久化要求同时满足：
 * 1. **localStorage**：中途刷新不丢进度（`persist` 中间件）；
 * 2. **后端草稿**：向导第 3 步起把可提交的字段 PATCH 到 `/students/{id}`（见 `submitDraft`）。
 */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { api, ApiError, type StudentPayload } from '../api/client'

/** 偏好与体检的结构直接取自契约，禁止前端另立字段（AGENTS.md §4.3 硬性规则 2）。 */
export type Preferences = NonNullable<StudentPayload['preferences']>
export type PhysicalExam = NonNullable<StudentPayload['physical_exam']>

export const DEFAULT_PREFERENCES: Preferences = {
  intended_regions: [],
  intended_levels: [],
  intended_major_categories: [],
  excluded_majors: [],
  // 默认：意向只影响排序（软偏好）；勾选"当作硬约束"后才直接过滤（ADR-022）
  intent_as_hard: false,
  // ★ ADR-022：学费维度已移除 → 现在是 **5 个维度**（各 1/5）
  weight_region: 1 / 5,
  weight_college_level: 1 / 5,
  weight_major: 1 / 5,
  weight_city: 1 / 5,
  weight_misc: 1 / 5,
}

export const DEFAULT_EXAM: PhysicalExam = {
  color_blindness: false,
  color_weakness: false,
  height_cm: null,
  other_restrictions: [],
}

export interface ProfileState {
  /** 后端草稿 id；第 1 步选定省份后立即建档 */
  studentId: string | null
  year: number | null
  province: string | null
  subjects: string[]
  totalScore: number | null
  rank: number | null
  rankSourceUrl: string | null
  gender: string | null
  foreignLanguage: string
  singleSubjectScores: Record<string, number>
  physicalExam: PhysicalExam
  preferences: Preferences
  /** 服务端返回的最新档案（含 missing_fields） */
  student: StudentPayload | null
  /** 最近一次提交/建档的错误（用于 UI 提示，例如 409 缺字段） */
  lastError: string | null

  setProvince: (province: string, year: number) => void
  toggleSubject: (subject: string, choose: number) => void
  setSubjects: (subjects: string[]) => void
  setScore: (score: number | null) => void
  setRank: (rank: number | null, sourceUrl?: string | null) => void
  setGender: (gender: string | null) => void
  setForeignLanguage: (language: string) => void
  setSingleSubjectScores: (scores: Record<string, number>) => void
  patchExam: (patch: Partial<PhysicalExam>) => void
  patchPreferences: (patch: Partial<Preferences>) => void
  setStudent: (student: StudentPayload | null) => void
  reset: () => void
}

const INITIAL = {
  studentId: null,
  year: null,
  province: null,
  subjects: [] as string[],
  totalScore: null,
  rank: null,
  rankSourceUrl: null,
  gender: null,
  foreignLanguage: '英语',
  singleSubjectScores: {} as Record<string, number>,
  physicalExam: DEFAULT_EXAM,
  preferences: DEFAULT_PREFERENCES,
  student: null,
  lastError: null,
}

export const useProfileStore = create<ProfileState>()(
  persist(
    (set) => ({
      ...INITIAL,

      setProvince: (province, year) =>
        set((state) => {
          if (state.province === province) return { year }
          // 换省份 → 选考科目池不同，已选科目必须清空（否则会带着别的省的科目进推荐）
          return { province, year, subjects: [], studentId: null, student: null }
        }),

      toggleSubject: (subject, choose) =>
        set((state) => {
          const selected = state.subjects.includes(subject)
          if (selected) return { subjects: state.subjects.filter((item) => item !== subject) }
          if (state.subjects.length >= choose) return {} // 选满后其余禁用（§8.1 Step 2）
          return { subjects: [...state.subjects, subject] }
        }),

      setSubjects: (subjects) => set({ subjects }),
      setScore: (totalScore) => set({ totalScore }),
      setRank: (rank, sourceUrl) =>
        set((state) => ({
          rank,
          rankSourceUrl: sourceUrl === undefined ? state.rankSourceUrl : sourceUrl,
        })),
      setGender: (gender) => set({ gender }),
      setForeignLanguage: (foreignLanguage) => set({ foreignLanguage }),
      setSingleSubjectScores: (singleSubjectScores) => set({ singleSubjectScores }),
      patchExam: (patch) => set((state) => ({ physicalExam: { ...state.physicalExam, ...patch } })),
      patchPreferences: (patch) =>
        set((state) => ({ preferences: { ...state.preferences, ...patch } })),
      setStudent: (student) =>
        set(
          student
            ? {
                student,
                studentId: student.id,
                subjects: student.subjects ?? [],
                totalScore: student.total_score ?? null,
                rank: student.rank ?? null,
                rankSourceUrl: student.rank_source_url ?? null,
                province: student.province,
                year: student.year,
              }
            : { student: null },
        ),
      reset: () => set({ ...INITIAL }),
    }),
    {
      name: 'exam-select.profile-draft',
      storage: createJSONStorage(() => localStorage),
      // student / lastError 是服务端派生状态，不进 localStorage（避免离线脏数据）
      partialize: (state) => ({
        studentId: state.studentId,
        year: state.year,
        province: state.province,
        subjects: state.subjects,
        totalScore: state.totalScore,
        rank: state.rank,
        rankSourceUrl: state.rankSourceUrl,
        gender: state.gender,
        foreignLanguage: state.foreignLanguage,
        singleSubjectScores: state.singleSubjectScores,
        physicalExam: state.physicalExam,
        preferences: state.preferences,
      }),
    },
  ),
)

/**
 * 把当前草稿同步到后端（建档或补全），返回服务端档案。
 *
 * 后端允许**草稿态**：缺字段不会报错，而是回传 `missing_fields`；
 * 只有进入计算路径（推荐/志愿表）才会 409——这正是"不替考生假设"的落地方式。
 *
 * ★ 失效草稿 id 的自愈（实测缺陷）：`studentId` 会随草稿持久化到 localStorage，
 * 但后端库可能被重建（`scripts/seed.py --reset`、换机器、清库）——那时这个 id 在后端
 * **不存在**，PATCH 会 404，向导第 3 步就直接报"后端有问题"（实测日志：
 * `PATCH /api/v1/students/stu-b9079021b8ef 404`）。
 * 因此 404 时**丢掉旧 id 并重新建档**，而不是把 404 抛给考生——
 * 对考生来说"我的草稿还在"才是正确语义，档案本来就是可以重建的。
 */
export async function submitDraft(): Promise<StudentPayload> {
  const state = useProfileStore.getState()
  if (!state.province) throw new ApiError(400, 'NO_PROVINCE', '请先选择省份。')
  const year = state.year ?? new Date().getFullYear()
  const payload = {
    province: state.province,
    year,
    track: '综合',
    subjects: state.subjects,
    total_score: state.totalScore,
    rank: state.rank,
    gender: state.gender,
    foreign_language: state.foreignLanguage,
    single_subject_scores: state.singleSubjectScores,
    physical_exam: state.physicalExam,
    preferences: state.preferences,
  }
  let envelope
  if (state.studentId) {
    try {
      envelope = await api.students.patch(state.studentId, payload)
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error
      // 草稿 id 已失效：清掉它，走建档路径重建（并把重建后的 id 写回 store）
      useProfileStore.setState({ studentId: null, student: null, lastError: null })
      envelope = await api.students.create(payload)
    }
  } else {
    envelope = await api.students.create(payload)
  }
  useProfileStore.getState().setStudent(envelope.data)
  return envelope.data
}

/** 档案是否齐全（`missing_fields` 为空才允许进入推荐，§8.1）。 */
export function isProfileComplete(student: StudentPayload | null): boolean {
  return Boolean(student) && (student?.missing_fields ?? []).length === 0
}

/** 直接读取当前草稿（非 hook 场景，如事件回调）。 */
export function readDraft() {
  return useProfileStore.getState()
}
