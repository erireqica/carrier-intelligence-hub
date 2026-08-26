import { useQuery } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  PageHeader,
  Pagination,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { Avatar } from '../components/Avatar'
import { formatDate } from '../lib/format'
import { getAgents, getCases } from '../lib/api'
import { getEffectiveTimezone } from '../lib/timezone'
import type { CaseLifecycle } from '../lib/types'

const lifecycleOptions: Array<{
  value: CaseLifecycle
  label: string
  description: string
}> = [
  { value: 'ACTIVE', label: 'Active', description: 'Current operational work' },
  {
    value: 'COMPLETED',
    label: 'Completed',
    description: 'Finished case history',
  },
  {
    value: 'DISMISSED',
    label: 'Dismissed',
    description: 'Removed from active work',
  },
]

export function CasesPage() {
  const auth = useCurrentUser()
  const [searchParams, setSearchParams] = useSearchParams()
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [agentId, setAgentId] = useState('')
  const isManager = auth.data?.user.role === 'MANAGER'
  const lifecycleParam = searchParams.get('lifecycle')
  const lifecycle: CaseLifecycle = ['COMPLETED', 'DISMISSED'].includes(
    lifecycleParam ?? '',
  )
    ? (lifecycleParam as CaseLifecycle)
    : 'ACTIVE'
  const requestedPage = Number(searchParams.get('page') ?? '1')
  const page =
    Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1
  function navigate(nextLifecycle: CaseLifecycle, nextPage = 1) {
    const next = new URLSearchParams(searchParams)
    if (nextLifecycle === 'ACTIVE') next.delete('lifecycle')
    else next.set('lifecycle', nextLifecycle)
    if (nextPage === 1) next.delete('page')
    else next.set('page', String(nextPage))
    setSearchParams(next)
  }
  const params = new URLSearchParams({ page: String(page), page_size: '10' })
  params.set('lifecycle', lifecycle)
  if (search) params.set('search', search)
  if (status) params.set('policy_status', status)
  if (priority) params.set('priority', priority)
  if (agentId) params.set('assigned_agent_id', agentId)
  const cases = useQuery({
    queryKey: ['cases', search, status, priority, agentId, lifecycle, page],
    queryFn: () => getCases(params.toString()),
  })
  const agents = useQuery({
    queryKey: ['manager', 'agents'],
    queryFn: getAgents,
    enabled: isManager,
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    setSearch(searchInput.trim())
    navigate(lifecycle)
  }
  if (cases.isPending) return <LoadingState label="Loading cases…" />
  if (cases.isError)
    return (
      <ErrorState message={cases.error.message} retry={() => cases.refetch()} />
    )
  const eligibleAgents = agents.data?.filter((agent) => agent.role === 'AGENT')

  return (
    <div className="app-page space-y-6">
      <PageHeader
        eyebrow="Policy operations"
        title="Cases"
        description={
          lifecycle === 'COMPLETED'
            ? 'Finished operational Cases with their full policy history preserved.'
            : lifecycle === 'DISMISSED'
              ? 'Cases removed from active work without deleting their history.'
              : 'Active policy work created from approved carrier communications.'
        }
      />
      <div
        className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-1.5 sm:grid-cols-3"
        role="tablist"
        aria-label="Case lifecycle"
      >
        {lifecycleOptions.map((option) => {
          const selected = lifecycle === option.value
          return (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={selected}
              className={`rounded-lg border px-4 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:outline-none ${
                selected
                  ? 'border-slate-300 bg-white text-slate-950 shadow-sm'
                  : 'border-transparent text-slate-600 hover:bg-white/70 hover:text-slate-900'
              }`}
              onClick={() => navigate(option.value)}
            >
              <span className="block text-sm font-semibold">
                {option.label}
              </span>
              <span className="mt-0.5 block text-xs text-slate-500">
                {option.description}
              </span>
            </button>
          )
        })}
      </div>
      <form
        onSubmit={submit}
        className="filter-toolbar grid gap-3 lg:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_minmax(150px,180px)_minmax(140px,160px)_minmax(160px,180px)_auto]"
      >
        <label className="sr-only" htmlFor="case-search">
          Search cases
        </label>
        <Input
          id="case-search"
          placeholder="Search client or policy number"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
        />
        <label className="sr-only" htmlFor="case-status">
          Policy status
        </label>
        <select
          id="case-status"
          className="px-3 py-2 text-sm"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value)
            navigate(lifecycle)
          }}
        >
          <option value="">All statuses</option>
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
        <label className="sr-only" htmlFor="case-priority">
          Priority
        </label>
        <select
          id="case-priority"
          className="px-3 py-2 text-sm"
          value={priority}
          onChange={(event) => {
            setPriority(event.target.value)
            navigate(lifecycle)
          }}
        >
          <option value="">All priorities</option>
          {['URGENT', 'HIGH', 'NORMAL', 'LOW'].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        {isManager && (
          <>
            <label className="sr-only" htmlFor="case-agent">
              Assigned agent
            </label>
            <select
              id="case-agent"
              className="px-3 py-2 text-sm"
              value={agentId}
              onChange={(event) => {
                setAgentId(event.target.value)
                navigate(lifecycle)
              }}
            >
              <option value="">All agents</option>
              {eligibleAgents?.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.full_name}
                </option>
              ))}
            </select>
          </>
        )}
        <div className="flex gap-2">
          <Button type="submit" variant="secondary">
            Search
          </Button>
          {(search || status || priority || agentId) && (
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setSearchInput('')
                setSearch('')
                setStatus('')
                setPriority('')
                setAgentId('')
                navigate(lifecycle)
              }}
            >
              Reset
            </Button>
          )}
        </div>
      </form>
      {cases.data.items.length === 0 ? (
        <EmptyState
          title={
            search || status || priority || agentId
              ? 'No cases match your filters'
              : lifecycle === 'COMPLETED'
                ? 'No completed cases yet'
                : lifecycle === 'DISMISSED'
                  ? 'No dismissed cases'
                  : 'No active carrier cases yet'
          }
          description={
            search || status || priority || agentId
              ? 'Adjust or reset the search and filters.'
              : lifecycle === 'COMPLETED'
                ? 'Cases explicitly completed by their assigned agent will appear here.'
                : lifecycle === 'DISMISSED'
                  ? 'Dismissed Cases will remain available here with their history intact.'
                  : 'Cases will appear after approved carrier communications are processed.'
          }
        />
      ) : (
        <div className="data-table-shell responsive-data-table">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-3">Client / policy</th>
                <th className="px-4 py-3">Carrier</th>
                <th className="px-4 py-3">Policy Status</th>
                <th className="px-4 py-3">Priority</th>
                <th className="px-4 py-3">Assigned agent</th>
                <th className="px-4 py-3">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {cases.data.items.map((item) => (
                <tr key={item.id} className="hover:bg-slate-50">
                  <td className="px-4 py-4" data-label="Case">
                    <Link
                      className="font-semibold text-blue-800"
                      to={`/cases/${item.id}`}
                    >
                      {item.client_name}
                    </Link>
                    <p className="mt-1 text-xs text-slate-500">
                      <span className="sm:hidden">{item.carrier.name} · </span>
                      {item.policy_number ?? 'Policy number pending'}
                      {item.needs_review ? ' · Needs review' : ''}
                    </p>
                    {item.dismissed_at && (
                      <span className="mt-2 inline-flex">
                        <Badge tone="red">DISMISSED</Badge>
                      </span>
                    )}
                    {!item.dismissed_at && item.completed_at && (
                      <span className="mt-2 inline-flex">
                        <Badge tone="green">COMPLETED</Badge>
                      </span>
                    )}
                  </td>
                  <td
                    className="px-4 py-4"
                    data-label="Carrier"
                    data-mobile-hide="true"
                  >
                    {item.carrier.name}
                  </td>
                  <td className="px-4 py-4" data-label="Policy status">
                    <StatusBadge status={item.policy_status} />
                  </td>
                  <td className="px-4 py-4" data-label="Priority">
                    <PriorityBadge priority={item.priority} />
                  </td>
                  <td className="px-4 py-4" data-label="Assigned agent">
                    {item.assigned_agent ? (
                      <span className="flex items-center gap-2">
                        <Avatar user={item.assigned_agent} size="sm" />
                        <span>{item.assigned_agent.full_name}</span>
                      </span>
                    ) : (
                      'Unassigned'
                    )}
                  </td>
                  <td className="px-4 py-4 text-slate-600" data-label="Updated">
                    {formatDate(
                      item.updated_at,
                      getEffectiveTimezone(auth.data?.user),
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination
        page={cases.data.page.page}
        pages={cases.data.page.pages}
        onPageChange={(nextPage) => navigate(lifecycle, nextPage)}
        label="Case pagination"
      />
    </div>
  )
}
