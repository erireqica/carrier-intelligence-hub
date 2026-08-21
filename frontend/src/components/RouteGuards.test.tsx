import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import { authFixture } from '../test/fixtures'
import { ApiError } from '../lib/api'
import { AgentRoute, ManagerRoute, ProtectedRoute } from './RouteGuards'

vi.mock('../app/auth', () => ({ useCurrentUser: vi.fn() }))
const mockedAuth = vi.mocked(useCurrentUser)

function renderGuard(role: 'AGENT' | 'MANAGER') {
  mockedAuth.mockReturnValue({ data: authFixture(role) } as ReturnType<
    typeof useCurrentUser
  >)
  render(
    <MemoryRouter initialEntries={['/manager/agents']}>
      <Routes>
        <Route path="/dashboard" element={<p>Agent dashboard</p>} />
        <Route element={<ManagerRoute />}>
          <Route path="/manager/agents" element={<p>Manager agents</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('ManagerRoute', () => {
  it('redirects an Agent away from a manager URL', () => {
    renderGuard('AGENT')
    expect(screen.getByText('Agent dashboard')).toBeInTheDocument()
    expect(screen.queryByText('Manager agents')).not.toBeInTheDocument()
  })

  it('allows a Manager to open a manager URL directly', () => {
    renderGuard('MANAGER')
    expect(screen.getByText('Manager agents')).toBeInTheDocument()
  })
})

describe('ProtectedRoute', () => {
  it('redirects an unauthenticated visitor to login', () => {
    mockedAuth.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError('Authentication required', 401),
    } as ReturnType<typeof useCurrentUser>)
    render(
      <MemoryRouter initialEntries={['/cases']}>
        <Routes>
          <Route path="/login" element={<p>Login screen</p>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/cases" element={<p>Protected cases</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText('Login screen')).toBeInTheDocument()
    expect(screen.queryByText('Protected cases')).not.toBeInTheDocument()
  })
})

describe('AgentRoute', () => {
  it('redirects a Manager away from the Agent-only activity URL', () => {
    mockedAuth.mockReturnValue({ data: authFixture('MANAGER') } as ReturnType<
      typeof useCurrentUser
    >)
    render(
      <MemoryRouter initialEntries={['/activity']}>
        <Routes>
          <Route path="/dashboard" element={<p>Manager dashboard</p>} />
          <Route element={<AgentRoute />}>
            <Route path="/activity" element={<p>Agent activity</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText('Manager dashboard')).toBeInTheDocument()
    expect(screen.queryByText('Agent activity')).not.toBeInTheDocument()
  })
})
