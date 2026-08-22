import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import {
  ArrowRight,
  ClipboardCheck,
  MailCheck,
  ShieldCheck,
} from 'lucide-react'
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
    <main className="grid min-h-screen bg-[#f3f6fa] lg:grid-cols-[minmax(0,1fr)_minmax(440px,580px)]">
      <section className="login-visual relative hidden overflow-hidden bg-[#10233d] px-14 py-14 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-500 shadow-lg shadow-blue-950/20">
              <ShieldCheck className="h-6 w-6" aria-hidden />
            </span>
            <div>
              <p className="text-[0.65rem] font-bold tracking-[0.17em] text-blue-300 uppercase">
                Internal operations
              </p>
              <p className="mt-0.5 font-semibold">Carrier Intelligence Hub</p>
            </div>
          </div>
          <h1 className="mt-16 max-w-2xl text-4xl leading-tight font-semibold tracking-[-0.03em] xl:text-5xl">
            Carrier communication,
            <span className="block text-blue-300">
              turned into accountable work.
            </span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-8 text-slate-300">
            Turn carrier communications into visible policy work, accountable
            tasks, and reviewable decisions.
          </p>
          <div className="mt-10 grid max-w-2xl gap-3 xl:grid-cols-2">
            {(
              [
                [MailCheck, 'Automatic inbox monitoring'],
                [ClipboardCheck, 'Human-verifiable decisions'],
              ] as const
            ).map(([Icon, label]) => (
              <div
                key={label}
                className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.05] p-4 text-sm font-medium text-slate-200"
              >
                <Icon className="h-5 w-5 text-blue-300" aria-hidden />
                {label}
              </div>
            ))}
          </div>
          <ol
            className="mt-10 flex max-w-2xl items-center text-xs font-semibold text-slate-300"
            aria-label="Carrier communication workflow"
          >
            {['Monitor', 'Interpret', 'Act'].map((step, index) => (
              <li key={step} className="flex flex-1 items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-blue-300/30 bg-blue-400/10 text-[0.65rem] text-blue-200">
                  {index + 1}
                </span>
                <span>{step}</span>
                {index < 2 && (
                  <span className="mx-2 h-px flex-1 bg-white/15" aria-hidden />
                )}
              </li>
            ))}
          </ol>
        </div>
        <p className="relative z-10 max-w-xl border-t border-white/10 pt-6 text-sm leading-6 text-slate-300">
          Sign in with your agency account, then connect Gmail securely with
          Google OAuth to begin automatic carrier monitoring.
        </p>
      </section>

      <section className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-xl shadow-slate-900/[0.06] sm:p-9">
          <p className="text-xs font-semibold tracking-[0.12em] text-slate-500 uppercase lg:hidden">
            Carrier Intelligence Hub
          </p>
          <p className="text-[0.7rem] font-bold tracking-[0.15em] text-blue-700 uppercase">
            Secure workspace
          </p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
            Welcome back
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
              {!loginMutation.isPending && (
                <ArrowRight className="h-4 w-4" aria-hidden />
              )}
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
