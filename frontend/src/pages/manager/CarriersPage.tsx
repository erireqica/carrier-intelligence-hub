import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import {
  addCarrierDomain,
  addCarrierSender,
  createCarrier,
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
    onSuccess: refreshCarriers,
  })
  const senderEntryMutation = useMutation({
    mutationFn: ({ id, enabled, remove }: EntryMutation) =>
      remove
        ? removeCarrierSender(carrier.id, id)
        : setCarrierSenderEnabled(carrier.id, id, enabled),
    onSuccess: refreshCarriers,
  })

  function beginEditing() {
    setName(carrier.name)
    setCode(carrier.code ?? '')
    setNotes(carrier.notes ?? '')
    carrierMutation.reset()
    setEditing(true)
  }

  return (
    <article className="border border-slate-200 bg-white">
      <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
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
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={beginEditing}
              disabled={carrierMutation.isPending}
            >
              Edit
            </Button>
            <Button
              variant="secondary"
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
                    className="font-medium text-blue-700 hover:underline disabled:text-slate-400"
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
                    className="font-medium text-red-700 hover:underline disabled:text-slate-400"
                    disabled={domainEntryMutation.isPending}
                    onClick={() =>
                      domainEntryMutation.mutate({
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
                      onClick={() =>
                        senderEntryMutation.mutate({
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
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency configuration"
        title="Carriers & Whitelist"
        description="These database records will determine which senders are eligible for future Gmail processing."
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
