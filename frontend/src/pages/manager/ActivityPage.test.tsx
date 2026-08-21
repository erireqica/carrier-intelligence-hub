import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { getActivity, getAgents } from '../../lib/api'
import { ActivityPage } from './ActivityPage'

vi.mock('../../lib/api', () => ({ getActivity: vi.fn(), getAgents: vi.fn() }))

describe('ActivityPage', () => {
  it('shows human-readable agent and case context', async () => {
    vi.mocked(getAgents).mockResolvedValue([])
    vi.mocked(getActivity).mockResolvedValue({
      items: [
        {
          id: 1,
          event_type: 'CASE_CORRECTED',
          severity: 'INFO',
          actor_name: 'Elena Torres',
          actor_user_id: 2,
          description: 'Case information corrected by the assigned agent',
          case_id: 4,
          case_label: 'Taylor Demo · DEMO-4',
          task_id: null,
          task_title: null,
          metadata: {},
          created_at: '2026-08-20T10:00:00Z',
        },
      ],
      page: { page: 1, page_size: 100, total: 1, pages: 1 },
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
    expect(await screen.findByText('Elena Torres')).toBeInTheDocument()
    expect(screen.getByText('Case: Taylor Demo · DEMO-4')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View case' })).toHaveAttribute(
      'href',
      '/cases/4',
    )
  })
})
