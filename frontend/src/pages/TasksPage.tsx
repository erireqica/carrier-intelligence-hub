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
import { formatDate } from '../lib/format'
import { getAgents, getTasks, updateTask } from '../lib/api'
import type { TaskStatus } from '../lib/types'

function dueState(dueAt: string | null, status: TaskStatus) {
  if (!dueAt || ['COMPLETED', 'DISMISSED'].includes(status)) return null
  const days = (new Date(dueAt).getTime() - Date.now()) / 86_400_000
  if (days < 0)
    return <span className="text-xs font-semibold text-red-700">Overdue</span>
  if (days <= 7)
    return (
      <span className="text-xs font-semibold text-amber-700">Due soon</span>
    )
  return null
}

export function TasksPage() {
  const auth = useCurrentUser()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [overdue, setOverdue] = useState(false)
  const [agentId, setAgentId] = useState('')
  const params = new URLSearchParams({ page_size: '100' })
  if (status) params.set('status', status)
  if (priority) params.set('priority', priority)
  if (overdue) params.set('overdue', 'true')
  if (agentId) params.set('assigned_agent_id', agentId)
  const tasks = useQuery({
    queryKey: ['tasks', status, priority, overdue, agentId],
    queryFn: () => getTasks(params.toString()),
  })
  const agents = useQuery({
    queryKey: ['manager', 'agents'],
    queryFn: getAgents,
    enabled: auth.data?.user.role === 'MANAGER',
  })
  const mutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TaskStatus }) =>
      updateTask(id, status),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['tasks'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  if (tasks.isPending) return <LoadingState label="Loading tasks…" />
  if (tasks.isError)
    return (
      <ErrorState message={tasks.error.message} retry={() => tasks.refetch()} />
    )
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Action management"
        title="Tasks"
        description="Operational follow-up linked to the case and carrier message that created it."
      />
      <div className="flex flex-wrap gap-3 border border-slate-200 bg-white p-4">
        <select
          aria-label="Task status"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">All statuses</option>
          {['OPEN', 'IN_PROGRESS', 'COMPLETED', 'DISMISSED'].map((value) => (
            <option key={value} value={value}>
              {value.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
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
        {auth.data?.user.role === 'MANAGER' && (
          <select
            aria-label="Assigned agent"
            className="border border-slate-300 bg-white px-3 py-2 text-sm"
            value={agentId}
            onChange={(event) => setAgentId(event.target.value)}
          >
            <option value="">All agents</option>
            {agents.data?.map((agent) => (
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
        {(status || priority || overdue || agentId) && (
          <button
            className="text-sm font-semibold text-blue-700"
            onClick={() => {
              setStatus('')
              setPriority('')
              setOverdue(false)
              setAgentId('')
            }}
          >
            Reset filters
          </button>
        )}
      </div>
      {tasks.data.items.length === 0 ? (
        <EmptyState
          title="You're all caught up."
          description="No tasks match your current scope."
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
                <th className="px-4 py-3">Assigned</th>
                <th className="px-4 py-3">Update</th>
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
                    {formatDate(task.due_at)}
                    <div className="mt-1">
                      {dueState(task.due_at, task.status)}
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <StatusBadge status={task.status} />
                  </td>
                  <td className="px-4 py-4">{task.assigned_agent.full_name}</td>
                  <td className="px-4 py-4">
                    <label className="sr-only" htmlFor={`task-${task.id}`}>
                      Update {task.title}
                    </label>
                    <select
                      id={`task-${task.id}`}
                      className="border border-slate-300 bg-white px-2 py-1.5"
                      value={task.status}
                      disabled={mutation.isPending}
                      onChange={(event) =>
                        mutation.mutate({
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
