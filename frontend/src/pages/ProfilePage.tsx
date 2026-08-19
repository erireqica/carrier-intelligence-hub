import { useCurrentUser } from '../app/auth'
import { PageHeader, StatusBadge } from '../components/ui'
import { formatDate } from '../lib/format'

export function ProfilePage() {
  const user = useCurrentUser().data!.user
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Account"
        title="Profile"
        description="Your internal Carrier Intelligence Hub identity."
      />
      <dl className="max-w-2xl divide-y divide-slate-100 border border-slate-200 bg-white">
        {[
          ['Full name', user.full_name],
          ['Email', user.email],
          ['Role', user.role],
          ['Agency', user.agency.name],
          ['Agency timezone', user.agency.timezone],
          ['Last login', formatDate(user.last_login_at)],
        ].map(([label, value]) => (
          <div
            key={label}
            className="grid grid-cols-[160px_1fr] px-5 py-4 text-sm"
          >
            <dt className="font-medium text-slate-500">{label}</dt>
            <dd className="text-slate-900">{value}</dd>
          </div>
        ))}
        <div className="grid grid-cols-[160px_1fr] px-5 py-4 text-sm">
          <dt className="font-medium text-slate-500">Account status</dt>
          <dd>
            <StatusBadge status={user.is_active ? 'ACTIVE' : 'DISABLED'} />
          </dd>
        </div>
      </dl>
    </div>
  )
}
