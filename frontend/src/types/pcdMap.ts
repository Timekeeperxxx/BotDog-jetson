export type PcdBounds = {
  min_x: number
  max_x: number
  min_y: number
  max_y: number
  min_z: number
  max_z: number
}

export type PcdSceneLayerRole = 'ground' | 'wall'

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
  ready: boolean
  navigable: boolean
  message: string | null
}

export type PcdSceneListResponse = {
  root: string
  items: PcdSceneItem[]
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
  }
  bounds: PcdBounds
  supported: boolean
  message: string | null
}

export type PcdSceneLayerPreview = {
  role: PcdSceneLayerRole
  file_name: string
  points: [number, number, number][]
  bounds: PcdBounds
}

export type PcdScenePreview = {
  scene_id: string
  frame_id: string
  layers: {
    ground: PcdSceneLayerPreview | null
    wall: PcdSceneLayerPreview | null
  }
  bounds: PcdBounds
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

export type LocalizationPosePayload = {
  map_id: string
  x: number
  y: number
  yaw: number
  frame_id: 'map'
}

export type LocalizationPose = {
  map_id: string
  x: number
  y: number
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
  scene_name: string | null
  map_dir: string | null
  pid: number | null
  message: string | null
}
