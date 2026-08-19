import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  createCarrier,
  getCarriers,
  updateCarrier,
} from '../../lib/api'
import { CarriersPage } from './CarriersPage'

vi.mock('../../lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/api')>()
  return {
    ...original,
    addCarrierDomain: vi.fn(),
    addCarrierSender: vi.fn(),
    createCarrier: vi.fn(),
    getCarriers: vi.fn(),
    removeCarrierDomain: vi.fn(),
    removeCarrierSender: vi.fn(),
    setCarrierDomainEnabled: vi.fn(),
    setCarrierSenderEnabled: vi.fn(),
    updateCarrier: vi.fn(),
  }
})

const carrier = {
  id: 1,
  name: 'Americo',
  code: 'AMR',
  notes: 'Seeded carrier',
  is_enabled: true,
  domains: [],
  senders: [],
}

function renderCarriers() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <CarriersPage />
    </QueryClientProvider>,
  )
}

describe('CarriersPage mutation errors', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getCarriers).mockResolvedValue([carrier])
  })

  it('shows a safe carrier update error instead of failing silently', async () => {
    vi.mocked(updateCarrier).mockRejectedValue(
      new ApiError('Carrier update could not be completed', 409),
    )
    renderCarriers()

    fireEvent.click(await screen.findByRole('button', { name: 'Disable' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Carrier update could not be completed',
    )
  })

  it('shows a duplicate create error beside the create form', async () => {
    vi.mocked(createCarrier).mockRejectedValue(
      new ApiError('A carrier with this name already exists', 409),
    )
    renderCarriers()

    fireEvent.click(await screen.findByRole('button', { name: 'Add carrier' }))
    fireEvent.change(screen.getByLabelText('Carrier name'), {
      target: { value: 'Americo' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create carrier' }))
    expect(
      await screen.findByText('A carrier with this name already exists'),
    ).toHaveAttribute('role', 'alert')
  })
})
