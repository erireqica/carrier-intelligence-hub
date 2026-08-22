import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

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

afterEach(cleanup)

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
          due_at: '2026-08-28',
          status: 'OPEN',
          created_at: '2026-08-22T10:00:00Z',
          completed_at: null,
          is_manual: true,
          created_by: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
          completed_by: null,
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
    expect(mockedGetTasks).toHaveBeenCalledWith(
      expect.stringContaining('view=TODO'),
    )
    expect(await screen.findByText('Aug 28, 2026')).toBeInTheDocument()
    expect(
      screen.getByText(/Added manually by Elena Torres/),
    ).toBeInTheDocument()
    const status = await screen.findByLabelText('Update Contact client')
    fireEvent.change(status, { target: { value: 'COMPLETED' } })
    await waitFor(() =>
      expect(mockedUpdateTask).toHaveBeenCalledWith(7, 'COMPLETED'),
    )
  })

  it('keeps even legacy manager-assigned tasks operationally read-only', async () => {
    const manager = authFixture('MANAGER')
    mockedAuth.mockReturnValue({ data: manager } as ReturnType<
      typeof useCurrentUser
    >)
    const agent = {
      ...authFixture('AGENT').user,
      open_tasks: 1,
      urgent_cases: 0,
      gmail_connections: 1,
    }
    vi.mocked(getAgents).mockResolvedValue([agent])
    mockedGetTasks.mockResolvedValue({
      items: [
        {
          id: 8,
          case_id: 3,
          client_name: 'Managed Client',
          policy_number: 'M-8',
          title: 'Agent decision',
          description: null,
          priority: 'NORMAL',
          due_at: null,
          status: 'OPEN',
          created_at: '2026-08-20T10:00:00Z',
          completed_at: null,
          is_manual: false,
          created_by: null,
          completed_by: null,
          assigned_agent: {
            id: manager.user.id,
            full_name: manager.user.full_name,
            email: manager.user.email,
          },
        },
      ],
      page: { page: 1, page_size: 100, total: 1, pages: 1 },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <TasksPage />
      </QueryClientProvider>,
    )
    await screen.findByText('Agent decision')
    expect(
      screen.queryByRole('columnheader', { name: 'Controls' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByLabelText('Update Agent decision'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByLabelText('Reassign Agent decision'),
    ).not.toBeInTheDocument()
  })

  it('shows agent-owned task status as read-only without task reassignment', async () => {
    const manager = authFixture('MANAGER')
    const agent = authFixture('AGENT').user
    mockedAuth.mockReturnValue({ data: manager } as ReturnType<
      typeof useCurrentUser
    >)
    vi.mocked(getAgents).mockResolvedValue([
      { ...agent, open_tasks: 1, urgent_cases: 0, gmail_connections: 1 },
    ])
    mockedGetTasks.mockResolvedValue({
      items: [
        {
          id: 9,
          case_id: 3,
          client_name: 'Assigned Client',
          policy_number: 'A-9',
          title: 'Assigned agent decision',
          description: null,
          priority: 'NORMAL',
          due_at: null,
          status: 'IN_PROGRESS',
          created_at: '2026-08-20T10:00:00Z',
          completed_at: null,
          is_manual: false,
          created_by: null,
          completed_by: null,
          assigned_agent: agent,
        },
      ],
      page: { page: 1, page_size: 100, total: 1, pages: 1 },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <TasksPage />
      </QueryClientProvider>,
    )
    await screen.findByText('Assigned agent decision')
    expect(
      screen.queryByRole('columnheader', { name: 'Controls' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByLabelText('Update Assigned agent decision'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByLabelText('Reassign Assigned agent decision'),
    ).not.toBeInTheDocument()
  })
})
