import { Navigate, Outlet } from 'react-router-dom'

import { ApiError } from '../lib/api'
import { useCurrentUser } from '../app/auth'
import { ErrorState, LoadingState } from './ui'

export function ProtectedRoute() {
  const auth = useCurrentUser()
  if (auth.isPending) return <LoadingState label="Verifying your session…" />
  if (auth.error instanceof ApiError && auth.error.status === 401) {
    return <Navigate to="/login" replace />
  }
  if (auth.isError)
    return (
      <ErrorState message={auth.error.message} retry={() => auth.refetch()} />
    )
  return <Outlet />
}

export function ManagerRoute() {
  const auth = useCurrentUser()
  if (auth.data?.user.role !== 'MANAGER')
    return <Navigate to="/dashboard" replace />
  return <Outlet />
}

export function AgentRoute() {
  const auth = useCurrentUser()
  if (auth.data?.user.role !== 'AGENT')
    return <Navigate to="/dashboard" replace />
  return <Outlet />
}
