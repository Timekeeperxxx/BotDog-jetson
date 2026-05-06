import { getApiUrl } from '../config/api'
import { getAuthState, clearAuthState } from '../stores/authStore'

export async function apiFetch<T = any>(path: string, init?: RequestInit): Promise<T> {
  const url = getApiUrl(path)
  
  const headers = new Headers(init?.headers)
  const authState = getAuthState()
  
  if (authState.accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${authState.accessToken}`)
  }

  const response = await fetch(url, {
    ...init,
    headers,
  })

  const contentType = response.headers.get('content-type') || ''

  if (response.status === 401 && authState.accessToken && !path.startsWith('/api/v1/auth/')) {
    clearAuthState('登录已过期，请重新登录')
    if (typeof window !== 'undefined') {
      window.location.assign('/login')
    }
  }

  // 204 No Content
  if (response.status === 204) {
    return null as any
  }

  if (!response.ok) {
    let message = `HTTP ${response.status}`
    if (contentType.includes('application/json')) {
      const data = await response.json().catch(() => ({}))
      message = data.detail || message
    }
    throw new Error(message)
  }

  if (!contentType.includes('application/json')) {
    throw new Error(`接口 ${path} 未返回 JSON`)
  }

  return response.json() as Promise<T>
}
