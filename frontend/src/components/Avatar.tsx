import { useState } from 'react'

import { apiBaseUrl } from '../lib/api-url'

type AvatarUser = {
  full_name: string
  avatar_url?: string | null
}

const sizes = {
  sm: 'h-8 w-8 text-[0.65rem] rounded-lg',
  md: 'h-9 w-9 text-xs rounded-lg',
  lg: 'h-11 w-11 text-sm rounded-xl',
  xl: 'h-24 w-24 text-xl rounded-2xl',
} as const

function initials(fullName: string) {
  return fullName
    .split(' ')
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export function Avatar({
  user,
  size = 'md',
  className = '',
}: {
  user: AvatarUser
  size?: keyof typeof sizes
  className?: string
}) {
  const imageUrl = user.avatar_url ? `${apiBaseUrl}${user.avatar_url}` : null
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const shared = `shrink-0 overflow-hidden ${sizes[size]} ${className}`

  if (imageUrl && imageUrl !== failedUrl) {
    return (
      <img
        className={`${shared} object-cover ring-1 ring-slate-900/10`}
        src={imageUrl}
        alt={`${user.full_name} profile`}
        onError={() => setFailedUrl(imageUrl)}
      />
    )
  }
  return (
    <span
      className={`${shared} inline-flex items-center justify-center bg-slate-900 font-bold text-white`}
      role="img"
      aria-label={`${user.full_name} initials`}
    >
      {initials(user.full_name)}
    </span>
  )
}
