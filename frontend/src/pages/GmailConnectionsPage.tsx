import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

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
  redirectToOAuth,
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
    message: 'The required Gmail read permission was not granted.',
  },
  failed: {
    tone: 'border-red-300 bg-red-50 text-red-950',
    message: 'Gmail authorization could not be completed. Please try again.',
  },
}

function RecentMessages({ connectionId }: { connectionId: number }) {
  const messages = useQuery({
    queryKey: ['gmail-connections', connectionId, 'messages'],
    queryFn: () => getGmailMessages(connectionId),
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
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
          <tr>
            <th className="px-3 py-2">Received</th>
            <th className="px-3 py-2">Carrier</th>
            <th className="px-3 py-2">Sender</th>
            <th className="px-3 py-2">Subject</th>
            <th className="px-3 py-2">State</th>
            <th className="px-3 py-2">Attachments</th>
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
              </td>
              <td className="px-3 py-3">{message.attachment_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ConnectionCard({ connection }: { connection: GmailConnection }) {
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
  const actionError = sync.error ?? reconnect.error ?? disconnect.error
  return (
    <article className="border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-semibold">{connection.gmail_address}</h2>
            <StatusBadge status={connection.status} />
          </div>
          <p className="mt-1 text-sm text-slate-500">
            Owner: {connection.owner.full_name} · Connected{' '}
            {formatDate(connection.connected_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
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
          {connection.is_owner && connection.status !== 'CONNECTED' && (
            <Button
              variant="secondary"
              onClick={() => reconnect.mutate()}
              disabled={reconnect.isPending || disconnect.isPending}
            >
              {reconnect.isPending ? 'Opening Google…' : 'Reconnect'}
            </Button>
          )}
          {connection.is_owner && connection.status !== 'DISCONNECTED' && (
            <Button
              variant="danger"
              onClick={() => disconnect.mutate()}
              disabled={disconnect.isPending || sync.isPending}
            >
              {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
            </Button>
          )}
        </div>
      </div>
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
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Mailbox monitoring"
        title="Gmail Connections"
        description="Google OAuth grants read-only access. The separate poller ingests only unread messages whose sender matches the agency whitelist."
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
      {connections.data.connections.length === 0 ? (
        <EmptyState
          title="No Gmail inbox connected"
          description={
            connections.data.configured
              ? 'Connect your Gmail inbox to begin read-only monitoring of approved carrier communications.'
              : 'Google OAuth must be configured locally before an inbox can be connected.'
          }
        />
      ) : (
        <div className="space-y-5">
          {connections.data.connections.map((connection) => (
            <ConnectionCard key={connection.id} connection={connection} />
          ))}
        </div>
      )}
      {auth.data!.user.role === 'MANAGER' && (
        <p className="text-xs text-slate-500">
          Managers can view and sync agency connections. Reconnect and
          disconnect remain restricted to the mailbox owner.
        </p>
      )}
    </div>
  )
}
