import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
} from '../components/ui'
import { formatDate } from '../lib/format'
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
  PENDING: 'Labels pending',
  PROCESSING: 'Labels syncing',
  RETRY_WAIT: 'Label retry scheduled',
  NEEDS_PERMISSION: 'Permission upgrade required',
  FAILED: 'Label sync failed',
}

function RecentMessages({ connectionId }: { connectionId: number }) {
  const queryClient = useQueryClient()
  const messages = useQuery({
    queryKey: ['gmail-connections', connectionId, 'messages'],
    queryFn: () => getGmailMessages(connectionId),
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
  if (!messages.data.length)
    return (
      <p className="mt-4 text-sm text-slate-500">
        No approved carrier messages have been ingested from this inbox yet.
      </p>
    )
  return (
    <div className="mt-5 overflow-x-auto">
      <h3 className="mb-3 text-sm font-semibold">
        Recent ingested carrier messages
      </h3>
      <table className="w-full min-w-[920px] text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
          <tr>
            <th className="px-3 py-2">Received</th>
            <th className="px-3 py-2">Carrier</th>
            <th className="px-3 py-2">Sender</th>
            <th className="px-3 py-2">Subject</th>
            <th className="px-3 py-2">State</th>
            <th className="px-3 py-2">Gmail workflow</th>
            <th className="px-3 py-2">Attachments</th>
            <th className="px-3 py-2">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {messages.data.map((message) => (
            <tr key={message.id}>
              <td className="px-3 py-3">{formatDate(message.received_at)}</td>
              <td className="px-3 py-3">{message.carrier.name}</td>
              <td className="px-3 py-3">{message.sender}</td>
              <td className="px-3 py-3 font-medium">{message.subject}</td>
              <td className="px-3 py-3">
                <StatusBadge status={message.processing_status} />
                {message.processing_status === 'FAILED' && (
                  <p className="mt-1 max-w-48 text-xs text-slate-500">
                    {message.processing_next_retry_at
                      ? `Automatic retry scheduled after attempt ${message.processing_attempt_count}`
                      : 'Automatic retries exhausted. Manual attention required.'}
                  </p>
                )}
              </td>
              <td className="px-3 py-3 text-xs text-slate-600">
                {message.label_sync_status
                  ? labelSyncText[message.label_sync_status]
                  : 'Not queued'}
              </td>
              <td className="px-3 py-3">{message.attachment_count}</td>
              <td className="px-3 py-3">
                {message.review_id ? (
                  <Link
                    className="font-semibold text-blue-700"
                    to={`/reviews/${message.review_id}`}
                  >
                    Review
                  </Link>
                ) : message.case_id ? (
                  <Link
                    className="font-semibold text-blue-700"
                    to={`/cases/${message.case_id}`}
                  >
                    Open case
                  </Link>
                ) : message.processing_status === 'FAILED' &&
                  message.processing_next_retry_at ? (
                  <span className="text-slate-500">Retry scheduled</span>
                ) : ['RECEIVED', 'FAILED'].includes(
                    message.processing_status,
                  ) ? (
                  <details>
                    <summary className="cursor-pointer text-xs font-semibold text-slate-600">
                      Manual recovery
                    </summary>
                    <Button
                      className="mt-2"
                      variant="secondary"
                      onClick={() => process.mutate(message.id)}
                      disabled={process.isPending}
                    >
                      {process.isPending && process.variables === message.id
                        ? 'Analyzing…'
                        : message.processing_status === 'FAILED'
                          ? 'Retry analysis'
                          : 'Analyze now'}
                    </Button>
                  </details>
                ) : (
                  <span className="text-slate-500">Processing…</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {process.error && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {process.error.message}
        </p>
      )}
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
  const retryLabels = useMutation({
    mutationFn: () => retryGmailWorkflowLabels(connection.id),
    onSuccess: refresh,
  })
  const actionError =
    sync.error ?? reconnect.error ?? retryLabels.error ?? disconnect.error
  return (
    <article className="border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-semibold">{connection.gmail_address}</h2>
            <StatusBadge status={connection.status} />
          </div>
          {isManager ? (
            <p className="mt-2 border-l-2 border-blue-500 pl-3 text-sm">
              <span className="font-semibold text-slate-900">
                Connected agent
              </span>
              <br />
              {connection.owner.full_name} · {connection.owner.email}
            </p>
          ) : (
            <p className="mt-1 text-sm text-slate-500">
              Connected {formatDate(connection.connected_at)}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {connection.is_owner &&
            connection.status !== 'DISCONNECTED' &&
            (connection.status !== 'CONNECTED' ||
              !connection.can_apply_workflow_labels) && (
              <Button
                variant="secondary"
                onClick={() => reconnect.mutate()}
                disabled={reconnect.isPending || disconnect.isPending}
              >
                {reconnect.isPending
                  ? 'Opening Google…'
                  : connection.can_apply_workflow_labels
                    ? 'Reconnect'
                    : 'Upgrade permissions'}
              </Button>
            )}
          {connection.is_owner && connection.status !== 'DISCONNECTED' && (
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
      {connection.can_apply_workflow_labels ? (
        <p className="mt-4 border border-green-200 bg-green-50 p-3 text-sm text-green-950">
          Workflow labels ready · {connection.pending_label_sync_count} pending
          · {connection.failed_label_sync_count} need attention
        </p>
      ) : (
        <p className="mt-4 border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          Connected for ingestion. Workflow labels require a permission upgrade.
          {connection.is_owner
            ? ' Use Upgrade permissions above.'
            : ' The mailbox owner must reconnect.'}
        </p>
      )}
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
      <details className="mt-4 border-t border-slate-200 pt-4">
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">
          Troubleshooting and manual recovery
        </summary>
        <div className="mt-3 flex flex-wrap gap-2">
          {(connection.status === 'CONNECTED' ||
            connection.status === 'ERROR') && (
            <Button
              variant="secondary"
              onClick={() => sync.mutate()}
              disabled={sync.isPending || disconnect.isPending}
            >
              {sync.isPending ? 'Syncing…' : 'Sync now'}
            </Button>
          )}
          {connection.can_apply_workflow_labels &&
            (connection.pending_label_sync_count > 0 ||
              connection.failed_label_sync_count > 0) && (
              <Button
                variant="secondary"
                onClick={() => retryLabels.mutate()}
                disabled={retryLabels.isPending}
              >
                {retryLabels.isPending
                  ? 'Queuing labels…'
                  : 'Retry workflow labels'}
              </Button>
            )}
        </div>
      </details>
      <RecentMessages connectionId={connection.id} />
    </article>
  )
}

export function GmailConnectionsPage() {
  const auth = useCurrentUser()
  const [searchParams, setSearchParams] = useSearchParams()
  const [oauthResult] = useState(() => searchParams.get('oauth'))
  useEffect(() => {
    if (searchParams.has('oauth')) setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams])
  const connections = useQuery({
    queryKey: ['gmail-connections'],
    queryFn: getGmailConnections,
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
  const activeConnections = connections.data.connections.filter(
    (connection) => connection.status !== 'DISCONNECTED',
  )
  return (
    <div className="space-y-6">
      <PageHeader
        title="Gmail Connections"
        description="Connect once. Carrier Hub automatically monitors approved carrier messages, creates work, and keeps Gmail workflow labels in sync."
        action={
          <Button
            onClick={() => connect.mutate()}
            disabled={!connections.data.configured || connect.isPending}
            title={
              connections.data.configured
                ? undefined
                : 'Google OAuth is not configured'
            }
          >
            {connect.isPending ? 'Opening Google…' : 'Connect Gmail'}
          </Button>
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
            connections.data.configured
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
              isManager={auth.data!.user.role === 'MANAGER'}
            />
          ))}
        </div>
      )}
      {auth.data!.user.role === 'MANAGER' && (
        <p className="text-xs text-slate-500">
          Managers can view, sync, and retry managed-label delivery for agency
          connections. OAuth reconnect and disconnect remain restricted to the
          mailbox owner.
        </p>
      )}
    </div>
  )
}
