import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  ClipboardCheck,
  Clock3,
  MailCheck,
  MailX,
  Radar,
  ShieldCheck,
  UsersRound,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import { Avatar } from '../components/Avatar'
import {
  ErrorState,
  LoadingState,
  PageHeader,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { getDashboard } from '../lib/api'
import { formatDate } from '../lib/format'
import { getEffectiveTimezone } from '../lib/timezone'

function AttentionItem({
  label,
  value,
  note,
  to,
  tone = 'default',
}: {
  label: string
  value: number
  note: string
  to: string
  tone?: 'default' | 'danger' | 'warning'
}) {
  const tones = {
    default: 'bg-blue-50 text-blue-700',
    danger: 'bg-red-50 text-red-700',
    warning: 'bg-amber-50 text-amber-700',
  }
  return (
    <Link
      to={to}
      className="group flex min-w-0 items-center gap-4 px-5 py-5 hover:bg-slate-50/80"
    >
      <span
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-lg font-semibold ${tones[tone]}`}
      >
        {value}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold text-slate-900">{label}</span>
        <span className="mt-0.5 block text-xs text-slate-500">{note}</span>
      </span>
      <ArrowRight
        className="h-4 w-4 shrink-0 text-slate-300 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-600"
        aria-hidden
      />
    </Link>
  )
}

function PipelineStat({
  label,
  value,
  attention = false,
}: {
  label: string
  value: string | number
  attention?: boolean
}) {
  return (
    <div className="relative min-w-0 px-4 py-4">
      <dt className="text-[0.67rem] font-bold tracking-[0.08em] text-slate-500 uppercase">
        {label}
      </dt>
      <dd
        className={`mt-2 text-xl font-semibold tracking-tight ${attention && value !== 0 ? 'text-red-700' : 'text-slate-950'}`}
      >
        {value}
      </dd>
    </div>
  )
}

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
  const isManager = auth.data!.user.role === 'MANAGER'
  const timezone = getEffectiveTimezone(auth.data?.user)
  const decisionCount =
    data.metrics.urgent_cases +
    data.metrics.overdue_tasks +
    data.metrics.review_items
  const operationsAttentionCount =
    decisionCount + data.metrics.failed_requiring_attention
  const pipelineHealthy =
    data.metrics.failed_requiring_attention === 0 &&
    data.metrics.gmail_labels_requiring_attention === 0 &&
    data.metrics.gmail_connections_needing_attention === 0
  const pipelineQueueCount =
    data.metrics.received_backlog +
    data.metrics.processing_messages +
    data.metrics.retry_scheduled +
    data.metrics.failed_requiring_attention +
    data.metrics.gmail_labels_pending +
    data.metrics.gmail_labels_requiring_attention +
    data.metrics.gmail_connections_needing_attention
  const maxWorkload = Math.max(
    1,
    ...data.workload.map((item) => item.open_tasks),
  )

  return (
    <div className="app-page space-y-6">
      <PageHeader
        eyebrow={isManager ? 'Agency command center' : 'Agent workspace'}
        title={`Good day, ${auth.data!.user.full_name.split(' ')[0]}`}
        description={
          isManager
            ? 'A prioritized view of carrier activity, operational risk, and agency work requiring a decision.'
            : 'Your policy follow-ups, carrier activity, and review work—organized for the day ahead.'
        }
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

      {isManager ? (
        <section className="dashboard-hero overflow-hidden rounded-2xl bg-[#12243c] text-white shadow-[0_18px_46px_rgb(15_23_42/14%)]">
          <div className="relative overflow-hidden px-6 py-7 sm:px-8 sm:py-9">
            <span className="absolute -top-24 -right-20 h-72 w-72 rounded-full border border-white/10" />
            <span className="absolute top-16 right-12 h-24 w-24 rounded-full border border-blue-300/10" />
            <div className="relative flex h-full flex-col justify-between gap-8">
              <div className="flex items-center gap-2 text-xs font-bold tracking-[0.16em] text-blue-200 uppercase">
                {pipelineHealthy ? (
                  <ShieldCheck className="h-4 w-4" aria-hidden />
                ) : (
                  <Radar className="h-4 w-4" aria-hidden />
                )}
                Live agency operations
              </div>
              <div>
                <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
                  <p className="text-3xl font-semibold tracking-tight sm:text-4xl">
                    {pipelineHealthy
                      ? 'Operations are running smoothly'
                      : 'Operations require attention'}
                  </p>
                  <span
                    className={`mb-1 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
                      pipelineHealthy
                        ? 'bg-emerald-400/15 text-emerald-200'
                        : 'bg-amber-400/15 text-amber-200'
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${pipelineHealthy ? 'bg-emerald-300' : 'bg-amber-300'}`}
                    />
                    {pipelineHealthy ? 'Healthy' : 'Attention'}
                  </span>
                </div>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                  {operationsAttentionCount
                    ? `${operationsAttentionCount} items currently require prioritization across cases, tasks, reviews, and processing.`
                    : 'No urgent exceptions are waiting. Continue with the open work queue below.'}
                </p>
              </div>
            </div>
          </div>
          <div className="grid border-t border-white/10 bg-white/[0.035] sm:grid-cols-3 2xl:border-t-0 2xl:border-l">
            {(
              [
                [data.metrics.open_tasks, 'Open tasks', ClipboardCheck],
                [data.metrics.processed_messages, 'Processed', CheckCircle2],
                [
                  data.gmail_health === 'CONNECTED' ? 'Online' : 'Attention',
                  'Gmail monitoring',
                  MailCheck,
                ],
              ] as const
            ).map(([value, label, Icon]) => (
              <div
                key={label}
                className="flex items-center gap-3 border-white/10 p-5 sm:border-r sm:last:border-r-0 2xl:border-r-0 2xl:border-b 2xl:last:border-b-0"
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/8 text-blue-200">
                  <Icon className="h-[18px] w-[18px]" aria-hidden />
                </span>
                <div>
                  <p className="text-xl font-semibold">{value}</p>
                  <p className="text-xs text-slate-400">{label}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-[0_14px_40px_rgb(15_23_42/7%)]">
          <div className="grid lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <div className="relative overflow-hidden p-6 sm:p-8">
              <span className="absolute -top-20 -right-20 h-56 w-56 rounded-full bg-blue-50" />
              <div className="relative">
                <div className="flex items-center gap-2 text-xs font-bold tracking-[0.16em] text-blue-700 uppercase">
                  <ClipboardCheck className="h-4 w-4" aria-hidden />{' '}
                  Today&apos;s workload
                </div>
                <h2 className="mt-4 max-w-2xl text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">
                  Your active work, at a glance
                </h2>
                <p className="mt-2 max-w-xl text-sm leading-6 text-slate-600">
                  Track the tasks already underway and the follow-ups coming due
                  across your assigned policies.
                </p>
              </div>
            </div>
            <dl className="grid grid-cols-3 border-t border-slate-100 bg-slate-50/70 lg:min-w-[360px] lg:border-t-0 lg:border-l">
              {[
                ['Active tasks', data.metrics.open_tasks],
                ['In progress', data.metrics.in_progress_tasks],
                ['Due soon', data.metrics.due_soon_tasks],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="border-r border-slate-100 px-4 py-5 text-center last:border-r-0 lg:py-8"
                >
                  <dd className="text-2xl font-semibold tracking-tight text-slate-950">
                    {value}
                  </dd>
                  <dt className="mt-1 text-[0.65rem] font-bold tracking-wider text-slate-500 uppercase">
                    {label}
                  </dt>
                </div>
              ))}
            </dl>
          </div>
        </section>
      )}

      <section className="surface-panel" aria-label="Operational priorities">
        <div className="section-titlebar">
          <div>
            <p className="text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
              Attention queue
            </p>
            <h2 className="mt-1 font-semibold text-slate-950">
              Work requiring a decision
            </h2>
          </div>
          <span className="text-xs font-semibold text-slate-500">
            {decisionCount} total
          </span>
        </div>
        <div className="grid divide-y divide-slate-100 md:grid-cols-3 md:divide-x md:divide-y-0">
          <AttentionItem
            label="Urgent cases"
            value={data.metrics.urgent_cases}
            note="High-priority policy work"
            to="/cases"
            tone="danger"
          />
          <AttentionItem
            label="Overdue tasks"
            value={data.metrics.overdue_tasks}
            note="Past their due date"
            to="/tasks"
            tone="warning"
          />
          <AttentionItem
            label="Needs review"
            value={data.metrics.review_items}
            note="Awaiting human verification"
            to="/reviews"
          />
        </div>
      </section>

      {isManager && (
        <section className="surface-panel">
          <div className="section-titlebar">
            <div>
              <p className="text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
                Automation pipeline
              </p>
              <h2 className="mt-1 font-semibold">Pipeline health</h2>
              <p className="mt-1 text-xs text-slate-500">
                {pipelineQueueCount === 0
                  ? 'All processing and label queues are currently clear.'
                  : `${pipelineQueueCount} items are active or awaiting pipeline attention.`}
              </p>
            </div>
            <span
              className={`flex items-center gap-2 text-xs font-semibold ${pipelineHealthy ? 'text-emerald-700' : 'text-amber-700'}`}
            >
              <span
                className={`h-2 w-2 rounded-full ${pipelineHealthy ? 'bg-emerald-500' : 'bg-amber-500'}`}
              />{' '}
              {pipelineQueueCount === 0 ? 'Queues clear' : 'Live status'}
            </span>
          </div>
          <div className="grid grid-cols-2 divide-x divide-y divide-slate-100 sm:grid-cols-4 xl:grid-cols-8 xl:divide-y-0">
            <PipelineStat
              label="Received"
              value={data.metrics.received_backlog}
            />
            <PipelineStat
              label="Processing"
              value={data.metrics.processing_messages}
            />
            <PipelineStat
              label="Retry queue"
              value={data.metrics.retry_scheduled}
            />
            <PipelineStat
              label="Failed"
              value={data.metrics.failed_requiring_attention}
              attention
            />
            <PipelineStat
              label="Labels queued"
              value={data.metrics.gmail_labels_pending}
            />
            <PipelineStat
              label="Label attention"
              value={data.metrics.gmail_labels_requiring_attention}
              attention
            />
            <PipelineStat
              label="Gmail attention"
              value={data.metrics.gmail_connections_needing_attention}
              attention
            />
            <PipelineStat
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

      {isManager && data.workload.length > 0 && (
        <section className="surface-panel">
          <div className="section-titlebar">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                <UsersRound className="h-[18px] w-[18px]" aria-hidden />
              </span>
              <div>
                <h2 className="font-semibold">Agent workload</h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  Open tasks by owner
                </p>
              </div>
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
          <div className="grid divide-y divide-slate-100 lg:grid-cols-2 lg:divide-x lg:divide-y-0">
            {data.workload.map((item) => (
              <div key={item.agent.id} className="px-5 py-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex min-w-0 items-center gap-3">
                    <Avatar user={item.agent} />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {item.agent.full_name}
                      </p>
                      <p className="truncate text-xs text-slate-500">
                        {item.agent.email}
                      </p>
                    </div>
                  </div>
                  <span className="text-xl font-semibold text-slate-950">
                    {item.open_tasks}
                  </span>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-blue-600"
                    style={{
                      width: `${(item.open_tasks / maxWorkload) * 100}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,0.8fr)]">
        <div className="surface-panel self-start">
          <div className="section-titlebar">
            <div>
              <p className="text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
                Portfolio movement
              </p>
              <h2 className="mt-1 font-semibold">Recent cases</h2>
            </div>
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
                  className="group grid gap-3 px-5 py-4 hover:bg-slate-50/80 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                      <CircleDot className="h-4 w-4" aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-950">
                        {item.client_name}
                      </p>
                      <p className="mt-0.5 truncate text-sm text-slate-500">
                        {item.carrier.name} ·{' '}
                        {item.policy_number ?? 'Policy number pending'}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 pl-12 sm:pl-0">
                    <PriorityBadge priority={item.priority} />
                    <StatusBadge status={item.policy_status} />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <p className="px-5 py-5 text-sm text-slate-600">
              No cases yet. Approved carrier messages will appear here after
              processing.
            </p>
          )}
        </div>
        <div className="surface-panel">
          <div className="section-titlebar">
            <div>
              <p className="text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
                Live record
              </p>
              <h2 className="mt-1 font-semibold">Recent activity</h2>
            </div>
            <Link
              className="text-sm font-semibold text-blue-700"
              to={isManager ? '/manager/system-logs' : '/activity'}
            >
              <span className="inline-flex items-center gap-1">
                View all <ChevronRight className="h-4 w-4" aria-hidden />
              </span>
            </Link>
          </div>
          <div className="px-5 py-2">
            {data.recent_activity.map((event, index) => (
              <div key={event.id} className="relative py-4 pl-7">
                {index < data.recent_activity.length - 1 && (
                  <span className="absolute top-7 bottom-0 left-[3px] w-px bg-slate-200" />
                )}
                <span className="absolute top-5 left-0 h-2 w-2 rounded-full bg-blue-600 ring-4 ring-blue-50" />
                <p className="text-sm font-medium leading-5 text-slate-800">
                  {event.description}
                </p>
                <p className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
                  <Clock3 className="h-3 w-3" aria-hidden />
                  {formatDate(event.created_at, timezone)} ·{' '}
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
