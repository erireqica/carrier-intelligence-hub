import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import {
  disconnectGmailConnection,
  getGmailConnections,
  getGmailMessages,
  processMessage,
  redirectToOAuth,
  startGmailOAuth,
  syncGmailConnection,
} from '../lib/api'
import type { GmailConnection, GmailMessage } from '../lib/types'
import { authFixture } from '../test/fixtures'
import { GmailConnectionsPage } from './GmailConnectionsPage'

vi.mock('../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../lib/api', () => ({
  disconnectGmailConnection: vi.fn(),
  getGmailConnections: vi.fn(),
  getGmailMessages: vi.fn(),
  processMessage: vi.fn(),
  redirectToOAuth: vi.fn(),
  startGmailOAuth: vi.fn(),
  syncGmailConnection: vi.fn(),
}))

const baseConnection: GmailConnection = {
  id: 11,
  gmail_address: 'agent@gmail.com',
  owner: { id: 2, full_name: 'Avery Agent', email: 'agent@example.com' },
  status: 'CONNECTED',
  connected_at: '2026-08-20T08:00:00Z',
  last_successful_sync_at: null,
  last_attempted_sync_at: null,
  last_error_summary: null,
  is_owner: true,
  can_apply_workflow_labels: true,
  pending_label_sync_count: 0,
  failed_label_sync_count: 0,
}

const baseMessage: GmailMessage = {
  id: 21,
  carrier: { id: 4, name: 'Acme Carrier', code: 'ACME' },
  sender: 'notices@acme.example',
  subject: 'Renewal notice',
  received_at: '2026-08-20T09:00:00Z',
  processing_status: 'RECEIVED',
  attachment_count: 2,
  case_id: null,
  case_assigned_agent: null,
  can_open_case: false,
  review_id: null,
  can_open_review: false,
  review_action_state: 'NONE',
  last_processing_error_code: null,
  processing_failure_reason: null,
  processing_retry_state: null,
  processing_attempt_count: 0,
  processing_next_retry_at: null,
  label_sync_status: 'PENDING',
}

function renderPage(
  path = '/gmail-connections',
  role: 'AGENT' | 'MANAGER' = 'AGENT',
) {
  vi.mocked(useCurrentUser).mockReturnValue({
    data: authFixture(role),
  } as ReturnType<typeof useCurrentUser>)
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <GmailConnectionsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(getGmailMessages).mockResolvedValue([])
  vi.mocked(processMessage).mockResolvedValue({
    message_id: 21,
    processing_status: 'PROCESSED',
    case_id: 31,
    review_id: null,
    tasks_created: 1,
    attachments_extracted: 0,
    analysis_confidence: 0.95,
    validation_flags: [],
  })
})

afterEach(cleanup)

