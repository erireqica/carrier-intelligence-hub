import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { formatDate } from '../../lib/format'
import { getAuditLogs } from '../../lib/api'

export function SystemLogsPage() {
  const [severity, setSeverity] = useState('')
  const [eventType, setEventType] = useState('')
  const params = new URLSearchParams({ page_size: '100' })
  if (severity) params.set('severity', severity)
  if (eventType) params.set('event_type', eventType)
  const logs = useQuery({
    queryKey: ['manager', 'audit-events', severity, eventType],
    queryFn: () => getAuditLogs(params.toString()),
  })
  if (logs.isPending) return <LoadingState label="Loading system logs…" />
  if (logs.isError)
    return (
      <ErrorState message={logs.error.message} retry={() => logs.refetch()} />
    )
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Auditability"
        title="System Logs"
        description="Append-oriented operational and user events with safe metadata only."
      />
      <div className="flex flex-wrap gap-3 border border-slate-200 bg-white p-4">
        <select
          aria-label="Log severity"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={severity}
          onChange={(event) => setSeverity(event.target.value)}
        >
          <option value="">All severities</option>
          {['INFO', 'WARNING', 'ERROR'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        <select
          aria-label="Log event type"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={eventType}
          onChange={(event) => setEventType(event.target.value)}
        >
          <option value="">All event types</option>
          {[
            'USER_LOGIN',
            'USER_LOGOUT',
            'TASK_STATUS_CHANGED',
            'TASK_ASSIGNED',
            'CASE_REVIEWED',
            'CARRIER_CREATED',
            'CARRIER_UPDATED',
            'WHITELIST_UPDATED',
            'PROCESSING_FAILED',
          ].map((value) => (
            <option key={value}>{value.replaceAll('_', ' ')}</option>
          ))}
        </select>
        {(severity || eventType) && (
          <button
            className="text-sm font-semibold text-blue-700"
            onClick={() => {
              setSeverity('')
              setEventType('')
            }}
          >
            Reset filters
          </button>
        )}
      </div>
      <div className="overflow-x-auto border border-slate-200 bg-white">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-3">Timestamp</th>
              <th className="px-4 py-3">Severity</th>
              <th className="px-4 py-3">Event</th>
              <th className="px-4 py-3">Actor</th>
              <th className="px-4 py-3">Description</th>
              <th className="px-4 py-3">Record</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {logs.data.items.map((item) => (
              <tr key={item.id}>
                <td className="px-4 py-4">{formatDate(item.created_at)}</td>
                <td className="px-4 py-4">
                  <StatusBadge status={item.severity} />
                </td>
                <td className="px-4 py-4 text-xs font-semibold">
                  {item.event_type}
                </td>
                <td className="px-4 py-4">{item.actor_name ?? 'System'}</td>
                <td className="px-4 py-4">{item.description}</td>
                <td className="px-4 py-4">
                  {item.case_id ? (
                    <Link
                      className="font-semibold text-blue-700"
                      to={`/cases/${item.case_id}`}
                    >
                      Case {item.case_id}
                    </Link>
                  ) : item.task_id ? (
                    `Task ${item.task_id}`
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
