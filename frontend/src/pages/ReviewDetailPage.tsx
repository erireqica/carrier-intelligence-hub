import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  Button,
  ErrorState,
  Input,
  LoadingState,
  PageHeader,
  StatusBadge,
} from '../components/ui'
import {
  applyReviewAnalysis,
  dismissReviewAnalysis,
  getReviewAnalysis,
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

export function ReviewDetailPage() {
  const { reviewId = '' } = useParams()
  const id = Number(reviewId)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const detail = useQuery({
    queryKey: ['review', id, 'analysis'],
    queryFn: () => getReviewAnalysis(id),
    enabled: Number.isInteger(id) && id > 0,
  })
  const [editedForm, setEditedForm] = useState<HumanAnalysisInput | null>(null)
  const [notes, setNotes] = useState('')

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
      ),
    onSuccess: (result) => refreshAfterDecision(result.case_id),
  })
  const dismiss = useMutation({
    mutationFn: () => dismissReviewAnalysis(id, notes),
    onSuccess: () => refreshAfterDecision(null),
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
  if (!proposal)
    return (
      <ErrorState message="This review does not contain a valid structured proposal." />
    )

  const review = detail.data
  const analysis = review.analysis
  const form = editedForm ?? toHumanInput(proposal)
  const update = <K extends keyof HumanAnalysisInput>(
    key: K,
    value: HumanAnalysisInput[K],
  ) => setEditedForm({ ...form, [key]: value })
  const updateAction = (index: number, action: ActionItem) =>
    update(
      'action_items',
      form.action_items.map((item, position) =>
        position === index ? action : item,
      ),
    )
  const error = apply.error ?? dismiss.error

  return (
    <div className="space-y-6">
      <Link className="text-sm font-semibold text-blue-700" to="/reviews">
        ← Back to review queue
      </Link>
      <PageHeader
        eyebrow={`${review.carrier_name} · ${review.reason_code.replaceAll('_', ' ')}`}
        title={review.message_subject}
        description={review.reason}
        action={<StatusBadge status={review.status} />}
      />
      <section className="grid gap-6 xl:grid-cols-2">
        <div className="space-y-5 border border-slate-200 bg-white p-5">
          <div>
            <h2 className="font-semibold">Source and evidence</h2>
            <p className="mt-1 text-sm text-slate-600">
              Compare every correction against the source before applying it.
            </p>
          </div>
          <div className="border border-slate-200 bg-slate-50 p-4">
            <p className="whitespace-pre-wrap text-sm leading-6">
              {analysis.source_content}
            </p>
          </div>
          {analysis.proposed_result?.evidence.map((evidence, index) => (
            <blockquote
              key={`${evidence.field_name}-${index}`}
              className="border-l-4 border-blue-200 pl-4"
            >
              <p className="text-xs font-semibold text-slate-500 uppercase">
                {evidence.field_name.replaceAll('_', ' ')} ·{' '}
                {evidence.source_id}
              </p>
              <p className="mt-1 text-sm">“{evidence.excerpt}”</p>
            </blockquote>
          ))}
          {analysis.attachments.map((attachment) => (
            <details
              key={attachment.id}
              className="border border-slate-200 p-3"
            >
              <summary className="cursor-pointer text-sm font-semibold">
                {attachment.filename} · {attachment.processing_status}
              </summary>
              <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
                {attachment.extracted_text_preview ??
                  'No extracted text preview.'}
              </p>
            </details>
          ))}
        </div>

        <form
          className="space-y-5 border border-slate-200 bg-white p-5"
          onSubmit={(event) => {
            event.preventDefault()
            apply.mutate()
          }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">Correct structured analysis</h2>
            <span className="text-sm text-slate-600">
              Confidence:{' '}
              {analysis.overall_confidence === null
                ? '—'
                : `${Math.round(analysis.overall_confidence * 100)}%`}
            </span>
          </div>
          {analysis.validation_flags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {analysis.validation_flags.map((flag) => (
                <StatusBadge key={flag} status={flag} />
              ))}
            </div>
          )}
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
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium">
              Policy status
              <select
                className={`${fieldClass} mt-1`}
                value={form.policy_status}
                onChange={(event) =>
                  update('policy_status', event.target.value as PolicyStatus)
                }
              >
                {policyStatuses.map((value) => (
                  <option key={value}>{value}</option>
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
                  <option key={value}>{value}</option>
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
            <label className="block text-sm font-medium">
              Dismissal notes
              <Input
                className="mt-1"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </label>
            {error && (
              <p className="mt-3 text-sm text-red-700" role="alert">
                {error.message}
              </p>
            )}
            <div className="mt-4 flex flex-wrap gap-3">
              <Button
                type="submit"
                disabled={apply.isPending || dismiss.isPending}
              >
                Approve &amp; Apply
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={apply.isPending || dismiss.isPending}
                onClick={() => dismiss.mutate()}
              >
                Dismiss message
              </Button>
            </div>
          </div>
        </form>
      </section>
    </div>
  )
}
