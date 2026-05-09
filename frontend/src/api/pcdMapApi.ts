import { getApiUrl } from '../config/api'
import type {
  LocalizationPose,
  LocalizationPosePayload,
  NavWaypoint,
  NavWaypointCreatePayload,
  MappingControlResponse,
  PcdSceneListResponse,
  PcdSceneMetadata,
  PcdScenePreview,
  PcdMapListResponse,
  PcdMetadata,
  PcdPreview,
} from '../types/pcdMap'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
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

export function listPcdMaps(): Promise<PcdMapListResponse> {
  return requestJson(getApiUrl('/api/v1/nav/pcd-maps'))
}

export function listPcdScenes(): Promise<PcdSceneListResponse> {
  return requestJson(getApiUrl('/api/v1/nav/pcd-scenes'))
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
  xyz_topic?: string
  yaw_topic?: string
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

export function restartNavigationLocalization(): Promise<{
  success: boolean
  running: boolean
  pid: number | null
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

export function triggerNavEmergencyStop(): Promise<{ success: boolean; topic: string }> {
  return requestJson(
    getApiUrl('/api/v1/nav/e-stop'),
    { method: 'POST' },
  )
}
