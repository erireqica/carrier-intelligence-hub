import { useQuery } from '@tanstack/react-query'
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
  return (
    <div className="space-y-6">
      <PageHeader
        title="My Activity"
        description="Your recent case, task, review, Gmail, and account actions."
      />
      <div className="flex flex-wrap items-center gap-3 border border-slate-200 bg-white p-4">
        <label className="text-sm font-medium" htmlFor="activity-type">
          Action type
        </label>
        <select
          id="activity-type"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={group}
          onChange={(event) => {
            setGroup(event.target.value)
            setPage(1)
          }}
        >
          <option value="">All actions</option>
          <option value="TASKS">Task work</option>
          <option value="REVIEWS">Reviews</option>
          <option value="CASES">Case corrections</option>
          <option value="GMAIL">Gmail connections</option>
          <option value="ACCESS">Account access</option>
        </select>
      </div>
      {activity.data.items.length === 0 ? (
        <EmptyState
          title="No activity found"
          description="Your actions will appear here as you work in Carrier Hub."
        />
      ) : (
        <div className="divide-y divide-slate-100 border border-slate-200 bg-white">
          <div className="hidden grid-cols-[180px_1fr_180px] gap-4 bg-slate-50 px-5 py-3 text-xs font-semibold tracking-wide text-slate-500 uppercase sm:grid">
            <span>Action</span>
            <span>Details</span>
            <span>Date</span>
          </div>
          {activity.data.items.map((event) => (
            <article
              key={event.id}
              className="grid gap-2 px-5 py-4 sm:grid-cols-[180px_1fr_180px] sm:items-start"
            >
              <div>
                <p className="font-semibold text-slate-900">
                  {event.event_label}
                </p>
              </div>
              <div>
                <p className="text-[0.95rem] leading-6 text-slate-800">
                  {event.description}
                </p>
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
              <div className="text-sm text-slate-500">
                {formatDateTime(
                  event.created_at,
                  auth.data!.user.agency.timezone,
                )}
                {event.case_id && (
                  <Link
                    className="mt-2 block text-sm font-semibold text-blue-700"
                    to={`/cases/${event.case_id}`}
                  >
                    View case
                  </Link>
                )}
              </div>
            </article>
          ))}
        </div>
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