describe('GmailConnectionsPage', () => {
  it('honestly explains the unconfigured OAuth state', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: false,
      connections: [],
    })
    renderPage()

    expect(
      await screen.findByText('No Gmail inbox connected'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect Gmail' })).toBeDisabled()
    expect(
      screen.getByText('Gmail integration is not configured.'),
    ).toBeInTheDocument()
  })

  it('starts a configured workflow-label OAuth connection', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [],
    })
    vi.mocked(startGmailOAuth).mockResolvedValue({
      authorization_url: 'https://accounts.google.test/authorize',
    })
    renderPage()

    fireEvent.click(
      await screen.findByRole('button', { name: 'Connect Gmail' }),
    )
    await waitFor(() => expect(startGmailOAuth).toHaveBeenCalledWith())
    expect(redirectToOAuth).toHaveBeenCalledWith(
      'https://accounts.google.test/authorize',
    )
  })

  it('renders every connection health state and owner actions', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [
        baseConnection,
        {
          ...baseConnection,
          id: 12,
          gmail_address: 'reauth@gmail.com',
          status: 'NEEDS_REAUTH',
        },
        {
          ...baseConnection,
          id: 13,
          gmail_address: 'error@gmail.com',
          status: 'ERROR',
          last_error_summary: 'Temporary provider failure.',
        },
        {
          ...baseConnection,
          id: 14,
          gmail_address: 'disconnected@gmail.com',
          status: 'DISCONNECTED',
        },
      ],
    })
    renderPage()

    expect(await screen.findByText('agent@gmail.com')).toBeInTheDocument()
    expect(screen.getByText('reauth@gmail.com')).toBeInTheDocument()
    expect(screen.getByText('error@gmail.com')).toBeInTheDocument()
    expect(screen.queryByText('disconnected@gmail.com')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Reconnect' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Disconnect' })).toHaveLength(
      3,
    )
    expect(screen.getAllByRole('button', { name: 'Sync now' })).toHaveLength(2)
    expect(screen.getByText(/Temporary provider failure/)).toBeInTheDocument()
  })

  it('shows sync progress and a successful ingestion summary', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [baseConnection],
    })
    let completeSync:
      | ((value: Awaited<ReturnType<typeof syncGmailConnection>>) => void)
      | undefined
    vi.mocked(syncGmailConnection).mockImplementation(
      () =>
        new Promise((resolve) => {
          completeSync = resolve
        }),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
    expect(
      await screen.findByRole('button', { name: 'Syncing…' }),
    ).toBeDisabled()
    completeSync?.({
      connection_id: 11,
      messages_seen: 4,
      already_ingested: 1,
      approved: 2,
      ingested: 2,
      skipped_unapproved: 1,
      attachments_discovered: 3,
    })
    expect(
      await screen.findByText(
        'Sync complete: 2 ingested, 1 already present, 1 unapproved skipped.',
      ),
    ).toBeInTheDocument()
  })

  it('shows safe sync errors and recent received messages', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [baseConnection],
    })
    vi.mocked(syncGmailConnection).mockRejectedValue(
      new Error('Gmail could not be reached.'),
    )
    vi.mocked(getGmailMessages).mockResolvedValue([baseMessage])
    renderPage()

    expect(getGmailMessages).not.toHaveBeenCalled()
    const recentMessages = await screen.findByText('Ingested carrier messages')
    fireEvent.click(recentMessages)
    expect(await screen.findByText('Renewal notice')).toBeInTheDocument()
    expect(screen.getByText('RECEIVED')).toBeInTheDocument()
    expect(screen.getByText('Queued for analysis')).toBeInTheDocument()
    expect(screen.getByText('Labels queued')).toBeInTheDocument()
    expect(getGmailMessages).toHaveBeenCalledWith(11, 1)
    expect(screen.queryByText('Sync manually')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Analyze now' }),
    ).not.toBeInTheDocument()
    expect(processMessage).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Gmail could not be reached.',
    )
  })

  it('keeps processing passive and exposes recovery only after retries exhaust', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [baseConnection],
    })
    vi.mocked(getGmailMessages).mockResolvedValue([
      {
        ...baseMessage,
        id: 22,
        subject: 'Processing message',
        processing_status: 'PROCESSING',
        label_sync_status: 'PROCESSING',
      },
      {
        ...baseMessage,
        id: 23,
        subject: 'Scheduled retry message',
        processing_status: 'FAILED',
        processing_attempt_count: 1,
        processing_next_retry_at: '2026-08-20T09:10:00Z',
        processing_failure_reason: 'The AI service did not respond in time.',
        processing_retry_state: 'AUTOMATIC_RETRY_SCHEDULED',
        label_sync_status: 'RETRY_WAIT',
      },
      {
        ...baseMessage,
        id: 24,
        subject: 'Exhausted retry message',
        processing_status: 'FAILED',
        processing_attempt_count: 3,
        last_processing_error_code: 'AI_TIMEOUT',
        processing_failure_reason: 'The AI service did not respond in time.',
        processing_retry_state: 'AUTOMATIC_RETRIES_EXHAUSTED',
        label_sync_status: 'FAILED',
      },
      {
        ...baseMessage,
        id: 25,
        subject: 'Accessible case message',
        processing_status: 'PROCESSED',
        case_id: 31,
        case_assigned_agent: {
          id: 2,
          full_name: 'Elena Torres',
          email: 'agent.one@demo.local',
        },
        can_open_case: true,
        label_sync_status: 'APPLIED',
      },
      {
        ...baseMessage,
        id: 26,
        subject: 'Reassigned case message',
        processing_status: 'PROCESSED',
        review_id: 91,
        can_open_review: false,
        review_action_state: 'UNAVAILABLE',
        case_id: 32,
        case_assigned_agent: {
          id: 3,
          full_name: 'Marcus Lee',
          email: 'agent.two@demo.local',
        },
        can_open_case: false,
        label_sync_status: 'NEEDS_PERMISSION',
      },
      {
        ...baseMessage,
        id: 27,
        subject: 'Accessible review message',
        processing_status: 'NEEDS_REVIEW',
        review_id: 92,
        can_open_review: true,
        review_action_state: 'ACTIONABLE',
      },
      {
        ...baseMessage,
        id: 28,
        subject: 'Dismissed case review',
        processing_status: 'IGNORED',
        review_id: 93,
        can_open_review: false,
        review_action_state: 'CASE_DISMISSED',
      },
      {
        ...baseMessage,
        id: 29,
        subject: 'Completed case review',
        processing_status: 'PROCESSED',
        review_id: 94,
        can_open_review: false,
        review_action_state: 'CASE_COMPLETED',
      },
    ])
    renderPage()

    fireEvent.click(await screen.findByText('Ingested carrier messages'))
    expect(await screen.findByText('Analyzing…')).toBeInTheDocument()
    expect(screen.getByText('Retry scheduled')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Automatic retries exhausted. Manual retry is available.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Updating labels…')).toBeInTheDocument()
    expect(screen.getByText('Label retry scheduled')).toBeInTheDocument()
    expect(screen.getByText('Labels need attention')).toBeInTheDocument()
    expect(screen.getByText('Gmail permissions required')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open case' })).toHaveAttribute(
      'href',
      '/cases/31',
    )
    expect(
      screen.queryByRole('link', { name: /case.*32/i }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Managed by Marcus Lee')).toBeInTheDocument()
    const reviewLinks = screen.getAllByRole('link', { name: 'Review' })
    expect(reviewLinks).toHaveLength(1)
    expect(reviewLinks[0]).toHaveAttribute('href', '/reviews/92')
    expect(screen.getByText('Case dismissed')).toBeInTheDocument()
    expect(screen.getByText('Case completed')).toBeInTheDocument()
    expect(screen.queryByText('Review required')).not.toBeInTheDocument()
    expect(
      screen.getByText('Case assigned to another agent'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Analyze now' }),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('Manual retry'))
    fireEvent.click(screen.getByRole('button', { name: 'Retry analysis' }))
    await waitFor(() => expect(processMessage).toHaveBeenCalledWith(24))
  })

  it('shows analysis progress and a safe API error during manual recovery', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [baseConnection],
    })
    vi.mocked(getGmailMessages).mockResolvedValue([
      {
        ...baseMessage,
        processing_status: 'FAILED',
        last_processing_error_code: 'MATERIALIZATION_FAILED',
        processing_failure_reason:
          'Analysis completed, but the case or tasks could not be saved safely.',
        processing_retry_state: 'MANUAL_RECOVERY_REQUIRED',
      },
    ])
    let rejectRetry: ((error: Error) => void) | undefined
    vi.mocked(processMessage).mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectRetry = reject
        }),
    )
    renderPage()

    fireEvent.click(await screen.findByText('Ingested carrier messages'))
    expect(
      await screen.findByText(
        'Analysis completed, but the case or tasks could not be saved safely.',
      ),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByText('Manual retry'))
    fireEvent.click(screen.getByRole('button', { name: 'Retry analysis' }))
    await waitFor(() =>
      expect(screen.getAllByText('Analyzing…')).toHaveLength(2),
    )
    rejectRetry?.(new Error('Analysis retry could not be started.'))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Analysis retry could not be started.',
    )
  })

  it('shows OAuth callback feedback and keeps manager actions read-only', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [{ ...baseConnection, is_owner: false }],
    })
    renderPage('/gmail-connections?oauth=scope_missing', 'MANAGER')

    expect(
      await screen.findByText(
        'The required Gmail workflow-label permission was not granted.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Connected agent')).toBeInTheDocument()
    expect(screen.getByText(/Avery Agent/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Reconnect' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Disconnect' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Connect Gmail' }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeInTheDocument()
    expect(
      screen.getByText(/Managers can monitor and sync agency connections/),
    ).toBeInTheDocument()
    expect(disconnectGmailConnection).not.toHaveBeenCalled()
  })

  it('shows an owner permission upgrade action', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [
        {
          ...baseConnection,
          can_apply_workflow_labels: false,
          failed_label_sync_count: 1,
        },
      ],
    })
    vi.mocked(startGmailOAuth).mockResolvedValue({
      authorization_url: 'https://accounts.google.test/upgrade',
    })
    renderPage()

    fireEvent.click(
      await screen.findByRole('button', { name: 'Upgrade permissions' }),
    )
    await waitFor(() => expect(startGmailOAuth).toHaveBeenCalledWith(11))
    expect(
      screen.getByText(/Connected for ingestion. Workflow labels require/),
    ).toBeInTheDocument()
  })

  it('does not expose manual workflow-label retry controls', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [
        {
          ...baseConnection,
          pending_label_sync_count: 1,
          failed_label_sync_count: 1,
        },
      ],
    })
    renderPage()

    expect(
      await screen.findByRole('button', { name: 'Sync now' }),
    ).toBeVisible()
    expect(
      screen.queryByRole('button', { name: 'Retry workflow labels' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/1 pending.*1 need attention/)).toBeInTheDocument()
  })

  it('shows the dedicated duplicate-inbox OAuth message', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [],
    })
    renderPage('/gmail-connections?oauth=already_connected')
    expect(
      await screen.findByText(
        'This Gmail inbox is already connected to another agent in your agency.',
      ),
    ).toBeInTheDocument()
  })

  it('confirms disconnect and removes the active card after success', async () => {
    vi.mocked(getGmailConnections)
      .mockResolvedValueOnce({
        configured: true,
        connections: [baseConnection],
      })
      .mockResolvedValue({ configured: true, connections: [] })
    vi.mocked(disconnectGmailConnection).mockResolvedValue({
      message: 'Disconnected',
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    await waitFor(() =>
      expect(disconnectGmailConnection).toHaveBeenCalledWith(11),
    )
    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringContaining(
        'Existing cases, tasks, messages and audit history will be preserved.',
      ),
    )
    expect(
      await screen.findByText('No Gmail inbox connected'),
    ).toBeInTheDocument()
    expect(screen.queryByText('agent@gmail.com')).not.toBeInTheDocument()
  })
})
