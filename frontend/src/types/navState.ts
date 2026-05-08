export type RobotPose = {
  x: number
  y: number
  z: number
  yaw: number
  frame_id: string
  source: string
  timestamp: number
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
}

export type NavWebSocketEvent =
  | { type: 'nav.robot_pose'; data: RobotPose; timestamp?: string }
  | { type: 'nav.navigation_status'; data: NavigationStatus; timestamp?: string }
  | { type: 'nav.localization_status'; data: LocalizationStatus; timestamp?: string }
  | { type: 'nav.global_path'; data: GlobalPath; timestamp?: string }
