import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { getCases } from '../lib/api'
import { CasesPage } from './CasesPage'

vi.mock('../lib/api', () => ({ getCases: vi.fn() }))
const mockedGetCases = vi.mocked(getCases)

describe('CasesPage lifecycle filtering', () => {
  it('defaults to Active and switches to mutually exclusive lifecycle categories', async () => {
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
    expect(
      await screen.findByText('No active carrier cases yet'),
    ).toBeInTheDocument()
    expect(mockedGetCases).toHaveBeenCalledWith(
      expect.stringContaining('lifecycle=ACTIVE'),
    )
    expect(screen.getByRole('tab', { name: /Active/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    fireEvent.click(screen.getByRole('tab', { name: /Completed/ }))
    await waitFor(() =>
      expect(mockedGetCases).toHaveBeenLastCalledWith(
        expect.stringContaining('lifecycle=COMPLETED'),
      ),
    )
    expect(
      await screen.findByText('No completed cases yet'),
    ).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Completed/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    fireEvent.click(screen.getByRole('tab', { name: /Dismissed/ }))
    await waitFor(() =>
      expect(mockedGetCases).toHaveBeenLastCalledWith(
        expect.stringContaining('lifecycle=DISMISSED'),
      ),
    )
    expect(await screen.findByText('No dismissed cases')).toBeInTheDocument()
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

  it('resets page one when switching lifecycle and renders completed history distinctly', async () => {
    mockedGetCases.mockResolvedValue({
      items: [
        {
          id: 9,
          client_name: 'Completed Client',
          policy_number: 'COM-9',
          policy_status: 'ACTIVE',
          priority: 'NORMAL',
          summary: 'Historical case.',
          deadline: null,
          updated_at: '2026-08-20T10:00:00Z',
          carrier: { id: 1, name: 'Americo', code: 'AMR' },
          assigned_agent: null,
          needs_review: false,
          dismissed_at: null,
          completed_at: '2026-08-21T10:00:00Z',
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
        <MemoryRouter initialEntries={['/cases?lifecycle=COMPLETED&page=3']}>
          <CasesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const badge = await screen.findByText('COMPLETED')
    expect(badge).toHaveClass('text-emerald-800')
    expect(
      screen
        .getAllByText('ACTIVE')
        .some((element) => element.tagName === 'SPAN'),
    ).toBe(true)
    expect(mockedGetCases).toHaveBeenCalledWith(
      expect.stringContaining('page=3'),
    )
    fireEvent.click(screen.getByRole('tab', { name: /Active/ }))
    await waitFor(() => {
      const request = mockedGetCases.mock.calls.at(-1)?.[0] ?? ''
      expect(request).toContain('lifecycle=ACTIVE')
      expect(request).toContain('page=1')
    })
  })
})
