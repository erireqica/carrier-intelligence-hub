import { clearSessionState } from '../app/queryClient'
import { apiBaseUrl } from './api-url'
import type {
  AgentItem,
  Analytics,
  AuditLog,
  AuthResponse,
  CarrierItem,
  CaseDetail,
  CaseCorrectionInput,
  CaseItem,
  Dashboard,
  GmailConnectionsResponse,
  GmailMessage,
  GmailMessageListResponse,
  GmailSyncResult,
  HumanAnalysisInput,
  ManualTaskInput,
  MessageAnalysis,
  MessageProcessingResult,
  PageInfo,
  ReviewItem,
  ReviewDetail,
  TaskItem,
  TaskStatus,
} from './types'

let csrfToken: string | null = null

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function setCsrfToken(token: string | null) {
  csrfToken = token
}

type ValidationErrorDetail = {
  ctx?: { min_length?: number }
  loc?: Array<number | string>
  message?: string
  msg?: string
  type?: string
}

const fieldLabels: Record<string, string> = {
  confirm_new_password: 'Confirm new password',
  confirm_initial_password: 'Confirm initial password',
  current_password: 'Current password',
  email: 'Login email',
  full_name: 'Full name',
  new_password: 'New password',
  initial_password: 'Initial password',
  password: 'Password',
}

function finishSentence(message: string) {
  return /[.!?]$/.test(message) ? message : `${message}.`
}

function validationErrorMessage(detail: ValidationErrorDetail) {
  const field = [...(detail.loc ?? [])]
    .reverse()
    .find((part): part is string => typeof part === 'string')
  const label = field ? fieldLabels[field] : undefined
  const minimum = detail.ctx?.min_length
  if (detail.type === 'string_too_short' && label && minimum) {
    return `${label} must be at least ${minimum} characters.`
  }
  if (detail.type === 'missing' && label) return `${label} is required.`
  const message = detail.message ?? detail.msg
  if (!message) return null
  return finishSentence(message.replace(/^Value error,\s*/i, ''))
}

export function parseApiErrorMessage(body: unknown) {
  if (!body || typeof body !== 'object' || !('detail' in body)) return null
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    for (const item of detail) {
      if (item && typeof item === 'object') {
        const message = validationErrorMessage(item as ValidationErrorDetail)
        if (message) return message
      }
    }
    return null
  }
  if (detail && typeof detail === 'object') {
    return validationErrorMessage(detail as ValidationErrorDetail)
  }
  return null
}

