import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Mail, PlugZap, RefreshCw, Unplug } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import { Avatar } from '../components/Avatar'
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  StatusBadge,
} from '../components/ui'
import { formatDate } from '../lib/format'
import {
  disconnectGmailConnection,
  getGmailConnections,
  getGmailMessages,
  processMessage,
  redirectToOAuth,
  startGmailOAuth,
  syncGmailConnection,
} from '../lib/api'
import { shouldPollRecentMessages } from '../lib/gmail'
import type { GmailConnection, GmailSyncResult } from '../lib/types'

const oauthMessages: Record<string, { tone: string; message: string }> = {
  success: {
    tone: 'border-green-300 bg-green-50 text-green-950',
    message: 'Gmail inbox connected successfully.',
  },
  denied: {
    tone: 'border-amber-300 bg-amber-50 text-amber-950',
    message: 'Google authorization was cancelled.',
  },
  invalid_state: {
    tone: 'border-amber-300 bg-amber-50 text-amber-950',
    message: 'The Gmail connection request expired. Please try again.',
  },
  scope_missing: {
    tone: 'border-red-300 bg-red-50 text-red-950',
    message: 'The required Gmail workflow-label permission was not granted.',
  },
  already_connected: {
    tone: 'border-amber-300 bg-amber-50 text-amber-950',
    message:
      'This Gmail inbox is already connected to another agent in your agency.',
  },
  failed: {
    tone: 'border-red-300 bg-red-50 text-red-950',
    message: 'Gmail authorization could not be completed. Please try again.',
  },
}

const labelSyncText: Record<string, string> = {
  APPLIED: 'Labels synced',
  PENDING: 'Labels queued',
  PROCESSING: 'Updating labels…',
  RETRY_WAIT: 'Label retry scheduled',
  NEEDS_PERMISSION: 'Gmail permissions required',
  FAILED: 'Labels need attention',
}

