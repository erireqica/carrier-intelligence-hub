import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import { getActivity } from '../lib/api'
import { authFixture } from '../test/fixtures'
import { ActivityPage } from './ActivityPage'

vi.mock('../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../lib/api', () => ({ getActivity: vi.fn() }))

describe('ActivityPage', () => {
  it('shows only self-scoped human-readable activity without actor controls', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('AGENT'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(getActivity).mockResolvedValue({
      items: [
        {
          id: 1,
          event_type: 'CASE_CORRECTED',
          event_label: 'Case Corrected',
          category: 'Cases',
          severity: 'INFO',
          actor_name: 'Elena Torres',
          actor_user_id: 2,
          description: 'Case information corrected by the assigned agent',
          case_id: 4,
          case_label: 'Taylor Demo · DEMO-4',
          task_id: null,
          task_title: null,
          review_id: null,
          review_label: null,
          metadata: {},
          created_at: '2026-08-20T10:00:00Z',
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
          <ActivityPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Case Corrected')).toBeInTheDocument()
    expect(screen.getByText('Case: Taylor Demo · DEMO-4')).toBeInTheDocument()
    expect(screen.getByText('Action')).toBeInTheDocument()
    expect(screen.getByText('Details')).toBeInTheDocument()
    expect(screen.getByText('Date')).toBeInTheDocument()
    expect(
      screen.getByText('Case information corrected by the assigned agent'),
    ).toHaveClass('text-[0.95rem]')
    expect(screen.queryByLabelText('Activity agent')).not.toBeInTheDocument()
    const caseLink = screen.getByRole('link', { name: 'View case' })
    expect(caseLink).toHaveAttribute('href', '/cases/4')
    expect(caseLink).toHaveClass('text-sm')
    expect(screen.getByLabelText('Go to page')).toHaveValue(1)
  })
})
