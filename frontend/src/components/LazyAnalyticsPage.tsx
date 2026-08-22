import { Suspense, lazy } from 'react'

const AnalyticsPage = lazy(() =>
  import('../pages/manager/AnalyticsPage').then((module) => ({
    default: module.AnalyticsPage,
  })),
)

export function LazyAnalyticsPage() {
  return (
    <Suspense
      fallback={
        <p className="p-6 text-sm text-slate-500">Loading analytics…</p>
      }
    >
      <AnalyticsPage />
    </Suspense>
  )
}