export function isInvalidSessionResponse(path: string, status: number) {
  return status === 401 && path !== '/auth/login'
}

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = options.method?.toUpperCase() ?? 'GET'
  const unsafe = !['GET', 'HEAD', 'OPTIONS'].includes(method)
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body && !headers.has('Content-Type'))
    headers.set('Content-Type', 'application/json')
  if (unsafe && csrfToken) headers.set('X-CSRF-Token', csrfToken)

  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...options,
      credentials: 'include',
      headers,
    })
  } catch {
    throw new ApiError('The Carrier Intelligence API could not be reached.')
  }
  if (!response.ok) {
    let message = 'The request could not be completed.'
    try {
      const parsedMessage = parseApiErrorMessage(await response.json())
      if (parsedMessage) message = parsedMessage
    } catch {
      // The safe generic message is used for non-JSON errors.
    }
    if (
      isInvalidSessionResponse(path, response.status) &&
      window.location.pathname !== '/login'
    ) {
      setCsrfToken(null)
      await clearSessionState()
      window.location.replace('/login')
    }
    throw new ApiError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function login(email: string, password: string) {
  const response = await apiRequest<AuthResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setCsrfToken(response.csrf_token)
  return response
}

export async function getMe() {
  const response = await apiRequest<AuthResponse>('/auth/me')
  setCsrfToken(response.csrf_token)
  return response
}

export async function logout() {
  await apiRequest<{ message: string }>('/auth/logout', { method: 'POST' })
  setCsrfToken(null)
}

export const updateProfile = (data: {
  full_name: string
  email: string
  current_password?: string
}) =>
  apiRequest<AuthResponse>('/auth/profile', {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

export const uploadProfileAvatar = (file: File) =>
  apiRequest<AuthResponse>('/auth/profile/avatar', {
    method: 'PUT',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  })

export const removeProfileAvatar = () =>
  apiRequest<AuthResponse>('/auth/profile/avatar', { method: 'DELETE' })

export const changePassword = (data: {
  current_password: string
  new_password: string
  confirm_new_password: string
}) =>
  apiRequest<{ message: string }>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const getDashboard = () => apiRequest<Dashboard>('/dashboard')
export const getCases = (params = '') =>
  apiRequest<{ items: CaseItem[]; page: PageInfo }>(
    `/cases${params ? `?${params}` : ''}`,
  )
export const getCase = (id: string) => apiRequest<CaseDetail>(`/cases/${id}`)
export const dismissCase = (id: number) =>
  apiRequest<CaseDetail>(`/cases/${id}/dismiss`, { method: 'POST' })
export const restoreCase = (id: number) =>
  apiRequest<CaseDetail>(`/cases/${id}/restore`, { method: 'POST' })
export const completeCase = (id: number) =>
  apiRequest<CaseDetail>(`/cases/${id}/complete`, { method: 'POST' })
export const reopenCase = (id: number) =>
  apiRequest<CaseDetail>(`/cases/${id}/reopen`, { method: 'POST' })
export const correctCase = (id: number, data: CaseCorrectionInput) =>
  apiRequest<CaseDetail>(`/cases/${id}/correction`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
export const assignCase = (id: number, assignedAgentId: number) =>
  apiRequest<CaseDetail>(`/cases/${id}/assignment`, {
    method: 'PATCH',
    body: JSON.stringify({ assigned_agent_id: assignedAgentId }),
  })
export const createManualTask = (caseId: number, data: ManualTaskInput) =>
  apiRequest<TaskItem>(`/cases/${caseId}/tasks`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
export const getTasks = (params = '') =>
  apiRequest<{ items: TaskItem[]; page: PageInfo }>(
    `/tasks${params ? `?${params}` : ''}`,
  )
export const updateTask = (id: number, status: TaskStatus) =>
  apiRequest<TaskItem>(`/tasks/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
export const getReviews = (params = '') =>
  apiRequest<{ items: ReviewItem[]; page: PageInfo }>(
    `/reviews${params ? `?${params}` : ''}`,
  )
export const updateReview = (
  id: number,
  status: string,
  resolutionNotes?: string,
) =>
  apiRequest<ReviewItem>(`/reviews/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status, resolution_notes: resolutionNotes ?? null }),
  })
export const getReviewAnalysis = (id: number) =>
  apiRequest<ReviewDetail>(`/reviews/${id}/analysis`)
export const getMessageAnalysis = (id: number) =>
  apiRequest<MessageAnalysis>(`/carrier-messages/${id}/analysis`)
export const processMessage = (id: number) =>
  apiRequest<MessageProcessingResult>(`/carrier-messages/${id}/process`, {
    method: 'POST',
  })
export const applyReviewAnalysis = (
  id: number,
  data: HumanAnalysisInput,
  selectedCaseId?: number,
) =>
  apiRequest<MessageProcessingResult>(
    `/reviews/${id}/apply-analysis${selectedCaseId ? `?selected_case_id=${selectedCaseId}` : ''}`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    },
  )
export const dismissReviewAnalysis = (id: number, resolutionNotes?: string) =>
  apiRequest<MessageProcessingResult>(`/reviews/${id}/dismiss-analysis`, {
    method: 'POST',
    body: JSON.stringify({ resolution_notes: resolutionNotes ?? null }),
  })
export const getGmailConnections = (page = 1) =>
  apiRequest<GmailConnectionsResponse>(
    `/gmail-connections?page=${page}&page_size=5`,
  )
export const startGmailOAuth = (reconnectConnectionId?: number) =>
  apiRequest<{ authorization_url: string }>('/gmail/oauth/start', {
    method: 'POST',
    body: JSON.stringify({
      reconnect_connection_id: reconnectConnectionId ?? null,
    }),
  })
export const syncGmailConnection = (connectionId: number) =>
  apiRequest<GmailSyncResult>(`/gmail-connections/${connectionId}/sync`, {
    method: 'POST',
  })
export const reconcileMessageGmailLabels = (messageId: number) =>
  apiRequest<{ message: string }>(
    `/carrier-messages/${messageId}/reconcile-gmail-labels`,
    { method: 'POST' },
  )
export const disconnectGmailConnection = (connectionId: number) =>
  apiRequest<{ message: string }>(`/gmail-connections/${connectionId}`, {
    method: 'DELETE',
  })
export const getGmailMessages = (connectionId: number, page = 1) =>
  apiRequest<GmailMessageListResponse | GmailMessage[]>(
    `/gmail-connections/${connectionId}/messages?page=${page}&page_size=8`,
  )
export function redirectToOAuth(authorizationUrl: string) {
  window.location.assign(authorizationUrl)
}
export const getAgents = () =>
  apiRequest<{ items: AgentItem[]; page: PageInfo }>(
    '/manager/agents?page=1&page_size=100',
  ).then((response) => response.items)
export const getAgentsPage = (page = 1) =>
  apiRequest<{ items: AgentItem[]; page: PageInfo }>(
    `/manager/agents?page=${page}&page_size=10`,
  )
export const createAgent = (data: {
  full_name: string
  email: string
  initial_password: string
  confirm_initial_password: string
}) =>
  apiRequest<AgentItem>('/manager/agents', {
    method: 'POST',
    body: JSON.stringify(data),
  })
export const setAgentEnabled = (agentId: number, isEnabled: boolean) =>
  apiRequest<AgentItem>(`/manager/agents/${agentId}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_enabled: isEnabled }),
  })
export const removeAgent = (agentId: number) =>
  apiRequest<void>(`/manager/agents/${agentId}`, { method: 'DELETE' })
export const getCarriers = () => apiRequest<CarrierItem[]>('/manager/carriers')
export const getAnalytics = (range: '7d' | '30d' | '90d' | 'all' = '30d') =>
  apiRequest<Analytics>(`/manager/analytics?range=${range}`)
export const getAuditLogs = (params = '') =>
  apiRequest<{ items: AuditLog[]; page: PageInfo }>(
    `/manager/audit-events${params ? `?${params}` : ''}`,
  )
export const getActivity = (params = '') =>
  apiRequest<{ items: AuditLog[]; page: PageInfo }>(
    `/activity${params ? `?${params}` : ''}`,
  )

export const createCarrier = (data: {
  name: string
  code?: string
  notes?: string
  is_enabled: boolean
}) =>
  apiRequest<CarrierItem>('/manager/carriers', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const updateCarrier = (carrier: CarrierItem) =>
  apiRequest<CarrierItem>(`/manager/carriers/${carrier.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      name: carrier.name,
      code: carrier.code,
      notes: carrier.notes,
      is_enabled: carrier.is_enabled,
    }),
  })

