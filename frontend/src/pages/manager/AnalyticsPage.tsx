import { useQuery } from '@tanstack/react-query'

import {
  ErrorState,
  LoadingState,
  Metric,
  PageHeader,
} from '../../components/ui'
import { getAnalytics } from '../../lib/api'

function Breakdown({
  title,
  values,
}: {
  title: string
  values: Record<string, number>
}) {
  return (
    <div className="border border-slate-200 bg-white">
      <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
        {title}
      </h2>
      <dl className="divide-y divide-slate-100">
        {Object.entries(values).map(([label, value]) => (
          <div key={label} className="flex justify-between px-5 py-3 text-sm">
            <dt>{label.replaceAll('_', ' ')}</dt>
            <dd className="font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function AnalyticsPage() {
  const analytics = useQuery({
    queryKey: ['manager', 'analytics'],
    queryFn: getAnalytics,
  })
  if (analytics.isPending)
    return <LoadingState label="Calculating agency analytics…" />
  if (analytics.isError)
    return (
      <ErrorState
        message={analytics.error.message}
        retry={() => analytics.refetch()}
      />
    )
  const data = analytics.data
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency oversight"
        title="Analytics"
        description="Focused metrics calculated directly from current PostgreSQL records."
      />
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        <Metric
          label="Urgent / high"
          value={data.urgent_high_cases}
          attention
        />
        <Metric label="Open tasks" value={data.open_tasks} />
        <Metric label="Overdue" value={data.overdue_tasks} attention />
        <Metric label="Open reviews" value={data.open_reviews} />
        <Metric label="Processed" value={data.processed_messages} />
        <Metric label="Failed" value={data.failed_messages} attention />
      </section>
      <section className="grid gap-5 lg:grid-cols-3">
        <Breakdown title="Cases by status" values={data.cases_by_status} />
        <Breakdown title="Cases by carrier" values={data.cases_by_carrier} />
        <div className="border border-slate-200 bg-white">
          <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
            Open workload by agent
          </h2>
          <dl className="divide-y divide-slate-100">
            {data.workload_by_agent.map((item) => (
              <div
                key={item.agent.id}
                className="flex justify-between gap-4 px-5 py-3 text-sm"
              >
                <dt>
                  {item.agent.full_name}
                  <span className="block text-xs text-slate-500">
                    {item.agent.email}
                  </span>
                </dt>
                <dd className="font-semibold">{item.open_tasks}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>
    </div>
  )
}
