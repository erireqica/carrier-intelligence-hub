import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Building2, LockKeyhole, UserRound } from 'lucide-react'

import { authQueryKey, useCurrentUser } from '../app/auth'
import { Button, Input, PageHeader, StatusBadge } from '../components/ui'
import { changePassword, updateProfile } from '../lib/api'
import { formatDate } from '../lib/format'

const CURRENT_PASSWORD_MIN_LENGTH = 8
const NEW_PASSWORD_MIN_LENGTH = 12

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
  const [profileValidationError, setProfileValidationError] = useState<
    string | null
  >(null)
  const [passwordValidationError, setPasswordValidationError] = useState<
    string | null
  >(null)
  const [showProfilePassword, setShowProfilePassword] = useState(false)
  const [showPasswords, setShowPasswords] = useState(false)
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
    <div className="app-page space-y-6">
      <PageHeader
        title="Profile"
        description="Update your Carrier Hub sign-in details and password."
      />
      <div className="grid items-start gap-6 xl:grid-cols-2">
        <div className="space-y-6" aria-label="Account and agency information">
          <form
            className="form-panel space-y-5 p-6"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              setProfileValidationError(null)
              if (
                emailChanged &&
                profilePassword.length < CURRENT_PASSWORD_MIN_LENGTH
              ) {
                setProfileValidationError(
                  `Current password must be at least ${CURRENT_PASSWORD_MIN_LENGTH} characters.`,
                )
                return
              }
              profile.mutate()
            }}
          >
            <div className="flex items-center gap-3 border-b border-slate-100 pb-4">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                <UserRound className="h-[18px] w-[18px]" aria-hidden />
              </span>
              <div>
                <h2 className="font-semibold">Account details</h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  Your name and sign-in email
                </p>
              </div>
            </div>
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
              <div>
                <label className="block text-sm font-medium">
                  Current password
                  <Input
                    className="mt-1"
                    type={showProfilePassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    minLength={CURRENT_PASSWORD_MIN_LENGTH}
                    value={profilePassword}
                    onChange={(event) => setProfilePassword(event.target.value)}
                    required
                  />
                  <span className="mt-1 block text-xs font-normal text-slate-500">
                    Required to change your login email.
                  </span>
                </label>
                <label className="mt-2 flex items-center gap-2 text-xs text-slate-700">
                  <input
                    type="checkbox"
                    checked={showProfilePassword}
                    onChange={(event) =>
                      setShowProfilePassword(event.target.checked)
                    }
                  />
                  Show password
                </label>
              </div>
            )}
            {profileValidationError && (
              <p className="text-sm text-red-700" role="alert">
                {profileValidationError}
              </p>
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
          <section className="surface-panel p-6">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                <Building2 className="h-[18px] w-[18px]" aria-hidden />
              </span>
              <h2 className="font-semibold">Agency access</h2>
            </div>
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
                  <StatusBadge
                    status={user.is_active ? 'ACTIVE' : 'DISABLED'}
                  />
                </dd>
              </div>
            </dl>
          </section>
        </div>

        <form
          aria-label="Change password"
          className="form-panel space-y-5 p-6"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            setPasswordValidationError(null)
            if (currentPassword.length < CURRENT_PASSWORD_MIN_LENGTH) {
              setPasswordValidationError(
                `Current password must be at least ${CURRENT_PASSWORD_MIN_LENGTH} characters.`,
              )
              return
            }
            if (newPassword.length < NEW_PASSWORD_MIN_LENGTH) {
              setPasswordValidationError(
                `New password must be at least ${NEW_PASSWORD_MIN_LENGTH} characters.`,
              )
              return
            }
            if (newPassword !== confirmPassword) {
              setPasswordValidationError(
                'New password and confirmation do not match.',
              )
              return
            }
            password.mutate()
          }}
        >
          <div className="flex items-center gap-3 border-b border-slate-100 pb-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
              <LockKeyhole className="h-[18px] w-[18px]" aria-hidden />
            </span>
            <div>
              <h2 className="font-semibold">Change password</h2>
              <p className="mt-0.5 text-xs text-slate-500">
                Keep your internal account secure
              </p>
            </div>
          </div>
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
                type={showPasswords ? 'text' : 'password'}
                autoComplete={autoComplete as string}
                minLength={
                  label === 'Current password'
                    ? CURRENT_PASSWORD_MIN_LENGTH
                    : NEW_PASSWORD_MIN_LENGTH
                }
                value={value as string}
                onChange={(event) =>
                  (setter as (value: string) => void)(event.target.value)
                }
                required
              />
            </label>
          ))}
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={showPasswords}
              onChange={(event) => setShowPasswords(event.target.checked)}
            />
            Show passwords
          </label>
          {passwordValidationError && (
            <p className="text-sm text-red-700" role="alert">
              {passwordValidationError}
            </p>
          )}
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
    </div>
  )
}
