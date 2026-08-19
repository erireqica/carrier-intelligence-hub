import { useQuery } from '@tanstack/react-query'

import { getMe } from '../lib/api'

export const authQueryKey = ['auth', 'me'] as const

export function useCurrentUser() {
  return useQuery({
    queryKey: authQueryKey,
    queryFn: getMe,
    retry: false,
    staleTime: 5 * 60_000,
  })
}
