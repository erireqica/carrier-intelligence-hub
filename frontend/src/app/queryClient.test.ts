import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { clearSessionState } from './queryClient'

describe('session cache isolation', () => {
  it('removes all cached user data before another account can render', async () => {
    const client = new QueryClient()
    client.setQueryData(['auth', 'me'], {
      user: { email: 'agent.a@demo.local' },
    })
    client.setQueryData(['cases'], [{ client_name: 'Agent A Client' }])
    client.setQueryData(['dashboard'], { private_agent_metric: 7 })
    client
      .getMutationCache()
      .build(client, { mutationFn: async () => undefined })
    await clearSessionState(client)
    expect(client.getQueryCache().getAll()).toHaveLength(0)
    expect(client.getMutationCache().getAll()).toHaveLength(0)
  })
})
