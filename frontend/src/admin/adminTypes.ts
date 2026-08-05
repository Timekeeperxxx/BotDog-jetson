import type { SystemConfig } from '../types/config'
import type { AIStatus, AutoTrackStatus } from '../types/event'
import type { NavigationStatus, NavStateResponse } from '../types/navState'
import type { VideoSource, NetworkInterface } from '../types/admin'
import type { PcdSceneItem, NavWaypoint, PcdSceneMetadata } from '../types/pcdMap'
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
  | 'face-identities'
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

export interface AdminLogFileInfo {
  name: string
  category: 'backend' | 'video' | 'navigation' | 'other'
  size_bytes: number
  modified_at: string
  lines_hint: number | null
}

export interface AdminLogFileTail {
  name: string
  lines: string[]
  line_count: number
  truncated: boolean
}

export interface AdminLogFilesResponse {
  items: AdminLogFileInfo[]
}

export interface AdminDashboardData {
  health: HealthResponse | null
  navState: NavStateResponse | null
  aiStatus: AIStatus | null
  autoTrackStatus: AutoTrackStatus | null
  systemInfo: SystemInfoGroup[]
  networkInterfaces: NetworkInterface[]
  hostResources: HostResources | null
}

export interface AdminServiceCard {
  key: string
  title: string
  status: ModuleHealthState
  detail: string
  extra?: string
}

export interface AdminNavigationData {
  scenes: PcdSceneItem[]
  selectedSceneId: string | null
  metadata: PcdSceneMetadata | null
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
  key: SystemDangerActionKey
  title: string
  description: string
  effect: string
  confirmation: string
}

export type SystemDangerActionKey =
  | 'restart-backend'
  | 'restart-video'
  | 'restart-ai'
  | 'reboot-device'

export interface HostResources {
  collected_at: string
  hostname: string
  platform: string
  architecture: string
  cpu_count: number
  load_average: number[]
  host_uptime_seconds: number | null
  memory: {
    total_bytes: number
    used_bytes: number
    available_bytes: number
    usage_percent: number
    swap_total_bytes: number
    swap_used_bytes: number
  }
  disk: {
    path: string
    total_bytes: number
    used_bytes: number
    free_bytes: number
    usage_percent: number
  }
}

export interface SystemActionResponse {
  success: boolean
  action: SystemDangerActionKey
  scheduled: boolean
  message: string
}

export interface DeviceOverviewData {
  systemInfo: SystemInfoGroup[]
  networkInterfaces: NetworkInterface[]
  health: HealthResponse | null
  navState: NavStateResponse | null
  aiStatus: AIStatus | null
  autoTrackStatus: AutoTrackStatus | null
  hostResources: HostResources | null
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
