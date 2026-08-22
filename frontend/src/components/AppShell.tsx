import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  BarChart3,
  BriefcaseBusiness,
  Building2,
  ClipboardCheck,
  ClipboardList,
  ContactRound,
  LayoutDashboard,
  LogOut,
  Mail,
  ShieldCheck,
  UserRound,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useCurrentUser } from '../app/auth'
import { clearSessionState } from '../app/queryClient'
import { logout } from '../lib/api'
import { Button } from './ui'

const agentNavigation = [
  ['Dashboard', '/dashboard', LayoutDashboard],
  ['Cases', '/cases', BriefcaseBusiness],
  ['My Tasks', '/tasks', ClipboardList],
  ['My Activity', '/activity', Activity],
  ['Review Queue', '/reviews', ClipboardCheck],
  ['Gmail Connections', '/gmail-connections', Mail],
  ['Profile', '/profile', UserRound],
] as const

const managerNavigation = [
  ['Analytics', '/manager/analytics', BarChart3],
  ['Agents', '/manager/agents', UsersRound],
  ['Carriers', '/manager/carriers', Building2],
  ['System Logs', '/manager/system-logs', ClipboardList],
] as const

function NavigationLink({
  label,
  to,
  icon: Icon,
}: {
  label: string
  to: string
  icon: LucideIcon
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
          isActive
            ? 'bg-white/10 text-white shadow-sm ring-1 ring-white/10'
            : 'text-slate-300 hover:bg-white/[0.06] hover:text-white'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            className={`h-[18px] w-[18px] ${isActive ? 'text-blue-300' : 'text-slate-400 group-hover:text-slate-200'}`}
            aria-hidden
          />
          <span>{label}</span>
          {isActive && (
            <span className="ml-auto h-1.5 w-1.5 rounded-full bg-blue-400" />
          )}
        </>
      )}
    </NavLink>
  )
}

export function AppShell() {
  const auth = useCurrentUser()
  const user = auth.data!.user
  const primaryNavigation = agentNavigation
    .filter(([, to]) => user.role === 'AGENT' || to !== '/activity')
    .map(
      ([label, to, icon]) =>
        [
          to === '/tasks' && user.role === 'MANAGER' ? 'Tasks' : label,
          to,
          icon,
        ] as const,
    )
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      await clearSessionState(queryClient)
      await navigate('/login', { replace: true })
    },
  })
  const initials = user.full_name
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)

  return (
    <div className="min-h-dvh bg-[#f3f6fa] lg:pl-[268px]">
      <aside className="hidden bg-[#13233a] text-white lg:fixed lg:inset-y-0 lg:left-0 lg:z-30 lg:flex lg:w-[268px] lg:flex-col lg:overflow-hidden">
        <div className="shrink-0 border-b border-white/10 px-5 py-6">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500 text-white shadow-lg shadow-blue-950/20">
              <ShieldCheck className="h-5 w-5" aria-hidden />
            </span>
            <div>
              <p className="text-[0.65rem] font-bold tracking-[0.17em] text-blue-300 uppercase">
                Carrier
              </p>
              <p className="mt-0.5 font-semibold tracking-tight">
                Intelligence Hub
              </p>
            </div>
          </div>
        </div>
        <nav
          className="min-h-0 flex-1 overflow-y-auto px-3 py-5"
          aria-label="Primary navigation"
        >
          <p className="px-3 pb-2 text-[0.65rem] font-bold tracking-[0.16em] text-slate-500 uppercase">
            Workspace
          </p>
          <div className="space-y-1">
            {primaryNavigation.map(([label, to, icon]) => (
              <NavigationLink key={to} label={label} to={to} icon={icon} />
            ))}
          </div>
          {user.role === 'MANAGER' && (
            <>
              <p className="px-3 pt-7 pb-2 text-[0.65rem] font-bold tracking-[0.16em] text-slate-500 uppercase">
                Management
              </p>
              <div className="space-y-1">
                {managerNavigation.map(([label, to, icon]) => (
                  <NavigationLink key={to} label={label} to={to} icon={icon} />
                ))}
              </div>
            </>
          )}
        </nav>
        <div className="shrink-0 border-t border-white/10 p-4">
          {auth.data!.environment === 'development' && (
            <div className="mb-3 flex items-center gap-2 text-xs font-medium text-amber-200">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-300" />
              Development workspace
            </div>
          )}
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 text-sm font-bold text-white">
              {initials}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{user.full_name}</p>
              <p className="mt-0.5 text-xs text-slate-400">
                {user.role === 'MANAGER' ? 'Agency manager' : 'Agent'}
              </p>
            </div>
          </div>
          <Button
            className="mt-4 w-full"
            variant="dark"
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
          >
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </Button>
        </div>
      </aside>

      <div className="min-h-dvh min-w-0">
        <header className="sticky top-0 z-20 border-b border-slate-200/90 bg-white/95 px-5 py-3 backdrop-blur lg:static lg:px-8 lg:py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 lg:hidden">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#13233a] text-white">
                <ShieldCheck className="h-4 w-4" aria-hidden />
              </span>
              <p className="font-semibold tracking-tight text-slate-900">
                Carrier Hub
              </p>
            </div>
            <div className="hidden items-center gap-2 text-sm text-slate-500 lg:flex">
              <ContactRound className="h-4 w-4 text-blue-600" aria-hidden />
              <span>{user.agency.name}</span>
              <span className="text-slate-300">/</span>
              <span>
                {user.role === 'MANAGER'
                  ? 'Agency operations'
                  : 'My operations'}
              </span>
            </div>
            <div className="ml-auto flex items-center gap-3">
              <div className="hidden text-right sm:block">
                <p className="text-sm font-semibold text-slate-900">
                  {user.full_name}
                </p>
                <p className="text-xs text-slate-500">{user.agency.name}</p>
              </div>
              <span className="hidden h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-xs font-bold text-slate-700 sm:flex lg:hidden">
                {initials}
              </span>
              <Button
                className="lg:hidden"
                variant="secondary"
                onClick={() => logoutMutation.mutate()}
                disabled={logoutMutation.isPending}
              >
                <LogOut className="h-4 w-4" aria-hidden />
                <span className="hidden sm:inline">Sign out</span>
              </Button>
            </div>
          </div>
          <nav
            className="mobile-nav mt-4 flex gap-5 overflow-x-auto pb-1 lg:hidden"
            aria-label="Mobile navigation"
          >
            {[
              ...primaryNavigation,
              ...(user.role === 'MANAGER' ? managerNavigation : []),
            ].map(([label, to, Icon]) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-2 whitespace-nowrap border-b-2 px-1 pb-2 text-sm font-medium ${isActive ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-600'}`
                }
              >
                <Icon className="h-4 w-4" aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="p-5 sm:p-6 lg:p-8 xl:px-10 xl:py-9">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
