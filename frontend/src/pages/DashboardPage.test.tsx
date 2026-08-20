import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import { getDashboard } from '../lib/api'
import type { Dashboard } from '../lib/types'
import { authFixture } from '../test/fixtures'
import { DashboardPage } from './DashboardPage'

vi.mock('../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../lib/api', () => ({ getDashboard: vi.fn() }))

const dashboardBase: Omit<Dashboard, 'gmail_health'> = {
  metrics: {
    urgent_cases: 0,
    open_tasks: 0,
    overdue_tasks: 0,
    review_items: 0,
    processing_failures: 0,
    processed_messages: 0,
    gmail_connections_needing_attention: 0,
    received_backlog: 0,
    processing_messages: 0,
    retry_scheduled: 0,
    failed_requiring_attention: 0,
    gmail_labels_pending: 0,
    gmail_labels_requiring_attention: 0,
    oldest_unprocessed_age_seconds: null,
  },
  recent_cases: [],
  recent_activity: [],
  workload: [],
  gmail_connected: false,
}

function renderDashboard() {
  vi.mocked(useCurrentUser).mockReturnValue({
    data: authFixture('AGENT'),
  } as ReturnType<typeof useCurrentUser>)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DashboardPage Gmail health', () => {
  it('shows an attention state for unhealthy existing connections', async () => {
    vi.mocked(getDashboard).mockResolvedValue({
      ...dashboardBase,
      gmail_health: 'NEEDS_ATTENTION',
    })
    renderDashboard()
    expect(
      await screen.findByText('Gmail connection needs attention.'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No Gmail inbox connected.'),
    ).not.toBeInTheDocument()
  })

  it('keeps the no-connection state distinct', async () => {
    vi.mocked(getDashboard).mockResolvedValue({
      ...dashboardBase,
      gmail_health: 'NOT_CONNECTED',
    })
    renderDashboard()
    expect(
      await screen.findByText('No Gmail inbox connected.'),
    ).toBeInTheDocument()
  })
})
