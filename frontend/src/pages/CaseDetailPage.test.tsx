import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  assignCase,
  completeCase,
  correctCase,
  createManualTask,
  getAgents,
  getCase,
  getMe,
  reopenCase,
  updateTask,
} from '../lib/api'
import { authFixture } from '../test/fixtures'
import { CaseDetailPage } from './CaseDetailPage'

vi.mock('../lib/api', () => ({
  assignCase: vi.fn(),
  completeCase: vi.fn(),
  correctCase: vi.fn(),
  createManualTask: vi.fn(),
  dismissCase: vi.fn(),
  getAgents: vi.fn(),
  getCase: vi.fn(),
  getMe: vi.fn(),
  restoreCase: vi.fn(),
  reopenCase: vi.fn(),
  updateTask: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('CaseDetailPage carrier messages', () => {
  it('renders lifecycle text and filters dismissed tasks', async () => {
    vi.mocked(getMe).mockResolvedValue(authFixture('AGENT'))
    vi.mocked(getCase).mockResolvedValue({
      id: 1,
      client_name: 'Synthetic Client',
      policy_number: null,
      policy_status: 'UNKNOWN',
      priority: 'NORMAL',
      summary: 'Source message received.',
      deadline: '2026-08-28',
      updated_at: '2026-08-20T10:00:00Z',
      carrier: { id: 1, name: 'Americo', code: 'AMR' },
      assigned_agent: null,
      needs_review: false,
      dismissed_at: '2026-08-21T10:00:00Z',
      completed_at: null,
      can_manage_lifecycle: true,
      completed_by: null,
      can_complete: false,
      can_reopen: false,
      completion_blockers: [
        'Complete all active tasks before completing this case.',
      ],
      premium_amount: null,
      currency: null,
      effective_date: null,
      messages: [
        {
          id: 10,
          sender: 'source@example.test',
          subject: 'New carrier message',
          received_at: '2026-08-20T10:00:00Z',
          classification: null,
          summary: null,
          priority: null,
          processing_status: 'PROCESSING',
          cleaned_content: 'Submit the form by August 28, 2026.',
          original_deadline_text: 'by August 28, 2026',
          analysis_confidence: null,
          validation_flags: [],
          review_id: null,
        },
      ],
      attachments: [],
      tasks: [
        {
          id: 5,
          case_id: 1,
          client_name: 'Synthetic Client',
          policy_number: null,
          title: 'Submit authorization',
          description: 'Send the signed form.',
          priority: 'HIGH',
          due_at: '2026-08-28',
          status: 'OPEN',
          created_at: '2026-08-20T10:00:00Z',
          completed_at: null,
          is_manual: false,
          created_by: null,
          completed_by: null,
          assigned_agent: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
        },
        {
          id: 9,
          case_id: 1,
          client_name: 'Synthetic Client',
          policy_number: null,
          title: 'Completed automated task',
          description: 'Generated from a carrier message.',
          priority: 'NORMAL',
          due_at: null,
          status: 'COMPLETED',
          created_at: '2026-08-20T10:00:00Z',
          completed_at: '2026-08-21T10:00:00Z',
          is_manual: false,
          created_by: null,
          completed_by: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
          assigned_agent: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
        },
        {
          id: 10,
          case_id: 1,
          client_name: 'Synthetic Client',
          policy_number: null,
          title: 'Completed manual task',
          description: 'Added by the assigned agent.',
          priority: 'LOW',
          due_at: null,
          status: 'COMPLETED',
          created_at: '2026-08-20T11:00:00Z',
          completed_at: '2026-08-21T11:00:00Z',
          is_manual: true,
          created_by: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
          completed_by: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
          assigned_agent: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
        },
        {
          id: 6,
          case_id: 1,
          client_name: 'Synthetic Client',
          policy_number: null,
          title: 'Other assignee task',
          description: 'Handled by another user.',
          priority: 'NORMAL',
          due_at: null,
          status: 'IN_PROGRESS',
          created_at: '2026-08-20T10:00:00Z',
          completed_at: null,
          is_manual: false,
          created_by: null,
          completed_by: null,
          assigned_agent: {
            id: 3,
            full_name: 'Marcus Lee',
            email: 'agent.two@demo.local',
          },
        },
        {
          id: 7,
          case_id: 1,
          client_name: 'Synthetic Client',
          policy_number: null,
          title: 'Dismissed automated task',
          description: 'Generated from a carrier message.',
          priority: 'NORMAL',
          due_at: null,
          status: 'DISMISSED',
          created_at: '2026-08-20T10:00:00Z',
          completed_at: null,
          is_manual: false,
          created_by: null,
          completed_by: null,
          assigned_agent: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
        },
        {
          id: 8,
          case_id: 1,
          client_name: 'Synthetic Client',
          policy_number: null,
          title: 'Dismissed manual task',
          description: 'Added by the assigned agent.',
          priority: 'LOW',
          due_at: null,
          status: 'DISMISSED',
          created_at: '2026-08-20T11:00:00Z',
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
      evidence: [],
      activity: [],
    })
    vi.mocked(updateTask).mockRejectedValue(new Error('Not used'))
    vi.mocked(correctCase).mockRejectedValue(new Error('Not used'))
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/cases/1']}>
          <Routes>
            <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('New carrier message')).toBeInTheDocument()
    expect(screen.getAllByText('Processing').length).toBeGreaterThan(0)
    expect(
      screen.getByText('Semantic analysis is currently in progress.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Aug 28, 2026')).toBeInTheDocument()
    expect(screen.getByText('Due Aug 28, 2026')).toBeInTheDocument()
    expect(
      screen.getByText('Submit the form by August 28, 2026.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('OTHER')).not.toBeInTheDocument()
    expect(screen.getByText('Status managed by Marcus Lee')).toBeInTheDocument()
    expect(
      screen.queryByLabelText('Update Other assignee task'),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Submit authorization')).toBeInTheDocument()
    expect(screen.getByText('Other assignee task')).toBeInTheDocument()
    expect(
      screen.queryByText('Dismissed automated task'),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Dismissed manual task')).not.toBeInTheDocument()
    expect(screen.getByText('Completed automated task')).toBeInTheDocument()
    expect(screen.getByText('Completed manual task')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /completed/i }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText('Dismissed automated task'),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Show dismissed (2)' }))

    const automatedTask = screen.getByText('Dismissed automated task')
    const manualTask = screen.getByText('Dismissed manual task')
    const automatedRow = automatedTask.closest('[data-task-status]')
    const manualRow = manualTask.closest('[data-task-status]')
    expect(automatedRow).toHaveAttribute('data-task-status', 'DISMISSED')
    expect(manualRow).toHaveAttribute('data-task-status', 'DISMISSED')
    expect(automatedRow).toHaveClass('bg-slate-50/80')
    expect(manualRow).toHaveClass('bg-slate-50/80')
    expect(automatedTask).toHaveClass('line-through')
    expect(manualTask).toHaveClass('line-through')
    expect(screen.getAllByText('DISMISSED')).toHaveLength(2)
    expect(screen.getByText('Submit authorization')).toBeInTheDocument()
    expect(screen.getByText('Other assignee task')).toBeInTheDocument()
    expect(screen.getByText('Completed automated task')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Hide dismissed' }))

    expect(
      screen.queryByText('Dismissed automated task'),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Dismissed manual task')).not.toBeInTheDocument()
    expect(screen.getByText('Submit authorization')).toBeInTheDocument()
    expect(screen.getByText('Other assignee task')).toBeInTheDocument()
    expect(screen.getByText('Completed automated task')).toBeInTheDocument()
    const restore = screen.getByRole('button', { name: 'Restore case' })
    expect(restore).toHaveClass('bg-emerald-700')
    expect(
      screen.queryByRole('button', { name: 'Correct case information' }),
    ).not.toBeInTheDocument()
  })

  it('lets an agent submit an audited current-case correction', async () => {
    vi.mocked(getMe).mockResolvedValue(authFixture('AGENT'))
    const item = {
      id: 2,
      client_name: 'Correction Client',
      policy_number: 'COR-2',
      policy_status: 'PENDING' as const,
      priority: 'HIGH' as const,
      summary: 'Pending carrier requirement.',
      deadline: null,
      updated_at: '2026-08-20T10:00:00Z',
      carrier: { id: 1, name: 'Americo', code: 'AMR' },
      assigned_agent: {
        id: 2,
        full_name: 'Elena Torres',
        email: 'agent.one@demo.local',
      },
      needs_review: false,
      dismissed_at: null,
      completed_at: null,
      can_manage_lifecycle: true,
      completed_by: null,
      can_complete: false,
      can_reopen: false,
      completion_blockers: [
        'Complete all active tasks before completing this case.',
      ],
      premium_amount: null,
      currency: null,
      effective_date: null,
      messages: [
        {
          id: 20,
          sender: 'carrier@example.test',
          subject: 'Pending requirement',
          received_at: '2026-08-20T10:00:00Z',
          classification: 'PENDING_REQUIREMENTS' as const,
          summary: 'Pending carrier requirement.',
          priority: 'HIGH' as const,
          processing_status: 'PROCESSED' as const,
          cleaned_content: 'Please return the requirement.',
          original_deadline_text: null,
          analysis_confidence: 0.9,
          validation_flags: [],
          review_id: null,
        },
      ],
      attachments: [],
      tasks: [],
      evidence: [],
      activity: [],
    }
    vi.mocked(getCase).mockResolvedValue(item)
    vi.mocked(correctCase).mockResolvedValue({
      ...item,
      policy_status: 'ACTIVE',
      summary: 'Confirmed active.',
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/cases/2']}>
          <Routes>
            <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const correctButton = await screen.findByRole('button', {
      name: 'Correct case information',
    })
    const dismissButton = screen.getByRole('button', { name: 'Dismiss case' })
    const completeButton = screen.getByRole('button', {
      name: 'Mark as complete',
    })
    expect(
      screen.queryByText(
        'Complete all active tasks before completing this case.',
      ),
    ).not.toBeInTheDocument()
    vi.useFakeTimers()
    fireEvent.click(completeButton)
    expect(
      screen.getByText(
        'Complete all active tasks before completing this case.',
      ),
    ).toBeInTheDocument()
    expect(completeCase).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(4000))
    expect(
      screen.queryByText(
        'Complete all active tasks before completing this case.',
      ),
    ).not.toBeInTheDocument()
    vi.useRealTimers()
    expect(correctButton.parentElement).toBe(dismissButton.parentElement)
    expect(dismissButton).toHaveClass('bg-red-700')
    expect(screen.getAllByText('Pending carrier requirement.')).toHaveLength(1)
    expect(screen.getByText('AI analysis')).toBeInTheDocument()
    expect(screen.queryByText('View AI analysis')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Technical analysis details'))
    expect(screen.getByText(/AI's analysis confidence:/)).toHaveTextContent(
      "AI's analysis confidence: 90%",
    )
    fireEvent.click(correctButton)
    fireEvent.change(screen.getByLabelText('Policy status'), {
      target: { value: 'ACTIVE' },
    })
    fireEvent.change(screen.getByLabelText('Summary'), {
      target: { value: 'Confirmed active.' },
    })
    fireEvent.change(screen.getByLabelText('Reason for correction'), {
      target: { value: 'Carrier confirmed status.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }))
    await waitFor(() =>
      expect(correctCase).toHaveBeenCalledWith(
        2,
        expect.objectContaining({
          policy_status: 'ACTIVE',
          reason: 'Carrier confirmed status.',
        }),
      ),
    )
  })

  it('lets a manager assign the whole case while keeping tasks read-only', async () => {
    const manager = authFixture('MANAGER')
    const agent = {
      ...authFixture('AGENT').user,
      open_tasks: 1,
      urgent_cases: 0,
      gmail_connections: 1,
    }
    vi.mocked(getMe).mockResolvedValue(manager)
    vi.mocked(getAgents).mockResolvedValue([agent])
    const item = {
      id: 3,
      client_name: 'Managed Client',
      policy_number: 'MAN-3',
      policy_status: 'PENDING' as const,
      priority: 'HIGH' as const,
      summary: 'Pending managed case.',
      deadline: null,
      updated_at: '2026-08-20T10:00:00Z',
      carrier: { id: 1, name: 'Americo', code: 'AMR' },
      assigned_agent: {
        id: manager.user.id,
        full_name: manager.user.full_name,
        email: manager.user.email,
      },
      needs_review: false,
      premium_amount: null,
      currency: null,
      effective_date: null,
      messages: [],
      attachments: [],
      tasks: [
        {
          id: 9,
          case_id: 3,
          client_name: 'Managed Client',
          policy_number: 'MAN-3',
          title: 'Agent-owned action',
          description: null,
          priority: 'HIGH' as const,
          due_at: null,
          status: 'OPEN' as const,
          created_at: '2026-08-20T10:00:00Z',
          completed_at: null,
          is_manual: false,
          created_by: null,
          completed_by: null,
          assigned_agent: agent,
        },
      ],
      evidence: [],
      activity: [],
      dismissed_at: null,
      can_manage_lifecycle: true,
      completed_at: null,
      completed_by: null,
      can_complete: false,
      can_reopen: false,
      completion_blockers: [
        'Complete all active tasks before completing this case.',
      ],
    }
    vi.mocked(getCase).mockResolvedValue(item)
    vi.mocked(assignCase).mockResolvedValue(item)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/cases/3']}>
          <Routes>
            <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await screen.findByRole('option', { name: 'Elena Torres' })
    expect(
      screen.getByRole('button', { name: 'Correct case information' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dismiss case' })).toHaveClass(
      'bg-red-700',
    )
    const back = screen.getByRole('link', { name: 'Back to cases' })
    const title = screen.getByRole('heading', { name: 'Managed Client' })
    expect(
      back.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Assigned agent'), {
      target: { value: String(agent.id) },
    })
    await waitFor(() => expect(assignCase).toHaveBeenCalledWith(3, agent.id))
    expect(
      screen.queryByLabelText('Update Agent-owned action'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByText('Status managed by Elena Torres'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Add task' }),
    ).not.toBeInTheDocument()
  })

  it('lets the assigned agent add a manual task with attribution', async () => {
    const auth = authFixture('AGENT')
    const item = {
      id: 4,
      client_name: 'Manual Task Client',
      policy_number: 'MT-4',
      policy_status: 'ACTIVE' as const,
      priority: 'NORMAL' as const,
      summary: 'Active policy.',
      deadline: null,
      updated_at: '2026-08-20T10:00:00Z',
      carrier: { id: 1, name: 'Americo', code: 'AMR' },
      assigned_agent: {
        id: auth.user.id,
        full_name: auth.user.full_name,
        email: auth.user.email,
      },
      needs_review: false,
      dismissed_at: null,
      completed_at: null,
      can_manage_lifecycle: true,
      completed_by: null,
      can_complete: true,
      can_reopen: false,
      completion_blockers: [],
      premium_amount: null,
      currency: null,
      effective_date: null,
      messages: [],
      attachments: [],
      tasks: [],
      evidence: [],
      activity: [],
    }
    const manualTask = {
      id: 40,
      case_id: 4,
      client_name: item.client_name,
      policy_number: item.policy_number,
      title: 'Call client to confirm mailing address',
      description: 'Confirm before mailing the policy package.',
      priority: 'HIGH' as const,
      due_at: '2026-08-29',
      status: 'OPEN' as const,
      created_at: '2026-08-22T12:00:00Z',
      completed_at: null,
      assigned_agent: item.assigned_agent,
      is_manual: true,
      created_by: item.assigned_agent,
      completed_by: null,
    }
    vi.mocked(getMe).mockResolvedValue(auth)
    vi.mocked(getCase)
      .mockResolvedValueOnce(item)
      .mockResolvedValue({ ...item, tasks: [manualTask] })
    vi.mocked(createManualTask).mockResolvedValue(manualTask)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/cases/4']}>
          <Routes>
            <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(
      screen.queryByRole('button', { name: /dismissed/i }),
    ).not.toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Add task' }))
    expect(screen.getByRole('form', { name: 'Add task' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Task title'), {
      target: { value: manualTask.title },
    })
    fireEvent.change(screen.getByLabelText(/Notes/), {
      target: { value: manualTask.description },
    })
    fireEvent.change(screen.getByLabelText('Priority'), {
      target: { value: 'HIGH' },
    })
    fireEvent.change(screen.getByLabelText(/Due date/), {
      target: { value: '2026-08-29' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add task' }))

    await waitFor(() =>
      expect(createManualTask).toHaveBeenCalledWith(4, {
        title: manualTask.title,
        description: manualTask.description,
        priority: 'HIGH',
        due_date: '2026-08-29',
      }),
    )
    expect(await screen.findByText(manualTask.title)).toBeInTheDocument()
    expect(
      screen.getByText(/Added manually by Elena Torres/),
    ).toBeInTheDocument()
  })

  it('lets the assigned agent explicitly complete and reopen ready Case work', async () => {
    const auth = authFixture('AGENT')
    const active = {
      id: 5,
      client_name: 'Ready Client',
      policy_number: 'READY-5',
      policy_status: 'ACTIVE' as const,
      priority: 'NORMAL' as const,
      summary: 'All operational work is finished.',
      deadline: null,
      updated_at: '2026-08-23T10:00:00Z',
      carrier: { id: 1, name: 'Americo', code: 'AMR' },
      assigned_agent: {
        id: auth.user.id,
        full_name: auth.user.full_name,
        email: auth.user.email,
      },
      needs_review: false,
      dismissed_at: null,
      completed_at: null,
      can_manage_lifecycle: true,
      completed_by: null,
      can_complete: true,
      can_reopen: false,
      completion_blockers: [],
      premium_amount: null,
      currency: null,
      effective_date: null,
      messages: [],
      attachments: [],
      tasks: [],
      evidence: [],
      activity: [],
    }
    const completed = {
      ...active,
      completed_at: '2026-08-23T10:30:00Z',
      completed_by: active.assigned_agent,
      can_complete: false,
      can_reopen: true,
    }
    vi.mocked(getMe).mockResolvedValue(auth)
    vi.mocked(getCase)
      .mockResolvedValueOnce(active)
      .mockResolvedValue(completed)
    vi.mocked(completeCase).mockResolvedValue(completed)
    vi.mocked(reopenCase).mockResolvedValue(active)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/cases/5']}>
          <Routes>
            <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    fireEvent.click(
      await screen.findByRole('button', { name: 'Mark as complete' }),
    )
    await waitFor(() => expect(completeCase).toHaveBeenCalledWith(5))
    expect(await screen.findByText('Case completed')).toBeInTheDocument()
    expect(screen.getByText(/Completed by Elena Torres/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reopen case' }))
    await waitFor(() => expect(reopenCase).toHaveBeenCalledWith(5))
  })
})
