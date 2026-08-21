import { describe, expect, it } from 'vitest'

import { managerRoutes } from './router'

describe('Manager route modules', () => {
  it('keeps every split Manager page wired into the guarded route tree', () => {
    expect(managerRoutes.map((route) => route.path)).toEqual([
      'manager/analytics',
      'manager/activity',
      'manager/agents',
      'manager/carriers',
      'manager/system-logs',
      'manager/settings',
    ])
  })
})
