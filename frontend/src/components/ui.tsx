import type {
  ButtonHTMLAttributes,
  FormEvent,
  InputHTMLAttributes,
  ReactNode,
} from 'react'
import { useId, useState } from 'react'

import type { Priority } from '../lib/types'

export function Button({
  className = '',
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?:
    'primary' | 'secondary' | 'danger' | 'dangerSecondary' | 'success' | 'info'
}) {
  const variants = {
    primary: 'border-slate-900 bg-slate-900 text-white hover:bg-slate-700',
    secondary: 'border-slate-300 bg-white text-slate-800 hover:bg-slate-50',
    danger: 'border-red-700 bg-red-700 text-white hover:bg-red-800',
    dangerSecondary:
      'border-red-700 bg-white text-red-700 hover:bg-red-50 hover:text-red-800',
    success:
      'border-emerald-700 bg-emerald-700 text-white hover:bg-emerald-800',
    info: 'border-blue-700 bg-blue-700 text-white hover:bg-blue-800',
  }
  return (
    <button
      className={`inline-flex min-h-10 items-center justify-center border px-4 py-2 text-sm font-semibold transition-colors focus:outline-2 focus:outline-offset-2 focus:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
      {...props}
    />
  )
}

export function Input({
  className = '',
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`min-h-10 w-full border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none focus:border-slate-600 focus:ring-2 focus:ring-slate-200 ${className}`}
      {...props}
    />
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <header className="flex flex-col gap-4 border-b border-slate-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && (
          <p className="text-xs font-semibold tracking-[0.12em] text-slate-500 uppercase">
            {eyebrow}
          </p>
        )}
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-3xl text-sm text-slate-600">{description}</p>
        )}
      </div>
      {action}
    </header>
  )
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: string
}) {
  const tones: Record<string, string> = {
    neutral: 'border-slate-300 bg-slate-50 text-slate-700',
    blue: 'border-blue-200 bg-blue-50 text-blue-800',
    green: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    amber: 'border-amber-200 bg-amber-50 text-amber-900',
    red: 'border-red-200 bg-red-50 text-red-800',
  }
  return (
    <span
      className={`inline-flex border px-2 py-0.5 text-xs font-semibold ${tones[tone] ?? tones.neutral}`}
    >
      {children}
    </span>
  )
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  const tone = { LOW: 'neutral', NORMAL: 'blue', HIGH: 'amber', URGENT: 'red' }[
    priority
  ]
  return <Badge tone={tone}>{priority}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status.includes('FAIL')
    ? 'red'
    : status.includes('REVIEW') || status === 'PENDING' || status === 'OPEN'
      ? 'amber'
      : status.includes('COMPLETE') ||
          status === 'ISSUED' ||
          status === 'PROCESSED'
        ? 'green'
        : 'blue'
  return <Badge tone={tone}>{status.replaceAll('_', ' ')}</Badge>
}

export function LoadingState({
  label = 'Loading workspace…',
}: {
  label?: string
}) {
  return (
    <div
      className="border border-slate-200 bg-white p-8 text-sm text-slate-600"
      role="status"
    >
      {label}
    </div>
  )
}

export function ErrorState({
  message,
  retry,
}: {
  message: string
  retry?: () => void
}) {
  return (
    <div className="border border-red-200 bg-red-50 p-5" role="alert">
      <h2 className="font-semibold text-red-900">
        Unable to load this information
      </h2>
      <p className="mt-1 text-sm text-red-800">{message}</p>
      {retry && (
        <Button className="mt-4" variant="secondary" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="border border-slate-200 bg-white px-6 py-10 text-center">
      <h2 className="font-semibold text-slate-900">{title}</h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-600">
        {description}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Metric({
  label,
  value,
  attention = false,
}: {
  label: string
  value: ReactNode
  attention?: boolean
}) {
  return (
    <div className="border border-slate-200 bg-white p-5">
      <p className="text-sm font-medium text-slate-600">{label}</p>
      <p
        className={`mt-2 text-3xl font-semibold ${attention && value ? 'text-red-700' : 'text-slate-950'}`}
      >
        {value}
      </p>
    </div>
  )
}

export function Pagination({
  page,
  pages,
  onPageChange,
  label = 'Pagination',
  summary,
}: {
  page: number
  pages: number
  onPageChange: (page: number) => void
  label?: string
  summary?: ReactNode
}) {
  const safePages = Math.max(1, pages)
  const safePage = Math.min(Math.max(1, page), safePages)
  if (safePages <= 1) return null
  return (
    <PaginationControls
      key={safePage}
      page={safePage}
      pages={safePages}
      onPageChange={onPageChange}
      label={label}
      summary={summary}
    />
  )
}

function PaginationControls({
  page,
  pages,
  onPageChange,
  label,
  summary,
}: {
  page: number
  pages: number
  onPageChange: (page: number) => void
  label: string
  summary?: ReactNode
}) {
  const [requestedPage, setRequestedPage] = useState(String(page))
  const [validationError, setValidationError] = useState<string | null>(null)
  const errorId = useId()

  function navigateTo(nextPage: number) {
    setRequestedPage(String(nextPage))
    setValidationError(null)
    onPageChange(nextPage)
  }

  function submitPage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalized = requestedPage.trim()
    if (!/^-?\d+$/.test(normalized)) {
      setValidationError('Enter a valid whole page number.')
      return
    }
    const nextPage = Number(normalized)
    if (!Number.isSafeInteger(nextPage)) {
      setValidationError('Enter a valid whole page number.')
      return
    }
    if (nextPage < 1) {
      setValidationError('Page number must be at least 1.')
      return
    }
    if (nextPage > pages) {
      setValidationError(
        `Page ${nextPage} does not exist. There are ${pages} pages.`,
      )
      return
    }
    navigateTo(nextPage)
  }

  return (
    <nav
      className="flex items-start justify-between gap-3 text-sm"
      aria-label={label}
    >
      <Button
        variant="secondary"
        disabled={page <= 1}
        onClick={() => navigateTo(page - 1)}
      >
        Previous
      </Button>
      <form
        className="flex flex-col items-center gap-1"
        onSubmit={submitPage}
        noValidate
      >
        <div className="flex items-center gap-2">
          <span>Page</span>
          <input
            className="min-h-10 w-14 border border-slate-300 bg-white px-2 py-1 text-center text-sm text-slate-950 outline-none focus:border-slate-600 focus:ring-2 focus:ring-slate-200"
            type="number"
            inputMode="numeric"
            min={1}
            max={pages}
            step={1}
            aria-label="Go to page"
            aria-invalid={Boolean(validationError)}
            aria-describedby={validationError ? errorId : undefined}
            value={requestedPage}
            onChange={(event) => setRequestedPage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
          />
          <span>of {pages}</span>
          {summary && <span>· {summary}</span>}
        </div>
        {validationError && (
          <span id={errorId} className="text-xs text-red-700" role="alert">
            {validationError}
          </span>
        )}
      </form>
      <Button
        variant="secondary"
        disabled={page >= pages}
        onClick={() => navigateTo(page + 1)}
      >
        Next
      </Button>
    </nav>
  )
}
