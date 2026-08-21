import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { authQueryKey, useCurrentUser } from '../app/auth'
import { clearSessionState } from '../app/queryClient'
import { Button, Input } from '../components/ui'
import { ApiError, login } from '../lib/api'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const auth = useCurrentUser()
  const loginMutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: async (response) => {
      await clearSessionState(queryClient)
      queryClient.setQueryData(authQueryKey, response)
      await navigate('/dashboard', { replace: true })
    },
  })

  if (auth.isSuccess) return <Navigate to="/dashboard" replace />

  function submit(event: FormEvent) {
    event.preventDefault()
    loginMutation.mutate()
  }

  return (
    <main className="grid min-h-screen bg-slate-100 lg:grid-cols-[minmax(0,1fr)_minmax(420px,560px)]">
      <section className="hidden bg-slate-900 px-14 py-16 text-white lg:flex lg:flex-col lg:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[0.14em] text-slate-400 uppercase">
            Internal operations
          </p>
          <h1 className="mt-4 max-w-xl text-4xl font-semibold tracking-tight">
            Carrier Intelligence Hub
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-8 text-slate-300">
            Turn carrier communications into visible policy work, accountable
            tasks, and reviewable decisions.
          </p>
        </div>
        <p className="max-w-lg text-sm leading-6 text-slate-400">
          Sign in with your agency account, then connect Gmail securely with
          Google OAuth to begin automatic carrier monitoring.
        </p>
      </section>

      <section className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-md border border-slate-200 bg-white p-7 shadow-sm sm:p-9">
          <p className="text-xs font-semibold tracking-[0.12em] text-slate-500 uppercase lg:hidden">
            Carrier Intelligence Hub
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-950">
            Sign in
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Use your internal agency account to access the operations workspace.
          </p>
          <form className="mt-7 space-y-5" onSubmit={submit}>
            <label className="block text-sm font-medium text-slate-800">
              Email address
              <Input
                className="mt-2"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label className="block text-sm font-medium text-slate-800">
              Password
              <Input
                className="mt-2"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={8}
              />
            </label>
            {loginMutation.isError && (
              <p
                className="border border-red-200 bg-red-50 p-3 text-sm text-red-800"
                role="alert"
              >
                {loginMutation.error instanceof ApiError
                  ? loginMutation.error.message
                  : 'Invalid email or password'}
              </p>
            )}
            <Button
              className="w-full"
              type="submit"
              disabled={loginMutation.isPending}
            >
              {loginMutation.isPending ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
          <p className="mt-6 border-t border-slate-200 pt-5 text-xs leading-5 text-slate-500">
            No public registration is available. Account access is managed by
            the agency.
          </p>
        </div>
      </section>
    </main>
  )
}
