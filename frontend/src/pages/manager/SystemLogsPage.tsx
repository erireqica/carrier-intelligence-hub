import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useCurrentUser } from '../../app/auth'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  StatusBadge,
} from '../../components/ui'
import { getAgents, getAuditLogs } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { getEffectiveTimezone } from '../../lib/timezone'
import type { AuditLog } from '../../lib/types'

const categories = [
  ['ACCESS', 'Access'],
  ['TASKS', 'Tasks'],
  ['REVIEWS', 'Reviews'],
  ['CASES', 'Cases'],
  ['GMAIL', 'Gmail'],
  ['CARRIER_CONFIG', 'Carrier config'],
  ['PROCESSING_SYSTEM', 'Processing / System'],
] as const

function RecordLink({ item }: { item: AuditLog }) {
  if (item.review_id)
    return (
      <Link
        className="font-semibold text-blue-700"
        to={`/reviews/${item.review_id}`}
      >
        {item.review_label ?? 'View review'}
      </Link>
    )
  if (item.case_id)
    return (
      <Link
        className="font-semibold text-blue-700"
        to={`/cases/${item.case_id}`}
      >
        {item.case_label ?? 'View case'}
      </Link>
    )
  if (item.task_title) return <span>Task: {item.task_title}</span>
  return <span>—</span>
}

function TechnicalDetails({ item }: { item: AuditLog }) {
  return (
    <details className="mt-2 text-xs text-slate-500">
      <summary className="cursor-pointer font-semibold">
        Technical details
      </summary>
      <p className="mt-2">Event code: {item.event_type}</p>
      {Object.keys(item.metadata).length > 0 && (
        <dl className="mt-2 space-y-1">
          {Object.entries(item.metadata).map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="font-semibold">{key.replaceAll('_', ' ')}:</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </details>
  )
}

export function SystemLogsPage() {
  const auth = useCurrentUser()
  const [severity, setSeverity] = useState('')
  const [category, setCategory] = useState('')
  const [actor, setActor] = useState('')
  const [excludeGmailSyncCompleted, setExcludeGmailSyncCompleted] =
    useState(true)
  const [page, setPage] = useState(1)
  const params = new URLSearchParams({ page_size: '25', page: String(page) })
  if (severity) params.set('severity', severity)
  if (category) params.set('category', category)
  if (actor) params.set('actor', actor)
  if (excludeGmailSyncCompleted)
    params.set('exclude_gmail_sync_completed', 'true')
  const logs = useQuery({
    queryKey: [
      'manager',
      'audit-events',
      severity,
      category,
      actor,
      excludeGmailSyncCompleted,
      page,
    ],
    queryFn: () => getAuditLogs(params.toString()),
  })
  const agents = useQuery({
    queryKey: ['manager', 'agents'],
    queryFn: getAgents,
  })
  if (logs.isPending) return <LoadingState label="Loading system logs…" />
  if (logs.isError)
    return (
      <ErrorState message={logs.error.message} retry={() => logs.refetch()} />
    )
  const resetPage = () => setPage(1)
  const timezone = getEffectiveTimezone(auth.data?.user)
  return (
    <div className="app-page space-y-6">
      <PageHeader
        eyebrow="Auditability"
        title="System Logs"
        description="Agency-wide operational and user events with safe metadata and related records."
      />
      <div className="filter-toolbar flex flex-wrap gap-3">
        <select
          aria-label="Log severity"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={severity}
          onChange={(event) => {
            setSeverity(event.target.value)
            resetPage()
          }}
        >
          <option value="">All severities</option>
          {['INFO', 'WARNING', 'ERROR'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        <select
          aria-label="Log category"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={category}
          onChange={(event) => {
            setCategory(event.target.value)
            resetPage()
          }}
        >
          <option value="">All categories</option>
          {categories.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="Log actor"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={actor}
          onChange={(event) => {
            setActor(event.target.value)
            resetPage()
          }}
        >
          <option value="">All actors</option>
          <option value="system">System</option>
          <option value={auth.data!.user.id}>
            {auth.data!.user.full_name}
          </option>
          {agents.data?.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.full_name}
            </option>
          ))}
        </select>
        <label className="flex min-h-10 items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={excludeGmailSyncCompleted}
            onChange={(event) => {
              setExcludeGmailSyncCompleted(event.target.checked)
              resetPage()
            }}
          />
          <span>Exclude Gmail sync completions</span>
        </label>
        {(severity || category || actor || !excludeGmailSyncCompleted) && (
          <button
            className="text-sm font-semibold text-blue-700"
            onClick={() => {
              setSeverity('')
              setCategory('')
              setActor('')
              setExcludeGmailSyncCompleted(true)
              resetPage()
            }}
          >
            Reset filters
          </button>
        )}
      </div>
      {logs.data.items.length === 0 ? (
        <EmptyState
          title="No log events found"
          description="No agency events match the selected filters."
        />
      ) : (
        <>
          <div className="data-table-shell hidden md:block">
            <table className="w-full min-w-[850px] text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3">Record</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {logs.data.items.map((item) => (
                  <tr key={item.id} className="align-top">
                    <td className="whitespace-nowrap px-4 py-4">
                      {formatDateTime(item.created_at, timezone)}
                    </td>
                    <td className="px-4 py-4">
                      <StatusBadge status={item.severity} />
                    </td>
                    <td className="px-4 py-4">
                      <p className="font-semibold">{item.event_label}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        {item.category}
                      </p>
                    </td>
                    <td className="px-4 py-4">{item.actor_name ?? 'System'}</td>
                    <td className="max-w-md px-4 py-4">
                      {item.description}
                      <TechnicalDetails item={item} />
                    </td>
                    <td className="px-4 py-4">
                      <RecordLink item={item} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="space-y-3 md:hidden">
            {logs.data.items.map((item) => (
              <article key={item.id} className="surface-panel p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold">{item.event_label}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {item.category}
                    </p>
                  </div>
                  <StatusBadge status={item.severity} />
                </div>
                <p className="mt-3 text-sm">{item.description}</p>
                <dl className="mt-3 grid gap-2 text-xs text-slate-600">
                  <div>
                    <dt className="font-semibold">Actor</dt>
                    <dd>{item.actor_name ?? 'System'}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold">Time</dt>
                    <dd>{formatDateTime(item.created_at, timezone)}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold">Record</dt>
                    <dd>
                      <RecordLink item={item} />
                    </dd>
                  </div>
                </dl>
                <TechnicalDetails item={item} />
              </article>
            ))}
          </div>
        </>
      )}
      <Pagination
        page={logs.data.page.page}
        pages={logs.data.page.pages}
        onPageChange={setPage}
        label="System log pagination"
        summary={`${logs.data.page.total} events`}
      />
    </div>
  )
}
