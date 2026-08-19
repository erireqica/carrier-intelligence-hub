import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
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
    fireEvent.change(screen.getByLabelText('Search cases'), {
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
})
