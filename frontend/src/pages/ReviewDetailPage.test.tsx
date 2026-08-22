import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  applyReviewAnalysis,
  dismissReviewAnalysis,
  getMe,
  getReviewAnalysis,
} from '../lib/api'
import { authFixture } from '../test/fixtures'
import { ReviewDetailPage } from './ReviewDetailPage'

vi.mock('../lib/api', () => ({
  applyReviewAnalysis: vi.fn(),
  dismissReviewAnalysis: vi.fn(),
  getMe: vi.fn(),
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

const noProposalReview = {
  id: 8,
  message_id: 13,
  case_id: null,
  client_name: null,
  policy_number: null,
  carrier_name: 'Americo',
  message_subject: 'Unreadable attachment',
  reason_code: 'ATTACHMENT_NEEDS_OCR',
  reason: 'A PDF attachment could not be read safely.',
  status: 'OPEN' as const,
  resolution_notes: null,
  assigned_reviewer: null,
  created_at: '2026-08-20T12:00:00Z',
  resolved_at: null,
  analysis_confidence: null,
  analysis: {
    message_id: 13,
    carrier_name: 'Americo',
    processing_status: 'NEEDS_REVIEW' as const,
    case_id: null,
    review_id: 8,
    model_name: null,
    schema_version: null,
    prompt_version: null,
    overall_confidence: null,
    validation_flags: ['ATTACHMENT_NEEDS_OCR'],
    proposed_result: null,
    final_result: null,
    source_content: 'The attached document requires human inspection.',
    attachments: [
      {
        id: 4,
        filename: 'scanned-notice.pdf',
        mime_type: 'application/pdf',
        size_bytes: 42,
        processing_status: 'NEEDS_OCR',
        page_count: 1,
        extraction_error_code: 'PDF_NO_TEXT',
        extracted_text_preview: null,
      },
    ],
  },
}

describe('ReviewDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getMe).mockResolvedValue(authFixture('AGENT'))
  })

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
      issues: [
        {
          code: 'INTERPRETATION_AMBIGUITY_1',
          category: 'INTERPRETATION_AMBIGUITY',
          title: 'More than one interpretation is plausible',
          message:
            'The deadline may apply to either requirement. Choose the interpretation best supported by the available communication.',
          field_name: 'requirement_association',
          human_resolvable: true,
          values: [
            {
              source_id: 'email',
              source_label: 'Email body',
              value: 'The deadline applies only to the authorization.',
              excerpt:
                'Please return the signed authorization within 10 business days.',
            },
            {
              source_id: 'attachment:4',
              source_label: 'PDF attachment 4',
              value: 'The deadline applies to every outstanding requirement.',
              excerpt:
                'Please return the signed authorization within 10 business days.',
            },
          ],
        },
      ],
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

    expect(
      await screen.findByText('Check against the carrier message'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('More than one interpretation is plausible'),
    ).toBeInTheDocument()
    expect(screen.getByText('PDF attachment 4')).toBeInTheDocument()
    expect(
      screen.getByText(
        'The deadline applies to every outstanding requirement.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('“Policy REVIEW-100”')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Client name'), {
      target: { value: 'Corrected Client' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm & apply' }))

    await waitFor(() =>
      expect(applyReviewAnalysis).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ client_name: 'Corrected Client' }),
      ),
    )
    expect(await screen.findByText('Case opened')).toBeInTheDocument()
  })

  it('keeps source context visible and dismisses a review without a proposal', async () => {
    vi.mocked(getReviewAnalysis).mockResolvedValue(noProposalReview)
    vi.mocked(dismissReviewAnalysis).mockResolvedValue({
      message_id: 13,
      processing_status: 'IGNORED',
      case_id: null,
      review_id: null,
      tasks_created: 0,
      attachments_extracted: 0,
      analysis_confidence: null,
      validation_flags: [],
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/reviews/8']}>
          <Routes>
            <Route path="/reviews/:reviewId" element={<ReviewDetailPage />} />
            <Route path="/reviews" element={<p>Review queue opened</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(
      await screen.findByText('No structured proposal'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('The attached document requires human inspection.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/scanned-notice\.pdf/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Confirm & apply' }),
    ).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Dismissal notes'), {
      target: { value: 'Not an actionable carrier notice.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss review' }))

    await waitFor(() =>
      expect(dismissReviewAnalysis).toHaveBeenCalledWith(
        8,
        'Not an actionable carrier notice.',
      ),
    )
    expect(await screen.findByText('Review queue opened')).toBeInTheDocument()
    expect(applyReviewAnalysis).not.toHaveBeenCalled()
  })

  it('renders a finalized no-proposal review as read-only', async () => {
    vi.mocked(getReviewAnalysis).mockResolvedValue({
      ...noProposalReview,
      status: 'DISMISSED',
      resolution_notes: 'Confirmed as non-operational.',
      resolved_at: '2026-08-20T13:00:00Z',
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/reviews/8']}>
          <Routes>
            <Route path="/reviews/:reviewId" element={<ReviewDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Finalized review')).toBeInTheDocument()
    expect(
      screen.getByText('Confirmed as non-operational.'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Dismiss review' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Dismissal notes')).not.toBeInTheDocument()
  })

  it('keeps manager review detail explicitly read-only', async () => {
    vi.mocked(getMe).mockResolvedValue(authFixture('MANAGER'))
    vi.mocked(getReviewAnalysis).mockResolvedValue({
      ...noProposalReview,
      id: 9,
      message_id: 14,
      analysis: {
        ...noProposalReview.analysis,
        message_id: 14,
        review_id: 9,
        proposed_result: proposal,
      },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/reviews/9']}>
          <Routes>
            <Route path="/reviews/:reviewId" element={<ReviewDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText(/Manager view/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Confirm & apply' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Not actionable' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Client name')).not.toBeInTheDocument()
    expect(screen.getByText('Confirmed analysis')).toBeInTheDocument()
    expect(screen.getAllByText('Review Client').length).toBeGreaterThan(0)
  })

  it('keeps an unresolved ownership conflict read-only for the Agent', async () => {
    vi.mocked(getReviewAnalysis).mockResolvedValue({
      ...noProposalReview,
      id: 10,
      message_id: 15,
      case_id: 44,
      reason_code: 'CASE_OWNER_CONFLICT',
      reason: 'A manager must confirm operational ownership.',
      analysis: {
        ...noProposalReview.analysis,
        message_id: 15,
        case_id: 44,
        review_id: 10,
        proposed_result: proposal,
      },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/reviews/10']}>
          <Routes>
            <Route path="/reviews/:reviewId" element={<ReviewDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(
      await screen.findByText(/Case ownership must be resolved before/),
    ).toBeInTheDocument()
    const view = within(rendered.container)
    expect(view.getByText('Confirmed analysis')).toBeInTheDocument()
    expect(view.queryByLabelText('Client name')).not.toBeInTheDocument()
    expect(
      view.queryByRole('button', { name: 'Confirm & apply' }),
    ).not.toBeInTheDocument()
    expect(applyReviewAnalysis).not.toHaveBeenCalled()
  })
})
