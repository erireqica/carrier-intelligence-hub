export function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
    new Date(value),
  )
}

export function formatBusinessDate(value: string | null | undefined) {
  if (!value) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return formatDate(value)
  const [, year, month, day] = match
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))))
}

export function businessDaysFromToday(
  value: string,
  timezone: string,
  now = new Date(),
) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const todayParts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(todayParts.find((item) => item.type === type)?.value)
  const today = Date.UTC(part('year'), part('month') - 1, part('day'))
  const due = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return (due - today) / 86_400_000
}
