import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useEffect, useState } from 'react'

import type { Analytics } from '../lib/types'

type Range = Analytics['range']

function useReducedMotion() {
  const [reduced, setReduced] = useState(false)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(media.matches)
    update()
    media.addEventListener?.('change', update)
    return () => media.removeEventListener?.('change', update)
  }, [])

  return reduced
}

function tickInterval(range: Range, bucketCount: number) {
  if (range === '7d') return 1
  if (range === '30d') return 5
  if (range === '90d') return 2
  return Math.max(1, Math.ceil(bucketCount / 8))
}

function formatDateTick(label: string, range: Range, includeYear = false) {
  const [year, month, day = 1] = label.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-US', {
    month: 'short',
    ...(range === 'all' ? {} : { day: 'numeric' }),
    ...(includeYear ? { year: 'numeric' } : {}),
    timeZone: 'UTC',
  })
}

function visibleTicks(data: Analytics['volume_trend'], range: Range) {
  const interval = tickInterval(range, data.length)
  const indexes = data
    .map((_, index) => index)
    .filter((index) => index % interval === 0 || index === data.length - 1)
  const multipleYears =
    new Set(data.map((item) => item.label.slice(0, 4))).size > 1
  let previousYear: string | undefined
  return new Map(
    indexes.map((index) => {
      const year = data[index].label.slice(0, 4)
      const includeYear = multipleYears && year !== previousYear
      previousYear = year
      return [index, formatDateTick(data[index].label, range, includeYear)]
    }),
  )
}

const tooltipStyle = {
  border: '1px solid #dbe3ed',
  borderRadius: '10px',
  boxShadow: '0 12px 30px rgb(15 23 42 / 10%)',
  fontSize: '12px',
}

export function VolumeAreaChart({
  data,
  range,
}: {
  data: Analytics['volume_trend']
  range: Range
}) {
  const ticks = visibleTicks(data, range)
  const reducedMotion = useReducedMotion()
  return (
    <>
      <div className="h-72 w-full" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            margin={{ top: 16, right: 12, left: -24, bottom: 0 }}
          >
            <defs>
              <linearGradient id="volumeFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#2563eb" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#2563eb" stopOpacity={0.015} />
              </linearGradient>
            </defs>
            <CartesianGrid
              vertical={false}
              stroke="#e8eef5"
              strokeDasharray="3 3"
            />
            <XAxis
              dataKey="label"
              axisLine={false}
              tickLine={false}
              minTickGap={36}
              tick={{ fill: '#64748b', fontSize: 11 }}
              tickFormatter={(value: string) => formatDateTick(value, range)}
            />
            <YAxis
              allowDecimals={false}
              axisLine={false}
              tickLine={false}
              tick={{ fill: '#94a3b8', fontSize: 11 }}
            />
            <Tooltip
              contentStyle={tooltipStyle}
              labelFormatter={(value) =>
                formatDateTick(String(value), range, true)
              }
              formatter={(value) => [Number(value), 'Messages']}
              cursor={{ stroke: '#93c5fd', strokeDasharray: '4 4' }}
            />
            <Area
              type="monotone"
              dataKey="count"
              stroke="#2563eb"
              strokeWidth={2.5}
              fill="url(#volumeFill)"
              activeDot={{ r: 5, strokeWidth: 3, stroke: '#dbeafe' }}
              isAnimationActive={!reducedMotion}
              animationDuration={650}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="sr-only">
        {data.map((item) => (
          <span
            key={item.label}
            aria-label={`${item.label}: ${item.count} carrier messages`}
          />
        ))}
        {[...ticks.values()].map((label) => (
          <span key={label} data-testid="volume-axis-label">
            {label}
          </span>
        ))}
      </div>
    </>
  )
}

const outcomeColors = ['#2563eb', '#d97706', '#dc2626', '#94a3b8']

