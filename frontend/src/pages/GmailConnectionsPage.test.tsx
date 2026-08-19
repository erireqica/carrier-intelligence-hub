import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { getGmailConnections } from '../lib/api'
import { GmailConnectionsPage } from './GmailConnectionsPage'

vi.mock('../lib/api', () => ({ getGmailConnections: vi.fn() }))

describe('GmailConnectionsPage', () => {
  it('honestly explains the unconfigured OAuth state', async () => {
    vi.mocked(getGmailConnections).mockResolvedValue([])
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <GmailConnectionsPage />
      </QueryClientProvider>,
    )
    expect(
      await screen.findByText('No Gmail inbox connected'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', {
        name: 'Connect Gmail — integration not configured',
      }),
    ).toBeDisabled()
  })
})
