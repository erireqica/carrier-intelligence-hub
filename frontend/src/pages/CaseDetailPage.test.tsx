import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
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
  correctCase,
  getAgents,
  getCase,
  getMe,
  updateTask,
} from '../lib/api'
import { authFixture } from '../test/fixtures'
import { CaseDetailPage } from './CaseDetailPage'

vi.mock('../lib/api', () => ({
  assignCase: vi.fn(),
  correctCase: vi.fn(),
  dismissCase: vi.fn(),
  getAgents: vi.fn(),
  getCase: vi.fn(),
  getMe: vi.fn(),
  restoreCase: vi.fn(),
  updateTask: vi.fn(),
}))

afterEach(cleanup)

describe('CaseDetailPage carrier messages', () => {
  it('renders truthful lifecycle text when semantic analysis is unavailable', async () => {
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
      can_manage_lifecycle: true,
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
          completed_at: null,
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
          completed_at: null,
          assigned_agent: {
            id: 3,
            full_name: 'Marcus Lee',
            email: 'agent.two@demo.local',
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
      can_manage_lifecycle: true,
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
          completed_at: null,
          assigned_agent: agent,
        },
      ],
      evidence: [],
      activity: [],
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
  })
})
