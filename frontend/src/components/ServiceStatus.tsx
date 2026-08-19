type ServiceStatusProps = {
  label: string
  detail: string
  state: 'checking' | 'healthy' | 'unavailable'
}

const stateStyles = {
  checking: {
    dot: 'bg-amber-500',
    text: 'text-amber-800',
    label: 'Checking',
  },
  healthy: {
    dot: 'bg-emerald-600',
    text: 'text-emerald-800',
    label: 'Operational',
  },
  unavailable: {
    dot: 'bg-red-600',
    text: 'text-red-800',
    label: 'Unavailable',
  },
} as const

export function ServiceStatus({ label, detail, state }: ServiceStatusProps) {
  const style = stateStyles[state]

  return (
    <section className="border-t border-slate-200 py-5 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{label}</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">{detail}</p>
        </div>
        <p
          className={`flex shrink-0 items-center gap-2 text-sm font-medium ${style.text}`}
        >
          <span
            className={`h-2 w-2 rounded-full ${style.dot}`}
            aria-hidden="true"
          />
          {style.label}
        </p>
      </div>
    </section>
  )
}
