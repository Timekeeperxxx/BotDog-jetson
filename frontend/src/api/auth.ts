import { getApiUrl } from '../config/api'

export type LoginResult = {
  access_token: string
  token_type: string
  user: {
    username: string
    role: 'viewer' | 'operator' | 'admin'
  }
}

export type AuthUser = {
  username: string
  role: 'viewer' | 'operator' | 'admin'
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const response = await fetch(getApiUrl('/api/v1/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const contentType = response.headers.get('content-type') || ''
  if (!response.ok) {
    let message = `HTTP ${response.status}`
    if (contentType.includes('application/json')) {
      const data = await response.json().catch(() => ({}))
      message = data.detail || message
    }
    throw new Error(message)
  }
  return response.json() as Promise<LoginResult>
}

export async function getCurrentUser(): Promise<AuthUser> {
  const response = await fetch(getApiUrl('/api/v1/auth/me'))
  const contentType = response.headers.get('content-type') || ''
  if (!response.ok) {
    let message = `HTTP ${response.status}`
    if (contentType.includes('application/json')) {
      const data = await response.json().catch(() => ({}))
      message = data.detail || message
    }
    throw new Error(message)
  }
  return response.json() as Promise<AuthUser>
}
