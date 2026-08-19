import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import { getAgents, getTasks, updateTask } from '../lib/api'
import { authFixture } from '../test/fixtures'
import { TasksPage } from './TasksPage'

vi.mock('../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../lib/api', () => ({
  getAgents: vi.fn(),
  getTasks: vi.fn(),
  updateTask: vi.fn(),
}))

const mockedAuth = vi.mocked(useCurrentUser)
const mockedGetTasks = vi.mocked(getTasks)
const mockedUpdateTask = vi.mocked(updateTask)

describe('TasksPage mutations', () => {
  it('sends an explicit task status update', async () => {
    mockedAuth.mockReturnValue({ data: authFixture('AGENT') } as ReturnType<
      typeof useCurrentUser
    >)
    vi.mocked(getAgents).mockResolvedValue([])
    mockedGetTasks.mockResolvedValue({
      items: [
        {
          id: 7,
          case_id: 3,
          client_name: 'Synthetic Client',
          policy_number: 'SYN-7',
          title: 'Contact client',
          description: null,
          priority: 'HIGH',
          due_at: '2026-09-15T17:00:00Z',
          status: 'OPEN',
          completed_at: null,
          assigned_agent: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
        },
      ],
      page: { page: 1, page_size: 100, total: 1, pages: 1 },
    })
    mockedUpdateTask.mockResolvedValue({
      ...(await mockedGetTasks()).items[0],
      status: 'COMPLETED',
      completed_at: '2026-08-19T12:00:00Z',
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <TasksPage />
      </QueryClientProvider>,
    )
    const status = await screen.findByLabelText('Update Contact client')
    fireEvent.change(status, { target: { value: 'COMPLETED' } })
    await waitFor(() =>
      expect(mockedUpdateTask).toHaveBeenCalledWith(7, 'COMPLETED'),
    )
  })
})
