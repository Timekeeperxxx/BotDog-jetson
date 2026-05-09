import type { SystemConfig } from '../types/config'
import type { AlertEvent, AIStatus, AutoTrackStatus } from '../types/event'
import type { EvidenceItem } from '../types/evidence'
import type { NavigationStatus, NavStateResponse } from '../types/navState'
import type { VideoSource, NetworkInterface } from '../types/admin'
import type { PcdMapItem, NavWaypoint, PcdMetadata } from '../types/pcdMap'
import type { TaskDefinition } from '../types/taskWorkflow'

export type AdminSection =
  | 'dashboard'
  | 'control'
  | 'navigation'
  | 'device-video'
  | 'ai-guard'
  | 'evidence'
  | 'logs'
  | 'config'
  | 'users'
  | 'diagnostics'

export type ModuleHealthState = 'normal' | 'degraded' | 'failed' | 'waiting' | 'todo'

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'offline'
  mavlink_connected: boolean
  uptime: number
}

export interface SystemInfoItem {
  key: string
  label: string
  value: string
  note: string
  env_key: string
}

export interface SystemInfoGroup {
  group: string
  icon: string
  items: SystemInfoItem[]
}

export interface AdminLogEntry {
  log_id: number
  level: string
  module: string
  message: string
  task_id: number | null
  created_at: string
}

export interface AdminDashboardData {
  health: HealthResponse | null
  navState: NavStateResponse | null
  aiStatus: AIStatus | null
  autoTrackStatus: AutoTrackStatus | null
  alerts: AlertEvent[]
  logs: AdminLogEntry[]
  evidence: EvidenceItem[]
  videoSources: VideoSource[]
}

export interface AdminServiceCard {
  key: string
  title: string
  status: ModuleHealthState
  detail: string
  extra?: string
}

export interface AdminNavigationData {
  maps: PcdMapItem[]
  selectedMapId: string | null
  metadata: PcdMetadata | null
  waypoints: NavWaypoint[]
  tasks: TaskDefinition[]
}

export interface AdminTaskSummary {
  id: string
  name: string
  mapId: string
  mapName: string
  loopMode: string
  failurePolicy: string
  enabled: boolean
  steps: string[]
  source: 'json_file'
}

export interface AiConfigGroup {
  title: string
  description: string
  configs: SystemConfig[]
}

export interface AdminVideoAiData {
  videoSources: VideoSource[]
  aiConfigGroups: AiConfigGroup[]
}

export interface DeviceDangerAction {
  key: string
  title: string
  description: string
  supported: boolean
  todo: string
}

export interface DeviceOverviewData {
  systemInfo: SystemInfoGroup[]
  networkInterfaces: NetworkInterface[]
  health: HealthResponse | null
  navState: NavStateResponse | null
  aiStatus: AIStatus | null
  autoTrackStatus: AutoTrackStatus | null
}

export interface AdminLogFilters {
  level: string
  keyword: string
}

export type SortableNavigationTab = 'maps' | 'waypoints' | 'tasks' | 'history'

export interface EvidenceFilters {
  severity: string
  keyword: string
}

export function mapHealthStatus(status?: string | null): ModuleHealthState {
  if (status === 'healthy' || status === 'connected' || status === 'ready') return 'normal'
  if (status === 'degraded') return 'degraded'
  if (status === 'offline' || status === 'failed' || status === 'error') return 'failed'
  if (status === 'waiting' || status === 'connecting' || status === 'initializing') return 'waiting'
  return 'todo'
}

export function mapNavStatus(status?: NavigationStatus['status'] | string | null): ModuleHealthState {
  if (!status) return 'waiting'
  if (['idle', 'localized', 'ready', 'succeeded'].includes(status)) return 'normal'
  if (['navigating', 'initializing'].includes(status)) return 'waiting'
  if (['cancelled', 'failed'].includes(status)) return 'degraded'
  return 'waiting'
}
