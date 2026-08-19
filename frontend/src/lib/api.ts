import type {
  AgentItem,
  Analytics,
  AuditLog,
  AuthResponse,
  CarrierItem,
  CaseDetail,
  CaseItem,
  Dashboard,
  PageInfo,
  ReviewItem,
  TaskItem,
  TaskStatus,
} from './types'

const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1'
export const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL
).replace(/\/$/, '')

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

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = options.method?.toUpperCase() ?? 'GET'
  const unsafe = !['GET', 'HEAD', 'OPTIONS'].includes(method)
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body) headers.set('Content-Type', 'application/json')
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
      const body = (await response.json()) as { detail?: string }
      if (body.detail) message = body.detail
    } catch {
      // The safe generic message is used for non-JSON errors.
    }
    if (
      response.status === 401 &&
      path !== '/auth/login' &&
      window.location.pathname !== '/login'
    ) {
      setCsrfToken(null)
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

export const getDashboard = () => apiRequest<Dashboard>('/dashboard')
export const getCases = (params = '') =>
  apiRequest<{ items: CaseItem[]; page: PageInfo }>(
    `/cases${params ? `?${params}` : ''}`,
  )
export const getCase = (id: string) => apiRequest<CaseDetail>(`/cases/${id}`)
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
export const getGmailConnections = () =>
  apiRequest<unknown[]>('/gmail-connections')
export const getAgents = () => apiRequest<AgentItem[]>('/manager/agents')
export const getCarriers = () => apiRequest<CarrierItem[]>('/manager/carriers')
export const getAnalytics = () => apiRequest<Analytics>('/manager/analytics')
export const getAuditLogs = (params = '') =>
  apiRequest<{ items: AuditLog[]; page: PageInfo }>(
    `/manager/audit-events${params ? `?${params}` : ''}`,
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
