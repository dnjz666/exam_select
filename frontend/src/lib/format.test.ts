import { describe, expect, it } from 'vitest'

import {
  describeSubjectRequirement,
  countByLevel,
  formatCoverage,
  formatInterval,
  formatRank,
  formatScore,
  formatTuition,
  shortUnitId,
} from './format'

/**
 * 前端只测**纯函数**：概率区间格式化是"MUST 显示区间"这条 UI 铁律的最后一道闸门，
 * 它一旦把区间压成一个数字，界面就会给出伪精确的错觉。
 */
describe('formatInterval', () => {
  it('把 ±1σ 区间格式化成区间而不是单点', () => {
    expect(formatInterval([0.62, 0.78])).toBe('62%–78%')
  })

  it('容忍倒序输入（算法侧顺序不该成为前端崩溃的理由）', () => {
    expect(formatInterval([0.78, 0.62])).toBe('62%–78%')
  })

  it('窄区间自动增加小数位，绝不把不确定度伪装成更宽的区间', () => {
    // 四舍五入到整数就不再相等 → 用整数位即可（94%–95% 本来就是不同的一档）
    expect(formatInterval([0.942, 0.946])).toBe('94%–95%')
    // 整数位与一位小数都会被抹平 → 必须继续增加到两位，而不是输出 "94%–94%"
    expect(formatInterval([0.9421, 0.9424])).toBe('94.21%–94.24%')
  })

  it('缺失或非法值显示占位符，而不是 0%', () => {
    expect(formatInterval(null)).toBe('—')
    expect(formatInterval(undefined)).toBe('—')
    expect(formatInterval([0.5])).toBe('—')
    expect(formatInterval([Number.NaN, 0.5])).toBe('—')
  })
})

describe('数值格式化', () => {
  it('位次带千分位', () => {
    expect(formatRank(12340)).toBe('12,340')
    expect(formatRank(null)).toBe('—')
  })

  it('分数保留整数或一位小数', () => {
    expect(formatScore(640)).toBe('640')
    expect(formatScore(639.54)).toBe('639.5')
  })

  it('学费与覆盖率带单位', () => {
    expect(formatTuition(6000)).toBe('6,000 元/年')
    expect(formatCoverage(0.7891)).toBe('78.9%')
    expect(formatCoverage(null)).toBe('—')
  })
})

describe('选考要求描述', () => {
  it('三种模式都有人话描述', () => {
    expect(describeSubjectRequirement({ mode: 'none', subjects: [] })).toBe('不限')
    expect(describeSubjectRequirement({ mode: 'all_of', subjects: ['物理', '化学'] })).toBe('均须选考：物理、化学')
    expect(describeSubjectRequirement({ mode: 'any_of', subjects: ['物理', '历史'] })).toBe('选考其一：物理、历史')
  })
})

describe('零散工具', () => {
  it('单位 id 缩短后可读但仍唯一到专业粒度', () => {
    expect(shortUnitId('zhejiang-2026-1001-NA-080901')).toBe('1001-NA-080901')
    expect(shortUnitId(null)).toBe('—')
  })

  it('按等级计数', () => {
    expect(countByLevel([{ level: 'HIGH' }, { level: 'HIGH' }, { level: 'LOW' }])).toEqual({
      HIGH: 2,
      LOW: 1,
    })
  })
})
