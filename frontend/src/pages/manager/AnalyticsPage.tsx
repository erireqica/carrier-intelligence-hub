import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, FileCheck2, Gauge } from 'lucide-react'

import {
  CarrierPerformanceChart,
  OutcomeDonut,
  ProgressRing,
  VolumeAreaChart,
} from '../../components/analytics-charts'
import { ErrorState, LoadingState, PageHeader } from '../../components/ui'
import { getAnalytics } from '../../lib/api'

type Range = '7d' | '30d' | '90d' | 'all'
const ranges: Array<[Range, string]> = [
  ['7d', '7 days'],
  ['30d', '30 days'],
  ['90d', '90 days'],
  ['all', 'All time'],
]
const percentage = (value: number | null) =>
  value === null ? '—' : `${value}%`

function SectionHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description?: string
}) {
  return (
    <div>
      <p className="text-[0.66rem] font-bold tracking-[0.16em] text-blue-700 uppercase">
        {eyebrow}
      </p>
      <h2 className="mt-1 text-lg font-semibold tracking-tight text-slate-950">
        {title}
      </h2>
      {description && (
        <p className="mt-1 text-sm leading-5 text-slate-500">{description}</p>
      )}
    </div>
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
  const attachments = data.attachments
  const extractionTotal = Math.max(1, attachments.pdfs_processed)

  return (
    <div className="app-page space-y-6">
      <PageHeader
        eyebrow="Agency intelligence"
        title="Analytics"
        description="A clear view of automation quality, carrier volume, and document-processing reliability."
        action={
          <div
            className="inline-flex rounded-lg border border-slate-200 bg-white p-1 shadow-sm"
            aria-label="Analytics time range"
          >
            {ranges.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setRange(value)}
                className={`rounded-md px-3 py-2 text-xs font-semibold ${
                  range === value
                    ? 'bg-slate-900 text-white shadow-sm'
                    : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        }
      />

      <section className="analytics-command-grid overflow-hidden rounded-2xl bg-[#12243c] text-white shadow-[0_18px_46px_rgb(15_23_42/14%)]">
        <div className="relative overflow-hidden p-6 sm:p-8">
          <div className="absolute -top-20 -right-16 h-64 w-64 rounded-full border border-white/10" />
          <div className="absolute top-6 right-8 h-24 w-24 rounded-full border border-blue-300/10" />
          <div className="relative">
            <div className="flex items-center gap-2 text-xs font-bold tracking-[0.16em] text-blue-200 uppercase">
              <Gauge className="h-4 w-4" aria-hidden /> Successful automation
            </div>
            <div className="mt-7 flex flex-wrap items-center gap-8">
              <ProgressRing
                value={data.automation_rate}
                label="auto-processed"
              />
              <div className="max-w-md">
                <p className="text-xs font-semibold tracking-wide text-blue-200 uppercase">
                  Of successfully processed messages
                </p>
                <p className="text-2xl font-semibold tracking-tight sm:text-3xl">
                  {data.carrier_messages} carrier communications
                </p>
                <p className="mt-2 max-w-sm text-sm leading-6 text-slate-300">
                  Processed through the agency workflow during this reporting
                  window, with human attention reserved for uncertain outcomes.
                </p>
              </div>
            </div>
          </div>
        </div>
        <dl className="grid border-t border-white/10 bg-white/[0.035] sm:grid-cols-3 2xl:border-t-0 2xl:border-l">
          {[
            ['Review rate', percentage(data.review_rate), 'Human verification'],
            [
              'Failure rate',
              percentage(data.failure_rate),
              'Processing exceptions',
            ],
            [
              'Average cycle',
              data.average_processing_seconds === null
                ? 'No timing data'
                : `${data.average_processing_seconds}s`,
              'Analysis start to processed · normal completed cycles',
            ],
          ].map(([label, value, note]) => (
            <div
              key={label}
              className="border-white/10 p-5 sm:border-r sm:last:border-r-0 2xl:flex 2xl:flex-col 2xl:justify-center 2xl:border-r-0 2xl:border-b 2xl:last:border-b-0"
            >
              <dt className="text-xs font-semibold text-slate-400">{label}</dt>
              <dd className="mt-2 text-2xl font-semibold tracking-tight">
                {value}
              </dd>
              <p className="mt-1 text-xs text-slate-400">{note}</p>
            </div>
          ))}
        </dl>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,0.8fr)]">
        <div className="surface-panel p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <SectionHeading
              eyebrow="Volume"
              title="Carrier message flow"
              description="Incoming communications across the selected period."
            />
            <div className="text-right">
              <p className="text-2xl font-semibold tracking-tight text-slate-950">
                {data.carrier_messages}
              </p>
              <p className="text-xs text-slate-500">total messages</p>
            </div>
          </div>
          <div className="mt-4">
            <VolumeAreaChart data={data.volume_trend} range={range} />
          </div>
        </div>
        <div className="surface-panel p-5 sm:p-6">
          <SectionHeading
            eyebrow="Outcomes"
            title="Processing distribution"
            description="Where communications landed after validation."
          />
          <div className="mt-5">
            <OutcomeDonut data={data.outcomes} total={data.carrier_messages} />
          </div>
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.75fr)]">
        <div className="surface-panel p-5 sm:p-6">
          <SectionHeading
            eyebrow="Classification mix"
            title="Message classifications"
            description="The operational reasons carriers are contacting the agency."
          />
          {data.classifications.length ? (
            <div className="mt-6 space-y-5">
              {data.classifications.map((item, index) => (
                <div key={item.label}>
                  <div className="mb-2 flex items-end justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <span className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-100 text-xs font-bold text-slate-600">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <span className="text-sm font-medium text-slate-800">
                        {item.label}
                      </span>
                    </div>
                    <span className="text-sm font-semibold text-slate-950">
                      {item.count}{' '}
                      <span className="font-normal text-slate-400">
                        / {item.percentage}%
                      </span>
                    </span>
                  </div>
                  <div
                    className="h-2 overflow-hidden rounded-full bg-slate-100"
                    role="img"
                    aria-label={`${item.label}: ${item.count}, ${item.percentage}%`}
                  >
                    <div
                      className="h-full rounded-full bg-blue-600"
                      style={{ width: `${item.percentage}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-6 text-sm text-slate-500">
              No classified messages in this period.
            </p>
          )}
        </div>
        <div className="surface-panel overflow-hidden">
          <div className="border-b border-slate-100 p-5 sm:p-6">
            <SectionHeading
              eyebrow="Document intelligence"
              title="Attachment quality"
              description="PDF extraction readiness for automated analysis."
            />
          </div>
          <div className="p-5 sm:p-6">
            <div className="flex items-center gap-4">
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
                <FileCheck2 className="h-6 w-6" aria-hidden />
              </span>
              <div>
                <p className="text-3xl font-semibold tracking-tight text-slate-950">
                  {percentage(data.pdf_extraction_success_rate)}
                </p>
                <p className="text-sm text-slate-500">extraction success</p>
              </div>
            </div>
            <div className="mt-6 flex h-2.5 overflow-hidden rounded-full bg-slate-100">
              {attachments.pdfs_processed > 0 && (
                <>
                  <div
                    className="bg-emerald-500"
                    style={{
                      width: `${(attachments.extracted_successfully / extractionTotal) * 100}%`,
                    }}
                  />
                  <div
                    className="bg-amber-400"
                    style={{
                      width: `${(attachments.needs_ocr / extractionTotal) * 100}%`,
                    }}
                  />
                  <div
                    className="bg-red-400"
                    style={{
                      width: `${(attachments.failed_or_unsupported / extractionTotal) * 100}%`,
                    }}
                  />
                </>
              )}
            </div>
            <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 text-sm">
              {[
                ['PDFs processed', attachments.pdfs_processed],
                ['Extracted', attachments.extracted_successfully],
                ['Needs OCR', attachments.needs_ocr],
                ['Failed / unsupported', attachments.failed_or_unsupported],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-slate-500">{label}</dt>
                  <dd className="mt-1 text-lg font-semibold text-slate-900">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </section>

      <section className="surface-panel overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 p-5 sm:p-6">
          <SectionHeading
            eyebrow="Carrier comparison"
            title="Carrier AI performance"
            description="Automation yield and exception rates by carrier."
          />
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500">
            Ranked by automation{' '}
            <ArrowUpRight className="h-4 w-4" aria-hidden />
          </span>
        </div>
        <div className="grid xl:grid-cols-[minmax(0,0.9fr)_minmax(580px,1.1fr)]">
          <div className="border-b border-slate-100 p-5 sm:p-6 xl:border-r xl:border-b-0">
            <CarrierPerformanceChart data={data.carrier_performance} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[580px] text-left text-sm">
              <thead className="bg-slate-50/70 text-[0.65rem] text-slate-500 uppercase">
                <tr>
                  {[
                    'Carrier',
                    'Messages',
                    'Auto-processed',
                    'Review',
                    'Failure',
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
                    <td className="px-4 py-3.5 font-semibold text-slate-900">
                      {item.carrier_name}
                    </td>
                    <td className="px-4 py-3.5">{item.messages}</td>
                    <td className="px-4 py-3.5 text-emerald-700">
                      {percentage(item.automation_rate)}
                    </td>
                    <td className="px-4 py-3.5">
                      {percentage(item.review_rate)}
                    </td>
                    <td className="px-4 py-3.5 text-red-700">
                      {percentage(item.failure_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.carrier_performance.length && (
              <p className="p-6 text-sm text-slate-500">
                No carrier messages in this period.
              </p>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
