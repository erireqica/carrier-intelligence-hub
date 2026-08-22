import { describe, expect, it } from 'vitest'

import { isInvalidSessionResponse, parseApiErrorMessage } from './api'

describe('API error handling', () => {
  it('turns structured validation errors into actionable field messages', () => {
    expect(
      parseApiErrorMessage({
        detail: [
          {
            type: 'string_too_short',
            loc: ['body', 'new_password'],
            msg: 'String should have at least 12 characters',
            ctx: { min_length: 12 },
          },
        ],
      }),
    ).toBe('New password must be at least 12 characters.')
    expect(
      parseApiErrorMessage({
        detail: [
          {
            type: 'value_error',
            loc: ['body'],
            msg: 'Value error, New password and confirmation do not match.',
          },
        ],
      }),
    ).toBe('New password and confirmation do not match.')
    expect(
      parseApiErrorMessage({
        detail: [
          {
            type: 'value_error',
            loc: ['body', 'email'],
            msg: 'Value error, Enter a valid internal email address',
          },
        ],
      }),
    ).toBe('Enter a valid internal email address.')
  })

  it('distinguishes credential verification from an invalid session', () => {
    expect(isInvalidSessionResponse('/auth/profile', 400)).toBe(false)
    expect(isInvalidSessionResponse('/auth/change-password', 400)).toBe(false)
    expect(isInvalidSessionResponse('/auth/profile', 401)).toBe(true)
    expect(isInvalidSessionResponse('/dashboard', 401)).toBe(true)
    expect(isInvalidSessionResponse('/dashboard', 403)).toBe(false)
  })
})
