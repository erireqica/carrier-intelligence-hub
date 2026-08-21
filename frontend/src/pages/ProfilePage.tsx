import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import { authQueryKey, useCurrentUser } from '../app/auth'
import { Button, Input, PageHeader, StatusBadge } from '../components/ui'
import { changePassword, updateProfile } from '../lib/api'
import { formatDate } from '../lib/format'

export function ProfilePage() {
  const auth = useCurrentUser()
  const user = auth.data!.user
  const queryClient = useQueryClient()
  const [fullName, setFullName] = useState(user.full_name)
  const [email, setEmail] = useState(user.email)
  const [profilePassword, setProfilePassword] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const profile = useMutation({
    mutationFn: () =>
      updateProfile({
        full_name: fullName,
        email,
        ...(profilePassword ? { current_password: profilePassword } : {}),
      }),
    onSuccess: (response) => {
      queryClient.setQueryData(authQueryKey, response)
      setProfilePassword('')
    },
  })
  const password = useMutation({
    mutationFn: () =>
      changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_new_password: confirmPassword,
      }),
    onSuccess: () => {
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    },
  })
  const emailChanged = email.trim().toLowerCase() !== user.email

  return (
    <div className="space-y-6">
      <PageHeader
        title="Profile"
        description="Update your Carrier Hub sign-in details and password."
      />
      <form
        className="max-w-2xl space-y-5 border border-slate-200 bg-white p-5"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          profile.mutate()
        }}
      >
        <h2 className="font-semibold">Account details</h2>
        <label className="block text-sm font-medium">
          Full name
          <Input
            className="mt-1"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            required
          />
        </label>
        <label className="block text-sm font-medium">
          Login email
          <Input
            className="mt-1"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        {emailChanged && (
          <label className="block text-sm font-medium">
            Current password
            <Input
              className="mt-1"
              type="password"
              autoComplete="current-password"
              value={profilePassword}
              onChange={(event) => setProfilePassword(event.target.value)}
              required
            />
            <span className="mt-1 block text-xs font-normal text-slate-500">
              Required to change your login email.
            </span>
          </label>
        )}
        {profile.error && (
          <p className="text-sm text-red-700" role="alert">
            {profile.error.message}
          </p>
        )}
        {profile.isSuccess && (
          <p className="text-sm text-green-700" role="status">
            Profile updated.
          </p>
        )}
        <Button disabled={profile.isPending} type="submit">
          {profile.isPending ? 'Saving…' : 'Save profile'}
        </Button>
      </form>

      <section className="max-w-2xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">Agency access</h2>
        <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
          {[
            ['Role', user.role],
            ['Agency', user.agency.name],
            ['Agency timezone', user.agency.timezone],
            ['Last login', formatDate(user.last_login_at)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-slate-500">{label}</dt>
              <dd className="mt-1 font-medium">{value}</dd>
            </div>
          ))}
          <div>
            <dt className="text-slate-500">Account status</dt>
            <dd className="mt-1">
              <StatusBadge status={user.is_active ? 'ACTIVE' : 'DISABLED'} />
            </dd>
          </div>
        </dl>
      </section>

      <form
        className="max-w-2xl space-y-5 border border-slate-200 bg-white p-5"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          password.mutate()
        }}
      >
        <h2 className="font-semibold">Change password</h2>
        {[
          [
            'Current password',
            currentPassword,
            setCurrentPassword,
            'current-password',
          ],
          ['New password', newPassword, setNewPassword, 'new-password'],
          [
            'Confirm new password',
            confirmPassword,
            setConfirmPassword,
            'new-password',
          ],
        ].map(([label, value, setter, autoComplete]) => (
          <label key={label as string} className="block text-sm font-medium">
            {label as string}
            <Input
              className="mt-1"
              type="password"
              autoComplete={autoComplete as string}
              minLength={label === 'Current password' ? 8 : 12}
              value={value as string}
              onChange={(event) =>
                (setter as (value: string) => void)(event.target.value)
              }
              required
            />
          </label>
        ))}
        {password.error && (
          <p className="text-sm text-red-700" role="alert">
            {password.error.message}
          </p>
        )}
        {password.isSuccess && (
          <p className="text-sm text-green-700" role="status">
            Password changed. Other signed-in sessions were ended.
          </p>
        )}
        <Button disabled={password.isPending} type="submit">
          {password.isPending ? 'Changing…' : 'Change password'}
        </Button>
      </form>
    </div>
  )
}
