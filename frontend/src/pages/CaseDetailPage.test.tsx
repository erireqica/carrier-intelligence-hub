import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { getCase, updateTask } from '../lib/api'
import { CaseDetailPage } from './CaseDetailPage'

vi.mock('../lib/api', () => ({ getCase: vi.fn(), updateTask: vi.fn() }))

describe('CaseDetailPage carrier messages', () => {
  it('renders truthful lifecycle text when semantic analysis is unavailable', async () => {
    vi.mocked(getCase).mockResolvedValue({
      id: 1,
      client_name: 'Synthetic Client',
      policy_number: null,
      policy_status: 'UNKNOWN',
      priority: 'NORMAL',
      summary: 'Source message received.',
      deadline: '2026-08-28',
      updated_at: '2026-08-20T10:00:00Z',
      carrier: { id: 1, name: 'Americo', code: 'AMR' },
      assigned_agent: null,
      needs_review: false,
      premium_amount: null,
      currency: null,
      effective_date: null,
      messages: [
        {
          id: 10,
          sender: 'source@example.test',
          subject: 'New carrier message',
          received_at: '2026-08-20T10:00:00Z',
          classification: null,
          summary: null,
          priority: null,
          processing_status: 'PROCESSING',
          cleaned_content: 'Submit the form by August 28, 2026.',
          original_deadline_text: 'by August 28, 2026',
          analysis_confidence: null,
          validation_flags: [],
          review_id: null,
        },
      ],
      attachments: [],
      tasks: [
        {
          id: 5,
          case_id: 1,
          client_name: 'Synthetic Client',
          policy_number: null,
          title: 'Submit authorization',
          description: 'Send the signed form.',
          priority: 'HIGH',
          due_at: '2026-08-28',
          status: 'OPEN',
          completed_at: null,
          assigned_agent: {
            id: 2,
            full_name: 'Elena Torres',
            email: 'agent.one@demo.local',
          },
        },
      ],
      evidence: [],
      activity: [],
    })
    vi.mocked(updateTask).mockRejectedValue(new Error('Not used'))
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/cases/1']}>
          <Routes>
            <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('New carrier message')).toBeInTheDocument()
    expect(screen.getAllByText('Processing').length).toBeGreaterThan(0)
    expect(
      screen.getByText('Semantic analysis is currently in progress.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Aug 28, 2026')).toBeInTheDocument()
    expect(screen.getByText('Due Aug 28, 2026')).toBeInTheDocument()
    expect(
      screen.getByText('Submit the form by August 28, 2026.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('OTHER')).not.toBeInTheDocument()
  })
})
