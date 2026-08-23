import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useEffect, useState } from 'react'
import {
  Activity,
  CalendarDays,
  CheckCircle2,
  ClipboardCheck,
  DollarSign,
  Eye,
  EyeOff,
  Mail,
  Paperclip,
  Plus,
  ShieldCheck,
  UserRound,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import { Avatar } from '../components/Avatar'
import { BackLink } from '../components/BackLink'
import {
  Button,
  ErrorState,
  Input,
  LoadingState,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { formatBusinessDate, formatDate } from '../lib/format'
import { evidenceSourceLabel, humanFieldLabel } from '../lib/humanize'
import {
  assignCase,
  completeCase,
  correctCase,
  createManualTask,
  dismissCase,
  getAgents,
  getCase,
  reopenCase,
  restoreCase,
  updateTask,
} from '../lib/api'
import type {
  CaseCorrectionInput,
  CaseDetail,
  ManualTaskInput,
  PolicyStatus,
  Priority,
  TaskItem,
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

function groupEvidence(items: CaseDetail['evidence']) {
  const groups = new Map<string, CaseDetail['evidence']>()
  for (const evidence of items) {
    const source = evidenceSourceLabel(
      evidence.source_type,
      evidence.attachment_filename,
    )
    groups.set(source, [...(groups.get(source) ?? []), evidence])
  }
  return Array.from(groups.entries())
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

const emptyManualTask: ManualTaskInput = {
  title: '',
  description: null,
  priority: 'NORMAL',
  due_date: null,
}

function ManualTaskForm({
  caseId,
  onCancel,
  onCreated,
}: {
  caseId: number
  onCancel: () => void
  onCreated: (task: TaskItem) => Promise<void>
}) {
  const [form, setForm] = useState<ManualTaskInput>(emptyManualTask)
  const mutation = useMutation({
    mutationFn: () => createManualTask(caseId, form),
    onSuccess: onCreated,
  })
  const fieldClass =
    'mt-1 min-h-10 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm'

  return (
    <form
      className="border-b border-blue-100 bg-blue-50/60 p-5"
      aria-label="Add task"
      onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}
    >
      <div className="mb-4">
        <h3 className="font-semibold text-slate-950">Add an action</h3>
        <p className="mt-1 text-xs leading-5 text-slate-600">
          This task stays with the Case and follows its active owner if the Case
          is reassigned.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-medium sm:col-span-2">
          Task title
          <Input
            className="mt-1"
            maxLength={300}
            value={form.title}
            onChange={(event) =>
              setForm({ ...form, title: event.target.value })
            }
            placeholder="Call client to confirm mailing address"
            autoFocus
            required
          />
        </label>
        <label className="text-sm font-medium sm:col-span-2">
          Notes <span className="font-normal text-slate-500">(optional)</span>
          <textarea
            className={`${fieldClass} min-h-20 resize-y`}
            maxLength={5000}
            value={form.description ?? ''}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value || null })
            }
            placeholder="Add any context the assigned agent will need."
          />
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
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Due date{' '}
          <span className="font-normal text-slate-500">(optional)</span>
          <Input
            className="mt-1"
            type="date"
            value={form.due_date ?? ''}
            onChange={(event) =>
              setForm({ ...form, due_date: event.target.value || null })
            }
          />
        </label>
      </div>
      {mutation.error && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {mutation.error.message}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Adding…' : 'Add task'}
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
  const [addingTask, setAddingTask] = useState(false)
  const [showDismissedTasks, setShowDismissedTasks] = useState(false)
  const [showCompletionBlockers, setShowCompletionBlockers] = useState(false)
  useEffect(() => {
    if (!showCompletionBlockers) return
    const timeout = window.setTimeout(
      () => setShowCompletionBlockers(false),
      4000,
    )
    return () => window.clearTimeout(timeout)
  }, [showCompletionBlockers])
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
  const lifecycleMutation = useMutation({
    mutationFn: () =>
      item.dismissed_at ? restoreCase(item.id) : dismissCase(item.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['case', caseId] })
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
      await queryClient.invalidateQueries({ queryKey: ['tasks'] })
      await queryClient.invalidateQueries({ queryKey: ['reviews'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  const completionMutation = useMutation({
    mutationFn: () =>
      item.completed_at ? reopenCase(item.id) : completeCase(item.id),
    onSuccess: async () => {
      setAddingTask(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['case', caseId] }),
        queryClient.invalidateQueries({ queryKey: ['cases'] }),
        queryClient.invalidateQueries({ queryKey: ['tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['reviews'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['activity'] }),
        queryClient.invalidateQueries({
          queryKey: ['manager', 'audit-events'],
        }),
      ])
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
  const isAssignedAgent =
    !isManager && item.assigned_agent?.id === auth.data!.user.id
  const canAddTask = !item.dismissed_at && !item.completed_at && isAssignedAgent
  const dismissedTaskCount = item.tasks.filter(
    (task) => task.status === 'DISMISSED',
  ).length
  const activeTaskCount = item.tasks.filter(
    (task) => task.status === 'OPEN' || task.status === 'IN_PROGRESS',
  ).length
  const visibleTasks = item.tasks.filter(
    (task) => task.status !== 'DISMISSED' || showDismissedTasks,
  )
  const eligibleAgents = agents.data?.filter(
    (agent) => agent.role === 'AGENT' && agent.is_active,
  )
  return (
    <div className="app-page space-y-6">
      <BackLink to="/cases" label="Back to cases" />
      <section className="case-identity overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-6 border-b border-slate-100 p-6 sm:p-7 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex min-w-0 items-start gap-4">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#12243c] text-blue-200 shadow-md">
              <ShieldCheck className="h-6 w-6" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-[0.68rem] font-bold tracking-[0.16em] text-blue-700 uppercase">
                {item.carrier.name} ·{' '}
                {item.policy_number ?? 'Policy number pending'}
              </p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
                {item.client_name}
              </h1>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <PriorityBadge priority={item.priority} />
                <StatusBadge status={item.policy_status} />
                <span className="text-xs text-slate-500">
                  Status reflects the latest carrier information
                </span>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {!item.dismissed_at && item.can_reopen && (
              <Button
                variant="secondary"
                disabled={completionMutation.isPending}
                onClick={() => completionMutation.mutate()}
              >
                Reopen case
              </Button>
            )}
            {!item.dismissed_at && !item.completed_at && isAssignedAgent && (
              <Button
                variant="success"
                disabled={completionMutation.isPending}
                onClick={() => {
                  if (!item.can_complete) {
                    setShowCompletionBlockers(true)
                    return
                  }
                  completionMutation.mutate()
                }}
              >
                <CheckCircle2 className="h-4 w-4" aria-hidden />
                Mark as complete
              </Button>
            )}
            {!item.dismissed_at && item.can_manage_lifecycle && (
              <Button variant="secondary" onClick={() => setCorrecting(true)}>
                Correct case information
              </Button>
            )}
            {item.can_manage_lifecycle && (
              <Button
                variant={item.dismissed_at ? 'success' : 'danger'}
                disabled={lifecycleMutation.isPending}
                onClick={() => lifecycleMutation.mutate()}
              >
                {item.dismissed_at ? 'Restore case' : 'Dismiss case'}
              </Button>
            )}
          </div>
        </div>
        <div className="grid divide-y divide-slate-100 sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-4">
          <div className="flex items-start gap-3 px-5 py-4">
            {item.assigned_agent ? (
              <Avatar user={item.assigned_agent} size="sm" />
            ) : (
              <UserRound className="mt-0.5 h-4 w-4 text-blue-600" aria-hidden />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-[0.66rem] font-bold tracking-wider text-slate-500 uppercase">
                Assigned agent
              </p>
              {isManager && !item.dismissed_at ? (
                <select
                  aria-label="Assigned agent"
                  className="mt-1 min-h-9 w-full border border-slate-300 bg-white px-2 py-1 text-sm"
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
                <p className="mt-1 text-sm font-semibold text-slate-900">
                  {item.assigned_agent?.full_name ?? 'Unassigned'}
                </p>
              )}
            </div>
          </div>
          {[
            [CalendarDays, 'Key deadline', formatBusinessDate(item.deadline)],
            [
              DollarSign,
              'Premium',
              item.premium_amount
                ? `${item.currency ?? 'USD'} ${item.premium_amount}`
                : '—',
            ],
            [
              CalendarDays,
              'Effective date',
              formatBusinessDate(item.effective_date),
            ],
          ].map(([Icon, label, value]) => (
            <div
              key={label as string}
              className="flex items-start gap-3 px-5 py-4"
            >
              <Icon className="mt-0.5 h-4 w-4 text-blue-600" aria-hidden />
              <div>
                <p className="text-[0.66rem] font-bold tracking-wider text-slate-500 uppercase">
                  {label as string}
                </p>
                <p className="mt-1 text-sm font-semibold text-slate-900">
                  {value as string}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>
      {item.dismissed_at && (
        <p className="border border-slate-300 bg-slate-50 p-4 text-sm text-slate-700">
          This Case is dismissed from active work. Restore it to update tasks or
          case information.
        </p>
      )}
      {!item.dismissed_at && item.completed_at && (
        <div className="flex items-start gap-3 border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">
          <CheckCircle2
            className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700"
            aria-hidden
          />
          <div>
            <p className="font-semibold">Case completed</p>
            <p className="mt-1 text-emerald-800">
              {item.completed_by
                ? `Completed by ${item.completed_by.full_name} · ${formatDate(item.completed_at)}`
                : `Completed ${formatDate(item.completed_at)}`}
            </p>
          </div>
        </div>
      )}
      {!item.dismissed_at &&
        !item.completed_at &&
        isAssignedAgent &&
        showCompletionBlockers &&
        item.completion_blockers.length > 0 && (
          <div
            className="completion-blocker-notice border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"
            role="alert"
          >
            <p className="font-semibold">Case completion is not ready</p>
            {item.completion_blockers.map((blocker) => (
              <p key={blocker} className="mt-1 text-amber-800">
                {blocker}
              </p>
            ))}
          </div>
        )}
      {lifecycleMutation.error && (
        <p className="text-sm text-red-700" role="alert">
          {lifecycleMutation.error.message}
        </p>
      )}
      {completionMutation.error && (
        <p className="text-sm text-red-700" role="alert">
          {completionMutation.error.message}
        </p>
      )}
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
      {assignmentMutation.error && (
        <p className="text-sm text-red-700" role="alert">
          {assignmentMutation.error.message}
        </p>
      )}
      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
        <div className="space-y-6">
          <div className="surface-panel">
            <div className="section-titlebar">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                  <ClipboardCheck className="h-[18px] w-[18px]" aria-hidden />
                </span>
                <div>
                  <h2 className="font-semibold">Required actions</h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Operational work for this policy
                  </p>
                </div>
              </div>
              <div className="flex w-full flex-wrap items-center justify-between gap-2 sm:w-auto sm:justify-end">
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                  {activeTaskCount} active
                </span>
                {dismissedTaskCount > 0 && (
                  <button
                    type="button"
                    className={`inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold shadow-sm transition-colors focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 focus-visible:outline-none ${
                      showDismissedTasks
                        ? 'border-blue-200 bg-blue-50 text-blue-800 hover:bg-blue-100'
                        : 'border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50 hover:text-blue-800'
                    }`}
                    aria-label={
                      showDismissedTasks
                        ? 'Hide dismissed'
                        : `Show dismissed (${dismissedTaskCount})`
                    }
                    aria-pressed={showDismissedTasks}
                    onClick={() => setShowDismissedTasks((visible) => !visible)}
                  >
                    {showDismissedTasks ? (
                      <EyeOff className="h-4 w-4" aria-hidden />
                    ) : (
                      <Eye className="h-4 w-4" aria-hidden />
                    )}
                    <span>
                      {showDismissedTasks ? 'Hide dismissed' : 'Show dismissed'}
                    </span>
                    <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[0.68rem] leading-none text-slate-600 ring-1 ring-slate-200">
                      {dismissedTaskCount}
                    </span>
                  </button>
                )}
                {canAddTask && !addingTask && (
                  <Button
                    className="min-h-9 px-3 py-1.5"
                    variant="secondary"
                    onClick={() => setAddingTask(true)}
                  >
                    <Plus className="h-4 w-4" aria-hidden />
                    Add task
                  </Button>
                )}
              </div>
            </div>
            {addingTask && canAddTask && (
              <ManualTaskForm
                caseId={item.id}
                onCancel={() => setAddingTask(false)}
                onCreated={async (task) => {
                  queryClient.setQueryData<CaseDetail>(
                    ['case', caseId],
                    (current) =>
                      current
                        ? { ...current, tasks: [...current.tasks, task] }
                        : current,
                  )
                  setAddingTask(false)
                  await Promise.all([
                    queryClient.invalidateQueries({
                      queryKey: ['case', caseId],
                    }),
                    queryClient.invalidateQueries({ queryKey: ['tasks'] }),
                    queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
                    queryClient.invalidateQueries({ queryKey: ['activity'] }),
                    queryClient.invalidateQueries({
                      queryKey: ['manager', 'audit-events'],
                    }),
                  ])
                }}
              />
            )}
            {activeTaskCount === 0 && visibleTasks.length === 0 && (
              <div className="px-5 py-8 text-center">
                <CheckCircle2
                  className="mx-auto h-6 w-6 text-emerald-600"
                  aria-hidden
                />
                <p className="mt-2 text-sm font-semibold text-slate-900">
                  No active actions remaining
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Historical actions remain available from the controls above.
                </p>
              </div>
            )}
            <div className="divide-y divide-slate-100">
              {visibleTasks.map((task) => (
                <div
                  key={task.id}
                  data-task-status={task.status}
                  className={`flex flex-col items-stretch justify-between gap-4 px-5 py-4 sm:flex-row sm:items-start ${
                    task.status === 'DISMISSED' || task.status === 'COMPLETED'
                      ? 'bg-slate-50/80 text-slate-500'
                      : ''
                  }`}
                >
                  <div className="min-w-0">
                    <p
                      className={`font-medium ${
                        task.status === 'DISMISSED'
                          ? 'line-through decoration-slate-400'
                          : task.status === 'COMPLETED'
                            ? 'text-slate-600'
                            : ''
                      }`}
                    >
                      {task.title}
                    </p>
                    <p
                      className={`mt-1 text-sm ${
                        task.status === 'DISMISSED' ||
                        task.status === 'COMPLETED'
                          ? 'text-slate-500'
                          : 'text-slate-600'
                      }`}
                    >
                      {task.description}
                    </p>
                    {task.due_at && (
                      <p className="mt-2 text-xs text-slate-500">
                        Due {formatBusinessDate(task.due_at)}
                      </p>
                    )}
                    {task.is_manual && task.created_by && (
                      <p className="mt-2 text-xs text-slate-500">
                        Added manually by {task.created_by.full_name} ·{' '}
                        {formatDate(task.created_at)}
                      </p>
                    )}
                    {task.completed_by && task.completed_at && (
                      <p className="mt-1 text-xs text-emerald-700">
                        Completed by {task.completed_by.full_name} ·{' '}
                        {formatDate(task.completed_at)}
                      </p>
                    )}
                  </div>
                  <div className="w-full shrink-0 border-t border-slate-100 pt-3 text-left sm:w-auto sm:border-t-0 sm:pt-0 sm:text-right">
                    <StatusBadge status={task.status} />
                    <label className="sr-only" htmlFor={`case-task-${task.id}`}>
                      Update {task.title}
                    </label>
                    {!item.dismissed_at &&
                    !item.completed_at &&
                    !isManager &&
                    task.assigned_agent.id === auth.data!.user.id ? (
                      <select
                        id={`case-task-${task.id}`}
                        className="mt-2 block w-full border border-slate-300 bg-white px-2 py-1.5 text-sm sm:w-auto"
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
                      <p className="mt-2 text-xs text-slate-500 sm:max-w-40">
                        {item.completed_at
                          ? 'Reopen the Case to update this action'
                          : `Status managed by ${task.assigned_agent.full_name}`}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="surface-panel">
            <div className="section-titlebar">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                  <Mail className="h-[18px] w-[18px]" aria-hidden />
                </span>
                <div>
                  <h2 className="font-semibold">Carrier communications</h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Source messages associated with this policy
                  </p>
                </div>
              </div>
            </div>
            <div className="divide-y divide-slate-100">
              {item.messages.map((message) => (
                <article
                  key={message.id}
                  className="communication-timeline-item relative px-5 py-5 pl-16"
                >
                  <span className="absolute top-6 left-5 flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
                    <Mail className="h-3.5 w-3.5" aria-hidden />
                  </span>
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
                  <p className="mt-3 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                    AI analysis
                  </p>
                  <p className="mt-1 text-sm leading-6 text-slate-700">
                    {message.summary ??
                      pendingAnalysisSummary(message.processing_status)}
                  </p>
                  {message.review_id && (
                    <Link
                      className="mt-2 inline-block text-sm font-semibold text-blue-700"
                      to={`/reviews/${message.review_id}`}
                    >
                      Review analysis
                    </Link>
                  )}
                  {(message.analysis_confidence !== null ||
                    message.validation_flags.length > 0) && (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-xs font-semibold text-slate-600">
                        Technical analysis details
                      </summary>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                        {message.analysis_confidence !== null && (
                          <span>
                            AI&apos;s analysis confidence:{' '}
                            {Math.round(message.analysis_confidence * 100)}%
                          </span>
                        )}
                        {message.validation_flags.map((flag) => (
                          <StatusBadge key={flag} status={flag} />
                        ))}
                      </div>
                    </details>
                  )}
                  <details className="mt-4 border-t border-slate-100 pt-3">
                    <summary className="cursor-pointer text-sm font-semibold text-blue-800">
                      View email content
                    </summary>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                      {message.cleaned_content}
                    </p>
                  </details>
                </article>
              ))}
            </div>
          </div>
          <div className="surface-panel">
            <div className="section-titlebar">
              <div className="flex items-center gap-3">
                <Paperclip className="h-5 w-5 text-blue-600" aria-hidden />
                <h2 className="font-semibold">Attachments</h2>
              </div>
            </div>
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
          <div className="surface-panel">
            <div className="section-titlebar">
              <div className="flex items-center gap-3">
                <ShieldCheck className="h-5 w-5 text-blue-600" aria-hidden />
                <div>
                  <h2 className="font-semibold">Evidence</h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Source-backed extracted values
                  </p>
                </div>
              </div>
            </div>
            <div className="divide-y divide-slate-100">
              {item.evidence.length ? (
                groupEvidence(item.evidence).map(([source, evidenceItems]) => (
                  <div key={source} className="px-5 py-4">
                    <h3 className="text-sm font-semibold">{source}</h3>
                    <p className="mt-2 text-xs text-slate-600">
                      {[
                        ...new Set(
                          evidenceItems.map((evidence) =>
                            humanFieldLabel(evidence.field_name),
                          ),
                        ),
                      ].join(' · ')}
                    </p>
                    <details className="mt-3">
                      <summary className="cursor-pointer text-xs font-semibold text-blue-700">
                        View source excerpts
                      </summary>
                      <div className="mt-2 space-y-2 text-sm text-slate-700">
                        {evidenceItems.map((evidence) => (
                          <blockquote
                            key={evidence.id}
                            className="rounded-r-lg border-l-2 border-blue-300 bg-blue-50/60 px-3 py-2 text-sm leading-6 text-slate-700"
                          >
                            “{evidence.excerpt}”
                          </blockquote>
                        ))}
                      </div>
                    </details>
                  </div>
                ))
              ) : (
                <p className="p-5 text-sm text-slate-600">
                  No evidence excerpts recorded.
                </p>
              )}
            </div>
          </div>
          <div className="surface-panel">
            <div className="section-titlebar">
              <div className="flex items-center gap-3">
                <Activity className="h-5 w-5 text-blue-600" aria-hidden />
                <div>
                  <h2 className="font-semibold">Activity</h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Auditable case history
                  </p>
                </div>
              </div>
            </div>
            <div className="max-h-[30rem] overflow-y-auto px-5 py-2">
              {item.activity.map((event) => (
                <div
                  key={event.id}
                  className="relative border-l border-slate-200 py-3 pl-5"
                >
                  <span className="absolute top-4 -left-1 h-2 w-2 rounded-full bg-blue-600 ring-4 ring-blue-50" />
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
