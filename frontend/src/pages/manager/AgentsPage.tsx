import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserPlus, UsersRound, X } from 'lucide-react'

import { useCurrentUser } from '../../app/auth'
import { Avatar } from '../../components/Avatar'
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
import { apiBaseUrl } from '../../lib/api-url'
import { formatDateTime } from '../../lib/format'

const emptyAgent = {
  full_name: '',
  email: '',
  initial_password: '',
  confirm_initial_password: '',
}

type PhotoPreview = {
  fullName: string
  avatarUrl: string
}

function AgentPhotoPreview({
  preview,
  onClose,
  returnFocusRef,
}: {
  preview: PhotoPreview
  onClose: () => void
  returnFocusRef: React.RefObject<HTMLButtonElement | null>
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const returnFocusTo = returnFocusRef.current
    const previousOverflow = document.body.style.overflow
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    document.body.style.overflow = 'hidden'
    closeButtonRef.current?.focus()

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('keydown', closeOnEscape)
      document.body.style.overflow = previousOverflow
      if (dialog.open && typeof dialog.close === 'function') dialog.close()
      returnFocusTo?.focus()
    }
  }, [onClose, returnFocusRef])

  return (
    <dialog
      ref={dialogRef}
      className="m-auto max-h-none max-w-none overflow-visible bg-transparent p-0 backdrop:bg-slate-950/65 backdrop:backdrop-blur-[1px]"
      aria-label={`${preview.fullName} profile photo preview`}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="relative rounded-xl border border-white/20 bg-white p-2 shadow-2xl">
        <img
          className="max-h-[calc(100vh-3rem)] max-w-[calc(100vw-3rem)] rounded-lg object-contain sm:max-h-[80vh] sm:max-w-[80vw]"
          src={`${apiBaseUrl}${preview.avatarUrl}`}
          alt={`${preview.fullName} profile`}
        />
        <button
          ref={closeButtonRef}
          type="button"
          className="absolute -top-3 -right-3 inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-600 bg-slate-900 text-white shadow-md transition hover:bg-slate-800 focus:outline-none focus-visible:ring-3 focus-visible:ring-blue-300"
          aria-label="Close profile photo preview"
          onClick={onClose}
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </dialog>
  )
}

export function AgentsPage() {
  const auth = useCurrentUser()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [showCreate, setShowCreate] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [form, setForm] = useState(emptyAgent)
  const [photoPreview, setPhotoPreview] = useState<PhotoPreview | null>(null)
  const photoTriggerRef = useRef<HTMLButtonElement | null>(null)
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
    <div className="app-page space-y-6">
      <PageHeader
        eyebrow="Agency"
        title="Agents"
        description="Create Agent access and manage current operational accounts."
        action={
          <Button onClick={() => setShowCreate((value) => !value)}>
            <UserPlus className="h-4 w-4" aria-hidden />
            Add agent
          </Button>
        }
      />
      {showCreate && (
        <form
          className="form-panel grid gap-4 p-6 md:grid-cols-2"
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
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-blue-500 focus:ring-3 focus:ring-blue-100"
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
      <div className="data-table-shell responsive-data-table">
        <div className="record-list-heading flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
              <UsersRound className="h-[18px] w-[18px]" aria-hidden />
            </span>
            <div>
              <h2 className="font-semibold text-slate-950">Agency roster</h2>
              <p className="mt-0.5 text-xs text-slate-500">
                Access and current operational load
              </p>
            </div>
          </div>
          <span className="text-xs font-semibold text-slate-500">
            {agents.data.page.total} users
          </span>
        </div>
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
                <td className="px-4 py-4 font-medium" data-label="User">
                  <div className="flex items-center gap-3">
                    {agent.avatar_url ? (
                      <button
                        type="button"
                        className="inline-flex h-9 w-9 shrink-0 cursor-zoom-in items-center justify-center overflow-hidden rounded-lg border-0 bg-transparent p-0 align-middle leading-none appearance-none hover:ring-2 hover:ring-blue-200 focus:outline-none focus-visible:ring-3 focus-visible:ring-blue-300"
                        aria-label={`View larger profile photo for ${agent.full_name}`}
                        onClick={(event) => {
                          photoTriggerRef.current = event.currentTarget
                          setPhotoPreview({
                            fullName: agent.full_name,
                            avatarUrl: agent.avatar_url!,
                          })
                        }}
                      >
                        <Avatar user={agent} />
                      </button>
                    ) : (
                      <Avatar user={agent} />
                    )}
                    <div>
                      <p className="font-semibold text-slate-900">
                        {agent.full_name}
                      </p>
                      <p className="text-xs font-normal text-slate-500">
                        {agent.email}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-4" data-label="Role">
                  <Badge tone="blue">{agent.role}</Badge>
                </td>
                <td className="px-4 py-4" data-label="Status">
                  <StatusBadge
                    status={agent.is_active ? 'ACTIVE' : 'DISABLED'}
                  />
                </td>
                <td className="px-4 py-4" data-label="Open tasks">
                  {agent.open_tasks}
                </td>
                <td className="px-4 py-4" data-label="Urgent cases">
                  {agent.urgent_cases}
                </td>
                <td className="px-4 py-4" data-label="Connected inboxes">
                  {agent.gmail_connections} connected
                </td>
                <td className="px-4 py-4" data-label="Last login">
                  {formatDateTime(
                    agent.last_login_at,
                    auth.data!.user.agency.timezone,
                  )}
                </td>
                <td
                  className="px-4 py-4"
                  data-label="Actions"
                  data-mobile-span="full"
                >
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
      {photoPreview && (
        <AgentPhotoPreview
          preview={photoPreview}
          onClose={() => setPhotoPreview(null)}
          returnFocusRef={photoTriggerRef}
        />
      )}
    </div>
  )
}
