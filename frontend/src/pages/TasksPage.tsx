import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ArrowUpRight, ListChecks } from 'lucide-react'

import { useCurrentUser } from '../app/auth'
import { Avatar } from '../components/Avatar'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { businessDaysFromToday, formatBusinessDate } from '../lib/format'
import { getAgents, getTasks, updateTask } from '../lib/api'
import type { TaskStatus } from '../lib/types'

type TaskView =
  'TODO' | 'IN_PROGRESS' | 'OPEN' | 'COMPLETED' | 'DISMISSED' | 'ALL'

function dueState(dueAt: string | null, status: TaskStatus, timezone: string) {
  if (!dueAt || ['COMPLETED', 'DISMISSED'].includes(status)) return null
  const days = businessDaysFromToday(dueAt, timezone)
  if (days !== null && days < 0)
    return <span className="text-xs font-semibold text-red-700">Overdue</span>
  if (days !== null && days <= 7)
    return (
      <span className="text-xs font-semibold text-amber-700">Due soon</span>
    )
  return null
}

export function TasksPage() {
  const auth = useCurrentUser()
  const isManager = auth.data?.user.role === 'MANAGER'
  const queryClient = useQueryClient()
  const [view, setView] = useState<TaskView>('TODO')
  const [priority, setPriority] = useState('')
  const [overdue, setOverdue] = useState(false)
  const [agentId, setAgentId] = useState('')
  const [page, setPage] = useState(1)
  const params = new URLSearchParams({
    page_size: '10',
    page: String(page),
    view,
  })
  if (priority) params.set('priority', priority)
  if (overdue) params.set('overdue', 'true')
  if (agentId) params.set('assigned_agent_id', agentId)
  const tasks = useQuery({
    queryKey: ['tasks', view, priority, overdue, agentId, page],
    queryFn: () => getTasks(params.toString()),
  })
  const agents = useQuery({
    queryKey: ['manager', 'agents'],
    queryFn: getAgents,
    enabled: isManager,
  })
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['tasks'] })
    await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    await queryClient.invalidateQueries({ queryKey: ['activity'] })
    await queryClient.invalidateQueries({
      queryKey: ['manager', 'audit-events'],
    })
  }
  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TaskStatus }) =>
      updateTask(id, status),
    onSuccess: refresh,
  })
  if (tasks.isPending) return <LoadingState label="Loading tasks…" />
  if (tasks.isError)
    return (
      <ErrorState message={tasks.error.message} retry={() => tasks.refetch()} />
    )
  const eligibleAgents = agents.data?.filter((agent) => agent.role === 'AGENT')

  return (
    <div className="app-page space-y-6">
      <PageHeader
        eyebrow={isManager ? 'Agency execution' : 'My work queue'}
        title="Tasks"
        description={
          isManager
            ? 'Monitor agency task status and workload.'
            : 'Your current policy follow-up work.'
        }
      />
      <div className="filter-toolbar flex flex-wrap items-center gap-3">
        <span className="mr-1 flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-white">
          <ListChecks className="h-4 w-4" aria-hidden />
        </span>
        <select
          aria-label="Task status"
          className="px-3 py-2 text-sm"
          value={view}
          onChange={(event) => {
            setView(event.target.value as TaskView)
            setPage(1)
          }}
        >
          <option value="TODO">To do</option>
          <option value="IN_PROGRESS">In progress</option>
          <option value="OPEN">Open</option>
          <option value="COMPLETED">Completed</option>
          <option value="DISMISSED">Dismissed</option>
          <option value="ALL">All statuses</option>
        </select>
        <select
          aria-label="Task priority"
          className="px-3 py-2 text-sm"
          value={priority}
          onChange={(event) => {
            setPriority(event.target.value)
            setPage(1)
          }}
        >
          <option value="">All priorities</option>
          {['URGENT', 'HIGH', 'NORMAL', 'LOW'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        {isManager && (
          <select
            aria-label="Assigned agent"
            className="px-3 py-2 text-sm"
            value={agentId}
            onChange={(event) => {
              setAgentId(event.target.value)
              setPage(1)
            }}
          >
            <option value="">All agents</option>
            {eligibleAgents?.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.full_name}
              </option>
            ))}
          </select>
        )}
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={overdue}
            onChange={(event) => {
              setOverdue(event.target.checked)
              setPage(1)
            }}
          />{' '}
          Overdue only
        </label>
      </div>
      {tasks.data.items.length === 0 ? (
        <EmptyState
          title="You're all caught up."
          description="No tasks match this view."
        />
      ) : (
        <div className="data-table-shell">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-3">Task</th>
                <th className="px-4 py-3">Client / policy</th>
                <th className="px-4 py-3">Priority</th>
                <th className="px-4 py-3">Due</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Assigned agent</th>
                {!isManager && <th className="px-4 py-3">Controls</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.data.items.map((task) => (
                <tr key={task.id} className="group hover:bg-blue-50/30">
                  <td className="relative px-4 py-4 pl-6 font-medium">
                    <span
                      className={`absolute inset-y-3 left-0 w-1 rounded-r ${task.priority === 'URGENT' ? 'bg-red-500' : task.priority === 'HIGH' ? 'bg-amber-500' : 'bg-blue-500'}`}
                    />
                    <p className="font-semibold text-slate-900">{task.title}</p>
                    {task.description && (
                      <p className="mt-1 max-w-sm line-clamp-2 text-xs font-normal leading-5 text-slate-500">
                        {task.description}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-4">
                    <a
                      className="inline-flex items-center gap-1 font-semibold text-slate-900 hover:text-blue-700"
                      href={`/cases/${task.case_id}`}
                    >
                      {task.client_name}
                      <ArrowUpRight
                        className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100"
                        aria-hidden
                      />
                    </a>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {task.policy_number}
                    </p>
                  </td>
                  <td className="px-4 py-4">
                    <PriorityBadge priority={task.priority} />
                  </td>
                  <td className="px-4 py-4">
                    {formatBusinessDate(task.due_at)}
                    <div className="mt-1">
                      {dueState(
                        task.due_at,
                        task.status,
                        auth.data!.user.agency.timezone,
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <StatusBadge status={task.status} />
                  </td>
                  <td className="px-4 py-4">
                    <span className="flex items-center gap-2">
                      <Avatar user={task.assigned_agent} size="sm" />
                      <span>{task.assigned_agent.full_name}</span>
                    </span>
                  </td>
                  {!isManager && (
                    <td className="px-4 py-4">
                      <select
                        aria-label={`Update ${task.title}`}
                        className="px-2 py-1.5"
                        value={task.status}
                        disabled={statusMutation.isPending}
                        onChange={(event) =>
                          statusMutation.mutate({
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
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {statusMutation.error && (
        <p className="text-sm text-red-700" role="alert">
          {statusMutation.error.message}
        </p>
      )}
      <Pagination
        page={tasks.data.page.page}
        pages={tasks.data.page.pages}
        onPageChange={setPage}
        label="Task pagination"
      />
    </div>
  )
}
