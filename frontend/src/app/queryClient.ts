import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
})

export async function clearSessionState(client: QueryClient = queryClient) {
  await client.cancelQueries()
  client.clear()
}
