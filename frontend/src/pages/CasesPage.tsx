import { useQuery } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  PageHeader,
  PriorityBadge,
  StatusBadge,
} from '../components/ui'
import { formatDate } from '../lib/format'
import { getCases } from '../lib/api'

export function CasesPage() {
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [page, setPage] = useState(1)
  const params = new URLSearchParams({ page: String(page), page_size: '20' })
  if (search) params.set('search', search)
  if (status) params.set('policy_status', status)
  if (priority) params.set('priority', priority)
  const cases = useQuery({
    queryKey: ['cases', search, status, priority, page],
    queryFn: () => getCases(params.toString()),
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    setSearch(searchInput.trim())
    setPage(1)
  }
  if (cases.isPending) return <LoadingState label="Loading cases…" />
  if (cases.isError)
    return (
      <ErrorState message={cases.error.message} retry={() => cases.refetch()} />
    )

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Policy operations"
        title="Cases"
        description="Ongoing policy records, separated from the carrier communications that update them."
      />
      <form
        onSubmit={submit}
        className="grid gap-3 lg:grid-cols-[minmax(260px,1fr)_180px_160px_auto]"
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
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value)
            setPage(1)
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
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
          value={priority}
          onChange={(event) => {
            setPriority(event.target.value)
            setPage(1)
          }}
        >
          <option value="">All priorities</option>
          {['URGENT', 'HIGH', 'NORMAL', 'LOW'].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <div className="flex gap-2">
          <Button type="submit" variant="secondary">
            Search
          </Button>
          {(search || status || priority) && (
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setSearchInput('')
                setSearch('')
                setStatus('')
                setPriority('')
                setPage(1)
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
            search || status || priority
              ? 'No cases match your filters'
              : 'No carrier cases yet'
          }
          description={
            search || status || priority
              ? 'Adjust or reset the search and filters.'
              : 'Cases will appear after approved carrier communications are processed.'
          }
        />
      ) : (
        <div className="overflow-x-auto border border-slate-200 bg-white">
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
                  <td className="px-4 py-4">
                    <Link
                      className="font-semibold text-blue-800"
                      to={`/cases/${item.id}`}
                    >
                      {item.client_name}
                    </Link>
                    <p className="mt-1 text-xs text-slate-500">
                      {item.policy_number ?? 'Policy number pending'}
                      {item.needs_review ? ' · Needs review' : ''}
                    </p>
                  </td>
                  <td className="px-4 py-4">{item.carrier.name}</td>
                  <td className="px-4 py-4">
                    <StatusBadge status={item.policy_status} />
                  </td>
                  <td className="px-4 py-4">
                    <PriorityBadge priority={item.priority} />
                  </td>
                  <td className="px-4 py-4">
                    {item.assigned_agent?.full_name ?? 'Unassigned'}
                  </td>
                  <td className="px-4 py-4 text-slate-600">
                    {formatDate(item.updated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cases.data.page.pages > 1 && (
        <nav
          className="flex items-center justify-between text-sm"
          aria-label="Case pagination"
        >
          <span>
            Page {cases.data.page.page} of {cases.data.page.pages}
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={page === 1}
              onClick={() => setPage((value) => value - 1)}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              disabled={page === cases.data.page.pages}
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </Button>
          </div>
        </nav>
      )}
    </div>
  )
}
