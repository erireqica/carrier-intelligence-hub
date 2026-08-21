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
  retryGmailWorkflowLabels,
  startGmailOAuth,
  syncGmailConnection,
} from '../lib/api'
import type { GmailConnection } from '../lib/types'
import { authFixture } from '../test/fixtures'
import { GmailConnectionsPage } from './GmailConnectionsPage'

vi.mock('../app/auth', () => ({ useCurrentUser: vi.fn() }))
vi.mock('../lib/api', () => ({
  disconnectGmailConnection: vi.fn(),
  getGmailConnections: vi.fn(),
  getGmailMessages: vi.fn(),
  processMessage: vi.fn(),
  redirectToOAuth: vi.fn(),
  retryGmailWorkflowLabels: vi.fn(),
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

    fireEvent.click(
      await screen.findByText('Troubleshooting and manual recovery'),
    )
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
    vi.mocked(getGmailMessages).mockResolvedValue([
      {
        id: 21,
        carrier: { id: 4, name: 'Acme Carrier', code: 'ACME' },
        sender: 'notices@acme.example',
        subject: 'Renewal notice',
        received_at: '2026-08-20T09:00:00Z',
        processing_status: 'RECEIVED',
        attachment_count: 2,
        case_id: null,
        review_id: null,
        last_processing_error_code: null,
        processing_attempt_count: 0,
        processing_next_retry_at: null,
        label_sync_status: 'PENDING',
      },
    ])
    renderPage()

    expect(await screen.findByText('Renewal notice')).toBeInTheDocument()
    expect(screen.getByText('RECEIVED')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Manual recovery'))
    fireEvent.click(screen.getByRole('button', { name: 'Analyze now' }))
    await waitFor(() => expect(processMessage).toHaveBeenCalledWith(21))
    fireEvent.click(screen.getByText('Troubleshooting and manual recovery'))
    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Gmail could not be reached.',
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
      screen.getByText(
        /Managers can view, sync, and retry managed-label delivery/,
      ),
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

  it('queues managed-label repair without accepting label IDs', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue({
      configured: true,
      connections: [{ ...baseConnection, pending_label_sync_count: 1 }],
    })
    vi.mocked(retryGmailWorkflowLabels).mockResolvedValue({ message: 'Queued' })
    renderPage()

    fireEvent.click(
      await screen.findByText('Troubleshooting and manual recovery'),
    )
    fireEvent.click(
      await screen.findByRole('button', { name: 'Retry workflow labels' }),
    )
    await waitFor(() =>
      expect(retryGmailWorkflowLabels).toHaveBeenCalledWith(11),
    )
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
