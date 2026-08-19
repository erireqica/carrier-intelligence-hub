import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHealth } from '../lib/api'
import { FoundationPage } from './FoundationPage'

vi.mock('../lib/api', () => ({
  getHealth: vi.fn(),
}))

const mockedGetHealth = vi.mocked(getHealth)

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={client}>
      <FoundationPage />
    </QueryClientProvider>,
  )
}

describe('FoundationPage', () => {
  beforeEach(() => {
    mockedGetHealth.mockReset()
  })

  it('shows that the backend is operational after a successful health check', async () => {
    mockedGetHealth.mockResolvedValue({
      status: 'ok',
      service: 'carrier-intelligence-api',
    })

    renderPage()

    expect(
      screen.getByRole('heading', { name: 'Carrier Intelligence Hub' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByText('Connected to carrier-intelligence-api.'),
    ).toBeInTheDocument()
  })

  it('explains how to recover when the backend is unavailable', async () => {
    mockedGetHealth.mockRejectedValue(new Error('offline'))

    renderPage()

    expect(
      await screen.findByText(
        'Start the backend service on port 8000, then refresh this page.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
  })
})
