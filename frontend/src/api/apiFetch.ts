import { getApiUrl } from '../config/api'
import { getAuthState, clearAuthStateForToken } from '../stores/authStore'

async function fetchWithAuth(path: string, init?: RequestInit): Promise<Response> {
  const url = getApiUrl(path)
  
  const headers = new Headers(init?.headers)
  const authState = getAuthState()
  const accessToken = authState.accessToken
  
  if (accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }

  const response = await fetch(url, {
    ...init,
    headers,
  })

  if (response.status === 401 && accessToken && !path.startsWith('/api/v1/auth/')) {
    const cleared = clearAuthStateForToken(accessToken, '登录已过期，请重新登录')
    if (cleared && typeof window !== 'undefined') {
      window.location.assign('/login')
    }
  }

  return response
}

async function readErrorMessage(response: Response) {
  const contentType = response.headers.get('content-type') || ''
  let message = `HTTP ${response.status}`
  if (contentType.includes('application/json')) {
    const data = await response.json().catch(() => ({})) as { detail?: unknown }
    message = typeof data.detail === 'string' ? data.detail : message
  }
  return message
}

export async function apiFetch<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithAuth(path, init)
  const contentType = response.headers.get('content-type') || ''

  // 204 No Content
  if (response.status === 204) {
    return null as T
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  if (!contentType.includes('application/json')) {
    throw new Error(`接口 ${path} 未返回 JSON`)
  }

  return response.json() as Promise<T>
}

export async function apiFetchArrayBuffer(path: string, init?: RequestInit): Promise<ArrayBuffer> {
  const response = await fetchWithAuth(path, init)
  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }
  return response.arrayBuffer()
}

export async function apiFetchBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await fetchWithAuth(path, init)
  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }
  return response.blob()
}
