import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Pagination, PriorityBadge, StatusBadge } from './ui'

function submit(input: HTMLElement) {
  fireEvent.submit(input.closest('form')!)
}

describe('Pagination', () => {
  it('is hidden when there is only one page', () => {
    render(<Pagination page={1} pages={1} onPageChange={vi.fn()} />)

    expect(screen.queryByLabelText('Pagination')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Go to page')).not.toBeInTheDocument()
  })

  it('navigates to a valid typed page only when the form is submitted', () => {
    const onPageChange = vi.fn()
    render(<Pagination page={2} pages={25} onPageChange={onPageChange} />)
    const input = screen.getByLabelText('Go to page')

    expect(input).toHaveValue(2)
    fireEvent.change(input, { target: { value: '1' } })
    expect(onPageChange).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: '12' } })
    expect(onPageChange).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Go' })).not.toBeInTheDocument()
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onPageChange).toHaveBeenCalledOnce()
    expect(onPageChange).toHaveBeenCalledWith(12)
  })

  it('rejects pages below and above the available range without navigating', () => {
    const onPageChange = vi.fn()
    render(<Pagination page={2} pages={8} onPageChange={onPageChange} />)
    const input = screen.getByLabelText('Go to page')

    fireEvent.change(input, { target: { value: '0' } })
    submit(input)
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Page number must be at least 1.',
    )
    expect(onPageChange).not.toHaveBeenCalled()

    fireEvent.change(input, { target: { value: '9' } })
    submit(input)
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Page 9 does not exist. There are 8 pages.',
    )
    expect(onPageChange).not.toHaveBeenCalled()
  })

  it('rejects blank, non-numeric, and decimal values', () => {
    const onPageChange = vi.fn()
    render(<Pagination page={2} pages={8} onPageChange={onPageChange} />)
    const input = screen.getByLabelText('Go to page')

    for (const value of ['', 'invalid', '1.5']) {
      fireEvent.change(input, { target: { value } })
      submit(input)
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Enter a valid whole page number.',
      )
    }
    expect(onPageChange).not.toHaveBeenCalled()
  })

  it('keeps Previous and Next working and clears errors after valid navigation', () => {
    const onPageChange = vi.fn()
    render(<Pagination page={2} pages={4} onPageChange={onPageChange} />)
    const input = screen.getByLabelText('Go to page')

    fireEvent.change(input, { target: { value: '8' } })
    submit(input)
    expect(screen.getByRole('alert')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(onPageChange).toHaveBeenLastCalledWith(1)
    expect(input).toHaveValue(1)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(onPageChange).toHaveBeenLastCalledWith(3)
    expect(input).toHaveValue(3)
  })

  it('synchronizes the input when the current page changes externally', () => {
    const onPageChange = vi.fn()
    const { rerender } = render(
      <Pagination page={2} pages={8} onPageChange={onPageChange} />,
    )

    rerender(<Pagination page={6} pages={8} onPageChange={onPageChange} />)

    expect(screen.getByLabelText('Go to page')).toHaveValue(6)
  })
})

describe('StatusBadge', () => {
  it('uses semantic tones for operational states', () => {
    const { rerender } = render(<StatusBadge status="CONNECTED" />)
    expect(screen.getByText('CONNECTED')).toHaveClass('text-emerald-800')

    rerender(<StatusBadge status="NEEDS_REAUTH" />)
    expect(screen.getByText('NEEDS REAUTH')).toHaveClass('text-amber-900')

    rerender(<StatusBadge status="ERROR" />)
    expect(screen.getByText('ERROR')).toHaveClass('text-red-800')

    rerender(<StatusBadge status="DISMISSED" />)
    expect(screen.getByText('DISMISSED')).toHaveClass('text-slate-700')
  })
})

describe('PriorityBadge', () => {
  it('uses stronger priority treatments without changing soft status tones', () => {
    const { rerender } = render(<PriorityBadge priority="LOW" />)
    expect(screen.getByText('LOW')).toHaveClass(
      'bg-slate-200',
      'text-slate-900',
    )

    rerender(<PriorityBadge priority="NORMAL" />)
    expect(screen.getByText('NORMAL')).toHaveClass('bg-slate-700', 'text-white')

    rerender(<PriorityBadge priority="HIGH" />)
    expect(screen.getByText('HIGH')).toHaveClass('bg-amber-800', 'text-white')

    rerender(<PriorityBadge priority="URGENT" />)
    expect(screen.getByText('URGENT')).toHaveClass('bg-red-800', 'text-white')

    rerender(<StatusBadge status="PENDING" />)
    expect(screen.getByText('PENDING')).toHaveClass(
      'bg-amber-50',
      'text-amber-900',
    )
  })
})
