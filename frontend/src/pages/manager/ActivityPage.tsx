import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from '../../components/ui'
import { formatDate } from '../../lib/format'
import { getActivity, getAgents } from '../../lib/api'

export function ActivityPage() {
  const [agentId, setAgentId] = useState('')
  const [group, setGroup] = useState('')
  const [includeSystem, setIncludeSystem] = useState(false)
  const params = new URLSearchParams({ page_size: '100' })
  if (agentId) params.set('actor_user_id', agentId)
  if (group) params.set('action_group', group)
  if (includeSystem) params.set('include_system', 'true')
  const activity = useQuery({
    queryKey: ['manager', 'activity', agentId, group, includeSystem],
    queryFn: () => getActivity(params.toString()),
  })
  const agents = useQuery({
    queryKey: ['manager', 'agents'],
    queryFn: getAgents,
  })
  if (activity.isPending)
    return <LoadingState label="Loading agency activity…" />
  if (activity.isError)
    return (
      <ErrorState
        message={activity.error.message}
        retry={() => activity.refetch()}
      />
    )
  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity"
        description="See the work agents have completed across the agency."
      />
      <div className="flex flex-wrap gap-3 border border-slate-200 bg-white p-4">
        <select
          aria-label="Activity agent"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={agentId}
          onChange={(event) => setAgentId(event.target.value)}
        >
          <option value="">All agents</option>
          {agents.data?.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.full_name}
            </option>
          ))}
        </select>
        <select
          aria-label="Activity type"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={group}
          onChange={(event) => setGroup(event.target.value)}
        >
          <option value="">All actions</option>
          <option value="TASKS">Task work</option>
          <option value="REVIEWS">Reviews</option>
          <option value="CASES">Case corrections</option>
          <option value="GMAIL">Gmail connections</option>
          <option value="ACCESS">Account access</option>
        </select>
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={includeSystem}
            onChange={(event) => setIncludeSystem(event.target.checked)}
          />{' '}
          Include system activity
        </label>
      </div>
      {activity.data.items.length === 0 ? (
        <EmptyState
          title="No activity found"
          description="No agency activity matches these filters."
        />
      ) : (
        <div className="divide-y divide-slate-100 border border-slate-200 bg-white">
          {activity.data.items.map((event) => (
            <article
              key={event.id}
              className="grid gap-2 px-5 py-4 sm:grid-cols-[180px_1fr_auto] sm:items-start"
            >
              <div>
                <p className="font-semibold text-slate-900">
                  {event.actor_name ?? 'System'}
                </p>
                <p className="text-xs text-slate-500">
                  {formatDate(event.created_at)}
                </p>
              </div>
              <div>
                <p className="text-sm text-slate-800">{event.description}</p>
                {event.task_title && (
                  <p className="mt-1 text-xs text-slate-500">
                    Task: {event.task_title}
                  </p>
                )}
                {event.case_label && (
                  <p className="mt-1 text-xs text-slate-500">
                    Case: {event.case_label}
                  </p>
                )}
              </div>
              {event.case_id && (
                <Link
                  className="text-sm font-semibold text-blue-700"
                  to={`/cases/${event.case_id}`}
                >
                  View case
                </Link>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
