import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  createCarrier,
  deleteCarrier,
  getCarriers,
  removeCarrierDomain,
  removeCarrierSender,
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
    deleteCarrier: vi.fn(),
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

  it('confirms destructive whitelist removals and respects cancellation', async () => {
    const configured = {
      ...carrier,
      domains: [{ id: 11, domain: 'americo.com', is_enabled: true }],
      senders: [
        { id: 12, email: 'specific.sender@gmail.com', is_enabled: true },
      ],
    }
    vi.mocked(getCarriers).mockResolvedValue([configured])
    vi.mocked(removeCarrierDomain).mockResolvedValue(configured)
    vi.mocked(removeCarrierSender).mockResolvedValue(configured)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderCarriers()

    const removeButtons = await screen.findAllByRole('button', {
      name: 'Remove',
    })
    fireEvent.click(removeButtons[0])
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('americo.com'))
    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining('Existing cases'),
    )
    expect(removeCarrierDomain).not.toHaveBeenCalled()

    confirm.mockReturnValue(true)
    fireEvent.click(removeButtons[0])
    await vi.waitFor(() =>
      expect(removeCarrierDomain).toHaveBeenCalledWith(1, 11),
    )
    fireEvent.click(removeButtons[1])
    await vi.waitFor(() =>
      expect(removeCarrierSender).toHaveBeenCalledWith(1, 12),
    )
  })

  it('uses semantic carrier actions and paginates domains five at a time', async () => {
    const configured = {
      ...carrier,
      domains: Array.from({ length: 6 }, (_, index) => ({
        id: index + 1,
        domain: `domain-${index + 1}.example`,
        is_enabled: true,
      })),
    }
    vi.mocked(getCarriers).mockResolvedValue([configured])
    vi.mocked(deleteCarrier).mockResolvedValue(undefined)
    renderCarriers()
    const disable = (
      await screen.findAllByRole('button', { name: 'Disable' })
    ).find((button) => button.classList.contains('bg-red-700'))
    expect(disable).toBeDefined()
    expect(disable!).toHaveClass('bg-red-700')
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
    expect(screen.queryByText('domain-6.example')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('domain-6.example')).toBeInTheDocument()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const deleteButton = screen.getByRole('button', { name: 'Delete' })
    expect(deleteButton).toHaveClass(
      'bg-white',
      'border-red-700',
      'text-red-700',
    )
    expect(deleteButton).not.toHaveClass('bg-red-700')
    fireEvent.click(deleteButton)
    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining('Permanently delete Americo'),
    )
    await vi.waitFor(() => expect(deleteCarrier).toHaveBeenCalledWith(1))
  })

  it('renders carrier Enable as a green success action', async () => {
    vi.mocked(getCarriers).mockResolvedValue([
      { ...carrier, is_enabled: false },
    ])
    renderCarriers()
    expect(await screen.findByRole('button', { name: 'Enable' })).toHaveClass(
      'bg-emerald-700',
      'text-white',
    )
  })
})
