import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import { ApiError, login } from '../lib/api'
import { authFixture } from '../test/fixtures'
import { LoginPage } from './LoginPage'

vi.mock('../app/auth', () => ({
  authQueryKey: ['auth', 'me'],
  useCurrentUser: vi.fn(),
}))
vi.mock('../lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../lib/api')>()
  return { ...original, login: vi.fn() }
})

const mockedAuth = vi.mocked(useCurrentUser)
const mockedLogin = vi.mocked(login)

function renderLogin() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<p>Dashboard loaded</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    mockedAuth.mockReturnValue({ isSuccess: false } as ReturnType<
      typeof useCurrentUser
    >)
    mockedLogin.mockReset()
  })

  it('navigates to the protected workspace after successful login', async () => {
    mockedLogin.mockResolvedValue(authFixture())
    renderLogin()
    fireEvent.change(screen.getByLabelText('Email address'), {
      target: { value: 'agent.one@demo.local' },
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'development-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Dashboard loaded')).toBeInTheDocument()
  })

  it('shows a generic invalid-credentials error', async () => {
    mockedLogin.mockRejectedValue(
      new ApiError('Invalid email or password', 401),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('Email address'), {
      target: { value: 'missing@demo.local' },
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'incorrect-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Invalid email or password',
    )
  })
})
