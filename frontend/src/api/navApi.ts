import { getApiUrl } from '../config/api'
import type { NavStateResponse } from '../types/navState'

async function requestJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  const contentType = res.headers.get('content-type') || ''

  if (!res.ok) {
    let message = `HTTP ${res.status}`
    if (contentType.includes('application/json')) {
      const data = await res.json()
      message = data.detail || message
    }
    throw new Error(message)
  }

  if (!contentType.includes('application/json')) {
    throw new Error('接口返回的不是 JSON，请检查 VITE_API_BASE_URL 或 Vite /api 代理是否指向后端')
  }

  return res.json() as Promise<T>
}

export function getNavState(): Promise<NavStateResponse> {
  return requestJson(getApiUrl('/api/v1/nav/state'))
}
