import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useCurrentUser } from '../../app/auth'
import {
  Badge,
  Button,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  StatusBadge,
} from '../../components/ui'
import {
  createAgent,
  getAgentsPage,
  removeAgent,
  setAgentEnabled,
} from '../../lib/api'
import { formatDateTime } from '../../lib/format'

const emptyAgent = {
  full_name: '',
  email: '',
  initial_password: '',
  confirm_initial_password: '',
}

export function AgentsPage() {
  const auth = useCurrentUser()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [showCreate, setShowCreate] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [form, setForm] = useState(emptyAgent)
  const agents = useQuery({
    queryKey: ['manager', 'agents', page],
    queryFn: () => getAgentsPage(page),
  })
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['manager', 'agents'] })
  const refreshAndClamp = async () => {
    const updated = await getAgentsPage(page)
    queryClient.setQueryData(['manager', 'agents', page], updated)
    if (updated.page.page !== page) setPage(updated.page.page)
  }
  const create = useMutation({
    mutationFn: createAgent,
    onSuccess: async () => {
      setForm(emptyAgent)
      setShowCreate(false)
      setPage(1)
      await refresh()
    },
  })
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      setAgentEnabled(id, enabled),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: removeAgent,
    onSuccess: refreshAndClamp,
  })
  if (agents.isPending) return <LoadingState label="Loading agency users…" />
  if (agents.isError)
    return (
      <ErrorState
        message={agents.error.message}
        retry={() => agents.refetch()}
      />
    )
  const error = create.error ?? toggle.error ?? remove.error
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency"
        title="Agents"
        description="Create Agent access and manage current operational accounts."
        action={
          <Button onClick={() => setShowCreate((value) => !value)}>
            Add agent
          </Button>
        }
      />
      {showCreate && (
        <form
          className="grid gap-4 border border-slate-200 bg-white p-5 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            create.mutate(form)
          }}
        >
          {[
            ['Full name', 'full_name', 'text'],
            ['Login email', 'email', 'email'],
            [
              'Initial password',
              'initial_password',
              showPassword ? 'text' : 'password',
            ],
            [
              'Confirm initial password',
              'confirm_initial_password',
              showPassword ? 'text' : 'password',
            ],
          ].map(([label, field, type]) => (
            <label key={field} className="text-sm font-medium">
              {label}
              <input
                className="mt-1 w-full border border-slate-300 px-3 py-2"
                type={type}
                minLength={field.includes('password') ? 12 : undefined}
                value={form[field as keyof typeof form]}
                onChange={(event) =>
                  setForm({ ...form, [field]: event.target.value })
                }
                required
              />
            </label>
          ))}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={showPassword}
              onChange={(event) => setShowPassword(event.target.checked)}
            />{' '}
            Show password
          </label>
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              type="button"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              Create agent
            </Button>
          </div>
        </form>
      )}
      {error && (
        <p className="border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error.message}
        </p>
      )}
      <div className="overflow-x-auto border border-slate-200 bg-white">
        <table className="w-full min-w-[980px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
            <tr>
              {[
                'User',
                'Role',
                'Status',
                'Open tasks',
                'Urgent cases',
                'Connected inboxes',
                'Last login',
                'Actions',
              ].map((label) => (
                <th key={label} className="px-4 py-3">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {agents.data.items.map((agent) => (
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
                <td className="px-4 py-4">
                  {agent.role === 'AGENT' && (
                    <div className="flex gap-2">
                      <Button
                        variant={agent.is_active ? 'danger' : 'success'}
                        onClick={() =>
                          toggle.mutate({
                            id: agent.id,
                            enabled: !agent.is_active,
                          })
                        }
                      >
                        {agent.is_active ? 'Disable' : 'Enable'}
                      </Button>
                      <Button
                        variant="dangerSecondary"
                        onClick={() => {
                          if (
                            window.confirm(
                              `Remove ${agent.full_name}? This permanently removes login access, preserves history, and cannot be undone.`,
                            )
                          )
                            remove.mutate(agent.id)
                        }}
                      >
                        Remove
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination
        page={agents.data.page.page}
        pages={agents.data.page.pages}
        onPageChange={setPage}
        label="Agents pagination"
      />
    </div>
  )
}
