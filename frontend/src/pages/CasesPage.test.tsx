import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { getAgents, getCases, getMe } from '../lib/api'
import { authFixture } from '../test/fixtures'
import { CasesPage } from './CasesPage'

vi.mock('../lib/api', () => ({
  getAgents: vi.fn(),
  getCases: vi.fn(),
  getMe: vi.fn(),
}))
const mockedGetCases = vi.mocked(getCases)

describe('CasesPage lifecycle filtering', () => {
  it('defaults to Active and switches to mutually exclusive lifecycle categories', async () => {
    vi.mocked(getMe).mockResolvedValue(authFixture('AGENT'))
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
    expect(screen.getByLabelText('Search cases').closest('form')).toHaveClass(
      'lg:grid-cols-2',
      'xl:grid-cols-[minmax(220px,1fr)_minmax(150px,180px)_minmax(140px,160px)_minmax(160px,180px)_auto]',
    )
    expect(screen.queryByLabelText('Assigned agent')).not.toBeInTheDocument()
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

  it('filters Manager Cases by assigned Agent across lifecycle, reset, and pagination', async () => {
    vi.mocked(getMe).mockResolvedValue(authFixture('MANAGER'))
    vi.mocked(getAgents).mockResolvedValue([
      {
        id: 2,
        full_name: 'Elena Torres',
        email: 'agent.one@demo.local',
        role: 'AGENT',
        is_active: true,
        last_login_at: null,
        open_tasks: 2,
        urgent_cases: 0,
        gmail_connections: 1,
      },
      {
        id: 3,
        full_name: 'Marcus Lee',
        email: 'agent.two@demo.local',
        role: 'AGENT',
        is_active: true,
        last_login_at: null,
        open_tasks: 1,
        urgent_cases: 0,
        gmail_connections: 1,
      },
      {
        id: 1,
        full_name: 'Morgan Reed',
        email: 'manager@demo.local',
        role: 'MANAGER',
        is_active: true,
        last_login_at: null,
        open_tasks: 0,
        urgent_cases: 0,
        gmail_connections: 0,
      },
    ])
    mockedGetCases.mockResolvedValue({
      items: [],
      page: { page: 1, page_size: 10, total: 21, pages: 3 },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/cases?page=3']}>
          <CasesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const agentFilter = await screen.findByLabelText('Assigned agent')
    expect(
      screen.getByRole('option', { name: 'All agents' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('option', { name: 'Elena Torres' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: 'Marcus Lee' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('option', { name: 'Morgan Reed' }),
    ).not.toBeInTheDocument()

    fireEvent.change(agentFilter, { target: { value: '3' } })
    await waitFor(() => {
      const request = mockedGetCases.mock.calls.at(-1)?.[0] ?? ''
      expect(request).toContain('assigned_agent_id=3')
      expect(request).toContain('page=1')
    })
    fireEvent.change(await screen.findByLabelText('Policy status'), {
      target: { value: 'PENDING' },
    })
    fireEvent.change(await screen.findByLabelText('Priority'), {
      target: { value: 'HIGH' },
    })
    fireEvent.change(await screen.findByLabelText('Search cases'), {
      target: { value: 'policy 771' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    fireEvent.click(await screen.findByRole('tab', { name: /Completed/ }))
    await waitFor(() => {
      const request = mockedGetCases.mock.calls.at(-1)?.[0] ?? ''
      expect(request).toContain('assigned_agent_id=3')
      expect(request).toContain('policy_status=PENDING')
      expect(request).toContain('priority=HIGH')
      expect(request).toContain('search=policy+771')
      expect(request).toContain('lifecycle=COMPLETED')
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }))
    await waitFor(() => {
      const request = mockedGetCases.mock.calls.at(-1)?.[0] ?? ''
      expect(request).toContain('assigned_agent_id=3')
      expect(request).toContain('page=2')
    })
    fireEvent.click(await screen.findByRole('tab', { name: /Dismissed/ }))
    await waitFor(() => {
      const request = mockedGetCases.mock.calls.at(-1)?.[0] ?? ''
      expect(request).toContain('assigned_agent_id=3')
      expect(request).toContain('lifecycle=DISMISSED')
      expect(request).toContain('page=1')
    })

    fireEvent.click(await screen.findByRole('button', { name: 'Reset' }))
    await waitFor(() => {
      const request = mockedGetCases.mock.calls.at(-1)?.[0] ?? ''
      expect(request).not.toContain('assigned_agent_id')
      expect(request).not.toContain('policy_status')
      expect(request).not.toContain('priority')
      expect(request).not.toContain('search=')
    })
    expect(await screen.findByLabelText('Assigned agent')).toHaveValue('')
  })

  it('resets page one when switching lifecycle and renders completed history distinctly', async () => {
    vi.mocked(getMe).mockResolvedValue(authFixture('AGENT'))
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
