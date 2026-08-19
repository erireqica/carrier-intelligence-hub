import { useQuery } from '@tanstack/react-query'

import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from '../components/ui'
import { getGmailConnections } from '../lib/api'

export function GmailConnectionsPage() {
  const connections = useQuery({
    queryKey: ['gmail-connections'],
    queryFn: getGmailConnections,
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
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Mailbox monitoring"
        title="Gmail Connections"
        description="Authorized inboxes will be monitored independently through Google OAuth in the next integration stage."
      />
      {connections.data.length === 0 ? (
        <EmptyState
          title="No Gmail inbox connected"
          description="Connect a Gmail inbox to begin automatically processing approved carrier communications."
          action={
            <Button disabled title="Google OAuth is not configured yet">
              Connect Gmail — integration not configured
            </Button>
          }
        />
      ) : (
        <p>{connections.data.length} connection(s)</p>
      )}
    </div>
  )
}
