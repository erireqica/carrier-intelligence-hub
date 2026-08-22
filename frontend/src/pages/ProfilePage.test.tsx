import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useCurrentUser } from '../app/auth'
import { changePassword, updateProfile } from '../lib/api'
import { authFixture } from '../test/fixtures'
import { ProfilePage } from './ProfilePage'

vi.mock('../app/auth', () => ({
  authQueryKey: ['auth', 'me'],
  useCurrentUser: vi.fn(),
}))
vi.mock('../lib/api', () => ({
  changePassword: vi.fn(),
  updateProfile: vi.fn(),
}))

afterEach(cleanup)

describe('ProfilePage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('updates profile details and requires the current password for email changes', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('AGENT'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(updateProfile).mockResolvedValue({
      ...authFixture('AGENT'),
      user: {
        ...authFixture('AGENT').user,
        full_name: 'Elena Updated',
        email: 'elena.updated@demo.local',
      },
    })
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <ProfilePage />
      </QueryClientProvider>,
    )
    const leftColumn = screen.getByLabelText('Account and agency information')
    expect(leftColumn).toContainElement(screen.getByText('Account details'))
    expect(leftColumn).toContainElement(screen.getByText('Agency access'))
    expect(leftColumn).not.toContainElement(
      screen.getByRole('form', { name: 'Change password' }),
    )
    fireEvent.change(screen.getByLabelText('Full name'), {
      target: { value: 'Elena Updated' },
    })
    fireEvent.change(screen.getByLabelText('Login email'), {
      target: { value: 'elena.updated@demo.local' },
    })
    await waitFor(() =>
      expect(screen.getAllByLabelText(/Current password/)).toHaveLength(2),
    )
    fireEvent.change(screen.getAllByLabelText(/Current password/)[0], {
      target: { value: 'current-demo-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() =>
      expect(updateProfile).toHaveBeenCalledWith({
        full_name: 'Elena Updated',
        email: 'elena.updated@demo.local',
        current_password: 'current-demo-password',
      }),
    )
    expect(await screen.findByText('Profile updated.')).toBeInTheDocument()
    expect(
      (client.getQueryData(['auth', 'me']) as ReturnType<typeof authFixture>)
        .user.email,
    ).toBe('elena.updated@demo.local')
  })

  it('submits current, new, and confirmed passwords separately', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('MANAGER'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(changePassword).mockResolvedValue({ message: 'Password changed' })
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <ProfilePage />
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('Current password'), {
      target: { value: 'current-password' },
    })
    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: 'new-password-123' },
    })
    fireEvent.change(screen.getByLabelText('Confirm new password'), {
      target: { value: 'new-password-123' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    await waitFor(() =>
      expect(changePassword).toHaveBeenCalledWith({
        current_password: 'current-password',
        new_password: 'new-password-123',
        confirm_new_password: 'new-password-123',
      }),
    )
  })

  it('shows a wrong current-password response beside the password form', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('AGENT'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(changePassword).mockRejectedValue(
      new Error('Current password is incorrect.'),
    )
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <ProfilePage />
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('Current password'), {
      target: { value: 'wrong-password' },
    })
    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: 'new-password-123' },
    })
    fireEvent.change(screen.getByLabelText('Confirm new password'), {
      target: { value: 'new-password-123' },
    })
    fireEvent.submit(screen.getByRole('form', { name: 'Change password' }))
    expect(
      await screen.findByText('Current password is incorrect.'),
    ).toBeInTheDocument()
  })

  it('validates password constraints before submitting either profile form', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('AGENT'),
    } as ReturnType<typeof useCurrentUser>)
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <ProfilePage />
      </QueryClientProvider>,
    )

    fireEvent.change(screen.getByLabelText('Login email'), {
      target: { value: 'updated@demo.local' },
    })
    fireEvent.change(screen.getAllByLabelText(/Current password/)[0], {
      target: { value: 'x' },
    })
    fireEvent.submit(screen.getByText('Account details').closest('form')!)
    expect(
      await screen.findByText(
        'Current password must be at least 8 characters.',
      ),
    ).toBeInTheDocument()
    expect(updateProfile).not.toHaveBeenCalled()

    fireEvent.change(screen.getAllByLabelText(/Current password/)[1], {
      target: { value: 'current-password' },
    })
    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: 'short' },
    })
    fireEvent.change(screen.getByLabelText('Confirm new password'), {
      target: { value: 'short' },
    })
    const passwordForm = screen.getByRole('form', { name: 'Change password' })
    fireEvent.submit(passwordForm)
    expect(
      await screen.findByText('New password must be at least 12 characters.'),
    ).toBeInTheDocument()
    expect(changePassword).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: 'new-password-123' },
    })
    fireEvent.change(screen.getByLabelText('Confirm new password'), {
      target: { value: 'different-12345' },
    })
    fireEvent.submit(passwordForm)
    expect(
      await screen.findByText('New password and confirmation do not match.'),
    ).toBeInTheDocument()
    expect(changePassword).not.toHaveBeenCalled()
  })

  it('keeps Profile and auth data intact when credential verification fails', async () => {
    const auth = authFixture('AGENT')
    vi.mocked(useCurrentUser).mockReturnValue({
      data: auth,
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(updateProfile).mockRejectedValue(
      new Error('Current password is incorrect.'),
    )
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    })
    client.setQueryData(['auth', 'me'], auth)
    render(
      <QueryClientProvider client={client}>
        <ProfilePage />
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('Login email'), {
      target: { value: 'updated@demo.local' },
    })
    fireEvent.change(screen.getAllByLabelText(/Current password/)[0], {
      target: { value: 'wrong-password' },
    })
    fireEvent.submit(screen.getByText('Account details').closest('form')!)

    expect(
      await screen.findByText('Current password is incorrect.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Profile' })).toBeInTheDocument()
    expect(client.getQueryData(['auth', 'me'])).toEqual(auth)
  })

  it('toggles password visibility without clearing entered values', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('AGENT'),
    } as ReturnType<typeof useCurrentUser>)
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <ProfilePage />
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('Login email'), {
      target: { value: 'updated@demo.local' },
    })
    const profilePassword = screen.getAllByLabelText(/Current password/)[0]
    fireEvent.change(profilePassword, { target: { value: 'profile-secret' } })
    expect(profilePassword).toHaveAttribute('type', 'password')
    fireEvent.click(screen.getByLabelText('Show password'))
    expect(profilePassword).toHaveAttribute('type', 'text')
    expect(profilePassword).toHaveValue('profile-secret')

    const passwordFields = [
      screen.getAllByLabelText(/Current password/)[1],
      screen.getByLabelText('New password'),
      screen.getByLabelText('Confirm new password'),
    ]
    passwordFields.forEach((field, index) =>
      fireEvent.change(field, { target: { value: `secret-value-${index}` } }),
    )
    fireEvent.click(screen.getByLabelText('Show passwords'))
    passwordFields.forEach((field, index) => {
      expect(field).toHaveAttribute('type', 'text')
      expect(field).toHaveValue(`secret-value-${index}`)
    })
  })
})
