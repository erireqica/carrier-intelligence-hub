import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  PageHeader,
  Pagination,
  StatusBadge,
} from '../../components/ui'
import {
  addCarrierDomain,
  addCarrierSender,
  createCarrier,
  deleteCarrier,
  getCarriers,
  removeCarrierDomain,
  removeCarrierSender,
  setCarrierDomainEnabled,
  setCarrierSenderEnabled,
  updateCarrier,
} from '../../lib/api'
import type { CarrierItem } from '../../lib/types'

type EntryMutation = { id: number; enabled: boolean; remove?: boolean }

function MutationError({ error }: { error: Error | null }) {
  if (!error) return null
  return (
    <p className="mt-2 text-xs font-medium text-red-700" role="alert">
      {error.message}
    </p>
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
  const [domainPage, setDomainPage] = useState(1)
  const domainPages = Math.max(1, Math.ceil(carrier.domains.length / 5))
  const safeDomainPage = Math.min(domainPage, domainPages)
  const visibleDomains = carrier.domains.slice(
    (safeDomainPage - 1) * 5,
    safeDomainPage * 5,
  )
  const refreshCarriers = () =>
    queryClient.invalidateQueries({ queryKey: ['manager', 'carriers'] })

  const carrierMutation = useMutation({
    mutationFn: (updated: CarrierItem) => updateCarrier(updated),
    onSuccess: async () => {
      setEditing(false)
      await refreshCarriers()
    },
  })
  const domainMutation = useMutation({
    mutationFn: () => addCarrierDomain(carrier.id, domain),
    onSuccess: async () => {
      setDomain('')
      setDomainPage(1)
      await refreshCarriers()
    },
  })
  const senderMutation = useMutation({
    mutationFn: () => addCarrierSender(carrier.id, sender),
    onSuccess: async () => {
      setSender('')
      await refreshCarriers()
    },
  })
  const domainEntryMutation = useMutation({
    mutationFn: ({ id, enabled, remove }: EntryMutation) =>
      remove
        ? removeCarrierDomain(carrier.id, id)
        : setCarrierDomainEnabled(carrier.id, id, enabled),
    onSuccess: async (_data, variables) => {
      if (variables.remove) {
        const remainingPages = Math.max(
          1,
          Math.ceil((carrier.domains.length - 1) / 5),
        )
        setDomainPage((current) => Math.min(current, remainingPages))
      }
      await refreshCarriers()
    },
  })
  const senderEntryMutation = useMutation({
    mutationFn: ({ id, enabled, remove }: EntryMutation) =>
      remove
        ? removeCarrierSender(carrier.id, id)
        : setCarrierSenderEnabled(carrier.id, id, enabled),
    onSuccess: refreshCarriers,
  })
  const deleteMutation = useMutation({
    mutationFn: () => deleteCarrier(carrier.id),
    onSuccess: refreshCarriers,
  })

  function beginEditing() {
    setName(carrier.name)
    setCode(carrier.code ?? '')
    setNotes(carrier.notes ?? '')
    carrierMutation.reset()
    setEditing(true)
  }

  function confirmRemoval(kind: 'domain' | 'sender', value: string) {
    return window.confirm(
      `Remove approved ${kind} “${value}” from ${carrier.name}?\n\nFuture messages matching this ${kind} will no longer be accepted for this carrier. Existing cases, messages, tasks, and audit history remain unchanged.`,
    )
  }

  return (
    <article className="surface-panel">
      <header className="flex flex-col items-stretch justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-start">
        {editing ? (
          <form
            className="grid flex-1 gap-3 sm:grid-cols-[1fr_140px]"
            onSubmit={(event) => {
              event.preventDefault()
              carrierMutation.mutate({ ...carrier, name, code, notes })
            }}
          >
            <label className="text-sm font-medium">
              Carrier name
              <Input
                className="mt-1"
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={carrierMutation.isPending}
                required
              />
            </label>
            <label className="text-sm font-medium">
              Code
              <Input
                className="mt-1"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                disabled={carrierMutation.isPending}
              />
            </label>
            <label className="text-sm font-medium sm:col-span-2">
              Notes
              <Input
                className="mt-1"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                disabled={carrierMutation.isPending}
              />
            </label>
            <div className="sm:col-span-2">
              <div className="flex gap-2">
                <Button type="submit" disabled={carrierMutation.isPending}>
                  Save
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setEditing(false)}
                  disabled={carrierMutation.isPending}
                >
                  Cancel
                </Button>
              </div>
              <MutationError error={carrierMutation.error} />
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
              {carrier.code ?? 'No code'} · {carrier.notes ?? 'No notes'}
            </p>
            <MutationError error={carrierMutation.error} />
          </div>
        )}
        {!editing && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={beginEditing}
              disabled={carrierMutation.isPending}
            >
              Edit
            </Button>
            <Button
              variant={carrier.is_enabled ? 'danger' : 'success'}
              onClick={() =>
                carrierMutation.mutate({
                  ...carrier,
                  is_enabled: !carrier.is_enabled,
                })
              }
              disabled={carrierMutation.isPending}
            >
              {carrier.is_enabled ? 'Disable' : 'Enable'}
            </Button>
            <Button
              variant="dangerSecondary"
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `Permanently delete ${carrier.name}?\n\nThis removes its configuration and whitelist entries and cannot be undone.`,
                  )
                )
                  deleteMutation.mutate()
              }}
            >
              Delete
            </Button>
          </div>
        )}
      </header>
      <div className="grid gap-6 p-5 lg:grid-cols-2">
        <section>
          <h3 className="text-sm font-semibold">Approved domains</h3>
          <ul className="mt-3 space-y-2">
            {visibleDomains.map((item) => (
              <li
                key={item.id}
                className="flex flex-col gap-3 rounded-lg border border-slate-200 px-3 py-2.5 text-sm sm:flex-row sm:items-center sm:justify-between"
              >
                <span>{item.domain}</span>
                <span className="flex flex-wrap items-center gap-2">
                  <StatusBadge
                    status={item.is_enabled ? 'ACTIVE' : 'DISABLED'}
                  />
                  <button
                    className="inline-flex min-h-9 items-center rounded-md px-2 py-1 font-medium text-blue-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 disabled:text-slate-400"
                    disabled={domainEntryMutation.isPending}
                    onClick={() =>
                      domainEntryMutation.mutate({
                        id: item.id,
                        enabled: !item.is_enabled,
                      })
                    }
                  >
                    {item.is_enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    className="inline-flex min-h-9 items-center rounded-md px-2 py-1 font-medium text-red-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 disabled:text-slate-400"
                    disabled={domainEntryMutation.isPending}
                    onClick={() => {
                      if (confirmRemoval('domain', item.domain))
                        domainEntryMutation.mutate({
                          id: item.id,
                          enabled: false,
                          remove: true,
                        })
                    }}
                  >
                    Remove
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-3">
            <Pagination
              page={safeDomainPage}
              pages={domainPages}
              onPageChange={setDomainPage}
              label={`${carrier.name} domain pagination`}
            />
          </div>
          <form
            className="mt-3 flex flex-col gap-2 sm:flex-row"
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
              disabled={domainMutation.isPending}
              required
            />
            <Button
              type="submit"
              variant="secondary"
              disabled={domainMutation.isPending}
            >
              Add
            </Button>
          </form>
          <MutationError error={domainMutation.error} />
          <MutationError error={domainEntryMutation.error} />
          <MutationError error={deleteMutation.error} />
        </section>
        <section>
          <h3 className="text-sm font-semibold">Approved exact senders</h3>
          {carrier.senders.length ? (
            <ul className="mt-3 space-y-2">
              {carrier.senders.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-col gap-3 rounded-lg border border-slate-200 px-3 py-2.5 text-sm sm:flex-row sm:items-center sm:justify-between"
                >
                  <span>{item.email}</span>
                  <span className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      status={item.is_enabled ? 'ACTIVE' : 'DISABLED'}
                    />
                    <button
                      className="font-medium text-blue-700 hover:underline disabled:text-slate-400"
                      disabled={senderEntryMutation.isPending}
                      onClick={() =>
                        senderEntryMutation.mutate({
                          id: item.id,
                          enabled: !item.is_enabled,
                        })
                      }
                    >
                      {item.is_enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button
                      className="font-medium text-red-700 hover:underline disabled:text-slate-400"
                      disabled={senderEntryMutation.isPending}
                      onClick={() => {
                        if (confirmRemoval('sender', item.email))
                          senderEntryMutation.mutate({
                            id: item.id,
                            enabled: false,
                            remove: true,
                          })
                      }}
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
            className="mt-3 flex flex-col gap-2 sm:flex-row"
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
              disabled={senderMutation.isPending}
              required
            />
            <Button
              type="submit"
              variant="secondary"
              disabled={senderMutation.isPending}
            >
              Add
            </Button>
          </form>
          <MutationError error={senderMutation.error} />
          <MutationError error={senderEntryMutation.error} />
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
    <div className="app-page space-y-6">
      <PageHeader
        eyebrow="Agency configuration"
        title="Carriers & Whitelist"
        description="Approved carrier-controlled domains and exact sender addresses determine which incoming messages Carrier Hub accepts."
        action={
          <Button
            onClick={() => {
              createMutation.reset()
              setShowForm((value) => !value)
            }}
            disabled={createMutation.isPending}
          >
            {showForm ? 'Cancel' : 'Add carrier'}
          </Button>
        }
      />
      <p className="border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
        Approve a whole domain only when the carrier controls it. For Gmail,
        Outlook, Yahoo, and other public email providers, add the specific
        sender address instead.
      </p>
      {showForm && (
        <form
          className="form-panel grid gap-4 p-6 sm:grid-cols-[1fr_180px_auto]"
          onSubmit={submit}
        >
          <label className="text-sm font-medium">
            Carrier name
            <Input
              className="mt-2"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={createMutation.isPending}
              required
            />
          </label>
          <label className="text-sm font-medium">
            Code
            <Input
              className="mt-2"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              disabled={createMutation.isPending}
            />
          </label>
          <Button
            className="self-end"
            type="submit"
            disabled={createMutation.isPending}
          >
            Create carrier
          </Button>
          <div className="sm:col-span-3">
            <MutationError error={createMutation.error} />
          </div>
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
