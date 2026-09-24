import { describe, expect, it } from 'vitest'

import type { StudentPayload } from '../api/client'
import { isProfileComplete } from './profile'

function student(overrides: Partial<StudentPayload>): StudentPayload {
  return {
    id: 'stu-test',
    province: 'zhejiang',
    year: 2026,
    track: '综合',
    subjects: ['物理', '化学', '地理'],
    total_score: 650,
    rank: 12000,
    gender: null,
    is_fresh_graduate: true,
    political_status: '群众',
    foreign_language: '英语',
    single_subject_scores: {},
    physical_exam: { color_blindness: false, color_weakness: false, height_cm: null, other_restrictions: [] },
    bonus_points: 0,
    bonus_type: null,
    preferences: {
      intended_regions: [], intended_levels: [], intended_major_categories: [], excluded_majors: [],
      intent_as_hard: false, weight_region: 0.2, weight_college_level: 0.2, weight_major: 0.2,
      weight_city: 0.2, weight_misc: 0.2,
    },
    missing_fields: [],
    rank_source_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  }
}

describe('isProfileComplete', () => {
  it('treats a zero score as incomplete even if a stale payload has no missing fields', () => {
    expect(isProfileComplete(student({ total_score: 0, missing_fields: [] }))).toBe(false)
  })

  it('allows a valid, completed score and profile', () => {
    expect(isProfileComplete(student({ total_score: 650, missing_fields: [] }))).toBe(true)
  })
})
