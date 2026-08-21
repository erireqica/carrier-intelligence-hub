import { useQuery } from '@tanstack/react-query'

import { useCurrentUser } from '../../app/auth'
import {
  Badge,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { getAgents } from '../../lib/api'

export function AgentsPage() {
  const auth = useCurrentUser()
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
      <div className="hidden overflow-x-auto border border-slate-200 bg-white md:block">
        <table className="w-full min-w-[850px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Open tasks</th>
              <th className="px-4 py-3">Urgent cases</th>
              <th className="px-4 py-3">Connected inboxes</th>
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
                <td className="px-4 py-4">
                  {agent.gmail_connections} connected
                </td>
                <td className="px-4 py-4">
                  {formatDateTime(
                    agent.last_login_at,
                    auth.data!.user.agency.timezone,
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-3 md:hidden">
        {agents.data.map((agent) => (
          <article
            key={agent.id}
            className="border border-slate-200 bg-white p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">{agent.full_name}</h2>
                <p className="text-xs text-slate-500">{agent.email}</p>
              </div>
              <StatusBadge status={agent.is_active ? 'ACTIVE' : 'DISABLED'} />
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-slate-500">Role</dt>
                <dd>{agent.role}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Open tasks</dt>
                <dd>{agent.open_tasks}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Urgent cases</dt>
                <dd>{agent.urgent_cases}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Connected inboxes</dt>
                <dd>{agent.gmail_connections} connected</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-slate-500">Last login</dt>
                <dd>
                  {formatDateTime(
                    agent.last_login_at,
                    auth.data!.user.agency.timezone,
                  )}
                </dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </div>
  )
}
