import type { GmailMessage, GmailMessageListResponse } from './types'

export function shouldPollRecentMessages(
  data: GmailMessageListResponse | GmailMessage[] | undefined,
) {
  if (!data) return false
  const items = Array.isArray(data) ? data : data.items
  return items.some(
    (message) =>
      message.processing_status === 'RECEIVED' ||
      message.processing_status === 'PROCESSING' ||
      Boolean(message.processing_next_retry_at),
  )
}
