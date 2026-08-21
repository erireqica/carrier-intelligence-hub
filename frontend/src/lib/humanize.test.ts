import { describe, expect, it } from 'vitest'

import { evidenceSourceLabel, humanFieldLabel } from './humanize'

describe('humanFieldLabel', () => {
  it.each([
    ['policy_status', 'Policy status'],
    ['action_item:0', 'Action item 1'],
    ['action_items[0]', 'Action item 1'],
    ['action_item:1', 'Action item 2'],
    ['requirement:0', 'Requirement 1'],
    ['premium_amount', 'Premium amount'],
  ])('formats %s as %s', (field, expected) => {
    expect(humanFieldLabel(field)).toBe(expected)
  })

  it('uses trustworthy source labels', () => {
    expect(evidenceSourceLabel('EMAIL')).toBe('Email body')
    expect(evidenceSourceLabel('PDF', 'requirements.pdf')).toBe(
      'requirements.pdf',
    )
  })
})
