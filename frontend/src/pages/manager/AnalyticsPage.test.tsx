import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { getAnalytics } from '../../lib/api'
import { AnalyticsPage } from './AnalyticsPage'

vi.mock('../../lib/api', () => ({ getAnalytics: vi.fn() }))

describe('AnalyticsPage', () => {
  it('renders historical pipeline performance without operational workload duplicates', async () => {
    vi.mocked(getAnalytics).mockResolvedValue({
      range: '30d',
      start_date: '2026-07-24',
      end_date: '2026-08-22',
      carrier_messages: 4,
      automation_rate: 50,
      review_rate: 25,
      failure_rate: 25,
      average_processing_seconds: 12.5,
      pdf_extraction_success_rate: 80,
      outcomes: [{ label: 'Automatic', count: 2, percentage: 50 }],
      volume_trend: [{ label: '2026-08-22', count: 4 }],
      classifications: [{ label: 'Policy Issued', count: 2, percentage: 100 }],
      carrier_performance: [
        {
          carrier_id: 1,
          carrier_name: 'Americo',
          messages: 4,
          automation_rate: 50,
          review_rate: 25,
          failure_rate: 25,
        },
      ],
      attachments: {
        pdfs_processed: 5,
        extracted_successfully: 4,
        needs_ocr: 1,
        failed_or_unsupported: 0,
      },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <AnalyticsPage />
      </QueryClientProvider>,
    )

    expect(
      await screen.findByText('Carrier AI performance'),
    ).toBeInTheDocument()
    expect(screen.getByText('Successful automation')).toBeInTheDocument()
    expect(screen.getByLabelText('auto-processed: 50')).toBeInTheDocument()
    expect(
      screen.getByText('Of successfully processed messages'),
    ).toBeInTheDocument()
    expect(screen.getByText('12.5s')).toBeInTheDocument()
    expect(
      screen.getByText('Analysis start to processed · normal completed cycles'),
    ).toBeInTheDocument()
    expect(screen.getByText('Auto-processed')).toBeInTheDocument()
    expect(screen.queryByText('Automated')).not.toBeInTheDocument()
    expect(screen.getByText('Message classifications')).toBeInTheDocument()
    expect(screen.queryByText('Open workload by agent')).not.toBeInTheDocument()
    expect(screen.queryByText('Open tasks')).not.toBeInTheDocument()
  })

  it('keeps every 30-day data bucket while rendering only concise spaced date ticks', async () => {
    const volumeTrend = Array.from({ length: 30 }, (_, index) => ({
      label: `2026-08-${String(index + 1).padStart(2, '0')}`,
      count: index + 1,
    }))
    vi.mocked(getAnalytics).mockResolvedValue({
      range: '30d',
      start_date: '2026-08-01',
      end_date: '2026-08-30',
      carrier_messages: 465,
      automation_rate: 100,
      review_rate: 0,
      failure_rate: 0,
      average_processing_seconds: null,
      pdf_extraction_success_rate: null,
      outcomes: [],
      volume_trend: volumeTrend,
      classifications: [],
      carrier_performance: [],
      attachments: {
        pdfs_processed: 0,
        extracted_successfully: 0,
        needs_ocr: 0,
        failed_or_unsupported: 0,
      },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <AnalyticsPage />
      </QueryClientProvider>,
    )

    expect(
      await screen.findByText('Carrier AI performance'),
    ).toBeInTheDocument()
    expect(screen.getByText('No timing data')).toBeInTheDocument()
    const ticks = screen.getAllByTestId('volume-axis-label')
    expect(ticks).toHaveLength(7)
    expect(ticks.map((tick) => tick.textContent)).toEqual([
      'Aug 1',
      'Aug 6',
      'Aug 11',
      'Aug 16',
      'Aug 21',
      'Aug 26',
      'Aug 30',
    ])
    expect(ticks.every((tick) => !tick.textContent?.includes('2026'))).toBe(
      true,
    )
    expect(screen.getAllByLabelText(/carrier messages$/)).toHaveLength(30)
    expect(
      screen.getByLabelText('2026-08-30: 30 carrier messages'),
    ).toBeInTheDocument()
  })
})
