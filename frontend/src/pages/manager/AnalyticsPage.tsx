import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  ErrorState,
  LoadingState,
  Metric,
  PageHeader,
} from '../../components/ui'
import { getAnalytics } from '../../lib/api'

type Range = '7d' | '30d' | '90d' | 'all'
const ranges: Array<[Range, string]> = [
  ['7d', 'Last 7 days'],
  ['30d', 'Last 30 days'],
  ['90d', 'Last 90 days'],
  ['all', 'All time'],
]
const percentage = (value: number | null) =>
  value === null ? '—' : `${value}%`

function trendTickInterval(range: Range, bucketCount: number) {
  if (range === '7d') return 1
  if (range === '30d') return 5
  if (range === '90d') return 2
  return Math.max(1, Math.ceil(bucketCount / 8))
}

function formatTrendTick(label: string, range: Range, includeYear: boolean) {
  const [year, month, day = 1] = label.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.toLocaleDateString('en-US', {
    month: 'short',
    ...(range === 'all' ? {} : { day: 'numeric' }),
    ...(includeYear ? { year: 'numeric' } : {}),
    timeZone: 'UTC',
  })
}

function trendTickLabels(labels: string[], range: Range) {
  const interval = trendTickInterval(range, labels.length)
  const tickIndexes = labels
    .map((_, index) => index)
    .filter((index) => index % interval === 0 || index === labels.length - 1)
  const multipleYears =
    new Set(labels.map((label) => label.slice(0, 4))).size > 1
  let previousTickYear: string | undefined
  return new Map(
    tickIndexes.map((index) => {
      const year = labels[index].slice(0, 4)
      const includeYear = multipleYears && year !== previousTickYear
      previousTickYear = year
      return [index, formatTrendTick(labels[index], range, includeYear)]
    }),
  )
}

function Breakdown({
  title,
  values,
}: {
  title: string
  values: Array<{ label: string; count: number; percentage: number }>
}) {
  return (
    <section className="border border-slate-200 bg-white">
      <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
        {title}
      </h2>
      {values.length ? (
        <dl className="space-y-4 p-5">
          {values.map((item) => (
            <div key={item.label} className="text-sm">
              <div className="flex justify-between gap-3">
                <dt>{item.label}</dt>
                <dd className="font-semibold">
                  {item.count} · {item.percentage}%
                </dd>
              </div>
              <div
                className="mt-2 h-2 bg-slate-100"
                role="img"
                aria-label={`${item.label}: ${item.count}, ${item.percentage}%`}
              >
                <div
                  className="h-2 bg-blue-600"
                  style={{ width: `${item.percentage}%` }}
                />
              </div>
            </div>
          ))}
        </dl>
      ) : (
        <p className="p-5 text-sm text-slate-600">
          No classified messages in this period.
        </p>
      )}
    </section>
  )
}

export function AnalyticsPage() {
  const [range, setRange] = useState<Range>('30d')
  const analytics = useQuery({
    queryKey: ['manager', 'analytics', range],
    queryFn: () => getAnalytics(range),
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
  const trendMax = Math.max(1, ...data.volume_trend.map((item) => item.count))
  const trendLabels = trendTickLabels(
    data.volume_trend.map((item) => item.label),
    range,
  )
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency oversight"
        title="Analytics"
        description="Historical carrier-AI performance, processing outcomes, and document extraction quality."
      />
      <div className="flex flex-wrap gap-2" aria-label="Analytics time range">
        {ranges.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setRange(value)}
            className={`border px-3 py-2 text-sm font-medium ${range === value ? 'border-blue-700 bg-blue-700 text-white' : 'border-slate-300 bg-white text-slate-700'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <section
        className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6"
        aria-label="Historical performance metrics"
      >
        <Metric label="Carrier messages" value={data.carrier_messages} />
        <Metric
          label="Automation rate"
          value={percentage(data.automation_rate)}
        />
        <Metric label="Review rate" value={percentage(data.review_rate)} />
        <Metric
          label="Failure rate"
          value={percentage(data.failure_rate)}
          attention={Boolean(data.failure_rate)}
        />
        <Metric
          label="Average processing time"
          value={
            data.average_processing_seconds === null
              ? '—'
              : `${data.average_processing_seconds}s`
          }
        />
        <Metric
          label="PDF extraction success"
          value={percentage(data.pdf_extraction_success_rate)}
        />
      </section>
      <section className="grid gap-5 xl:grid-cols-2">
        <Breakdown title="Processing outcomes" values={data.outcomes} />
        <Breakdown
          title="Message classifications"
          values={data.classifications}
        />
      </section>
      <section className="border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="font-semibold">Carrier message volume over time</h2>
          <p className="mt-1 text-sm text-slate-500">
            Received carrier messages in the selected period.
          </p>
        </div>
        <div className="flex min-h-48 items-end gap-1 overflow-x-auto p-5">
          {data.volume_trend.map((item, index) => (
            <div
              key={item.label}
              className="flex min-w-5 flex-1 flex-col items-center justify-end gap-2"
              aria-label={`${item.label}: ${item.count} carrier messages`}
            >
              <span className="text-xs font-medium">{item.count}</span>
              <div
                className="w-full bg-blue-600"
                style={{
                  height: `${Math.max(item.count ? 8 : 2, (item.count / trendMax) * 120)}px`,
                }}
              />
              <span className="h-4 text-[10px] whitespace-nowrap text-slate-500">
                {trendLabels.has(index) && (
                  <span data-testid="volume-axis-label">
                    {trendLabels.get(index)}
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      </section>
      <section className="overflow-x-auto border border-slate-200 bg-white">
        <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
          Carrier AI performance
        </h2>
        <table className="w-full min-w-[700px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
            <tr>
              {[
                'Carrier',
                'Messages',
                'Automation rate',
                'Review rate',
                'Failure rate',
              ].map((label) => (
                <th key={label} className="px-4 py-3">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.carrier_performance.map((item) => (
              <tr key={item.carrier_id}>
                <td className="px-4 py-3 font-medium">{item.carrier_name}</td>
                <td className="px-4 py-3">{item.messages}</td>
                <td className="px-4 py-3">
                  {percentage(item.automation_rate)}
                </td>
                <td className="px-4 py-3">{percentage(item.review_rate)}</td>
                <td className="px-4 py-3">{percentage(item.failure_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data.carrier_performance.length && (
          <p className="p-5 text-sm text-slate-600">
            No carrier messages in this period.
          </p>
        )}
      </section>
      <section className="border border-slate-200 bg-white">
        <h2 className="border-b border-slate-200 px-5 py-4 font-semibold">
          Attachment processing
        </h2>
        <dl className="grid gap-px bg-slate-200 sm:grid-cols-4">
          {[
            ['PDFs processed', data.attachments.pdfs_processed],
            ['Extracted successfully', data.attachments.extracted_successfully],
            ['Needs OCR', data.attachments.needs_ocr],
            ['Failed / unsupported', data.attachments.failed_or_unsupported],
          ].map(([label, value]) => (
            <div key={label} className="bg-white p-5">
              <dt className="text-sm text-slate-500">{label}</dt>
              <dd className="mt-2 text-2xl font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  )
}
