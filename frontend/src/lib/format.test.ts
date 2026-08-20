import { describe, expect, it } from 'vitest'

import { businessDaysFromToday, formatBusinessDate, formatDate } from './format'

describe('business date formatting', () => {
  it('preserves the literal calendar date independently of browser timezone', () => {
    expect(formatBusinessDate('2026-08-28')).toContain('28')
    expect(formatBusinessDate('2026-08-28')).not.toContain('29')
  })

  it('compares due dates using the agency calendar day', () => {
    const lateEveningUtc = new Date('2026-08-29T04:30:00Z')
    expect(
      businessDaysFromToday('2026-08-28', 'America/Chicago', lateEveningUtc),
    ).toBe(0)
  })

  it('continues to format real timestamps as instants', () => {
    const timestamp = '2026-08-20T10:00:00Z'
    const expected = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
    }).format(new Date(timestamp))
    expect(formatDate(timestamp)).toBe(expected)
  })
})
