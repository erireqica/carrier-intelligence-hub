export type Role = 'AGENT' | 'MANAGER'
export type Priority = 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT'
export type TaskStatus = 'OPEN' | 'IN_PROGRESS' | 'COMPLETED' | 'DISMISSED'
export type ProcessingStatus =
  | 'RECEIVED'
  | 'PROCESSING'
  | 'PROCESSED'
  | 'NEEDS_REVIEW'
  | 'FAILED'
  | 'IGNORED'
export type GmailHealth = 'CONNECTED' | 'NEEDS_ATTENTION' | 'NOT_CONNECTED'
export type GmailConnectionStatus =
  'CONNECTED' | 'NEEDS_REAUTH' | 'ERROR' | 'DISCONNECTED'

export type AgentBrief = { id: number; full_name: string; email: string }
export type CarrierBrief = { id: number; name: string; code: string | null }

export type AuthResponse = {
  user: {
    id: number
    email: string
    full_name: string
    role: Role
    is_active: boolean
    last_login_at: string | null
    agency: { id: number; name: string; timezone: string }
  }
  csrf_token: string
  environment: string
}

export type PageInfo = {
  page: number
  page_size: number
  total: number
  pages: number
}

export type CaseItem = {
  id: number
  client_name: string
  policy_number: string | null
  policy_status: string
  priority: Priority
  summary: string
  deadline: string | null
  updated_at: string
  carrier: CarrierBrief
  assigned_agent: AgentBrief | null
  needs_review: boolean
}

export type TaskItem = {
  id: number
  case_id: number
  client_name: string
  policy_number: string | null
  title: string
  description: string | null
  priority: Priority
  due_at: string | null
  status: TaskStatus
  completed_at: string | null
  assigned_agent: AgentBrief
}

export type ActivityItem = {
  id: number
  event_type: string
  severity: 'INFO' | 'WARNING' | 'ERROR'
  description: string
  created_at: string
}

export type CaseDetail = CaseItem & {
  premium_amount: string | null
  currency: string | null
  effective_date: string | null
  messages: Array<{
    id: number
    sender: string
    subject: string
    received_at: string
    classification: string | null
    summary: string | null
    priority: Priority | null
    processing_status: ProcessingStatus
    cleaned_content: string
    original_deadline_text: string | null
  }>
  attachments: Array<{
    id: number
    filename: string
    mime_type: string
    size_bytes: number
    processing_status: string
  }>
  tasks: TaskItem[]
  evidence: Array<{
    id: number
    field_name: string
    source_type: string
    excerpt: string
  }>
  activity: ActivityItem[]
}

export type ReviewItem = {
  id: number
  case_id: number | null
  client_name: string | null
  policy_number: string | null
  carrier_name: string
  message_subject: string
  reason_code: string
  reason: string
  status: string
  resolution_notes: string | null
  assigned_reviewer: AgentBrief | null
  created_at: string
  resolved_at: string | null
}

export type Dashboard = {
  metrics: {
    urgent_cases: number
    open_tasks: number
    overdue_tasks: number
    review_items: number
    processing_failures: number
    processed_messages: number
  }
  recent_cases: CaseItem[]
  recent_activity: ActivityItem[]
  workload: Array<{ agent: AgentBrief; open_tasks: number }>
  gmail_connected: boolean
  gmail_health: GmailHealth
}

export type GmailConnection = {
  id: number
  gmail_address: string
  owner: AgentBrief
  status: GmailConnectionStatus
  connected_at: string | null
  last_successful_sync_at: string | null
  last_attempted_sync_at: string | null
  last_error_summary: string | null
  is_owner: boolean
}

export type GmailConnectionsResponse = {
  configured: boolean
  connections: GmailConnection[]
}

export type GmailSyncResult = {
  connection_id: number
  messages_seen: number
  already_ingested: number
  approved: number
  ingested: number
  skipped_unapproved: number
  attachments_discovered: number
}

export type GmailMessage = {
  id: number
  carrier: CarrierBrief
  sender: string
  subject: string
  received_at: string
  processing_status: ProcessingStatus
  attachment_count: number
}

export type AgentItem = {
  id: number
  full_name: string
  email: string
  role: Role
  is_active: boolean
  last_login_at: string | null
  open_tasks: number
  urgent_cases: number
  gmail_connections: number
}

export type CarrierItem = {
  id: number
  name: string
  code: string | null
  notes: string | null
  is_enabled: boolean
  domains: Array<{ id: number; domain: string; is_enabled: boolean }>
  senders: Array<{ id: number; email: string; is_enabled: boolean }>
}

export type Analytics = {
  cases_by_status: Record<string, number>
  cases_by_carrier: Record<string, number>
  workload_by_agent: Array<{ agent: AgentBrief; open_tasks: number }>
  urgent_high_cases: number
  open_tasks: number
  overdue_tasks: number
  open_reviews: number
  processed_messages: number
  failed_messages: number
}

export type AuditLog = {
  id: number
  event_type: string
  severity: 'INFO' | 'WARNING' | 'ERROR'
  actor_name: string | null
  description: string
  case_id: number | null
  task_id: number | null
  metadata: Record<string, unknown>
  created_at: string
}
