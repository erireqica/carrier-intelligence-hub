import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

afterEach(cleanup)

function renderLogin() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<p>Dashboard loaded</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...rendered, client }
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

  it('shows the safe disabled-account message returned for valid credentials', async () => {
    mockedLogin.mockRejectedValue(
      new ApiError(
        'This account has been disabled. Contact your manager.',
        401,
      ),
    )
    renderLogin()
    fireEvent.change(screen.getByLabelText('Email address'), {
      target: { value: 'disabled.agent@demo.local' },
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'correct-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This account has been disabled. Contact your manager.',
    )
  })

  it.each([
    ['another agent', 'AGENT'],
    ['an agent after a manager', 'MANAGER'],
  ] as const)(
    'clears private cached data before rendering %s',
    async (_description, priorRole) => {
      mockedLogin.mockResolvedValue(authFixture('AGENT'))
      const { client } = renderLogin()
      client.setQueryData(
        ['cases'],
        [{ client_name: `${priorRole} private client` }],
      )
      client.setQueryData(['dashboard'], { prior_role: priorRole })

      fireEvent.change(screen.getByLabelText('Email address'), {
        target: { value: 'agent.two@demo.local' },
      })
      fireEvent.change(screen.getByLabelText('Password'), {
        target: { value: 'development-password' },
      })
      fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

      expect(await screen.findByText('Dashboard loaded')).toBeInTheDocument()
      expect(client.getQueryData(['cases'])).toBeUndefined()
      expect(client.getQueryData(['dashboard'])).toBeUndefined()
      expect(
        screen.queryByText(`${priorRole} private client`),
      ).not.toBeInTheDocument()
    },
  )
})