export const deleteCarrier = (carrierId: number) =>
  apiRequest<void>(`/manager/carriers/${carrierId}`, { method: 'DELETE' })

export const addCarrierDomain = (carrierId: number, domain: string) =>
  apiRequest<CarrierItem>(`/manager/carriers/${carrierId}/domains`, {
    method: 'POST',
    body: JSON.stringify({ domain, is_enabled: true }),
  })

export const addCarrierSender = (carrierId: number, email: string) =>
  apiRequest<CarrierItem>(`/manager/carriers/${carrierId}/senders`, {
    method: 'POST',
    body: JSON.stringify({ email, is_enabled: true }),
  })

export const setCarrierDomainEnabled = (
  carrierId: number,
  domainId: number,
  isEnabled: boolean,
) =>
  apiRequest<CarrierItem>(
    `/manager/carriers/${carrierId}/domains/${domainId}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ is_enabled: isEnabled }),
    },
  )

export const removeCarrierDomain = (carrierId: number, domainId: number) =>
  apiRequest<CarrierItem>(
    `/manager/carriers/${carrierId}/domains/${domainId}`,
    { method: 'DELETE' },
  )

export const setCarrierSenderEnabled = (
  carrierId: number,
  senderId: number,
  isEnabled: boolean,
) =>
  apiRequest<CarrierItem>(
    `/manager/carriers/${carrierId}/senders/${senderId}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ is_enabled: isEnabled }),
    },
  )

export const removeCarrierSender = (carrierId: number, senderId: number) =>
  apiRequest<CarrierItem>(
    `/manager/carriers/${carrierId}/senders/${senderId}`,
    { method: 'DELETE' },
  )
