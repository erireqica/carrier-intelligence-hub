import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
} from '../components/ui'
import { formatDate } from '../lib/format'
import { getReviews } from '../lib/api'

export function ReviewsPage() {
  const [status, setStatus] = useState('')
  const reviews = useQuery({
    queryKey: ['reviews', status],
    queryFn: () =>
      getReviews(
        new URLSearchParams({
          page_size: '100',
          ...(status ? { status } : {}),
        }).toString(),
      ),
  })
  if (reviews.isPending) return <LoadingState label="Loading review queue…" />
  if (reviews.isError)
    return (
      <ErrorState
        message={reviews.error.message}
        retry={() => reviews.refetch()}
      />
    )
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Human verification"
        title="Review Queue"
        description="Records that need explicit human attention because validation or source interpretation was incomplete."
      />
      <div className="flex items-center gap-3 border border-slate-200 bg-white p-4">
        <label className="text-sm font-medium" htmlFor="review-status">
          Status
        </label>
        <select
          id="review-status"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">All statuses</option>
          {['OPEN', 'IN_REVIEW', 'RESOLVED', 'DISMISSED'].map((value) => (
            <option key={value} value={value}>
              {value.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
        {status && (
          <button
            className="text-sm font-semibold text-blue-700"
            onClick={() => setStatus('')}
          >
            Reset filter
          </button>
        )}
      </div>
      {reviews.data.items.length === 0 ? (
        <EmptyState
          title={
            status
              ? 'No reviews match this filter'
              : 'No reviews require attention'
          }
          description={
            status
              ? 'Reset the status filter to see the full queue.'
              : 'New validation exceptions will appear here.'
          }
        />
      ) : (
        <div className="space-y-4">
          {reviews.data.items.map((item) => (
            <article
              key={item.id}
              className="border border-slate-200 bg-white p-5"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={item.status} />
                    <span className="text-xs font-semibold text-slate-500">
                      {item.reason_code.replaceAll('_', ' ')}
                    </span>
                  </div>
                  <h2 className="mt-3 font-semibold text-slate-950">
                    {item.client_name ?? 'Unlinked communication'} ·{' '}
                    {item.carrier_name}
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">
                    {item.message_subject}
                  </p>
                  <p className="mt-3 text-sm leading-6 text-slate-700">
                    {item.reason}
                  </p>
                  <p className="mt-3 text-xs text-slate-500">
                    Opened {formatDate(item.created_at)}
                    {item.analysis_confidence === null
                      ? ''
                      : ` · Confidence ${Math.round(item.analysis_confidence * 100)}%`}
                    {item.assigned_reviewer
                      ? ` · Assigned to ${item.assigned_reviewer.full_name}`
                      : ''}
                  </p>
                </div>
                <div className="flex shrink-0 items-start gap-2">
                  {item.case_id && (
                    <Link
                      className="border border-slate-300 px-3 py-2 text-sm font-semibold"
                      to={`/cases/${item.case_id}`}
                    >
                      Open case
                    </Link>
                  )}
                  {!['RESOLVED', 'DISMISSED'].includes(item.status) && (
                    <Link
                      className="border border-slate-900 bg-slate-900 px-3 py-2 text-sm font-semibold text-white"
                      to={`/reviews/${item.id}`}
                    >
                      Review analysis
                    </Link>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
