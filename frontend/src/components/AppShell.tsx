import { useMutation, useQueryClient } from '@tanstack/react-query'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { authQueryKey, useCurrentUser } from '../app/auth'
import { logout } from '../lib/api'
import { Button } from './ui'

const agentNavigation = [
  ['Dashboard', '/dashboard'],
  ['Cases', '/cases'],
  ['My Tasks', '/tasks'],
  ['Review Queue', '/reviews'],
  ['Gmail Connections', '/gmail-connections'],
  ['Profile', '/profile'],
] as const

const managerNavigation = [
  ['Analytics', '/manager/analytics'],
  ['Agents', '/manager/agents'],
  ['Carriers', '/manager/carriers'],
  ['System Logs', '/manager/system-logs'],
  ['Settings / Integrations', '/manager/settings'],
] as const

function NavigationLink({ label, to }: { label: string; to: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `block border-l-2 px-4 py-2.5 text-sm font-medium transition-colors ${
          isActive
            ? 'border-blue-600 bg-slate-800 text-white'
            : 'border-transparent text-slate-300 hover:bg-slate-800 hover:text-white'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

export function AppShell() {
  const auth = useCurrentUser()
  const user = auth.data!.user
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: authQueryKey })
      await navigate('/login', { replace: true })
    },
  })

  return (
    <div className="min-h-screen bg-slate-100 lg:grid lg:grid-cols-[248px_1fr]">
      <aside className="hidden min-h-screen bg-slate-900 text-white lg:flex lg:flex-col">
        <div className="border-b border-slate-700 px-6 py-6">
          <p className="text-xs font-semibold tracking-[0.12em] text-slate-400 uppercase">
            Carrier
          </p>
          <p className="mt-1 text-lg font-semibold">Intelligence Hub</p>
        </div>
        <nav className="flex-1 px-3 py-5" aria-label="Primary navigation">
          {agentNavigation.map(([label, to]) => (
            <NavigationLink key={to} label={label} to={to} />
          ))}
          {user.role === 'MANAGER' && (
            <>
              <p className="px-4 pt-7 pb-2 text-xs font-semibold tracking-wider text-slate-500 uppercase">
                Agency
              </p>
              {managerNavigation.map(([label, to]) => (
                <NavigationLink key={to} label={label} to={to} />
              ))}
            </>
          )}
        </nav>
        <div className="border-t border-slate-700 p-4">
          {auth.data!.environment === 'development' && (
            <p className="mb-3 text-xs font-medium text-slate-400">
              Development data
            </p>
          )}
          <p className="text-sm font-medium">{user.full_name}</p>
          <p className="mt-0.5 text-xs text-slate-400">{user.role}</p>
          <Button
            className="mt-4 w-full border-slate-600 bg-transparent text-slate-200 hover:bg-slate-800"
            variant="secondary"
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
          >
            Sign out
          </Button>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="border-b border-slate-200 bg-white px-5 py-4 lg:px-8">
          <div className="flex items-center justify-between">
            <p className="font-semibold text-slate-900 lg:hidden">
              Carrier Intelligence Hub
            </p>
            <div className="ml-auto flex items-center gap-3">
              <div className="text-right">
                <p className="text-sm font-medium text-slate-900">
                  {user.full_name}
                </p>
                <p className="text-xs text-slate-500">{user.agency.name}</p>
              </div>
              <Button
                className="lg:hidden"
                variant="secondary"
                onClick={() => logoutMutation.mutate()}
                disabled={logoutMutation.isPending}
              >
                Sign out
              </Button>
            </div>
          </div>
          <nav
            className="mt-4 flex gap-4 overflow-x-auto pb-1 lg:hidden"
            aria-label="Mobile navigation"
          >
            {[
              ...agentNavigation,
              ...(user.role === 'MANAGER' ? managerNavigation : []),
            ].map(([label, to]) => (
              <NavLink
                key={to}
                to={to}
                className="whitespace-nowrap text-sm font-medium text-slate-700"
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="p-5 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
