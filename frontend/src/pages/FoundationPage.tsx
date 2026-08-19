import { useQuery } from '@tanstack/react-query'

import { ServiceStatus } from '../components/ServiceStatus'
import { getHealth } from '../lib/api'

export function FoundationPage() {
  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => getHealth(signal),
  })

  const backendState = healthQuery.isPending
    ? 'checking'
    : healthQuery.isSuccess
      ? 'healthy'
      : 'unavailable'

  const backendDetail = healthQuery.isPending
    ? 'Contacting the versioned FastAPI health endpoint.'
    : healthQuery.isSuccess
      ? `Connected to ${healthQuery.data.service}.`
      : 'Start the backend service on port 8000, then refresh this page.'

  return (
    <main className="min-h-screen bg-slate-100 px-5 py-10 text-slate-950 sm:px-8 sm:py-16">
      <div className="mx-auto max-w-3xl">
        <header className="border-b border-slate-300 pb-8">
          <p className="text-xs font-semibold tracking-[0.14em] text-slate-600 uppercase">
            Development foundation
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            Carrier Intelligence Hub
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-slate-600">
            The core application services are being prepared for secure carrier
            communication workflows. This temporary page verifies the local
            stack.
          </p>
        </header>

        <div
          className="mt-8 border border-slate-300 bg-white p-6 shadow-sm sm:p-8"
          aria-live="polite"
          aria-label="Application service status"
        >
          <ServiceStatus
            label="Frontend application"
            detail="React, routing, TypeScript, and Tailwind are running."
            state="healthy"
          />
          <ServiceStatus
            label="Backend API"
            detail={backendDetail}
            state={backendState}
          />
        </div>

        <footer className="mt-6 text-sm leading-6 text-slate-500">
          Domain features are intentionally not included in this foundation
          stage.
        </footer>
      </div>
    </main>
  )
}
