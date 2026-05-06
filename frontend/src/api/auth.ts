import { getApiUrl } from '../config/api'
import { apiFetch } from './apiFetch'

export type LoginResult = {
  access_token: string
  token_type: string
  user: {
    id: number
    username: string
    role: 'viewer' | 'operator' | 'admin'
    must_change_password: boolean
  }
}

export type AuthUser = {
  id: number
  username: string
  role: 'viewer' | 'operator' | 'admin'
  must_change_password: boolean
}

export type AuthStatusResult = {
  auth_enabled: boolean
  current_user: {
    id: number
    username: string
    role: 'viewer' | 'operator' | 'admin'
    must_change_password: boolean
  }
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
  return apiFetch<AuthUser>('/api/v1/auth/me')
}

export async function getAuthStatus(): Promise<AuthStatusResult> {
  return apiFetch<AuthStatusResult>('/api/v1/auth/status')
}
