export type PcdBounds = {
  min_x: number
  max_x: number
  min_y: number
  max_y: number
  min_z: number
  max_z: number
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
