import type { AuthResponse } from '../lib/types'

export function authFixture(role: 'AGENT' | 'MANAGER' = 'AGENT'): AuthResponse {
  return {
    user: {
      id: role === 'MANAGER' ? 1 : 2,
      email: role === 'MANAGER' ? 'manager@demo.local' : 'agent.one@demo.local',
      full_name: role === 'MANAGER' ? 'Morgan Reed' : 'Elena Torres',
      role,
      is_active: true,
      last_login_at: null,
      agency: {
        id: 1,
        name: 'Harbor Point Insurance Agency',
        timezone: 'America/Chicago',
      },
    },
    csrf_token: 'test-csrf-token',
    environment: 'development',
  }
}
