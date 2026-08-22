import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
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
    in_progress_tasks: 0,
    due_soon_tasks: 0,
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

function renderDashboard(role: 'AGENT' | 'MANAGER' = 'AGENT') {
  vi.mocked(useCurrentUser).mockReturnValue({
    data: authFixture(role),
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
  it('uses an agent-focused workload summary instead of agency live operations', async () => {
    vi.mocked(getDashboard).mockResolvedValue({
      ...dashboardBase,
      gmail_health: 'CONNECTED',
    })
    renderDashboard('AGENT')

    expect(await screen.findByText("Today's workload")).toBeInTheDocument()
    expect(screen.getByText('Active tasks')).toBeInTheDocument()
    expect(screen.getByText('In progress')).toBeInTheDocument()
    expect(screen.getByText('Due soon')).toBeInTheDocument()
    expect(screen.queryByText('Live agency operations')).not.toBeInTheDocument()
  })

  it('reserves live agency operations and pipeline health for managers', async () => {
    vi.mocked(getDashboard).mockResolvedValue({
      ...dashboardBase,
      gmail_health: 'CONNECTED',
    })
    renderDashboard('MANAGER')

    expect(
      await screen.findByText('Live agency operations'),
    ).toBeInTheDocument()
    expect(screen.getByText('Pipeline health')).toBeInTheDocument()
    expect(
      screen.getByText('All processing and label queues are currently clear.'),
    ).toBeInTheDocument()
  })

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
    expect(
      screen.getByText(/Existing cases, tasks, and history remain/),
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/deterministic development data/i),
    ).not.toBeInTheDocument()
  })

  it('routes recent activity to the role-appropriate full history', async () => {
    vi.mocked(getDashboard).mockResolvedValue({
      ...dashboardBase,
      gmail_health: 'CONNECTED',
    })
    renderDashboard('AGENT')
    expect(
      (await screen.findAllByRole('link', { name: 'View all' })).some(
        (link) => link.getAttribute('href') === '/activity',
      ),
    ).toBe(true)
  })

  it('routes manager recent activity to agency system logs', async () => {
    vi.mocked(getDashboard).mockResolvedValue({
      ...dashboardBase,
      gmail_health: 'CONNECTED',
    })
    renderDashboard('MANAGER')
    await waitFor(() =>
      expect(
        screen
          .getAllByRole('link', { name: 'View all' })
          .some((link) => link.getAttribute('href') === '/manager/system-logs'),
      ).toBe(true),
    )
  })

  it('places Agent workload directly after Pipeline health for managers', async () => {
    vi.mocked(getDashboard).mockResolvedValue({
      ...dashboardBase,
      gmail_health: 'CONNECTED',
      workload: [
        {
          agent: { id: 2, full_name: 'Elena Agent', email: 'elena@demo.local' },
          open_tasks: 2,
        },
      ],
    })
    renderDashboard('MANAGER')
    const pipeline = await screen.findByRole('heading', {
      name: 'Pipeline health',
    })
    const workload = screen.getByRole('heading', { name: 'Agent workload' })
    const recent = screen.getByRole('heading', { name: 'Recent cases' })
    expect(
      pipeline.compareDocumentPosition(workload) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(
      workload.compareDocumentPosition(recent) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })
})
