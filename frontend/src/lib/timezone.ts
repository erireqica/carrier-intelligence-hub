import type { AuthResponse } from './types'

type TimezoneUser = Pick<AuthResponse['user'], 'timezone' | 'agency'>

const browserTimezone =
  Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

export type TimezoneOption = {
  label: string
  value: string
}

export const curatedTimezoneOptions: readonly TimezoneOption[] = [
  {
    label: 'UTC−08 — Los Angeles, Vancouver',
    value: 'America/Los_Angeles',
  },
  { label: 'UTC−07 — Denver', value: 'America/Denver' },
  {
    label: 'UTC−07 — Phoenix (no daylight saving)',
    value: 'America/Phoenix',
  },
  { label: 'UTC−06 — Chicago', value: 'America/Chicago' },
  {
    label: 'UTC−06 — Mexico City (no daylight saving)',
    value: 'America/Mexico_City',
  },
  { label: 'UTC−05 — New York, Toronto', value: 'America/New_York' },
  { label: 'UTC−04 — Halifax', value: 'America/Halifax' },
  {
    label: 'UTC−04 — Caracas (no daylight saving)',
    value: 'America/Caracas',
  },
  {
    label: 'UTC−03 — São Paulo, Buenos Aires',
    value: 'America/Sao_Paulo',
  },
  { label: 'UTC−01 — Azores', value: 'Atlantic/Azores' },
  { label: 'UTC±00 — Coordinated Universal Time', value: 'UTC' },
  { label: 'UTC±00 — London, Lisbon', value: 'Europe/London' },
  {
    label: 'UTC+01 — Pristina, Berlin, Paris, Rome',
    value: 'Europe/Belgrade',
  },
  { label: 'UTC+02 — Athens, Bucharest', value: 'Europe/Athens' },
  { label: 'UTC+02 — Cairo', value: 'Africa/Cairo' },
  {
    label: 'UTC+03 — Istanbul, Moscow, Riyadh',
    value: 'Europe/Istanbul',
  },
  { label: 'UTC+04 — Dubai, Baku', value: 'Asia/Dubai' },
  { label: 'UTC+05 — Karachi, Tashkent', value: 'Asia/Karachi' },
  { label: 'UTC+05:30 — Delhi, Mumbai', value: 'Asia/Kolkata' },
  { label: 'UTC+06 — Dhaka', value: 'Asia/Dhaka' },
  { label: 'UTC+07 — Bangkok, Jakarta', value: 'Asia/Bangkok' },
  {
    label: 'UTC+08 — Singapore, Beijing, Hong Kong',
    value: 'Asia/Singapore',
  },
  { label: 'UTC+09 — Tokyo, Seoul', value: 'Asia/Tokyo' },
  { label: 'UTC+09:30 — Adelaide', value: 'Australia/Adelaide' },
  { label: 'UTC+10 — Sydney', value: 'Australia/Sydney' },
  {
    label: 'UTC+10 — Brisbane (no daylight saving)',
    value: 'Australia/Brisbane',
  },
  { label: 'UTC+12 — Auckland', value: 'Pacific/Auckland' },
]

export function getEffectiveTimezone(user?: TimezoneUser) {
  return user?.timezone ?? user?.agency.timezone ?? browserTimezone
}

export function getTimezoneOptions(currentTimezone?: string | null) {
  if (
    !currentTimezone ||
    curatedTimezoneOptions.some((option) => option.value === currentTimezone)
  ) {
    return curatedTimezoneOptions
  }
  return [
    {
      label: `Current selection — ${currentTimezone}`,
      value: currentTimezone,
    },
    ...curatedTimezoneOptions,
  ]
}
