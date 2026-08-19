import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { getAnalytics } from '../../lib/api'
import { AnalyticsPage } from './AnalyticsPage'

vi.mock('../../lib/api', () => ({ getAnalytics: vi.fn() }))

describe('AnalyticsPage workload identity', () => {
  it('renders employees with the same name as separate user records', async () => {
    vi.mocked(getAnalytics).mockResolvedValue({
      cases_by_status: {},
      cases_by_carrier: {},
      workload_by_agent: [
        {
          agent: {
            id: 2,
            full_name: 'Shared Name',
            email: 'first@example.test',
          },
          open_tasks: 2,
        },
        {
          agent: {
            id: 3,
            full_name: 'Shared Name',
            email: 'second@example.test',
          },
          open_tasks: 1,
        },
      ],
      urgent_high_cases: 0,
      open_tasks: 3,
      overdue_tasks: 0,
      open_reviews: 0,
      processed_messages: 0,
      failed_messages: 0,
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <AnalyticsPage />
      </QueryClientProvider>,
    )

    expect(await screen.findAllByText('Shared Name')).toHaveLength(2)
    expect(screen.getByText('first@example.test')).toBeInTheDocument()
    expect(screen.getByText('second@example.test')).toBeInTheDocument()
  })
})
