const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1'

export const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL
).replace(/\/$/, '')
