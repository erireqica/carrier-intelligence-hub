import { useQuery } from '@tanstack/react-query'

import {
  Badge,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { formatDate } from '../../lib/format'
import { getAgents } from '../../lib/api'

export function AgentsPage() {
  const agents = useQuery({
    queryKey: ['manager', 'agents'],
    queryFn: getAgents,
  })
  if (agents.isPending) return <LoadingState label="Loading agency users…" />
  if (agents.isError)
    return (
      <ErrorState
        message={agents.error.message}
        retry={() => agents.refetch()}
      />
    )
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency"
        title="Agents"
        description="Internal users and their current operational workload."
      />
      <div className="overflow-x-auto border border-slate-200 bg-white">
        <table className="w-full min-w-[850px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Open tasks</th>
              <th className="px-4 py-3">Urgent cases</th>
              <th className="px-4 py-3">Gmail</th>
              <th className="px-4 py-3">Last login</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {agents.data.map((agent) => (
              <tr key={agent.id}>
                <td className="px-4 py-4 font-medium">
                  {agent.full_name}
                  <p className="text-xs font-normal text-slate-500">
                    {agent.email}
                  </p>
                </td>
                <td className="px-4 py-4">
                  <Badge tone="blue">{agent.role}</Badge>
                </td>
                <td className="px-4 py-4">
                  <StatusBadge
                    status={agent.is_active ? 'ACTIVE' : 'DISABLED'}
                  />
                </td>
                <td className="px-4 py-4">{agent.open_tasks}</td>
                <td className="px-4 py-4">{agent.urgent_cases}</td>
                <td className="px-4 py-4">{agent.gmail_connections}</td>
                <td className="px-4 py-4">{formatDate(agent.last_login_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
