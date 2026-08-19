import { EmptyState, PageHeader } from '../../components/ui'

export function SettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agency configuration"
        title="Settings / Integrations"
        description="Reserved for deliberate external integration configuration."
      />
      <EmptyState
        title="No external integration configured"
        description="CRM webhook delivery and other external integrations are not implemented in this stage. No credentials or connectivity are being simulated."
      />
    </div>
  )
}
