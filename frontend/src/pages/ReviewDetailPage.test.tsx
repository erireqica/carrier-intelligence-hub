import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import {
  applyReviewAnalysis,
  dismissReviewAnalysis,
  getReviewAnalysis,
} from '../lib/api'
import { ReviewDetailPage } from './ReviewDetailPage'

vi.mock('../lib/api', () => ({
  applyReviewAnalysis: vi.fn(),
  dismissReviewAnalysis: vi.fn(),
  getReviewAnalysis: vi.fn(),
}))

const proposal = {
  classification: 'PENDING_REQUIREMENTS' as const,
  summary: 'Authorization is required.',
  priority: 'HIGH' as const,
  client_name: 'Review Client',
  policy_number: 'REVIEW-100',
  policy_status: 'PENDING' as const,
  premium_amount: null,
  currency: null,
  effective_date: null,
  deadline: {
    raw_text: 'within 2 days',
    explicit_date: null,
    relative_count: 2,
    relative_unit: 'BUSINESS_DAYS' as const,
  },
  requirements: ['signed authorization'],
  action_items: [
    {
      title: 'Obtain authorization',
      description: 'Contact the client.',
      priority: 'HIGH' as const,
      explicit_due_date: null,
      due_text: 'within 2 days',
    },
  ],
  evidence: [
    {
      field_name: 'policy_number',
      source_id: 'email',
      excerpt: 'Policy REVIEW-100',
    },
  ],
  overall_confidence: 0.62,
  uncertainties: ['Client name formatting'],
}

describe('ReviewDetailPage', () => {
  it('shows grounded proposal fields and submits human corrections', async () => {
    vi.mocked(getReviewAnalysis).mockResolvedValue({
      id: 7,
      message_id: 12,
      case_id: null,
      client_name: 'Review Client',
      policy_number: 'REVIEW-100',
      carrier_name: 'Americo',
      message_subject: 'Pending requirements',
      reason_code: 'LOW_CONFIDENCE',
      reason: 'Confidence is below the automatic threshold.',
      status: 'OPEN',
      resolution_notes: null,
      assigned_reviewer: null,
      created_at: '2026-08-20T12:00:00Z',
      resolved_at: null,
      analysis_confidence: 0.62,
      analysis: {
        message_id: 12,
        carrier_name: 'Americo',
        processing_status: 'NEEDS_REVIEW',
        case_id: null,
        review_id: 7,
        model_name: 'synthetic-model',
        schema_version: '1',
        prompt_version: 'stage4-v1',
        overall_confidence: 0.62,
        validation_flags: ['LOW_CONFIDENCE'],
        proposed_result: proposal,
        final_result: null,
        source_content: 'Client Review Client\nPolicy REVIEW-100',
        attachments: [],
      },
    })
    vi.mocked(applyReviewAnalysis).mockResolvedValue({
      message_id: 12,
      processing_status: 'PROCESSED',
      case_id: 44,
      review_id: null,
      tasks_created: 1,
      attachments_extracted: 0,
      analysis_confidence: 0.62,
      validation_flags: [],
    })
    vi.mocked(dismissReviewAnalysis).mockRejectedValue(new Error('Not used'))
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/reviews/7']}>
          <Routes>
            <Route path="/reviews/:reviewId" element={<ReviewDetailPage />} />
            <Route path="/cases/:caseId" element={<p>Case opened</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Source and evidence')).toBeInTheDocument()
    expect(screen.getByText('“Policy REVIEW-100”')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Client name'), {
      target: { value: 'Corrected Client' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Approve & Apply' }))

    await waitFor(() =>
      expect(applyReviewAnalysis).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ client_name: 'Corrected Client' }),
      ),
    )
    expect(await screen.findByText('Case opened')).toBeInTheDocument()
  })
})
