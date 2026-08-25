import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../../app/auth'
import { getAgents, getAuditLogs } from '../../lib/api'
import { authFixture } from '../../test/fixtures'
import { SystemLogsPage } from './SystemLogsPage'

vi.mock('../../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../../lib/api', () => ({ getAgents: vi.fn(), getAuditLogs: vi.fn() }))

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SystemLogsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SystemLogsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('MANAGER'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(getAgents).mockResolvedValue([
      {
        id: 2,
        full_name: 'Elena Torres',
        email: 'agent.one@demo.local',
        role: 'AGENT',
        is_active: true,
        last_login_at: null,
        open_tasks: 2,
        urgent_cases: 1,
        gmail_connections: 1,
      },
    ])
    vi.mocked(getAuditLogs).mockImplementation(async (query) => ({
      items: [
        {
          id: 1,
          event_type: 'CASE_REVIEWED',
          event_label: 'Case Reviewed',
          category: 'Reviews',
          severity: 'INFO',
          actor_name: 'Elena Torres',
          actor_user_id: 2,
          description: 'Review moved to resolved',
          case_id: 4,
          case_label: 'Taylor Demo · DEMO-4',
          task_id: null,
          task_title: null,
          review_id: 7,
          review_label: 'Review Low Confidence',
          metadata: {},
          created_at: '2026-08-20T10:30:00Z',
        },
      ],
      page: {
        page: Number(new URLSearchParams(query).get('page')),
        page_size: 25,
        total: 26,
        pages: 2,
      },
    }))
  })

  it('includes the current manager, agents, and System in the actor filter', async () => {
    renderPage()

    expect(await screen.findAllByText('Case Reviewed')).not.toHaveLength(0)
    await screen.findByLabelText('Log actor')
    expect(screen.getByRole('option', { name: 'System' })).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: 'Morgan Reed' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: 'Elena Torres' }),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() =>
      expect(getAuditLogs).toHaveBeenLastCalledWith(
        expect.stringContaining('page=2'),
      ),
    )
    await waitFor(() =>
      expect(screen.getByLabelText('Go to page')).toHaveValue(2),
    )
    fireEvent.change(screen.getByLabelText('Log actor'), {
      target: { value: '1' },
    })
    await waitFor(() => {
      expect(
        vi.mocked(getAuditLogs).mock.calls.some(([query]) => {
          const params = new URLSearchParams(query)
          return params.get('actor') === '1' && params.get('page') === '1'
        }),
      ).toBe(true)
    })

    fireEvent.change(await screen.findByLabelText('Log actor'), {
      target: { value: 'system' },
    })
    await waitFor(() => {
      expect(
        vi.mocked(getAuditLogs).mock.calls.some(([query]) => {
          const params = new URLSearchParams(query)
          return params.get('actor') === 'system'
        }),
      ).toBe(true)
    })
  })

  it('excludes Gmail sync completions by default and resets that filter', async () => {
    renderPage()

    const checkbox = await screen.findByRole('checkbox', {
      name: 'Exclude Gmail sync completions',
    })
    expect(checkbox).toBeChecked()
    await waitFor(() => {
      expect(
        vi.mocked(getAuditLogs).mock.calls.some(([query]) => {
          const params = new URLSearchParams(query)
          return params.get('exclude_gmail_sync_completed') === 'true'
        }),
      ).toBe(true)
    })

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() =>
      expect(getAuditLogs).toHaveBeenLastCalledWith(
        expect.stringContaining('page=2'),
      ),
    )
    await waitFor(() =>
      expect(screen.getByLabelText('Go to page')).toHaveValue(2),
    )
    fireEvent.click(
      screen.getByRole('checkbox', {
        name: 'Exclude Gmail sync completions',
      }),
    )
    await waitFor(() => {
      expect(
        vi.mocked(getAuditLogs).mock.calls.some(([query]) => {
          const params = new URLSearchParams(query)
          return (
            !params.has('exclude_gmail_sync_completed') &&
            params.get('page') === '1'
          )
        }),
      ).toBe(true)
    })

    fireEvent.click(
      await screen.findByRole('button', { name: 'Reset filters' }),
    )
    expect(
      screen.getByRole('checkbox', {
        name: 'Exclude Gmail sync completions',
      }),
    ).toBeChecked()
  })

  it('renders human audit context and related records', async () => {
    renderPage()

    expect(await screen.findAllByText('Case Reviewed')).not.toHaveLength(0)
    expect(screen.getAllByText('Elena Torres').length).toBeGreaterThan(0)
    expect(
      screen.getAllByRole('link', { name: 'Review Low Confidence' })[0],
    ).toHaveAttribute('href', '/reviews/7')
  })
})
