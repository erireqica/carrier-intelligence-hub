import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import {
  Button,
  ErrorState,
  Input,
  LoadingState,
  PageHeader,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { formatBusinessDate, formatDate } from '../lib/format'
import { evidenceSourceLabel, humanFieldLabel } from '../lib/humanize'
import {
  assignCase,
  correctCase,
  getAgents,
  getCase,
  updateTask,
} from '../lib/api'
import type {
  CaseCorrectionInput,
  CaseDetail,
  PolicyStatus,
  Priority,
  TaskStatus,
} from '../lib/types'

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

function CaseCorrectionForm({
  item,
  onCancel,
  onSaved,
}: {
  item: CaseDetail
  onCancel: () => void
  onSaved: () => Promise<void>
}) {
  const [form, setForm] = useState<CaseCorrectionInput>({
    client_name: item.client_name,
    policy_number: item.policy_number,
    policy_status: item.policy_status as PolicyStatus,
    priority: item.priority,
    summary: item.summary,
    premium_amount: item.premium_amount,
    currency: item.currency,
    effective_date: item.effective_date,
    deadline: item.deadline,
    reason: '',
  })
  const mutation = useMutation({
    mutationFn: () => correctCase(item.id, form),
    onSuccess: onSaved,
  })
  const fieldClass =
    'mt-1 min-h-10 w-full border border-slate-300 bg-white px-3 py-2 text-sm'
  return (
    <form
      className="space-y-4 border border-blue-200 bg-blue-50 p-5"
      onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}
    >
      <div>
        <h2 className="font-semibold">Correct case information</h2>
        <p className="mt-1 text-sm text-slate-600">
          This updates the current case only. The original carrier message,
          evidence, and analysis remain unchanged.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-medium">
          Client name
          <Input
            className="mt-1"
            value={form.client_name}
            onChange={(event) =>
              setForm({ ...form, client_name: event.target.value })
            }
            required
          />
        </label>
        <label className="text-sm font-medium">
          Policy number
          <Input
            className="mt-1"
            value={form.policy_number ?? ''}
            onChange={(event) =>
              setForm({ ...form, policy_number: event.target.value || null })
            }
          />
        </label>
        <label className="text-sm font-medium">
          Policy status
          <select
            className={fieldClass}
            value={form.policy_status}
            onChange={(event) =>
              setForm({
                ...form,
                policy_status: event.target.value as PolicyStatus,
              })
            }
          >
            {[
              'ISSUED',
              'PENDING',
              'LAPSED',
              'DECLINED',
              'ACTIVE',
              'GRACE_PERIOD',
              'UNKNOWN',
            ].map((value) => (
              <option key={value} value={value}>
                {value.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Priority
          <select
            className={fieldClass}
            value={form.priority}
            onChange={(event) =>
              setForm({ ...form, priority: event.target.value as Priority })
            }
          >
            {['LOW', 'NORMAL', 'HIGH', 'URGENT'].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Premium amount
          <Input
            className="mt-1"
            inputMode="decimal"
            value={form.premium_amount ?? ''}
            onChange={(event) =>
              setForm({ ...form, premium_amount: event.target.value || null })
            }
          />
        </label>
        <label className="text-sm font-medium">
          Currency
          <Input
            className="mt-1"
            maxLength={3}
            value={form.currency ?? ''}
            onChange={(event) =>
              setForm({ ...form, currency: event.target.value || null })
            }
          />
        </label>
        <label className="text-sm font-medium">
          Effective date
          <Input
            className="mt-1"
            type="date"
            value={form.effective_date ?? ''}
            onChange={(event) =>
              setForm({ ...form, effective_date: event.target.value || null })
            }
          />
        </label>
        <label className="text-sm font-medium">
          Current deadline
          <Input
            className="mt-1"
            type="date"
            value={form.deadline ?? ''}
            onChange={(event) =>
              setForm({ ...form, deadline: event.target.value || null })
            }
          />
        </label>
      </div>
      <label className="block text-sm font-medium">
        Summary
        <textarea
          className={`${fieldClass} min-h-24`}
          value={form.summary}
          onChange={(event) =>
            setForm({ ...form, summary: event.target.value })
          }
          required
        />
      </label>
      <label className="block text-sm font-medium">
        Reason for correction
        <Input
          className="mt-1"
          value={form.reason}
          onChange={(event) => setForm({ ...form, reason: event.target.value })}
          minLength={3}
          required
        />
      </label>
      {mutation.error && (
        <p className="text-sm text-red-700" role="alert">
          {mutation.error.message}
        </p>
      )}
      <div className="flex gap-3">
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving…' : 'Save correction'}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

export function CaseDetailPage() {
  const { caseId = '' } = useParams()
  const queryClient = useQueryClient()
  const auth = useCurrentUser()
  const isManager = auth.data?.user.role === 'MANAGER'
  const [correcting, setCorrecting] = useState(false)
  const agents = useQuery({
    queryKey: ['manager', 'agents'],
    queryFn: getAgents,
    enabled: isManager,
  })
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
  const assignmentMutation = useMutation({
    mutationFn: (assignedAgentId: number) =>
      assignCase(Number(caseId), assignedAgentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['case', caseId] })
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
      await queryClient.invalidateQueries({ queryKey: ['tasks'] })
      await queryClient.invalidateQueries({ queryKey: ['reviews'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      await queryClient.invalidateQueries({
        queryKey: ['manager', 'audit-events'],
      })
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
  const eligibleAgents = agents.data?.filter(
    (agent) => agent.role === 'AGENT' && agent.is_active,
  )
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
          <div className="flex w-full flex-col items-start gap-3 self-start sm:w-auto sm:items-end sm:self-end">
            <div className="flex flex-wrap items-center gap-2 self-start sm:self-end">
              <PriorityBadge priority={item.priority} />
              <StatusBadge status={item.policy_status} />
            </div>
            {!isManager && (
              <Button variant="secondary" onClick={() => setCorrecting(true)}>
                Correct case information
              </Button>
            )}
          </div>
        }
      />
      <p className="text-sm text-slate-500">
        Policy status is based on the latest carrier information.
      </p>
      {correcting && (
        <CaseCorrectionForm
          item={item}
          onCancel={() => setCorrecting(false)}
          onSaved={async () => {
            setCorrecting(false)
            await queryClient.invalidateQueries({ queryKey: ['case', caseId] })
            await queryClient.invalidateQueries({ queryKey: ['cases'] })
            await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
            await queryClient.invalidateQueries({ queryKey: ['activity'] })
            await queryClient.invalidateQueries({
              queryKey: ['manager', 'audit-events'],
            })
          }}
        />
      )}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-500 uppercase">
            Policy Status
          </p>
          <p className="mt-2 font-medium text-slate-900">
            {item.policy_status.replaceAll('_', ' ')}
          </p>
        </div>
        <div className="border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-500 uppercase">
            Assigned agent
          </p>
          {isManager ? (
            <select
              aria-label="Assigned agent"
              className="mt-2 min-h-10 w-full border border-slate-300 bg-white px-3 py-2 text-sm"
              value={item.assigned_agent?.id ?? ''}
              disabled={assignmentMutation.isPending || agents.isPending}
              onChange={(event) =>
                assignmentMutation.mutate(Number(event.target.value))
              }
            >
              {!item.assigned_agent && <option value="">Unassigned</option>}
              {item.assigned_agent &&
                !eligibleAgents?.some(
                  (agent) => agent.id === item.assigned_agent?.id,
                ) && (
                  <option value={item.assigned_agent.id} disabled>
                    {item.assigned_agent.full_name} (requires reassignment)
                  </option>
                )}
              {eligibleAgents?.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.full_name}
                </option>
              ))}
            </select>
          ) : (
            <p className="mt-2 font-medium text-slate-900">
              {item.assigned_agent?.full_name ?? 'Unassigned'}
            </p>
          )}
          {assignmentMutation.error && (
            <p className="mt-2 text-xs text-red-700" role="alert">
              {assignmentMutation.error.message}
            </p>
          )}
        </div>
        {[
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
                    {!isManager &&
                    task.assigned_agent.id === auth.data!.user.id ? (
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
                    ) : (
                      <p className="mt-2 max-w-40 text-xs text-slate-500">
                        Status managed by {task.assigned_agent.full_name}
                      </p>
                    )}
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
                    className="flex items-start justify-between gap-4 px-5 py-4"
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
                    <span className="inline-flex h-fit shrink-0 self-start">
                      <StatusBadge status={attachment.processing_status} />
                    </span>
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
                      {humanFieldLabel(evidence.field_name)} ·{' '}
                      {evidenceSourceLabel(
                        evidence.source_type,
                        evidence.attachment_filename,
                      )}
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
