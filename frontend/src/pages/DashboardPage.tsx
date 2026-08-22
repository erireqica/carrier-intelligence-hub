import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronRight, MailX, UsersRound } from 'lucide-react'
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
    <div className="app-page space-y-7">
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
        <div className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
          <p>
            <strong>Gmail connection needs attention.</strong> Automatic carrier
            monitoring is paused until the inbox is reconnected.
          </p>
        </div>
      )}
      {data.gmail_health === 'NOT_CONNECTED' && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <MailX className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
          <p>
            <strong>No Gmail inbox connected.</strong> Automatic carrier
            monitoring is inactive. Existing cases, tasks, and history remain
            available.
          </p>
        </div>
      )}
      <section
        className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6"
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
        <section className="surface-panel">
          <div className="section-titlebar">
            <div>
              <h2 className="font-semibold">Pipeline health</h2>
              <p className="mt-1 text-sm text-slate-500">
                Agency-wide processing and Gmail workflow-label delivery.
              </p>
            </div>
            <span className="flex items-center gap-2 text-xs font-semibold text-emerald-700">
              <span className="h-2 w-2 rounded-full bg-emerald-500" /> Live
              status
            </span>
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
        <section className="surface-panel">
          <div className="section-titlebar">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                <UsersRound className="h-[18px] w-[18px]" aria-hidden />
              </span>
              <h2 className="font-semibold">Agent workload</h2>
            </div>
            <Link
              className="text-sm font-semibold text-blue-700"
              to="/manager/agents"
            >
              <span className="inline-flex items-center gap-1">
                View agents <ChevronRight className="h-4 w-4" aria-hidden />
              </span>
            </Link>
          </div>
          <div className="grid divide-y divide-slate-100 sm:grid-cols-2 sm:divide-x sm:divide-y-0 lg:grid-cols-3">
            {data.workload.map((item) => (
              <div
                key={item.agent.id}
                className="flex items-center justify-between px-5 py-4"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-xs font-bold text-slate-700">
                    {item.agent.full_name
                      .split(' ')
                      .map((part) => part[0])
                      .join('')
                      .slice(0, 2)}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {item.agent.full_name}
                    </p>
                    <p className="text-xs text-slate-500">{item.agent.email}</p>
                  </div>
                </div>
                <span className="rounded-lg bg-slate-100 px-3 py-1.5 text-xl font-semibold">
                  {item.open_tasks}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <div className="surface-panel self-start">
          <div className="section-titlebar">
            <h2 className="font-semibold">Recent cases</h2>
            <Link className="text-sm font-semibold text-blue-700" to="/cases">
              <span className="inline-flex items-center gap-1">
                View all <ChevronRight className="h-4 w-4" aria-hidden />
              </span>
            </Link>
          </div>
          {data.recent_cases.length ? (
            <div className="divide-y divide-slate-100">
              {data.recent_cases.map((item) => (
                <Link
                  key={item.id}
                  to={`/cases/${item.id}`}
                  className="group grid gap-2 px-5 py-4 transition hover:bg-blue-50/40 sm:grid-cols-[1fr_auto]"
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
        <div className="surface-panel">
          <div className="section-titlebar">
            <h2 className="font-semibold">Recent activity</h2>
            <Link
              className="text-sm font-semibold text-blue-700"
              to={
                auth.data!.user.role === 'MANAGER'
                  ? '/manager/system-logs'
                  : '/activity'
              }
            >
              <span className="inline-flex items-center gap-1">
                View all <ChevronRight className="h-4 w-4" aria-hidden />
              </span>
            </Link>
          </div>
          <div className="divide-y divide-slate-100">
            {data.recent_activity.map((event) => (
              <div key={event.id} className="relative px-5 py-4 pl-10">
                <span className="absolute top-5 left-5 h-2 w-2 rounded-full bg-blue-500 ring-4 ring-blue-50" />
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
