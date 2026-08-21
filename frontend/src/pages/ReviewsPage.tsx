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
  const [view, setView] = useState<
    'ACTIONABLE' | 'RESOLVED' | 'DISMISSED' | 'ALL'
  >('ACTIONABLE')
  const [page, setPage] = useState(1)
  const reviews = useQuery({
    queryKey: ['reviews', view, page],
    queryFn: () =>
      getReviews(
        new URLSearchParams({
          page_size: '25',
          page: String(page),
          view,
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
      <div className="flex flex-wrap gap-2" aria-label="Review views">
        {(
          [
            ['ACTIONABLE', 'Needs attention'],
            ['RESOLVED', 'Resolved'],
            ['DISMISSED', 'Dismissed'],
            ['ALL', 'All'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            className={`border px-4 py-2 text-sm font-semibold ${view === value ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white text-slate-700'}`}
            onClick={() => {
              setView(value)
              setPage(1)
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {reviews.data.items.length === 0 ? (
        <EmptyState
          title={
            view !== 'ACTIONABLE'
              ? 'No reviews match this filter'
              : 'No reviews require attention'
          }
          description={
            view !== 'ACTIONABLE'
              ? 'Choose another review view to see other records.'
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
                  <Link
                    className="border border-slate-900 bg-slate-900 px-3 py-2 text-sm font-semibold text-white"
                    to={`/reviews/${item.id}`}
                  >
                    {['RESOLVED', 'DISMISSED'].includes(item.status)
                      ? 'View review'
                      : 'Review analysis'}
                  </Link>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between gap-3 text-sm">
        <button
          className="font-semibold text-blue-700 disabled:text-slate-400"
          disabled={page <= 1}
          onClick={() => setPage((value) => value - 1)}
        >
          Previous
        </button>
        <span>
          Page {reviews.data.page.page} of {reviews.data.page.pages}
        </span>
        <button
          className="font-semibold text-blue-700 disabled:text-slate-400"
          disabled={page >= reviews.data.page.pages}
          onClick={() => setPage((value) => value + 1)}
        >
          Next
        </button>
      </div>
    </div>
  )
}
