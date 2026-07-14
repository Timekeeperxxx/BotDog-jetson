import { getApiUrl } from '../config/api'
import { apiFetch, apiFetchArrayBuffer } from './apiFetch'
import type {
  LocalizationPose,
  LocalizationPosePayload,
  NavWaypoint,
  NavWaypointCreatePayload,
  MappingControlResponse,
  RadarHealthResponse,
  PcdSceneListResponse,
  NavCurrentScene,
  PcdBounds,
  PcdSceneMetadata,
  PcdScenePreview,
  PcdSceneLayerRole,
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

const PCD_SCENE_BINARY_MAGIC = 'BDPCD001'

type PcdSceneBinaryLayerHeader = {
  role: PcdSceneLayerRole
  file_name: string
  bounds: PcdBounds
  point_count: number
  byte_offset: number
  byte_length: number
}

type PcdSceneBinaryHeader = {
  scene_id: string
  frame_id: string
  layers: Record<'ground' | 'wall' | 'footprint_fill', PcdSceneBinaryLayerHeader | null>
  bounds: PcdBounds
}

function decodePcdScenePreviewBinary(buffer: ArrayBuffer): PcdScenePreview {
  if (buffer.byteLength < 12) throw new Error('无效的点云二进制响应')

  const magic = new TextDecoder().decode(new Uint8Array(buffer, 0, 8))
  if (magic !== PCD_SCENE_BINARY_MAGIC) throw new Error('无效的点云二进制响应')

  const headerLength = new DataView(buffer, 8, 4).getUint32(0, true)
  const pointDataOffset = 12 + headerLength
  if (headerLength <= 0 || pointDataOffset > buffer.byteLength || pointDataOffset % 4 !== 0) {
    throw new Error('无效的点云二进制响应')
  }

  let header: PcdSceneBinaryHeader
  try {
    const headerText = new TextDecoder().decode(new Uint8Array(buffer, 12, headerLength))
    header = JSON.parse(headerText) as PcdSceneBinaryHeader
  } catch {
    throw new Error('无效的点云二进制响应')
  }

  const decodeLayer = (role: 'ground' | 'wall' | 'footprint_fill') => {
    const layer = header.layers[role]
    if (!layer) return null
    const { byte_length: byteLength, byte_offset: byteOffset, point_count: pointCount } = layer
    const absoluteOffset = pointDataOffset + byteOffset
    if (
      !Number.isSafeInteger(pointCount) || pointCount < 0 ||
      !Number.isSafeInteger(byteOffset) || byteOffset < 0 ||
      byteLength !== pointCount * 3 * Float32Array.BYTES_PER_ELEMENT ||
      absoluteOffset % 4 !== 0 || absoluteOffset + byteLength > buffer.byteLength
    ) {
      throw new Error('无效的点云二进制响应')
    }

    const values = new Float32Array(buffer, absoluteOffset, pointCount * 3)
    const points = new Array<[number, number, number]>(pointCount)
    for (let index = 0; index < pointCount; index += 1) {
      const valueIndex = index * 3
      points[index] = [values[valueIndex], values[valueIndex + 1], values[valueIndex + 2]]
    }
    return {
      role: layer.role,
      file_name: layer.file_name,
      points,
      bounds: layer.bounds,
    }
  }

  return {
    scene_id: header.scene_id,
    frame_id: header.frame_id,
    layers: {
      ground: decodeLayer('ground'),
      wall: decodeLayer('wall'),
      footprint_fill: decodeLayer('footprint_fill'),
    },
    bounds: header.bounds,
  }
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
  cmd_vel?: {
    success: boolean
    running: boolean
    pid: number | null
    ready?: boolean
    ready_wait_s?: number
    message?: string
  }
  auto_track?: {
    requested: boolean
    enabled: boolean
    state: string | null
    message?: string | null
  } | null
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
  cleanup?: {
    waypoints?: { removed_items?: number; deleted_files?: string[]; updated_files?: string[] }
    localization?: { deleted_files?: string[] }
    tasks?: { deleted_task_ids?: string[]; removed_count?: number }
    runtime?: { deleted_files?: string[] }
  } | null
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
  const path = `/api/v1/nav/pcd-scenes/${encodeURIComponent(sceneId)}/preview.bin?max_points=${maxPoints}`
  return apiFetchArrayBuffer(path).then(decodePcdScenePreviewBinary).catch((error: unknown) => {
    // 兼容前端先于后端发布的短暂窗口；新后端的其他错误保持原样抛出。
    if (
      !(error instanceof Error) ||
      (
        error.message !== 'HTTP 404' &&
        error.message !== 'Not Found' &&
        error.message !== '无效的点云二进制响应'
      )
    ) throw error
    return requestJson(
      getApiUrl(
        `/api/v1/nav/pcd-scenes/${encodeURIComponent(sceneId)}/preview?max_points=${maxPoints}`,
      ),
    )
  })
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
    publish_count?: number
    waypoint_id?: string
    x: number
    y: number
    z: number
    yaw: number
    frame_id: string
  }
  message?: string | null
  cmd_vel?: {
    success: boolean
    running: boolean
    pid: number | null
    ready?: boolean
    ready_wait_s?: number
    message?: string
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
  runtime_mode?: 'navigation_scan' | 'legacy_p2p'
  scene_ok: boolean
  scene_id: string | null
  scene_dir: string | null
  map_pcd_ok: boolean
  map_pcd: string | null
  ground_pcd_ok: boolean
  ground_pcd: string | null
  planground_pcd_ok: boolean
  planground_pcd: string | null
  livox_ok: boolean
  relocation_ok: boolean
  global_planner_ok: boolean
  navigation_ok?: boolean | null
  p2p_move_base_ok: boolean | null
  scan_planner_ok?: boolean | null
  scan_controller_ok?: boolean | null
  dynamic_avoidance_ok?: boolean | null
  nav_status_monitor_ok?: boolean | null
  cmd_vel_test_publisher_running: boolean
  cmd_vel_running?: boolean | null
  cmd_vel_pid?: number | null
  tf_ok: boolean | null
  warnings: string[]
  errors: string[]
}

export type LocalizationRestartResponse = {
  success: boolean
  running: boolean
  pid: number | null
  scene_id?: string | null
  scene_dir?: string | null
  map_pcd?: string | null
  ground_pcd?: string | null
  planground_pcd?: string | null
  livox_pid: number | null
  relocation_pid: number | null
  global_planner_pid: number | null
  p2p_move_base_pid?: number | null
  navigation_pid?: number | null
  scan_planner_pid?: number | null
  scan_controller_pid?: number | null
  dynamic_avoidance_pid?: number | null
  nav_status_monitor_pid?: number | null
  cmd_vel_pid: number | null
  cmd_vel_running?: boolean | null
  startup_ready?: boolean | null
  navigation_ready?: boolean | null
  process_pids?: Record<string, number | null> | null
  health?: LocalizationRestartHealth | null
  warnings?: string[] | null
  errors?: string[] | null
  message: string
  initialpose_wait_log_offset?: number | null
}

const RESTART_NAVIGATION_LOCALIZATION_TIMEOUT_MS = 10 * 60 * 1000

export function restartNavigationLocalization(): Promise<LocalizationRestartResponse> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    RESTART_NAVIGATION_LOCALIZATION_TIMEOUT_MS,
  )

  return requestJson<LocalizationRestartResponse>(
    getApiUrl('/api/v1/nav/localization/restart'),
    {
      method: 'POST',
      signal: controller.signal,
    },
  ).finally(() => window.clearTimeout(timeoutId))
}

