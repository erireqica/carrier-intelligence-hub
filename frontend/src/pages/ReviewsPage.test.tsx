import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { getMe, getReviews } from '../lib/api'
import { authFixture } from '../test/fixtures'
import { ReviewsPage } from './ReviewsPage'

vi.mock('../lib/api', () => ({ getMe: vi.fn(), getReviews: vi.fn() }))

describe('ReviewsPage history views', () => {
  it('defaults to actionable and lets users reopen a terminal review read-only', async () => {
    vi.mocked(getMe).mockResolvedValue(authFixture('AGENT'))
    vi.mocked(getReviews).mockImplementation(async (params) => ({
      items: (params ?? '').includes('view=RESOLVED')
        ? [
            {
              id: 7,
              message_id: 9,
              case_id: 4,
              client_name: 'Historical Client',
              policy_number: 'HIST-4',
              carrier_name: 'Americo',
              message_subject: 'Historical review',
              reason_code: 'LOW_CONFIDENCE',
              reason: 'Human confirmation was required.',
              status: 'RESOLVED',
              resolution_notes: 'Confirmed.',
              assigned_reviewer: null,
              created_at: '2026-08-20T10:00:00Z',
              resolved_at: '2026-08-20T11:00:00Z',
              analysis_confidence: 0.7,
            },
          ]
        : [],
      page: { page: 1, page_size: 25, total: 1, pages: 1 },
    }))
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ReviewsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(getReviews).toHaveBeenCalledWith(
        expect.stringContaining('view=ACTIONABLE'),
      ),
    )
    expect(
      await screen.findByText(
        "Messages that require an agent's judgment before Carrier Hub can continue.",
      ),
    ).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Resolved' }))
    expect(
      await screen.findByText('Historical Client · Americo'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View review' })).toHaveAttribute(
      'href',
      '/reviews/7',
    )
  })
})
