import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Metric,
  PageHeader,
  StatusBadge,
} from '../components/ui'
import { formatDate } from '../lib/format'
import {
  addCarrierDomain,
  addCarrierSender,
  createCarrier,
  getAgents,
  getAnalytics,
  getAuditLogs,
  getCarriers,
  removeCarrierDomain,
  removeCarrierSender,
  setCarrierDomainEnabled,
  setCarrierSenderEnabled,
  updateCarrier,
} from '../lib/api'
import type { CarrierItem } from '../lib/types'

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

function CarrierCard({ carrier }: { carrier: CarrierItem }) {
  const queryClient = useQueryClient()
  const [domain, setDomain] = useState('')
  const [sender, setSender] = useState('')
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(carrier.name)
  const [code, setCode] = useState(carrier.code ?? '')
  const [notes, setNotes] = useState(carrier.notes ?? '')
  const mutation = useMutation({
    mutationFn: (updated: CarrierItem) => updateCarrier(updated),
    onSuccess: async () => {
      setEditing(false)
      await queryClient.invalidateQueries({ queryKey: ['manager', 'carriers'] })
    },
  })
  const domainMutation = useMutation({
    mutationFn: () => addCarrierDomain(carrier.id, domain),
    onSuccess: async () => {
      setDomain('')
      await queryClient.invalidateQueries({ queryKey: ['manager', 'carriers'] })
    },
  })
  const senderMutation = useMutation({
    mutationFn: () => addCarrierSender(carrier.id, sender),
    onSuccess: async () => {
      setSender('')
      await queryClient.invalidateQueries({ queryKey: ['manager', 'carriers'] })
    },
  })
  const whitelistMutation = useMutation({
    mutationFn: ({
      kind,
      id,
      enabled,
      remove,
    }: {
      kind: 'domain' | 'sender'
      id: number
      enabled: boolean
      remove?: boolean
    }) => {
      if (kind === 'domain') {
        return remove
          ? removeCarrierDomain(carrier.id, id)
          : setCarrierDomainEnabled(carrier.id, id, enabled)
      }
      return remove
        ? removeCarrierSender(carrier.id, id)
        : setCarrierSenderEnabled(carrier.id, id, enabled)
    },
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ['manager', 'carriers'] }),
  })
  return (
    <article className="border border-slate-200 bg-white">
      <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
        {editing ? (
          <form
            className="grid flex-1 gap-3 sm:grid-cols-[1fr_140px]"
            onSubmit={(event) => {
              event.preventDefault()
              mutation.mutate({ ...carrier, name, code, notes })
            }}
          >
            <label className="text-sm font-medium">
              Carrier name
              <Input
                className="mt-1"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </label>
            <label className="text-sm font-medium">
              Code
              <Input
                className="mt-1"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
            </label>
            <label className="text-sm font-medium sm:col-span-2">
              Notes
              <Input
                className="mt-1"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </label>
            <div className="flex gap-2 sm:col-span-2">
              <Button type="submit" disabled={mutation.isPending}>
                Save
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setEditing(false)}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-semibold">{carrier.name}</h2>
              <StatusBadge
                status={carrier.is_enabled ? 'ACTIVE' : 'DISABLED'}
              />
            </div>
            <p className="mt-1 text-sm text-slate-500">
              {carrier.code} · {carrier.notes}
            </p>
          </div>
        )}
        {!editing && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Button
              variant="secondary"
              onClick={() =>
                mutation.mutate({ ...carrier, is_enabled: !carrier.is_enabled })
              }
            >
              {carrier.is_enabled ? 'Disable' : 'Enable'}
            </Button>
          </div>
        )}
      </header>
      <div className="grid gap-6 p-5 lg:grid-cols-2">
        <section>
          <h3 className="text-sm font-semibold">Approved domains</h3>
          <ul className="mt-3 space-y-2">
            {carrier.domains.map((item) => (
              <li
                key={item.id}
                className="flex justify-between border border-slate-200 px-3 py-2 text-sm"
              >
                <span>{item.domain}</span>
                <span className="flex items-center gap-2">
                  <StatusBadge
                    status={item.is_enabled ? 'ACTIVE' : 'DISABLED'}
                  />
                  <button
                    className="font-medium text-blue-700 hover:underline"
                    onClick={() =>
                      whitelistMutation.mutate({
                        kind: 'domain',
                        id: item.id,
                        enabled: !item.is_enabled,
                      })
                    }
                  >
                    {item.is_enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    className="font-medium text-red-700 hover:underline"
                    onClick={() =>
                      whitelistMutation.mutate({
                        kind: 'domain',
                        id: item.id,
                        enabled: false,
                        remove: true,
                      })
                    }
                  >
                    Remove
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              domainMutation.mutate()
            }}
          >
            <label className="sr-only" htmlFor={`domain-${carrier.id}`}>
              Add domain
            </label>
            <Input
              id={`domain-${carrier.id}`}
              placeholder="carrier.example"
              value={domain}
              onChange={(event) => setDomain(event.target.value)}
              required
            />
            <Button type="submit" variant="secondary">
              Add
            </Button>
          </form>
          {domainMutation.isError && (
            <p className="mt-2 text-xs text-red-700">
              {domainMutation.error.message}
            </p>
          )}
        </section>
        <section>
          <h3 className="text-sm font-semibold">Approved exact senders</h3>
          {carrier.senders.length ? (
            <ul className="mt-3 space-y-2">
              {carrier.senders.map((item) => (
                <li
                  key={item.id}
                  className="flex justify-between border border-slate-200 px-3 py-2 text-sm"
                >
                  <span>{item.email}</span>
                  <span className="flex items-center gap-2">
                    <StatusBadge
                      status={item.is_enabled ? 'ACTIVE' : 'DISABLED'}
                    />
                    <button
                      className="font-medium text-blue-700 hover:underline"
                      onClick={() =>
                        whitelistMutation.mutate({
                          kind: 'sender',
                          id: item.id,
                          enabled: !item.is_enabled,
                        })
                      }
                    >
                      {item.is_enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button
                      className="font-medium text-red-700 hover:underline"
                      onClick={() =>
                        whitelistMutation.mutate({
                          kind: 'sender',
                          id: item.id,
                          enabled: false,
                          remove: true,
                        })
                      }
                    >
                      Remove
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-slate-500">
              No exact sender addresses configured.
            </p>
          )}
          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              senderMutation.mutate()
            }}
          >
            <label className="sr-only" htmlFor={`sender-${carrier.id}`}>
              Add sender
            </label>
            <Input
              id={`sender-${carrier.id}`}
              type="email"
              placeholder="notices@carrier.example"
              value={sender}
              onChange={(event) => setSender(event.target.value)}
              required
            />
            <Button type="submit" variant="secondary">
              Add
            </Button>
          </form>
          {senderMutation.isError && (
            <p className="mt-2 text-xs text-red-700">
              {senderMutation.error.message}
            </p>
          )}
        </section>
      </div>
    </article>
  )
}

export function CarriersPage() {
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const queryClient = useQueryClient()
  const carriers = useQuery({
    queryKey: ['manager', 'carriers'],
    queryFn: getCarriers,
  })
  const createMutation = useMutation({
    mutationFn: () => createCarrier({ name, code, is_enabled: true }),
    onSuccess: async () => {
      setName('')
      setCode('')
      setShowForm(false)
      await queryClient.invalidateQueries({ queryKey: ['manager', 'carriers'] })
    },
  })
  if (carriers.isPending)
    return <LoadingState label="Loading carrier configuration…" />
  if (carriers.isError)
    return (
      <ErrorState
        message={carriers.error.message}
        retry={() => carriers.refetch()}
      />
    )
  function submit(event: FormEvent) {
    event.preventDefault()
    createMutation.mutate()
  }
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency configuration"
        title="Carriers & Whitelist"
        description="These database records will determine which senders are eligible for future Gmail processing."
        action={
          <Button onClick={() => setShowForm((value) => !value)}>
            {showForm ? 'Cancel' : 'Add carrier'}
          </Button>
        }
      />
      {showForm && (
        <form
          className="grid gap-4 border border-slate-200 bg-white p-5 sm:grid-cols-[1fr_180px_auto]"
          onSubmit={submit}
        >
          <label className="text-sm font-medium">
            Carrier name
            <Input
              className="mt-2"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </label>
          <label className="text-sm font-medium">
            Code
            <Input
              className="mt-2"
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
          </label>
          <Button
            className="self-end"
            type="submit"
            disabled={createMutation.isPending}
          >
            Create carrier
          </Button>
        </form>
      )}
      {carriers.data.length ? (
        <div className="space-y-5">
          {carriers.data.map((carrier) => (
            <CarrierCard key={carrier.id} carrier={carrier} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No carriers configured"
          description="Add an approved insurance carrier to begin building the whitelist."
        />
      )}
    </div>
  )
}

export function AnalyticsPage() {
  const analytics = useQuery({
    queryKey: ['manager', 'analytics'],
    queryFn: getAnalytics,
  })
  if (analytics.isPending)
    return <LoadingState label="Calculating agency analytics…" />
  if (analytics.isError)
    return (
      <ErrorState
        message={analytics.error.message}
        retry={() => analytics.refetch()}
      />
    )
  const data = analytics.data
  const lists = [
    ['Cases by status', data.cases_by_status],
    ['Cases by carrier', data.cases_by_carrier],
    ['Open workload by agent', data.workload_by_agent],
  ] as const
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency oversight"
        title="Analytics"
        description="Focused metrics calculated directly from current PostgreSQL records."
      />
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        <Metric
          label="Urgent / high"
          value={data.urgent_high_cases}
          attention
        />
        <Metric label="Open tasks" value={data.open_tasks} />
        <Metric label="Overdue" value={data.overdue_tasks} attention />
        <Metric label="Open reviews" value={data.open_reviews} />
        <Metric label="Processed" value={data.processed_messages} />
        <Metric label="Failed" value={data.failed_messages} attention />
      </section>
      <section className="grid gap-5 lg:grid-cols-3">
        {lists.map(([title, values]) => (
          <div key={title} className="border border-slate-200 bg-white">
            <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
              {title}
            </h2>
            <dl className="divide-y divide-slate-100">
              {Object.entries(values).map(([label, value]) => (
                <div
                  key={label}
                  className="flex justify-between px-5 py-3 text-sm"
                >
                  <dt>{label.replaceAll('_', ' ')}</dt>
                  <dd className="font-semibold">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </section>
    </div>
  )
}

export function SystemLogsPage() {
  const [severity, setSeverity] = useState('')
  const [eventType, setEventType] = useState('')
  const params = new URLSearchParams({ page_size: '100' })
  if (severity) params.set('severity', severity)
  if (eventType) params.set('event_type', eventType)
  const logs = useQuery({
    queryKey: ['manager', 'audit-events', severity, eventType],
    queryFn: () => getAuditLogs(params.toString()),
  })
  if (logs.isPending) return <LoadingState label="Loading system logs…" />
  if (logs.isError)
    return (
      <ErrorState message={logs.error.message} retry={() => logs.refetch()} />
    )
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Auditability"
        title="System Logs"
        description="Append-oriented operational and user events with safe metadata only."
      />
      <div className="flex flex-wrap gap-3 border border-slate-200 bg-white p-4">
        <select
          aria-label="Log severity"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={severity}
          onChange={(event) => setSeverity(event.target.value)}
        >
          <option value="">All severities</option>
          {['INFO', 'WARNING', 'ERROR'].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        <select
          aria-label="Log event type"
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={eventType}
          onChange={(event) => setEventType(event.target.value)}
        >
          <option value="">All event types</option>
          {[
            'USER_LOGIN',
            'USER_LOGOUT',
            'TASK_STATUS_CHANGED',
            'TASK_ASSIGNED',
            'CASE_REVIEWED',
            'CARRIER_CREATED',
            'CARRIER_UPDATED',
            'WHITELIST_UPDATED',
            'PROCESSING_FAILED',
          ].map((value) => (
            <option key={value}>{value.replaceAll('_', ' ')}</option>
          ))}
        </select>
        {(severity || eventType) && (
          <button
            className="text-sm font-semibold text-blue-700"
            onClick={() => {
              setSeverity('')
              setEventType('')
            }}
          >
            Reset filters
          </button>
        )}
      </div>
      <div className="overflow-x-auto border border-slate-200 bg-white">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-3">Timestamp</th>
              <th className="px-4 py-3">Severity</th>
              <th className="px-4 py-3">Event</th>
              <th className="px-4 py-3">Actor</th>
              <th className="px-4 py-3">Description</th>
              <th className="px-4 py-3">Record</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {logs.data.items.map((item) => (
              <tr key={item.id}>
                <td className="px-4 py-4">{formatDate(item.created_at)}</td>
                <td className="px-4 py-4">
                  <StatusBadge status={item.severity} />
                </td>
                <td className="px-4 py-4 text-xs font-semibold">
                  {item.event_type}
                </td>
                <td className="px-4 py-4">{item.actor_name ?? 'System'}</td>
                <td className="px-4 py-4">{item.description}</td>
                <td className="px-4 py-4">
                  {item.case_id ? (
                    <Link
                      className="font-semibold text-blue-700"
                      to={`/cases/${item.case_id}`}
                    >
                      Case {item.case_id}
                    </Link>
                  ) : item.task_id ? (
                    `Task ${item.task_id}`
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function SettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency configuration"
        title="Settings / Integrations"
        description="Reserved for deliberate external integration configuration."
      />
      <EmptyState
        title="No external integration configured"
        description="CRM webhook delivery and other external integrations are not implemented in this stage. No credentials or connectivity are being simulated."
      />
    </div>
  )
}
