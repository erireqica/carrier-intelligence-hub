import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { useCurrentUser } from '../app/auth'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { businessDaysFromToday, formatBusinessDate } from '../lib/format'
import { getAgents, getTasks, reassignTask, updateTask } from '../lib/api'
import type { TaskStatus } from '../lib/types'

type TaskView = 'TODO' | 'COMPLETED' | 'DISMISSED' | 'ALL'

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
  const params = new URLSearchParams({ page_size: '100', view })
  if (priority) params.set('priority', priority)
  if (overdue) params.set('overdue', 'true')
  if (agentId) params.set('assigned_agent_id', agentId)
  const tasks = useQuery({
    queryKey: ['tasks', view, priority, overdue, agentId],
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
  const assignmentMutation = useMutation({
    mutationFn: ({ id, agent }: { id: number; agent: number }) =>
      reassignTask(id, agent),
    onSuccess: refresh,
  })
  if (tasks.isPending) return <LoadingState label="Loading tasks…" />
  if (tasks.isError)
    return (
      <ErrorState message={tasks.error.message} retry={() => tasks.refetch()} />
    )
  const eligibleAgents = agents.data?.filter((agent) => agent.role === 'AGENT')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tasks"
        description={
          isManager
            ? 'Monitor work and reassign it when needed.'
            : 'Your current policy follow-up work.'
        }
      />
      <div className="flex flex-wrap gap-2" aria-label="Task views">
        {(
          [
            ['TODO', 'To do'],
            ['COMPLETED', 'Completed'],
            ['DISMISSED', 'Dismissed'],
            ['ALL', 'All'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            className={`border px-4 py-2 text-sm font-semibold ${view === value ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white text-slate-700'}`}
            onClick={() => setView(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-3 border border-slate-200 bg-white p-4">
        <select
          aria-label="Task priority"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={priority}
          onChange={(event) => setPriority(event.target.value)}
        >
          <option value="">All priorities</option>
          {['URGENT', 'HIGH', 'NORMAL', 'LOW'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        {isManager && (
          <select
            aria-label="Assigned agent"
            className="border border-slate-300 bg-white px-3 py-2 text-sm"
            value={agentId}
            onChange={(event) => setAgentId(event.target.value)}
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
            onChange={(event) => setOverdue(event.target.checked)}
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
        <div className="overflow-x-auto border border-slate-200 bg-white">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-3">Task</th>
                <th className="px-4 py-3">Client / policy</th>
                <th className="px-4 py-3">Priority</th>
                <th className="px-4 py-3">Due</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Assigned agent</th>
                <th className="px-4 py-3">Controls</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.data.items.map((task) => (
                <tr key={task.id}>
                  <td className="px-4 py-4 font-medium">{task.title}</td>
                  <td className="px-4 py-4">
                    {task.client_name}
                    <p className="text-xs text-slate-500">
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
                  <td className="px-4 py-4">{task.assigned_agent.full_name}</td>
                  <td className="px-4 py-4">
                    {isManager ? (
                      <div className="space-y-2">
                        {task.assigned_agent.id === auth.data!.user.id ? (
                          <select
                            aria-label={`Update ${task.title}`}
                            className="block border border-slate-300 bg-white px-2 py-1.5"
                            value={task.status}
                            disabled={statusMutation.isPending}
                            onChange={(event) =>
                              statusMutation.mutate({
                                id: task.id,
                                status: event.target.value as TaskStatus,
                              })
                            }
                          >
                            {[
                              'OPEN',
                              'IN_PROGRESS',
                              'COMPLETED',
                              'DISMISSED',
                            ].map((status) => (
                              <option key={status} value={status}>
                                {status.replaceAll('_', ' ')}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <p className="text-xs text-slate-500">
                            Status managed by assignee
                          </p>
                        )}
                        <select
                          aria-label={`Reassign ${task.title}`}
                          className="border border-slate-300 bg-white px-2 py-1.5"
                          value={task.assigned_agent.id}
                          disabled={assignmentMutation.isPending}
                          onChange={(event) =>
                            assignmentMutation.mutate({
                              id: task.id,
                              agent: Number(event.target.value),
                            })
                          }
                        >
                          {!eligibleAgents?.some(
                            (agent) => agent.id === task.assigned_agent.id,
                          ) && (
                            <option value={task.assigned_agent.id} disabled>
                              {task.assigned_agent.full_name} (current —
                              manager)
                            </option>
                          )}
                          {eligibleAgents?.map((agent) => (
                            <option key={agent.id} value={agent.id}>
                              {agent.full_name}
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <select
                        aria-label={`Update ${task.title}`}
                        className="border border-slate-300 bg-white px-2 py-1.5"
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
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(statusMutation.error ?? assignmentMutation.error) && (
        <p className="text-sm text-red-700" role="alert">
          {(statusMutation.error ?? assignmentMutation.error)!.message}
        </p>
      )}
    </div>
  )
}
