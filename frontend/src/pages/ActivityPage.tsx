import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowUpRight,
  BriefcaseBusiness,
  ClipboardCheck,
  KeyRound,
  MailCheck,
  SearchCheck,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
} from '../components/ui'
import { getActivity } from '../lib/api'
import { formatDateTime } from '../lib/format'
import { getEffectiveTimezone } from '../lib/timezone'
import type { AuditLog } from '../lib/types'

const actionGroups = [
  ['', 'All actions', Activity],
  ['TASKS', 'Task work', ClipboardCheck],
  ['REVIEWS', 'Reviews', SearchCheck],
  ['CASES', 'Case corrections', BriefcaseBusiness],
  ['GMAIL', 'Gmail connections', MailCheck],
  ['ACCESS', 'Account access', KeyRound],
] as const

const categoryVisuals: Record<
  string,
  { icon: LucideIcon; iconClass: string; railClass: string }
> = {
  TASKS: {
    icon: ClipboardCheck,
    iconClass: 'bg-blue-50 text-blue-700',
    railClass: 'bg-blue-500',
  },
  REVIEWS: {
    icon: SearchCheck,
    iconClass: 'bg-amber-50 text-amber-700',
    railClass: 'bg-amber-500',
  },
  CASES: {
    icon: BriefcaseBusiness,
    iconClass: 'bg-indigo-50 text-indigo-700',
    railClass: 'bg-indigo-500',
  },
  GMAIL: {
    icon: MailCheck,
    iconClass: 'bg-emerald-50 text-emerald-700',
    railClass: 'bg-emerald-500',
  },
  ACCESS: {
    icon: KeyRound,
    iconClass: 'bg-slate-100 text-slate-700',
    railClass: 'bg-slate-500',
  },
}

function visualFor(event: AuditLog) {
  if (event.severity === 'ERROR') {
    return {
      icon: Activity,
      iconClass: 'bg-red-50 text-red-700',
      railClass: 'bg-red-500',
    }
  }
  return (
    categoryVisuals[event.category.toUpperCase()] ?? {
      icon: Activity,
      iconClass: 'bg-blue-50 text-blue-700',
      railClass: 'bg-blue-500',
    }
  )
}

function dayLabel(value: string, timezone: string) {
  return new Date(value).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    timeZone: timezone,
  })
}

function groupByDay(items: AuditLog[], timezone: string) {
  const grouped = new Map<string, AuditLog[]>()
  for (const item of items) {
    const label = dayLabel(item.created_at, timezone)
    grouped.set(label, [...(grouped.get(label) ?? []), item])
  }
  return [...grouped.entries()]
}

