import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../../app/auth'
import { getAgents, getAuditLogs } from '../../lib/api'
import { authFixture } from '../../test/fixtures'
import { SystemLogsPage } from './SystemLogsPage'

vi.mock('../../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../../lib/api', () => ({ getAgents: vi.fn(), getAuditLogs: vi.fn() }))

describe('SystemLogsPage', () => {
  it('renders human audit context and resets pagination when filters change', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('MANAGER'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(getAgents).mockResolvedValue([])
    vi.mocked(getAuditLogs).mockResolvedValue({
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
      page: { page: 1, page_size: 25, total: 26, pages: 2 },
    })
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
    expect(await screen.findAllByText('Case Reviewed')).not.toHaveLength(0)
    expect(screen.getAllByText('Elena Torres').length).toBeGreaterThan(0)
    expect(
      screen.getAllByRole('link', { name: 'Review Low Confidence' })[0],
    ).toHaveAttribute('href', '/reviews/7')
    expect(screen.getByLabelText('Go to page')).toHaveValue(1)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() =>
      expect(getAuditLogs).toHaveBeenLastCalledWith(
        expect.stringContaining('page=2'),
      ),
    )
    fireEvent.change(await screen.findByLabelText('Log category'), {
      target: { value: 'TASKS' },
    })
    await waitFor(() =>
      expect(getAuditLogs).toHaveBeenLastCalledWith(
        expect.stringContaining('page=1'),
      ),
    )
  })
})
