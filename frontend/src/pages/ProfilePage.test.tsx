import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

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
  it('updates profile details and requires the current password for email changes', async () => {
    vi.mocked(useCurrentUser).mockReturnValue({
      data: authFixture('AGENT'),
    } as ReturnType<typeof useCurrentUser>)
    vi.mocked(updateProfile).mockResolvedValue({
      ...authFixture('AGENT'),
      user: { ...authFixture('AGENT').user, full_name: 'Elena Updated' },
    })
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <ProfilePage />
      </QueryClientProvider>,
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
})
