import { getApiUrl } from '../config/api'
import type {
  AdminLogEntry,
  HealthResponse,
  SystemInfoGroup,
} from './adminTypes'

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(getApiUrl(path), init)
  const contentType = response.headers.get('content-type') || ''

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

export function getSystemHealth() {
  return requestJson<HealthResponse>('/api/v1/system/health')
}

export function getSystemInfo() {
  return requestJson<{ groups: SystemInfoGroup[] }>('/api/v1/system-info')
}

export function getAdminLogs() {
  return requestJson<{ items: AdminLogEntry[] }>('/api/v1/logs')
}

export function getAutoTrackDebug() {
  return requestJson<Record<string, unknown>>('/api/v1/auto-track/debug')
}