function RecentMessages({ connectionId }: { connectionId: number }) {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const messages = useQuery({
    queryKey: ['gmail-connections', connectionId, 'messages', page],
    queryFn: () => getGmailMessages(connectionId, page),
    refetchInterval: (query) =>
      shouldPollRecentMessages(query.state.data) ? 3000 : false,
  })
  const process = useMutation({
    mutationFn: (messageId: number) => processMessage(messageId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['gmail-connections', connectionId, 'messages'],
      })
      await queryClient.invalidateQueries({ queryKey: ['reviews'] })
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  if (messages.isPending)
    return (
      <p className="mt-4 text-sm text-slate-500">Loading recent messages…</p>
    )
  if (messages.isError)
    return (
      <p className="mt-4 text-sm text-red-700">
        Recent messages could not be loaded.
      </p>
    )
  const messageItems = Array.isArray(messages.data)
    ? messages.data
    : messages.data.items
  const messagePage = Array.isArray(messages.data)
    ? {
        page: 1,
        pages: 1,
        page_size: messageItems.length,
        total: messageItems.length,
      }
    : messages.data.page
  if (!messageItems.length)
    return (
      <p className="mt-4 text-sm text-slate-500">
        No approved carrier messages have been ingested from this inbox yet.
      </p>
    )
  return (
    <div className="data-table-shell responsive-data-table mt-5">
      <table className="w-full min-w-[920px] text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
          <tr>
            <th className="px-3 py-2">Subject</th>
            <th className="px-3 py-2">Received</th>
            <th className="px-3 py-2">Carrier</th>
            <th className="px-3 py-2">Sender</th>
            <th className="px-3 py-2">State</th>
            <th className="px-3 py-2">Gmail workflow</th>
            <th className="px-3 py-2">Attachments</th>
            <th className="px-3 py-2">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {messageItems.map((message) => {
            const isRetrying =
              process.isPending && process.variables === message.id
            return (
              <tr key={message.id}>
                <td className="px-3 py-3 font-medium" data-label="Subject">
                  {message.subject}
                </td>
                <td className="px-3 py-3" data-label="Received">
                  {formatDate(message.received_at)}
                </td>
                <td className="px-3 py-3" data-label="Carrier">
                  {message.carrier.name}
                </td>
                <td
                  className="px-3 py-3 break-all"
                  data-label="Sender"
                  data-mobile-span="full"
                >
                  {message.sender}
                </td>
                <td className="px-3 py-3" data-label="State">
                  <StatusBadge
                    status={
                      isRetrying ? 'PROCESSING' : message.processing_status
                    }
                  />
                  {isRetrying ? (
                    <p className="mt-1 max-w-48 text-xs text-slate-500">
                      Analyzing…
                    </p>
                  ) : message.processing_status === 'FAILED' ? (
                    <p className="mt-1 max-w-48 text-xs text-slate-500">
                      {message.processing_failure_reason}
                      <span className="mt-1 block">
                        {message.processing_retry_state ===
                        'AUTOMATIC_RETRY_SCHEDULED'
                          ? `Automatic retry scheduled after attempt ${message.processing_attempt_count}.`
                          : message.processing_retry_state ===
                              'AUTOMATIC_RETRIES_EXHAUSTED'
                            ? 'Automatic retries exhausted. Manual retry is available.'
                            : message.processing_retry_state ===
                                'REAUTHORIZATION_REQUIRED'
                              ? 'Reconnect Gmail to resume analysis.'
                              : 'Manual retry is required.'}
                      </span>
                    </p>
                  ) : null}
                </td>
                <td
                  className="px-3 py-3 text-xs text-slate-600"
                  data-label="Gmail workflow"
                >
                  {message.label_sync_status
                    ? labelSyncText[message.label_sync_status]
                    : 'Not queued'}
                </td>
                <td className="px-3 py-3" data-label="Attachments">
                  {message.attachment_count}
                </td>
                <td className="px-3 py-3" data-label="Action">
                  {isRetrying ? (
                    <span className="text-slate-500">Analyzing…</span>
                  ) : message.review_action_state === 'CASE_DISMISSED' ? (
                    <span className="font-medium text-slate-600">
                      Case dismissed
                    </span>
                  ) : message.review_action_state === 'CASE_COMPLETED' ? (
                    <span className="font-medium text-slate-600">
                      Case completed
                    </span>
                  ) : message.review_action_state === 'ACTIONABLE' &&
                    message.review_id &&
                    message.can_open_review ? (
                    <Link
                      className="font-semibold text-blue-700"
                      to={`/reviews/${message.review_id}`}
                    >
                      Review
                    </Link>
                  ) : message.case_id && message.can_open_case ? (
                    <Link
                      className="font-semibold text-blue-700"
                      to={`/cases/${message.case_id}`}
                    >
                      Open case
                    </Link>
                  ) : message.case_id ? (
                    <div>
                      <span className="font-medium text-slate-700">
                        Managed by{' '}
                        {message.case_assigned_agent?.full_name ??
                          'another agent'}
                      </span>
                      <p className="mt-1 text-xs text-slate-500">
                        Case assigned to another agent
                      </p>
                    </div>
                  ) : message.processing_status === 'PROCESSED' ? (
                    <span className="font-medium text-slate-600">
                      No further action
                    </span>
                  ) : message.processing_status === 'RECEIVED' ? (
                    <span className="text-slate-500">Queued for analysis</span>
                  ) : message.processing_status === 'PROCESSING' ? (
                    <span className="text-slate-500">Analyzing…</span>
                  ) : message.processing_status === 'FAILED' &&
                    message.processing_next_retry_at ? (
                    <span className="text-slate-500">Retry scheduled</span>
                  ) : message.processing_status === 'FAILED' &&
                    message.processing_retry_state !==
                      'REAUTHORIZATION_REQUIRED' ? (
                    <details>
                      <summary className="cursor-pointer text-xs font-semibold text-slate-600">
                        Manual retry
                      </summary>
                      <Button
                        className="mt-2"
                        variant="secondary"
                        onClick={() => process.mutate(message.id)}
                        disabled={process.isPending}
                      >
                        Retry analysis
                      </Button>
                    </details>
                  ) : message.processing_status === 'NEEDS_REVIEW' ? (
                    <span className="text-slate-500">Review unavailable</span>
                  ) : message.processing_status === 'IGNORED' ? (
                    <span className="font-medium text-slate-600">
                      Dismissed
                    </span>
                  ) : (
                    <span className="text-slate-500">Processing…</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {process.error && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {process.error.message}
        </p>
      )}
      <div className="mt-4">
        <Pagination
          page={messagePage.page}
          pages={messagePage.pages}
          onPageChange={setPage}
          label="Ingested carrier message pagination"
        />
      </div>
    </div>
  )
}

function ConnectionCard({
  connection,
  isManager,
}: {
  connection: GmailConnection
  isManager: boolean
}) {
  const queryClient = useQueryClient()
  const [syncResult, setSyncResult] = useState<GmailSyncResult | null>(null)
  const [messagesOpen, setMessagesOpen] = useState(false)
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['gmail-connections'] })
  }
  const sync = useMutation({
    mutationFn: () => syncGmailConnection(connection.id),
    onSuccess: async (result) => {
      setSyncResult(result)
      await refresh()
    },
  })
  const reconnect = useMutation({
    mutationFn: () => startGmailOAuth(connection.id),
    onSuccess: ({ authorization_url }) => redirectToOAuth(authorization_url),
  })
  const disconnect = useMutation({
    mutationFn: () => disconnectGmailConnection(connection.id),
    onSuccess: refresh,
  })
  const actionError = sync.error ?? reconnect.error ?? disconnect.error
  return (
    <article className="surface-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
            <Mail className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-semibold">{connection.gmail_address}</h2>
              <StatusBadge status={connection.status} />
            </div>
            {isManager ? (
              <div className="mt-3 flex items-center gap-2 border-l-2 border-blue-500 pl-3 text-sm">
                <Avatar user={connection.owner} size="sm" />
                <p>
                  <span className="text-[0.65rem] font-bold tracking-wide text-blue-700 uppercase">
                    Connected agent
                  </span>
                  <br />
                  <span className="font-semibold text-slate-900">
                    {connection.owner.full_name}
                  </span>
                  <br />
                  <span className="text-xs text-slate-500">
                    {connection.owner.email}
                  </span>
                </p>
              </div>
            ) : (
              <p className="mt-1 text-sm text-slate-500">
                Connected {formatDate(connection.connected_at)}
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {!isManager &&
            connection.is_owner &&
            connection.status !== 'DISCONNECTED' &&
            (connection.status !== 'CONNECTED' ||
              !connection.can_apply_workflow_labels) && (
              <Button
                variant="secondary"
                onClick={() => reconnect.mutate()}
                disabled={reconnect.isPending || disconnect.isPending}
              >
                <PlugZap className="h-4 w-4" aria-hidden />
                {reconnect.isPending
                  ? 'Opening Google…'
                  : connection.can_apply_workflow_labels
                    ? 'Reconnect'
                    : 'Upgrade permissions'}
              </Button>
            )}
          {(connection.is_owner || isManager) &&
            (connection.status === 'CONNECTED' ||
              connection.status === 'ERROR') && (
              <Button
                variant="secondary"
                onClick={() => sync.mutate()}
                disabled={sync.isPending || disconnect.isPending}
              >
                <RefreshCw
                  className={`h-4 w-4 ${sync.isPending ? 'animate-spin' : ''}`}
                  aria-hidden
                />
                {sync.isPending ? 'Syncing…' : 'Sync now'}
              </Button>
            )}
          {!isManager &&
            connection.is_owner &&
            connection.status !== 'DISCONNECTED' && (
              <Button
                variant="danger"
                onClick={() => {
                  if (
                    window.confirm(
                      'Disconnect this inbox?\n\nCarrier Hub will stop monitoring new emails from this account. Existing cases, tasks, messages and audit history will be preserved.',
                    )
                  )
                    disconnect.mutate()
                }}
                disabled={disconnect.isPending || sync.isPending}
              >
                <Unplug className="h-4 w-4" aria-hidden />
                {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
              </Button>
            )}
        </div>
      </div>
      <p className="mt-4 text-sm text-slate-600">
        Monitoring and analysis run automatically for approved carrier messages.
      </p>
      <dl className="mt-5 grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-slate-500">Last successful sync</dt>
          <dd className="mt-1 font-medium">
            {formatDate(connection.last_successful_sync_at)}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Last sync attempt</dt>
          <dd className="mt-1 font-medium">
            {formatDate(connection.last_attempted_sync_at)}
          </dd>
        </div>
      </dl>
      {connection.can_apply_workflow_labels &&
      (connection.pending_label_sync_count > 0 ||
        connection.failed_label_sync_count > 0) ? (
        <p className="mt-4 border border-green-200 bg-green-50 p-3 text-sm text-green-950">
          Workflow labels ready · {connection.pending_label_sync_count} pending
          · {connection.failed_label_sync_count} need attention
        </p>
      ) : !connection.can_apply_workflow_labels ? (
        <p className="mt-4 border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          Connected for ingestion. Workflow labels require a permission upgrade.
          {connection.is_owner
            ? ' Use Upgrade permissions above.'
            : ' The mailbox owner must reconnect.'}
        </p>
      ) : null}
      {connection.status === 'NEEDS_REAUTH' && (
        <p className="mt-4 border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          Google authorization is no longer valid. Reconnect this inbox.
        </p>
      )}
      {connection.status === 'ERROR' && (
        <p className="mt-4 border border-red-200 bg-red-50 p-3 text-sm text-red-950">
          Gmail sync needs attention.{' '}
          {connection.last_error_summary ?? 'Try syncing again.'}
        </p>
      )}
      {syncResult && (
        <p className="mt-4 border border-green-200 bg-green-50 p-3 text-sm text-green-950">
          Sync complete: {syncResult.ingested} ingested,{' '}
          {syncResult.already_ingested} already present,{' '}
          {syncResult.skipped_unapproved} unapproved skipped.
        </p>
      )}
      {actionError && (
        <p className="mt-4 text-sm text-red-700" role="alert">
          {actionError.message}
        </p>
      )}
      <details
        className="mt-4 border-t border-slate-200 pt-4"
        onToggle={(event) => setMessagesOpen(event.currentTarget.open)}
      >
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">
          Ingested carrier messages
        </summary>
        {messagesOpen && <RecentMessages connectionId={connection.id} />}
      </details>
    </article>
  )
}

export function GmailConnectionsPage() {
  const auth = useCurrentUser()
  const [searchParams, setSearchParams] = useSearchParams()
  const [oauthResult] = useState(() => searchParams.get('oauth'))
  const [page, setPage] = useState(1)
  useEffect(() => {
    if (searchParams.has('oauth')) setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams])
  const connections = useQuery({
    queryKey: ['gmail-connections', page],
    queryFn: () => getGmailConnections(page),
  })
  const connect = useMutation({
    mutationFn: () => startGmailOAuth(),
    onSuccess: ({ authorization_url }) => redirectToOAuth(authorization_url),
  })
  if (connections.isPending)
    return <LoadingState label="Loading Gmail connection health…" />
  if (connections.isError)
    return (
      <ErrorState
        message={connections.error.message}
        retry={() => connections.refetch()}
      />
    )
  const feedback = oauthResult ? oauthMessages[oauthResult] : null
  const isManager = auth.data!.user.role === 'MANAGER'
  const activeConnections = connections.data.connections.filter(
    (connection) => connection.status !== 'DISCONNECTED',
  )
  return (
    <div className="app-page space-y-6">
      <PageHeader
        title="Gmail Connections"
        description={
          isManager
            ? 'Monitor agency Gmail connections, synchronization health, and workflow-label delivery.'
            : 'Connect once. Carrier Hub automatically monitors approved carrier messages, creates work, and keeps Gmail workflow labels in sync.'
        }
        action={
          !isManager ? (
            <Button
              onClick={() => connect.mutate()}
              disabled={!connections.data.configured || connect.isPending}
              title={
                connections.data.configured
                  ? undefined
                  : 'Google OAuth is not configured'
              }
            >
              <PlugZap className="h-4 w-4" aria-hidden />
              {connect.isPending ? 'Opening Google…' : 'Connect Gmail'}
            </Button>
          ) : undefined
        }
      />
      {feedback && (
        <p className={`border p-4 text-sm ${feedback.tone}`} role="status">
          {feedback.message}
        </p>
      )}
      {!connections.data.configured && (
        <div className="border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <strong>Gmail integration is not configured.</strong> Add the Google
          OAuth client ID, client secret, and a dedicated token-encryption key
          to the ignored backend environment file.
        </div>
      )}
      {connect.error && (
        <p className="text-sm text-red-700" role="alert">
          {connect.error.message}
        </p>
      )}
      {activeConnections.length === 0 ? (
        <EmptyState
          title="No Gmail inbox connected"
          description={
            isManager
              ? 'No active agent Gmail connections are available for agency monitoring.'
              : connections.data.configured
                ? 'Connect your Gmail inbox to monitor approved carrier communications and synchronize workflow labels.'
                : 'Google OAuth must be configured locally before an inbox can be connected.'
          }
        />
      ) : (
        <div className="space-y-5">
          {activeConnections.map((connection) => (
            <ConnectionCard
              key={connection.id}
              connection={connection}
              isManager={isManager}
            />
          ))}
        </div>
      )}
      {connections.data.page && (
        <Pagination
          page={connections.data.page.page}
          pages={connections.data.page.pages}
          onPageChange={setPage}
          label="Gmail connection pagination"
        />
      )}
      {isManager && (
        <p className="text-xs text-slate-500">
          Managers can monitor and sync agency connections. Gmail authorization
          and disconnect remain Agent-owned.
        </p>
      )}
    </div>
  )
}
