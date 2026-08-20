import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import {
  ErrorState,
  LoadingState,
  PageHeader,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { formatBusinessDate, formatDate } from '../lib/format'
import { getCase, updateTask } from '../lib/api'
import type { TaskStatus } from '../lib/types'

function pendingAnalysisLabel(processingStatus: string) {
  switch (processingStatus) {
    case 'PROCESSING':
      return 'Processing'
    case 'FAILED':
      return 'Analysis failed'
    case 'NEEDS_REVIEW':
      return 'Needs review'
    default:
      return 'Pending analysis'
  }
}

function pendingAnalysisSummary(processingStatus: string) {
  switch (processingStatus) {
    case 'PROCESSING':
      return 'Semantic analysis is currently in progress.'
    case 'FAILED':
      return 'Semantic analysis did not complete. Review the source content for details.'
    case 'NEEDS_REVIEW':
      return 'Semantic analysis is incomplete and requires human review.'
    default:
      return 'Semantic analysis has not started yet.'
  }
}

export function CaseDetailPage() {
  const { caseId = '' } = useParams()
  const queryClient = useQueryClient()
  const detail = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => getCase(caseId),
    enabled: Boolean(caseId),
  })
  const taskMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TaskStatus }) =>
      updateTask(id, status),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['case', caseId] })
      await queryClient.invalidateQueries({ queryKey: ['tasks'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  if (detail.isPending) return <LoadingState label="Loading case history…" />
  if (detail.isError)
    return (
      <ErrorState
        message={detail.error.message}
        retry={() => detail.refetch()}
      />
    )
  const item = detail.data
  return (
    <div className="space-y-6">
      <Link className="text-sm font-semibold text-blue-700" to="/cases">
        ← Back to cases
      </Link>
      <PageHeader
        eyebrow={`${item.carrier.name} · ${item.policy_number ?? 'Policy number pending'}`}
        title={item.client_name}
        description={item.summary}
        action={
          <div className="flex gap-2">
            <PriorityBadge priority={item.priority} />
            <StatusBadge status={item.policy_status} />
          </div>
        }
      />
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['Assigned agent', item.assigned_agent?.full_name ?? 'Unassigned'],
          ['Key deadline', formatBusinessDate(item.deadline)],
          [
            'Premium',
            item.premium_amount
              ? `${item.currency ?? 'USD'} ${item.premium_amount}`
              : '—',
          ],
          ['Effective date', formatBusinessDate(item.effective_date)],
        ].map(([label, value]) => (
          <div key={label} className="border border-slate-200 bg-white p-4">
            <p className="text-xs font-semibold text-slate-500 uppercase">
              {label}
            </p>
            <p className="mt-2 font-medium text-slate-900">{value}</p>
          </div>
        ))}
      </section>
      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
        <div className="space-y-6">
          <div className="border border-slate-200 bg-white">
            <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
              Required actions
            </h2>
            <div className="divide-y divide-slate-100">
              {item.tasks.map((task) => (
                <div
                  key={task.id}
                  className="flex items-start justify-between gap-4 px-5 py-4"
                >
                  <div>
                    <p className="font-medium">{task.title}</p>
                    <p className="mt-1 text-sm text-slate-600">
                      {task.description}
                    </p>
                    <p className="mt-2 text-xs text-slate-500">
                      Due {formatBusinessDate(task.due_at)}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <StatusBadge status={task.status} />
                    <label className="sr-only" htmlFor={`case-task-${task.id}`}>
                      Update {task.title}
                    </label>
                    <select
                      id={`case-task-${task.id}`}
                      className="mt-2 block border border-slate-300 bg-white px-2 py-1.5 text-sm"
                      value={task.status}
                      disabled={taskMutation.isPending}
                      onChange={(event) =>
                        taskMutation.mutate({
                          id: task.id,
                          status: event.target.value as TaskStatus,
                        })
                      }
                    >
                      {['OPEN', 'IN_PROGRESS', 'COMPLETED', 'DISMISSED'].map(
                        (status) => (
                          <option key={status} value={status}>
                            {status.replaceAll('_', ' ')}
                          </option>
                        ),
                      )}
                    </select>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="border border-slate-200 bg-white">
            <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
              Carrier communications
            </h2>
            <div className="divide-y divide-slate-100">
              {item.messages.map((message) => (
                <article key={message.id} className="px-5 py-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={message.processing_status} />
                    <span className="text-xs font-semibold text-slate-500">
                      {message.classification
                        ? message.classification.replaceAll('_', ' ')
                        : pendingAnalysisLabel(message.processing_status)}
                    </span>
                  </div>
                  <h3 className="mt-3 font-semibold">{message.subject}</h3>
                  <p className="mt-1 text-xs text-slate-500">
                    From {message.sender} · {formatDate(message.received_at)}
                  </p>
                  <p className="mt-3 text-sm text-slate-700">
                    {message.summary ??
                      pendingAnalysisSummary(message.processing_status)}
                  </p>
                  {(message.analysis_confidence !== null ||
                    message.validation_flags.length > 0) && (
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                      {message.analysis_confidence !== null && (
                        <span>
                          Analysis confidence:{' '}
                          {Math.round(message.analysis_confidence * 100)}%
                        </span>
                      )}
                      {message.validation_flags.map((flag) => (
                        <StatusBadge key={flag} status={flag} />
                      ))}
                      {message.review_id && (
                        <Link
                          className="font-semibold text-blue-700"
                          to={`/reviews/${message.review_id}`}
                        >
                          Review analysis
                        </Link>
                      )}
                    </div>
                  )}
                  <details className="mt-4 border-t border-slate-100 pt-3">
                    <summary className="cursor-pointer text-sm font-semibold text-blue-800">
                      View cleaned source content
                    </summary>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                      {message.cleaned_content}
                    </p>
                  </details>
                </article>
              ))}
            </div>
          </div>
          <div className="border border-slate-200 bg-white">
            <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
              Attachments
            </h2>
            {item.attachments.length ? (
              <div className="divide-y divide-slate-100">
                {item.attachments.map((attachment) => (
                  <div
                    key={attachment.id}
                    className="flex justify-between px-5 py-4"
                  >
                    <div>
                      <p className="font-medium">{attachment.filename}</p>
                      <p className="text-xs text-slate-500">
                        {attachment.mime_type} ·{' '}
                        {Math.ceil(attachment.size_bytes / 1024)} KB
                        {attachment.page_count
                          ? ` · ${attachment.page_count} pages`
                          : ''}
                      </p>
                      {attachment.extraction_error_code && (
                        <p className="mt-1 text-xs text-amber-800">
                          {attachment.extraction_error_code.replaceAll(
                            '_',
                            ' ',
                          )}
                        </p>
                      )}
                      {attachment.processing_status === 'NEEDS_OCR' && (
                        <p className="mt-2 text-sm text-amber-900">
                          This PDF contains little or no extractable text and
                          requires manual review.
                        </p>
                      )}
                      {attachment.extracted_text_preview && (
                        <details className="mt-3">
                          <summary className="cursor-pointer text-sm font-semibold text-blue-700">
                            View extracted text
                          </summary>
                          <p className="mt-2 max-w-3xl whitespace-pre-wrap text-sm leading-6 text-slate-700">
                            {attachment.extracted_text_preview}
                          </p>
                        </details>
                      )}
                    </div>
                    <StatusBadge status={attachment.processing_status} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="p-5 text-sm text-slate-600">
                No attachments are associated with this case.
              </p>
            )}
          </div>
        </div>
        <aside className="space-y-6">
          <div className="border border-slate-200 bg-white">
            <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
              Evidence
            </h2>
            <div className="divide-y divide-slate-100">
              {item.evidence.length ? (
                item.evidence.map((evidence) => (
                  <blockquote key={evidence.id} className="px-5 py-4">
                    <p className="text-xs font-semibold text-slate-500 uppercase">
                      {evidence.field_name.replaceAll('_', ' ')}
                    </p>
                    <p className="mt-2 text-sm leading-6 text-slate-700">
                      “{evidence.excerpt}”
                    </p>
                  </blockquote>
                ))
              ) : (
                <p className="p-5 text-sm text-slate-600">
                  No evidence excerpts recorded.
                </p>
              )}
            </div>
          </div>
          <div className="border border-slate-200 bg-white">
            <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
              Activity
            </h2>
            <div className="divide-y divide-slate-100">
              {item.activity.map((event) => (
                <div key={event.id} className="px-5 py-4">
                  <p className="text-sm font-medium">{event.description}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {formatDate(event.created_at)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </section>
    </div>
  )
}
