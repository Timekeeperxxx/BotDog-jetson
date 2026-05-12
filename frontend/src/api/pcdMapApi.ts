import { getApiUrl } from '../config/api'
import { apiFetch } from './apiFetch'
import type {
  LocalizationPose,
  LocalizationPosePayload,
  NavWaypoint,
  NavWaypointCreatePayload,
  MappingControlResponse,
  PcdSceneListResponse,
  NavCurrentScene,
  PcdSceneMetadata,
  PcdScenePreview,
  PcdMapListResponse,
  PcdMetadata,
  PcdPreview,
} from '../types/pcdMap'
import type { TaskDefinition } from '../types/taskWorkflow'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const path = url.startsWith('http://') || url.startsWith('https://')
    ? `${new URL(url).pathname}${new URL(url).search}`
    : url

  return apiFetch<T>(path, init)
}

export function listPcdMaps(): Promise<PcdMapListResponse> {
  return requestJson(getApiUrl('/api/v1/nav/pcd-maps'))
}

export function listPcdScenes(): Promise<PcdSceneListResponse> {
  return requestJson(getApiUrl('/api/v1/nav/pcd-scenes'))
}

export function listNavTasks(): Promise<{ items: TaskDefinition[] }> {
  return requestJson(getApiUrl('/api/v1/nav/tasks'))
}

export function saveNavTask(task: TaskDefinition): Promise<{ success: boolean; task: TaskDefinition }> {
  return requestJson(
    getApiUrl(`/api/v1/nav/tasks/${encodeURIComponent(task.id)}`),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task }),
    },
  )
}

export function deleteNavTask(taskId: string): Promise<{ success: boolean; task_id: string }> {
  return requestJson(
    getApiUrl(`/api/v1/nav/tasks/${encodeURIComponent(taskId)}`),
    { method: 'DELETE' },
  )
}

export function executeNavTask(taskId: string): Promise<{
  success: boolean
  task_id: string
  topic: string
  data: boolean
  nav_start: {
    success: boolean
    topic: string
    data: boolean
  }
  message: string
  runtime_file?: string | null
  runtime_task?: Record<string, unknown> | null
}> {
  return requestJson(
    getApiUrl(`/api/v1/nav/tasks/${encodeURIComponent(taskId)}/execute`),
    { method: 'POST' },
  )
}

export function stopNavTask(taskId: string): Promise<{
  success: boolean
  task_id: string
  topic: string
  data: boolean
  nav_start: {
    success: boolean
    topic: string
    data: boolean
  }
  message: string
}> {
  return requestJson(
    getApiUrl(`/api/v1/nav/tasks/${encodeURIComponent(taskId)}/stop`),
    { method: 'POST' },
  )
}

export function deletePcdScene(sceneId: string): Promise<{
  success: boolean
  scene_id: string
  deleted_path: string
  message: string
}> {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-scenes/${encodeURIComponent(sceneId)}`),
    { method: 'DELETE' },
  )
}

export function selectPcdScene(sceneId: string): Promise<NavCurrentScene> {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-scenes/${encodeURIComponent(sceneId)}/select`),
    { method: 'POST' },
  )
}

export function notifyNavPageOpen(): Promise<{ success: boolean; topic: string; data: boolean }> {
  return requestJson(
    getApiUrl('/api/v1/nav/page-open'),
    { method: 'POST' },
  )
}

export function getPcdMetadata(mapId: string): Promise<PcdMetadata> {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/metadata`),
  )
}

export function getPcdSceneMetadata(sceneId: string): Promise<PcdSceneMetadata> {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-scenes/${encodeURIComponent(sceneId)}/metadata`),
  )
}

export function getPcdPreview(mapId: string, maxPoints = 100000): Promise<PcdPreview> {
  return requestJson(
    getApiUrl(
      `/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/preview?max_points=${maxPoints}`,
    ),
  )
}

export function getPcdScenePreview(sceneId: string, maxPoints = 15000): Promise<PcdScenePreview> {
  return requestJson(
    getApiUrl(
      `/api/v1/nav/pcd-scenes/${encodeURIComponent(sceneId)}/preview?max_points=${maxPoints}`,
    ),
  )
}

export function listWaypoints(mapId: string): Promise<{ items: NavWaypoint[] }> {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/waypoints`),
  )
}

export function createWaypoint(
  mapId: string,
  payload: NavWaypointCreatePayload,
): Promise<NavWaypoint> {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/waypoints`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function deleteWaypoint(
  mapId: string,
  waypointId: string,
): Promise<{ success: boolean }> {
  return requestJson(
    getApiUrl(
      `/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/waypoints/${encodeURIComponent(waypointId)}`,
    ),
    { method: 'DELETE' },
  )
}

export function goToWaypoint(
  mapId: string,
  waypointId: string,
): Promise<{
  success: boolean
  topic: string
  waypoint_id: string
  xyz_topic: string
  yaw_topic: string
  goal?: {
    success: boolean
    xyz_topic: string
    yaw_topic: string
    waypoint_id?: string
    x: number
    y: number
    z: number
    yaw: number
    frame_id: string
  }
  message?: string | null
}> {
  return requestJson(
    getApiUrl(
      `/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/waypoints/${encodeURIComponent(waypointId)}/go-to`,
    ),
    { method: 'POST' },
  )
}

export function setLocalizationPose(
  payload: LocalizationPosePayload,
): Promise<LocalizationPose> {
  return requestJson(
    getApiUrl('/api/v1/nav/localization/set-pose'),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function triggerControlEmergencyStop(): Promise<{
  success: boolean
  timestamp: string
  message: string
}> {
  return requestJson(
    getApiUrl('/api/v1/control/e-stop'),
    { method: 'POST' },
  )
}

export type LocalizationRestartHealth = {
  scene_ok: boolean
  scene_id: string | null
  scene_dir: string | null
  map_pcd_ok: boolean
  map_pcd: string | null
  ground_pcd_ok: boolean
  ground_pcd: string | null
  livox_ok: boolean
  relocation_ok: boolean
  global_planner_ok: boolean
  p2p_move_base_ok: boolean
  cmd_vel_test_publisher_running: boolean
  cmd_vel_running?: boolean | null
  cmd_vel_pid?: number | null
  tf_ok: boolean | null
  warnings: string[]
  errors: string[]
}

export function restartNavigationLocalization(): Promise<{
  success: boolean
  running: boolean
  pid: number | null
  scene_id?: string | null
  scene_dir?: string | null
  map_pcd?: string | null
  ground_pcd?: string | null
  livox_pid: number | null
  relocation_pid: number | null
  global_planner_pid: number | null
  p2p_move_base_pid: number | null
  cmd_vel_pid: number | null
  cmd_vel_running?: boolean | null
  navigation_ready?: boolean | null
  process_pids?: Record<string, number | null> | null
  health?: LocalizationRestartHealth | null
  warnings?: string[] | null
  errors?: string[] | null
  message: string
}> {
  return requestJson(
    getApiUrl('/api/v1/nav/localization/restart'),
    { method: 'POST' },
  )
}

export function setMappingEnabled(
  enabled: boolean,
  sceneName?: string,
): Promise<MappingControlResponse> {
  const body: Record<string, string | boolean | null> = {
    enabled,
  }
  if (sceneName !== undefined) {
    body.scene_name = sceneName
  }

  return requestJson(
    getApiUrl('/api/v1/nav/mapping/set-enabled'),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
}

export function triggerNavEmergencyStop(): Promise<{ success: boolean; topic: string | null; message: string }> {
  return requestJson(
    getApiUrl('/api/v1/nav/e-stop'),
    { method: 'POST' },
  )
}
