export type RobotPose = {
  x: number
  y: number
  z: number
  yaw: number
  frame_id: string
  source: string
  timestamp: number
  ros_timestamp?: number | null
}

export type GlobalPathPoint = {
  x: number
  y: number
  z: number
}

export type GlobalPath = {
  frame_id: string
  points: GlobalPathPoint[]
  timestamp: number
}

export type NavigationStatus = {
  status: string
  target_waypoint_id: string | null
  target_name: string | null
  message: string
  timestamp: number | null
  ros_status?: string | null
  task_id?: string | null
  waypoint_id?: string | null
  distance_to_goal?: number | null
  error_code?: string | null
  source?: string | null
  planning_status?: 'queued' | 'planning' | 'path_ready' | 'failed' | 'rejected' | 'submitted' | null
  planning_generation?: number | null
  planning_elapsed_seconds?: number | null
}

export type LocalizationStatus = {
  status: string
  frame_id: string
  source: string | null
  message: string
  timestamp: number | null
}

export type NavStateResponse = {
  robot_pose: RobotPose | null
  navigation_status: NavigationStatus
  localization_status: LocalizationStatus
  global_path: GlobalPath | null
  execution_path: GlobalPath | null
}

export type MappingCloud = {
  points?: [number, number, number][]
  accumulated_points?: [number, number, number][]
  live_points?: [number, number, number][]
  timestamp: number
}

export type NavWebSocketEvent =
  | { type: 'nav.robot_pose'; data: RobotPose | null; timestamp?: string }
  | { type: 'nav.navigation_status'; data: NavigationStatus; timestamp?: string }
  | { type: 'nav.localization_status'; data: LocalizationStatus; timestamp?: string }
  | { type: 'nav.global_path'; data: GlobalPath | null; timestamp?: string }
  | { type: 'nav.execution_path'; data: GlobalPath | null; timestamp?: string }
  | { type: 'nav.mapping_cloud'; data: MappingCloud; timestamp?: string }
