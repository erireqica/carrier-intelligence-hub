import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../../app/auth'
import { getAgents } from '../../lib/api'
import { authFixture } from '../../test/fixtures'
import { AgentsPage } from './AgentsPage'

vi.mock('../../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../../lib/api', () => ({ getAgents: vi.fn() }))

describe('AgentsPage', () => {
  it('labels active connection counts as connected inboxes', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('MANAGER'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(getAgents).mockResolvedValue([
      {
        ...authFixture('AGENT').user,
        open_tasks: 2,
        urgent_cases: 1,
        gmail_connections: 1,
      },
    ])
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <AgentsPage />
      </QueryClientProvider>,
    )
    expect(
      (await screen.findAllByText('Connected inboxes')).length,
    ).toBeGreaterThan(0)
    expect(screen.getAllByText('1 connected').length).toBeGreaterThan(0)
  })
})