export function OutcomeDonut({
  data,
  total,
}: {
  data: Analytics['outcomes']
  total: number
}) {
  const reducedMotion = useReducedMotion()
  const chartData = data.length
    ? data
    : [{ label: 'No outcomes', count: 1, percentage: 100 }]
  return (
    <div className="grid items-center gap-4 sm:grid-cols-[180px_1fr] xl:grid-cols-1 2xl:grid-cols-[180px_1fr]">
      <div className="relative mx-auto h-44 w-44" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              dataKey="count"
              nameKey="label"
              innerRadius={58}
              outerRadius={78}
              paddingAngle={2}
              stroke="none"
              isAnimationActive={!reducedMotion}
              animationDuration={650}
            >
              {chartData.map((item, index) => (
                <Cell
                  key={item.label}
                  fill={
                    data.length
                      ? outcomeColors[index % outcomeColors.length]
                      : '#e2e8f0'
                  }
                />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-semibold tracking-tight text-slate-950">
            {total}
          </span>
          <span className="mt-0.5 text-[0.65rem] font-bold tracking-wider text-slate-500 uppercase">
            messages
          </span>
        </div>
      </div>
      <div className="space-y-3">
        {data.map((item, index) => (
          <div
            key={item.label}
            className="flex items-center justify-between gap-4 text-sm"
          >
            <div className="flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{
                  background: outcomeColors[index % outcomeColors.length],
                }}
              />
              <span className="text-slate-600">{item.label}</span>
            </div>
            <span className="font-semibold text-slate-900">
              {item.percentage}%
            </span>
          </div>
        ))}
      </div>
      <p className="sr-only">
        {data.length
          ? data
              .map(
                (item) =>
                  `${item.label}: ${item.count}, ${item.percentage} percent`,
              )
              .join('. ')
          : 'No processing outcomes are available.'}
      </p>
    </div>
  )
}

export function CarrierPerformanceChart({
  data,
}: {
  data: Analytics['carrier_performance']
}) {
  const reducedMotion = useReducedMotion()
  if (!data.length)
    return (
      <p className="py-12 text-center text-sm text-slate-500">
        No carrier data in this period.
      </p>
    )
  return (
    <div
      className="h-64 w-full"
      role="img"
      aria-label={`Carrier automation rates. ${data
        .map((item) => `${item.carrier_name}: ${item.automation_rate} percent`)
        .join('. ')}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, left: 18, bottom: 4 }}
        >
          <CartesianGrid
            horizontal={false}
            stroke="#e8eef5"
            strokeDasharray="3 3"
          />
          <XAxis
            type="number"
            domain={[0, 100]}
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickFormatter={(value) => `${value}%`}
          />
          <YAxis
            type="category"
            dataKey="carrier_name"
            width={118}
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#475569', fontSize: 11 }}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value) => `${Number(value)}%`}
          />
          <Bar
            dataKey="automation_rate"
            name="Automation"
            fill="#2563eb"
            radius={[0, 4, 4, 0]}
            maxBarSize={18}
            isAnimationActive={!reducedMotion}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ProgressRing({
  value,
  label,
}: {
  value: number | null
  label: string
}) {
  const safeValue = Math.min(100, Math.max(0, value ?? 0))
  const circumference = 2 * Math.PI * 46
  return (
    <div
      className="relative h-32 w-32"
      role="img"
      aria-label={`${label}: ${value ?? 'not available'}`}
    >
      <svg
        className="h-full w-full -rotate-90"
        viewBox="0 0 112 112"
        aria-hidden
      >
        <circle
          cx="56"
          cy="56"
          r="46"
          fill="none"
          stroke="rgb(255 255 255 / 10%)"
          strokeWidth="8"
        />
        <circle
          cx="56"
          cy="56"
          r="46"
          fill="none"
          stroke="#60a5fa"
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - safeValue / 100)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-semibold text-white">
          {value === null ? '—' : `${value}%`}
        </span>
        <span className="mt-0.5 text-[0.6rem] font-bold tracking-wider text-blue-200 uppercase">
          {label}
        </span>
      </div>
    </div>
  )
}