export function ActivityPage() {
  const auth = useCurrentUser()
  const [group, setGroup] = useState('')
  const [page, setPage] = useState(1)
  const params = new URLSearchParams({ page_size: '25', page: String(page) })
  if (group) params.set('action_group', group)
  const activity = useQuery({
    queryKey: ['activity', group, page],
    queryFn: () => getActivity(params.toString()),
  })
  if (activity.isPending) return <LoadingState label="Loading your activity…" />
  if (activity.isError)
    return (
      <ErrorState
        message={activity.error.message}
        retry={() => activity.refetch()}
      />
    )
  const timezone = getEffectiveTimezone(auth.data?.user)
  const groupedActivity = groupByDay(activity.data.items, timezone)
  const visibleCategories = Array.from(
    activity.data.items.reduce((counts, item) => {
      counts.set(item.category, (counts.get(item.category) ?? 0) + 1)
      return counts
    }, new Map<string, number>()),
  )

  return (
    <div className="app-page space-y-6">
      <PageHeader
        eyebrow="Personal audit trail"
        title="My Activity"
        description="A traceable history of the case decisions, task updates, reviews, and account actions you have completed."
      />

      <section className="grid overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm lg:grid-cols-[270px_minmax(0,1fr)]">
        <div className="relative overflow-hidden bg-[#12243c] p-6 text-white">
          <span className="absolute -top-16 -right-16 h-44 w-44 rounded-full border border-white/10" />
          <div className="relative">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 text-blue-200">
              <ShieldCheck className="h-5 w-5" aria-hidden />
            </span>
            <p className="mt-6 text-4xl font-semibold tracking-tight">
              {activity.data.page.total}
            </p>
            <p className="mt-1 text-sm font-semibold text-white">
              Recorded actions
            </p>
            <p className="mt-2 text-xs leading-5 text-slate-400">
              Your personal, self-scoped operational history.
            </p>
          </div>
        </div>
        <div className="flex flex-col justify-between gap-5 p-5 sm:p-6">
          <div>
            <p className="text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
              Current view
            </p>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-slate-950">
              {group
                ? actionGroups.find(([value]) => value === group)?.[1]
                : 'Your complete activity stream'}
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {activity.data.items.length} actions visible on this page
            </p>
          </div>
          {visibleCategories.length > 0 && (
            <div
              className="flex flex-wrap gap-2"
              aria-label="Visible activity categories"
            >
              {visibleCategories.map(([category, count]) => (
                <span
                  key={category}
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600"
                >
                  {category} <strong className="text-slate-950">{count}</strong>
                </span>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="filter-toolbar flex flex-wrap items-center gap-3">
        <label
          className="text-sm font-semibold text-slate-700"
          htmlFor="activity-type"
        >
          Action type
        </label>
        <select
          id="activity-type"
          className="px-3 py-2 text-sm"
          value={group}
          onChange={(event) => {
            setGroup(event.target.value)
            setPage(1)
          }}
        >
          {actionGroups.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <div className="ml-auto hidden items-center gap-2 text-xs text-slate-500 sm:flex">
          <ShieldCheck className="h-4 w-4 text-emerald-600" aria-hidden />
          Self-scoped and auditable
        </div>
      </div>

      {activity.data.items.length === 0 ? (
        <EmptyState
          title="No activity found"
          description="Your actions will appear here as you work in Carrier Hub."
        />
      ) : (
        <section className="surface-panel">
          <div className="hidden grid-cols-[210px_1fr_190px] gap-5 border-b border-slate-200 bg-slate-50 px-6 py-3 text-[0.66rem] font-bold tracking-[0.1em] text-slate-500 uppercase sm:grid">
            <span>Action</span>
            <span>Details</span>
            <span>Date</span>
          </div>
          <div className="p-4 sm:p-6">
            {groupedActivity.map(([date, events], groupIndex) => (
              <div key={date} className={groupIndex ? 'mt-7' : ''}>
                <div className="mb-3 flex items-center gap-3">
                  <p className="shrink-0 text-xs font-bold tracking-[0.08em] text-slate-500 uppercase">
                    {date}
                  </p>
                  <span className="h-px flex-1 bg-slate-200" />
                </div>
                <div className="space-y-2">
                  {events.map((event) => {
                    const visual = visualFor(event)
                    const Icon = visual.icon
                    return (
                      <article
                        key={event.id}
                        className="group relative grid gap-3 overflow-hidden rounded-xl border border-slate-200 bg-white p-4 pl-5 transition hover:border-slate-300 hover:shadow-md hover:shadow-slate-900/[0.04] sm:grid-cols-[190px_1fr_170px] sm:items-start sm:gap-5"
                      >
                        <span
                          className={`absolute inset-y-0 left-0 w-1 ${visual.railClass}`}
                        />
                        <div className="flex items-center gap-3">
                          <span
                            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${visual.iconClass}`}
                          >
                            <Icon className="h-[18px] w-[18px]" aria-hidden />
                          </span>
                          <div className="min-w-0">
                            <p className="font-semibold text-slate-900">
                              {event.event_label}
                            </p>
                            <p className="mt-0.5 text-[0.65rem] font-bold tracking-wider text-slate-400 uppercase">
                              {event.category}
                            </p>
                          </div>
                        </div>
                        <div>
                          <p className="text-[0.95rem] leading-6 text-slate-800">
                            {event.description}
                          </p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {event.task_title && (
                              <span className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">
                                Task: {event.task_title}
                              </span>
                            )}
                            {event.case_label && (
                              <span className="rounded-md bg-blue-50 px-2 py-1 text-xs text-blue-800">
                                Case: {event.case_label}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex items-start justify-between gap-3 sm:block">
                          <p className="text-sm leading-5 text-slate-500">
                            {formatDateTime(event.created_at, timezone)}
                          </p>
                          {event.case_id && (
                            <Link
                              className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-blue-700"
                              to={`/cases/${event.case_id}`}
                            >
                              View case
                              <ArrowUpRight
                                className="h-3.5 w-3.5"
                                aria-hidden
                              />
                            </Link>
                          )}
                        </div>
                      </article>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
      <Pagination
        page={activity.data.page.page}
        pages={activity.data.page.pages}
        onPageChange={setPage}
        label="Activity pagination"
      />
    </div>
  )
}
