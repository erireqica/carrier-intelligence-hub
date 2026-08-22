import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { getCases } from '../lib/api'
import { CasesPage } from './CasesPage'

vi.mock('../lib/api', () => ({ getCases: vi.fn() }))
const mockedGetCases = vi.mocked(getCases)

describe('CasesPage empty states', () => {
  it('distinguishes an empty scope from filters with no matches', async () => {
    mockedGetCases.mockResolvedValue({
      items: [],
      page: { page: 1, page_size: 20, total: 0, pages: 1 },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CasesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('No carrier cases yet')).toBeInTheDocument()
    expect(mockedGetCases).toHaveBeenCalledWith(
      expect.stringContaining('page_size=10'),
    )
    fireEvent.click(screen.getByLabelText('Include dismissed cases'))
    await waitFor(() =>
      expect(mockedGetCases).toHaveBeenLastCalledWith(
        expect.stringContaining('include_dismissed=true'),
      ),
    )
    fireEvent.change(await screen.findByLabelText('Search cases'), {
      target: { value: 'missing policy' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(
      await screen.findByText('No cases match your filters'),
    ).toBeInTheDocument()
    expect(mockedGetCases).toHaveBeenLastCalledWith(
      expect.stringContaining('search=missing+policy'),
    )
  })

  it('renders a strong lifecycle badge for an included dismissed case', async () => {
    mockedGetCases.mockResolvedValue({
      items: [
        {
          id: 9,
          client_name: 'Dismissed Client',
          policy_number: 'DIS-9',
          policy_status: 'ACTIVE',
          priority: 'NORMAL',
          summary: 'Historical case.',
          deadline: null,
          updated_at: '2026-08-20T10:00:00Z',
          carrier: { id: 1, name: 'Americo', code: 'AMR' },
          assigned_agent: null,
          needs_review: false,
          dismissed_at: '2026-08-21T10:00:00Z',
          can_manage_lifecycle: true,
        },
      ],
      page: { page: 1, page_size: 10, total: 1, pages: 1 },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CasesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const badge = await screen.findByText('DISMISSED')
    expect(badge).toHaveClass('text-red-800')
    expect(
      screen
        .getAllByText('ACTIVE')
        .some((element) => element.tagName === 'SPAN'),
    ).toBe(true)
  })
})
