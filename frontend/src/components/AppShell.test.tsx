import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import { authFixture } from '../test/fixtures'
import { AppShell } from './AppShell'

vi.mock('../app/auth', () => ({
  authQueryKey: ['auth', 'me'],
  useCurrentUser: vi.fn(),
}))
vi.mock('../lib/api', () => ({ logout: vi.fn() }))
const mockedAuth = vi.mocked(useCurrentUser)

function renderShell(role: 'AGENT' | 'MANAGER') {
  mockedAuth.mockReturnValue({ data: authFixture(role) } as ReturnType<
    typeof useCurrentUser
  >)
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route path="dashboard" element={<p>Workspace content</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppShell navigation', () => {
  it('keeps manager navigation out of the Agent experience', () => {
    renderShell('AGENT')
    expect(screen.queryByText('System Logs')).not.toBeInTheDocument()
    expect(screen.getAllByText('My Tasks').length).toBeGreaterThan(0)
  })

  it('shows agency management navigation to Managers', () => {
    renderShell('MANAGER')
    expect(screen.getAllByText('System Logs').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Carriers').length).toBeGreaterThan(0)
  })
})
