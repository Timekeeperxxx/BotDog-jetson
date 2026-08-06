export type PcdBounds = {
  min_x: number
  max_x: number
  min_y: number
  max_y: number
  min_z: number
  max_z: number
}

export type PcdSceneLayerRole =
  | 'ground'
  | 'wall'
  | 'footprint_fill'
  | 'mapping'
  | 'live'

export type WallColorMode = 'solid' | 'height' | 'intensity'
export type PointCloudQualityMode = 'auto' | 'performance' | 'quality'

export type PointCloudPoints = [number, number, number][] | Float32Array

export type PcdSceneFile = {
  name: string
  size_bytes: number
  modified_at: string
}

export type PcdSceneItem = {
  id: string
  name: string
  path: string
  modified_at: string
  wall: PcdSceneFile | null
  ground: PcdSceneFile | null
  footprint_fill: PcdSceneFile | null
  ready: boolean
  navigable: boolean
  message: string | null
}

export type PcdSceneListResponse = {
  root: string
  items: PcdSceneItem[]
}

export type NavCurrentScene = {
  scene_id: string
  scene_dir: string
  map_pcd: string
  ground_pcd: string
  planground_pcd: string | null
  updated_at: string
}

export type PcdSceneLayerMetadata = PcdSceneFile & {
  frame_id: string
  type: 'pcd'
  point_count: number
  fields: string[]
  data_type: string
  bounds: PcdBounds | null
  supported: boolean
  message: string | null
}

export type PcdSceneMetadata = {
  scene_id: string
  name: string
  frame_id: string
  type: 'scene_pcd'
  point_count: number
  fields: string[]
  data_type: string
  files: {
    wall: PcdSceneLayerMetadata | null
    ground: PcdSceneLayerMetadata | null
    footprint_fill: PcdSceneLayerMetadata | null
  }
  bounds: PcdBounds
  supported: boolean
  message: string | null
}

export type PcdSceneLayerPreview = {
  role: PcdSceneLayerRole
  file_name: string
  points: PointCloudPoints
  intensity?: Uint8Array
  bounds: PcdBounds
}

export type PcdScenePreview = {
  scene_id: string
  frame_id: string
  layers: {
    ground: PcdSceneLayerPreview | null
    wall: PcdSceneLayerPreview | null
    footprint_fill: PcdSceneLayerPreview | null
  }
  bounds: PcdBounds
}

export type PcdSceneTilePayload = {
  file: string
  point_count: number
  byte_length: number
  has_intensity: boolean
}

export type PcdSceneRootTile = PcdSceneTilePayload & {
  id: string
  role: Extract<PcdSceneLayerRole, 'ground' | 'wall' | 'footprint_fill'>
  bounds: PcdBounds
}

export type PcdSceneTileNode = {
  id: string
  role: Extract<PcdSceneLayerRole, 'ground' | 'wall' | 'footprint_fill'>
  bounds: PcdBounds
  center: [number, number, number]
  radius: number
  performance: PcdSceneTilePayload
  balanced: PcdSceneTilePayload
  original: PcdSceneTilePayload
}

export type PcdSceneTileManifest = {
  version: number
  cache_key: string
  scene_id: string
  frame_id: string
  bounds: PcdBounds
  layer_bounds: Record<'ground' | 'wall' | 'footprint_fill', PcdBounds | null>
  root_tiles: PcdSceneRootTile[]
  nodes: PcdSceneTileNode[]
  stats: Record<string, {
    source_points: number
    retained_points: number
    original_points: number
    balanced_points: number
    performance_points: number
    tile_count: number
    intensity_percentile_2_98?: [number, number]
  } | null>
  settings: {
    tile_size_m: number
    balanced_voxel_size_m: number
    balanced_points_per_voxel: number
    performance_voxel_size_m: number
    performance_points_per_voxel: number
    max_points_per_tile: number
  }
}

export type PcdMapItem = {
  id: string
  name: string
  size_bytes: number
  modified_at: string
}

export type PcdMapListResponse = {
  root: string
  items: PcdMapItem[]
}

export type PcdMetadata = {
  map_id: string
  name: string
  frame_id: string
  type: 'pcd'
  point_count: number
  fields: string[]
  data_type: string
  bounds: PcdBounds | null
  supported?: boolean
  message?: string | null
}

export type PcdPreview = {
  map_id: string
  frame_id: string
  points: [number, number, number][]
  bounds: PcdBounds
}

export type NavWaypoint = {
  id: string
  map_id: string
  name: string
  x: number
  y: number
  z: number
  yaw: number
  frame_id: string
  created_at: string
  updated_at: string
}

export type NavWaypointCreatePayload = {
  name: string
  x: number
  y: number
  z: number
  yaw: number
  frame_id: 'map'
}

export type NavFencePoint = {
  x: number
  y: number
}

export type NavFence = {
  id: string
  scene_id: string
  start: NavFencePoint
  end: NavFencePoint
  enabled: boolean
}

export type NavFenceCreatePayload = {
  start: NavFencePoint
  end: NavFencePoint
  enabled?: boolean
}

export type LocalizationPosePayload = {
  map_id: string
  x: number
  y: number
  z: number
  yaw: number
  frame_id: 'map'
}

export type LocalizationPose = {
  map_id: string
  x: number
  y: number
  z: number
  yaw: number
  frame_id: string
  updated_at: string
}

export type MappingControlRequest = {
  enabled: boolean
  scene_name?: string | null
}

export type MappingControlResponse = {
  success: boolean
  enabled: boolean
  running: boolean
  saving: boolean
  saved: boolean
  scene_name: string | null
  map_dir: string | null
  pid: number | null
  started_at?: number | null
  map_pcd_candidates: string[]
  ground_pcd_candidates: string[]
  pcd_files: Array<{ name: string; path: string; size_bytes: number }>
  origin_waypoint?: NavWaypoint | null
  origin_waypoint_error?: string | null
  message: string | null
}

export type RosbagRecordingResponse = {
  success: boolean
  enabled: boolean
  running: boolean
  pid: number | null
  output_dir: string | null
  log_path: string | null
  started_at: number | null
  lidar_mode: 'mapping' | 'existing' | 'owned' | null
  mapping_active_at_start: boolean
  saved: boolean | null
  message: string
}

export type RadarHealthCheck = {
  name: string
  ok: boolean
  status: 'normal' | 'warning' | 'failed' | string
  message: string
  details: Record<string, unknown>
}

export type RadarHealthResponse = {
  ok: boolean
  level: 'normal' | 'warning' | 'error' | string
  topic: string | null
  topic_type: string | null
  publisher_count: number | null
  subscription_count: number | null
  frequency_hz: number | null
  checked_at: string
  checks: RadarHealthCheck[]
  message: string
}
