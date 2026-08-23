import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import { BackLink } from '../components/BackLink'
import {
  Button,
  ErrorState,
  Input,
  LoadingState,
  StatusBadge,
} from '../components/ui'
import {
  applyReviewAnalysis,
  dismissReviewAnalysis,
  getReviewAnalysis,
  returnCaseToReview,
} from '../lib/api'
import type {
  ActionItem,
  AnalysisResult,
  HumanAnalysisInput,
  MessageClassification,
  PolicyStatus,
  Priority,
} from '../lib/types'

const classifications: MessageClassification[] = [
  'POLICY_ISSUED',
  'PENDING_REQUIREMENTS',
  'LAPSE_NOTICE',
  'COMMISSION_UPDATE',
  'OTHER',
]
const policyStatuses: PolicyStatus[] = [
  'ISSUED',
  'PENDING',
  'LAPSED',
  'DECLINED',
  'ACTIVE',
  'GRACE_PERIOD',
  'UNKNOWN',
]
const priorities: Priority[] = ['LOW', 'NORMAL', 'HIGH', 'URGENT']
const fieldClass =
  'min-h-10 w-full border border-slate-300 bg-white px-3 py-2 text-sm'

function humanize(value: string) {
  return value
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function reviewExplanation(reasonCode: string, fallback: string) {
  const explanations: Record<string, string> = {
    LOW_CONFIDENCE:
      'Carrier Hub was not confident enough to apply these details automatically. Compare the proposed information with the carrier message and correct anything that is wrong.',
    MODEL_UNCERTAINTY:
      'Some details in the message were ambiguous. Check the proposed information against the carrier message before applying it.',
    CLIENT_MISMATCH:
      'The client name in this message does not match the client currently attached to this policy. Confirm which information is correct.',
    SOURCE_INCOMPLETE:
      'Carrier Hub could not verify all required details from the available message and attachments.',
    SOURCE_TRUNCATED:
      'Part of the source was too long to analyze safely. Check the carrier message before deciding.',
    MISSING_POLICY_NUMBER:
      'Carrier Hub could not verify a policy number. Check the message and add it if available.',
    MISSING_CLIENT_NAME:
      'Carrier Hub could not verify the client name. Check the message and correct the proposal.',
  }
  return (
    explanations[reasonCode] ??
    fallback ??
    'Carrier Hub could not safely apply this message automatically. Compare the proposed details with the carrier message.'
  )
}

function toHumanInput(proposal: AnalysisResult): HumanAnalysisInput {
  return {
    classification: proposal.classification,
    summary: proposal.summary,
    priority: proposal.priority,
    client_name: proposal.client_name,
    policy_number: proposal.policy_number,
    policy_status: proposal.policy_status,
    premium_amount: proposal.premium_amount,
    currency: proposal.currency,
    effective_date: proposal.effective_date,
    deadline: proposal.deadline,
    requirements: proposal.requirements,
    action_items: proposal.action_items,
  }
}

function ReadOnlyProposal({
  proposal,
  status,
  resolutionNotes,
  className = '',
}: {
  proposal: AnalysisResult
  status: string
  resolutionNotes: string | null
  className?: string
}) {
  return (
    <section className={`surface-panel space-y-5 p-5 ${className}`}>
      <div>
        <p className="mb-2 text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
          04 · Decision record
        </p>
        <h2 className="font-semibold">Confirmed analysis</h2>
        <p className="mt-1 text-sm text-slate-600">
          This review is display-only. No editable controls are available in
          this view.
        </p>
      </div>
      <dl className="grid gap-4 text-sm sm:grid-cols-2">
        {[
          ['Classification', humanize(proposal.classification)],
          ['Policy status', humanize(proposal.policy_status)],
          ['Client name', proposal.client_name ?? 'Not found'],
          ['Policy number', proposal.policy_number ?? 'Not found'],
          ['Priority', humanize(proposal.priority)],
          ['Effective date', proposal.effective_date ?? 'Not found'],
          ['Premium amount', proposal.premium_amount ?? 'Not found'],
          ['Currency', proposal.currency ?? 'Not found'],
          [
            'Deadline',
            proposal.deadline.explicit_date ??
              proposal.deadline.raw_text ??
              'Not found',
          ],
          ['Review status', humanize(status)],
        ].map(([label, value]) => (
          <div key={label}>
            <dt className="text-slate-500">{label}</dt>
            <dd className="mt-1 font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      <div>
        <h3 className="text-sm font-semibold">Summary</h3>
        <p className="mt-1 text-sm leading-6 text-slate-700">
          {proposal.summary}
        </p>
      </div>
      <div>
        <h3 className="text-sm font-semibold">Requirements</h3>
        {proposal.requirements.length ? (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
            {proposal.requirements.map((requirement) => (
              <li key={requirement}>{requirement}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-slate-500">
            No requirements recorded.
          </p>
        )}
      </div>
      <div>
        <h3 className="text-sm font-semibold">Action items</h3>
        <div className="mt-2 space-y-2">
          {proposal.action_items.map((action) => (
            <div
              key={action.title}
              className="border border-slate-200 p-3 text-sm"
            >
              <p className="font-medium">{action.title}</p>
              <p className="mt-1 text-slate-600">{action.description}</p>
              <p className="mt-1 text-xs text-slate-500">
                {humanize(action.priority)}
                {action.explicit_due_date
                  ? ` · Due ${action.explicit_due_date}`
                  : ''}
              </p>
            </div>
          ))}
        </div>
      </div>
      {resolutionNotes && (
        <div>
          <h3 className="text-sm font-semibold">Resolution notes</h3>
          <p className="mt-1 text-sm text-slate-700">{resolutionNotes}</p>
        </div>
      )}
    </section>
  )
}

function ProposalSummary({ proposal }: { proposal: AnalysisResult }) {
  return (
    <section className="surface-panel h-fit self-start p-5">
      <p className="mb-2 text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
        03 · Compare the interpretation
      </p>
      <h2 className="font-semibold">What Carrier Hub found</h2>
      <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
        {[
          ['Classification', humanize(proposal.classification)],
          ['Client', proposal.client_name ?? 'Not found'],
          ['Policy number', proposal.policy_number ?? 'Not found'],
          ['Policy status', humanize(proposal.policy_status)],
          ['Priority', humanize(proposal.priority)],
          [
            'Deadline',
            proposal.deadline.explicit_date ??
              proposal.deadline.raw_text ??
              'Not found',
          ],
          [
            'Premium',
            proposal.premium_amount
              ? `${proposal.currency ?? ''} ${proposal.premium_amount}`.trim()
              : 'Not found',
          ],
          ['Effective date', proposal.effective_date ?? 'Not found'],
        ].map(([label, value]) => (
          <div key={label}>
            <dt className="text-slate-500">{label}</dt>
            <dd className="mt-1 font-medium text-slate-900">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-5 border-t border-slate-100 pt-4 text-sm leading-6 text-slate-700">
        {proposal.summary}
      </p>
    </section>
  )
}

export function ReviewDetailPage() {
  const { reviewId = '' } = useParams()
  const id = Number(reviewId)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const auth = useCurrentUser()
  const isManager = auth.data?.user.role === 'MANAGER'
  const detail = useQuery({
    queryKey: ['review', id, 'analysis'],
    queryFn: () => getReviewAnalysis(id),
    enabled: Number.isInteger(id) && id > 0,
  })
  const [editedForm, setEditedForm] = useState<HumanAnalysisInput | null>(null)
  const [notes, setNotes] = useState('')
  const [showDismiss, setShowDismiss] = useState(false)
  const [selectedCaseId, setSelectedCaseId] = useState<number | undefined>()

  const refreshAfterDecision = async (caseId: number | null) => {
    await queryClient.invalidateQueries({ queryKey: ['reviews'] })
    await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    await queryClient.invalidateQueries({ queryKey: ['cases'] })
    navigate(caseId ? `/cases/${caseId}` : '/reviews')
  }
  const apply = useMutation({
    mutationFn: () =>
      applyReviewAnalysis(
        id,
        editedForm ?? toHumanInput(detail.data!.analysis.proposed_result!),
        selectedCaseId,
      ),
    onSuccess: (result) => refreshAfterDecision(result.case_id),
  })
  const dismiss = useMutation({
    mutationFn: () => dismissReviewAnalysis(id, notes),
    onSuccess: () => refreshAfterDecision(null),
  })
  const returnToReview = useMutation({
    mutationFn: () => returnCaseToReview(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['review', id, 'analysis'],
      })
      await queryClient.invalidateQueries({ queryKey: ['reviews'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  if (detail.isPending)
    return <LoadingState label="Loading analysis proposal…" />
  if (detail.isError)
    return (
      <ErrorState
        message={detail.error.message}
        retry={() => detail.refetch()}
      />
    )
  const proposal = detail.data.analysis.proposed_result
  const review = detail.data
  const analysis = review.analysis
  const form = editedForm ?? (proposal ? toHumanInput(proposal) : null)
  const isFinalized = ['RESOLVED', 'DISMISSED'].includes(review.status)
  const isCaseDismissed = review.case_is_dismissed
  const isOwnershipBlocked =
    !isFinalized && review.reason_code === 'CASE_OWNER_CONFLICT'
  const isCaseMatch =
    !isFinalized && review.reason_code === 'CASE_MATCH_CONFLICT'
  const update = <K extends keyof HumanAnalysisInput>(
    key: K,
    value: HumanAnalysisInput[K],
  ) => {
    if (form) setEditedForm({ ...form, [key]: value })
  }
  const updateAction = (index: number, action: ActionItem) => {
    if (!form) return
    update(
      'action_items',
      form.action_items.map((item, position) =>
        position === index ? action : item,
      ),
    )
  }
  const error = apply.error ?? dismiss.error

  return (
    <div className="app-page space-y-6">
      <BackLink to="/reviews" label="Back to review queue" />
      <section className="overflow-hidden rounded-2xl bg-[#12243c] text-white shadow-[0_18px_46px_rgb(15_23_42/14%)]">
        <div className="relative p-6 sm:p-8">
          <span className="absolute -top-20 -right-16 h-64 w-64 rounded-full border border-white/10" />
          <div className="relative flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-[0.68rem] font-bold tracking-[0.16em] text-blue-200 uppercase">
                Decision workspace
              </p>
              <h1 className="mt-2 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
                {isManager
                  ? 'This email needs agent review'
                  : 'This email needs your review'}
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                {review.carrier_name} · {review.message_subject}
              </p>
            </div>
            <div className="self-start sm:self-auto">
              <StatusBadge status={review.status} />
            </div>
          </div>
        </div>
        <ol className="grid border-t border-white/10 bg-white/[0.035] text-xs font-semibold text-slate-300 sm:grid-cols-4">
          {[
            'Identify issue',
            'Inspect source',
            'Compare interpretation',
            'Make decision',
          ].map((label, index) => (
            <li
              key={label}
              className="flex items-center gap-2 border-white/10 px-4 py-3 sm:border-r sm:last:border-r-0"
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-400/20 text-[0.65rem] text-blue-200">
                {index + 1}
              </span>
              {label}
            </li>
          ))}
        </ol>
      </section>
      {isManager && !isFinalized && (
        <p className="border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
          <strong>Manager view —</strong> review decisions are completed by the
          assigned agent.
        </p>
      )}
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
        <p className="mb-2 text-[0.66rem] font-bold tracking-[0.14em] text-amber-700 uppercase">
          01 · Identify the issue
        </p>
        <h2 className="font-semibold text-amber-950">
          {isManager ? 'What needs attention' : 'What needs your attention'}
        </h2>
        <div className="mt-3 space-y-4">
          {review.issues && review.issues.length > 0 ? (
            review.issues.map((issue) => (
              <div key={issue.code}>
                <h3 className="text-sm font-semibold text-amber-950">
                  {issue.title}
                </h3>
                <p className="mt-1 max-w-4xl text-sm leading-6 text-amber-950">
                  {issue.message}
                </p>
                {issue.values.length > 0 && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {issue.values.map((value, index) => {
                      const caseId = value.source_id.startsWith('case:')
                        ? Number(value.source_id.slice(5))
                        : undefined
                      return (
                        <label
                          className="border border-amber-200 bg-white p-3 text-sm"
                          key={`${value.source_id}-${index}`}
                        >
                          {isCaseMatch && caseId && !isManager && (
                            <input
                              className="mr-2"
                              type="radio"
                              name="selected-case"
                              checked={selectedCaseId === caseId}
                              onChange={() => setSelectedCaseId(caseId)}
                            />
                          )}
                          <span className="block text-amber-800">
                            {value.source_label}
                          </span>
                          <span className="mt-1 block font-medium text-slate-950">
                            {value.value}
                          </span>
                          {value.excerpt && (
                            <span className="mt-2 block text-xs leading-5 text-slate-600">
                              “{value.excerpt}”
                            </span>
                          )}
                        </label>
                      )
                    })}
                  </div>
                )}
              </div>
            ))
          ) : (
            <p className="max-w-4xl text-sm leading-6 text-amber-950">
              {reviewExplanation(review.reason_code, review.reason)}
            </p>
          )}
        </div>
      </section>
      {isOwnershipBlocked && !isManager && (
        <p className="border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <strong>
            Case ownership must be resolved before this review can be applied.
          </strong>{' '}
          Ask a manager to confirm the Case assignment. Editing extracted fields
          cannot resolve an ownership conflict.
        </p>
      )}
      <section className="grid items-start gap-6 xl:grid-cols-2">
        <div className="surface-panel h-fit self-start space-y-5 p-5">
          <div>
            <p className="mb-2 text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
              02 · Inspect the source
            </p>
            <h2 className="font-semibold">Email content</h2>
            <p className="mt-1 text-sm text-slate-600">
              Review the original email and any attachments to identify the
              issue before confirming your decision.
            </p>
          </div>
          <div className="space-y-4 border border-slate-200 bg-slate-50 p-4">
            <div>
              <p className="text-sm font-semibold text-slate-900">
                Email subject
              </p>
              <p className="mt-1 text-sm text-slate-700">
                {review.message_subject}
              </p>
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">Email body</p>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                {analysis.source_content}
              </p>
            </div>
          </div>
          {analysis.attachments.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-slate-900">
                Attachments
              </h3>
              <div className="mt-2 space-y-3">
                {analysis.attachments.map((attachment) => (
                  <div
                    key={attachment.id}
                    className="border border-slate-200 p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-semibold">
                        {attachment.filename}
                      </p>
                      <StatusBadge status={attachment.processing_status} />
                    </div>
                    <details className="mt-2">
                      <summary className="cursor-pointer text-sm font-semibold text-blue-700">
                        View extracted text
                      </summary>
                      <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
                        {attachment.extracted_text_preview ??
                          'No extracted text preview.'}
                      </p>
                    </details>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {proposal && <ProposalSummary proposal={proposal} />}

        {proposal && form ? (
          isManager || isFinalized || isCaseDismissed || isOwnershipBlocked ? (
            <ReadOnlyProposal
              proposal={proposal}
              status={review.status}
              resolutionNotes={review.resolution_notes}
              className="xl:col-span-2"
            />
          ) : (
            <form
              className="surface-panel space-y-5 p-5 xl:col-span-2"
              onSubmit={(event) => {
                event.preventDefault()
                apply.mutate()
              }}
            >
              <fieldset className="space-y-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="mb-2 text-[0.66rem] font-bold tracking-[0.14em] text-blue-700 uppercase">
                      04 · Make a decision
                    </p>
                    <h2 className="font-semibold">Confirm or correct</h2>
                  </div>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="text-sm font-medium">
                    Classification
                    <select
                      className={`${fieldClass} mt-1`}
                      value={form.classification}
                      onChange={(event) =>
                        update(
                          'classification',
                          event.target.value as MessageClassification,
                        )
                      }
                    >
                      {classifications.map((value) => (
                        <option key={value} value={value}>
                          {humanize(value)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-medium">
                    Policy status
                    <select
                      className={`${fieldClass} mt-1`}
                      value={form.policy_status}
                      onChange={(event) =>
                        update(
                          'policy_status',
                          event.target.value as PolicyStatus,
                        )
                      }
                    >
                      {policyStatuses.map((value) => (
                        <option key={value} value={value}>
                          {humanize(value)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-medium">
                    Client name
                    <Input
                      className="mt-1"
                      value={form.client_name ?? ''}
                      onChange={(event) =>
                        update('client_name', event.target.value || null)
                      }
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Policy number
                    <Input
                      className="mt-1"
                      value={form.policy_number ?? ''}
                      onChange={(event) =>
                        update('policy_number', event.target.value || null)
                      }
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Priority
                    <select
                      className={`${fieldClass} mt-1`}
                      value={form.priority}
                      onChange={(event) =>
                        update('priority', event.target.value as Priority)
                      }
                    >
                      {priorities.map((value) => (
                        <option key={value} value={value}>
                          {humanize(value)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-medium">
                    Effective date
                    <Input
                      className="mt-1"
                      type="date"
                      value={form.effective_date ?? ''}
                      onChange={(event) =>
                        update('effective_date', event.target.value || null)
                      }
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Premium amount
                    <Input
                      className="mt-1"
                      inputMode="decimal"
                      value={form.premium_amount ?? ''}
                      onChange={(event) =>
                        update('premium_amount', event.target.value || null)
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
                        update('currency', event.target.value || null)
                      }
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Deadline date
                    <Input
                      className="mt-1"
                      type="date"
                      value={form.deadline.explicit_date ?? ''}
                      onChange={(event) =>
                        update('deadline', {
                          ...form.deadline,
                          explicit_date: event.target.value || null,
                          relative_count: null,
                          relative_unit: null,
                        })
                      }
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Deadline source wording
                    <Input
                      className="mt-1"
                      value={form.deadline.raw_text ?? ''}
                      onChange={(event) =>
                        update('deadline', {
                          ...form.deadline,
                          raw_text: event.target.value || null,
                        })
                      }
                    />
                  </label>
                </div>
                <label className="block text-sm font-medium">
                  Summary
                  <textarea
                    className={`${fieldClass} mt-1 min-h-24`}
                    required
                    value={form.summary}
                    onChange={(event) => update('summary', event.target.value)}
                  />
                </label>
                <label className="block text-sm font-medium">
                  Requirements (one per line)
                  <textarea
                    className={`${fieldClass} mt-1 min-h-24`}
                    value={form.requirements.join('\n')}
                    onChange={(event) =>
                      update(
                        'requirements',
                        event.target.value.split('\n').filter(Boolean),
                      )
                    }
                  />
                </label>
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold">Action items</h3>
                  {form.action_items.map((action, index) => (
                    <div
                      key={index}
                      className="grid gap-3 border border-slate-200 p-3 sm:grid-cols-2"
                    >
                      <label className="text-sm font-medium sm:col-span-2">
                        Title
                        <Input
                          className="mt-1"
                          required
                          value={action.title}
                          onChange={(event) =>
                            updateAction(index, {
                              ...action,
                              title: event.target.value,
                            })
                          }
                        />
                      </label>
                      <label className="text-sm font-medium">
                        Priority
                        <select
                          className={`${fieldClass} mt-1`}
                          value={action.priority}
                          onChange={(event) =>
                            updateAction(index, {
                              ...action,
                              priority: event.target.value as Priority,
                            })
                          }
                        >
                          {priorities.map((value) => (
                            <option key={value}>{value}</option>
                          ))}
                        </select>
                      </label>
                      <label className="text-sm font-medium">
                        Due date
                        <Input
                          className="mt-1"
                          type="date"
                          value={action.explicit_due_date ?? ''}
                          onChange={(event) =>
                            updateAction(index, {
                              ...action,
                              explicit_due_date: event.target.value || null,
                            })
                          }
                        />
                      </label>
                      <label className="text-sm font-medium sm:col-span-2">
                        Description
                        <Input
                          className="mt-1"
                          value={action.description ?? ''}
                          onChange={(event) =>
                            updateAction(index, {
                              ...action,
                              description: event.target.value || null,
                            })
                          }
                        />
                      </label>
                    </div>
                  ))}
                </div>
                <div className="border-t border-slate-200 pt-5">
                  <details className="mb-5 border border-slate-200 p-3">
                    <summary className="cursor-pointer text-sm font-semibold text-slate-700">
                      Technical details
                    </summary>
                    <p className="mt-3 text-sm text-slate-600">
                      <span className="font-semibold text-slate-700">
                        AI&apos;s confidence that this is the issue:
                      </span>{' '}
                      {analysis.overall_confidence === null
                        ? 'Unavailable'
                        : `${Math.round(analysis.overall_confidence * 100)}%`}
                    </p>
                    {analysis.validation_flags.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {analysis.validation_flags.map((flag) => (
                          <StatusBadge key={flag} status={flag} />
                        ))}
                      </div>
                    )}
                  </details>
                  {showDismiss && !isManager && !isFinalized && (
                    <div className="mb-4 border border-red-200 bg-red-50 p-4">
                      <label className="block text-sm font-medium">
                        Why is this message not actionable?
                        <Input
                          className="mt-1"
                          value={notes}
                          onChange={(event) => setNotes(event.target.value)}
                        />
                      </label>
                      <Button
                        className="mt-3"
                        type="button"
                        variant="danger"
                        disabled={dismiss.isPending}
                        onClick={() => dismiss.mutate()}
                      >
                        Dismiss message
                      </Button>
                    </div>
                  )}
                  {error && (
                    <p className="mt-3 text-sm text-red-700" role="alert">
                      {error.message}
                    </p>
                  )}
                  {!isFinalized && !isManager && (
                    <div className="mt-4 flex flex-wrap gap-3">
                      <Button
                        type="submit"
                        disabled={
                          apply.isPending ||
                          dismiss.isPending ||
                          (isCaseMatch && !selectedCaseId)
                        }
                      >
                        Confirm &amp; apply
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={apply.isPending || dismiss.isPending}
                        onClick={() => setShowDismiss((current) => !current)}
                      >
                        Not actionable
                      </Button>
                    </div>
                  )}
                </div>
              </fieldset>
            </form>
          )
        ) : (
          <section className="surface-panel space-y-5 p-5 xl:col-span-2">
            <div>
              <h2 className="font-semibold">No structured proposal</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                Analysis did not produce a valid structured record, so there is
                nothing safe to approve and apply. Review the source and any
                attachment previews before dismissing this non-operational
                message.
              </p>
            </div>
            <dl className="grid gap-4 border border-slate-200 bg-slate-50 p-4 text-sm sm:grid-cols-2">
              <div>
                <dt className="font-semibold text-slate-500">Carrier</dt>
                <dd className="mt-1">{review.carrier_name}</dd>
              </div>
              <div>
                <dt className="font-semibold text-slate-500">Status</dt>
                <dd className="mt-1">{review.status.replaceAll('_', ' ')}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="font-semibold text-slate-500">Review reason</dt>
                <dd className="mt-1">{review.reason}</dd>
              </div>
            </dl>
            {isFinalized || isManager || isCaseDismissed ? (
              <div className="border-t border-slate-200 pt-5 text-sm text-slate-600">
                <p className="font-semibold text-slate-900">
                  {isCaseDismissed ? 'Case dismissed' : 'Finalized review'}
                </p>
                <p className="mt-1">
                  {isCaseDismissed
                    ? 'Send this Case back to review before making a decision.'
                    : isManager && !isFinalized
                      ? 'Review decisions are completed by the assigned agent.'
                      : (review.resolution_notes ??
                        'This review is read-only because it has already been finalized.')}
                </p>
              </div>
            ) : (
              <div className="border-t border-slate-200 pt-5">
                <label className="block text-sm font-medium">
                  Dismissal notes
                  <Input
                    className="mt-1"
                    value={notes}
                    onChange={(event) => setNotes(event.target.value)}
                  />
                </label>
                {dismiss.error && (
                  <p className="mt-3 text-sm text-red-700" role="alert">
                    {dismiss.error.message}
                  </p>
                )}
                <Button
                  className="mt-4"
                  type="button"
                  variant="danger"
                  disabled={dismiss.isPending}
                  onClick={() => dismiss.mutate()}
                >
                  Dismiss review
                </Button>
              </div>
            )}
          </section>
        )}
      </section>
      {(isCaseDismissed || review.status === 'DISMISSED') &&
        review.can_return_to_review &&
        !isManager && (
          <section className="surface-panel flex flex-col gap-4 border-l-4 border-l-blue-600 p-5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <div className="flex-1">
              <h2 className="font-semibold text-slate-950">
                {isCaseDismissed
                  ? 'Return this case to review'
                  : 'Return this review to active work'}
              </h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
                Reopen the existing Review and return this carrier message to
                the active Review queue.
              </p>
            </div>
            <Button
              className="shrink-0"
              disabled={returnToReview.isPending}
              onClick={() => returnToReview.mutate()}
            >
              {returnToReview.isPending ? 'Sending…' : 'Send back to review'}
            </Button>
            {returnToReview.error && (
              <p className="text-sm text-red-700 sm:basis-full" role="alert">
                {returnToReview.error.message}
              </p>
            )}
          </section>
        )}
    </div>
  )
}
