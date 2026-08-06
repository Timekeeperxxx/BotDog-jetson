export type FenceDetectionState =
  | 'disabled'
  | 'finding'
  | 'gimbal_moving'
  | 'detecting'
  | 'not_found'
  | 'out_of_range'
  | 'localization_unavailable'
  | 'calibration_unavailable'

export type FenceBehavior =
  | 'normal'
  | 'approaching'
  | 'dwelling'
  | 'contact'
  | 'climbing_suspected'

export type FenceDetectionStatus = {
  enabled: boolean
  state: FenceDetectionState
  detail: string
  scene_id: string | null
  target_fence_id: string | null
  target_point: { x: number; y: number } | null
  distance_m: number | null
  desired_yaw_deg: number | null
  desired_pitch_deg: number | null
  behavior: FenceBehavior
  behavior_track_id: number | null
  persons: Array<{
    track_id: number
    behavior: FenceBehavior
    duration_seconds: number
  }>
  missing_calibration: string[]
  gimbal_error: string | null
}
