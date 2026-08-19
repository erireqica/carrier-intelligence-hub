const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1'

export const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL
).replace(/\/$/, '')

export type HealthResponse = {
  status: 'ok'
  service: string
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== 'object' || value === null) {
    return false
  }

  const candidate = value as Record<string, unknown>
  return candidate.status === 'ok' && typeof candidate.service === 'string'
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  let response: Response

  try {
    response = await fetch(`${apiBaseUrl}/health`, {
      headers: { Accept: 'application/json' },
      signal,
    })
  } catch {
    throw new ApiError('The backend API could not be reached.')
  }

  if (!response.ok) {
    throw new ApiError('The backend API returned an error.', response.status)
  }

  const body: unknown = await response.json()
  if (!isHealthResponse(body)) {
    throw new ApiError('The backend API returned an unexpected response.')
  }

  return body
}
