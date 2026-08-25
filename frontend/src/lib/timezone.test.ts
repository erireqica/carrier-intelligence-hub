import { describe, expect, it } from 'vitest'

import { authFixture } from '../test/fixtures'
import {
  curatedTimezoneOptions,
  getEffectiveTimezone,
  getTimezoneOptions,
} from './timezone'

describe('timezone preferences', () => {
  it('falls back to the agency timezone when the user has no preference', () => {
    const auth = authFixture('AGENT')
    expect(getEffectiveTimezone(auth.user)).toBe('America/Chicago')

    auth.user.timezone = 'Europe/London'
    expect(getEffectiveTimezone(auth.user)).toBe('Europe/London')
  })

  it('offers only the curated timezone choices with IANA values', () => {
    expect(curatedTimezoneOptions).toHaveLength(27)
    expect(curatedTimezoneOptions).toContainEqual({
      label: 'UTC+01 — Pristina, Berlin, Paris, Rome',
      value: 'Europe/Belgrade',
    })
    expect(curatedTimezoneOptions).toContainEqual({
      label: 'UTC+05:30 — Delhi, Mumbai',
      value: 'Asia/Kolkata',
    })
    expect(curatedTimezoneOptions).toContainEqual({
      label: 'UTC±00 — Coordinated Universal Time',
      value: 'UTC',
    })
  })

  it('preserves a previously saved valid timezone outside the curated list', () => {
    expect(getTimezoneOptions('Europe/Vienna')[0]).toEqual({
      label: 'Current selection — Europe/Vienna',
      value: 'Europe/Vienna',
    })
    expect(getTimezoneOptions('Europe/Belgrade')).toBe(curatedTimezoneOptions)
  })
})
