import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../../app/auth'
import { getAgentsPage, removeAgent, setAgentEnabled } from '../../lib/api'
import { authFixture } from '../../test/fixtures'
import { AgentsPage } from './AgentsPage'

vi.mock('../../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../../lib/api', () => ({
  createAgent: vi.fn(),
  getAgentsPage: vi.fn(),
  removeAgent: vi.fn(),
  setAgentEnabled: vi.fn(),
}))

describe('AgentsPage', () => {
  it('labels active connection counts as connected inboxes', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('MANAGER'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(getAgentsPage).mockResolvedValue({
      items: [
        {
          ...authFixture('AGENT').user,
          open_tasks: 2,
          urgent_cases: 1,
          gmail_connections: 1,
        },
      ],
      page: { page: 1, page_size: 10, total: 1, pages: 1 },
    })
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <AgentsPage />
      </QueryClientProvider>,
    )
    expect(
      (await screen.findAllByText('Connected inboxes')).length,
    ).toBeGreaterThan(0)
    expect(screen.getAllByText('1 connected').length).toBeGreaterThan(0)
  })

  it('uses distinct lifecycle treatments without changing action behavior', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('MANAGER'),
    } as ReturnType<typeof useCurrentUser>)
    const activeAgent = {
      ...authFixture('AGENT').user,
      id: 10,
      full_name: 'Active Agent',
      is_active: true,
      open_tasks: 0,
      urgent_cases: 0,
      gmail_connections: 0,
    }
    const inactiveAgent = {
      ...activeAgent,
      id: 11,
      full_name: 'Inactive Agent',
      email: 'inactive@example.test',
      is_active: false,
    }
    vi.mocked(getAgentsPage).mockResolvedValue({
      items: [activeAgent, inactiveAgent],
      page: { page: 1, page_size: 10, total: 2, pages: 1 },
    })
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
    render(
      <QueryClientProvider client={client}>
        <AgentsPage />
      </QueryClientProvider>,
    )

    const disable = await screen.findByRole('button', { name: 'Disable' })
    const enable = screen.getByRole('button', { name: 'Enable' })
    const removeButtons = screen.getAllByRole('button', { name: 'Remove' })
    expect(disable).toHaveClass('bg-red-700', 'text-white')
    expect(enable).toHaveClass('bg-emerald-700', 'text-white')
    expect(removeButtons[0]).toHaveClass(
      'bg-white',
      'border-red-700',
      'text-red-700',
    )
    expect(removeButtons[0]).not.toHaveClass('bg-red-700')

    fireEvent.click(disable)
    await vi.waitFor(() =>
      expect(setAgentEnabled).toHaveBeenCalledWith(10, false),
    )
    fireEvent.click(enable)
    await vi.waitFor(() =>
      expect(setAgentEnabled).toHaveBeenCalledWith(11, true),
    )
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(removeButtons[0])
    expect(confirm).toHaveBeenCalled()
    await vi.waitFor(() => expect(removeAgent).toHaveBeenCalled())
    expect(vi.mocked(removeAgent).mock.calls[0][0]).toBe(10)
  })

  it('opens uploaded profile photos in an accessible dismissible preview', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('MANAGER'),
    } as ReturnType<typeof useCurrentUser>)
    const photoAgent = {
      ...authFixture('AGENT').user,
      id: 20,
      full_name: 'Photo Agent',
      avatar_url: '/users/20/avatar',
      open_tasks: 0,
      urgent_cases: 0,
      gmail_connections: 0,
    }
    const initialsAgent = {
      ...photoAgent,
      id: 21,
      full_name: 'Initials Agent',
      email: 'initials@example.test',
      avatar_url: null,
    }
    vi.mocked(getAgentsPage).mockResolvedValue({
      items: [photoAgent, initialsAgent],
      page: { page: 1, page_size: 10, total: 2, pages: 1 },
    })
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <AgentsPage />
      </QueryClientProvider>,
    )

    const trigger = await screen.findByRole('button', {
      name: 'View larger profile photo for Photo Agent',
    })
    expect(trigger).toHaveClass(
      'h-9',
      'w-9',
      'shrink-0',
      'overflow-hidden',
      'p-0',
    )
    expect(
      within(trigger).getByRole('img', { name: 'Photo Agent profile' }),
    ).toHaveClass('h-9', 'w-9', 'object-cover')
    expect(
      screen.queryByRole('button', {
        name: 'View larger profile photo for Initials Agent',
      }),
    ).not.toBeInTheDocument()

    trigger.focus()
    fireEvent.click(trigger)
    let dialog = screen.getByRole('dialog', {
      name: 'Photo Agent profile photo preview',
    })
    expect(
      within(dialog).getByRole('img', { name: 'Photo Agent profile' }),
    ).toHaveAttribute('src', 'http://localhost:8000/api/v1/users/20/avatar')
    expect(
      within(dialog).getByRole('button', {
        name: 'Close profile photo preview',
      }),
    ).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Escape' })
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(trigger).toHaveFocus()

    fireEvent.click(trigger)
    dialog = screen.getByRole('dialog', {
      name: 'Photo Agent profile photo preview',
    })
    fireEvent.click(dialog)
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
