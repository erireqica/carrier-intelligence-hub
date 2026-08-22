import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import {
  ErrorState,
  LoadingState,
  Metric,
  PageHeader,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { formatDate } from '../lib/format'
import { getDashboard } from '../lib/api'

export function DashboardPage() {
  const auth = useCurrentUser()
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: getDashboard })
  if (dashboard.isPending)
    return <LoadingState label="Loading operational overview…" />
  if (dashboard.isError)
    return (
      <ErrorState
        message={dashboard.error.message}
        retry={() => dashboard.refetch()}
      />
    )
  const data = dashboard.data

  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow={
          auth.data!.user.role === 'MANAGER'
            ? 'Agency overview'
            : 'My workspace'
        }
        title={`Good day, ${auth.data!.user.full_name.split(' ')[0]}`}
        description="Prioritized operational work from your carrier communications and assigned follow-up."
      />
      {data.gmail_health === 'NEEDS_ATTENTION' && (
        <div className="border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <strong>Gmail connection needs attention.</strong> Automatic carrier
          monitoring is paused until the inbox is reconnected.
        </div>
      )}
      {data.gmail_health === 'NOT_CONNECTED' && (
        <div className="border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <strong>No Gmail inbox connected.</strong> Automatic carrier
          monitoring is inactive. Existing cases, tasks, and history remain
          available.
        </div>
      )}
      <section
        className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6"
        aria-label="Operational metrics"
      >
        <Metric
          label="Urgent cases"
          value={data.metrics.urgent_cases}
          attention
        />
        <Metric label="Open tasks" value={data.metrics.open_tasks} />
        <Metric
          label="Overdue tasks"
          value={data.metrics.overdue_tasks}
          attention
        />
        <Metric label="Needs review" value={data.metrics.review_items} />
        <Metric
          label="Failures"
          value={data.metrics.processing_failures}
          attention
        />
        <Metric label="Processed" value={data.metrics.processed_messages} />
      </section>
      {auth.data!.user.role === 'MANAGER' && (
        <section className="border border-slate-200 bg-white">
          <div className="border-b border-slate-200 px-5 py-4">
            <h2 className="font-semibold">Pipeline health</h2>
            <p className="mt-1 text-sm text-slate-500">
              Agency-wide processing and Gmail workflow-label delivery.
            </p>
          </div>
          <div className="grid gap-px bg-slate-200 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Received backlog"
              value={data.metrics.received_backlog}
            />
            <Metric
              label="Processing"
              value={data.metrics.processing_messages}
            />
            <Metric
              label="Retries scheduled"
              value={data.metrics.retry_scheduled}
            />
            <Metric
              label="Failed attention"
              value={data.metrics.failed_requiring_attention}
              attention
            />
            <Metric
              label="Labels pending"
              value={data.metrics.gmail_labels_pending}
            />
            <Metric
              label="Label attention"
              value={data.metrics.gmail_labels_requiring_attention}
              attention
            />
            <Metric
              label="Gmail attention"
              value={data.metrics.gmail_connections_needing_attention}
              attention
            />
            <Metric
              label="Oldest work"
              value={
                data.metrics.oldest_unprocessed_age_seconds === null
                  ? '—'
                  : `${Math.floor(data.metrics.oldest_unprocessed_age_seconds / 60)}m`
              }
            />
          </div>
        </section>
      )}
      {auth.data!.user.role === 'MANAGER' && data.workload.length > 0 && (
        <section className="border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
            <h2 className="font-semibold">Agent workload</h2>
            <Link
              className="text-sm font-semibold text-blue-700"
              to="/manager/agents"
            >
              View agents
            </Link>
          </div>
          <div className="grid divide-y divide-slate-100 sm:grid-cols-2 sm:divide-x sm:divide-y-0 lg:grid-cols-3">
            {data.workload.map((item) => (
              <div
                key={item.agent.id}
                className="flex items-center justify-between px-5 py-4"
              >
                <div>
                  <p className="font-medium">{item.agent.full_name}</p>
                  <p className="text-xs text-slate-500">{item.agent.email}</p>
                </div>
                <span className="text-2xl font-semibold">
                  {item.open_tasks}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <div className="self-start border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
            <h2 className="font-semibold">Recent cases</h2>
            <Link className="text-sm font-semibold text-blue-700" to="/cases">
              View all
            </Link>
          </div>
          {data.recent_cases.length ? (
            <div className="divide-y divide-slate-100">
              {data.recent_cases.map((item) => (
                <Link
                  key={item.id}
                  to={`/cases/${item.id}`}
                  className="grid gap-2 px-5 py-4 hover:bg-slate-50 sm:grid-cols-[1fr_auto]"
                >
                  <div>
                    <p className="font-medium text-slate-950">
                      {item.client_name}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      {item.carrier.name} ·{' '}
                      {item.policy_number ?? 'Policy number pending'}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <PriorityBadge priority={item.priority} />
                    <StatusBadge status={item.policy_status} />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <p className="px-5 py-4 text-sm text-slate-600">
              No cases yet. Approved carrier messages will appear here after
              processing.
            </p>
          )}
        </div>
        <div className="border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
            <h2 className="font-semibold">Recent activity</h2>
            <Link
              className="text-sm font-semibold text-blue-700"
              to={
                auth.data!.user.role === 'MANAGER'
                  ? '/manager/system-logs'
                  : '/activity'
              }
            >
              View all
            </Link>
          </div>
          <div className="divide-y divide-slate-100">
            {data.recent_activity.map((event) => (
              <div key={event.id} className="px-5 py-4">
                <p className="text-sm font-medium text-slate-800">
                  {event.description}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {formatDate(event.created_at)} ·{' '}
                  {event.event_type.replaceAll('_', ' ')}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
