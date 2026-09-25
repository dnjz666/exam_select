import { describe, expect, it } from 'vitest'

import { REGION_LABEL, regionLabel } from './labels'

describe('nationwide region labels', () => {
  it('covers all 31 province-level regions represented in the college catalog', () => {
    expect(Object.keys(REGION_LABEL)).toHaveLength(31)
  })

  it('shows Chinese names for regions outside the six supported exam provinces', () => {
    expect(regionLabel('jiangsu')).toBe('江苏')
    expect(regionLabel('hubei')).toBe('湖北')
  })
})
