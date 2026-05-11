import { apiFetch } from '../api/apiFetch'
import type {
  AdminLogEntry,
  AdminLogFileTail,
  AdminLogFilesResponse,
  HealthResponse,
  SystemInfoGroup,
} from './adminTypes'

export function getSystemHealth() {
  return apiFetch<HealthResponse>('/api/v1/system/health')
}

export function getSystemInfo() {
  return apiFetch<{ groups: SystemInfoGroup[] }>('/api/v1/system-info')
}

export function getAdminLogs() {
  return apiFetch<{ items: AdminLogEntry[] }>('/api/v1/logs')
}

export function getAutoTrackDebug() {
  return apiFetch<Record<string, unknown>>('/api/v1/auto-track/debug')
}

export function listLogFiles() {
  return apiFetch<AdminLogFilesResponse>('/api/v1/log-files')
}

export function getLogFileTail(name: string, lines = 300) {
  return apiFetch<AdminLogFileTail>(`/api/v1/log-files/${encodeURIComponent(name)}/tail?lines=${lines}`)
}
