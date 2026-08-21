import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import { logout } from '../lib/api'
import { authFixture } from '../test/fixtures'
import { AppShell } from './AppShell'

vi.mock('../app/auth', () => ({
  authQueryKey: ['auth', 'me'],
  useCurrentUser: vi.fn(),
}))
vi.mock('../lib/api', () => ({ logout: vi.fn() }))
const mockedAuth = vi.mocked(useCurrentUser)

afterEach(cleanup)

function renderShell(role: 'AGENT' | 'MANAGER') {
  mockedAuth.mockReturnValue({ data: authFixture(role) } as ReturnType<
    typeof useCurrentUser
  >)
  const client = new QueryClient()
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route path="dashboard" element={<p>Workspace content</p>} />
          </Route>
          <Route path="login" element={<p>Login screen</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...rendered, client }
}

describe('AppShell navigation', () => {
  it('keeps manager navigation out of the Agent experience', () => {
    renderShell('AGENT')
    expect(screen.queryByText('System Logs')).not.toBeInTheDocument()
    expect(screen.getAllByText('My Tasks').length).toBeGreaterThan(0)
    expect(screen.getAllByText('My Activity').length).toBeGreaterThan(0)
  })

  it('shows agency management navigation to Managers', () => {
    renderShell('MANAGER')
    expect(screen.getAllByText('System Logs').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Carriers').length).toBeGreaterThan(0)
    expect(screen.queryByText('My Activity')).not.toBeInTheDocument()
  })

  it('clears all user-scoped cache before completing sign out', async () => {
    vi.mocked(logout).mockResolvedValue()
    const { client } = renderShell('AGENT')
    client.setQueryData(['cases'], [{ client_name: 'Private client' }])
    client.setQueryData(['tasks'], [{ title: 'Private task' }])

    fireEvent.click(screen.getAllByRole('button', { name: 'Sign out' })[0])

    expect(await screen.findByText('Login screen')).toBeInTheDocument()
    await waitFor(() => expect(client.getQueryCache().getAll()).toHaveLength(0))
  })
})