export function waitInitialposeReady(
  offset = 0,
  timeoutSeconds = 45,
): Promise<{
  ready: boolean
  marker: string
  offset: number
  initialpose_subscriber_count?: number
  initialpose_graph_subscriber_count?: number
  initialpose_matched_subscriber_count?: number
  initialpose_topic?: string
  relocation_pid?: number | null
  relocation_running?: boolean
  message: string
}> {
  return requestJson(
    getApiUrl(
      `/api/v1/nav/localization/initialpose-ready?offset=${encodeURIComponent(String(offset))}&timeout_s=${encodeURIComponent(String(timeoutSeconds))}`,
    ),
  )
}

export function waitNavigationRuntimeReady(timeoutSeconds = 600): Promise<{
  ready: boolean
  navigation_ready: boolean
  health?: LocalizationRestartHealth | null
  warnings?: string[] | null
  errors?: string[] | null
  message: string
}> {
  return requestJson(
    getApiUrl(
      `/api/v1/nav/localization/navigation-ready?timeout_s=${encodeURIComponent(String(timeoutSeconds))}`,
    ),
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

export function getMappingStatus(): Promise<MappingControlResponse> {
  return requestJson(getApiUrl('/api/v1/nav/mapping/status'))
}

export function checkRadarHealth(): Promise<RadarHealthResponse> {
  return requestJson(getApiUrl('/api/v1/system/radar/health'))
}

export type NavAutoTrackModeResponse = {
  success: boolean
  enabled: boolean
  auto_track_enabled: boolean
  auto_track_state: string | null
  message: string
}

export function getNavAutoTrackMode(): Promise<NavAutoTrackModeResponse> {
  return requestJson(getApiUrl('/api/v1/nav/auto-track-mode'))
}

export function setNavAutoTrackMode(enabled: boolean): Promise<NavAutoTrackModeResponse> {
  return requestJson(
    getApiUrl('/api/v1/nav/auto-track-mode'),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    },
  )
}

export function triggerNavEmergencyStop(): Promise<{ success: boolean; topic: string | null; message: string }> {
  return requestJson(
    getApiUrl('/api/v1/nav/e-stop'),
    { method: 'POST' },
  )
}
