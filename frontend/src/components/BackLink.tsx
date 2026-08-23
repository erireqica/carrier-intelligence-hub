import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'

export function BackLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      className="group inline-flex w-fit items-center gap-2.5 rounded-xl border border-slate-200/90 bg-white px-2.5 py-2 pr-3.5 text-sm font-semibold text-slate-700 shadow-[0_3px_12px_rgb(15_23_42/6%)] transition duration-200 hover:-translate-y-0.5 hover:border-blue-200 hover:bg-blue-50/70 hover:text-blue-800 hover:shadow-[0_6px_18px_rgb(15_23_42/9%)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 motion-reduce:transform-none"
      to={to}
    >
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-600 transition duration-200 group-hover:bg-white group-hover:text-blue-700">
        <ArrowLeft
          className="h-4 w-4 transition-transform duration-200 group-hover:-translate-x-0.5 motion-reduce:transform-none"
          aria-hidden
        />
      </span>
      <span>{label}</span>
    </Link>
  )
}
